"""
Datalastic Maritime API — reusable Python client.

A dependency-light wrapper (only `requests`) over the Datalastic API covering
every endpoint: live tracking, history, area scans, vessel/port reference,
sea routes, SAT-E, the data add-ons, and the async report lifecycle.

Auth:
    Set your key in the environment (recommended, keeps it out of source):
        export DATALASTIC_API_KEY="your-datalastic-key-here"        # macOS/Linux
        setx DATALASTIC_API_KEY "your-datalastic-key-here"          # Windows (new shell)
    Then:  client = Datalastic()
    Or pass explicitly:  client = Datalastic(api_key="...")

The key is sent as the `x-api-key` header (not in the URL), so it never leaks
into server/proxy logs.

Docs: https://docs.datalastic.com/
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a local .env into os.environ (no override).

    Looks for a .env next to this file and in the current working directory.
    Keeps secrets out of source: put DATALASTIC_API_KEY=... in .env (which
    should be git-ignored) instead of hardcoding it.
    """
    for candidate in (Path(__file__).resolve().parent / ".env", Path(".env")):
        try:
            if not candidate.is_file():
                continue
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
        except Exception:
            pass  # never let env loading break the client


_load_dotenv()

V0 = "https://api.datalastic.com/api/v0"
EXT = "https://api.datalastic.com/api/ext"
REPORTS = "https://api.datalastic.com/api/maritime_reports"


class DatalasticError(Exception):
    """Raised for API-level errors (non-2xx, or meta.success == false)."""

    def __init__(self, message: str, status: Optional[int] = None,
                 payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} | payload: {self.payload}" if self.payload else base


def _safe_json(resp) -> Any:
    """Body as JSON, falling back to trimmed text. Never raises — it is only
    ever called while building an error, and must not mask the real failure."""
    try:
        return resp.json()
    except Exception:
        try:
            return (resp.text or "")[:500]
        except Exception:
            return None


def _one_identifier(uuid, mmsi, imo) -> Dict[str, str]:
    """Return exactly one of uuid/mmsi/imo as a params dict, or raise."""
    given = {k: v for k, v in (("uuid", uuid), ("mmsi", mmsi), ("imo", imo))
             if v is not None}
    if len(given) != 1:
        raise ValueError("Supply exactly one of uuid, mmsi, or imo.")
    return {k: str(v) for k, v in given.items()}


class Datalastic:
    def __init__(self, api_key: Optional[str] = None, *,
                 timeout: int = 30, max_retries: int = 5,
                 session: Optional[requests.Session] = None):
        self.api_key = api_key or os.environ.get("DATALASTIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "No API key. Pass api_key=... or set DATALASTIC_API_KEY.")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update({"x-api-key": self.api_key})

    # ---- core request helpers ------------------------------------------

    def _request(self, method: str, url: str, *,
                 params: Optional[dict] = None,
                 json_body: Optional[dict] = None) -> dict:
        """Send a request with 429/5xx backoff. Returns parsed JSON dict."""
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.request(
                    method, url, params=params, json=json_body,
                    timeout=self.timeout)
            except requests.exceptions.RequestException as e:
                if attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise DatalasticError(
                    f"network error after {self.max_retries} retries: {e}") from e

            if resp.status_code == 429:  # rate limit: back off and retry
                if attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise DatalasticError("429 rate limit — retries exhausted",
                                      status=429, payload=resp.text)
            if resp.status_code >= 500:  # transient server error
                if attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise DatalasticError(f"{resp.status_code} server error",
                                      status=resp.status_code,
                                      payload=resp.text)
            if resp.status_code == 402:
                raise DatalasticError(
                    "402 Payment Required — credits exhausted or plan expired.",
                    status=402, payload=_safe_json(resp))
            if resp.status_code == 401:
                raise DatalasticError("401 Unauthorized — invalid API key.",
                                      status=401, payload=_safe_json(resp))
            if resp.status_code == 404:
                return _safe_json(resp) or {"data": None,
                                            "meta": {"success": False,
                                                     "http_status": 404}}
            if resp.status_code == 400:
                raise DatalasticError("400 Bad Request — check parameters.",
                                      status=400, payload=_safe_json(resp))
            resp.raise_for_status()

            data = resp.json()
            if isinstance(data, dict) and data.get("meta", {}).get(
                    "success") is False:
                raise DatalasticError("API returned meta.success = false",
                                      status=resp.status_code, payload=data)
            return data

    def _get(self, base: str, path: str, params: dict) -> dict:
        return self._request("GET", f"{base}/{path}", params=params)

    # ---- account --------------------------------------------------------

    def stat(self) -> dict:
        """Key status + credit usage. Free."""
        return self._get(V0, "stat", {})["data"]

    # ---- live tracking -------------------------------------------------

    def vessel(self, *, uuid=None, mmsi=None, imo=None) -> dict:
        """Real-time position, basic AIS fields. 1 credit."""
        return self._get(V0, "vessel", _one_identifier(uuid, mmsi, imo))["data"]

    def vessel_pro(self, *, uuid=None, mmsi=None, imo=None) -> dict:
        """Real-time + ETA/ATD/draft/ports. 3 credits."""
        return self._get(V0, "vessel_pro",
                         _one_identifier(uuid, mmsi, imo))["data"]

    def vessel_bulk(self, *, mmsi: Optional[List[str]] = None,
                    imo: Optional[List[str]] = None,
                    uuid: Optional[List[str]] = None) -> dict:
        """Up to 100 vessels in one call. 1 credit per vessel found."""
        params: List[tuple] = []
        for key, vals in (("mmsi", mmsi), ("imo", imo), ("uuid", uuid)):
            for v in (vals or []):
                params.append((key, str(v)))
        if not params:
            raise ValueError("Provide at least one mmsi/imo/uuid list.")
        if len(params) > 100:
            raise ValueError("vessel_bulk accepts at most 100 vessels.")
        return self._request("GET", f"{V0}/vessel_bulk", params=params)["data"]

    def vessel_pro_est(self, *, uuid=None, mmsi=None, imo=None) -> dict:
        """SAT-E estimated position when out of AIS range (add-on, ext/)."""
        return self._get(EXT, "vessel_pro_est",
                         _one_identifier(uuid, mmsi, imo))["data"]

    # ---- area / location traffic ---------------------------------------

    def vessel_inradius(self, *, radius: float,
                        lat: Optional[float] = None,
                        lon: Optional[float] = None,
                        port_uuid: Optional[str] = None,
                        port_unlocode: Optional[str] = None,
                        uuid: Optional[str] = None,
                        mmsi: Optional[str] = None,
                        imo: Optional[str] = None,
                        type: Optional[str] = None,
                        type_specific: Optional[str] = None,
                        exclude: Optional[str] = None,
                        nav_status: Optional[int] = None,
                        next: Optional[str] = None) -> dict:
        """
        Vessels currently within `radius` NM (max 50) of a center. Give one
        center: lat+lon, OR port_uuid/port_unlocode, OR a vessel identifier.
        1 credit per vessel found (max 500).
        """
        if radius > 50:
            raise ValueError("radius max is 50 nautical miles.")
        params: Dict[str, Any] = {"radius": radius}
        centers = [lat is not None and lon is not None, bool(port_uuid),
                   bool(port_unlocode), bool(uuid), bool(mmsi), bool(imo)]
        if sum(bool(c) for c in centers) != 1:
            raise ValueError(
                "Give exactly one center: lat+lon, port_uuid, port_unlocode, "
                "uuid, mmsi, or imo.")
        for k, v in (("lat", lat), ("lon", lon), ("port_uuid", port_uuid),
                     ("port_unlocode", port_unlocode), ("uuid", uuid),
                     ("mmsi", mmsi), ("imo", imo), ("type", type),
                     ("type_specific", type_specific), ("exclude", exclude),
                     ("nav_status", nav_status), ("next", next)):
            if v is not None:
                params[k] = v
        return self._get(V0, "vessel_inradius", params)["data"]

    def vessel_inradius_all(self, **kwargs) -> List[dict]:
        """Auto-paginate vessel_inradius across all `next` pages."""
        out: List[dict] = []
        data = self.vessel_inradius(**kwargs)
        while True:
            vessels = data.get("vessels") or data.get("points") or []
            out.extend(vessels)
            token = data.get("next")
            if not token:
                return out
            kwargs["next"] = token
            data = self.vessel_inradius(**kwargs)

    # ---- history -------------------------------------------------------

    def vessel_history(self, *, uuid=None, mmsi=None, imo=None,
                       days: Optional[int] = None,
                       from_: Optional[str] = None,
                       to: Optional[str] = None) -> dict:
        """
        Past track for one vessel (data since 2021-08-10). Use `days` OR
        from_/to (YYYY-MM-DD, span <= 30 days). 2 credits per day.
        """
        params = _one_identifier(uuid, mmsi, imo)
        if days is not None:
            params["days"] = days
        if from_ is not None:
            params["from"] = from_
        if to is not None:
            params["to"] = to
        if "days" not in params and "from" not in params:
            raise ValueError("Provide `days` or `from_`/`to`.")
        return self._get(V0, "vessel_history", params)["data"]

    # ---- reference / search --------------------------------------------

    def vessel_info(self, *, uuid=None, mmsi=None, imo=None) -> dict:
        """Static vessel specs. 1 credit."""
        return self._get(V0, "vessel_info",
                         _one_identifier(uuid, mmsi, imo))["data"]

    def vessel_find(self, **filters) -> dict:
        """
        Search the fleet by filters (name, fuzzy, type, type_specific,
        country_iso, gross_tonnage_min/max, deadweight_min/max,
        length_min/max, breadth_min/max, year_built_min/max, next).
        1 credit per vessel found (max 500). Use vessel_find_all to paginate.
        """
        params = {k: v for k, v in filters.items() if v is not None}
        return self._get(V0, "vessel_find", params)["data"]

    def vessel_find_all(self, **filters) -> List[dict]:
        out: List[dict] = []
        data = self.vessel_find(**filters)
        while True:
            out.extend(data.get("vessels", []))
            token = data.get("next")
            if not token:
                return out
            filters["next"] = token
            data = self.vessel_find(**filters)

    # ---- ports ---------------------------------------------------------

    def port_find(self, **filters) -> dict:
        """Search ports (name, uuid, fuzzy, port_type, country_iso, unlocode,
        lat/lon/radius). 1 credit per port found."""
        params = {k: v for k, v in filters.items() if v is not None}
        return self._get(V0, "port_find", params)["data"]

    def port(self, *, uuid: Optional[str] = None,
             unlocode: Optional[str] = None) -> dict:
        """Port detail incl. terminals[]. Give uuid OR unlocode. 1 credit."""
        if bool(uuid) == bool(unlocode):
            raise ValueError("Provide exactly one of uuid or unlocode.")
        params = {"uuid": uuid} if uuid else {"unlocode": unlocode}
        return self._get(V0, "port", params)["data"]


    # ---- sea routes (add-on, ext/) ------------------------------------

    def route(self, *, lat_from=None, lon_from=None, port_uuid_from=None,
              port_unlocode_from=None, lat_to=None, lon_to=None,
              port_uuid_to=None, port_unlocode_to=None) -> dict:
        """Sea route + distance (NM) between two points/ports. 1 credit.
        NOT for navigation - distance/logistics estimation only."""
        params = {k: v for k, v in dict(
            lat_from=lat_from, lon_from=lon_from, port_uuid_from=port_uuid_from,
            port_unlocode_from=port_unlocode_from, lat_to=lat_to, lon_to=lon_to,
            port_uuid_to=port_uuid_to, port_unlocode_to=port_unlocode_to,
        ).items() if v is not None}
        return self._get(EXT, "route", params)["data"]

    # ---- data add-ons (maritime_reports/, single-vessel) ---------------

    def _addon(self, path: str, **filters) -> dict:
        params = {k: v for k, v in filters.items() if v is not None}
        return self._get(REPORTS, path, params)["data"]

    def dry_dock_dates(self, *, imo=None, name=None,
                       dry_dock_from=None, dry_dock_to=None) -> dict:
        return self._addon("dry_dock_dates", imo=imo, name=name,
                           dry_dock_from=dry_dock_from, dry_dock_to=dry_dock_to)

    def casualty(self, *, imo=None, name=None, from_=None, to=None) -> dict:
        p = {"imo": imo, "name": name, "from": from_, "to": to}
        return self._addon("casualty", **p)

    def inspections(self, *, imo=None, name=None, from_=None, to=None) -> dict:
        p = {"imo": imo, "name": name, "from": from_, "to": to}
        return self._addon("inspections", **p)

    def sales_demolitions(self, *, imo=None, name=None,
                          from_=None, to=None) -> dict:
        p = {"imo": imo, "name": name, "from": from_, "to": to}
        return self._addon("spd", **p)

    def ownership(self, *, imo=None, name=None, beneficial_owner=None,
                  operator=None, technical_manager=None,
                  commercial_manager=None, updated_from=None) -> dict:
        return self._addon("ownership", imo=imo, name=name,
                           beneficial_owner=beneficial_owner, operator=operator,
                           technical_manager=technical_manager,
                           commercial_manager=commercial_manager,
                           updated_from=updated_from)

    def class_society(self, *, imo=None, name=None, fuzzy=None,
                      beneficial_owner=None, beneficial_owner_imo=None,
                      technical_manager=None, technical_manager_imo=None,
                      updated_from=None) -> dict:
        return self._addon("class_society", imo=imo, name=name, fuzzy=fuzzy,
                           beneficial_owner=beneficial_owner,
                           beneficial_owner_imo=beneficial_owner_imo,
                           technical_manager=technical_manager,
                           technical_manager_imo=technical_manager_imo,
                           updated_from=updated_from)

    def engine(self, *, imo=None, name=None, fuzzy=None,
               updated_from=None) -> dict:
        return self._addon("engine", imo=imo, name=name, fuzzy=fuzzy,
                           updated_from=updated_from)

    def companies(self, *, company_imo=None, name=None,
                  updated_from=None) -> dict:
        return self._addon("companies", company_imo=company_imo, name=name,
                           updated_from=updated_from)

    # ---- async reports -------------------------------------------------

    def submit_report(self, report_type: str, **params) -> dict:
        """POST a report job. Returns data incl. report_id and status."""
        body = {"api-key": self.api_key, "report_type": report_type}
        body.update({k: v for k, v in params.items() if v is not None})
        return self._request("POST", f"{V0}/report", json_body=body)["data"]

    def report_status(self, report_id: str) -> dict:
        """GET status/result for a report id (or '_all' to list all)."""
        return self._get(V0, "report", {"report_id": report_id})["data"]

    def wait_for_report(self, report_id: str, *, poll_seconds: int = 10,
                        timeout_seconds: int = 1800) -> dict:
        """Poll until status is _DONE_; return the final data (has result_url)."""
        deadline = time.time() + timeout_seconds
        waited = 0
        while time.time() < deadline:
            data = self.report_status(report_id)
            status = data.get("status")
            if status == "_DONE_":
                if waited:
                    # \r + padding clears the in-place progress line first
                    print(f"\r    ...report ready ({waited}s)" + " " * 12,
                          flush=True)
                return data
            if status not in ("_PENDING_", "_IN_PROGRESS_"):
                raise DatalasticError(f"Unexpected report status: {status}",
                                      payload=data)
            waited += poll_seconds
            print(f"    ...building report ({waited}s)", end="\r", flush=True)
            time.sleep(poll_seconds)
        raise DatalasticError("Report polling timed out.",
                              payload={"report_id": report_id})

    def download_report(self, result_url: str, dest_path: str) -> str:
        """Download a finished report ZIP to dest_path. Returns dest_path."""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")

        attempt = 0
        while True:
            attempt += 1
            # result_url is a pre-signed storage link - fetch it bare, without
            # the session's x-api-key header, and give it a generous timeout
            # since report ZIPs are much larger than JSON responses.
            try:
                resp = requests.get(result_url, stream=True,
                                    timeout=(self.timeout, 300))
            except requests.exceptions.RequestException as e:
                if attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise DatalasticError(
                    f"network error downloading report: {e}") from e
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.close()
                if attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise DatalasticError(
                    f"{resp.status_code} downloading report - retries exhausted",
                    status=resp.status_code)
            if resp.status_code != 200:
                raise DatalasticError(f"{resp.status_code} downloading report",
                                      status=resp.status_code,
                                      payload=resp.text[:500])
            try:
                with resp, open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
            except requests.exceptions.RequestException as e:
                # Connection dropped mid-stream; .part is discarded on retry.
                if attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise DatalasticError(
                    f"network error mid-download: {e}") from e
            break

        # Guard the cache: a partial write or an error page must never land at
        # dest_path, because callers treat "file exists" as "window done".
        with open(part, "rb") as fh:
            magic = fh.read(2)
        if magic != b"PK":
            head = part.read_bytes()[:500]
            part.unlink(missing_ok=True)
            raise DatalasticError("Report download is not a ZIP.",
                                  payload=head)

        part.replace(dest)
        return str(dest)

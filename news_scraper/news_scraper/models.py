"""The Article data model plus normalization helpers (slugs, IDs, buckets)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Article:
    """A single article as harvested from a feed.

    Only feed-provided metadata is stored — never paywalled body text.
    """

    id: str                      # stable hash of guid/link
    source_id: str               # e.g. "wsj"
    source_name: str             # e.g. "The Wall Street Journal"
    section: str                 # feed section, e.g. "markets"
    title: str
    url: str
    summary: str = ""
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    published: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ---- derived helpers -------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.astimezone(timezone.utc).isoformat()
        d["fetched_at"] = self.fetched_at.astimezone(timezone.utc).isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Article":
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            source_name=d["source_name"],
            section=d.get("section", ""),
            title=d.get("title", ""),
            url=d.get("url", ""),
            summary=d.get("summary", ""),
            authors=list(d.get("authors", [])),
            tags=list(d.get("tags", [])),
            published=_parse_iso(d["published"]),
            fetched_at=_parse_iso(d["fetched_at"]),
        )

    def slug(self) -> str:
        base = slugify(self.title) or self.id[:10]
        date = self.published.astimezone(timezone.utc).strftime("%Y-%m-%d")
        return f"{date}-{base}"[:120]

    def bucket(self, week_scheme: str = "month") -> tuple[str, str, str]:
        """Return (year, month, week) folder labels for this article."""
        return date_bucket(self.published, week_scheme)


# ---------------------------------------------------------------------------
# free functions (also used directly by tests)
# ---------------------------------------------------------------------------

def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def make_id(source_id: str, guid: str) -> str:
    """A stable, source-scoped id from a feed guid/link."""
    h = hashlib.sha1(f"{source_id}\n{guid}".encode("utf-8")).hexdigest()
    return f"{source_id}-{h[:16]}"


def slugify(text: str) -> str:
    """ASCII, url-safe slug. Returns '' when text has no latin content
    (e.g. Arabic-only titles) — callers fall back to the article id."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def date_bucket(dt: datetime, week_scheme: str = "month") -> tuple[str, str, str]:
    """Map a datetime to (year, month, week) folder labels.

    year  -> "2026"
    month -> "07-Jul"
    week  -> "W3"   (month scheme: week-of-month 1..5)
             "W30"  (iso scheme:   ISO week-of-year 1..53)
    """
    dt = dt.astimezone(timezone.utc)
    year = f"{dt.year:04d}"
    month = f"{dt.month:02d}-{dt.strftime('%b')}"
    if week_scheme == "iso":
        week = f"W{dt.isocalendar().week:02d}"
    else:  # month scheme: week-of-month
        week = f"W{(dt.day - 1) // 7 + 1}"
    return year, month, week

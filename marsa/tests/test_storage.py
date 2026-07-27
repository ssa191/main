import os
import tempfile

from marsa import storage


def _call(uuid="u1", arrival="2026-01-05 10:00", port="Dammam", days=5.0,
          grain="Unknown"):
    return {
        "uuid": uuid, "port": port, "vessel_name": "TEST VESSEL",
        "mmsi": "123456789", "imo": "9525338", "type_specific": "Bulk Carrier",
        "size_class": "Panamax/Kamsarmax", "dwt": "82000",
        "gross_tonnage": "44000", "length_m": "229", "breadth_m": "32.26",
        "year_built": "2019", "arrival_utc": arrival,
        "departure_utc": "2026-01-10 12:00", "days_in_port": days,
        "arrived_anchored": "Yes", "grain_flag": grain,
        "grain_confidence": "Low", "_min_dist_nm": 4.1,
    }


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # let sqlite create it fresh
    return path


def test_upsert_is_idempotent_on_key():
    path = _tmp_db()
    try:
        conn = storage.connect(path)
        storage.upsert_calls(conn, [_call(days=5.0)])
        # same (uuid, arrival_date) again with a changed value -> update, not dup
        storage.upsert_calls(conn, [_call(days=9.9)])
        rows = conn.execute("SELECT days_in_port FROM port_calls").fetchall()
        assert len(rows) == 1
        assert rows[0]["days_in_port"] == 9.9
    finally:
        os.unlink(path)


def test_different_arrival_dates_are_distinct_calls():
    path = _tmp_db()
    try:
        conn = storage.connect(path)
        storage.upsert_calls(conn, [
            _call(arrival="2026-01-05 10:00"),
            _call(arrival="2026-03-20 08:00"),  # same hull, later call
        ])
        n = conn.execute("SELECT COUNT(*) FROM port_calls").fetchone()[0]
        assert n == 2
    finally:
        os.unlink(path)


def test_latest_arrival_date():
    path = _tmp_db()
    try:
        conn = storage.connect(path)
        storage.upsert_calls(conn, [
            _call(arrival="2026-01-05 10:00"),
            _call(arrival="2026-03-20 08:00"),
        ])
        assert storage.latest_arrival_date(conn) == "2026-03-20"
    finally:
        os.unlink(path)


def test_export_csv_roundtrip():
    path = _tmp_db()
    try:
        conn = storage.connect(path)
        storage.upsert_calls(conn, [_call()])
        out = path + ".csv"
        n = storage.export_csv(conn, out)
        assert n == 1
        text = open(out).read()
        assert "TEST VESSEL" in text
        assert "_min_dist_nm" in text.splitlines()[0]  # header uses CSV key
        os.unlink(out)
    finally:
        os.unlink(path)


def test_record_draught_idempotent():
    path = _tmp_db()
    try:
        conn = storage.connect(path)
        snap = {"uuid": "u1", "captured_at": "2026-07-27T09:00:00Z",
                "port_key": "dammam", "draught_m": 13.2, "source": "vessel_pro"}
        storage.record_draught(conn, snap)
        storage.record_draught(conn, snap)  # same PK -> ignored
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM draught_snapshots").fetchone()[0]
        assert n == 1
    finally:
        os.unlink(path)

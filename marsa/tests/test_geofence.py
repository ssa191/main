from marsa.geofence import haversine_nm, nearest_berth, infer_grain


def test_haversine_zero():
    assert haversine_nm(21.4, 39.1, 21.4, 39.1) == 0


def test_haversine_known_distance():
    # ~1 degree of latitude ~= 60 NM.
    d = haversine_nm(21.0, 39.0, 22.0, 39.0)
    assert 59 < d < 61


def test_infer_grain_no_geofence_is_unknown():
    port = {"grain_berths": []}
    flag, conf = infer_grain(port, [(21.48, 39.14)])
    assert flag.startswith("Unknown")
    assert conf == "Low"


def test_infer_grain_hit_high_confidence():
    berth = {"name": "silo", "lat": 21.500, "lon": 39.170, "radius_nm": 0.8}
    port = {"grain_berths": [berth]}
    # a position essentially on the berth -> Grain, High confidence
    flag, conf = infer_grain(port, [(21.500, 39.170), (21.600, 39.300)])
    assert flag == "Grain (est.)"
    assert conf == "High"


def test_infer_grain_miss_is_non_grain():
    berth = {"name": "silo", "lat": 21.500, "lon": 39.170, "radius_nm": 0.5}
    port = {"grain_berths": [berth]}
    # a position ~6 NM away from the only grain berth -> Non-grain
    flag, conf = infer_grain(port, [(21.40, 39.14)])
    assert flag == "Non-grain (est.)"


def test_nearest_berth_empty():
    assert nearest_berth(21.0, 39.0, []) == (None, None)

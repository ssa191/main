from marsa.tpc import tpc, tonnage_from_draught, laden_state


def test_tpc_panamax_ballpark():
    # A Kamsarmax ~229 x 32.26 m at C_wp=0.84: TPC ~= 63-64 t/cm.
    t = tpc(229.0, 32.26)
    assert 55 < t < 72


def test_tpc_bad_dims_returns_none():
    assert tpc(0, 32) is None
    assert tpc("n/a", None) is None


def test_tonnage_sign_and_scale():
    # 5 m deeper on arrival than departure => a discharge => positive tonnes,
    # and for a Kamsarmax that is many tens of thousands of tonnes.
    t = tonnage_from_draught(5.0, 229.0, 32.26)
    assert t > 30000
    # loading (ballast arrival) flips the sign.
    assert tonnage_from_draught(-5.0, 229.0, 32.26) < 0


def test_tonnage_missing_dims_none():
    assert tonnage_from_draught(5.0, None, 32) is None


def test_laden_state_labels():
    assert laden_state(13.5, 7.0).startswith("discharge")
    assert laden_state(7.0, 13.5).startswith("loading")
    assert laden_state(13.5, 13.4) == "no significant cargo change"
    assert laden_state(None, 7.0) == "unknown"

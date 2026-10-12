from sckg import analytics as A


def _event(b, etype):
    return next(e for e in b.kg.nodes_of("Event") if b.kg.g.nodes[e]["event_type"] == etype)


def test_sub_tier_exposure_found_only_in_documents(b):
    r = A.event_impact(b.kg, _event(b, "earthquake"))
    assert "S11" in r["sub_tier_only"] and r["revenue_at_risk_musd"] == 460.0


def test_inventory_buffers_short_disruptions(b):
    r = A.event_impact(b.kg, _event(b, "typhoon"))
    assert r["tier1_affected"] and r["revenue_at_risk_musd"] == 0.0


def test_false_dual_sourcing_detected(b):
    rows = {r["name"]: r for r in A.hidden_concentration(b.kg)}
    assert rows["Kunlun Lithium Materials"]["false_dual_sourcing"] == ["P-1001"]


def test_sanctions_exposure_through_subsidiary(b):
    rows = A.sanctions_exposure(b.kg)
    assert {r["tier1_supplier"] for r in rows} == {"S08", "S10"} and rows[0]["sanctions_entry"] == "SL-0417"


def test_every_document_edge_has_provenance(b):
    for u, v, k, d in b.kg.g.edges(keys=True, data=True):
        assert d["provenance"], (u, v, k)

from fastapi.testclient import TestClient

from sckg.api import app

c = TestClient(app)
H = {"X-API-Key": "test-key"}


def test_auth_and_health():
    assert c.get("/health").status_code == 200
    assert c.post("/v1/ask", json={"question": "Which parts are single-sourced?"}).status_code == 401


def test_ask_and_events():
    r = c.post("/v1/ask", headers=H, json={"question": "Are we exposed to any sanctioned companies?"}).json()
    assert r["intent"] == "sanctions" and "Altai" in r["answer"]
    ev = c.get("/v1/events", headers=H).json()
    assert len(ev) == 6 and max(e["revenue_at_risk_musd"] for e in ev) == 1150.0
    detail = c.get(f"/v1/events/{ev[0]['event_id']}", headers=H).json()
    assert "products" in detail and "explanations" in detail


def test_resolve_endpoint():
    top = c.get("/v1/resolve", params={"name": "VCS"}, headers=H).json()[0]
    assert top["entity_id"] == "S01"

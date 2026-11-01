import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db, get_llm
from app.main import app
from tests.conftest import FakeLLM

H = {"X-API-Key": "test-key"}


@pytest.fixture
def client(session_factory):
    def _db():
        s = session_factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_llm] = lambda: FakeLLM(error="llm_disabled")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_is_public_everything_else_needs_key(client):
    assert client.get("/health").status_code == 200
    assert client.get("/watchlists").status_code == 401
    assert client.get("/watchlists", headers={"X-API-Key": "wrong"}).status_code == 401


def test_end_to_end_flow(client):
    run = client.post("/screening/runs", json={"as_of_date": "2026-10-24", "enqueue_top_n": 2}, headers=H)
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    assert run.json()["summary"]["enqueued_for_research"] == 2

    detail = client.get(f"/screening/runs/{run_id}", params={"result_status": "candidate"}, headers=H).json()
    assert detail["results"][0]["rank"] == 1 and all(r["status"] == "candidate" for r in detail["results"])

    wl = client.post("/watchlists", json={"name": "core"}, headers=H).json()
    assert client.post("/watchlists", json={"name": "core"}, headers=H).status_code == 409
    body = {
        "symbol": "smplalpha",
        "thesis": "Capital-efficient machinery maker",
        "invalidation_conditions": [{"metric": "roce_latest", "op": "<", "value": 0.9, "description": "test trigger"}],
        "valuation_range": {"metric": "pe", "low": 1, "high": 500, "assumptions": "wide test band"},
    }
    put = client.put(f"/watchlists/{wl['id']}/companies", json=body, headers=H)
    assert put.status_code == 200, put.text and put.json()["symbol"] == "SMPLALPHA"
    bad = {**body, "valuation_range": {"metric": "pe", "low": 1, "high": 2, "assumptions": ""}}
    assert client.put(f"/watchlists/{wl['id']}/companies", json=bad, headers=H).status_code == 422
    assert client.put(f"/watchlists/{wl['id']}/companies", json={"symbol": "SMPLNIFTYETF"}, headers=H).status_code == 409

    rep = client.post("/research", json={"query": "SMPLALPHA", "as_of_date": "2026-10-24"}, headers=H)
    assert rep.status_code == 201, rep.text
    report = rep.json()
    assert report["report"]["disclaimer"] and report["status"] == "partial"
    assert client.get(f"/research/reports/{report['id']}", headers=H).json()["id"] == report["id"]
    assert client.get("/research/reports", params={"symbol": "SMPLALPHA"}, headers=H).json()[0]["id"] == report["id"]
    assert client.post("/research", json={"query": "NOSUCH"}, headers=H).status_code == 422

    alerts = client.get("/alerts", params={"symbol": "SMPLALPHA"}, headers=H).json()
    rules = {a["rule_id"] for a in alerts}
    assert {"thesis_review", "valuation_watch"} <= rules
    assert all(a["delivery_status"] == "sent" for a in alerts)  # log channel delivers synchronously

    mon = client.post("/alerts/monitor", params={"as_of_date": "2026-10-24"}, headers=H).json()
    assert mon["companies_checked"] == 1 and mon["errors"] == [] and mon["alerts_created"] == 0  # deduped

    wl_out = client.get(f"/watchlists/{wl['id']}", headers=H).json()
    assert wl_out["companies"][0]["needs_review"] is True

    q = client.post("/research/queue/process", params={"limit": 1, "as_of_date": "2026-10-24"}, headers=H).json()
    assert q["processed"] == 1 and q["succeeded"] == 1
    short = client.get("/research/shortlist", headers=H)
    assert short.status_code == 200
    for item in short.json():
        assert item["conclusion"] != "high_risk" and set(item["ratings"]) >= {"business_quality", "valuation"}
    assert client.post("/research/queue/SMPLBETA", headers=H).status_code == 202

    assert client.delete(f"/watchlists/{wl['id']}/companies/SMPLALPHA", headers=H).status_code == 204
    assert client.delete(f"/watchlists/{wl['id']}/companies/SMPLALPHA", headers=H).status_code == 404


def test_ui_is_served_without_key_and_root_redirects(client):
    page = client.get("/ui/")
    assert page.status_code == 200 and "Investment Agent" in page.text
    assert client.get("/ui/app.js").status_code == 200
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == "/ui/"

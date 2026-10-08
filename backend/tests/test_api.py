import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Set NODERZE_TEST_RESUME to run the flow on your own resume; otherwise a fictional sample is generated.
_OWN = os.environ.get("NODERZE_TEST_RESUME")


@pytest.fixture(scope="module")
def resume_docx(tmp_path_factory) -> Path:
    if _OWN and Path(_OWN).exists():
        return Path(_OWN)
    from tests.sample_resume import build
    return build(tmp_path_factory.mktemp("resume") / "sample_resume.docx")


@pytest.fixture(scope="module")
def client():
    from app.db import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    import scripts.seed_db as seed_db
    db = SessionLocal()
    seed_db.seed(db)
    db.close()
    from app.main import app
    with TestClient(app) as c:
        c.headers["X-Agent-Token"] = "test-token"
        yield c


def test_auth_required(client):
    assert TestClient(client.app).get("/api/dashboard").status_code == 401


def test_dashboard_and_lists(client):
    d = client.get("/api/dashboard").json()
    assert d["stats"]["programs"] >= 10
    jobs = client.get("/api/jobs").json()
    assert jobs and all("score_breakdown" in j for j in jobs)
    assert client.get("/api/programs").json()


def test_company_and_report(client):
    v = next(c for c in client.get("/api/companies").json() if c["name"] == "Verkada")
    page = client.get(f"/api/companies/{v['id']}").json()
    assert page["programs"] and page["standout"]
    job = client.get("/api/jobs", params={"company_id": v["id"]}).json()[0]
    rep = client.get(f"/api/jobs/{job['id']}/report").json()
    assert "Compensation" in rep["sections"] and rep["confidence"]["facts"] > 0


def test_resume_prepare_and_approval_flow(client, resume_docx):
    with resume_docx.open("rb") as fh:
        r = client.post("/api/resume/upload", files={"file": ("resume.docx", fh)}).json()
    kinds = {c["kind"] for c in r["checks"]}
    assert {"graduation_date", "overclaim", "typo"} <= kinds
    job = client.get("/api/jobs").json()[0]
    from app.workflows import WORKFLOWS, run_sync
    run = run_sync("prepare_application", None, WORKFLOWS["prepare_application"], job_id=job["id"])
    assert run.status == "done", run.error
    app_id = run.result["application_id"]
    page = client.get(f"/api/applications/{app_id}").json()
    assert page["docs"] and page["application"]["readiness"]["checklist"]
    v = page["resume_version"]
    fix = next(e for e in v["edits"] if e["category"] == "fix")
    client.post(f"/api/resume/versions/{v['id']}/edits/{fix['id']}", json={"decision": "approve"})
    out = client.post(f"/api/resume/versions/{v['id']}/render").json()
    assert out["status"] == "rendered"
    # submission requires filled drafts, then an approval; nothing is sent without it
    resp = client.post(f"/api/applications/{app_id}/request", json={"action": "submit_application"})
    assert resp.status_code in (200, 409)


def test_one_click_apply_and_board(client, resume_docx):
    board = client.get("/api/company-board").json()
    assert board and all(c["category"] == "cybersecurity" for c in board)
    varonis = next(c for c in board if c["name"] == "Varonis")
    assert varonis["presence"]["az"] and varonis["entry_count"] >= 1
    jid = varonis["entry_roles"][0]["id"]
    r = client.post(f"/api/apply/{jid}").json()
    assert r["ats"]["after"] >= r["ats"]["before"] and r["drafts"]["recruiter_connect"] and r["links"]
    assert all(not e["flags"] for e in r["edits"] if e["status"] == "approved")  # nothing flagged is pre-approved
    missing = [t["term"] for t in r["ats"]["terms"] if t["status"] == "missing"]
    if missing:
        client.post("/api/profile/claims", json={"term": missing[0], "have": True})
        r2 = client.post(f"/api/apply/{jid}").json()
        assert next(t for t in r2["ats"]["terms"] if t["term"] == missing[0])["status"] != "missing"
        client.post("/api/profile/claims", json={"term": missing[0], "have": False})
    u = client.get("/api/updates", params={"since": "2020-01-01T00:00:00"}).json()
    assert u["new_jobs"] > 0

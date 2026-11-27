"""Internship outreach: batches dropped by the weekday task, statuses, replies and the state file."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from app.db import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        for t in ("prospects", "email_replies", "question_answers"):
            c.exec_driver_sql(f"DROP TABLE IF EXISTS {t}")
    Base.metadata.create_all(engine)
    import scripts.seed_db as seed_db
    db = SessionLocal()
    seed_db.seed(db)
    db.close()
    from app.main import app
    with TestClient(app) as c:
        c.headers["X-Agent-Token"] = "test-token"
        yield c


BATCH = {"batch": "2026-11-27", "prospects": [
    {"company": "Desert Grid Analytics", "email": "Internships@desertgrid.com", "name": None, "title": "Campus recruiting",
     "track": "data", "why": "Phoenix data team", "subject": "Spring 2027 internship inquiry", "body": "Hello...",
     "draft_id": "r-1", "draft_url": "https://mail.google.com/mail/u/0/#drafts?compose=abc"},
    {"company": "Copper Secure", "linkedin_url": "https://www.linkedin.com/in/Jane-Recruiter/?trk=x", "name": "Jane Recruiter",
     "title": "Technical Recruiter", "track": "cyber", "note": "Hi Jane, " + "x" * 250, "followup": "Thanks for connecting"},
    {"company": "No Contact Inc"},
]}


def test_batch_import_and_state(client, tmp_path):
    from app.db import SessionLocal
    from app.services import outreach as O
    folder = tmp_path / "outreach"
    folder.mkdir()
    (folder / "outreach-20261127.json").write_text(json.dumps(BATCH))
    db = SessionLocal()
    assert O.import_dropped(db, folder) == 2
    # The same people again are not added twice
    (folder / "again.json").write_text(json.dumps(BATCH))
    assert O.import_dropped(db, folder) == 0
    data = client.get("/api/prospects").json()
    by = {p["company"]: p for p in data["items"]}
    assert by["Desert Grid Analytics"]["status"] == "drafted" and by["Desert Grid Analytics"]["email"] == "internships@desertgrid.com"
    li = by["Copper Secure"]
    assert li["channel"] == "linkedin" and li["status"] == "ready" and len(li["note"]) <= 200
    assert li["linkedin_url"] == "https://www.linkedin.com/in/jane-recruiter"
    assert data["counts"]["to_send"] == 2 and data["searches"][0]["linkedin_hour"].endswith("f_TPR=r3600")
    state = json.loads(O.write_state(db).read_text())
    assert {c["company"] for c in state["contacts"]} == {"Desert Grid Analytics", "Copper Secure"}
    db.close()


def test_status_updates_and_reply_tracking(client, tmp_path):
    from app.db import SessionLocal
    from app.models import Prospect
    from app.services import outreach as O
    from app.services import replies as R
    db = SessionLocal()
    p = db.query(Prospect).filter_by(company_name="Desert Grid Analytics").one()
    # The weekday task saw the draft sent
    assert O.apply_updates(db, [{"draft_id": "r-1", "status": "sent", "at": "2026-11-30T16:00:00Z"}]) == 1
    db.commit()
    assert p.status == "sent" and p.sent_at is not None
    # Their company is now watched for replies, and an answer marks the contact replied
    assert any(w.get("prospect") and "desertgrid.com" in w["domains"] for w in R.watch_list(db))
    added = R.import_items(db, [{"id": "rep-1", "from": "Maria Lopez <mlopez@desertgrid.com>",
                                 "subject": "Re: Spring 2027 internship inquiry",
                                 "snippet": "Thanks for reaching out about an internship. Do you have time for a call next week?"}])
    db.commit()
    assert len(added) == 1 and added[0].company_id == p.company_id
    db.refresh(p)
    assert p.status == "replied" and p.reply_id == added[0].id
    assert R.needs_you(db, added[0])
    db.close()


def test_patch_status(client):
    items = client.get("/api/prospects").json()["items"]
    li = next(p for p in items if p["channel"] == "linkedin")
    assert client.patch(f"/api/prospects/{li['id']}", json={"status": "sent"}).json()["status"] == "sent"
    assert client.patch(f"/api/prospects/{li['id']}", json={"status": "nope"}).status_code == 400
    assert client.get("/api/updates").json()["outreach_to_send"] == 0

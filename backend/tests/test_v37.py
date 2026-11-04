"""Applications only after you start applying, Remove, pasted questions, and email replies."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from app.db import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    import scripts.seed_db as seed_db
    db = SessionLocal()
    seed_db.seed(db)
    db.close()
    from app.main import app
    from tests.sample_resume import build
    with TestClient(app) as c:
        c.headers["X-Agent-Token"] = "test-token"
        path = build(tmp_path_factory.mktemp("r") / "r.docx")
        with open(path, "rb") as fh:
            assert c.post("/api/resume/upload", files={"file": ("r.docx", fh)}).status_code == 200
        yield c


def _job(client, **kw):
    body = {"company_name": "Desert Cyber Co", "title": "Cybersecurity Intern", "location": "Tempe, AZ",
            "description": ("Paid internship at $20 per hour, 15-20 hours per week during the spring 2027 semester. "
                            "Our culture of curiosity, teamwork and service guides everything. Triage SIEM alerts "
                            "and document incidents with the SOC team. ") * 2} | kw
    return client.post("/api/internships", json=body).json()


def _board(client):
    b = client.get("/api/applications").json()
    saved = next(g for g in b["groups"] if g["key"] == "saved")["stages"]
    return b, [c for c in b["cards"] if c["stage"] not in saved]


def test_opening_apply_doesnt_add_it_to_applications(client):
    it = _job(client)
    a = client.post(f"/api/apply/{it['id']}", json={}).json()
    assert a["stage"] == "preparing"
    b, on_board = _board(client)
    assert not any(c["job_id"] == it["id"] for c in on_board)  # only a draft
    assert any(c["job_id"] == it["id"] and c["kind"] == "internship" for c in b["cards"])
    client.patch(f"/api/applications/{a['application_id']}", json={"stage": "started"})
    _, on_board = _board(client)
    assert next(c for c in on_board if c["job_id"] == it["id"])["stage"] == "started"
    done = client.patch(f"/api/applications/{a['application_id']}", json={"stage": "applied"}).json()
    assert done["stage"] == "applied" and done["date_applied"] and done["follow_up_date"]
    assert client.get("/api/home").json()["pipeline"]["Applied"] >= 1


def test_remove_and_bring_back(client):
    it = _job(client, title="Network Intern", company_name="Mesa Grid Co")
    client.patch(f"/api/jobs/{it['id']}", json={"hidden": True})
    assert it["id"] not in [j["id"] for j in client.get("/api/internships").json()["items"]]
    assert it["id"] in [j["id"] for j in client.get("/api/removed").json()]
    client.patch(f"/api/jobs/{it['id']}", json={"hidden": False})
    assert it["id"] in [j["id"] for j in client.get("/api/internships").json()["items"]]
    assert it["id"] not in [j["id"] for j in client.get("/api/removed").json()]


def test_pasted_questions(client):
    it = _job(client, title="SOC Analyst Intern", company_name="Valley Shield")
    aid = client.post(f"/api/apply/{it['id']}", json={}).json()["application_id"]
    q = client.post(f"/api/applications/{aid}/questions", json={"question": "Why would you like to work at Valley Shield?"}).json()
    assert q["answer"] and "Valley Shield" in q["answer"] and q["generated_by"] == "template"
    assert "culture of curiosity, teamwork and service" in q["answer"]  # one real thing from the posting
    assert "—" not in q["answer"] and "I'm" not in q["answer"]
    short = client.post(f"/api/applications/{aid}/questions",
                        json={"question": "Tell us about a time you faced a setback.", "limit_chars": 300}).json()
    assert len(short["answer"]) <= 300 and not any("characters" in f for f in short["flags"])
    edited = client.patch(f"/api/questions/{q['id']}", json={"answer": "My own answer — edited."}).json()
    assert edited["generated_by"] == "you" and "—" not in edited["answer"]
    again = client.patch(f"/api/questions/{q['id']}", json={"regenerate": True, "notes": "mention teamwork"}).json()
    assert again["generated_by"] == "template" and again["notes"] == "mention teamwork"
    page = client.get(f"/api/applications/{aid}").json()
    assert [x["id"] for x in page["questions"]] == [short["id"], q["id"]] and "started" in page["stages_all"]
    client.delete(f"/api/questions/{short['id']}")
    assert len(client.get(f"/api/applications/{aid}").json()["questions"]) == 1
    assert client.post(f"/api/applications/{aid}/questions", json={"question": "  "}).status_code == 400


def test_question_kinds():
    from app.services.writing import question_kind
    assert question_kind("Why would you like to work at FOX?") == "why_company"
    assert question_kind("Tell us about yourself.") == "about"
    assert question_kind("Why are you interested in this internship?") == "why_role"
    assert question_kind("Describe a time you failed and what you learned") == "challenge"
    assert question_kind("What is your greatest weakness?") == "weakness"


def test_anthropic_key_is_checked(client):
    r = client.post("/api/settings/anthropic-key", json={"key": "not-a-key"})
    assert r.status_code == 400 and "sk-ant-" in r.json()["detail"]


def test_replies_matched_to_applications(client, tmp_path):
    import json

    from app.db import SessionLocal
    from app.models import Company
    from app.services import replies as RP
    db = SessionLocal()
    co = db.query(Company).filter(Company.name == "Valley Shield").one()
    co.website = "https://www.valleyshield.com"
    db.commit()
    watch = RP.watch_list(db)
    w = next(x for x in watch if x["company"] == "Valley Shield")
    assert w["domains"] == ["valleyshield.com"] and "valley shield" in w["terms"]
    folder = tmp_path / "reply-imports"
    folder.mkdir()
    emails = [
        {"id": "m1", "from": "Valley Shield Careers <careers@mail.valleyshield.com>", "subject": "Interview for SOC Analyst Intern",
         "snippet": "We'd like to schedule a time to speak with you next week.", "date": "2026-11-02T17:00:00Z",
         "url": "https://mail.google.com/mail/u/0/#inbox/m1", "account": "jalen@example.com"},
        {"id": "m2", "from": "no-reply@us.greenhouse-mail.io", "subject": "Thank you for applying to Valley Shield",
         "snippet": "We have received your application.", "date": "Mon, 02 Nov 2026 10:00:00 -0700"},
        {"id": "m3", "from": "Handshake <handshake@notifications.joinhandshake.com>", "subject": "New jobs for you at Valley Shield",
         "snippet": "Apply now"},
        {"id": "m4", "from": "Pizza Place <deals@pizza.com>", "subject": "50% off tonight", "snippet": "Hungry?"},
        {"id": "m5", "from": "no-reply@us.greenhouse-mail.io", "subject": "Your application to Some Other Co",
         "snippet": "Unfortunately we have decided to move forward with other candidates."},
        {"id": "m6", "from": "Valley Shield <news@valleyshield.com>", "subject": "Valley Shield's November newsletter",
         "snippet": "Our latest product updates and webinars."},
    ]
    (folder / "check.json").write_text(json.dumps({"account": "jalen@example.com", "emails": emails}))
    assert RP.import_dropped(db, folder) == 2
    assert RP.import_dropped(db, folder) == 0 and (folder / "done" / "check.json").exists()
    db.close()
    r = client.get("/api/replies").json()
    by = {x["subject"]: x for x in r["items"]}
    interview = by["Interview for SOC Analyst Intern"]
    assert interview["kind"] == "interview" and interview["company"] == "Valley Shield" and interview["needs_you"]
    assert interview["suggest"]["stage"] == "interview"
    thanks = by["Thank you for applying to Valley Shield"]
    assert thanks["kind"] == "confirmation" and thanks["suggest"]["stage"] == "applied" and thanks["needs_you"]
    assert r["unseen"] == 2 and client.get("/api/updates").json()["unseen_replies"] == 2
    moved = client.post(f"/api/replies/{thanks['id']}/apply").json()
    assert moved["stage"] == "applied" and moved["suggest"] is None
    assert client.get("/api/replies").json()["unseen"] == 1  # a confirmation for an applied role no longer pings you
    client.post("/api/replies/seen", json={})
    assert client.get("/api/replies").json()["unseen"] == 0
    client.patch(f"/api/replies/{interview['id']}", json={"dismissed": True})
    assert interview["id"] not in [x["id"] for x in client.get("/api/replies").json()["items"]]
    page = client.get(f"/api/applications/{moved['application_id']}").json()
    assert page["replies"] and page["application"]["stage"] == "applied"


def test_watch_file_written(client, tmp_path, monkeypatch):
    import json

    from app.db import SessionLocal
    from app.services import replies as RP
    monkeypatch.setattr(RP, "folder", lambda: tmp_path)
    db = SessionLocal()
    path = RP.write_watch(db)
    db.close()
    data = json.loads(Path(path).read_text())
    assert data["companies"] and "greenhouse-mail.io" in data["ats_senders"]


def test_scheduler_loads_every_rule(client, monkeypatch):
    """Scheduled scans register at startup (the test settings turn the scheduler off, so turn it on here)."""
    from app import scheduler
    from app.config import settings
    monkeypatch.setattr(settings, "enable_scheduler", True)
    scheduler._scheduler = None
    try:
        scheduler.reload()
        ids = {j.id for j in scheduler._scheduler.get_jobs()}
        assert "intern-imports" in ids and any(i.startswith("rule-") for i in ids)
    finally:
        scheduler.shutdown()
        scheduler._scheduler = None


def test_stale_code_is_noticed(tmp_path):
    """A managed backend notices its own code changed on disk (once the change has settled) and restarts."""
    import os
    import time

    from app import selfupdate as SU
    f = tmp_path / "x.py"
    f.write_text("a = 1\n")
    started = time.time() - 100
    os.utime(f, (started - 50, started - 50))
    assert not SU.stale_code(root=str(tmp_path), started=started)  # older than this process
    os.utime(f, (time.time(), time.time()))
    assert not SU.stale_code(root=str(tmp_path), started=started)  # still settling
    assert SU.stale_code(now=time.time() + SU.CODE_SETTLE_S + 1, root=str(tmp_path), started=started)

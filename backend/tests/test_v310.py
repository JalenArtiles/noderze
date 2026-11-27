"""Approved outreach batches sent from Gmail, follow-ups on applications, and new columns on old tables."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
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


def test_next_send_time_is_next_weekday_morning():
    from app.services.mailer import next_send_time
    # Friday 2 PM Phoenix (21:00 UTC) -> Monday 9 AM Phoenix (16:00 UTC)
    assert next_send_time(datetime(2026, 11, 27, 21, 0)) == datetime(2026, 11, 30, 16, 0)
    # Tuesday 7 AM Phoenix -> same day 9 AM
    assert next_send_time(datetime(2026, 12, 1, 14, 0)) == datetime(2026, 12, 1, 16, 0)
    # Tuesday 8:45 AM Phoenix (less than 30 minutes to go) -> Wednesday 9 AM
    assert next_send_time(datetime(2026, 12, 1, 15, 45)) == datetime(2026, 12, 2, 16, 0)


def test_approve_and_send(client, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Prospect
    from app.services import mailer
    from app.services import outreach as O
    db = SessionLocal()
    O.import_items(db, [
        {"company": "Mesa Data Co", "email": "jobs@mesadata.com", "subject": "Data Intern Inquiry, Spring 2027",
         "body": "Dear Hiring Team,\n\nHello. My resume is attached.\n\nJalen", "draft_id": "r-9"},
        {"company": "Chandler Net", "linkedin_url": "https://www.linkedin.com/in/someone", "note": "Hi"},
    ], batch="2026-11-30")
    db.commit()
    # Without Gmail sending set up, nothing can be approved
    monkeypatch.setattr(settings, "gmail_app_password", None)
    assert client.post("/api/prospects/approve", json={}).status_code == 409
    monkeypatch.setattr(settings, "gmail_address", "me@gmail.com")
    monkeypatch.setattr(settings, "gmail_app_password", "abcdabcdabcdabcd")
    r = client.post("/api/prospects/approve", json={}).json()
    assert r["scheduled"] == 1
    p = db.query(Prospect).filter_by(email="jobs@mesadata.com").one()
    db.refresh(p)
    assert p.status == "scheduled" and p.send_at is not None
    # Can't jump straight to scheduled, and nothing goes out before its time
    assert client.patch(f"/api/prospects/{p.id}", json={"status": "scheduled"}).status_code == 400
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def send_message(self, m): sent.append(m)

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailer, "_remove_gmail_draft", lambda p: None)
    assert mailer.send_due(db) == 0
    # Edit before it goes out, then let the time pass
    client.patch(f"/api/prospects/{p.id}", json={"subject": "Edited subject"})
    db.refresh(p)
    p.send_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert mailer.send_due(db) == 1
    db.refresh(p)
    assert p.status == "sent" and p.message_id and sent[0]["Subject"] == "Edited subject" and sent[0]["To"] == "jobs@mesadata.com"
    db.close()


def test_cancel_before_sending(client, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.services import outreach as O
    db = SessionLocal()
    O.import_items(db, [{"company": "Gilbert Sec", "email": "hr@gilbertsec.com", "subject": "S", "body": "B"}], batch="x")
    db.commit()
    monkeypatch.setattr(settings, "gmail_address", "me@gmail.com")
    monkeypatch.setattr(settings, "gmail_app_password", "abcdabcdabcdabcd")
    assert client.post("/api/prospects/approve", json={}).json()["scheduled"] == 1
    assert client.post("/api/prospects/unschedule", json={}).json()["unscheduled"] == 1
    items = {p["email"]: p for p in client.get("/api/prospects").json()["items"] if p["email"]}
    assert items["hr@gilbertsec.com"]["status"] == "ready" and items["hr@gilbertsec.com"]["send_at"] is None
    db.close()


def test_follow_ups_on_applications(client):
    from app.db import SessionLocal
    from app.models import Application, Job
    from app.services import outreach as O
    from app.util import today
    db = SessionLocal()
    job = db.query(Job).first()
    a = db.query(Application).filter_by(job_id=job.id).one_or_none() or Application(job_id=job.id)
    a.stage, a.date_applied = "applied", today() - timedelta(days=4)
    db.add(a)
    db.commit()
    apps = {x["application_id"]: x for x in O.applications(db)}
    assert apps[a.id]["due"] is True
    O.import_items(db, [{"company": job.company.name, "linkedin_url": "https://www.linkedin.com/search/results/people/?keywords=x",
                         "application_id": a.id, "job_title": job.title, "note": "I applied"}], batch="y")
    db.commit()
    apps = {x["application_id"]: x for x in O.applications(db)}
    assert apps[a.id]["due"] is False and apps[a.id]["followed_up"] is True
    # A second LinkedIn follow-up for the same application is not added
    assert O.import_items(db, [{"company": job.company.name, "linkedin_url": "https://www.linkedin.com/in/other",
                                "application_id": a.id}]) == []
    p = next(x for x in client.get("/api/prospects").json()["items"] if x["application_id"] == a.id)
    assert p["kind"] == "applied" and p["job_title"] == job.title
    db.close()


def test_new_columns_are_added_to_old_tables(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app import db as dbmod
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as c:
        c.execute(text("CREATE TABLE prospects (id INTEGER PRIMARY KEY, company_name VARCHAR(300), status VARCHAR(20))"))
    real = dbmod.engine
    dbmod.engine = old
    try:
        added = dbmod.add_missing_columns()
    finally:
        dbmod.engine = real
    cols = {c["name"] for c in inspect(old).get_columns("prospects")}
    assert {"kind", "send_at", "application_id", "email"} <= cols and "prospects.send_at" in added


def test_gmail_setup_checks_the_password(client, monkeypatch):
    from app.services import mailer
    monkeypatch.setattr(mailer, "check_login", lambda a, p: "Gmail didn't accept that app password.")
    assert client.post("/api/settings/gmail-send", json={"address": "me@gmail.com", "app_password": "abcd abcd abcd abcd"}).status_code == 400
    assert client.post("/api/settings/gmail-send", json={"address": "me@gmail.com", "app_password": "short"}).status_code == 400

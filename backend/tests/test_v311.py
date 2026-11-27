"""The master resume can be swapped by dropping a file, and tailored files are named "<Name> (<Company>) Resume"."""
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient


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


def _resume_docx(path, role="Technical Sales Engineer Intern | Example Co"):
    import docx
    d = docx.Document()
    d.add_paragraph().add_run("TEST PERSON").bold = True
    d.add_paragraph("Tempe, AZ 85281  |  555-555-0100  |  test@example.com")
    d.add_paragraph().add_run("EXPERIENCE").bold = True
    p = d.add_paragraph()
    p.add_run(role).bold = True
    p.add_run("\tFeb 2026 – Jun 2026").italic = True
    d.add_paragraph("Tempe, AZ")
    d.add_paragraph("Led discovery with university stakeholders", style="List Bullet")
    d.save(str(path))


def test_file_label():
    from app.services.resume import file_label
    assert file_label("Jalen Artiles", "GuidePoint Security", "Resume") == "Jalen Artiles (GuidePoint Security) Resume"
    assert file_label("Jalen Artiles", "Acme", "Cover Letter") == "Jalen Artiles (Acme) Cover Letter"
    assert file_label("Jalen Artiles", "AT&T / Mobility: Inc.", "Resume") == "Jalen Artiles (AT&T Mobility Inc.) Resume"
    assert file_label("Jalen Artiles", None, "Resume") == "Jalen Artiles Resume"
    assert file_label("", "Acme", "Resume") == "(Acme) Resume"


def test_disposition_keeps_the_name():
    from app.services.resume import disposition
    h = disposition("Jalen Artiles (Société Générale) Resume.docx")
    assert 'filename="Jalen Artiles (Socit Gnrale) Resume.docx"' in h
    assert "filename*=UTF-8''Jalen%20Artiles%20%28Soci%C3%A9t%C3%A9%20G%C3%A9n%C3%A9rale%29%20Resume.docx" in h


def test_dropped_docx_becomes_master_and_pdf_becomes_attachment(client, tmp_path, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.services import mailer
    from app.services import resume as R
    from app.services.profile import master_resume
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    drop = R.imports_folder()
    drop.mkdir()
    _resume_docx(drop / "Test Person Resume.docx")
    (drop / "Test Person Resume.pdf").write_bytes(b"%PDF-1.4 test")
    (drop / "~$st Person Resume.docx").write_bytes(b"lock file")
    (drop / "broken.docx").write_bytes(b"not a zip")
    db = SessionLocal()
    try:
        assert R.import_dropped(db) == 2
        m = master_resume(db)
        assert m.filename == "Test Person Resume.docx" and m.path.startswith(str(tmp_path / "resumes" / "master-"))
        roles = [it for s in m.parsed["sections"] if s["key"] == "experience" for it in s["items"] if it["kind"] == "role"]
        assert roles[0]["title"] == "Technical Sales Engineer Intern" and roles[0]["org"] == "Example Co"
        assert roles[0]["dates"] == "Feb 2026 – Jun 2026" and roles[0]["location"] == "Tempe, AZ"
        assert mailer.resume_file().read_bytes() == b"%PDF-1.4 test"
        assert sorted(p.name for p in (drop / "done").iterdir()) == ["Test Person Resume.docx", "Test Person Resume.pdf"]
        assert [p.name for p in (drop / "failed").iterdir()] == ["broken.docx"]
        assert (drop / "~$st Person Resume.docx").exists()
        assert R.import_dropped(db) == 0
    finally:
        db.close()


def test_attachment_name_has_spaces(tmp_path, monkeypatch):
    from app.config import settings
    from app.models import Prospect
    from app.services import mailer
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "gmail_address", "me@example.com")
    mailer.resume_file().parent.mkdir(parents=True)
    mailer.resume_file().write_bytes(b"%PDF-1.4")
    m: EmailMessage = mailer.build(Prospect(email="r@example.com", subject="Hi", email_body="My resume is attached."))
    names = [part.get_filename() for part in m.iter_attachments()]
    assert names == ["Jalen Artiles Resume.pdf"]


def test_tailored_resume_and_cover_letter_names(client, tmp_path, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.models import GeneratedDoc, Job, ResumeVersion
    from app.services import resume as R
    from app.services.profile import master_resume
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db = SessionLocal()
    try:
        if master_resume(db) is None:
            (tmp_path / "resumes").mkdir()
            _resume_docx(tmp_path / "resumes" / "master.docx")
            R.ingest_master(db, str(tmp_path / "resumes" / "master.docx"), "master.docx")
        res = master_resume(db)
        job = db.query(Job).first()
        company = job.company.name
        person = R.person_name(db)
        v = ResumeVersion(resume_id=res.id, job_id=job.id, label=f"{company} - {job.title}", analysis={}, edits=[])
        doc = GeneratedDoc(kind="cover_letter", job_id=job.id, title=f"Cover letter - {company}",
                           content="Jalen Artiles\nTempe, AZ\n\nDear Hiring Team,\n\nThank you.")
        db.add_all([v, doc])
        db.commit()
        vid, did = v.id, doc.id
    finally:
        db.close()

    r = client.post(f"/api/resume/versions/{vid}/render")
    assert r.status_code == 200
    expected = R.file_label(person, company, "Resume")
    assert expected.endswith(f"({company}) Resume")
    db = SessionLocal()
    try:
        out = db.get(ResumeVersion, vid).output_path
    finally:
        db.close()
    assert out.endswith(f"{expected}.docx") and (tmp_path / "resumes" / "versions") in __import__("pathlib").Path(out).parents

    d = client.get(f"/api/resume/versions/{vid}/download")
    assert d.status_code == 200 and f"{expected}.docx".replace(" ", "%20").replace("(", "%28").replace(")", "%29") in \
        d.headers["content-disposition"] or f'filename="{expected}.docx"' in d.headers["content-disposition"]

    c = client.get(f"/api/docs/{did}/docx")
    assert c.status_code == 200
    assert f'filename="{R.file_label(person, company, "Cover Letter")}.docx"' in c.headers["content-disposition"] \
        or not company.isascii()


def test_rewrites_reach_unsent_messages_only(client):
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import Prospect
    from app.services import outreach as O
    db = SessionLocal()
    try:
        search = "https://www.linkedin.com/search/results/people/?keywords=Rewrite+Co+recruiter"
        O.import_items(db, [
            {"company": "Rewrite Co", "channel": "linkedin", "linkedin_url": search, "note": "old note", "followup": "old"},
            {"company": "Rewrite Co", "channel": "email", "email": "Team@RewriteCo.com", "subject": "Old", "body": "Old body"},
            {"company": "Sent Co", "channel": "email", "email": "hr@sentco.com", "subject": "Old", "body": "Old body"},
        ], batch="t")
        db.commit()
        approved = O.find(db, "team@rewriteco.com")
        approved.status, approved.send_at, approved.approved_at = "scheduled", datetime(2026, 11, 30, 16), datetime(2026, 11, 27)
        O.find(db, "hr@sentco.com").status = "sent"
        db.commit()
        n = O.apply_updates(db, [
            {"linkedin_url": search, "set": {"name": "Pat Example", "title": "University Recruiter",
                                             "linkedin_url": "https://www.linkedin.com/in/Pat-Example/?trk=x",
                                             "note": "x" * 250, "followup": "New follow-up"}},
            {"email": "team@rewriteco.com", "set": {"subject": "New", "body": "New body"}},
            {"email": "hr@sentco.com", "set": {"subject": "New", "body": "New body"}},
        ])
        db.commit()
        assert n == 2
        li = O.find(db, linkedin_url="https://www.linkedin.com/in/pat-example")
        assert li.name == "Pat Example" and li.followup == "New follow-up" and len(li.note) <= O.NOTE_LIMIT
        em = O.find(db, "team@rewriteco.com")
        assert (em.subject, em.email_body, em.status, em.send_at) == ("New", "New body", "ready", None)
        assert O.find(db, "hr@sentco.com").email_body == "Old body"
    finally:
        db.close()


def test_messages_about_a_removed_posting_are_set_aside(client, monkeypatch):
    from datetime import datetime

    import httpx

    from app.db import SessionLocal
    from app.services import mailer
    from app.services import outreach as O

    class Resp:
        def __init__(self, code): self.status_code = code

    def fake_get(url, **kw):
        if "timeout" in url:
            raise httpx.ConnectTimeout("slow")
        return Resp(404 if "gone" in url else 200)
    monkeypatch.setattr(httpx, "get", fake_get)
    db = SessionLocal()
    try:
        O.import_items(db, [
            {"company": "Gone Agency", "email": "hr@goneagency.gov", "subject": "S", "body": "B",
             "source_url": "https://jobs.example.gov/gone-intern"},
            {"company": "Live Agency", "email": "hr@liveagency.gov", "subject": "S", "body": "B",
             "source_url": "https://jobs.example.gov/live-intern"},
            {"company": "Slow Agency", "email": "hr@slowagency.gov", "subject": "S", "body": "B",
             "source_url": "https://jobs.example.gov/timeout-intern"},
        ], batch="g")
        db.commit()
        gone, live, slow = (O.find(db, e) for e in ("hr@goneagency.gov", "hr@liveagency.gov", "hr@slowagency.gov"))
        assert (gone.status, gone.send_error) == ("skipped", O.GONE_NOTE)
        assert live.status == "ready" and slow.status == "ready"
        # A posting that closes after approval is caught right before sending
        live.source_url = "https://jobs.example.gov/gone-later"
        live.status, live.send_at = "scheduled", datetime(2026, 1, 1)
        db.commit()
        monkeypatch.setattr(mailer, "configured", lambda: True)
        monkeypatch.setattr(mailer, "send_one", lambda p: (_ for _ in ()).throw(AssertionError("sent a dead posting")))
        assert mailer.send_due(db) == 0
        assert O.find(db, "hr@liveagency.gov").status == "skipped"
    finally:
        db.close()

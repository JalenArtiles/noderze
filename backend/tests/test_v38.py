"""Stricter email filtering, a Spring internships list without the ones you acted on, and live posting checks."""
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from app.db import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        for t in ("email_replies", "question_answers"):
            c.exec_driver_sql(f"DROP TABLE IF EXISTS {t}")
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


DESC = ("Paid internship at $20 per hour, 15-20 hours per week during the spring 2027 semester. Triage SIEM alerts "
        "and document incidents with the SOC team. ") * 3


def _job(client, **kw):
    body = {"company_name": "Desert Cyber Co", "title": "Cybersecurity Intern", "location": "Tempe, AZ",
            "description": DESC} | kw
    return client.post("/api/internships", json=body).json()


def _listed(client):
    return {i["id"] for i in client.get("/api/internships").json()["items"]}


# ----------------------------------------------------------------------------- email filtering

def test_meeting_reports_are_not_interviews():
    from app.services import replies as R
    subj, snip = "Capstone sync on November 18, 2026 | Read Meeting Report", ("Student teams presented research on defense "
                                                                    "technology concepts, interview findings, and needs.")
    assert R.classify(subj, snip) == "other"
    assert R.keep(subj, snip, "Jordan Lee via Read AI", "executiveassistant@e.read.ai", matched=False)[0] is False
    assert R.keep(subj, snip, "Read AI", "executiveassistant@e.read.ai", matched=True)[0] is False  # even for a tracked company
    assert R.classify("Career Center: Interview tips", "Mock interview practice") == "other"
    # Real invitations still count
    assert R.classify("Next steps", "We would like to invite you to an interview. Please share your availability.") == "interview"
    assert R.classify("Interview with Acme Robotics", "") == "interview"
    assert R.classify("Your application", "Please pick a time for a phone screen") == "interview"
    assert not R.not_hiring("Sam", "calendar-notification@google.com", "Invitation: Interview with GuidePoint @ Mon")
    assert R.not_hiring("Google Calendar", "calendar-notification@google.com", "Invitation: Team sync @ Mon")


def test_people_are_not_companies():
    from app.services import replies as R
    assert R.parse_confirmation("Quick question", "Jordan Lee via Read AI", "x@e.read.ai") is None
    assert R.parse_confirmation("Hello", "Jane Doe", "jane@gmail.com") is None
    assert R.parse_confirmation("Thanks", "Kimball Electronics", "kei@myworkday.com")["company"] == "Kimball Electronics"
    assert R.parse_confirmation("Your application", "Acme Robotics", "talent@acmerobotics.com")["company"] == "Acme Robotics"


def test_import_drops_meeting_report_and_refilter_cleans_old_ones(client):
    from app.db import SessionLocal
    from app.models import EmailReply
    from app.services import replies as R
    db = SessionLocal()
    added = R.import_items(db, [{"id": "m-h4d", "from": "Jordan Lee via Read AI <executiveassistant@e.read.ai>",
                                 "subject": "Capstone sync on November 18, 2026 | Read Meeting Report",
                                 "snippet": "Student teams presented research, interview findings, and open questions."}])
    assert added == []
    # One stored by the old rules is removed by the update
    db.add(EmailReply(message_id="old-h4d", from_name="Jordan Lee via Read AI",
                      from_email="executiveassistant@e.read.ai", subject="Capstone sync | Read Meeting Report",
                      snippet="interview findings", kind="interview"))
    db.add(EmailReply(message_id="old-ok", from_name="Kimball Electronics", from_email="kei@myworkday.com",
                      subject="Thank you for applying to Kimball Electronics!",
                      snippet="We have received your application for the Cybersecurity Intern position.", kind="other"))
    db.commit()
    assert R.refilter(db) == 1
    db.commit()
    ids = {r.message_id: r.kind for r in db.query(EmailReply)}
    assert "old-h4d" not in ids and ids["old-ok"] == "confirmation"
    db.close()


def test_not_about_a_job_blocks_the_sender(client):
    from app.db import SessionLocal
    from app.models import EmailReply
    from app.services import replies as R
    db = SessionLocal()
    R.import_items(db, [{"id": "n1", "from": "Talent Team <talent@noisyco.com>", "subject": "Your application to Noisyco",
                         "snippet": "Thank you for applying to Noisyco. We received your application."}])
    db.commit()
    r = db.query(EmailReply).filter_by(message_id="n1").one()
    out = client.patch(f"/api/replies/{r.id}", json={"not_job": True}).json()
    assert out["hidden_from_sender"] >= 1
    db.expire_all()
    assert db.get(EmailReply, r.id).dismissed
    assert R.import_items(db, [{"id": "n2", "from": "Talent Team <talent@noisyco.com>", "subject": "Your application",
                                "snippet": "Thank you for applying. We received your application."}]) == []
    db.close()


# ----------------------------------------------------------------------------- the list

def test_acted_on_internships_leave_the_list(client):
    started, applied, rejected, removed, saved = (_job(client, company_name=f"Co {n}", title=f"Data Intern {n}")
                                                  for n in ("A", "B", "C", "D", "E"))
    listed = _listed(client)
    assert {started["id"], applied["id"], rejected["id"], removed["id"], saved["id"]} <= listed
    for it, stage in ((started, "started"), (applied, "applied"), (rejected, "rejected")):
        a = client.post(f"/api/apply/{it['id']}", json={}).json()
        client.patch(f"/api/applications/{a['application_id']}", json={"stage": stage})
    client.patch(f"/api/jobs/{removed['id']}", json={"hidden": True})
    client.post("/api/applications", json={"job_id": saved["id"]})  # saved, not applied: stays
    listed = _listed(client)
    assert not {started["id"], applied["id"], rejected["id"], removed["id"]} & listed
    assert saved["id"] in listed
    data = client.get("/api/internships").json()
    assert data["moved"]["applied"] >= 1 and data["moved"]["started"] >= 1 and data["moved"]["closed_out"] >= 1
    assert data["counts"]["total_ok"] == sum(1 for i in data["items"] if i["intern"]["status"] != "out")
    assert client.get("/api/home").json()["internships"]["total_ok"] == data["counts"]["total_ok"]


def test_same_posting_shows_once(client):
    from app.db import SessionLocal
    from app.models import Job
    from app.services import intern_jobs as IJ
    a = _job(client, company_name="U-Haul", title="Data Analyst Spring Internship")
    b = _job(client, company_name="Uhaul", title="Data Analyst Spring Internship")
    db = SessionLocal()
    url = "https://uhaul.wd1.myworkdayjobs.com/UhaulJobs/job/Phoenix-Arizona/Data-Analyst-Spring-Internship_R258909"
    for jid in (a["id"], b["id"]):
        j = db.get(Job, jid)
        j.url = url
    # The SimplifyJobs copy of a Greenhouse posting, and the posting itself (closed)
    c = db.get(Job, _job(client, company_name="Copyco", title="AI Intern")["id"])
    d = db.get(Job, _job(client, company_name="Copyco", title="AI Intern - GPSU")["id"])
    c.url, c.source, c.source_is_original = "https://boards.greenhouse.io/copyco/jobs/6218650004", "simplify", False
    d.url, d.source_is_original, d.is_active = "https://boards.greenhouse.io/copyco/jobs/6218650004?gh_jid=6218650004", True, False
    db.commit()
    assert IJ.posting_key(c) == IJ.posting_key(d)
    shown = {j.id for j in IJ.board(db)[0]}
    assert len({a["id"], b["id"]} & shown) == 1
    assert c.id not in shown and d.id not in shown
    # Two Handshake searches are two postings, not one
    h1, h2 = db.get(Job, _job(client, title="H1")["id"]), db.get(Job, _job(client, title="H2")["id"])
    h1.url = "https://app.joinhandshake.com/stu/postings?query=AppLovin%20Data"
    h2.url = "https://app.joinhandshake.com/stu/postings?query=Peraton%20IT"
    assert IJ.posting_key(h1) != IJ.posting_key(h2)
    db.commit()
    db.close()


# ----------------------------------------------------------------------------- reading the posting

def test_dates_and_hours_read_from_the_posting():
    from app.services.internships import hours_of, term_of
    t = term_of("Intern - IT Database", "Internship 2026 Dates: May 18, 2026 - August 7, 2026\nLocation: Remote")
    assert t.status == "past"
    t = term_of("Data Analyst Spring Internship", "Program Dates: The Spring Internship program will run from "
                                                  "February 1st through April 30th.")
    assert t.status == "spring" and "Feb" in t.label and "Apr" in t.label
    t = term_of("Cybersecurity Analyst Intern", "The internship dates are June 7, 2027 through August 6, 2027.")
    assert t.status == "summer"
    t = term_of("Intern", "Applications are accepted from October 1, 2026 through December 15, 2026. Spring 2027.")
    assert t.status == "spring"  # an application window is not the internship
    h = hours_of("Duration: 12 weeks, full-time. Casual, PRN & Part Time employees regularly scheduled to work less "
                 "than 20 hours are eligible for paid sick leave.")
    assert h.status == "full_time"


def test_sections_from_the_posting():
    from app.services.intern_jobs import sections
    text = ("About us\nWe move people.\n\nPrimary Responsibilities:\n\n- Assist in developing ETL workflows and data "
            "pipelines.\n\n- Create, test, and document SQL queries.\n\nQualifications:\n\n- Currently pursuing a "
            "bachelor's degree in:\n\n- Computer Science\n\n- Data Analytics\n\n- Basic knowledge of SQL.\n\nAbout Us\n"
            "- Since 1945 we have moved families.")
    s = sections(text)
    assert s["do"] == ["Assist in developing ETL workflows and data pipelines.", "Create, test, and document SQL queries."]
    assert s["need"][0] == "Currently pursuing a bachelor's degree in: Computer Science, Data Analytics"
    assert s["need"][1] == "Basic knowledge of SQL."
    assert len(s["need"]) == 2


# ----------------------------------------------------------------------------- live checks

class _R:
    def __init__(self, code):
        self.status_code = code


def _http_error(code):
    req = httpx.Request("GET", "https://x")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))


def test_live_check_closes_and_refreshes(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import Job
    from app.services import intern_verify as V
    from app.services.fetch import PoliteFetcher
    monkeypatch.setattr(PoliteFetcher, "_wait", lambda self, host: None)
    gone = _job(client, company_name="Gone Co", title="Security Intern")
    live = _job(client, company_name="Live Co", title="Data Intern")
    late = _job(client, company_name="Late Co", title="Network Intern")
    hs = _job(client, company_name="Hand Co", title="Data Science Intern")
    db = SessionLocal()
    db.get(Job, gone["id"]).url = "https://job-boards.greenhouse.io/goneco/jobs/111"
    db.get(Job, live["id"]).url = "https://live.wd1.myworkdayjobs.com/External/job/Tempe/Data-Intern_R9"
    db.get(Job, late["id"]).deadline = date.today() - timedelta(days=3)
    db.get(Job, hs["id"]).url = "https://app.joinhandshake.com/stu/postings?query=Hand"
    db.commit()
    wd = {"jobPostingInfo": {"title": "Data Intern", "jobDescription": "<p>Part-time, 20 hours a week from January 12 "
          "to May 1, 2027. Pay is $22 per hour. Build Power BI dashboards and clean data in SQL.</p>" * 3,
          "location": "Tempe, AZ", "timeType": "Part time", "jobReqId": "R9", "canApply": True}}

    def get_json(self, url, **kw):
        if "goneco" in url:
            raise _http_error(404)
        if "/wday/cxs/live/" in url:
            return wd
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(PoliteFetcher, "get_json", get_json)
    states = {}
    for jid in (gone["id"], live["id"], late["id"], hs["id"]):
        states[jid] = V.verify_job(db, db.get(Job, jid)).state
        db.commit()
    assert states == {gone["id"]: "closed", live["id"]: "open", late["id"]: "closed", hs["id"]: "unchecked"}
    j = db.get(Job, live["id"])
    assert j.source_is_original and j.last_verified_at and "Power BI" in j.description_text
    assert j.intern.term["status"] == "spring" and j.intern.hours["status"] == "ok"
    assert not db.get(Job, gone["id"]).is_active
    listed = _listed(client)
    assert gone["id"] not in listed and late["id"] not in listed and live["id"] in listed and hs["id"] in listed
    page = client.get(f"/api/jobs/{live['id']}").json()
    assert page["details"]["original"] and page["details"]["verify"]["state"] == "open"
    assert any(f["key"] == "pay" and "$22" in f["value"] for f in page["details"]["facts"])
    assert page["details"]["do"] == [] or isinstance(page["details"]["do"], list)
    db.close()


def test_muse_copy_and_check_one_endpoint(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import Job
    from app.services.fetch import PoliteFetcher
    monkeypatch.setattr(PoliteFetcher, "_wait", lambda self, host: None)
    it = _job(client, company_name="Musey", title="Data Center Design Intern")
    db = SessionLocal()
    j = db.get(Job, it["id"])
    j.url, j.source, j.source_is_original = "https://www.themuse.com/jobs/musey/data-center-design-intern", "themuse", False
    db.commit()
    db.close()
    monkeypatch.setattr(PoliteFetcher, "get_json", lambda self, url, **kw: {"results": [], "page_count": 1})
    r = client.post(f"/api/internships/{it['id']}/verify").json()
    assert r["verify"]["state"] == "closed" and "Muse" in r["verify"]["reason"]
    assert it["id"] not in _listed(client)


def test_deadline_in_pasted_text():
    from app.services.intern_verify import stated_deadline
    assert stated_deadline("Pay: $30 per hour.\nHandshake application deadline: October 30, 2026.") == date(2026, 10, 30)
    assert stated_deadline("No dates here.") is None


def test_logo_domains():
    from app.services import logos
    assert logos.matches("Maricopa Association of Governments", "azmag.gov")
    assert logos.matches("FOX", "fox.com") and logos.matches("Risepoint", "risepoint.com")
    assert not logos.matches("Risepoint", "linkedin.com") and not logos.matches("FOX", "greenhouse.io")
    assert logos._from_name("Arizona State University") == "asu.edu"
    assert logos._from_name("Labcorp") == "labcorp.com" and logos._from_name("Wells Fargo") == "wellsfargo.com"
    assert logos._from_name("NXP Semiconductors") is None and logos._from_name("CAI") is None


def test_logo_from_posting_and_board(client):
    from app.db import SessionLocal
    from app.models import Company, Job
    from app.services import logos
    a = _job(client, company_name="Regional Planners Group", title="GIS Intern",
             description=DESC + " Visit www.regionalplanners.org to learn more. Follow us on linkedin.com.")
    b = _job(client, company_name="Haulco", title="Data Intern")
    db = SessionLocal()
    db.get(Job, b["id"]).url = "https://haulco.wd1.myworkdayjobs.com/Jobs/job/Phoenix/Data-Intern_R1"
    for c in db.query(Company).filter(Company.name.in_(["Regional Planners Group", "Haulco"])):
        c.website = None
    db.commit()
    logos.fill(db)
    db.commit()
    got = {c.name: (c.data or {}).get("logo_domain") for c in db.query(Company).filter(
        Company.name.in_(["Regional Planners Group", "Haulco"]))}
    assert got == {"Regional Planners Group": "regionalplanners.org", "Haulco": "haulco.com"}
    assert client.get(f"/api/jobs/{a['id']}").json()["company_website"] == "regionalplanners.org"
    db.close()


def test_no_platform_specific_date_formats():
    """Windows' strftime has no %-d; the app runs on Windows."""
    import pathlib
    import re
    app = pathlib.Path(__file__).resolve().parent.parent / "app"
    bad = [str(f) for f in app.rglob("*.py") if re.search(r"%-[dmIHMSj]", f.read_text(encoding="utf-8"))]
    assert bad == []


def test_all_roles_work_setup_filter(client):
    jobs = client.get("/api/jobs?limit=2000&lite=true").json()
    hybrid = client.get("/api/jobs?limit=2000&lite=true&work=hybrid").json()
    assert all(j["remote_type"] == "hybrid" for j in hybrid)
    assert len(hybrid) == sum(1 for j in jobs if j["remote_type"] == "hybrid")
    both = client.get("/api/jobs?limit=2000&lite=true&work=remote,hybrid").json()
    assert {j["remote_type"] for j in both} <= {"remote", "hybrid"}

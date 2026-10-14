"""Spring internship rules, parsers and the API. Postings below are real (trimmed) or modeled on real ones."""
from pathlib import Path

import pytest

from app.services import internships as I

FX = Path(__file__).parent / "fixtures"


def ev(title, desc="", loc="", **kw):
    return I.evaluate(I.InternInput(title=title, description=desc, location_text=loc, **kw))


def state(r, key):
    return next(c["state"] for c in r["checks"] if c["key"] == key)


# ----------------------------------------------------------------------------- field

@pytest.mark.parametrize("title,track", [
    ("Cyber Security Intern", "cyber"),
    ("IT Intern - Cyber Security PT", "cyber"),
    ("2027 Summer Internship - Cybersecurity", "cyber"),
    ("Data Engineer Intern - Enterprise Technology & Security", "data"),
    ("Data Analytics Intern", "data"),
    ("Business Intelligence Intern", "data"),
    ("Network Engineering Intern", "network"),
    ("Intern, Network Operations Center", "network"),
    ("College Intern - TechStop IT Help Desk", "it"),
    ("Product Management Intern - Global Merchant & Network Services", "other"),
    ("Securities Operations Intern", "other"),
    ("Accounting Intern", "other"),
])
def test_track_from_title(title, track):
    assert I.track_of(title).track == track


def test_generic_intern_title_uses_the_posting_text():
    desc = "You'll help the SOC triage phishing reports, tune SIEM alerts in Splunk and document incident response steps."
    assert I.track_of("College Intern", desc).track == "cyber"
    assert I.track_of("Intern", "Help with radiation licensing inspections.").track == "other"


# ----------------------------------------------------------------------------- pay

def test_pay_signals():
    assert I.pay_of("Hourly Pay Rate: $16.50 Grade: 01").label == "$16.50 an hour"
    assert I.pay_of("The hourly pay range for this position is $17-22.").hourly == 19.5
    assert I.pay_of("In addition to competitive pay and performance incentives...").status == "stated"
    assert I.pay_of("This is an unpaid internship for academic credit.").status == "unpaid"
    assert I.pay_of("Interns receive a $3,000 stipend for the semester.").label == "$3,000 stipend"
    assert I.pay_of("Help our team with dashboards.").status == "none"
    assert I.pay_of("", 18, 22, "hour").label == "$18 to $22 an hour"


# ----------------------------------------------------------------------------- hours

def test_hours():
    assert I.hours_of("The BRC intern will join our team for 52 weeks, working 19 hours each week.").label == "19 hours a week"
    h = I.hours_of("A minimum requirement of 30 hours and up to 40 hours per week maximum.")
    assert (h.status, h.low, h.high) == ("crosses", 30, 40)
    assert I.hours_of("Interns work up to 20 hrs/week during the semester.").status == "ok"
    assert I.hours_of("Must be a full-time student. Part-time role.").status == "part_time"
    assert I.hours_of("This is a full-time, 40 hours per week internship.").status == "too_many"
    assert I.hours_of("Respond to tickets within 24 hours.").status == "unknown"
    assert I.hours_of("", {"time_type": "Full time"}).status == "full_time"
    assert I.hours_of("Part-time (15-20 hours per week) during the school year, 40 hours per week in summer.").status == "ok"
    assert I.hours_of("Interns work 5 hours a week.").status == "too_few"


# ----------------------------------------------------------------------------- dates

def test_term():
    assert I.term_of("Data Analyst Intern", "For the spring 2027 semester.").status == "spring"
    assert I.term_of("Intern", "Join us for 52 weeks, working around your class schedule.").status == "school_year"
    assert I.term_of("2027 Summer Internship - Cybersecurity", "A 10-week program.").status == "summer"
    assert I.term_of("Intern", "This internship runs August through December 2026.").status == "fall"
    assert I.term_of("Intern", "", ["Spring 2027"]).status == "spring"
    assert I.term_of("Intern", "Help the team.").status == "unknown"


# ----------------------------------------------------------------------------- where

@pytest.mark.parametrize("loc,desc,status", [
    ("Tempe, AZ, US, 85280", "", "phoenix"),
    ("US-Arizona-Chandler", "", "phoenix"),
    ("Glendale, AZ", "", "phoenix"),
    ("Glendale, CA", "", "outside"),
    ("Costa Mesa, CA", "", "outside"),
    ("Tucson, AZ", "", "tucson"),
    ("Remote", "", "remote"),
    ("Phoenix", "100% Remote (must reside in Arizona).", "remote"),
    ("Remote", "Must reside in Texas.", "outside"),
    ("Arizona", "", "az_unknown"),
    ("United States", "", "unknown"),
    ("Seattle, WA; Mesa, AZ", "", "phoenix"),
])
def test_where(loc, desc, status):
    assert I.where_of(loc, desc).status == status


# ----------------------------------------------------------------------------- whole evaluation

def test_qualifying_state_cyber_internship():
    r = ev("Cyber Security Intern", "Hourly Pay Rate: $16.50. Cyber Command interns work up to 20 hours per week "
           "during the spring 2027 semester.", "PHOENIX, Arizona")
    assert r["status"] == "qualifies" and r["track"] == "cyber" and r["score"] >= 75


def test_no_pay_is_filtered_out_until_you_confirm_it():
    desc = "Part-Time. About 20 hours/week. 100% Remote (must reside in Arizona). Spring 2027."
    r = ev("IT Intern - Cyber Security PT", desc, "Phoenix")
    assert r["status"] == "out" and state(r, "pay") == "fail"
    r = ev("IT Intern - Cyber Security PT", desc, "Phoenix", overrides={"paid": True})
    assert r["status"] == "qualifies"


def test_missing_hours_or_dates_still_qualify_with_a_check():
    r = ev("Data Analyst Intern", "This is a paid internship. Build dashboards in Tableau.", "Tempe, AZ")
    assert r["status"] == "check" and state(r, "hours") == "warn" and state(r, "term") == "warn"


def test_full_time_summer_and_grad_internships_are_out():
    assert ev("Security Analyst Intern", "Competitive pay.", "Chandler, AZ", hints={"time_type": "Full time"})["status"] == "out"
    assert ev("Data Analytics Intern", "Our 10-week summer program pays $25/hour.", "Phoenix, AZ")["status"] == "out"
    assert ev("Data Scientist Intern - PhD", "Paid internship, 20 hours a week, spring 2027.", "Tempe, AZ")["status"] == "out"


def test_general_it_is_out_but_can_be_counted_anyway():
    desc = "SRP is recruiting a college student to work part-time. In addition to competitive pay... 20 hours per week."
    r = ev("College Intern - TechStop IT Help Desk", desc, "Tempe, AZ")
    assert r["status"] == "out" and state(r, "field") == "fail"
    assert ev("College Intern - TechStop IT Help Desk", desc, "Tempe, AZ", overrides={"include": True})["status"] != "out"


def test_real_posting_edge_cases():
    # Benefits text is not an unpaid internship
    boeing = "Boeing Summer 2027 Internship Program (Paid). Programs provide for both paid and unpaid time away from work."
    assert I.pay_of(boeing).status != "unpaid"
    assert I.pay_of("This is an unpaid internship.").status == "unpaid"
    # "Remote" in the location wins over "hybrid" in the company's boilerplate
    assert I.where_of("Remote, UNAVAILABLE", "We have remote, hybrid and in-person roles.").status == "remote"
    # Internships open only to students at other schools
    st, why = I.level_check("Collections Data Analyst Intern", "Must be enrolled at University of South Florida, "
                            "University of Tampa, or University of South Carolina to be eligible.")
    assert st == "fail" and why.endswith("University of South Carolina.")
    assert I.level_check("Intern", "Must be enrolled in an accredited college or university.")[0] == "pass"
    assert I.track_of("Data Center Design Intern").track == "network"
    assert I.track_of("Summer Internship (Paid) - Security & Fire Operation").track == "other"


def test_closed_posting_is_out():
    assert ev("Cyber Security Intern", "Paid, $18/hr, 20 hours per week, spring 2027.", "Phoenix, AZ",
              is_active=False)["status"] == "out"


# ----------------------------------------------------------------------------- parsers

def test_successfactors_parsers():
    from app.services.ats import parse_successfactors_job, parse_successfactors_search
    tiles = parse_successfactors_search((FX / "sf_search_tiles.html").read_text(), "https://careers.srpnet.com")
    assert tiles and tiles[0].title == "College Intern - TechStop IT Help Desk" and tiles[0].location_text == "Tempe, AZ"
    assert len({t.ats_job_id for t in tiles}) == len(tiles)
    rows = parse_successfactors_search((FX / "sf_search_rows.html").read_text(), "https://careers.aps.com")
    assert any("Cybersecurity" in r.title for r in rows) and rows[0].location_text == "Phoenix, AZ"
    job = parse_successfactors_job((FX / "sf_job.html").read_text(), tiles[0])
    assert job.location_text == "Tempe, AZ" and "part-time" in job.description and job.posted_at.year == 2026


def test_azstate_parsers():
    from app.services.ats import parse_azstatejobs_search, parse_jsonld_posting
    rows = parse_azstatejobs_search((FX / "azstate_search.html").read_text())
    assert len(rows) == 6 and rows[0]["department"] and "AZ" in rows[0]["location"]
    p = parse_jsonld_posting((FX / "azstate_job.html").read_text(), "https://example.gov/job")
    assert p.title == "Intern" and "19 hours each week" in p.description and p.extra["deadline"] == "2027-01-11"
    r = I.evaluate(I.InternInput(title=p.title, description=p.description, location_text=p.location_text))
    assert state(r, "pay") == "pass" and state(r, "hours") == "pass" and r["track"] == "other"


def test_workday_urls_both_host_styles():
    from app.services.ats import parse_ats_url, parse_workday_url, workday_endpoints
    u = "https://wd5.myworkdaysite.com/recruiting/microchiphr/External/job/AZ---Chandler/Intern_R1-26"
    assert parse_workday_url(u) == ("wd5.myworkdaysite.com", "microchiphr/External", "/job/AZ---Chandler/Intern_R1-26")
    assert parse_ats_url(u)[:3] == ("workday", "wd5.myworkdaysite.com", "microchiphr/External")
    assert workday_endpoints("wd5.myworkdaysite.com", "microchiphr/External")[0] == \
        "https://wd5.myworkdaysite.com/wday/cxs/microchiphr/External"
    assert parse_workday_url("https://intel.wd1.myworkdayjobs.com/en-us/external/job/US-Arizona-Phoenix/X_JR1")[1] == "external"


def test_feed_candidates():
    from app.services.intern_sources import feed_candidates
    base = {"active": True, "is_visible": True, "company_name": "X", "url": "https://x"}
    listings = [
        base | {"title": "Cybersecurity Intern", "terms": ["Spring 2027"], "locations": ["Tempe, AZ"]},
        base | {"title": "Data Analyst Intern", "terms": ["Summer 2027"], "locations": ["Phoenix, AZ"]},
        base | {"title": "Network Intern", "terms": ["N/A"], "locations": ["Remote in USA"]},
        base | {"title": "Software Engineer Intern", "terms": ["Spring 2027"], "locations": ["Tempe, AZ"]},
        base | {"title": "Security Intern", "terms": ["Spring 2027"], "locations": ["Seattle, WA"]},
    ]
    assert [x["title"] for x in feed_candidates(listings)] == ["Cybersecurity Intern", "Network Intern"]


# ----------------------------------------------------------------------------- API

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

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


def test_internship_api_flow(client, tmp_path):
    from tests.sample_resume import build
    with open(build(tmp_path / "r.docx"), "rb") as fh:
        assert client.post("/api/resume/upload", files={"file": ("r.docx", fh)}).status_code == 200
    body = {"company_name": "Desert Cyber Co", "title": "Cybersecurity Intern", "location": "Tempe, AZ",
            "description": "Paid internship at $20 per hour. Work 15-20 hours per week during the spring 2027 semester "
                           "on our SOC team: triage phishing reports, review SIEM alerts and document incidents. "
                           "Students studying cybersecurity or networking are encouraged to apply." * 2}
    it = client.post("/api/internships", json=body).json()
    assert it["intern"]["status"] == "qualifies" and it["intern"]["track"] == "cyber"
    unpaid = client.post("/api/internships", json=body | {"title": "Network Intern", "description":
                                                           "Help with switches and VLANs, 20 hours per week, spring 2027."}).json()
    assert unpaid["intern"]["status"] == "out"
    lst = client.get("/api/internships").json()
    assert lst["counts"]["qualifies"] >= 1 and lst["links"] and lst["prefs"]["hours_max"] == 30
    # Internships stay off the sales job lists
    assert all(j["family"] != "internship" for j in client.get("/api/jobs?limit=2000&lite=true").json())
    # Your own confirmation moves it into the list
    fixed = client.patch(f"/api/internships/{unpaid['id']}", json={"paid": True}).json()
    assert fixed["intern"]["status"] == "qualifies"
    home = client.get("/api/home").json()
    assert home["tiles"][0]["key"] == "interns" and home["tiles"][0]["count"] >= 2
    # Apply page: internship tailoring and drafts
    a = client.post(f"/api/apply/{it['id']}", json={}).json()
    assert a["is_intern"] and a["draft_labels"][1][0] == "hiring_manager"
    assert "spring" in a["drafts"]["recruiter_connect"] and len(a["drafts"]["recruiter_connect"]) <= 200
    assert any(t["term"] in ("SIEM", "Incident response", "Cybersecurity") for t in a["ats"]["terms"])
    # Full package: internship questions and readiness
    from app.db import SessionLocal
    from app.models import Job
    from app.services import prep
    db = SessionLocal()
    app = prep.prepare(db, db.get(Job, it["id"]), lambda *x: None)
    assert "Credit approved" in app.readiness["components"]
    assert any(c["key"] == "credit" for c in app.readiness["checklist"])
    db.close()
    page = client.get(f"/api/applications/{app.id}").json()
    kinds = {d["kind"] for d in page["docs"]}
    assert {"availability", "why_field", "cover_letter"} <= kinds and "why_se" not in kinds
    cl = next(d for d in page["docs"] if d["kind"] == "cover_letter")["content"]
    assert "spring 2027" in cl and "sales engineering" not in cl.lower()


def test_profile_change_refreshes_resume_checks(client):
    prof = client.get("/api/profile").json()["data"]
    skills = dict(prof.get("skills") or {})
    skills["programming"] = (skills.get("programming", "") + ", Haskell").strip(", ")
    client.put("/api/profile", json={"data": prof | {"skills": skills}})
    checks = client.get("/api/resume").json()["master"]["checks"]
    assert any("Haskell" in c["message"] for c in checks)
    skills["programming"] = skills["programming"].replace(", Haskell", "")
    client.put("/api/profile", json={"data": prof | {"skills": skills}})
    checks = client.get("/api/resume").json()["master"]["checks"]
    assert not any("Haskell" in c["message"] for c in checks)


def test_profile_updates_folder(client, tmp_path, monkeypatch):
    import json

    from app import migrations
    from app.config import settings
    from app.db import SessionLocal
    from app.services.profile import get_profile
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "profile-updates").mkdir()
    db = SessionLocal()
    prof = get_profile(db)
    prof.data = dict(prof.data or {}) | {"skills": {"programming": "Java, Go, Scheme, SQL", "data_ai": "JSON, CSV, Git"}}
    db.commit()
    (tmp_path / "profile-updates" / "a.json").write_text(json.dumps({"id": "a", "remove_skills": ["go", "Scheme", "JSON", "CSV"]}))
    assert migrations.apply_profile_updates(db) == 1
    assert get_profile(db).data["skills"] == {"programming": "Java, SQL", "data_ai": "Git"}
    assert migrations.apply_profile_updates(db) == 0  # applied once
    db.close()


def test_search_runs_offline_against_saved_pages(client, monkeypatch):
    """The whole internship search, with every network call answered from saved pages."""
    import json

    import httpx

    from app.services import intern_sources as S
    from app.services.fetch import PoliteFetcher

    gh = {"jobs": [{"id": 901, "title": "Cybersecurity Intern (Spring 2027)", "absolute_url": "https://job-boards.greenhouse.io/desertco/jobs/901",
                    "location": {"name": "Scottsdale, AZ"}, "content": "&lt;p&gt;Paid internship, $21 per hour, 15-20 hours per week "
                    "from January to May 2027. Help our SOC review SIEM alerts and phishing reports.&lt;/p&gt;" * 3},
                   {"id": 902, "title": "Account Executive", "absolute_url": "https://x/902", "location": {"name": "Remote"}, "content": ""}]}
    wd_list = {"total": 1, "jobPostings": [{"title": "Network Engineering Intern", "externalPath": "/job/Tempe/Network-Intern_R1",
                                            "locationsText": "Tempe, AZ", "postedOn": "Posted Today"}]}
    wd_job = {"jobPostingInfo": {"title": "Network Engineering Intern", "jobDescription": "<p>Part-time, up to 25 hours a week during "
              "the spring 2027 semester. The hourly pay range is $18-24. Configure switches and VLANs.</p>" * 3,
              "location": "Tempe, AZ", "timeType": "Part time", "jobReqId": "R1",
              "externalUrl": "https://acme.wd1.myworkdayjobs.com/External/job/Tempe/Network-Intern_R1"}}
    pages = {"careers.srpnet.com/search": (FX / "sf_search_tiles.html").read_text(),
             "careers.srpnet.com/job": (FX / "sf_job.html").read_text(),
             "azstatejobs.gov/jobs/search?page=1": (FX / "azstate_search.html").read_text(),
             "azstatejobs.gov/jobs/": (FX / "azstate_job.html").read_text()}

    def get_json(self, url, **kw):
        if "boards-api.greenhouse.io" in url:
            return gh
        if "/wday/cxs/" in url:
            return wd_job
        raise httpx.ConnectError("offline")

    def post_json(self, url, body, **kw):
        return wd_list if body.get("searchText") == "intern" else {"total": 0, "jobPostings": []}

    def get_text(self, url, max_bytes=2_000_000):
        for k, v in pages.items():
            if k in url and (k != "careers.srpnet.com/search" or "startrow=0" in url):
                return v
        if "careers.srpnet.com/search" in url or "azstatejobs.gov/jobs/search" in url:
            return "<html></html>"
        raise httpx.ConnectError("offline")

    feed = [{"active": True, "is_visible": True, "company_name": "Desert Co", "title": "Cybersecurity Intern (Spring 2027)",
             "terms": ["Spring 2027"], "locations": ["Scottsdale, AZ"], "url": "https://job-boards.greenhouse.io/desertco/jobs/901"}]

    class Resp:
        def __init__(self, data, code=200):
            self.data, self.status_code = data, code

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    monkeypatch.setattr(PoliteFetcher, "get_json", get_json)
    monkeypatch.setattr(PoliteFetcher, "post_json", post_json)
    monkeypatch.setattr(PoliteFetcher, "get_text", get_text)
    monkeypatch.setattr(PoliteFetcher, "_wait", lambda self, host: None)
    monkeypatch.setattr(S.httpx, "get", lambda url, **kw: Resp(feed) if "githubusercontent" in url else Resp({}, 404))
    monkeypatch.setattr(S, "load_boards", lambda: [
        {"name": "Desert Co", "ats_type": "greenhouse", "token": "desertco"},
        {"name": "Acme", "ats_type": "workday", "host": "acme.wd1.myworkdayjobs.com", "site": "External"},
        {"name": "SRP", "ats_type": "successfactors", "base": "https://careers.srpnet.com"},
        {"name": "State of Arizona", "ats_type": "azstatejobs", "base": "https://www.azstatejobs.gov"}])
    run = client.post("/api/workflows/find_internships", json={}).json()["run_id"]
    import time
    for _ in range(100):
        r = client.get(f"/api/runs/{run}").json()
        if r["status"] != "running":
            break
        time.sleep(0.1)
    assert r["status"] == "done", r.get("error")
    titles = {i["title"]: i["intern"]["status"] for i in client.get("/api/internships").json()["items"]}
    assert titles.get("Cybersecurity Intern (Spring 2027)") == "qualifies"
    assert titles.get("Network Engineering Intern") == "qualifies"
    assert "Account Executive" not in titles
    assert titles.get("College Intern - TechStop IT Help Desk") == "out"  # SRP: general IT
    steps = [s["status"] for s in r["view"]["steps"]]
    assert steps == ["done"] * 5, json.dumps(r["view"]["steps"])[:600]

"""Spring Sales Internships: a second list beside Applied Computing Spring Internships."""
import pytest
from fastapi.testclient import TestClient

from app.services.internships import InternInput, evaluate, is_sales_title, pay_of, tech_tier, track_of

SPRING = ("Spring 2027 internship, January through May 2027. Part-time, 20 hours per week. "
          "Pay: $18 per hour. ")


@pytest.mark.parametrize("title,track", [
    ("Sales Intern", "sales"),
    ("Sales Development Representative Intern (Spring 2027)", "sales"),
    ("SDR Intern", "sales"),
    ("BDR Intern - Part Time", "sales"),
    ("Account Executive Intern", "sales"),
    ("Sales Engineering Intern - Cybersecurity", "sales"),
    ("Solutions Engineer Intern", "sales"),
    ("Presales Intern", "sales"),
    ("Inside Sales Intern", "sales"),
    ("Business Development Representative Intern", "sales"),
    ("Salesforce Developer Intern", "other"),
    ("Point of Sale Support Intern", "other"),
    ("Cybersecurity Intern", "cyber"),
    ("Data Analyst Intern, Sales Operations", "data"),
    ("Sales Data Analytics Intern", "data"),
    ("Cybersecurity Sales Intern", "sales"),
    ("Account Development Representative Intern - Phoenix", "sales"),
    ("Sales Intern - ASU", "sales"),
])
def test_sales_titles(title, track):
    assert track_of(title).track == track


def test_commission_only_is_not_paid_enough():
    assert pay_of("This is a commission-only internship with uncapped earnings.").status == "commission"
    assert pay_of("Earnings are based on commission.").status == "commission"
    assert pay_of("Base pay of $18/hour plus commission.").status == "amount"
    assert pay_of("$17 per hour, with commission-based bonuses.").status == "amount"


def test_tech_tiers():
    assert tech_tier("cybersecurity")[0] == 1
    assert tech_tier(None, "We are a SaaS company building cloud security for small businesses.")[0] == 1
    assert tech_tier(None, "A semiconductor and electronics distributor.")[0] == 2
    assert tech_tier(None, "A family-owned insurance agency.")[0] == 0


def _eval(title, text, category=None, name="Acme"):
    return evaluate(InternInput(title=title, description=text, location_text="Tempe, AZ", company_category=category,
                                company_name=name))


def test_sales_internship_rules():
    good = _eval("Sales Development Intern", SPRING + "Join our cybersecurity software sales team.", "cybersecurity")
    assert good["status"] == "qualifies" and good["track"] == "sales" and good["tech_tier"] == 1
    hardware = _eval("Sales Intern", SPRING + "We sell networking hardware and IT solutions.")
    assert hardware["status"] == "qualifies" and hardware["tech_tier"] == 2
    assert good["score"] > hardware["score"]  # security and software first
    unsure = _eval("Sales Intern", SPRING + "Help our team grow.")
    assert unsure["status"] == "check" and unsure["tech_tier"] == 0
    commission = _eval("Sales Intern", "Spring 2027, January to May. Part-time, 20 hours per week. "
                                       "Commission-only pay with uncapped earnings. Software company.")
    assert commission["status"] == "out" and any("Commission only" in r for r in commission["reasons_out"])
    summer = _eval("Sales Intern", "Summer 2027 internship, June to August. Full-time, 40 hours per week. $20 per hour. "
                                   "SaaS company.")
    assert summer["status"] == "out"


@pytest.fixture(scope="module")
def client():
    import app.models  # noqa: F401
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


def test_two_lists(client, tmp_path, monkeypatch):
    import json

    from app.config import settings
    from app.db import SessionLocal
    from app.models import Company, Job
    from app.services import intern_jobs as IJ
    from app.util import slugify
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db = SessionLocal()
    try:
        made = {}
        for name, title, cat, text in [
            ("Shieldworks", "Sales Development Intern", "cybersecurity", SPRING + "Cybersecurity platform."),
            ("Chipco", "Sales Intern", None, SPRING + "A semiconductor company."),
            ("Desert Data", "Data Analyst Intern", None, SPRING + "SQL, Excel and Tableau dashboards."),
        ]:
            c = Company(name=name, slug=slugify(name), category=cat)
            db.add(c)
            db.flush()
            j = Job(company=c, title=title, url=f"https://example.com/{slugify(name)}", description_text=text,
                    fingerprint=f"test-{slugify(name)}",
                    location_text="Tempe, AZ", is_active=True, source_is_original=True)
            db.add(j)
            db.flush()
            IJ.evaluate_job(db, j)
            made[name] = j.id
        db.commit()
        IJ.write_report(db)
        report = json.loads((tmp_path / "reports" / "internships.json").read_text())
    finally:
        db.close()
    sales = client.get("/api/internships?program=sales").json()
    applied = client.get("/api/internships").json()
    s_ids = [i["id"] for i in sales["items"]]
    a_ids = {i["id"] for i in applied["items"]}
    assert s_ids.index(made["Shieldworks"]) < s_ids.index(made["Chipco"])  # security tech first
    assert made["Desert Data"] in a_ids and made["Desert Data"] not in s_ids
    assert made["Shieldworks"] not in a_ids
    assert sales["title"] == "Spring Sales Internships" and applied["title"] == "Applied Computing Spring Internships"
    assert sales["links"][0]["searches"][0]["label"] == "Sales"
    assert next(i for i in sales["items"] if i["id"] == made["Shieldworks"])["intern"]["tech_tier"] == 1
    listed = {x["job_id"] for x in report["lists"]["sales"]["items"]}
    assert {made["Shieldworks"], made["Chipco"]} <= listed
    assert made["Desert Data"] in {x["job_id"] for x in report["lists"]["applied"]["items"]}


def test_search_keeps_sales_candidates():
    from app.services.intern_sources import candidate
    assert candidate("Sales Development Intern", "Remote, US")
    assert candidate("Sales Intern", "Tempe, AZ")
    assert not candidate("Sales Intern", "Dallas, TX")
    assert is_sales_title("Account Executive Intern") and not is_sales_title("Salesforce Admin Intern")


def _rippling_page(page_props):
    import json
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": page_props}, "page": "/x"}) + "</script></body></html>")


def test_rippling_board_and_posting():
    from app.services.ats import parse_ats_url, parse_rippling_board, parse_rippling_job
    board = _rippling_page({"dehydratedState": {"queries": [
        {"queryKey": ["board", "uplinq", "locations"], "state": {"data": {"items": []}}},
        {"queryKey": ["board", "uplinq", "job-posts", False, {"page": 0}, "en-US"], "state": {"data": {
            "items": [{"id": "d448-uuid", "name": "Sales Intern - ASU", "url": "https://ats.rippling.com/uplinq/jobs/d448-uuid",
                       "department": {"name": "Sales"},
                       "locations": [{"name": "Scottsdale, AZ", "workplaceType": "ON_SITE"}]}],
            "totalPages": 1}}}]}})
    jobs, pages = parse_rippling_board(board)
    assert pages == 1 and jobs[0]["title"] == "Sales Intern - ASU" and jobs[0]["workplace"] == "onsite"
    assert jobs[0]["locations"] == "Scottsdale, AZ"
    with pytest.raises(ValueError):  # a changed page never reads as an empty board
        parse_rippling_board("<html></html>")
    url = "https://ats.rippling.com/uplinq/jobs/d448-uuid"
    post = _rippling_page({"apiData": {
        "jobPost": {"uuid": "d448-uuid", "name": "Sales Intern - ASU",
                    "description": {"company": "<p>Uplinq is an AI-powered bookkeeping and tax company.</p>",
                                    "role": "<p>15 to 20 hours a week. One semester, starting January 11, 2027.</p>"}},
        "workLocations": ["Scottsdale, AZ"],
        "payRangeDetails": [{"currency": "USD", "frequency": "HOUR", "rangeStart": 20, "rangeEnd": 24}]}})
    p = parse_rippling_job(post, url)
    assert p.title == "Sales Intern - ASU" and (p.comp_min, p.comp_max, p.comp_period) == (20, 24, "hour")
    assert "AI-powered" in p.description and "January 11, 2027" in p.description
    assert parse_rippling_job(board, url) is None  # a job that's gone shows the board: closed
    assert parse_ats_url(url) == ("rippling", "uplinq", "d448-uuid")
    assert parse_ats_url("https://ats.rippling.com/en-US/uplinq/jobs/d448-uuid") == ("rippling", "uplinq", "d448-uuid")


def test_rippling_check_closed(monkeypatch):
    from types import SimpleNamespace

    from app.services import intern_verify as V
    monkeypatch.setattr("app.services.ats.rippling_job", lambda f, t, j: None)
    job = SimpleNamespace(url="https://ats.rippling.com/uplinq/jobs/gone", apply_url=None, title="Sales Intern - ASU",
                          deadline=None, description_text="", company=None)
    assert V.check(None, job).state == "closed"


def test_sales_boards_seeded():
    import json
    from pathlib import Path
    boards = json.loads((Path(__file__).parents[1] / "seed" / "intern_boards.json").read_text())["boards"]
    keys = [(b["ats_type"], b.get("token") or f'{b.get("host") or b.get("base")}/{b.get("site") or ""}') for b in boards]
    assert ("rippling", "uplinq") in keys and ("greenhouse", "samsara") in keys
    assert len(keys) == len(set(keys))


def test_same_internship_posted_twice_shows_once(client):
    from app.db import SessionLocal
    from app.models import Company, Job
    from app.services import intern_jobs as IJ
    db = SessionLocal()
    try:
        c = Company(name="Fleetco", slug="fleetco", category="software")
        db.add(c)
        db.flush()
        ids = []
        for n in range(3):
            j = Job(company=c, title="Account Development Representative Intern - Phoenix", url=f"https://example.com/fleet/{n}",
                    description_text=SPRING + "SaaS sales.", fingerprint=f"fleet-{n}", location_text="Phoenix, AZ",
                    is_active=True, source_is_original=True)
            db.add(j)
            db.flush()
            IJ.evaluate_job(db, j)
            ids.append(j.id)
        db.commit()
        jobs, _ = IJ.board(db, "sales")
        assert len([j for j in jobs if j.id in ids]) == 1
        db.get(Job, ids[0]).is_active = False  # one copy closing doesn't hide the others
        db.commit()
        jobs, _ = IJ.board(db, "sales")
        assert len([j for j in jobs if j.id in ids]) == 1
    finally:
        db.close()

import json
from pathlib import Path

from app.services.ats import parse_ashby, parse_ats_url, parse_greenhouse, parse_lever
from app.services.discovery import is_relevant
from app.util import fingerprint

F = Path(__file__).parent / "fixtures"


def test_greenhouse_parse_and_filter():
    jobs = parse_greenhouse(json.loads((F / "greenhouse.json").read_text()))
    assert jobs[0].ats_job_id == "4135267007" and "Verkademy" in jobs[0].description and "$55,000" in jobs[0].description
    assert [is_relevant(j.title, j.description) for j in jobs] == [True, False]


def test_lever_and_ashby():
    lv = parse_lever(json.loads((F / "lever.json").read_text()))[0]
    assert lv.comp_min == 90000 and lv.workplace == "hybrid" and "Python" in lv.description
    ab = parse_ashby(json.loads((F / "ashby.json").read_text()))[0]
    assert ab.comp_max == 100000 and ab.workplace == "hybrid" and "Phoenix" in ab.location_text


def test_ats_url_parsing():
    assert parse_ats_url("https://job-boards.greenhouse.io/verkada/jobs/4135267007") == ("greenhouse", "verkada", "4135267007")
    assert parse_ats_url("https://jobs.lever.co/acme/abc-123")[0:2] == ("lever", "acme")
    assert parse_ats_url("https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers/job/x_1") == ("workday", "cisco.wd5.myworkdayjobs.com", "Cisco_Careers")


def test_fingerprint_dedup():
    a = fingerprint("Verkada", "SDR", "4135267007", "https://x/1")
    assert a == fingerprint("Verkada", "SDR (renamed)", "4135267007", "https://x/2")
    assert fingerprint("Verkada", "SDR", None, "https://x/1?utm=a") == fingerprint("Verkada", "SDR", None, "https://x/1")

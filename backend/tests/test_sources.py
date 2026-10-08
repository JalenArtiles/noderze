import time

from app.services.ats import parse_ats_url, parse_jobvite_html
from app.services.sources import build_directory, location_ok, parse_adzuna, parse_muse, parse_simplify


def test_embed_and_jobvite_urls():
    assert parse_ats_url("https://boards.greenhouse.io/embed/job_app?for=databricks&token=123") == ("greenhouse", "databricks", "123")
    assert parse_ats_url("https://jobs.jobvite.com/varonis/job/okDbvfwn") == ("jobvite", "varonis", "okDbvfwn")


def test_jobvite_html():
    html = ('<tr><td class="jv-job-list-name"><a href="/varonis/job/oAbc123">Sales Development Representative</a></td>'
            '<td class="jv-job-list-location">Phoenix, Arizona</td></tr>')
    p = parse_jobvite_html(html, "varonis")[0]
    assert p.title == "Sales Development Representative" and p.location_text == "Phoenix, Arizona" and p.ats_job_id == "oAbc123"


def test_location_filter():
    assert location_ok("Tempe, AZ") and location_ok("Remote in USA") and location_ok("")
    assert not location_ok("London, UK") and not location_ok("Chicago, IL")


def test_simplify_feed_and_directory():
    now = time.time()
    rows = [{"company_name": "Nerdio", "title": "Solutions Engineer - Early Career", "active": True, "is_visible": True,
             "date_posted": now - 86400, "url": "https://jobs.lever.co/nerdio/abc?utm_source=Simplify", "locations": ["Remote in USA"]},
            {"company_name": "Acme", "title": "Senior Sales Engineer", "active": True, "is_visible": True, "date_posted": now,
             "url": "https://job-boards.greenhouse.io/acme/jobs/1", "locations": ["Phoenix, AZ"]},
            {"company_name": "Old", "title": "Sales Engineer", "active": True, "is_visible": True, "date_posted": now - 400 * 86400,
             "url": "https://x", "locations": ["Phoenix, AZ"]}]
    leads = parse_simplify(rows)
    assert [c for c, _ in leads] == ["Nerdio"] and "utm_source" not in leads[0][1].url
    d = {e["name"]: e for e in build_directory(rows)}
    assert d["Nerdio"]["ats_type"] == "lever" and d["Acme"]["token"] == "acme"


def test_aggregator_parsers():
    muse = parse_muse({"results": [{"name": "Sales Development Representative", "company": {"name": "Acme"},
                                     "locations": [{"name": "Phoenix, AZ"}], "refs": {"landing_page": "https://x"},
                                     "contents": "<p>Prospect</p>", "publication_date": "2026-09-20T00:00:00Z"}]})
    assert muse[0][0] == "Acme" and muse[0][1].location_text == "Phoenix, AZ"
    adz = parse_adzuna({"results": [{"title": "Sales <strong>Engineer</strong>", "company": {"display_name": "Acme"},
                                      "location": {"display_name": "Tempe, Maricopa County"}, "redirect_url": "https://y",
                                      "description": "x", "salary_min": 70000, "salary_max": 90000, "created": "2026-09-25T10:00:00Z"}]})
    assert adz[0][1].title == "Sales Engineer" and adz[0][1].comp_min == 70000

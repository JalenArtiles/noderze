from app.services import keywords as K
from app.services.classify import sales_level
from app.services.recruiters import linkedin_links, parse_connections_csv

POSTING = ("As an SDR you will prospect and cold call into enterprise accounts, qualify leads using BANT, book meetings for "
           "Account Executives, and log activity in Salesforce. Experience with Outreach or Salesloft is a plus. You are "
           "coachable, resilient and an excellent communicator. Interest in cybersecurity required.")


def test_keyword_extraction_and_support():
    terms = {t["term"]: t for t in K.screened_terms(POSTING)}
    for t in ("Cold calling", "Prospecting", "Lead qualification", "Booking meetings", "Salesforce", "Coachable", "Cybersecurity"):
        assert t in terms
    evidence = "Generated new business through cold calling, referrals, lead generation, and prospecting. Tracked intelligence using CRM tools."
    assert K.supported("Cold calling", evidence, []) and K.supported("CRM", evidence, [])
    assert not K.supported("Salesforce", evidence, [])
    assert K.supported("Salesforce", evidence, ["Salesforce"])  # only after the user confirms it


def test_coverage_and_typical_fallback():
    terms = K.screened_terms("Sales Development Representative")
    assert any(t["typical"] for t in terms)
    assert 0 <= K.coverage(terms, "cold calling and prospecting") <= 100


def test_sales_levels():
    assert sales_level("Territory Development Representative").startswith("Development rep")
    assert sales_level("Commercial Account Executive") == "Account executive"


def test_linkedin_helpers():
    links = linkedin_links("Varonis")
    assert all(l["url"].startswith("https://www.linkedin.com/") for l in links) and any("ASU" in l["label"] for l in links)
    csv_text = ("Notes:\n\"When exporting your connection data...\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                "Ana,Lopez,https://www.linkedin.com/in/ana,ana@x.com,Varonis,Sales Development Representative,01 Sep 2026\n")
    rows = parse_connections_csv(csv_text)
    assert rows == [{"name": "Ana Lopez", "url": "https://www.linkedin.com/in/ana", "company": "Varonis",
                     "position": "Sales Development Representative", "connected_on": "01 Sep 2026"}]

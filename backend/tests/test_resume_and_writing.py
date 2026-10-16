from app.services.resume import claim_check
from app.services.writing import style_check
from app.util import clean_dashes

LEDGER = [{"id": "experience-1", "text": "Generated new business through cold calling and prospecting", "section": "experience",
           "kind": "bullet", "index": 1, "role": None}]


def test_claim_check_flags_inventions():
    flags = claim_check("Generated new business", "Generated $2M in new business as an AWS expert", LEDGER, {})
    assert any("2M" in f or "$2M" in f for f in flags)
    assert any("aws" in f.lower() for f in flags)
    assert any("expert" in f.lower() for f in flags)
    assert claim_check("x", "Generated new business through cold calling", LEDGER, {}) == []


def test_style_guard_removes_em_dashes_and_flags_cliches():
    text, flags = style_check("I am thrilled \u2014 truly passionate about this dynamic role.", "answer")
    assert "\u2014" not in text
    assert any("thrilled" in f for f in flags) and any("dynamic" in f for f in flags)
    assert clean_dashes("May 2025 \u2013 Aug 2025") == "May 2025 - Aug 2025"


def test_connection_note_limit():
    _, flags = style_check("x" * 250, "recruiter_connect")
    assert any("limit" in f for f in flags)


def test_cover_letter_follows_the_chosen_pattern(tmp_path):
    """Formal, no contractions, courses as a foundation, roles by what they taught, the fixed close, and never
    availability, hours, credit or an assessment."""
    import json
    import re
    from pathlib import Path

    from app.services import resume as R
    from app.services import writing as W
    from tests.sample_resume import build
    parsed = R.parse_docx(build(tmp_path / "r.docx"))
    prof = json.loads((Path(__file__).parents[1] / "seed" / "profile.example.json").read_text())
    ctx = {"profile": prof, "ledger": R.build_ledger(parsed), "contact": parsed["contact"], "company_facts": [],
           "analysis": None, "program": None, "company": "Acme Security", "job_title": "Security Analyst Intern",
           "job_text": "Assist the SOC with network security monitoring. 20 hours a week. Technical assessment required.",
           "mode": "intern", "track": "cyber"}
    text, _ = W.intern_cover_letter(ctx)
    lines = text.split("\n")
    assert lines[0] == prof["name"] and "@" in lines[1] and "Tempe, AZ" in lines[1]
    assert "Dear Acme Security Hiring Team," in text
    assert "I am excited to apply for the Spring 2027 Security Analyst Intern at Acme Security." in text
    assert "I have begun building a foundation in cybersecurity and networking" in text
    assert "open-minded and adaptable" in text and "eager to be taught" in text
    assert "taught me the importance of communication" in text
    assert "technical background, work ethic, and eagerness to learn" in text
    assert text.rstrip().endswith("Sincerely,\n" + prof["name"])
    assert not re.search(r"\b\w+'(m|re|ve|ll|d)\b|n't\b", text), "no contractions"
    assert not re.search(r"assessment|hours a week|credit", text, re.I)
    assert "—" not in text and W.style_check(text, "cover_letter")[1] == []
    ctx |= {"mode": None, "track": None, "company": "Verkada", "job_title": "Associate Sales Engineer"}
    se, _ = W.cover_letter(ctx)
    assert "the Associate Sales Engineer role at Verkada" in se and "graduating in May 2027" in se
    assert W._scrub("I can start in January. I am happy to take the technical assessment.") == "I can start in January."

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

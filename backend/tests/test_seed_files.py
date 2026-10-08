"""Personal data lives in gitignored files; the public seed data must work without them."""
import json
from pathlib import Path

import scripts.seed_db as seed_db
from app.services import profile as profile_mod

BACKEND = Path(__file__).resolve().parent.parent


def test_example_profile_is_used_when_no_personal_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_mod, "SEED_PROFILE", tmp_path / "missing.json")
    data = profile_mod.load_seed_profile()
    assert data["name"] == "Sample Candidate" and data["expected_graduation"]


def test_personal_profile_wins_over_example(monkeypatch, tmp_path):
    own = tmp_path / "profile.json"
    own.write_text(json.dumps({"name": "Someone Real"}))
    monkeypatch.setattr(profile_mod, "SEED_PROFILE", own)
    assert profile_mod.load_seed_profile()["name"] == "Someone Real"


def test_personal_notes_overlay_merges_over_public_research(monkeypatch, tmp_path):
    companies = [{"name": "Acme", "watch_note": None, "data": {"standout": [{"action": "public"}], "product": "x"},
                  "programs": [{"name": "SE Academy", "data": {"concerns": ["public concern"]}}]},
                 {"name": "Other", "watch_note": "kept"}]
    (tmp_path / "companies.json").write_text(json.dumps(companies))
    (tmp_path / "personal.json").write_text(json.dumps({"companies": {"Acme": {
        "watch_note": "my note", "data": {"standout": [{"action": "mine"}]},
        "programs": {"SE Academy": {"data": {"concerns": ["my concern"]}}}}}}))
    monkeypatch.setattr(seed_db, "SEED", tmp_path)
    acme, other = seed_db.load_companies()
    assert acme["watch_note"] == "my note"
    assert acme["data"] == {"standout": [{"action": "mine"}], "product": "x"}  # lists replace, dicts merge
    assert acme["programs"][0]["data"]["concerns"] == ["my concern"]
    assert other["watch_note"] == "kept"


def test_without_personal_notes_the_public_file_loads_unchanged(monkeypatch, tmp_path):
    (tmp_path / "companies.json").write_text(json.dumps([{"name": "Acme"}]))
    monkeypatch.setattr(seed_db, "SEED", tmp_path)
    assert seed_db.load_companies() == [{"name": "Acme"}]


def test_private_files_are_gitignored():
    ignored = (BACKEND.parent / ".gitignore").read_text().splitlines()
    for entry in ("backend/seed/profile.json", "backend/seed/personal.json", "backend/data/", "backend/.env", "logs/"):
        assert entry in ignored, entry

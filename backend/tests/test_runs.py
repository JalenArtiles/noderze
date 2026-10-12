"""Run logs become clean steps for the interface: a plan, one result line per step, warnings, and details."""
from app.models import SearchRun
from app.workflows import run_view


def _run(log, status="done", error=None, result=None):
    return SearchRun(kind="full_company_analysis", status=status, log=log, error=error, result=result or {})


def test_steps_follow_the_plan():
    log = [{"type": "plan", "steps": ["Research", "Scan", "Score"]},
           {"type": "step", "step": 0}, {"type": "skip", "msg": "Skipped: needs a search provider", "step": 0},
           {"type": "step", "step": 1}, {"msg": "Acme: 61 postings", "level": "info", "step": 1},
           {"msg": "Workday search blocked", "level": "warn", "step": 1},
           {"type": "result", "msg": "18 roles that fit", "step": 1},
           {"type": "step", "step": 2}]
    v = run_view(_run(log, status="running"))
    research, scan, score = v["steps"]
    assert research["status"] == "skipped" and research["summary"].startswith("Skipped")
    assert scan["status"] == "done" and scan["summary"] == "18 roles that fit"
    assert scan["warnings"] == ["Workday search blocked"] and "Acme: 61 postings" in scan["lines"]
    assert score["status"] == "running"
    assert v["progress"] == {"done": 2, "total": 3}


def test_finished_run_closes_open_steps():
    log = [{"type": "plan", "steps": ["A", "B"]}, {"type": "step", "step": 0}, {"msg": "working", "step": 0}]
    v = run_view(_run(log, status="done", result={"highlights": [{"label": "New roles", "value": 3}]}))
    assert [s["status"] for s in v["steps"]] == ["done", "skipped"]
    assert v["highlights"][0]["value"] == 3


def test_failure_is_shown_on_the_step_that_failed():
    log = [{"type": "plan", "steps": ["A", "B", "C"]}, {"type": "step", "step": 0}, {"type": "result", "msg": "ok", "step": 0},
           {"type": "step", "step": 1}]
    v = run_view(_run(log, status="failed", error="ValueError: boom"))
    assert [s["status"] for s in v["steps"]] == ["done", "failed", "not_run"]
    assert v["steps"][1]["summary"] == "ValueError: boom"


def test_runs_logged_before_steps_existed_still_render():
    v = run_view(_run([{"msg": "Step 1/7: research"}, {"msg": "Acme: 3 relevant of 9 postings"}]))
    assert len(v["steps"]) == 1 and v["steps"][0]["status"] == "done"
    assert v["steps"][0]["summary"] == "Acme: 3 relevant of 9 postings"


def test_research_without_a_search_provider_is_skipped_with_a_way_forward():
    from app.db import Base, SessionLocal, engine
    Base.metadata.create_all(engine)
    from app.models import Company
    from app.workflows import WORKFLOWS, run_sync
    db = SessionLocal()
    c = Company(name="Runview Test Co", slug="runview-test-co", category="cybersecurity")
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    run = run_sync("deep_research", "Runview Test Co", WORKFLOWS["deep_research"], company_id=cid)
    v = run_view(run)
    assert run.status == "done"
    assert v["steps"][0]["status"] == "skipped" and v["steps"][1]["status"] == "done"
    assert v["notices"] and v["notices"][0]["action"]["href"].startswith("/settings")

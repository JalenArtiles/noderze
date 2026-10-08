from datetime import date

from app.services.classify import apply_window, grad_compat

G, T = date(2027, 5, 15), date(2026, 10, 8)


def test_apply_window_for_entry_sales():
    assert apply_window(date(2027, 8, 1)) == (date(2027, 5, 1), date(2027, 7, 1))
    assert apply_window(date(2027, 2, 1)) == (date(2026, 11, 1), date(2027, 1, 1))
    st, why = grad_compat("Sales Development Representative", "Prospect and qualify leads.", G, T, date(2027, 8, 1))
    assert st == "eligible_closer" and "May to July 2027" in why
    st, _ = grad_compat("Sales Development Representative", "", G, date(2027, 5, 20), date(2027, 8, 1))
    assert st == "eligible_now"
    # dated programs keep their own answer
    assert grad_compat("Solutions Architect, AWSI - 2027", "Start dates are tentatively set to occur January 4 and "
                       "July 6 of 2027.", G, T, date(2027, 8, 1))[0] == "likely_may_2027"
    assert grad_compat("Sales Engineer", "5+ years of experience required", G, T)[0] == "requires_experience"


def test_sqlite_runs_in_wal_mode():
    from sqlalchemy import text

    from app.db import IS_SQLITE, engine
    if IS_SQLITE:
        with engine.connect() as c:
            assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert c.execute(text("PRAGMA busy_timeout")).scalar() == 30000


def test_runs_single_flight_and_interrupted_cleanup():
    import threading

    from app.db import Base, SessionLocal, engine
    from app.models import SearchRun
    from app.workflows import mark_interrupted_runs, start
    Base.metadata.create_all(engine)
    gate = threading.Event()

    def slow(db, log):
        gate.wait(5)
        return {}

    a = start("discover_jobs", None, slow)
    b = start("discover_jobs", None, slow)
    assert a == b  # the second click joins the running scan
    gate.set()
    for _ in range(50):
        db = SessionLocal()
        st = db.get(SearchRun, a).status
        db.close()
        if st != "running":
            break
        threading.Event().wait(0.1)
    assert st == "done"
    db = SessionLocal()
    db.add(SearchRun(kind="discover_jobs", status="running", log=[]))
    db.commit()
    db.close()
    assert mark_interrupted_runs() >= 1


def test_failed_run_is_never_left_running():
    from app.db import SessionLocal
    from app.models import SearchRun
    from app.workflows import run_sync

    def boom(db, log):
        log("about to fail")
        raise RuntimeError("network down")

    r = run_sync("deep_research", None, boom)
    db = SessionLocal()
    r = db.get(SearchRun, r.id)
    db.close()
    assert r.status == "failed" and "network down" in r.error and r.finished_at


def test_fingerprint_changes_with_sources(tmp_path, monkeypatch):
    from app import frontend_build as FB
    monkeypatch.setattr(FB, "FRONTEND", tmp_path)
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "page.tsx"
    f.write_text("a")
    one = FB.fingerprint()
    f.write_text("ab")
    assert FB.fingerprint() != one
    (tmp_path / "tsconfig.json").write_text("{}")  # builds rewrite tsconfig; it must not trigger rebuild loops
    two = FB.fingerprint()
    (tmp_path / "tsconfig.json").write_text('{"x": 1}')
    assert FB.fingerprint() == two

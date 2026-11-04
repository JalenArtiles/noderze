"""Applies interface updates on its own.

When Claude edits Noderze's interface files, this thread notices (the source fingerprint no longer matches
the running build), rebuilds into .next-staging while the current version keeps working, and swaps the new
build in. Backend code is reloaded by uvicorn --reload. Runs only when Noderze's launcher started the
backend (NODERZE_MANAGED=1), never in tests.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time

from . import frontend_build as FB

log = logging.getLogger("noderze.selfupdate")
STATUS = FB.LOGS / "update-status.json"
LOCK = FB.LOGS / "build.lock"
SETTLE_S, POLL_S = 15, 20
_thread: threading.Thread | None = None


def managed() -> bool:
    return os.environ.get("NODERZE_MANAGED") == "1"


def status() -> dict:
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {"state": "idle", "build_id": FB.build_id()}


def _set(state: str, **kw) -> None:
    data = {**status(), "state": state, "at": time.time(), **kw}
    if state != "failed":
        data.pop("error", None)
    if state in ("idle", "done"):
        data.pop("step", None)
        data.pop("started", None)
    FB.LOGS.mkdir(exist_ok=True)
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, STATUS)


def _lock() -> bool:
    try:
        held = json.loads(LOCK.read_text())
        if FB.alive(held.get("pid")) or FB.alive(held.get("child")):
            return False
        LOCK.unlink()
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        try:
            LOCK.unlink()
        except OSError:
            return False
    try:
        with open(LOCK, "x") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "started": time.time()}))
        return True
    except FileExistsError:
        return False


def _lock_child(child: int) -> None:
    LOCK.write_text(json.dumps({"pid": os.getpid(), "child": child, "started": time.time()}))


def _unlock() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


def check_once() -> str:
    """One pass of the update check. Returns what happened (for logs and tests)."""
    if not FB.next_bin().exists() or not FB.node():
        return "no-toolchain"
    fp = FB.fingerprint()
    if fp == FB.built_hash():
        if status().get("state") not in ("idle", "done"):
            _set("idle", build_id=FB.build_id())
        return "current"
    if fp == status().get("failed_hash"):
        return "failed-before"
    time.sleep(SETTLE_S)  # let a batch of edits finish landing
    if FB.fingerprint() != fp:
        return "settling"
    if not _lock():
        return "locked"
    try:
        return _rebuild(fp)
    finally:
        _unlock()


def _rebuild(fp: str) -> str:
    FB.LOGS.mkdir(exist_ok=True)
    build_log = FB.LOGS / "build.log"
    with open(build_log, "w", encoding="utf-8") as out:
        if FB.needs_install():
            _set("building", step="installing packages")
            if FB.npm_install(out) != 0:
                _set("failed", error=FB.tail(build_log), failed_hash=fp)
                return "install-failed"
        shutil.rmtree(FB.STAGING, ignore_errors=True)
        _set("building", step="building", started=time.time())
        proc = FB.start_build(FB.STAGING.name, out)
        _lock_child(proc.pid)
        code = proc.wait()
    if code != 0 or not (FB.STAGING / "BUILD_ID").exists():
        _set("failed", error=FB.tail(build_log), failed_hash=fp)
        shutil.rmtree(FB.STAGING, ignore_errors=True)
        return "build-failed"
    FB.write_hash(FB.STAGING, fp)
    _set("swapping")
    FB.swap_in_staging()
    end = time.time() + 90
    while not FB.listening(3000) and time.time() < end:
        time.sleep(1)
    _set("done", build_id=FB.build_id(), failed_hash=None, finished=time.time())
    return "rebuilt"


APP_DIR = os.path.dirname(os.path.abspath(__file__))
STARTED = time.time()
CODE_SETTLE_S = 12


def newest_code_change(root: str = APP_DIR) -> float:
    """The newest modification time of the backend's Python files."""
    newest = 0.0
    for d, _, files in os.walk(root):
        if "__pycache__" in d:
            continue
        for f in files:
            if f.endswith(".py"):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(d, f)))
                except OSError:
                    pass
    return newest


def stale_code(now: float | None = None, root: str = APP_DIR, started: float | None = None) -> bool:
    """True when backend code changed after this process started and the change has settled.

    uvicorn --reload on Windows stops the old process with a Ctrl+C event, and with no console window that
    event can sit unprocessed for minutes, so the old code keeps running. A process that notices it's stale
    stops itself the same way Ctrl+C would; the waiting reloader then starts the new code."""
    now = now or time.time()
    changed = newest_code_change(root)
    return changed > (started or STARTED) + 1 and now - changed >= CODE_SETTLE_S


def _stop_self() -> None:
    import signal
    log.warning("Backend code changed on disk; stopping so the reloader starts the new version")
    signal.raise_signal(signal.SIGINT)


def _loop() -> None:
    time.sleep(10)
    while True:
        try:
            if stale_code():
                _stop_self()
                return
            result = check_once()
            if result not in ("current", "failed-before", "no-toolchain"):
                log.info("interface update check: %s", result)
        except Exception as e:  # never let the updater take the app down
            log.exception("interface update failed")
            try:
                _set("failed", error=f"{e.__class__.__name__}: {e}")
            except OSError:
                pass
        time.sleep(POLL_S)


def start() -> None:
    global _thread
    if managed() and _thread is None:
        _thread = threading.Thread(target=_loop, name="noderze-selfupdate", daemon=True)
        _thread.start()

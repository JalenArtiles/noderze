"""Building and restarting the Noderze interface. Standard library only, so the launcher can import it too.

The interface is rebuilt into .next-staging while the current version keeps serving, then swapped in with a
restart of a few seconds. A fingerprint of the interface's source files, stored next to each build, decides
whether a rebuild is needed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND, FRONTEND, LOGS = ROOT / "backend", ROOT / "frontend", ROOT / "logs"
DIST, STAGING = FRONTEND / ".next", FRONTEND / ".next-staging"
HASH_FILE = "noderze-src.json"
SOURCE_DIRS = ("app", "components", "lib", "public")
SOURCE_FILES = ("package.json", "next.config.mjs")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
FRONTEND_PID, BACKEND_PID = LOGS / "frontend.pid", LOGS / "backend.pid"


def fingerprint() -> str:
    h = hashlib.sha1()
    paths = []
    for d in SOURCE_DIRS:
        base = FRONTEND / d
        if base.exists():
            paths += [p for p in base.rglob("*") if p.is_file()]
    paths += [FRONTEND / f for f in SOURCE_FILES if (FRONTEND / f).exists()]
    for p in sorted(paths):
        st = p.stat()
        h.update(f"{p.relative_to(FRONTEND).as_posix()}|{st.st_size}|{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def built_hash(dist: Path = DIST) -> str | None:
    try:
        return json.loads((dist / HASH_FILE).read_text())["hash"]
    except (OSError, ValueError, KeyError):
        return None


def write_hash(dist: Path, fp: str) -> None:
    (dist / HASH_FILE).write_text(json.dumps({"hash": fp, "built": time.time()}))


def build_id(dist: Path = DIST) -> str | None:
    try:
        return (dist / "BUILD_ID").read_text().strip()
    except OSError:
        return None


def node() -> str | None:
    return shutil.which("node")


def next_bin() -> Path:
    return FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"


def needs_install() -> bool:
    lock = FRONTEND / "node_modules" / ".package-lock.json"
    pkg = FRONTEND / "package.json"
    return not lock.exists() or pkg.stat().st_mtime > lock.stat().st_mtime + 1


def npm_install(log) -> int:
    cmd = ["cmd", "/c", "npm", "install", "--no-audit", "--no-fund", "--loglevel=error"] if os.name == "nt" else \
        ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"]
    return subprocess.run(cmd, cwd=str(FRONTEND), stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW).returncode


def start_build(dist_name: str, log) -> subprocess.Popen:
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
    if dist_name != ".next":
        env["NEXT_DIST_DIR"] = dist_name
    else:
        env.pop("NEXT_DIST_DIR", None)
    return subprocess.Popen([node(), str(next_bin()), "build"], cwd=str(FRONTEND), env=env, stdout=log,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)


def tail(path: Path, n: int = 25) -> str:
    try:
        return "\n".join(path.read_text(errors="ignore").splitlines()[-n:])
    except OSError:
        return ""


# ----------------------------------------------------------------------------- processes

def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def kill_tree(pid: int | None) -> None:
    if not pid or not alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        import signal
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        except OSError:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass


def port_pids(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
            pids.add(int(parts[4]))
    return pids


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def stop_port(port: int, pid_file: Path, wait_s: float = 20) -> None:
    kill_tree(read_pid(pid_file))
    for pid in port_pids(port):
        kill_tree(pid)
    end = time.time() + wait_s
    while listening(port) and time.time() < end:
        time.sleep(0.5)
    try:
        pid_file.unlink()
    except OSError:
        pass


def start_frontend() -> subprocess.Popen:
    LOGS.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "NEXT_DIST_DIR"}
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    log = open(LOGS / "frontend.log", "a", encoding="utf-8")
    kw = {"start_new_session": True} if os.name != "nt" else {}
    p = subprocess.Popen([node(), str(next_bin()), "start", "-p", "3000", "-H", "127.0.0.1"], cwd=str(FRONTEND),
                         env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW, **kw)
    FRONTEND_PID.write_text(str(p.pid))
    return p


def _rename(src: Path, dst: Path, tries: int = 20) -> None:
    for i in range(tries):
        try:
            src.rename(dst)
            return
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(1)  # Windows can hold files briefly after a process exits


def swap_in_staging() -> None:
    """Stop the interface, move the new build into place, start it again. Rolls back on failure."""
    old = FRONTEND / f".next-old-{int(time.time())}"
    stop_port(3000, FRONTEND_PID)
    moved_old = False
    try:
        if DIST.exists():
            _rename(DIST, old)
            moved_old = True
        _rename(STAGING, DIST)
    except OSError:
        if moved_old and not DIST.exists():
            _rename(old, DIST)
        start_frontend()
        raise
    start_frontend()
    for leftover in FRONTEND.glob(".next-old-*"):
        shutil.rmtree(leftover, ignore_errors=True)

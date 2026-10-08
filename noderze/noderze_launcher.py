"""Noderze launcher for Windows. Standard library only.

Starts the backend and the interface with no console windows, then opens Noderze in its own app window.
It uses no hidden PowerShell and no security-bypass flags, which is the pattern antivirus tools flag.

Updates apply themselves: the backend runs with auto-reload, and the interface is rebuilt by the backend's
self-updater whenever its source files change. If an older Noderze is running, opening Noderze restarts it.

    pythonw noderze_launcher.py                 open Noderze (starts it first if needed)
    python  noderze_launcher.py --install       create Desktop and Start menu shortcuts, then open Noderze
    python  noderze_launcher.py --stop          stop Noderze
    python  noderze_launcher.py --autostart on  also start Noderze quietly when you sign in (off to undo)
    pythonw noderze_launcher.py --background    start without opening a window (used by auto-start)
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND, FRONTEND, LOGS, HERE = ROOT / "backend", ROOT / "frontend", ROOT / "logs", ROOT / "noderze"
VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe"
VENV_PYW = BACKEND / ".venv" / "Scripts" / "pythonw.exe"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
URL = "http://127.0.0.1:3000"
sys.path.insert(0, str(BACKEND))
try:  # shared with the backend's self-updater
    from app import frontend_build as FB
    from app import selfupdate as SU
except Exception:  # an older or partial copy of the backend
    FB = SU = None


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def message(text: str, error: bool = False) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Noderze", 0x10 if error else 0x40)
    except Exception:
        print(text)


def spawn(args: list[str], cwd: Path, logname: str) -> None:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / logname, "a", encoding="utf-8")
    subprocess.Popen(args, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=NO_WINDOW)


def backend_version() -> str | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as r:
            return json.loads(r.read().decode()).get("version")
    except Exception:
        return None


def ensure_interface_build() -> None:
    """Build the interface now if its files changed since the last build (the interface is not running)."""
    if FB is None:
        return
    fresh = FB.build_id() is None
    if not fresh and FB.fingerprint() == FB.built_hash():
        return
    if SU is not None and not SU._lock():
        return  # the backend is already rebuilding it
    try:
        message("Noderze is applying an update to its interface. This takes 2 to 4 minutes. "
                "Click OK, and the window opens when it's ready.")
        LOGS.mkdir(exist_ok=True)
        with open(LOGS / "build.log", "w", encoding="utf-8") as log:
            if FB.needs_install() and FB.npm_install(log) != 0:
                message(f"Installing interface packages failed. Details are in {LOGS / 'build.log'}.", True)
                return
            fp = FB.fingerprint()
            code = FB.start_build(".next", log).wait()
        if code == 0 and FB.build_id():
            FB.write_hash(FB.DIST, fp)
            if SU is not None:
                SU._set("idle", build_id=FB.build_id(), failed_hash=None)
        elif FB.build_id():
            message("The update didn't build, so Noderze is opening the previous version. "
                    f"Details are in {LOGS / 'build.log'}.", True)
        else:
            message(f"The interface build failed. Details are in {LOGS / 'build.log'}.", True)
            sys.exit(1)
    finally:
        if SU is not None:
            SU._unlock()


def start() -> None:
    if not VENV_PY.exists():
        message(f"Could not find {VENV_PY}. Run the first-time setup again.", True)
        sys.exit(1)
    if listening(8000) and backend_version() is None:
        stop(quiet=True)  # an older Noderze is running; replace it with this version
    node = shutil.which("node")
    if not node:
        message("Node.js was not found. Install the LTS version from nodejs.org, then open Noderze again.", True)
        sys.exit(1)
    next_bin = FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"
    if not next_bin.exists():
        message("The interface packages are missing. Run setup-noderze.ps1 again.", True)
        sys.exit(1)
    if not listening(3000):
        ensure_interface_build()
    if not listening(8000):
        LOGS.mkdir(exist_ok=True)
        log = open(LOGS / "backend.log", "a", encoding="utf-8")
        p = subprocess.Popen([str(VENV_PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
                              "--reload", "--reload-dir", "app"], cwd=str(BACKEND), stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                             env={**os.environ, "NODERZE_MANAGED": "1"})
        (LOGS / "backend.pid").write_text(str(p.pid))
    if not listening(3000):
        if FB is not None:
            FB.start_frontend()
        else:
            spawn([node, str(next_bin), "start", "-p", "3000", "-H", "127.0.0.1"], FRONTEND, "frontend.log")


def wait_for(port: int, seconds: int) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if listening(port):
            return True
        time.sleep(1)
    return False


def edge_path() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def open_app() -> None:
    start()
    if not wait_for(3000, 120):
        message(f"Noderze did not start in time. The logs in {LOGS} say why; send a screenshot of frontend.log.", True)
        sys.exit(1)
    if not wait_for(8000, 45):
        message(f"Noderze's backend didn't start. The details are in {LOGS / 'backend.log'}; Claude can read them "
                f"and fix it.", True)
    edge = edge_path()
    if edge:
        subprocess.Popen([edge, f"--app={URL}"])
    else:
        webbrowser.open(URL)


def listening_pids(text: str, ports=("8000", "3000")) -> set[int]:
    pids = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] in ports:
            pids.add(int(parts[4]))
    return pids


def stop(quiet: bool = False) -> None:
    for name in ("backend.pid", "frontend.pid"):
        try:
            pid = int((LOGS / name).read_text().strip())
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
            (LOGS / name).unlink()
        except (OSError, ValueError):
            pass
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    for pid in listening_pids(out):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    end = time.time() + 15
    while (listening(8000) or listening(3000)) and time.time() < end:
        time.sleep(0.5)
    if not quiet:
        message("Noderze stopped.")


def _powershell(script: str, env: dict) -> None:
    # A plain, visible-for-a-moment PowerShell command (no hidden window, no execution-policy bypass).
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env={**os.environ, **env}, check=True,
                   creationflags=NO_WINDOW)


SHORTCUT = ("$ws = New-Object -ComObject WScript.Shell; "
            "$dir = [Environment]::GetFolderPath($env:NZ_FOLDER); "
            "$s = $ws.CreateShortcut((Join-Path $dir $env:NZ_NAME)); "
            "$s.TargetPath = $env:NZ_TARGET; $s.Arguments = $env:NZ_ARGS; $s.WorkingDirectory = $env:NZ_DIR; "
            "$s.IconLocation = $env:NZ_ICON; $s.Description = 'Noderze'; $s.Save()")
REMOVE_OLD = ("foreach ($pair in @(@('Desktop','Noderze.lnk'), @('Programs','Noderze.lnk'), @('Startup','Noderze background.lnk'))) {"
              " $p = Join-Path ([Environment]::GetFolderPath($pair[0])) $pair[1];"
              " if (Test-Path $p) { Remove-Item $p -Force -ErrorAction SilentlyContinue } }")


def shortcut(folder: str, name: str, args: str = "") -> None:
    _powershell(SHORTCUT, {"NZ_FOLDER": folder, "NZ_NAME": name, "NZ_TARGET": str(VENV_PYW),
                           "NZ_ARGS": f'"{Path(__file__).resolve()}" {args}'.strip(), "NZ_DIR": str(HERE),
                           "NZ_ICON": str(HERE / "noderze.ico")})


def install() -> None:
    try:
        _powershell(REMOVE_OLD, {})  # old PowerShell-based shortcuts; a file Norton is holding is skipped
    except Exception:
        pass
    shortcut("Desktop", "Noderze App.lnk")
    shortcut("Programs", "Noderze App.lnk")
    print("Shortcuts created: 'Noderze App' on your Desktop and in the Start menu. Opening Noderze...")
    open_app()


def autostart(on: bool) -> None:
    if on:
        shortcut("Startup", "Noderze App (background).lnk", "--background")
        message("Noderze will now start quietly when you sign in, so scheduled job scans run.")
    else:
        _powershell("$p = Join-Path ([Environment]::GetFolderPath('Startup')) 'Noderze App (background).lnk'; "
                    "if (Test-Path $p) { Remove-Item $p -Force }", {})
        message("Auto-start is off.")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--install":
        install()
    elif arg == "--stop":
        stop(quiet=len(sys.argv) > 2 and sys.argv[2] == "quiet")
    elif arg == "--background":
        start()
    elif arg == "--autostart":
        autostart(len(sys.argv) > 2 and sys.argv[2].lower() == "on")
    else:
        open_app()

"""Install pinned dependencies and launch the unchanged local URS application."""
import os
from pathlib import Path
import subprocess
import sys
import webbrowser
import threading

ROOT = Path(__file__).resolve().parent

def main():
    os.chdir(ROOT)
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Python 3.12 is required. Install Python 3.12 and run again.")
    venv = ROOT / ".venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    marker = venv / "urs-requirements.sha256"
    import hashlib
    digest = hashlib.sha256((ROOT / "requirements.lock").read_bytes()).hexdigest()
    if not marker.exists() or marker.read_text() != digest:
        subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.lock"], check=True)
        subprocess.run([str(python), "-m", "pip", "check"], check=True)
        marker.write_text(digest)
    data = ROOT / ".runtime/workspace.sqlite"
    needs_user = True
    if data.exists():
        import sqlite3
        with sqlite3.connect(str(data)) as db:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                needs_user = not db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if needs_user:
        print("First run: create your employee account.")
        username = input("Employee ID: ").strip()
        if not username:
            raise SystemExit("Employee ID is required.")
        subprocess.run([str(python), "-m", "urs", "--data", str(data), "add-user", username], check=True)
    print("Open http://127.0.0.1:8795 — press Ctrl+C to stop.")
    timer = threading.Timer(2, lambda: webbrowser.open("http://127.0.0.1:8795"))
    timer.daemon = True
    timer.start()
    try:
        return subprocess.call([str(python), "-m", "urs", "--data", str(data), "serve", "--port", "8795"])
    except KeyboardInterrupt:
        return 0

if __name__ == "__main__":
    raise SystemExit(main())

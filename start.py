"""Install dependencies, set up the first account, and start the URS application."""
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

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
    return run_server(ROOT,python,data)


def run_server(root, python, data, port=8795):
    from urs.launcher import StartupError,wait_ready,port_busy
    lock=None;child=None
    try:
        if os.name=='posix':
            from service import Service
            result=Service(root,port).restart()
            if result==0 and not os.environ.get('CODESPACES'):
                webbrowser.open(f'http://127.0.0.1:{port}')
            return result
        if port_busy(port):
            raise StartupError(f'{port} 포트를 사용 중입니다. 기존 서버 창을 먼저 종료해 주세요.')
        child=subprocess.Popen([str(python),'-m','urs','--data',str(data),'serve','--port',str(port)],cwd=root)
        wait_ready(child,port)
        print(f'로컬 웹 서버 응답 확인: http://127.0.0.1:{port} (HTTP 200). 종료: Ctrl+C',flush=True)
        if not os.environ.get('CODESPACES'):webbrowser.open(f'http://127.0.0.1:{port}')
        if lock is not None:lock.close();lock=None
        return child.wait()
    except StartupError as exc:
        print(str(exc),flush=True)
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:print('서버 프로세스 종료가 지연되고 있습니다.',flush=True)
        return 1
    except KeyboardInterrupt:
        if child is not None and child.poll() is None:
            child.send_signal(__import__('signal').SIGINT)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.terminate()
        return 0
    finally:
        if lock is not None:lock.close()

if __name__ == "__main__":
    raise SystemExit(main())

"""Persistent local/Codespaces server supervisor (POSIX, no extra dependencies)."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent

class Service:
    def __init__(self, root=ROOT, port=8795):
        self.root=Path(root).resolve();self.port=port
        self.runtime=self.root/'.runtime'
        self.runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lockfile=self.runtime/'service.lock'
        self.state=self.runtime/'service.json'
        self.disabled=self.runtime/'service.disabled'
        self.log=self.runtime/'server.log'
        self.python=self.root/'.venv/bin/python'
        if not self.python.exists():self.python=Path(sys.executable)

    def running(self):
        with self.lockfile.open('a+') as handle:
            try:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
            fcntl.flock(handle,fcntl.LOCK_UN)
        return False

    def has_account(self):
        dbfile=self.runtime/'workspace.sqlite'
        if not dbfile.exists():return False
        with sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='users' AND type='table'").fetchone():return False
            return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

    def healthy(self):
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{self.port}/',timeout=1) as response:
                return response.status==200 and b'URS AI REPORT SYSTEM' in response.read(32768)
        except (OSError,ValueError):return False

    def status(self):
        alive=self.running()
        return {'supervisor_running':alive,'web_ready':self.healthy(),
                'manually_stopped':self.disabled.exists(),'port':self.port}

    def _control(self, action):
        # Serialize all public lifecycle commands, including concurrent CLI starts.
        with (self.runtime/'control.lock').open('a+') as lock:
            deadline=time.monotonic()+35
            while True:
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic()>=deadline:
                        print('다른 시작/종료 명령이 진행 중입니다. 중복 실행하지 않았습니다.');return 1
                    time.sleep(.1)
            return action()

    def start(self, automatic=False):
        return self._control(lambda:self._start(automatic))

    def _browser_ready(self):
        from urs.browser_setup import ensure
        return ensure(self.root,self.python)

    def restart(self):
        def restart_ready():
            if not self._browser_ready():return 1
            return self._stop() or self._start(browser_ready=True)
        return self._control(restart_ready)

    def _start(self, automatic=False, browser_ready=False):
        if automatic and self.disabled.exists():
            print('수동 종료 상태입니다. python service.py start 로 다시 켜세요.');return 0
        if not self.has_account():
            print('첫 실행: python start.py 로 직원 계정을 먼저 만들어 주세요.');return 0 if automatic else 1
        if not browser_ready and not self.running() and not self._browser_ready():return 1
        if not automatic:self.disabled.unlink(missing_ok=True)
        if not self.running():
            from urs.launcher import release_owned_port,StartupError
            try:release_owned_port(self.root,self.port)
            except StartupError as exc:
                print(str(exc));return 1
            fd=os.open(self.log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            with os.fdopen(fd,'ab',buffering=0) as output:
                subprocess.Popen([str(self.python),str(Path(__file__).resolve()),'supervise','--root',str(self.root),'--port',str(self.port)],
                    cwd=self.root,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True,close_fds=True)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if self.running() and self._owned_ready():
                print(f'로컬 웹 서버 응답 확인: http://127.0.0.1:{self.port} (HTTP 200, 터미널을 닫아도 유지됩니다.)')
                print('종료: python service.py stop / 재시작: python service.py restart')
                if os.environ.get('CODESPACE_NAME'):
                    print('외부 접속 주소: https://'+os.environ['CODESPACE_NAME']+f'-{self.port}.app.github.dev/ (외부 응답은 별도 확인 필요)')
                return 0
            time.sleep(.15)
        print('아직 시작되지 않았습니다. python service.py status 및 .runtime/server.log 를 확인하세요.')
        return 1

    def _owned_ready(self):
        from urs.launcher import owned_listener_pids
        try:
            pid=json.loads(self.state.read_text())['server_pid']
            return pid in owned_listener_pids(self.root,self.port) and self.healthy()
        except (OSError,ValueError,KeyError):return False

    def stop(self):
        return self._control(self._stop)

    def _stop(self):
        supervised=self.running()
        self.disabled.touch(mode=0o600,exist_ok=True)
        deadline=time.monotonic()+12
        while self.running() and time.monotonic()<deadline:time.sleep(.1)
        if self.running():
            print('종료가 지연되고 있습니다. 상태와 로그를 확인하세요.');return 1
        from urs.launcher import release_owned_port,StartupError
        try:stopped=release_owned_port(self.root,self.port)
        except StartupError as exc:
            print(str(exc));return 1
        if supervised or stopped:print('기존 URS 서버 종료를 확인했습니다. 자동 시작은 비활성화했습니다.')
        else:print('종료할 URS 서버가 없습니다. 자동 시작은 비활성화했습니다.')
        return 0

    def supervise(self):
        with self.lockfile.open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return 0
            stopping=False;child=None
            def shutdown(*_):
                nonlocal stopping
                stopping=True
            signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
            delay=1
            try:
                while not stopping and not self.disabled.exists():
                    started=time.monotonic()
                    child=subprocess.Popen([str(self.python),'-m','urs','--data',str(self.runtime/'workspace.sqlite'),'serve','--port',str(self.port)],
                        cwd=self.root,stdin=subprocess.DEVNULL,close_fds=True)
                    temporary=self.state.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'supervisor_pid':os.getpid(),'server_pid':child.pid,'port':self.port}))
                    temporary.chmod(0o600);temporary.replace(self.state)
                    failures=0;next_probe=time.monotonic()+2
                    while child.poll() is None and not stopping and not self.disabled.exists():
                        if time.monotonic()>=next_probe:
                            failures=0 if self.healthy() else failures+1
                            next_probe=time.monotonic()+2
                            if failures>=3:
                                print('Local HTTP health checks failed three times; restarting server.',flush=True)
                                break
                        time.sleep(.15)
                    if child.poll() is None:
                        child.terminate()
                        try:child.wait(timeout=8)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                    if stopping or self.disabled.exists():break
                    print('Server exited; restarting.',flush=True)
                    end=time.monotonic()+delay
                    while time.monotonic()<end and not stopping and not self.disabled.exists():time.sleep(.1)
                    delay=1 if time.monotonic()-started>=30 else min(delay*2,30)
            finally:
                if child is not None and child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=8)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                self.state.unlink(missing_ok=True)
        return 0


def main():
    parser=argparse.ArgumentParser(description='URS 웹 시작/종료/자동 복구')
    parser.add_argument('command',choices=['start','stop','restart','status','autostart','supervise'])
    parser.add_argument('--root',type=Path,default=ROOT,help=argparse.SUPPRESS)
    parser.add_argument('--port',type=int,default=8795,help=argparse.SUPPRESS)
    args=parser.parse_args();service=Service(args.root,args.port)
    if args.command=='status':print(json.dumps(service.status(),ensure_ascii=False));return 0
    if args.command=='stop':return service.stop()
    if args.command=='restart':return service.restart()
    if args.command=='supervise':return service.supervise()
    return service.start(automatic=args.command=='autostart')

if __name__=='__main__':raise SystemExit(main())

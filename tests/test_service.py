"""Real detached-server lifecycle in isolated temporary databases; no AI calls."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Service
from urs.workspace import Workspace
from html_fixtures import visual_pdf

ROOT=Path(__file__).resolve().parents[1]

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'urs').symlink_to(ROOT/'urs',target_is_directory=True)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.service=Service(self.root,self.port)
        self.addCleanup(self.service.stop)
        self.w=Workspace(self.root/'.runtime/workspace.sqlite')
        self.w.add_user('fixture','fixture-only-password-123')
        self.project=self.w.create_project('fixture','Service restart fixture')
        self.pdf=visual_pdf();self.doc=self.w.upload('fixture',self.project,'source.pdf',self.pdf)
        self.token,_=self.w.login('fixture','fixture-only-password-123')

    def command(self,name):
        return subprocess.run([sys.executable,str(ROOT/'service.py'),name,'--root',str(self.root),'--port',str(self.port)],
            capture_output=True,text=True,timeout=20)

    def wait(self,condition):
        end=time.monotonic()+10
        while time.monotonic()<end:
            if condition():return
            time.sleep(.1)
        self.fail('Service condition did not become true')

    def test_detached_survives_start_command_exit_and_start_is_idempotent(self):
        first=self.command('start');self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        self.assertTrue(self.service.healthy());self.assertTrue(self.service.running())
        original=json.loads(self.service.state.read_text())
        second=self.command('start');self.assertEqual(second.returncode,0)
        self.assertEqual(json.loads(self.service.state.read_text()),original)
        self.assertEqual(self.command('status').returncode,0)
        self.assertEqual(self.w.original('fixture',self.doc)['original'],self.pdf)
        self.assertEqual(self.w.session(self.token)[0],'fixture')

    def test_server_crash_restarts_and_keeps_database_and_sessions(self):
        before=self.w.verification_record('fixture',self.doc)['record_sha256']
        self.assertEqual(self.command('start').returncode,0)
        old=json.loads(self.service.state.read_text())['server_pid']
        os.kill(old,signal.SIGTERM)
        def restarted():
            try:return json.loads(self.service.state.read_text())['server_pid']!=old and self.service.healthy()
            except (OSError,ValueError):return False
        self.wait(restarted)
        self.assertEqual(self.w.verification_record('fixture',self.doc)['record_sha256'],before)
        self.assertEqual(self.w.session(self.token)[0],'fixture')
        with self.w.workflow.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0],0)

    def test_manual_stop_persists_across_autostart_and_explicit_start_resumes(self):
        self.assertEqual(self.command('autostart').returncode,0)
        self.assertTrue(self.service.healthy())
        self.assertEqual(self.command('stop').returncode,0)
        self.assertFalse(self.service.running());self.assertFalse(self.service.healthy())
        self.assertTrue(self.service.disabled.exists())
        self.assertEqual(self.command('autostart').returncode,0)
        self.assertFalse(self.service.running())
        self.assertEqual(self.command('start').returncode,0)
        self.assertTrue(self.service.healthy());self.assertFalse(self.service.disabled.exists())

    def test_first_run_autostart_never_creates_an_account_or_prompts(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Service(folder,self.port)
            self.assertEqual(service.start(automatic=True),0)
            self.assertFalse(service.running())
            self.assertFalse((Path(folder)/'.runtime/workspace.sqlite').exists())

    def spawn_foreground(self,data=None,module='urs'):
        output=(self.root/('listener-'+str(time.time_ns())+'.log')).open('wb')
        args=[sys.executable,'-m',module]
        args+=['--data',str(data or self.root/'.runtime/workspace.sqlite'),'serve','--port',str(self.port)] if module=='urs' else [str(self.port),'--bind','127.0.0.1']
        process=subprocess.Popen(args,cwd=self.root,stdout=output,stderr=output)
        def cleanup():
            if process.poll() is None:process.terminate()
            process.wait(timeout=10);output.close()
        self.addCleanup(cleanup)
        return process

    def spawn_launcher(self):
        path=self.root/('launcher-'+str(time.time_ns())+'.log');output=path.open('wb')
        code="from pathlib import Path; import sys; sys.path.insert(0,sys.argv[1]); from start import run_server; raise SystemExit(run_server(Path(sys.argv[2]),Path(sys.executable),Path(sys.argv[2])/'.runtime/workspace.sqlite',int(sys.argv[3])))"
        process=subprocess.Popen([sys.executable,'-c',code,str(ROOT),str(self.root),str(self.port)],cwd=self.root,stdout=output,stderr=output,env={**os.environ,'CODESPACES':'true'})
        def cleanup():
            self.service.stop()
            if process.poll() is None:
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
            output.close()
        self.addCleanup(cleanup)
        return process,path

    def test_normal_launcher_restarts_supervisor_and_detaches_after_real_http_success(self):
        self.assertEqual(self.command('start').returncode,0)
        old=json.loads(self.service.state.read_text())['server_pid']
        before=self.w.verification_record('fixture',self.doc)['record_sha256']
        process,log=self.spawn_launcher()
        from urs.launcher import owned_listener_pids
        self.wait(lambda:process.poll()==0 and self.service.healthy() and old not in owned_listener_pids(self.root,self.port) and 'HTTP 200' in log.read_text())
        self.assertTrue(self.service.running())
        self.assertFalse(self.service.disabled.exists())
        self.assertEqual(self.w.verification_record('fixture',self.doc)['record_sha256'],before)
        self.assertEqual(self.w.session(self.token)[0],'fixture')

    def test_existing_foreground_listener_is_restarted_without_address_in_use(self):
        old=self.spawn_foreground();self.wait(self.service.healthy)
        before=self.w.verification_record('fixture',self.doc)['record_sha256']
        process,log=self.spawn_launcher()
        self.wait(lambda:old.poll() is not None and process.poll()==0 and self.service.healthy() and 'HTTP 200' in log.read_text())
        self.assertNotIn('Address already in use',log.read_text())
        self.assertEqual(self.w.verification_record('fixture',self.doc)['record_sha256'],before)
        self.assertEqual(self.w.session(self.token)[0],'fixture')

    def test_foreign_application_on_port_is_not_terminated_or_reported_as_started(self):
        other=self.spawn_foreground(module='http.server')
        from urs.launcher import port_busy
        self.wait(lambda:port_busy(self.port))
        process,log=self.spawn_launcher();process.wait(timeout=10)
        self.assertEqual(process.returncode,1);self.assertIsNone(other.poll())
        self.assertIn('자동 종료하지 않았습니다',log.read_text())
        self.assertNotIn('HTTP 200',log.read_text())

    def test_same_project_with_another_database_is_not_terminated(self):
        other=self.spawn_foreground(data=self.root/'other.sqlite');self.wait(self.service.healthy)
        process,log=self.spawn_launcher();process.wait(timeout=10)
        self.assertEqual(process.returncode,1);self.assertIsNone(other.poll())
        self.assertIn('자동 종료하지 않았습니다',log.read_text())

    def test_concurrent_starts_share_one_supervisor_and_listener(self):
        args=[sys.executable,str(ROOT/'service.py'),'start','--root',str(self.root),'--port',str(self.port)]
        children=[subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(3)]
        for child in children:
            out,err=child.communicate(timeout=35)
            self.assertEqual(child.returncode,0,out+err)
        from urs.launcher import owned_listener_pids
        state=json.loads(self.service.state.read_text())
        self.assertEqual(owned_listener_pids(self.root,self.port),{state['server_pid']})
        self.assertTrue(self.service.running());self.assertTrue(self.service.healthy())

    def test_unresponsive_server_is_recovered_without_losing_original_or_session(self):
        self.assertEqual(self.command('start').returncode,0)
        before=self.w.verification_record('fixture',self.doc)['record_sha256']
        old=json.loads(self.service.state.read_text())['server_pid']
        os.kill(old,signal.SIGSTOP)
        deadline=time.monotonic()+30
        recovered=False
        while time.monotonic()<deadline:
            try:
                recovered=json.loads(self.service.state.read_text())['server_pid']!=old and self.service.healthy()
            except (OSError,ValueError):pass
            if recovered:break
            time.sleep(.2)
        self.assertTrue(recovered,'Supervisor did not recover the frozen HTTP server')
        self.assertIn('health checks failed three times',self.service.log.read_text())
        self.assertEqual(self.w.verification_record('fixture',self.doc)['record_sha256'],before)
        self.assertEqual(self.w.session(self.token)[0],'fixture')

    def test_restart_command_preserves_data_and_manual_stop_survives_autostart(self):
        self.assertEqual(self.command('start').returncode,0)
        old=json.loads(self.service.state.read_text())['server_pid']
        self.assertEqual(self.command('restart').returncode,0)
        self.assertNotEqual(json.loads(self.service.state.read_text())['server_pid'],old)
        self.assertEqual(self.w.original('fixture',self.doc)['original'],self.pdf)
        self.assertEqual(self.command('stop').returncode,0)
        self.assertEqual(self.command('autostart').returncode,0)
        self.assertFalse(self.service.running());self.assertFalse(self.service.healthy())

    def test_stop_does_not_claim_it_stopped_a_nonexistent_server(self):
        import contextlib,io
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(self.service.stop(),0)
        self.assertIn('종료할 URS 서버가 없습니다',output.getvalue())
        self.assertNotIn('웹을 종료했습니다',output.getvalue())

if __name__=='__main__':unittest.main()

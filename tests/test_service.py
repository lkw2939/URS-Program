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

if __name__=='__main__':unittest.main()

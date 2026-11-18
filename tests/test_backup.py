import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter
from urs.backup import backup_database,restore_database
from urs.workspace import Workspace,Unauthorized


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'original.sqlite'
        self.w=Workspace(self.path);self.w.add_user('operator','synthetic-backup-password')
        self.project=self.w.create_project('operator','복구 시험')
        writer=PdfWriter();writer.add_blank_page(300,400);stream=io.BytesIO();writer.write(stream)
        self.payload=stream.getvalue();self.doc=self.w.upload('operator',self.project,'original.pdf',self.payload)
        self.token,_=self.w.login('operator','synthetic-backup-password')

    def test_consistent_snapshot_restores_original_history_and_requires_new_login(self):
        backup=self.root/'snapshot.sqlite';restored=self.root/'restored.sqlite'
        result=backup_database(self.path,backup)
        self.assertEqual(result['documents'],1);self.assertEqual(result['projects'],1)
        self.assertEqual(backup.stat().st_mode&0o777,0o600)
        restore=restore_database(backup,restored)
        self.assertTrue(restore['old_sessions_invalidated'])
        recovered=Workspace(restored)
        with self.assertRaises(Unauthorized):recovered.session(self.token)
        token,_=recovered.login('operator','synthetic-backup-password')
        self.assertEqual(recovered.session(token)[0],'operator')
        self.assertEqual(recovered.original('operator',self.doc)['original'],self.payload)
        self.assertEqual(recovered.status('operator',self.doc)['events'],self.w.status('operator',self.doc)['events'])
        self.assertEqual(recovered.projects('operator')[0]['id'],self.project)
        self.assertEqual(self.w.session(self.token)[0],'operator')

    def test_existing_target_and_original_are_never_overwritten(self):
        target=self.root/'occupied';target.write_bytes(b'keep this file')
        for operation in (backup_database,restore_database):
            with self.assertRaises(ValueError):operation(self.path,target)
            self.assertEqual(target.read_bytes(),b'keep this file')
            with self.assertRaises(ValueError):operation(self.path,self.path)
        self.assertEqual(self.w.original('operator',self.doc)['original'],self.payload)

    def test_invalid_database_does_not_create_output(self):
        source=self.root/'not-db';source.write_bytes(b'not SQLite')
        output=self.root/'output.sqlite'
        with self.assertRaises(ValueError):restore_database(source,output)
        self.assertFalse(output.exists())

    def test_tampered_evidence_blocks_backup(self):
        with self.w.workflow.connect() as db:db.execute('UPDATE results SET evidence=?', ('{"fake":true}',))
        output=self.root/'tampered.sqlite'
        with self.assertRaises(ValueError):backup_database(self.path,output)
        self.assertFalse(output.exists())

    def _processed_document(self):
        from html_fixtures import ReportAI,visual_pdf,PROMPT,RAW
        self.w.processing.provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'))
        self.w.save_report_settings('operator',PROMPT)
        document=self.w.upload('operator',self.project,'processed.pdf',visual_pdf())
        state=self.w.run('operator',document,'report')
        self.assertTrue(next(s['passed'] for s in state['stages'] if s['id']=='report'))
        return document

    def _reject_damaged_assets(self,table,delete):
        document=self._processed_document()
        with self.w.workflow.connect() as db:
            kind='report.html' if table=='artifacts' else 'report-images'
            if delete:db.execute('DELETE FROM artifacts WHERE document=? AND kind=?',(document,kind))
            else:db.execute('UPDATE artifacts SET payload=? WHERE document=? AND kind=?',(b'damaged bytes',document,kind))
        before=self.path.read_bytes()
        for operation in (backup_database,restore_database):
            output=self.root/(operation.__name__+'.sqlite')
            with self.assertRaises(ValueError):operation(self.path,output)
            self.assertFalse(output.exists())
            self.assertEqual(self.path.read_bytes(),before)

    def test_damaged_report_blocks_backup_and_restore(self):
        self._reject_damaged_assets('artifacts',False)

    def test_missing_report_blocks_backup_and_restore(self):
        self._reject_damaged_assets('artifacts',True)

    def test_damaged_source_crops_blocks_backup_and_restore(self):
        self._reject_damaged_assets('page_assets',False)

    def test_missing_source_crops_blocks_backup_and_restore(self):
        self._reject_damaged_assets('page_assets',True)

    def test_cli_backup_restore_and_nonzero_exit_for_overwrite(self):
        backup=self.root/'cli-snapshot.sqlite';restored=self.root/'cli-restored.sqlite'
        def run(*args):
            return subprocess.run([sys.executable,'-m','urs',*map(str,args)],capture_output=True,text=True)
        first=run('--data',self.path,'backup',backup)
        self.assertEqual(first.returncode,0,first.stderr)
        self.assertEqual(json.loads(first.stdout)['documents'],1)
        second=run('--data',restored,'restore',backup)
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(Workspace(restored).original('operator',self.doc)['original'],self.payload)
        repeated=run('--data',restored,'restore',backup)
        self.assertNotEqual(repeated.returncode,0)
        self.assertEqual(Workspace(restored).original('operator',self.doc)['original'],self.payload)

    def test_sqlite_backup_includes_committed_wal_changes(self):
        db=sqlite3.connect(self.path)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('INSERT INTO projects VALUES(?,?,?)',('wal-project','operator','committed in WAL'))
            db.commit()
            snapshot=self.root/'wal-snapshot.sqlite'
            result=backup_database(self.path,snapshot)
            self.assertEqual(result['projects'],2)
            self.assertTrue(any(p['id']=='wal-project' for p in Workspace(snapshot).projects('operator')))
        finally:
            db.close()

    def test_restored_cli_server_serves_original_and_audit_after_relogin(self):
        import http.cookiejar
        import urllib.request
        backup=self.root/'http-backup.sqlite';restored=self.root/'http-restored.sqlite'
        backup_database(self.path,backup);restore_database(backup,restored)
        child=subprocess.Popen([sys.executable,'-m','urs','--data',str(restored),'serve','--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            line=child.stdout.readline();port=int(line.rsplit(' ',1)[1]);base=f'http://127.0.0.1:{port}'
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            request=urllib.request.Request(base+'/api/login',data=json.dumps({'username':'operator','password':'synthetic-backup-password'}).encode(),headers={'Content-Type':'application/json'})
            with opener.open(request,timeout=10) as response:self.assertTrue(json.load(response)['csrf'])
            with opener.open(base+f'/api/documents/{self.doc}/original',timeout=10) as response:
                self.assertEqual(response.read(),self.payload)
            with opener.open(base+f'/api/documents/{self.doc}/verification.json',timeout=10) as response:
                proof=json.load(response)
            self.assertEqual(proof['record_sha256'],self.w.verification_record('operator',self.doc)['record_sha256'])
            self.assertEqual(proof['record']['snapshot']['revision'],1)
        finally:
            child.terminate();child.wait(timeout=10)
            child.stdout.close();child.stderr.close()

    def test_processed_html_and_source_crops_survive_restore(self):
        document=self._processed_document()
        snapshot=self.root/'processed-backup.sqlite';restored=self.root/'processed-restored.sqlite'
        backup_database(self.path,snapshot);restore_database(snapshot,restored)
        recovered=Workspace(restored)
        for kind in ('report.raw.html','report.html','report-images','image-bindings','report-metadata'):
            self.assertEqual(recovered.artifact('operator',document,kind),self.w.artifact('operator',document,kind))
        self.assertEqual(recovered.verification_record('operator',document)['record_sha256'],self.w.verification_record('operator',document)['record_sha256'])

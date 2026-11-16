import base64
import hashlib
import http.cookiejar
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from urs.web import make_app
from urs.workflow import Blocked
from urs.workspace import AccessDenied, Unauthorized, Workspace


def pdf(encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    if encrypted:
        writer.encrypt('fixture-encryption')
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class WorkspaceTests(unittest.TestCase):
    def test_operator_password_reset_invalidates_only_target_sessions_and_keeps_documents(self):
        alice,_=self.w.login('alice','alice-test-password-123')
        bob,_=self.w.login('bob','bob-test-password-456')
        project=self.w.create_project('alice','password recovery fixture')
        doc=self.w.upload('alice',project,'source.pdf',pdf())
        before=self.w.verification_record('alice',doc)['record_sha256']
        self.w.reset_password('alice','new-synthetic-password-123')
        with self.assertRaises(Unauthorized):self.w.session(alice)
        with self.assertRaises(Unauthorized):self.w.login('alice','alice-test-password-123')
        token,_=self.w.login('alice','new-synthetic-password-123')
        self.assertEqual(self.w.session(token)[0],'alice')
        self.assertEqual(self.w.session(bob)[0],'bob')
        self.assertEqual(before,self.w.verification_record('alice',doc)['record_sha256'])

    def test_invalid_reset_does_not_create_account_or_invalidate_session(self):
        token,_=self.w.login('alice','alice-test-password-123')
        for name,password in [('missing','valid-synthetic-password'),('alice','short')]:
            with self.assertRaises(ValueError):self.w.reset_password(name,password)
        self.assertEqual(self.w.session(token)[0],'alice')
        self.assertTrue(self.w.login('alice','alice-test-password-123'))

    def test_password_reset_cli_uses_hidden_prompt_and_does_not_print_password(self):
        import contextlib
        from urs.__main__ import main
        password='new-synthetic-hidden-password'
        output=io.StringIO()
        with patch('sys.argv',['urs','--data',self.w.workflow.path,'reset-password','alice']),patch('getpass.getpass',side_effect=[password,password]),contextlib.redirect_stdout(output):
            main()
        self.assertNotIn(password,output.getvalue())
        self.assertTrue(self.w.login('alice',password))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'workspace.sqlite'
        self.w = Workspace(self.path)
        self.w.add_user('alice', 'alice-test-password-123')
        self.w.add_user('bob', 'bob-test-password-456')
        self.project = self.w.create_project('alice', '검증 프로젝트')
        self.payload = pdf()

    def test_password_hash_sessions_logout_expiry(self):
        with self.w.workflow.connect() as db:
            row = db.execute('SELECT * FROM users WHERE name=?', ('alice',)).fetchone()
            self.assertNotEqual(row['digest'], b'alice-test-password-123')
            self.assertEqual(len(row['salt']), 16)
        for username, password in [('alice', 'wrong'), ('unknown', 'wrong')]:
            with self.assertRaises(Unauthorized):
                self.w.login(username, password)
        token, csrf = self.w.login('alice', 'alice-test-password-123')
        self.assertEqual(self.w.session(token), ('alice', csrf))
        with self.w.workflow.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM sessions WHERE digest=?', (token,)).fetchone())
        restored = Workspace(self.path)
        self.assertEqual(restored.session(token)[0], 'alice')
        restored.logout(token)
        with self.assertRaises(Unauthorized):
            restored.session(token)
        token, _ = restored.login('alice', 'alice-test-password-123')
        with self.w.workflow.connect() as db:
            db.execute('UPDATE sessions SET expires=?', (time.time() - 1,))
        with self.assertRaises(Unauthorized):
            restored.session(token)

    def test_login_rate_limit_and_password_policy(self):
        with self.assertRaises(ValueError):
            self.w.add_user('weak', 'short')
        for _ in range(5):
            with self.assertRaises(Unauthorized):
                self.w.login('alice', 'wrong')
        with self.assertRaises(Unauthorized):
            self.w.login('alice', 'alice-test-password-123')
        with self.w.workflow.connect() as db:
            db.execute('UPDATE attempts SET since=?', (time.time() - 61,))
        self.assertTrue(self.w.login('alice', 'alice-test-password-123')[0])

    def test_owner_isolation_and_restart(self):
        document = self.w.upload('alice', self.project, 'spec.pdf', self.payload)
        restored = Workspace(self.path)
        self.assertEqual(restored.projects('alice')[0]['id'], self.project)
        self.assertEqual(restored.projects('bob'), [])
        self.assertEqual(restored.documents('alice', self.project)[0]['id'], document)
        for action in [lambda: restored.documents('bob', self.project),
                       lambda: restored.original('bob', document),
                       lambda: restored.status('bob', document),
                       lambda: restored.run('bob', document, 'source'),
                       lambda: restored.upload('bob', self.project, 'x.pdf', self.payload)]:
            with self.assertRaises(AccessDenied):
                action()

    def test_original_bytes_immutable_and_not_overwritten(self):
        doc1 = self.w.upload('alice', self.project, '../../spec.pdf', self.payload)
        doc2 = self.w.upload('alice', self.project, '../../spec.pdf', self.payload)
        self.assertNotEqual(doc1, doc2)
        original = self.w.original('alice', doc1)
        self.assertEqual(original['name'], 'spec.pdf')
        self.assertEqual(original['original'], self.payload)
        self.assertEqual(original['sha256'], hashlib.sha256(self.payload).hexdigest())
        for sql in ['UPDATE documents SET original=? WHERE id=?', 'DELETE FROM documents WHERE id=?']:
            with self.assertRaises(sqlite3.IntegrityError):
                with self.w.workflow.connect() as db:
                    db.execute(sql, (b'corrupt', doc1) if sql.startswith('UPDATE') else (doc1,))
        self.assertEqual(self.w.original('alice', doc1)['original'], self.payload)

    def test_invalid_encrypted_oversize_empty_pdf_rejected(self):
        writer = PdfWriter()
        empty = io.BytesIO()
        writer.write(empty)
        for name, payload in [('x.txt', self.payload), ('x.pdf', b'not a PDF'),
                              ('x.pdf', b'%PDF-1.7\ninvalid'), ('x.pdf', pdf(True)),
                              ('x.pdf', b''), ('x.pdf', empty.getvalue())]:
            with self.subTest(name=name, size=len(payload)), self.assertRaises(ValueError):
                self.w.upload('alice', self.project, name, payload)
        with patch('urs.workspace.MAX_PDF', len(self.payload) - 1):
            with self.assertRaises(ValueError):
                self.w.upload('alice', self.project, 'x.pdf', self.payload)
        self.assertEqual(self.w.documents('alice', self.project), [])

    def test_only_original_integrity_passes_and_downstream_blocks(self):
        document = self.w.upload('alice', self.project, 'spec.pdf', self.payload)
        snapshot = self.w.status('alice', document)
        self.assertTrue(snapshot['stages'][0]['passed'])
        self.assertFalse(any(s['passed'] for s in snapshot['stages'][1:]))
        self.assertFalse(snapshot['approved'])
        with self.assertRaises(ValueError):self.w.run('alice',document,'extract')
        with self.assertRaises(Blocked):self.w.run('alice',document,'report')
        with self.assertRaises(Blocked):self.w.run('alice',document,'verify')
        with self.assertRaises(Blocked):
            self.w.workflow.approve(document, 1, 'alice')

    def test_http_login_upload_download_csrf_and_other_user(self):
        server = make_app(self.w, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        csrf = ''
        def req(path, body=None, headers=None):
            request_headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}
            request_headers.update(headers or {})
            request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=request_headers)
            try:
                with opener.open(request) as r:
                    raw = r.read()
                    return r.status, json.loads(raw) if 'application/json' in r.headers['Content-Type'] else raw, r.headers
            except urllib.error.HTTPError as e:
                return e.code, json.load(e), e.headers
        self.assertEqual(req('/api/projects')[0], 401)
        code, login, headers = req('/api/login', {'username': 'alice', 'password': 'alice-test-password-123'})
        self.assertEqual(code, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertEqual(req('/api/projects', {'title': 'blocked-without-csrf'})[0], 403)
        csrf = login['csrf']
        self.assertEqual(req('/api/projects', {'title': 'cross-origin'}, {'Origin': 'https://attacker.invalid'})[0], 403)
        code, project, _ = req('/api/projects', {'title': '<script>not markup</script>'})
        self.assertEqual(code, 201)
        path = f"/api/projects/{project['id']}/documents"
        code, document, _ = req(path, {'name': 'sample.pdf', 'content': base64.b64encode(self.payload).decode()})
        self.assertEqual(code, 201)
        doc = document['id']
        record_code,record,record_headers=req(f'/api/documents/{doc}/verification.json')
        self.assertEqual(record_code,200)
        self.assertEqual(record['record']['document_id'],doc)
        self.assertIn('attachment',record_headers['Content-Disposition'])
        self.assertEqual(req(f'/api/documents/{doc}/verification.html')[0],200)
        self.assertEqual(req(f'/api/documents/{doc}/original')[1], self.payload)
        self.assertEqual(req(f'/api/documents/{doc}/run', {'stage': 'translate'})[0], 404)
        self.assertEqual(req(f'/api/documents/{doc}/run', {'stage': 'extract', 'status': 'PASS'})[0], 400)
        self.assertEqual(req(path, {'name': 'x.pdf', 'content': 'invalid-base64'})[0], 400)
        self.assertEqual(req('/api/logout', {})[0], 200)
        self.assertEqual(req(f'/api/documents/{doc}/original')[0], 401)
        self.assertEqual(req(f'/api/documents/{doc}/verification.json')[0],401)
        csrf = req('/api/login', {'username': 'bob', 'password': 'bob-test-password-456'})[1]['csrf']
        self.assertEqual(req('/api/projects')[1], [])
        self.assertEqual(req(f'/api/documents/{doc}/original')[0], 403)
        self.assertEqual(req(f'/api/documents/{doc}/verification.json')[0],403)
        self.assertEqual(req(f'/api/documents/{doc}/verification.html')[0],403)
        self.assertEqual(req(path)[0], 403)
        self.assertEqual(req('/')[0], 200)
        self.assertIn('고객 원본 PDF'.encode(), req('/')[1])
        self.assertEqual(req('/app.js')[0], 200)
        self.assertEqual(req('/app.css')[0], 200)

    def test_verification_record_has_original_status_and_valid_content_hash(self):
        document=self.w.upload('alice',self.project,'spec.pdf',self.payload)
        bundle=self.w.verification_record('alice',document)
        record=bundle['record']
        self.assertEqual(record['original']['sha256'],hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(record['snapshot']['revision'],1)
        self.assertFalse(record['snapshot']['approved'])
        self.assertTrue(record['snapshot']['stages'][0]['passed'])
        self.assertFalse(record['snapshot']['stages'][1]['passed'])
        canonical=json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),bundle['record_sha256'])
        record['snapshot']['approved']=True
        altered=json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        self.assertNotEqual(hashlib.sha256(altered).hexdigest(),bundle['record_sha256'])

    def test_verification_record_does_not_include_environment_or_login_credentials(self):
        document=self.w.upload('alice',self.project,'spec.pdf',self.payload)
        token,csrf=self.w.login('alice','alice-test-password-123')
        marker='private-environment-marker-not-a-real-key'
        with patch.dict('os.environ',{'URS_OPENAI_API_KEY':marker}):
            raw=json.dumps(self.w.verification_record('alice',document))
        for secret in (marker,token,csrf,'alice-test-password-123','bob-test-password-456'):
            self.assertNotIn(secret,raw)

    def test_verification_record_is_owner_only(self):
        document=self.w.upload('alice',self.project,'spec.pdf',self.payload)
        with self.assertRaises(AccessDenied):self.w.verification_record('bob',document)

    def test_verification_record_preserves_old_results_after_edit(self):
        document=self.w.upload('alice',self.project,'spec.pdf',self.payload)
        self.w.workflow.edit(document,1,json.dumps({'document':document,'sha256':hashlib.sha256(self.payload).hexdigest(),'revision':2}))
        record=self.w.verification_record('alice',document)['record']
        self.assertEqual(record['snapshot']['revision'],2)
        self.assertFalse(record['snapshot']['approved'])
        self.assertEqual(record['snapshot']['results'],[])
        self.assertEqual({r['revision'] for r in record['all_results']},{1})
        self.assertTrue(any(e['action']=='edited_all_results_invalidated' for e in record['snapshot']['events']))

    def test_readable_record_escapes_customer_content_and_shows_unverified(self):
        from urs.audit import html_report
        document=self.w.upload('alice',self.project,'<script>alert(1)</script>.pdf',self.payload)
        bundle=self.w.verification_record('alice',document)
        bundle['record']['snapshot']['events'][0]['detail']=json.dumps({'note':'<script>alert(2)</script>'})
        html=html_report(bundle).decode()
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('승인 전',html)
        self.assertIn('확인 전',html)
        self.assertIn('전자서명이나 실제 번역 정확도 인증은 아닙니다',html)

    def test_repeat_exports_of_unchanged_document_have_matching_record_hashes(self):
        document=self.w.upload('alice',self.project,'spec.pdf',self.payload)
        first=self.w.verification_record('alice',document)
        second=self.w.verification_record('alice',document)
        self.assertEqual(first['record_sha256'],second['record_sha256'])
        self.assertEqual(first['record'],second['record'])
        self.assertIn('exported_at_kst',second)

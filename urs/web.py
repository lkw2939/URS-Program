"""Loopback employee application. Public deployment requires an HTTPS proxy."""
import base64
import binascii
import hmac
import json
import sqlite3
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from urs.workflow import Blocked
from urs.ai import AIBlocked, AIError
from urs.workspace import AccessDenied, Unauthorized, MAX_PDF

STATIC = Path(__file__).resolve().parents[1] / 'static'


def make_app(workspace, port=8795, secure_cookie=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, kind='application/json; charset=utf-8', cookie=None, attachment=None, report=False):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                "sandbox allow-scripts allow-modals; default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; worker-src blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; connect-src https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; img-src data: blob: https:; style-src 'unsafe-inline' https:; font-src data: blob: https:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'" if report else
                "default-src 'self'; script-src 'self'; style-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            if attachment:
                self.send_header('Content-Disposition', 'attachment; filename="' + attachment + '"')
            self.end_headers()
            self.wfile.write(data)

        def cookie(self, token, expire=False):
            return ('urs_session=' + token + '; Path=/; HttpOnly; SameSite=Strict; Max-Age=' +
                    ('0' if expire else '28800') + ('; Secure' if secure_cookie else ''))

        def token(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            return cookie['urs_session'].value if 'urs_session' in cookie else ''

        def do_GET(self):
            self.dispatch(False)

        def do_POST(self):
            self.dispatch(True)

        def dispatch(self, post):
            try:
                path = urlparse(self.path).path
                if not post and path in ('/', '/app.js', '/app.css'):
                    file = {'/': 'index.html', '/app.js': 'app.js', '/app.css': 'app.css'}[path]
                    kind = {'/': 'text/html', '/app.js': 'text/javascript', '/app.css': 'text/css'}[path]
                    self.reply(200, (STATIC / file).read_bytes(), kind + '; charset=utf-8')
                    return
                body = {}
                if post:
                    # Same-origin JSON plus custom CSRF header on authenticated writes.
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        raise ValueError('JSON 요청이 필요합니다.')
                    origin = self.headers.get('Origin')
                    host = self.headers.get('Host', '')
                    if origin and origin not in ('http://' + host, 'https://' + host):
                        raise AccessDenied('다른 사이트의 요청을 허용하지 않습니다.')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= (MAX_PDF * 4 // 3 + 4096):
                        self.reply(413, {'error': '업로드 제한을 초과했습니다.'})
                        return
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError('객체 형식이 필요합니다.')
                if post and path == '/api/login':
                    token, csrf = workspace.login(body.get('username'), body.get('password'))
                    self.reply(200, {'csrf': csrf}, cookie=self.cookie(token))
                    return
                token = self.token()
                owner, csrf = workspace.session(token)
                if post and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), csrf):
                    raise AccessDenied('요청 인증에 실패했습니다.')
                if not post and path == '/api/me':
                    self.reply(200, {'username': owner, 'csrf': csrf})
                elif post and path == '/api/logout':
                    workspace.logout(token)
                    self.reply(200, {'ok': True}, cookie=self.cookie('', True))
                elif path == '/api/settings/report':
                    self.reply(200,workspace.save_report_settings(owner,body['prompt']) if post else workspace.report_settings(owner))
                elif path == '/api/projects':
                    if post:
                        self.reply(201, {'id': workspace.create_project(owner, body['title'])})
                    else:
                        self.reply(200, workspace.projects(owner))
                else:
                    parts = path.strip('/').split('/')
                    if len(parts) == 4 and parts[:2] == ['api', 'projects'] and parts[3] == 'documents':
                        if post:
                            if set(body) != {'name', 'content'} or not isinstance(body['content'], str):
                                raise ValueError('PDF 이름과 데이터가 필요합니다.')
                            payload = base64.b64decode(body['content'], validate=True)
                            self.reply(201, {'id': workspace.upload(owner, parts[2], body['name'], payload)})
                        else:
                            self.reply(200, workspace.documents(owner, parts[2]))
                    elif len(parts) == 4 and parts[:2] == ['api', 'documents']:
                        document, action = parts[2:]
                        if not post and action == 'original':
                            original = workspace.original(owner, document)
                            self.reply(200, original['original'], 'application/pdf', attachment=document + '.pdf')
                        elif not post and action == 'status':
                            self.reply(200, workspace.status(owner, document))
                        elif not post and action in ('verification.json','verification.html'):
                            bundle=workspace.verification_record(owner,document)
                            if action.endswith('.html'):
                                from urs.audit import html_report
                                payload=html_report(bundle);mime='text/html; charset=utf-8'
                            else:
                                payload=json.dumps(bundle,ensure_ascii=False,indent=2).encode();mime='application/json; charset=utf-8'
                            self.reply(200,payload,mime,attachment=action)
                        elif not post and action == 'detail':
                            data = {'status': workspace.status(owner, document)}
                            for kind in ('report-metadata','image-bindings','verification','analysis'):
                                try:
                                    data[kind] = workspace.artifact(owner, document, kind)
                                except Blocked:
                                    pass
                            self.reply(200, data)
                        elif not post and action in ('report.html','report.raw.html'):
                            from urllib.parse import parse_qs
                            query=parse_qs(urlparse(self.path).query)
                            revision=int(query['revision'][0]) if 'revision' in query else None
                            self.reply(200,workspace.report_html(owner,document,action=='report.raw.html',revision),
                                'text/html; charset=utf-8',attachment='report.raw.html' if action=='report.raw.html' else None,report=True)
                        elif not post and (action.startswith('draft-') or action.startswith('final-')):
                            final = action.startswith('final-')
                            kind = action.split('-',1)[1]
                            payload = workspace.export(owner,document,kind,final)
                            mime = 'application/pdf' if kind.endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                            self.reply(200,payload,mime,attachment=action)
                        elif post and action == 'approve':
                            self.reply(200,workspace.approve_document(owner,document,body['revision'],body['note'],body['reviewed_outputs']))
                        elif post and action == 'run':
                            if set(body) != {'stage'}:
                                raise ValueError('검증 상태는 서버만 기록할 수 있습니다.')
                            if body['stage'] not in ('source','report','verify','analyze'):
                                self.reply(404,{'error':'존재하지 않는 단계입니다.'})
                                return
                            self.reply(200, workspace.run(owner, document, body['stage']))
                        else:
                            self.reply(404, {'error': '존재하지 않는 기능입니다.'})
                    else:
                        self.reply(404, {'error': '존재하지 않는 경로입니다.'})
            except Unauthorized as exc:
                self.reply(401, {'error': str(exc)})
            except AccessDenied as exc:
                self.reply(403, {'error': str(exc)})
            except Blocked as exc:
                self.reply(409, {'error': str(exc)})
            except AIBlocked as exc:
                self.reply(409, {'error': str(exc)})
            except AIError as exc:
                self.reply(502, {'error': str(exc)})
            except (ValueError, KeyError, TypeError, binascii.Error):
                self.reply(400, {'error': '요청을 확인해 주세요. PDF 형식·크기 또는 입력이 올바르지 않습니다.'})
            except sqlite3.Error:
                self.reply(503, {'error': '저장소 작업에 실패했습니다. 잠시 후 다시 시도해 주세요.'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)

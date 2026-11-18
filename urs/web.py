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
from urs.ai_settings import SettingsError
from urs.costing import CostError
from urs.workspace import AccessDenied, Unauthorized, MAX_PDF

STATIC = Path(__file__).resolve().parents[1] / 'static'


def make_app(workspace, port=8795, secure_cookie=False):
    from urs.report_tasks import ReportTasks
    tasks=ReportTasks(workspace)
    from urs import targets
    target_tasks=targets.Tasks(workspace)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, kind='application/json; charset=utf-8', cookie=None, attachment=None, report=False, review=False):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                "sandbox allow-scripts allow-modals; default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; worker-src blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; connect-src https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; img-src data: blob: https:; style-src 'unsafe-inline' https:; font-src data: blob: https:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'" if report else
                "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" if review else
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
                if not post and path in ('/', '/app.js', '/app.css', '/review.js', '/review.css'):
                    file = {'/': 'index.html', '/app.js': 'app.js', '/app.css': 'app.css', '/review.js':'review.js','/review.css':'review.css'}[path]
                    kind = {'/': 'text/html', '/app.js': 'text/javascript', '/app.css': 'text/css', '/review.js':'text/javascript','/review.css':'text/css'}[path]
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
                elif path == '/api/settings/ai':
                    self.reply(200,workspace.save_ai_settings(owner,body) if post else workspace.ai_settings(owner))
                elif path == '/api/settings/report-timeout':
                    self.reply(200,workspace.report_timeout(owner,body['timeout_seconds']) if post else workspace.report_timeout(owner))
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
                            from urs.reviews import overview
                            data = {'targets':targets.listing(workspace,owner,document),'reviews':overview(workspace,owner,document),'report_task':tasks.status(document),'status': workspace.status(owner, document), 'reports': workspace.report_availability(owner,document)}
                            for kind in ('report-metadata','image-bindings','verification','analysis'):
                                try:
                                    data[kind] = workspace.artifact(owner, document, kind)
                                except Blocked:
                                    pass
                            selected=data['reports']['selected']
                            data['current_report']=selected
                            data['current_review']=target_tasks.status(owner,document,f"displayed:{document}:{selected['revision']}") if selected else None
                            try:data['latest_layout']=workspace.processing.get(document,'layout-audit',data['status']['revision'])
                            except Blocked:data['latest_layout']=None
                            data['generation_contract']=__import__('urs.report_contract',fromlist=['TEXT']).TEXT
                            data['image_presentation_version']=__import__('urs.image_presentation',fromlist=['VERSION']).VERSION
                            try:data['current_layout']=workspace.processing.get(document,'layout-audit',selected['revision']) if selected else None
                            except Blocked:data['current_layout']={'status':'UNVERIFIED','reason':'기존 보고서는 A4 화면 검사를 받지 않았습니다. 사진 표시·배치를 점검해야 합니다.'}
                            for stage in ('verify','analyze'):
                                if tasks.status(document,stage)['state']=='running':data['reviews'][stage].update(running=True,can_run=False,blocked_reason='실행 중입니다. 결과가 저장될 때까지 기다려 주세요.')
                            self.reply(200, data)
                        elif not post and action=='review-result-data':
                            from urllib.parse import parse_qs
                            from urs.review_results import load
                            q=parse_qs(urlparse(self.path).query)
                            self.reply(200,load(workspace,owner,document,q['target'][0],int(q['attempt'][0])))
                        elif post and action=='correction-preview':
                            from urs.corrections import preview
                            from urs.review_results import CorrectionInputError
                            try:result=preview(workspace,owner,document,body['target'],int(body['attempt']),body['changes'])
                            except CorrectionInputError as exc:
                                self.reply(400,{'error':str(exc)});return
                            self.reply(200,result)
                        elif post and action=='correction-apply':
                            from urs.corrections import apply
                            self.reply(200,apply(workspace,owner,document,body['plan_id']))
                        elif post and action=='review-prepare':
                            from urs.costing import review_quote
                            selected=workspace.report_availability(owner,document)['selected']
                            if not selected or body['stage'] not in ('verify','analyze'):raise Blocked('검증할 현재 보고서가 없습니다.')
                            target=f"displayed:{document}:{selected['revision']}"
                            info=targets.overview(workspace,owner,document,target)
                            if body.get('expected_revision')!=selected['revision'] or body.get('expected_sha256')!=info['sha256']:raise Blocked('현재 보고서가 바뀌었습니다. 화면을 새로고침해 주세요.')
                            stage=body['stage']
                            if info['reviews'][stage]['running']:raise Blocked('이미 실행 중입니다. 결과를 기다려 주세요.')
                            if stage=='analyze' and info['reviews']['verify']['status']!='PASS':raise Blocked('현재 보고서의 독립검증 PASS 후 기술분석을 실행할 수 있습니다.')
                            self.reply(200,review_quote(workspace,owner,document,target,stage,True))
                        elif post and action=='cost-preview':
                            from urs.costing import review_quote,report_quote
                            stage=body['stage']
                            if stage=='report':result=report_quote(workspace,owner,document,True)
                            elif stage in ('verify','analyze'):
                                selected=workspace.report_availability(owner,document)['selected']
                                if not selected:raise Blocked('열람할 저장 보고서가 없습니다.')
                                result=review_quote(workspace,owner,document,f"displayed:{document}:{selected['revision']}",stage,True)
                            else:raise ValueError('실행 단계를 확인하세요.')
                            self.reply(200,result)
                        elif post and action=='current-review-run':
                            selected=workspace.report_availability(owner,document)['selected']
                            if not selected:raise Blocked('정상 저장된 보고서가 없습니다. 생성 실패 또는 배치 확인 이력을 확인하세요.')
                            if body['stage'] not in ('verify','analyze'):raise ValueError('검토 단계를 확인하세요.')
                            ident=f"displayed:{document}:{selected['revision']}"
                            visible,_=targets.get(workspace,owner,document,ident)
                            if body.get('expected_revision')!=selected['revision'] or body.get('expected_sha256')!=visible['sha256']:raise Blocked('보고서가 갱신됐거나 화면과 다릅니다. 새로고침해 현재 보고서를 확인한 뒤 실행하세요. API를 호출하지 않았습니다.')
                            from urs.costing import review_quote
                            q=review_quote(workspace,owner,document,ident,body['stage'])
                            if q['status']!='READY':raise Blocked('먼저 무료 비용 계산으로 이번 1회 예상액을 확인하세요.')
                            workspace.processing.authorized_quotes[(document,'independent_verify' if body['stage']=='verify' else 'technical_analysis')]=q['fingerprint']
                            result=target_tasks.start(owner,document,ident,body['stage'])
                            self.reply(202,{**result,'target':ident})
                        elif post and action=='target-cost-preview':
                            from urs.costing import review_quote
                            if body['stage'] not in ('verify','analyze'):raise ValueError('실행 단계를 확인하세요.')
                            self.reply(200,review_quote(workspace,owner,document,body['target'],body['stage'],True))
                        elif not post and action=='usage-preview':
                            from urs.usage_audit import server_preview
                            self.reply(200,server_preview(workspace,owner,document))
                        elif action=='review-targets':
                            if post:
                                payload=base64.b64decode(body['content'],validate=True)
                                ident=targets.register(workspace,owner,document,body['parent_revision'],body['name'],payload)
                                self.reply(201,{'id':ident})
                            else:self.reply(200,targets.listing(workspace,owner,document))
                        elif not post and action=='target-status':
                            from urllib.parse import parse_qs
                            target=parse_qs(urlparse(self.path).query)['target'][0]
                            self.reply(200,target_tasks.status(owner,document,target))
                        elif post and action=='target-run':
                            from urs.costing import review_quote
                            q=review_quote(workspace,owner,document,body['target'],body['stage'])
                            if q['status']!='READY':raise Blocked('먼저 선택 대상의 무료 비용 계산을 확인하세요.')
                            workspace.processing.authorized_quotes[(document,'independent_verify' if body['stage']=='verify' else 'technical_analysis')]=q['fingerprint']
                            if body['stage'] not in ('verify','analyze'):raise ValueError('검토 단계를 확인하세요.')
                            self.reply(202,target_tasks.start(owner,document,body['target'],body['stage']))
                        elif not post and action in ('target.html','target-result.html'):
                            from urllib.parse import parse_qs
                            q=parse_qs(urlparse(self.path).query);ident=q['target'][0]
                            if action=='target.html':
                                row,_=targets.get(workspace,owner,document,ident)
                                self.reply(200,bytes(row['payload']),'text/html; charset=utf-8',attachment=('stored-r'+str(row['parent_revision'])+'.raw.html' if row['kind']=='stored_revision' else 'registered-a4.html'),report=True)
                            else:
                                stage=q['stage'][0]
                                if stage not in ('verify','analyze'):raise ValueError('검토 단계를 확인하세요.')
                                self.reply(200,targets.result_html(workspace,owner,document,ident,stage,int(q['attempt'][0])),'text/html; charset=utf-8',review=True)
                        elif not post and action in ('review-verification.html','review-analysis.html'):
                            from urs.reviews import result_html
                            from urllib.parse import parse_qs
                            query=parse_qs(urlparse(self.path).query)
                            attempt=int(query['attempt'][0]) if 'attempt' in query else None
                            revision=int(query['revision'][0]) if 'revision' in query else None
                            self.reply(200,result_html(workspace,owner,document,'verify' if action=='review-verification.html' else 'analyze',attempt,revision),'text/html; charset=utf-8',review=True)
                        elif not post and action in ('verify-task','analyze-task'):
                            workspace.original(owner,document)
                            self.reply(200,tasks.status(document,'verify' if action=='verify-task' else 'analyze'))
                        elif not post and action == 'stored-review.zip':
                            from urllib.parse import parse_qs
                            query=parse_qs(urlparse(self.path).query)
                            revision=int(query.get('revision',[workspace.status(owner,document)['revision']])[0])
                            self.reply(200,workspace.stored_report_review(owner,document,revision),'application/zip',attachment=f'stored-html-r{revision}.zip')
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
                        elif not post and action == 'report-task':
                            workspace.original(owner,document)
                            self.reply(200,tasks.status(document))
                        elif post and action == 'run':
                            if set(body)=={'stage','background'} and body['background'] is True and body['stage'] in ('verify','analyze'):
                                self.reply(202,tasks.start(owner,document,body['stage']));return
                            if body=={'stage':'report','background':True}:
                                from urs.costing import report_quote
                                q=report_quote(workspace,owner,document)
                                if q['status']!='READY':raise Blocked('먼저 보고서 무료 비용 계산으로 이번 실행 예상액을 확인하세요.')
                                if q['blocked']:raise Blocked('이번 보고서 1회 예상 비용이 실행 한도를 넘습니다.')
                                workspace.processing.authorized_quotes[(document,'report_html')]=q['fingerprint']
                                self.reply(202,tasks.start(owner,document));return
                            if set(body) != {'stage'}:
                                raise ValueError('검증 상태는 서버만 기록할 수 있습니다.')
                            if body['stage'] not in ('source','report','verify','analyze'):
                                self.reply(404,{'error':'존재하지 않는 단계입니다.'})
                                return
                            if body['stage'] in ('verify','analyze'):
                                from urs.reviews import run
                                self.reply(200,run(workspace,owner,document,body['stage']))
                            else:self.reply(200, workspace.run(owner, document, body['stage']))
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
            except (SettingsError,CostError) as exc:
                self.reply(400,{'error':str(exc)})
            except (ValueError, KeyError, TypeError, binascii.Error):
                self.reply(400, {'error': '요청을 확인해 주세요. PDF 형식·크기 또는 입력이 올바르지 않습니다.'})
            except sqlite3.Error:
                self.reply(503, {'error': '저장소 작업에 실패했습니다. 잠시 후 다시 시도해 주세요.'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)

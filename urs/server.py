"""Internal loopback API for stage-one integration. Not an employee login UI."""
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from urs.workflow import Blocked


def make_server(workflow, validators, token, port=0):
    if not token or len(token) < 32:
        raise ValueError('internal bearer token must have at least 32 characters')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.handle_api(False)

        def do_POST(self):
            self.handle_api(True)

        def handle_api(self, post):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send(401, {'error': 'authentication required'})
                return
            try:
                if post:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 1_000_000:
                        raise ValueError('invalid body size')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError('object required')
                else:
                    body = {}
                parts = urlparse(self.path).path.strip('/').split('/')
                if len(parts) < 2 or parts[0] != 'jobs':
                    self.send(404, {'error': 'not found'})
                    return
                job = parts[1]
                action = parts[2] if len(parts) == 3 else ''
                if not post and len(parts) == 2:
                    self.send(200, workflow.snapshot(job))
                    return
                if not post:
                    self.send(404, {'error': 'not found'})
                    return
                if action == 'create':
                    workflow.create(job, body['content'])
                elif action == 'edit':
                    workflow.edit(job, body['revision'], body['content'])
                elif action == 'run':
                    if set(body) != {'stage'}:
                        raise ValueError('only stage may be supplied; results are server-owned')
                    workflow.run(job, body['stage'], validators)
                elif action == 'approve':
                    workflow.approve(job, body['revision'], 'internal-operator')
                else:
                    self.send(404, {'error': 'not found'})
                    return
                # Human development review is deliberately not exposed in this
                # internal API; real employee identity/permissions come in stage 2.
                self.send(200, workflow.snapshot(job))
            except Blocked as exc:
                self.send(409, {'error': str(exc)})
            except (ValueError, KeyError, TypeError) as exc:
                self.send(400, {'error': str(exc)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)

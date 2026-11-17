"""Employee settings, actual adapter payloads and output-limit protection (mock API)."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import http.cookiejar
from unittest.mock import patch
from html_fixtures import PROMPT,RAW,visual_pdf
from urs.workspace import Workspace,AccessDenied
from urs.ai import OpenAI,AIBlocked
from urs.ai_settings import SettingsError
from urs.web import make_app

ENV={'URS_OPENAI_API_KEY':'fixture-private-key-never-return','URS_OPENAI_MODEL':'server-model','URS_OPENAI_REASONING_EFFORT':'medium',
 'URS_AI_BUDGET_USD':'50','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'2'}
CONFIG={'model':'web-model','effort':'xhigh','max_output_tokens':64000}

def response(raw=RAW,status='completed',reason=None):
    value={'status':status,'usage':{'output_tokens':12},'output':[{'content':[{'type':'output_text','text':raw}]}]}
    if reason:value['incomplete_details']={'reason':reason}
    return io.BytesIO(json.dumps(value).encode())

class AISettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'data.sqlite';self.w=Workspace(self.path)
        self.w.add_user('alice','fixture-password-alice');self.w.add_user('bob','fixture-password-bob')
        project=self.w.create_project('alice','API settings fixture')
        self.doc=self.w.upload('alice',project,'source.pdf',visual_pdf())
        self.w.save_report_settings('alice',PROMPT)

    def test_owner_isolation_persistence_and_append_only_history(self):
        with patch.dict(os.environ,ENV,clear=True):
            initial=self.w.ai_settings('alice');self.assertEqual(initial['max_output_tokens'],5000)
            self.assertEqual(initial['source'],'server')
            before=self.w.verification_record('alice',self.doc)['record_sha256']
            self.w.save_ai_settings('alice',CONFIG)
            restored=Workspace(self.path)
            self.assertEqual(restored.ai_settings('alice')['model'],'web-model')
            self.assertEqual(restored.ai_settings('bob')['model'],'server-model')
            self.w.save_ai_settings('alice',{**CONFIG,'max_output_tokens':32000})
            self.assertEqual(self.w.ai_settings('alice')['version'],2)
            self.assertEqual(self.w.verification_record('alice',self.doc)['record_sha256'],before)
        with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_settings').fetchone()[0],2)
        with self.assertRaises(AccessDenied):self.w.save_ai_settings('missing',CONFIG)

    def test_invalid_server_defaults_can_be_repaired_in_web_settings(self):
        with patch.dict(os.environ,{**ENV,'URS_OPENAI_MAX_OUTPUT_TOKENS':'bad'},clear=True):
            fallback=self.w.ai_settings('alice')
            self.assertIn('configuration_error',fallback)
            self.w.save_ai_settings('alice',CONFIG)
            self.assertEqual(self.w.ai_settings('alice')['max_output_tokens'],64000)

    def test_validation_rejects_unknown_fields_invalid_limits_and_effort(self):
        for config in [{**CONFIG,'max_output_tokens':0},{**CONFIG,'max_output_tokens':1.5},{**CONFIG,'max_output_tokens':True},
                       {**CONFIG,'max_output_tokens':1000001},{**CONFIG,'effort':'ultra'},{**CONFIG,'model':'bad\nmodel'},
                       {**CONFIG,'model':''},{**CONFIG,'api_key':'never-save-a-key'}]:
            with self.subTest(config=config),self.assertRaises(SettingsError):self.w.save_ai_settings('alice',config)
        with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_settings').fetchone()[0],0)

    def test_web_values_reach_report_and_review_payload_and_metadata(self):
        self.w.save_ai_settings('alice',CONFIG)
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=response()) as network:
            state=self.w.run('alice',self.doc,'report')
            self.assertTrue(next(s['passed'] for s in state['stages'] if s['id']=='report'))
            wire=json.loads(network.call_args.args[0].data)
        self.assertEqual(wire['model'],'web-model');self.assertEqual(wire['reasoning'],{'effort':'xhigh'})
        self.assertEqual(wire['max_output_tokens'],64000)
        self.assertEqual(wire['input'][0]['content'][1]['text'],PROMPT);self.assertNotIn('instructions',wire)
        metadata=self.w.artifact('alice',self.doc,'report-metadata')
        self.assertEqual(metadata['max_output_tokens'],64000);self.assertEqual(metadata['model'],'web-model')
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=response('{}')) as network:
            OpenAI(self.w.workflow,self.doc).review_pdf('independent_verify',b'%PDF-fixture','source.pdf','<html>saved</html>')
        self.assertEqual(json.loads(network.call_args.args[0].data)['max_output_tokens'],64000)

    def test_settings_apply_to_next_call_without_restart_or_rewriting_old_html(self):
        with patch.dict(os.environ,ENV,clear=True):
            self.w.save_ai_settings('alice',CONFIG)
            with patch('urllib.request.urlopen',return_value=response()):self.w.run('alice',self.doc,'report')
            raw=self.w.report_html('alice',self.doc,True,1);final=self.w.report_html('alice',self.doc,False,1)
            self.w.save_ai_settings('alice',{'model':'next-model','effort':'','max_output_tokens':32000})
            self.assertEqual(self.w.report_html('alice',self.doc,True,1),raw)
            self.assertEqual(self.w.report_html('alice',self.doc,False,1),final)
            with patch('urllib.request.urlopen',return_value=response()) as network:state=self.w.run('alice',self.doc,'report')
            wire=json.loads(network.call_args.args[0].data)
        self.assertEqual(state['revision'],2);self.assertEqual(wire['model'],'next-model')
        self.assertEqual(wire['max_output_tokens'],32000);self.assertNotIn('reasoning',wire)
        self.assertEqual(self.w.report_html('alice',self.doc,True,1),raw)

    def test_running_call_keeps_its_snapshot_if_settings_change_during_network(self):
        self.w.save_ai_settings('alice',CONFIG)
        def transport(request,**kwargs):
            self.w.save_ai_settings('alice',{'model':'changed','effort':'low','max_output_tokens':16000})
            return response()
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',side_effect=transport) as network:
            self.w.run('alice',self.doc,'report')
        metadata=self.w.artifact('alice',self.doc,'report-metadata')
        self.assertEqual(metadata['model'],'web-model');self.assertEqual(metadata['max_output_tokens'],64000)
        self.assertEqual(json.loads(network.call_args.args[0].data)['max_output_tokens'],64000)
        self.assertEqual(self.w.ai_settings('alice')['model'],'changed')

    def test_budget_reservation_uses_configured_output_limit(self):
        self.w.save_ai_settings('alice',CONFIG)
        with patch.dict(os.environ,{**ENV,'URS_AI_BUDGET_USD':'0.02'},clear=True),patch('urllib.request.urlopen') as network:
            with self.assertRaises(AIBlocked):OpenAI(self.w.workflow,self.doc).report_html(b'%PDF-x','x.pdf','prompt','map')
            network.assert_not_called()
        with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0],0)

    def test_output_limit_failure_is_visible_in_stage_evidence(self):
        self.w.save_ai_settings('alice',CONFIG)
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=response(status='incomplete',reason='max_output_tokens')):
            state=self.w.run('alice',self.doc,'report')
        result=next(r for r in state['results'] if r['stage']=='report')
        self.assertEqual(result['status'],'FAIL');self.assertIn('64,000',json.loads(result['evidence'])['reason'])
        self.assertIn('AI 호출 설정',json.loads(result['evidence'])['reason'])

    def test_http_settings_require_login_csrf_and_never_return_key(self):
        server=make_app(self.w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));csrf=''
        def request(path,body=None):
            req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
            return opener.open(req,timeout=10)
        with self.assertRaises(urllib.error.HTTPError) as error:request('/api/settings/ai')
        self.assertEqual(error.exception.code,401)
        with request('/api/login',{'username':'alice','password':'fixture-password-alice'}) as r:login=json.load(r)
        with self.assertRaises(urllib.error.HTTPError) as error:request('/api/settings/ai',CONFIG)
        self.assertEqual(error.exception.code,403);csrf=login['csrf']
        with patch.dict(os.environ,ENV,clear=True):
            with request('/api/settings/ai') as r:raw=r.read().decode();self.assertNotIn(ENV['URS_OPENAI_API_KEY'],raw)
            with request('/api/settings/ai',CONFIG) as r:self.assertEqual(json.load(r)['max_output_tokens'],64000)
            with request('/api/settings/ai') as r:self.assertEqual(json.load(r)['source'],'web')
        with self.assertRaises(urllib.error.HTTPError) as error:request('/api/settings/ai',{**CONFIG,'max_output_tokens':0})
        self.assertEqual(error.exception.code,400)

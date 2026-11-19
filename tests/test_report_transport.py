"""Real report adapter with mock HTTP; fixture DB only, no paid calls."""
import io,json,os,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from urs.workspace import Workspace
from urs.report_transport import diagnostics
from html_fixtures import RAW,PROMPT,visual_pdf
ENV={'URS_OPENAI_API_KEY':'PRIVATE-KEY-SHOULD-NOT-LOG','URS_OPENAI_MODEL':'mock-terra','URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
class Reply(io.BytesIO):
    status=200
    def __init__(self,value):super().__init__(json.dumps(value).encode())
def good(html=RAW):return Reply({'status':'completed','usage':{'input_tokens':12,'output_tokens':9},'output':[{'content':[{'type':'output_text','text':html}]}]})
class ReportTransportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('urs.costing.count_input_tokens',return_value=12000))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=Workspace(Path(self.tmp.name)/'mock.sqlite');self.w.add_user('alice','fixture-password-123')
        p=self.w.create_project('alice','timeout fixture');self.doc=self.w.upload('alice',p,'fixture.pdf',visual_pdf());self.w.save_report_settings('alice',PROMPT)
        self.w.save_ai_settings('alice',{'model':'mock-terra','effort':'high','max_output_tokens':16000})
    def run_report(self,response=None,error=None):
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',side_effect=error,return_value=response or good()) as network:
            state=self.w.run('alice',self.doc,'report')
        return state,network
    def record(self):return diagnostics(self.w.workflow,self.doc)[-1]
    def test_legacy_web_timeout_cannot_reenable_a_deadline(self):
        config=self.w.report_timeout('alice',900)
        self.assertTrue(config['unlimited']);self.assertFalse(config['legacy_value_applied']);self.assertEqual(config['legacy_timeout_seconds'],900)
        self.assertEqual(set(config['scope']),{'report_html','independent_verify','technical_analysis','input_token_count'})
        state,net=self.run_report();wire=json.loads(net.call_args.args[0].data)
        self.assertIsNone(net.call_args.kwargs['timeout']);self.assertEqual(wire['max_output_tokens'],16000)
        self.assertEqual(wire['input'][0]['content'][1]['text'],PROMPT)
        self.assertEqual(self.record()['outcome'],'completed');self.assertEqual(self.record()['http_status'],200)
        self.assertEqual(self.w.report_html('alice',self.doc,True),RAW.encode())
        with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT seconds FROM report_timeouts WHERE owner=?',('alice',)).fetchone()[0],900)
    def test_default_and_legacy_environment_both_wait_without_deadline(self):
        with patch.dict(os.environ,ENV,clear=True):self.assertIsNone(self.w.report_timeout('alice')['timeout_seconds'])
        with patch.dict(os.environ,{**ENV,'URS_OPENAI_REPORT_TIMEOUT_SECONDS':'1200'},clear=True):self.assertIsNone(self.w.report_timeout('alice')['timeout_seconds'])
        self.run_report();self.assertIsNone(self.record()['timeout_seconds']);self.assertEqual(self.record()['timeout_policy'],'unlimited')
    def test_timeout_before_response_preserves_old_files_and_exports_diagnostics(self):
        self.run_report();old=self.w.report_html('alice',self.doc,revision=1)
        state,net=self.run_report(error=TimeoutError('PRIVATE-KEY-SHOULD-NOT-LOG + DOCUMENT BODY'))
        d=self.record();self.assertEqual(d['outcome'],'timeout_before_response');self.assertIsNone(d['http_status'])
        self.assertEqual(d['max_output_tokens'],16000);self.assertGreaterEqual(d['elapsed_seconds'],0)
        self.assertIsNone(d['timeout_seconds']);self.assertEqual(d['timeout_origin'],'upstream_or_network')
        self.assertEqual(self.w.report_html('alice',self.doc,revision=1),old)
        with self.w.workflow.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM artifacts WHERE revision=2").fetchone()[0],0)
        evidence=json.loads(next(r['evidence'] for r in state['results'] if r['stage']=='report'))
        self.assertEqual(evidence['api_diagnostics']['outcome'],'timeout_before_response')
        bundle=self.w.verification_record('alice',self.doc);self.assertEqual(bundle['record']['api_diagnostics'][-1]['max_output_tokens'],16000)
        self.assertNotIn(ENV['URS_OPENAI_API_KEY'],json.dumps(bundle));self.assertNotIn('DOCUMENT BODY',json.dumps(bundle))
    def test_token_limit_is_distinct_and_incomplete_html_not_saved(self):
        self.run_report(response=Reply({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}))
        d=self.record();self.assertEqual(d['outcome'],'max_output_tokens');self.assertEqual(d['response_status'],'incomplete')
        self.assertEqual(self.w.report_availability('alice',self.doc)['state'],'none')
    def test_http_error_records_status_without_body(self):
        self.run_report(error=urllib.error.HTTPError('https://api.openai.com',429,'SECRET MESSAGE',{},io.BytesIO(b'SECRET BODY')))
        self.assertEqual(self.record()['http_status'],429);self.assertEqual(self.record()['outcome'],'http_error')
        self.assertNotIn('SECRET',json.dumps(self.record()))
    def test_response_received_but_json_unreadable(self):
        reply=io.BytesIO(b'PRIVATE BAD BODY');reply.status=200
        self.run_report(response=reply)
        self.assertEqual(self.record()['outcome'],'response_parse_error');self.assertEqual(self.record()['http_status'],200)
    def test_response_completed_but_html_unusable(self):
        self.run_report(response=Reply({'status':'completed','output':[{'content':[{'type':'output_text','text':'PRIVATE NON HTML BODY'}]}]}))
        self.assertEqual(self.record()['outcome'],'html_processing_error');self.assertEqual(self.record()['response_status'],'completed')
        self.assertEqual(self.w.report_availability('alice',self.doc)['state'],'none')
    def test_read_timeout_after_headers_is_not_response_before_timeout(self):
        class Partial:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):raise TimeoutError('PRIVATE')
        self.run_report(response=Partial());self.assertEqual(self.record()['outcome'],'timeout_reading_response')
    def test_image_binding_failure_recorded_without_mutating_old_report(self):
        self.run_report();old=self.w.report_html('alice',self.doc,revision=1)
        with patch('urs.layout_refinement.bind_images',side_effect=ValueError('PRIVATE')):self.run_report()
        self.assertEqual(self.record()['processing_phase'],'image_binding');self.assertEqual(self.record()['outcome'],'html_processing_error')
        self.assertEqual(self.w.report_html('alice',self.doc,revision=1),old)
    def test_web_accepts_and_polls_while_openai_pending_without_second_paid_request(self):
        import threading,time
        from http.client import HTTPConnection
        from urs.web import make_app
        from http.cookies import SimpleCookie
        server=make_app(self.w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        gate=threading.Event();entered=threading.Event();calls=[]
        cookie='';csrf=''
        def http(path,data=None):
            conn=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            conn.request('GET' if data is None else 'POST',path,body=None if data is None else json.dumps(data),headers={'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':csrf})
            r=conn.getresponse();status=r.status;headers=r.getheader('Set-Cookie');body=json.loads(r.read());conn.close();return status,body,headers
        def pending(req,**kwargs):
            calls.append((json.loads(req.data),kwargs));entered.set();gate.wait(5);return good(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'))
        try:
            status,login,header=http('/api/login',{'username':'alice','password':'fixture-password-123'})
            cookie=header.split(';')[0];_,me,_=http('/api/me');csrf=me['csrf']
            self.assertEqual(http('/api/settings/report-timeout',{'timeout_seconds':900})[0],200)
            with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',side_effect=pending):
                path=f'/api/documents/{self.doc}'
                self.assertEqual(http(path+'/cost-preview',{'stage':'report'})[0],200)
                start=__import__('time').monotonic();status,_,_=http(path+'/run',{'stage':'report','background':True})
                self.assertEqual(status,202);self.assertLess(time.monotonic()-start,2);self.assertTrue(entered.wait(2))
                self.assertEqual(http(path+'/report-task')[1]['state'],'running')
                self.assertEqual(http('/api/me')[0],200)
                self.assertEqual(http(path+'/run',{'stage':'report','background':True})[0],202)
                gate.set();deadline=time.monotonic()+5
                while http(path+'/report-task')[1]['state']=='running' and time.monotonic()<deadline:time.sleep(.05)
                self.assertEqual(http(path+'/report-task')[1]['state'],'finished')
                self.assertEqual(len(calls),1);self.assertEqual(calls[0][0]['max_output_tokens'],16000);self.assertIsNone(calls[0][1]['timeout'])
                self.assertEqual(http(path+'/detail')[1]['reports']['state'],'current')
        finally:gate.set();server.shutdown();server.server_close();thread.join()
    def test_timeout_validation_owner_isolation_and_existing_output_unchanged(self):
        from urs.workspace import AccessDenied
        self.w.add_user('bob','fixture-password-456')
        for value in (0,9,3601,True,'900',90.5):
            with self.assertRaises(ValueError):self.w.report_timeout('alice',value)
        with self.assertRaises(AccessDenied):self.w.report_timeout('missing',900)
        self.w.report_timeout('alice',900)
        with patch.dict(os.environ,ENV,clear=True):
            self.assertIsNone(self.w.report_timeout('bob')['timeout_seconds'])
        self.assertEqual(self.w.ai_settings('alice')['max_output_tokens'],16000)
        self.assertEqual(self.w.report_settings('alice')['prompt'],PROMPT)
    def test_verification_and_analysis_use_unlimited_wait(self):
        from urs.ai import OpenAI
        self.w.report_timeout('alice',900)
        for task in ('independent_verify','technical_analysis'):
            with self.subTest(task=task),patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=Reply({'status':'completed','output':[{'content':[{'type':'output_text','text':'{}'}]}]})) as network:
                OpenAI(self.w.workflow,self.doc).review_pdf(task,b'%PDF','source.pdf','<html>same</html>')
            self.assertIsNone(network.call_args.kwargs['timeout'])
        self.assertEqual(diagnostics(self.w.workflow,self.doc),[])

    def test_connection_lost_after_headers_is_not_json_or_before_response_error(self):
        import http.client
        class Partial:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):raise http.client.IncompleteRead(b'PRIVATE BODY',500)
        self.run_report(response=Partial())
        self.assertEqual(self.record()['outcome'],'response_read_error')
        self.assertEqual(self.record()['http_status'],200)
        self.assertIsNone(self.record()['response_status'])
        self.assertNotIn('PRIVATE',json.dumps(self.record()))

import base64
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.ai import OpenAI
from urs.images import bind_images,crop_images
from urs.workspace import Workspace,AccessDenied
from urs.workflow import Blocked
from urs.web import make_app

SETTINGS={'URS_OPENAI_API_KEY':'synthetic-only','URS_OPENAI_MODEL':'fixture-terra',
 'URS_AI_BUDGET_USD':'50','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'2'}

class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.sqlite';self.w=Workspace(self.path)
        self.w.add_user('alice','fixture-password-123');self.w.add_user('bob','fixture-password-456')
        self.project=self.w.create_project('alice','synthetic-only')
        self.pdf=visual_pdf();self.doc=self.w.upload('alice',self.project,'source.pdf',self.pdf)
        self.provider=ReportAI();self.w.processing.provider=self.provider
        self.w.save_report_settings('alice',PROMPT)

    def generate(self):
        state=self.w.run('alice',self.doc,'report')
        self.assertTrue(next(s['passed'] for s in state['stages'] if s['id']=='report'))
        return state

    def test_only_pdf_verbatim_saved_prompt_and_image_address_guide_sent(self):
        self.generate()
        task,pdf,name,prompt,guide=self.provider.calls[0]
        self.assertEqual(pdf,self.pdf);self.assertEqual(name,'source.pdf');self.assertEqual(prompt,PROMPT)
        self.assertNotIn('DO NOT EXTRACT',guide)
        self.assertNotIn('translate',guide.lower());self.assertNotIn('font',guide.lower())
        for uri in ['urs-image:1:1','urs-image:1:2']:self.assertIn(uri,guide)
        with self.w.workflow.connect() as db:
            kinds={r[0] for r in db.execute('SELECT kind FROM artifacts')}
        self.assertNotIn('extraction',kinds);self.assertNotIn('translation',kinds)
        self.assertEqual(len(self.provider.calls),1)

    def test_transport_exact_pdf_prompt_no_system_terminology_template_or_images(self):
        result={'status':'completed','output':[{'content':[{'type':'output_text','text':RAW}]}]}
        self.w.processing.provider=None
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(result).encode())) as transport:
            self.generate()
        payload=json.loads(transport.call_args.args[0].data)
        self.assertEqual(set(payload),{'model','input','max_output_tokens','store'})
        self.assertEqual(payload['model'],SETTINGS['URS_OPENAI_MODEL'])
        content=payload['input'][0]['content']
        self.assertEqual([c['type'] for c in content],['input_file','input_text','input_text','input_text'])
        self.assertEqual(base64.b64decode(content[0]['file_data'].split(',')[1]),self.pdf)
        self.assertEqual(content[1]['text'],PROMPT)
        self.assertEqual(content[2]['text'],self.w.artifact('alice',self.doc,'report-metadata')['image_guide'])
        self.assertEqual(self.w.report_html('alice',self.doc,True),RAW.encode())

    def test_final_diff_is_only_two_src_values_with_inverted_placement(self):
        self.generate();assets=self.w.artifact('alice',self.doc,'report-images')
        expected=RAW.replace('src = "urs-image:1:2"','src = "'+assets[1]['data_url']+'"').replace("src='urs-image:1:1'","src='"+assets[0]['data_url']+"'")
        self.assertEqual(self.w.report_html('alice',self.doc),expected.encode())
        self.assertEqual(self.w.report_html('alice',self.doc,True),RAW.encode())
        comparison=self.w.artifact('alice',self.doc,'image-bindings')
        self.assertEqual([c['uri'] for c in comparison['replacements']],['urs-image:1:2','urs-image:1:1'])
        self.assertEqual(comparison['unresolved'][0]['uri'],'urs-image:9:8')
        # Reverse using source offsets: every non-address span is identical.
        pos=0;cursor=0;final=expected
        mapping={a['uri']:a['data_url'] for a in assets}
        for change in comparison['replacements']:
            unchanged=RAW[pos:change['start']]
            self.assertEqual(final[cursor:cursor+len(unchanged)],unchanged)
            cursor+=len(unchanged)+len(mapping[change['uri']]);pos=change['end']
        self.assertEqual(final[cursor:],RAW[pos:])

    def test_missing_slot_not_replaced_with_another_picture(self):
        self.generate();final=self.w.report_html('alice',self.doc).decode()
        self.assertIn('src=urs-image:9:8',final)
        self.assertEqual(final.count('data:image/png;base64,'),2)
        self.w.run('alice',self.doc,'verify')
        status=self.w.status('alice',self.doc)
        self.assertEqual(next(r['status'] for r in status['results'] if r['stage']=='verify'),'NEEDS_REVIEW')

    def test_settings_are_owner_scoped_and_append_only_no_regeneration(self):
        self.generate();before=self.w.report_html('alice',self.doc)
        self.w.save_report_settings('alice','\nnew prompt\n')
        self.assertEqual(self.w.report_settings('bob'),{'prompt':'','version':0})
        self.assertEqual(self.w.report_settings('alice')['prompt'],'\nnew prompt\n')
        self.assertEqual(self.w.report_html('alice',self.doc),before)
        self.assertEqual(len(self.provider.calls),1)
        with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM report_settings').fetchone()[0],2)

    def test_separate_verification_analysis_do_not_mutate_either_html(self):
        self.provider.raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1')
        self.generate();raw=self.w.report_html('alice',self.doc,True);final=self.w.report_html('alice',self.doc)
        for stage in ['verify','analyze']:self.w.run('alice',self.doc,stage)
        self.assertEqual(self.w.report_html('alice',self.doc,True),raw)
        self.assertEqual(self.w.report_html('alice',self.doc),final)
        self.assertEqual([c[0] for c in self.provider.calls],['report','independent_verify','technical_analysis'])
        for c in self.provider.calls[1:]:self.assertEqual(c[1],self.pdf);self.assertEqual(c[3],raw.decode())
        with self.assertRaises(Blocked):self.w.approve_document('alice',self.doc,1,'review',['report.html'])

    def test_legacy_db_initialization_preserves_all_original_rows_and_files(self):
        with self.w.workflow.connect() as db:
            db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(self.doc,1,'extraction',b'{"historic":"kept"}'))
            db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(self.doc,1,'translation.pdf',b'legacy-pdf'))
            db.execute('INSERT INTO approvals VALUES(?,?,?)',(self.doc,1,'alice'))
            db.execute('INSERT INTO definitions VALUES(?,?,?)',('extract',100,'[]'))
            tables=['documents','jobs','artifacts','results','events','approvals','definitions']
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
        reopened=Workspace(self.path)
        with reopened.workflow.connect() as db:
            after={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
        self.assertEqual(before,after)
        state=reopened.status('alice',self.doc)
        self.assertNotIn('extract',[s['id'] for s in state['stages']]);self.assertFalse(state['approved'])
        self.assertEqual(reopened.export('alice',self.doc,'translation.pdf'),b'legacy-pdf')

    def test_explicit_regeneration_creates_revision_without_overwriting_old_html(self):
        self.generate();old=self.w.report_html('alice',self.doc,True)
        self.provider.raw='<!doctype html><html><body>New model output</body></html>'
        state=self.generate();self.assertEqual(state['revision'],2)
        self.assertEqual(self.w.report_html('alice',self.doc,True,1),old)
        self.assertEqual(self.w.report_html('alice',self.doc,True,2),self.provider.raw.encode())

    def test_legacy_text_is_never_used_to_generate_a_report(self):
        marker='LEGACY TEXT MUST NEVER LEAVE'
        self.w.processing.put(self.doc,1,'extraction',{'pages':[{'text':marker}]})
        self.w.processing.put(self.doc,1,'translation',{'block':marker})
        self.generate()
        self.assertNotIn(marker,str(self.provider.calls))
        self.assertEqual(self.w.processing.get(self.doc,'translation',1),{'block':marker})

    def test_corrupt_html_not_displayed_as_verified(self):
        self.generate()
        with self.w.workflow.connect() as db:
            db.execute("UPDATE artifacts SET payload=? WHERE document=? AND kind='report.html'",(b'<html>changed</html>',self.doc))
        with self.assertRaises(Blocked):self.w.report_html('alice',self.doc)

    def test_duplicate_placeholders_and_comments_css_scripts_are_not_rewritten(self):
        assets=crop_images(self.pdf)
        raw='<html><style>p:after{content:"urs-image:1:1"}</style><!-- <img src="urs-image:1:1"> --><img src="urs-image:1:1"/><img SRC=urs-image:1:1><script>"<img src=urs-image:1:1>"</script></html>'
        final,report=bind_images(raw,assets)
        self.assertEqual(len(report['replacements']),2)
        expected=raw.replace('<img src="urs-image:1:1"/>','<img src="'+assets[0]['data_url']+'"/>').replace('<img SRC=urs-image:1:1>','<img SRC='+assets[0]['data_url']+'>')
        self.assertEqual(final,expected)

    def test_live_ui_and_removed_routes_and_html_sandbox(self):
        self.generate()
        server=make_app(self.w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        csrf=''
        def request(path,body=None):
            req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
            return opener.open(req,timeout=10)
        with request('/api/login',{'username':'alice','password':'fixture-password-123'}) as r:csrf=json.load(r)['csrf']
        for path in ['/','/app.js']:
            with request(path) as r:
                text=r.read().decode();self.assertNotIn('추출',text);self.assertNotIn('extraction',text)
        for action,body in [('review-extraction',{'revision':1}),('run',{'stage':'extract'}),('run',{'stage':'translate'}),('edit-translation',{})]:
            with self.assertRaises(urllib.error.HTTPError) as error:request(f'/api/documents/{self.doc}/{action}',body)
            self.assertEqual(error.exception.code,404)
        with request(f'/api/documents/{self.doc}/detail') as r:
            detail=json.load(r);self.assertNotIn('extraction',detail);self.assertNotIn('translation',detail)
        with request(f'/api/documents/{self.doc}/report.html') as r:
            self.assertEqual(r.read(),self.w.report_html('alice',self.doc));self.assertIn('sandbox allow-scripts allow-modals;',r.headers['Content-Security-Policy']);self.assertNotIn('allow-same-origin',r.headers['Content-Security-Policy']);self.assertIn('worker-src blob:',r.headers['Content-Security-Policy']);self.assertIn("style-src 'unsafe-inline'",r.headers['Content-Security-Policy'])
        with request('/api/settings/report') as r:self.assertEqual(json.load(r)['prompt'],PROMPT)
        with self.assertRaises(AccessDenied):self.w.report_html('bob',self.doc)

if __name__=='__main__':unittest.main()

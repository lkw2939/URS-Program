import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from urs.ai import AIBlocked, AIError, OpenAI
from urs.evaluation import record, require
from urs.workspace import Workspace
from urs.workflow import Blocked

SETTINGS={'URS_OPENAI_API_KEY':'synthetic-test-key-not-real','URS_OPENAI_MODEL':'fixture-model-2026-01-01',
          'URS_AI_BUDGET_USD':'0.5','URS_AI_INPUT_USD_PER_MILLION':'2','URS_AI_OUTPUT_USD_PER_MILLION':'8'}


def corpus(fail=0,critical=0):
    return {'reviewer':'synthetic-reviewer-not-an-expert-evaluation','samples':[
        {'id':str(i),'language':'en' if i%2 else 'id','source':f'fixture source {i}',
         'expected_meaning':f'정답 {i}','observed_translation':f'시험 출력 {i}',
         'verdict':'FAIL' if i<fail else 'PASS','critical_error':i<critical,'evidence':'합성 게이트 시험'} for i in range(100)]}


class AIAndEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('urs.costing.count_input_tokens',return_value=12000))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=Workspace(Path(self.tmp.name)/'state.sqlite')
        self.ai=OpenAI(self.w.workflow,'synthetic-document')

    def test_response_transport_contract_and_usage_storage(self):
        response={'status':'completed','usage':{'input_tokens':12,'output_tokens':6},
                  'output':[{'content':[{'type':'output_text','text':'<html><body>fixture</body></html>'}]}]}
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as network:
            self.assertEqual(self.ai.report_html(b'%PDF-fixture','source.pdf','saved prompt','image map'),'<html><body>fixture</body></html>')
            request=network.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
            payload=json.loads(request.data)
            self.assertFalse(payload['store'])
            self.assertEqual(payload['max_output_tokens'],5000)
            self.assertNotIn('text',payload)
            self.assertNotIn('instructions',payload)
            self.assertNotIn('reasoning',payload)
        with self.w.workflow.connect() as db:
            row=dict(db.execute('SELECT * FROM ai_usage').fetchone())
        self.assertEqual(row['state'],'completed')
        self.assertEqual(json.loads(row['usage'])['input_tokens'],12)
        self.assertNotIn(SETTINGS['URS_OPENAI_API_KEY'],str(row))

    def test_effort_is_sent_for_reports_and_reviews_without_changing_prompt(self):
        for effort in ['none','minimal','low','medium','high','xhigh']:
            for task in ['report','independent_verify','technical_analysis']:
                raw='<html><body>fixture</body></html>' if task=='report' else '{}'
                response={'status':'completed','output':[{'content':[{'type':'output_text','text':raw}]}]}
                with self.subTest(effort=effort,task=task),patch.dict(os.environ,{**SETTINGS,'URS_AI_BUDGET_USD':'50','URS_OPENAI_REASONING_EFFORT':effort},clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as network:
                    if task=='report':self.ai.report_html(b'%PDF-fixture','source.pdf','saved prompt unchanged','image map')
                    else:self.ai.review_pdf(task,b'%PDF-fixture','source.pdf','<html>saved</html>')
                    payload=json.loads(network.call_args.args[0].data)
                    self.assertEqual(payload['reasoning'],{'effort':effort})
                    self.assertEqual(payload['model'],SETTINGS['URS_OPENAI_MODEL'])
                    if task=='report':self.assertEqual(payload['input'][0]['content'][1]['text'],'saved prompt unchanged')

    def test_invalid_effort_blocks_before_network_and_budget_reservation(self):
        with patch.dict(os.environ,{**SETTINGS,'URS_OPENAI_REASONING_EFFORT':'invalid-value'},clear=True),patch('urllib.request.urlopen') as network:
            with self.assertRaises(AIBlocked):self.ai.report_html(b'%PDF-fixture','source.pdf','prompt','guide')
            network.assert_not_called()
        with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0],0)

    def test_budget_and_invalid_prices_block_before_network(self):
        for values in [{'URS_AI_BUDGET_USD':'0.000001'},{'URS_AI_INPUT_USD_PER_MILLION':'NaN'}, {'URS_AI_OUTPUT_USD_PER_MILLION':'-1'}]:
            with self.subTest(values=values),patch.dict(os.environ,{**SETTINGS,**values},clear=True),patch('urllib.request.urlopen') as network:
                with self.assertRaises(AIBlocked):self.ai.report_html(b'%PDF-fixture','source.pdf','saved prompt','image map')
                network.assert_not_called()

    def test_failed_call_is_reserved_and_no_secret_error_leaks(self):
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',side_effect=RuntimeError('synthetic-test-key-not-real upstream details')):
            with self.assertRaises(AIError) as error:self.ai.report_html(b'%PDF-fixture','source.pdf','saved prompt','image map')
        self.assertNotIn(SETTINGS['URS_OPENAI_API_KEY'],str(error.exception))
        with self.w.workflow.connect() as db:
            row=db.execute('SELECT * FROM ai_usage').fetchone()
        self.assertEqual(row['state'],'failed');self.assertGreater(row['reserved'],0)

    def test_noncompleted_ai_response_never_passes(self):
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"status":"incomplete"}')):
            with self.assertRaises(AIError):self.ai.report_html(b'%PDF-fixture','source.pdf','saved prompt','image map')

    def test_qualification_threshold_critical_errors_and_model_binding(self):
        with self.assertRaises(Blocked):require(self.w.workflow,'fixture')
        self.assertFalse(record(self.w.workflow,'fixture',corpus(fail=2))['passed'])
        with self.assertRaises(Blocked):require(self.w.workflow,'fixture')
        self.assertFalse(record(self.w.workflow,'fixture',corpus(critical=1))['passed'])
        with self.assertRaises(Blocked):require(self.w.workflow,'fixture')
        self.assertTrue(record(self.w.workflow,'fixture',corpus(fail=1))['passed'])
        self.assertEqual(require(self.w.workflow,'fixture')['correct'],99)
        with self.assertRaises(Blocked):require(self.w.workflow,'different-model')
        with patch('urs.evaluation.fingerprint',return_value='changed-code'):
            with self.assertRaises(Blocked):require(self.w.workflow,'fixture')

    def test_duplicate_and_missing_evaluation_evidence_rejected(self):
        report=corpus();report['samples'][1]['id']=report['samples'][0]['id']
        with self.assertRaises(ValueError):record(self.w.workflow,'fixture',report)
        report=corpus();report['samples'][0]['evidence']=''
        with self.assertRaises(ValueError):record(self.w.workflow,'fixture',report)
        report=corpus();report['samples']=report['samples'][:99]
        with self.assertRaises(ValueError):record(self.w.workflow,'fixture',report)

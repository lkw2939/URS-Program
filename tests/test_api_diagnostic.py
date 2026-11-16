"""Diagnostic acceptance with explicit mock transport; no live paid requests."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,visual_pdf
from scripts.check_api_report import run
from urs.workspace import Workspace

SETTINGS={'URS_OPENAI_API_KEY':'fixture-only-not-a-real-key','URS_OPENAI_MODEL':'fixture-terra',
 'URS_AI_BUDGET_USD':'50','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'2'}
class Response(io.BytesIO):
    status=200
    headers={'x-request-id':'fixture-request'}

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.w=Workspace(self.root/'.runtime/workspace.sqlite')
        self.w.add_user('fixture','fixture-password-123')
        project=self.w.create_project('fixture','fixture')
        self.doc=self.w.upload('fixture',project,'fixture.pdf',visual_pdf())
    def test_missing_saved_prompt_blocks_live_call_and_does_not_invent_prompt(self):
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen') as network:
            result=run(self.root,live=True)
        network.assert_not_called();self.assertFalse(result['prompt_saved'])
        self.assertIn('prompt missing',result['blocked'])
    def test_inspect_reports_model_and_unset_effort_without_any_network(self):
        self.w.save_report_settings('fixture',PROMPT)
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen') as network:
            result=run(self.root)
        network.assert_not_called()
        self.assertEqual(result['requested_model'],'fixture-terra');self.assertIsNone(result['requested_effort'])
        self.assertTrue(result['prompt_saved']);self.assertEqual(result['prompt_version'],1)
        self.assertNotIn(PROMPT,json.dumps(result));self.assertNotIn(SETTINGS['URS_OPENAI_API_KEY'],json.dumps(result))
    def test_completed_response_yields_independent_image_only_comparison_and_preserves_reports(self):
        self.w.save_report_settings('fixture',PROMPT)
        self.w.processing.put(self.doc,1,'translation.pdf',b'old report must stay')
        evidence=self.w.verification_record('fixture',self.doc)['record_sha256']
        body={'id':'fixture-response','model':'fixture-model-resolved','status':'completed',
              'reasoning':{'effort':'medium'},'usage':{'input_tokens':10,'output_tokens':20},
              'output':[{'content':[{'type':'output_text','text':RAW}]}]}
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',return_value=Response(json.dumps(body).encode())) as network:
            result=run(self.root,live=True)
        network.assert_called_once();self.assertTrue(result['api_call_verified']);self.assertTrue(result['html_image_only_verified'])
        self.assertTrue(result['existing_reports_and_stages_unchanged']);self.assertEqual(result['images_inserted'],2)
        self.assertEqual(result['live_request']['returned_effort'],'medium')
        self.assertIsNone(result['live_request']['requested_effort'])
        self.assertTrue(result['live_request']['sent_original_pdf']);self.assertTrue(result['live_request']['sent_verbatim_saved_prompt'])
        self.assertEqual(self.w.verification_record('fixture',self.doc)['record_sha256'],evidence)
        with self.w.workflow.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM ai_usage').fetchone()[0],'completed')
        raw=(self.root/result['diagnostic_files']/'report.raw.html').read_bytes();self.assertEqual(raw,RAW.encode())
    def test_401_is_reported_as_failure_with_safe_error_code(self):
        self.w.save_report_settings('fixture',PROMPT)
        failure=urllib.error.HTTPError('https://api.openai.com/v1/responses',401,'unauthorized',{},io.BytesIO(b'{"error":{"code":"invalid_api_key","type":"invalid_request_error"}}'))
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',side_effect=failure):
            result=run(self.root,live=True)
        self.assertFalse(result['api_call_verified']);self.assertFalse(result['html_image_only_verified'])
        self.assertEqual(result['live_request']['http_status'],401)
        self.assertEqual(result['live_request']['provider_error_code'],'invalid_api_key')
        self.assertTrue(result['existing_reports_and_stages_unchanged'])

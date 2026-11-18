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
from scripts.check_api_report import run, save_prompt_file
from urs.workspace import Workspace

SETTINGS={'URS_OPENAI_API_KEY':'fixture-only-not-a-real-key','URS_OPENAI_MODEL':'fixture-terra',
 'URS_AI_BUDGET_USD':'50','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'2'}
class Response(io.BytesIO):
    status=200
    headers={'x-request-id':'fixture-request'}

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('urs.costing.count_input_tokens',return_value=12000))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.w=Workspace(self.root/'.runtime/workspace.sqlite')
        self.w.add_user('fixture','fixture-password-123')
        project=self.w.create_project('fixture','fixture')
        self.doc=self.w.upload('fixture',project,'fixture.pdf',visual_pdf())
    def test_explicit_prompt_file_is_saved_verbatim_and_idempotently(self):
        file=self.root/'user-prompt.txt';file.write_text(PROMPT)
        old=self.w.verification_record('fixture',self.doc)['record_sha256']
        first=save_prompt_file(self.root,file,self.doc)
        self.assertTrue(first['changed']);self.assertEqual(first['version'],1)
        self.assertEqual(self.w.report_settings('fixture')['prompt'],PROMPT)
        second=save_prompt_file(self.root,file,self.doc)
        self.assertFalse(second['changed']);self.assertEqual(second['version'],1)
        self.assertEqual(self.w.verification_record('fixture',self.doc)['record_sha256'],old)

    def test_prompt_save_does_not_create_a_database_or_invent_a_document(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);file=root/'prompt.txt';file.write_text(PROMPT)
            with self.assertRaises(ValueError):save_prompt_file(root,file)
            self.assertFalse((root/'.runtime/workspace.sqlite').exists())

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
    def test_diagnostic_uses_saved_web_model_effort_limit_over_environment(self):
        self.w.save_report_settings('fixture',PROMPT)
        self.w.save_ai_settings('fixture',{'model':'web-model','effort':'high','max_output_tokens':32000})
        with patch.dict(os.environ,{**SETTINGS,'URS_OPENAI_MAX_OUTPUT_TOKENS':'invalid-old-default'},clear=True),patch('urllib.request.urlopen') as network:
            result=run(self.root)
        network.assert_not_called()
        self.assertEqual(result['requested_model'],'web-model')
        self.assertEqual(result['requested_effort'],'high')
        self.assertEqual(result['requested_max_output_tokens'],32000)
        self.assertEqual(result['ai_settings_source'],'web')
        self.assertNotIn('blocked',result)

    def test_configured_effort_is_visible_without_calling_api(self):
        self.w.save_report_settings('fixture',PROMPT)
        with patch.dict(os.environ,{**SETTINGS,'URS_OPENAI_REASONING_EFFORT':'xhigh'},clear=True),patch('urllib.request.urlopen') as network:
            result=run(self.root)
        network.assert_not_called();self.assertEqual(result['requested_effort'],'xhigh')

    def test_completed_response_yields_independent_image_only_comparison_and_preserves_reports(self):
        self.w.save_report_settings('fixture',PROMPT)
        self.w.processing.put(self.doc,1,'translation.pdf',b'old report must stay')
        previous_costs=self.w.verification_record('fixture',self.doc)['record']['ai_cost_history']
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
        after=self.w.verification_record('fixture',self.doc)
        self.assertEqual(len(after['record']['api_diagnostics']),1)
        after['record']['api_diagnostics']=[]
        self.assertEqual(len(after['record']['ai_cost_history']['calls']),1)
        self.assertEqual(after['record']['ai_cost_history']['calls'][0]['settlement_state'],'settled')
        after['record']['ai_cost_history']=previous_costs
        from urs.audit import envelope
        self.assertEqual(envelope(after['record'])['record_sha256'],evidence)
        with self.w.workflow.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM ai_usage').fetchone()[0],'completed')
        raw=(self.root/result['diagnostic_files']/'report.raw.html').read_bytes();self.assertEqual(raw,RAW.encode())
    def test_no_image_slots_is_reported_as_binding_not_exercised(self):
        self.w.save_report_settings('fixture',PROMPT)
        body={'id':'fixture-no-slots','model':'fixture-terra','status':'completed',
              'output':[{'content':[{'type':'output_text','text':'<!DOCTYPE html><html><body><input type="file"></body></html>'}]}]}
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',return_value=Response(json.dumps(body).encode())):
            result=run(self.root,live=True)
        self.assertTrue(result['api_call_verified']);self.assertTrue(result['html_image_only_verified'])
        self.assertFalse(result['image_binding_exercised']);self.assertEqual(result['images_inserted'],0)

    def test_incomplete_output_distinguishes_successful_http_from_unfinished_html(self):
        self.w.save_report_settings('fixture',PROMPT)
        body={'id':'fixture-incomplete','model':'fixture-terra','status':'incomplete',
              'incomplete_details':{'reason':'max_output_tokens'},'usage':{'output_tokens':5000},'output':[]}
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',return_value=Response(json.dumps(body).encode())):
            result=run(self.root,live=True)
        self.assertTrue(result['api_http_success']);self.assertFalse(result['api_response_completed'])
        self.assertFalse(result['api_call_verified']);self.assertFalse(result['html_image_only_verified'])
        self.assertEqual(result['live_request']['incomplete_reason'],'max_output_tokens')
        self.assertTrue(result['existing_reports_and_stages_unchanged'])

    def test_401_is_reported_as_failure_with_safe_error_code(self):
        self.w.save_report_settings('fixture',PROMPT)
        failure=urllib.error.HTTPError('https://api.openai.com/v1/responses',401,'unauthorized',{},io.BytesIO(b'{"error":{"code":"invalid_api_key","type":"invalid_request_error"}}'))
        with patch.dict(os.environ,SETTINGS,clear=True),patch('urllib.request.urlopen',side_effect=failure):
            result=run(self.root,live=True)
        self.assertFalse(result['api_call_verified']);self.assertFalse(result['html_image_only_verified'])
        self.assertEqual(result['live_request']['http_status'],401)
        self.assertEqual(result['live_request']['provider_error_code'],'invalid_api_key')
        self.assertTrue(result['existing_reports_and_stages_unchanged'])

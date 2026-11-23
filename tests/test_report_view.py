"""Employee button identity and verification conditions from saved history only."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from report_view_fixtures import seed
from urs.workspace import Workspace
from urs.targets import overview
from urs.report_view import context,picture_facts
class ReportViewTests(unittest.TestCase):
 def setUp(self):
  self.enterContext(patch('urllib.request.urlopen',side_effect=AssertionError('API forbidden')));self.tmp=self.enterContext(tempfile.TemporaryDirectory());self.w=Workspace(Path(self.tmp)/'fixture.sqlite');self.w.add_user('viewer','fixture-password-123');self.doc,_,self.raw,self.final,self.target=seed(self.w)
 def view(self):return context(self.w,'viewer',self.doc,self.w.report_availability('viewer',self.doc)['selected'],overview(self.w,'viewer',self.doc,self.target))
 def test_same_employee_file_identity_and_legacy_hidden_structure(self):
  info=self.view();self.assertEqual(info['revision'],1);self.assertEqual(info['filename'],'report.html');self.assertIn('/report.html?revision=1',info['report_url']);self.assertIn('/report.raw.html?revision=1',info['raw_url']);self.assertNotEqual(self.raw,self.final)
  p=info['picture_facts'];self.assertEqual((p['image_count'],p['embedded_images'],p['waiting_for_ready']),(3,3,3));self.assertFalse(p['browser_visibility_verified']);self.assertEqual(p['pdf_selection_controls'],1)
 def test_can_run_is_not_pass_and_customer_has_no_recording_ui(self):
  info=self.view()['verification'];self.assertTrue(info['can_execute']);self.assertEqual(info['saved_result_status'],'NEEDS_REVIEW');self.assertFalse(info['customer_answer_recording_available']);self.assertEqual(info['customer_handoff_count'],1);self.assertEqual({i['kind'] for i in info['findings']},{'error','program'})
 def test_failed_latest_attempt_does_not_relabel_previous_findings(self):
  with self.w.workflow.connect() as db:db.execute('INSERT INTO target_reviews(target,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?)',(self.target,'verify','failed','FAIL',None,json.dumps({'reason':'mock network failure'}),'2026-11-19T01:00:00+00:00'))
  info=self.view()['verification'];self.assertTrue(info['previous_attempt_result']);self.assertEqual(info['latest_attempt_state'],'failed');self.assertEqual(info['saved_result_status'],'NEEDS_REVIEW');self.assertEqual(info['latest_attempt_reason'],'mock network failure')
 def test_reading_never_changes_saved_report_or_verification(self):
  with self.w.workflow.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','target_reviews','ai_usage','documents')}
  self.view();self.view()
  with self.w.workflow.connect() as db:self.assertEqual(before,{t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before})
 def test_image_absence_unresolved_and_visible_data_are_separate(self):
  self.assertEqual(picture_facts('<img src="urs-image:1:2">')['unresolved_slots'],1);self.assertEqual(picture_facts('<p>body</p>')['embedded_images'],0);self.assertFalse(picture_facts('<img src="data:image/png;base64,AAAA">')['legacy_hidden_rule']);self.assertTrue(picture_facts("<script>document.querySelectorAll('img[src^=\"urs-image:\"]')</script><img src='data:image/png;base64,AAAA'>")['legacy_selector_mismatch'])

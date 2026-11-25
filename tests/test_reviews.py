"""Append-only review execution, exact inputs, readable owner-only results."""
import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
from urs.workspace import Workspace,AccessDenied
from urs.reviews import run,overview,result_html
from urs.workflow import Blocked
class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'fixture.sqlite')
  self.w.add_user('alice','fixture-password-123');self.w.add_user('bob','fixture-password-456');p=self.w.create_project('alice','Review fixture');self.doc=self.w.upload('alice',p,'fixture.pdf',visual_pdf())
  self.w.save_report_settings('alice',PROMPT);self.provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));self.w.processing.provider=self.provider
 def generate(self):self.w.run('alice',self.doc,'report')
 def legacy(self):
  with self.w.workflow.connect() as db:return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','events','approvals','report_settings','documents')}
 def test_missing_preconditions_explained_and_no_provider_call(self):
  info=overview(self.w,'alice',self.doc)
  self.assertFalse(info['verify']['can_run']);self.assertIn('HTML',info['verify']['blocked_reason'])
  with self.assertRaises(Blocked):run(self.w,'alice',self.doc,'verify')
  self.assertEqual(self.provider.calls,[])
 def test_run_both_preserves_legacy_rows_and_uses_exact_current_raw_pdf(self):
  self.generate();self.w.processing.put(self.doc,1,'employee-answers',{'answer':'기존 직원 답변 보존'});self.w.processing.put(self.doc,1,'verification',{'status':'PASS','issues':[]});before=self.legacy();raw=self.w.processing.get(self.doc,'report.raw.html');pdf=self.w.original('alice',self.doc)['original']
  self.assertTrue(overview(self.w,'alice',self.doc)['verify']['can_run']);self.assertFalse(overview(self.w,'alice',self.doc)['analyze']['can_run'])
  run(self.w,'alice',self.doc,'verify');run(self.w,'alice',self.doc,'analyze')
  self.assertEqual(self.legacy(),before)
  for call in self.provider.calls[1:]:self.assertEqual(call[1],pdf);self.assertEqual(call[3],raw.decode())
  for stage in ('verify','analyze'):
   self.assertTrue(overview(self.w,'alice',self.doc)[stage]['available'])
   html=result_html(self.w,'alice',self.doc,stage).decode();self.assertIn('보고서 리비전 1',html);self.assertIn('A4 별도 수정본',html);self.assertNotIn('<pre>',html)
   self.assertTrue(next(s['passed'] for s in self.w.status('alice',self.doc)['stages'] if s['id']==stage))
 def test_retry_appends_and_does_not_overwrite_old_attempt_or_other_results(self):
  self.generate();run(self.w,'alice',self.doc,'verify');run(self.w,'alice',self.doc,'analyze')
  with self.w.workflow.connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM review_attempts ORDER BY id')]
  run(self.w,'alice',self.doc,'verify')
  with self.w.workflow.connect() as db:after=[tuple(r) for r in db.execute('SELECT * FROM review_attempts ORDER BY id')]
  self.assertEqual(after[:len(before)],before);self.assertEqual(len(after),3)
  self.assertFalse(next(s['passed'] for s in self.w.status('alice',self.doc)['stages'] if s['id']=='analyze'))
  self.assertTrue(overview(self.w,'alice',self.doc)['analyze']['available'])
 def test_needs_review_is_viewable_and_blocks_analysis_with_reason(self):
  self.generate()
  with patch.object(self.provider,'review_pdf',return_value={'status':'NEEDS_REVIEW','issues':[{'page':18,'severity':'확인 필요','reason':'수치 원문 확인 필요','before':'A','after':'B'}]}):run(self.w,'alice',self.doc,'verify')
  info=overview(self.w,'alice',self.doc);self.assertTrue(info['verify']['available']);self.assertFalse(info['analyze']['can_run']);self.assertIn('독립검증',info['analyze']['blocked_reason'])
  html=result_html(self.w,'alice',self.doc,'verify').decode();self.assertIn('수치 원문 확인 필요',html);self.assertIn('수정 전',html);self.assertIn('실제 적용된 수정이 아닙니다',html)
 def test_runtime_failure_has_saved_reason_and_previous_result_is_labeled(self):
  from urs.ai import AIError
  self.generate();run(self.w,'alice',self.doc,'verify')
  with patch.object(self.provider,'review_pdf',side_effect=AIError('API 응답 대기시간 초과')):run(self.w,'alice',self.doc,'verify')
  info=overview(self.w,'alice',self.doc)['verify'];self.assertIn('시간 초과',info['failure']);self.assertTrue(info['older_attempt'])
  self.assertIn('같은 리비전의 이전 실행',result_html(self.w,'alice',self.doc,'verify').decode())
 def test_prior_revision_result_never_labeled_current(self):
  self.generate();run(self.w,'alice',self.doc,'verify');self.generate()
  self.assertTrue(overview(self.w,'alice',self.doc)['verify']['previous'])
  self.assertIn('이전 결과 — 최신 결과가 아닙니다',result_html(self.w,'alice',self.doc,'verify').decode())
 def test_owner_isolation_and_xss_escaping(self):
  self.generate()
  with patch.object(self.provider,'review_pdf',return_value={'status':'FAIL','issues':[{'page':1,'reason':'<script>alert(1)</script>'}]}):run(self.w,'alice',self.doc,'verify')
  self.assertNotIn('<script>',result_html(self.w,'alice',self.doc,'verify').decode())
  with self.assertRaises(AccessDenied):result_html(self.w,'bob',self.doc,'verify')
  with self.assertRaises(AccessDenied):run(self.w,'bob',self.doc,'analyze')
 def test_new_fenced_output_is_not_completed_or_reviewable(self):
  self.provider.raw='```html\n'+self.provider.raw+'\n```';self.generate()
  self.assertEqual(self.w.report_availability('alice',self.doc)['state'],'none')
  self.assertFalse(overview(self.w,'alice',self.doc)['verify']['can_run'])
  with self.assertRaises(Blocked):run(self.w,'alice',self.doc,'verify')
  self.assertEqual(len(self.provider.calls),1)

 def test_previous_server_pending_attempt_does_not_leave_button_permanently_disabled(self):
  self.generate()
  with self.w.workflow.connect() as db:db.execute("INSERT INTO review_attempts(document,revision,stage,state,status,payload,evidence,created) VALUES(?,1,'verify','running','UNVERIFIED',NULL,?,'past')",(self.doc,json.dumps({'server_instance':'previous-server'})))
  info=overview(self.w,'alice',self.doc)['verify']
  self.assertFalse(info['running']);self.assertTrue(info['can_run']);self.assertIn('완료 여부',info['failure'])
  run(self.w,'alice',self.doc,'verify')
  with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM review_attempts').fetchone()[0],2)

 def test_finished_legacy_attempt_and_artifact_copies_are_durable(self):
  import sqlite3
  from urs.review_archive import listing,saved
  self.generate();run(self.w,'alice',self.doc,'verify');initial=listing(self.w,'alice',self.doc);self.assertEqual(len(initial),1)
  for statement in ['DELETE FROM review_attempts',"UPDATE review_attempts SET payload='{}'",'INSERT OR REPLACE INTO review_attempts SELECT * FROM review_attempts']:
   with self.assertRaises(sqlite3.IntegrityError):
    with self.w.workflow.connect() as db:db.execute(statement)
  a={'status':'PASS','issues':[]};b={'status':'NEEDS_REVIEW','issues':[{'reason':'별도 모의 결과'}]}
  self.w.processing.put(self.doc,1,'verification',a);self.w.processing.put(self.doc,1,'verification',b)
  reopened=Workspace(self.w.workflow.path);rows=listing(reopened,'alice',self.doc);self.assertEqual(len(rows),3)
  self.assertEqual(saved(reopened,'alice',self.doc,initial[0]['key'])[0]['payload_sha256'],initial[0]['payload_sha256'])
  self.assertEqual({json.loads(saved(reopened,'alice',self.doc,r['key'])[0]['payload'])['status'] for r in rows},{'PASS','NEEDS_REVIEW'})

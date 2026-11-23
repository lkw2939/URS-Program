"""Temporary documents only; no paid calls, including correction preview/apply."""
import hashlib,html,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.workspace import Workspace,AccessDenied
from urs.workflow import Blocked
from urs import corrections
from urs.review_results import load,plan_changes
from urs.ai import AIError

ENV={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'fixture-model','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
BEFORE='고객은 시험을 반드시 수행해야 합니다.'
AFTER='고객의 시험 수행을 권장합니다.'
ISSUES=[{'page':1,'severity':'오류','title_ko':'원문은 권장인데 번역은 의무로 바뀌었습니다','problem_ko':'권장 사항이 의무로 번역됐습니다.','why_ko':'불필요한 계약 의무가 생깁니다.','fix_ko':'권장 표현으로 고치세요.','before':BEFORE,'after':AFTER,'source_en':'The customer should perform the test.'},
 {'page':1,'severity':'확인 필요','reason':'치수 원본 확인 필요','before':'120 mm','after':'125 mm','needs_confirmation':True},
 {'page':1,'severity':'오류','category':'pagination','reason':'쪽수 차이만 있음'},
 {'page':1,'severity':'오류','reason':'제목 표현 확인','before':'모델 제목 & 원문','after':'모델 제목 & 원문 수정'}]
class CorrectionTests(unittest.TestCase):
 def setUp(self):
  self.enterContext(patch.dict(os.environ,ENV,clear=True));self.network=self.enterContext(patch('urllib.request.urlopen',side_effect=AssertionError('Paid API forbidden')))
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'fixture.sqlite');self.w.add_user('alice','fixture-password-123');self.w.add_user('bob','fixture-password-456');project=self.w.create_project('alice','Repair fixture');self.doc=self.w.upload('alice',project,'URS fixture.pdf',visual_pdf());self.w.save_report_settings('alice',PROMPT)
  self.raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</section>','<p>'+BEFORE+'</p></section>');self.provider=ReportAI(self.raw);self.w.processing.provider=self.provider;self.w.run('alice',self.doc,'report')
  with patch.object(self.provider,'report_html',side_effect=AIError('모의 새 생성 실패')):self.w.run('alice',self.doc,'report')
  self.target=f'displayed:{self.doc}:1'
  with self.w.workflow.connect() as db:
   self.attempt=db.execute('INSERT INTO target_reviews(target,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?)',(self.target,'verify','finished','FAIL',json.dumps({'status':'FAIL','issues':ISSUES}),json.dumps({'input_revision':1}),'2026-11-18T00:00:00+00:00')).lastrowid
   db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(self.doc,1,'employee-answers',b'{"kept":"answer"}'))
   db.execute('INSERT INTO approvals VALUES(?,?,?)',(self.doc,1,'alice'))
  self.old=self.w.report_html('alice',self.doc,revision=1)
 def proposed(self,changes=None):
  return corrections.preview(self.w,'alice',self.doc,self.target,self.attempt,changes or [{'issue_id':'0','before':BEFORE,'after':AFTER}])
 def test_result_distinguishes_errors_confirmation_layout_and_unknown_transport(self):
  d=load(self.w,'alice',self.doc,self.target,self.attempt);self.assertEqual((d['error_count'],d['review_count'],d['layout_count']),(2,1,1));self.assertIsNone(d['transport']);self.assertTrue(d['can_edit']);self.assertEqual(d['revision'],1)
 def test_preview_is_read_only_and_only_explicit_apply_creates_new_history(self):
  p=self.proposed();self.assertEqual(self.w.status('alice',self.doc)['revision'],2);self.assertEqual(self.w.report_html('alice',self.doc,revision=1),self.old)
  with self.w.workflow.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','events','approvals','documents','report_settings','ai_usage','target_reviews')}
  new=corrections.apply(self.w,'alice',self.doc,p['plan_id']);self.assertEqual(new['revision'],3);self.assertEqual(self.w.report_availability('alice',self.doc)['selected']['revision'],3)
  final=self.w.report_html('alice',self.doc,revision=3);self.assertEqual(final,self.old.replace(BEFORE.encode(),AFTER.encode()));self.assertEqual(self.w.report_html('alice',self.doc,True,3),self.raw.encode())
  with self.w.workflow.connect() as db:
   for table,rows in before.items():self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM '+table+' LIMIT ?',(len(rows),))],rows,table)
  self.network.assert_not_called()
 def test_confirmations_and_layout_items_cannot_be_applied(self):
  for ident,before,after in [('1','120 mm','125 mm'),('2',BEFORE,AFTER)]:
   with self.assertRaises(Blocked):self.proposed([{'issue_id':ident,'before':before,'after':after}])
 def test_applied_item_is_locked_but_remaining_items_can_continue(self):
  p=self.proposed();corrections.apply(self.w,'alice',self.doc,p['plan_id'])
  self.assertTrue(load(self.w,'alice',self.doc,self.target,self.attempt)['can_edit'])
  with self.assertRaises(Blocked):self.proposed()
  self.assertFalse(load(self.w,'alice',self.doc,self.target,self.attempt)['execution_report']['reviews']['analyze']['can_run'])
 def test_apply_is_idempotent_and_preserves_old_approval(self):
  p=self.proposed();a=corrections.apply(self.w,'alice',self.doc,p['plan_id']);b=corrections.apply(self.w,'alice',self.doc,p['plan_id']);self.assertEqual(a['revision'],b['revision']);self.assertEqual(self.w.status('alice',self.doc)['revision'],3)
  with self.w.workflow.connect() as db:self.assertEqual(db.execute('SELECT revision FROM approvals').fetchone()[0],1)
 def test_wrong_owner_cannot_read_preview_or_apply(self):
  p=self.proposed()
  with self.assertRaises(AccessDenied):load(self.w,'bob',self.doc,self.target,self.attempt)
  with self.assertRaises(AccessDenied):corrections.apply(self.w,'bob',self.doc,p['plan_id'])
 def test_entities_roundtrip_without_adding_markup_or_touching_css_images(self):
  after='모델 제목 & 원문 <수정>';p=self.proposed([{'issue_id':'3','before':'모델 제목 & 원문','after':after}]);corrections.apply(self.w,'alice',self.doc,p['plan_id'])
  final=self.w.report_html('alice',self.doc,revision=3).decode();self.assertEqual(final,self.old.decode().replace('모델 제목 &amp; 원문',html.escape(after,quote=False)))
 def test_attribute_css_and_ambiguous_text_are_not_replaceable(self):
  for text in ["font-family: serif",self.old.decode().split('data:image/png;base64,',1)[1].split('"')[0][:80]]:
   with self.assertRaises(Blocked):self.proposed([{'issue_id':'0','before':text,'after':'변경'}])
  with self.assertRaises(Blocked):plan_changes('<html><body><section data-urs-page="1"><p>반복</p><p>반복</p></section></body></html>',[{'id':'0','page':1,'can_propose':True}],[{'issue_id':'0','before':'반복','after':'수정'}])
 def test_chain_integrity_and_backup_restore(self):
  p=self.proposed();corrections.apply(self.w,'alice',self.doc,p['plan_id']);self.w.processing.checked_html(self.doc,3)
  from urs.backup import backup_database,restore_database
  path=Path(self.tmp.name);backup_database(self.w.path if hasattr(self.w,'path') else self.w.workflow.path,path/'backup.sqlite');restore_database(path/'backup.sqlite',path/'restored.sqlite');restored=Workspace(path/'restored.sqlite');self.assertEqual(restored.report_html('alice',self.doc,revision=3),self.w.report_html('alice',self.doc,revision=3))
  with self.w.workflow.connect() as db:db.execute("UPDATE artifacts SET payload=? WHERE document=? AND revision=3 AND kind='correction-patch'",(b'{}',self.doc))
  with self.assertRaises(Blocked):self.w.report_html('alice',self.doc,revision=3)
 def test_deletion_requires_explicit_choice_and_preview(self):
  with self.assertRaises(ValueError):self.proposed([{'issue_id':'0','before':BEFORE,'after':''}])
  p=self.proposed([{'issue_id':'0','before':BEFORE,'after':'','delete':True}]);corrections.apply(self.w,'alice',self.doc,p['plan_id']);self.assertNotIn(BEFORE.encode(),self.w.report_html('alice',self.doc,revision=3))

 def test_partial_corrections_do_not_unlock_css_workflow(self):
  from urs.flow import state,enter
  p=self.proposed();new=corrections.apply(self.w,'alice',self.doc,p['plan_id'])
  info=state(self.w,'alice',self.doc);self.assertEqual(info['revision'],new['revision']);self.assertFalse(info['steps'][1]['passed']);self.assertFalse(info['steps'][2]['can_enter']);self.assertIn('아직 적용하지 않은',info['steps'][1]['reason']);self.assertIn('다시 실행할 필요는 없습니다',info['steps'][1]['reason'])
  with self.assertRaises(Blocked):enter(self.w,'alice',self.doc,2,new['revision'])

 def test_multiple_applies_keep_source_review_and_accumulate_remaining_corrections(self):
  from urs.flow import state
  first=corrections.apply(self.w,'alice',self.doc,self.proposed()['plan_id'])
  p=self.proposed([{'issue_id':'3','before':'모델 제목 & 원문','after':'모델 제목 & 원문 수정'}]);self.assertEqual(p['revision'],first['revision'])
  second=corrections.apply(self.w,'alice',self.doc,p['plan_id'])
  self.assertEqual(set(load(self.w,'alice',self.doc,self.target,self.attempt)['applied_issue_ids']),{'0','3'})
  self.assertFalse(state(self.w,'alice',self.doc)['steps'][2]['can_enter'])
  change={'issue_id':'1','page':1,'before':'120 mm','after':'120 mm (원본 확인 필요)','confirmed':True,'basis':'원문 확인이 필요한 상태를 명확하게 표시합니다.'}
  third=corrections.apply(self.w,'alice',self.doc,self.proposed([change])['plan_id'])
  final=self.w.report_html('alice',self.doc,revision=third['revision']).decode();self.assertIn(AFTER,final);self.assertIn('모델 제목 &amp; 원문 수정',final);self.assertIn('120 mm (원본 확인 필요)',final)
  self.assertTrue(state(self.w,'alice',self.doc)['steps'][2]['can_enter']);self.assertEqual(self.w.report_html('alice',self.doc,revision=1),self.old)
  with self.w.workflow.connect() as db:self.assertEqual(json.loads(db.execute('SELECT payload FROM target_reviews WHERE id=?',(self.attempt,)).fetchone()[0])['status'],'FAIL')
 def test_manual_text_edit_needs_basis_and_does_not_clear_unrelated_findings(self):
  from urs.flow import state
  change={'issue_id':'manual:0','page':1,'before':'모델 제목 & 원문','after':'직원이 수정한 제목','confirmed':True,'basis':'원문 제목과 대조하여 작성한 수정입니다.'}
  without={**change,'basis':''}
  with self.assertRaises(Blocked):self.proposed([without])
  revision=corrections.apply(self.w,'alice',self.doc,self.proposed([change])['plan_id'])['revision']
  self.assertIn('직원이 수정한 제목',self.w.report_html('alice',self.doc,revision=revision).decode());self.assertFalse(state(self.w,'alice',self.doc)['steps'][2]['can_enter'])
  self.assertEqual(load(self.w,'alice',self.doc,self.target,self.attempt)['manual_index'],1)
 def test_new_generation_breaks_continuation_with_old_review(self):
  corrections.apply(self.w,'alice',self.doc,self.proposed()['plan_id']);self.w.run('alice',self.doc,'report')
  self.assertFalse(load(self.w,'alice',self.doc,self.target,self.attempt)['can_edit'])
  with self.assertRaises(Blocked):self.proposed([{'issue_id':'3','before':'모델 제목 & 원문','after':'수정'}])

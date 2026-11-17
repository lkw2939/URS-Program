import tempfile,json,sqlite3,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.workspace import Workspace,AccessDenied
from urs.workflow import Blocked
from urs import targets
from urs.usage_audit import preview
class TargetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'db.sqlite');self.w.add_user('alice','fixture-password-123');self.w.add_user('bob','fixture-password-456')
  p=self.w.create_project('alice','target fixture');self.doc=self.w.upload('alice',p,'source.pdf',visual_pdf());self.w.save_report_settings('alice',PROMPT);self.w.processing.provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));self.w.run('alice',self.doc,'report')
  # Preserve r1 and failed current r2, matching SG6 state, without changing old rows.
  with self.w.workflow.connect() as db:
   job=self.w.workflow._job(db,self.doc);content=json.loads(job['content']);content['revision']=2;db.execute('UPDATE jobs SET revision=2,content=? WHERE id=?',(json.dumps(content),self.doc))
  self.html=b'<!doctype html><html><body>A4 exact bytes</body></html>'
 def snapshot(self):
  with self.w.workflow.connect() as db:return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('jobs','artifacts','results','events','approvals','documents','report_settings','ai_usage')}
 def register(self):return targets.register(self.w,'alice',self.doc,1,'report-a4.html',self.html)
 def test_register_preserves_revisions_and_bytes_and_does_not_call_ai(self):
  before=self.snapshot();calls=len(self.w.processing.provider.calls);ident=self.register();self.assertEqual(self.snapshot(),before);self.assertEqual(len(self.w.processing.provider.calls),calls)
  row,_=targets.get(self.w,'alice',self.doc,ident);self.assertEqual(row['payload'],self.html);self.assertEqual(row['parent_revision'],1);self.assertEqual(row['sha256'],hashlib.sha256(self.html).hexdigest())
  self.assertEqual(self.register(),ident)
 def test_immutable_and_owner_permissions(self):
  ident=self.register()
  with self.assertRaises(AccessDenied):targets.get(self.w,'bob',self.doc,ident)
  with self.assertRaises(AccessDenied):targets.register(self.w,'bob',self.doc,1,'x.html',self.html)
  with self.assertRaises(sqlite3.IntegrityError):
   with self.w.workflow.connect() as db:db.execute('DELETE FROM review_targets WHERE id=?',(ident,))
 def test_missing_parent_or_bad_html_not_silently_repaired(self):
  with self.assertRaises(Blocked):targets.register(self.w,'alice',self.doc,2,'x.html',self.html)
  with self.assertRaises(ValueError):targets.register(self.w,'alice',self.doc,1,'x.html',b'<html>cut')
 def test_a4_review_uses_registered_input_not_raw_or_current_r2(self):
  ident=self.register();before=self.snapshot()
  info=targets.overview(self.w,'alice',self.doc,ident);self.assertTrue(info['reviews']['verify']['can_run']);self.assertFalse(info['reviews']['analyze']['can_run'])
  with self.assertRaises(Blocked):targets.run(self.w,'alice',self.doc,ident,'analyze')
  targets.run(self.w,'alice',self.doc,ident,'verify');targets.run(self.w,'alice',self.doc,ident,'analyze')
  for call in self.w.processing.provider.calls[1:]:self.assertEqual(call[3],self.html.decode())
  self.assertEqual(self.snapshot(),before)
  info=targets.overview(self.w,'alice',self.doc,ident)
  html=targets.result_html(self.w,'alice',self.doc,ident,'verify',info['reviews']['verify']['attempt']).decode();self.assertIn('등록 A4 HTML',html);self.assertIn('부모 리비전 1',html)
 def test_existing_terra_verification_does_not_qualify_a4(self):
  ident=self.register()
  self.w.processing.put(self.doc,2,'verification',{'status':'PASS','issues':[]})
  self.assertFalse(targets.overview(self.w,'alice',self.doc,ident)['reviews']['analyze']['can_run'])
 def test_failure_preserves_prior_target_result_and_budget(self):
  from urs.ai import AIBlocked
  ident=self.register();targets.run(self.w,'alice',self.doc,ident,'verify')
  with self.w.workflow.connect() as db:old=[tuple(r) for r in db.execute('SELECT * FROM target_reviews')]
  with patch.object(self.w.processing.provider,'review_pdf',side_effect=AIBlocked('문서 예산 상한')):targets.run(self.w,'alice',self.doc,ident,'verify')
  info=targets.overview(self.w,'alice',self.doc,ident)['reviews']['verify'];self.assertTrue(info['available']);self.assertTrue(info['older_attempt']);self.assertIn('예산',info['failure'])
  with self.w.workflow.connect() as db:self.assertEqual(tuple(db.execute('SELECT * FROM target_reviews ORDER BY id LIMIT 1').fetchone()),old[0])
 def test_settlement_preview_never_refunds_unknown_usage_or_rewrites_ledger(self):
  with self.w.workflow.connect() as db:
   db.execute('INSERT INTO ai_usage(document,task,model,reserved,state,usage) VALUES(?,?,?,?,?,?)',(self.doc,'report_html','model',3.0,'failed',json.dumps({'input_tokens':10000,'output_tokens':16000})))
   db.execute('INSERT INTO ai_usage(document,task,model,reserved,state,usage) VALUES(?,?,?,?,?,?)',(self.doc,'report_html','model',2.0,'failed',None))
  before=self.snapshot()
  with self.w.workflow.connect() as db:r=preview(db,self.doc,1,5)
  self.assertAlmostEqual(r['known_usage_estimate_usd'],.09);self.assertEqual(r['unknown_usage_reservations_kept_usd'],2);self.assertFalse(r['applied']);self.assertEqual(self.snapshot(),before)

 def test_partial_or_pending_usage_is_not_treated_as_refundable(self):
  with self.w.workflow.connect() as db:
   db.execute('INSERT INTO ai_usage(document,task,model,reserved,state,usage) VALUES(?,?,?,?,?,?)',(self.doc,'report_html','model',3.0,'failed',json.dumps({'input_tokens':10000})))
   db.execute('INSERT INTO ai_usage(document,task,model,reserved,state,usage) VALUES(?,?,?,?,?,?)',(self.doc,'report_html','model',2.0,'reserved',json.dumps({'input_tokens':1,'output_tokens':1})))
  with self.w.workflow.connect() as db:r=preview(db,self.doc,1,5)
  self.assertEqual(r['unknown_usage_reservations_kept_usd'],5);self.assertEqual(r['known_usage_estimate_usd'],0);self.assertFalse(any(x['usage_available'] for x in r['calls']))

 def test_budget_block_does_not_prevent_registration_or_send_a_request(self):
  import os
  ident=self.register();calls=len(self.w.processing.provider.calls)
  with patch.dict(os.environ,{'URS_AI_BUDGET_USD':'0.01','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'},clear=True):
   info=targets.overview(self.w,'alice',self.doc,ident)['reviews']['verify']
   self.assertFalse(info['can_run']);self.assertTrue(info['budget_preview']['blocked'])
   with self.assertRaises(Blocked):targets.run(self.w,'alice',self.doc,ident,'verify')
  self.assertEqual(len(self.w.processing.provider.calls),calls)
  self.assertEqual(targets.get(self.w,'alice',self.doc,ident)[0]['payload'],self.html)

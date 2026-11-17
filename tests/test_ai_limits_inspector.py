import importlib.util,json,os,tempfile,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('inspect_limits',ROOT/'scripts/inspect_ai_limits.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class LimitInspectorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.db=self.root/'db.sqlite'
  (self.root/'.env').write_text('URS_AI_BUDGET_USD=10\nURS_AI_INPUT_USD_PER_MILLION=1\nURS_AI_OUTPUT_USD_PER_MILLION=5\nURS_OPENAI_API_KEY=PRIVATE-NEVER-PRINT\n')
  with sqlite3.connect(self.db) as db:
   db.executescript('CREATE TABLE documents(id,original,project);CREATE TABLE projects(id,owner);CREATE TABLE jobs(id,revision);CREATE TABLE artifacts(document,revision,kind,payload);CREATE TABLE ai_settings(owner,version,payload);CREATE TABLE ai_usage(document,state,reserved);')
   db.execute('INSERT INTO projects VALUES(1,"alice")');db.execute('INSERT INTO documents VALUES("doc",?,1)',(b'x'*2000000,));db.execute('INSERT INTO jobs VALUES("doc",2)');db.execute('INSERT INTO artifacts VALUES("doc",1,"report.raw.html",?)',(b'PRIVATE DOCUMENT',));db.execute('INSERT INTO ai_settings VALUES("alice",1,?)',(json.dumps({'max_output_tokens':64000}),))
 def run_audit(self):
  before=self.db.read_bytes();env=(self.root/'.env').read_bytes()
  with patch.dict(os.environ,{},clear=True):result=module.audit(self.root,self.db,'doc',1)
  self.assertEqual(self.db.read_bytes(),before);self.assertEqual((self.root/'.env').read_bytes(),env)
  self.assertNotIn('PRIVATE',json.dumps(result));return result
 def test_budget_only_and_failed_calls_count(self):
  with sqlite3.connect(self.db) as db:db.executemany('INSERT INTO ai_usage VALUES("doc",?,?)',[('failed',3),('completed',3),('reserved',3)])
  r=self.run_audit();self.assertEqual(r['current_revision'],2);self.assertEqual(r['target_revision'],1);self.assertEqual(r['request_count'],3);self.assertFalse(r['request_count_limit_reached']);self.assertTrue(r['budget_limit_for_target']);self.assertEqual(r['max_output_tokens'],64000)
 def test_count_only(self):
  with sqlite3.connect(self.db) as db:db.executemany('INSERT INTO ai_usage VALUES("doc","failed",0.001)',[()]*120)
  r=self.run_audit();self.assertTrue(r['request_count_limit_reached']);self.assertFalse(r['budget_limit_for_target'])
 def test_current_revision_without_html_is_not_switched_automatically(self):
  with patch.dict(os.environ,{},clear=True):r=module.audit(self.root,self.db,'doc')
  self.assertFalse(r['target_raw_html_exists']);self.assertIsNone(r['budget_limit_for_target']);self.assertEqual(r['target_revision'],2)
 def test_instruction_matches_actual_adapter_literals(self):
  for task in ('verify','analyze'):
   text=module.instruction(task);self.assertIn('한국어',text);self.assertIn('Do not edit or rewrite',text)

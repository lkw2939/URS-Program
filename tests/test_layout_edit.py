import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
from urs.workspace import Workspace
from urs import layout_edit
from urs.workflow import Blocked
class LayoutEditTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'t.sqlite');self.w.add_user('a','fixture-password-123');p=self.w.create_project('a','fixture');self.d=self.w.upload('a',p,'source.pdf',visual_pdf());self.w.save_report_settings('a',PROMPT);self.raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1');self.provider=ReportAI(self.raw);self.w.processing.provider=self.provider;self.w.run('a',self.d,'report');self.before=self.w.report_html('a',self.d,revision=1)
 def test_layout_edit_saves_new_report_without_generation_or_overwriting(self):
  self.provider.refine_report_html=lambda *args:args[4].replace('margin: 23px','margin: 25px')
  result=layout_edit.run(self.w,'a',self.d,1,'여백을 다듬으세요.');self.assertEqual(result['revision'],2);self.assertEqual(self.w.report_html('a',self.d,revision=1),self.before);self.assertIn(b'margin: 25px',self.w.report_html('a',self.d,revision=2));self.assertEqual(len(self.provider.calls),1);self.assertEqual(layout_edit.latest(self.w,'a',self.d)['state'],'finished')
 def test_content_change_is_rejected_and_recorded(self):
  self.provider.refine_report_html=lambda *args:args[4].replace('120 mm','125 mm')
  with self.assertRaises(Blocked):layout_edit.run(self.w,'a',self.d,1,'')
  self.assertEqual(self.w.status('a',self.d)['revision'],1);self.assertEqual(self.w.report_html('a',self.d,revision=1),self.before);self.assertEqual(layout_edit.latest(self.w,'a',self.d)['state'],'failed')
 def test_latest_unverified_report_is_editable_without_regeneration(self):
  self.provider.raw=self.raw.replace('width:210mm','width:260mm');self.w.run('a',self.d,'report');parent=self.w.report_html('a',self.d,revision=2);self.assertEqual(self.w.report_availability('a',self.d)['selected']['revision'],1)
  self.provider.refine_report_html=lambda *args:args[4].replace('width:260mm','width:210mm')
  result=layout_edit.run(self.w,'a',self.d,2,'배치만 수정');self.assertEqual(result['revision'],3);self.assertEqual(self.w.report_html('a',self.d,revision=2),parent);self.assertEqual(self.w.report_availability('a',self.d)['selected']['revision'],3);self.assertEqual(len(self.provider.calls),2)
 def test_page_number_uses_caption_size_without_false_body_warning(self):
  from urs.layout_audit import inspect
  html=self.before.decode().replace('</section>','<div class="page-number" style="font-size:12px">1 / 1</div></section>')
  self.assertEqual(inspect(html,1)['status'],'PASS')
 def test_server_restart_records_interrupted_job_without_retry(self):
  layout_edit.schema(self.w)
  with self.w.workflow.connect() as db:db.execute("INSERT INTO layout_edit_attempts(document,parent,state,created) VALUES(?,?,?,?)",(self.d,1,'queued','2026-11-19'))
  layout_edit.recover(self.w);self.assertEqual(layout_edit.latest(self.w,'a',self.d)['state'],'failed');self.assertIn('자동 유료 재시도하지 않았습니다',layout_edit.latest(self.w,'a',self.d)['reason']);self.assertEqual(len(self.provider.calls),1)
 def test_css_only_rejects_structure_or_attribute_changes(self):
  from urs.css_only import unchanged_outside_styles
  self.assertFalse(unchanged_outside_styles(self.raw,self.raw.replace('<h1>','<h1 class="new">')))
  self.assertFalse(unchanged_outside_styles(self.raw,self.raw.replace('src=urs-image:1:1','src="urs-image:1:1"')))
  self.assertFalse(unchanged_outside_styles(self.raw,self.raw+'\n'))
 def test_css_only_allows_existing_style_contents_only(self):
  from urs.css_only import unchanged_outside_styles
  self.assertTrue(unchanged_outside_styles(self.raw,self.raw.replace('margin: 23px','margin: 25px')))
  self.assertFalse(unchanged_outside_styles(self.raw,self.raw.replace('<style>','<style media="screen">')))
 def test_browser_failure_blocks_before_paid_call(self):
  with patch('urs.layout_audit.inspect',return_value={'status':'UNVERIFIED'}):
   with self.assertRaises(Blocked):layout_edit.run(self.w,'a',self.d,1,'')
  self.assertIn('유료 호출',layout_edit.latest(self.w,'a',self.d)['reason'])

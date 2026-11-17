"""Post-image A4 measurement and failure-safe current-report selection, no paid API."""
import tempfile,unittest,json,hashlib
from pathlib import Path
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.workspace import Workspace
from urs.images import bind_images,crop_images
from urs.layout_audit import inspect
from urs.ai import AIError
from urs import targets
class LayoutFlowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'fixture.sqlite');self.w.add_user('alice','fixture-password-123');p=self.w.create_project('alice','Automatic flow fixture');self.doc=self.w.upload('alice',p,'fixture.pdf',visual_pdf());self.w.save_report_settings('alice',PROMPT)
  self.raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1');self.provider=ReportAI(self.raw);self.w.processing.provider=self.provider
 def generate(self):self.w.run('alice',self.doc,'report')
 def final(self,raw=None):return bind_images(raw or self.raw,crop_images(visual_pdf()))[0]
 def test_actual_final_with_images_measures_a4(self):
  self.generate();audit=self.w.processing.get(self.doc,'layout-audit');self.assertEqual(audit['status'],'PASS');self.assertEqual(audit['image_count'],3)
  self.assertAlmostEqual(audit['pages'][0]['width_px'],210*96/25.4,delta=2);self.assertAlmostEqual(audit['pages'][0]['height_px'],297*96/25.4,delta=2)
  self.assertEqual(self.w.report_html('alice',self.doc,True),self.raw.encode());self.assertEqual(self.w.report_html('alice',self.doc),self.final().encode())
 def test_print_rule_alone_is_not_a4_screen(self):
  result=inspect(self.final(self.raw.replace('width:210mm','width:230mm')),1);self.assertEqual(result['status'],'NEEDS_REVIEW');self.assertIn('A4 화면 크기 불일치',result['pages'][0]['issues'])
 def test_hidden_embedded_images_are_rejected(self):
  raw=self.raw.replace('</style>','img{display:none}</style>');result=inspect(self.final(raw),1);self.assertIn('이미지 숨김',result['pages'][0]['issues'])
 def test_overflow_is_reported_not_clipped_or_reflowed(self):
  raw=self.raw.replace('</section>','<p>'+('원문 내용 보존 '*2000)+'</p></section>');result=inspect(self.final(raw),1);self.assertEqual(result['status'],'NEEDS_REVIEW');self.assertIn('페이지 내용 넘침',result['pages'][0]['issues'])
 def test_failed_attempt_keeps_previous_visible_final_as_review_input(self):
  self.generate();old=self.w.report_html('alice',self.doc,revision=1)
  with patch.object(self.provider,'report_html',side_effect=AIError('출력 한도 실패')):self.generate()
  current=self.w.report_availability('alice',self.doc)['selected'];self.assertEqual(current['revision'],1);self.assertEqual(self.w.status('alice',self.doc)['revision'],2)
  target=f'displayed:{self.doc}:1';targets.run(self.w,'alice',self.doc,target,'verify')
  self.assertEqual(self.provider.calls[-1][3],old.decode());self.assertEqual(self.w.report_html('alice',self.doc,revision=1),old)
 def test_bad_new_layout_does_not_displace_old_report(self):
  self.generate();old=self.w.report_html('alice',self.doc,revision=1)
  self.provider.raw=self.raw.replace('width:210mm','width:230mm');self.generate()
  self.assertEqual(self.w.report_availability('alice',self.doc)['selected']['revision'],1)
  self.assertEqual(self.w.processing.get(self.doc,'layout-audit',2)['status'],'NEEDS_REVIEW')
  self.assertEqual(self.w.report_html('alice',self.doc,revision=1),old)
 def test_closing_tag_followed_by_code_fence_does_not_change_original_bytes(self):
  self.provider.raw='```html\n'+self.raw+'\n```';self.generate()
  # Simulate a report saved before this new A4 contract; no migration rewrites it.
  with self.w.workflow.connect() as db:
   row=db.execute("SELECT payload FROM artifacts WHERE document=? AND kind='report-metadata'",(self.doc,)).fetchone();meta=json.loads(row[0]);meta.pop('layout_contract',None);meta.pop('layout_status',None);db.execute("UPDATE artifacts SET payload=? WHERE document=? AND kind='report-metadata'",(json.dumps(meta).encode(),self.doc))
  self.assertEqual(self.w.report_availability('alice',self.doc)['selected']['revision'],1)
  self.assertTrue(self.w.report_html('alice',self.doc,True).endswith(b'</html>\n```'))
 def test_forced_scale_and_model_unfit_pages_are_flagged(self):
  raw=self.raw.replace('data-urs-page="1"','data-urs-page="1" data-urs-unfit="도면 글자 확인 필요"').replace('</style>','section{transform:scale(.8)}</style>')
  audit=inspect(self.final(raw),1);self.assertIn('강제 축소 배치',audit['pages'][0]['issues']);self.assertTrue(any('도면 글자' in x for x in audit['pages'][0]['issues']))

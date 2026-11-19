"""Server pagination tests with exact content and immutable receipt integrity."""
import json,tempfile,unittest
from pathlib import Path
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.workspace import Workspace
from urs.a4_pages import paginate
from urs.workflow import Blocked
class A4Tests(unittest.TestCase):
 def test_missing_html_end_is_never_manufactured(self):
  raw=RAW.replace('</html>','');final,receipt=paginate(raw,1);self.assertEqual(final,raw);self.assertFalse(receipt['changed']);self.assertTrue(receipt['issues'])
 def test_wrong_screen_size_hidden_image_and_long_content_are_saved_automatically(self):
  with tempfile.TemporaryDirectory() as tmp:
   w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('a','fixture-password-123');project=w.create_project('a','fixture');doc=w.upload('a',project,'source.pdf',visual_pdf());w.save_report_settings('a',PROMPT)
   raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('width:210mm','width:260mm').replace('</style>','img{display:none}</style>').replace('</section>',''.join(f'<p>조건 {i}: 120 mm를 유지합니다.</p>' for i in range(75))+'</section>')
   w.processing.provider=ReportAI(raw);w.run('a',doc,'report');final=w.report_html('a',doc)
   self.assertEqual(w.report_html('a',doc,True),raw.encode());self.assertEqual(w.processing.checked_html(doc),final)
   self.assertIn('조건 74'.encode(),final);audit=w.processing.get(doc,'layout-audit');self.assertEqual(audit['status'],'PASS');self.assertGreater(len(audit['pages']),1);self.assertEqual(audit['visible_image_count'],3)
   for page in audit['pages']:self.assertFalse(page['issues']);self.assertAlmostEqual(page['height_px'],297*96/25.4,delta=2)
   with w.workflow.connect() as db:db.execute("UPDATE artifacts SET payload=? WHERE document=? AND kind='a4-pagination'",(b'{}',doc))
   with self.assertRaises(Blocked):w.report_html('a',doc)
 def test_unsplittable_table_row_is_preserved_and_reported(self):
  raw='<!doctype html><html><head><style>section{width:1000px;padding:40px}td{font:16px/1.6 sans-serif}</style></head><body><section data-urs-page="1"><table><tr><td>'+('보존할 문장 '*500)+'</td></tr></table></section></body></html>'
  final,receipt=paginate(raw,1);self.assertIn('보존할 문장 '*500,final);self.assertTrue(receipt['issues'])

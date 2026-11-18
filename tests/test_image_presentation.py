"""Program-level legacy image-loader cleanup. Temporary DB, no paid calls."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf,legacy_image_loader
from urs.image_presentation import prepare
from urs.images import ImageSlots,bind_images
from urs.workspace import Workspace
from urs.workflow import Blocked
class PresentationTests(unittest.TestCase):
 def test_healthy_response_is_byte_exact(self):
  final,receipt=prepare(RAW);self.assertEqual(final,RAW);self.assertFalse(receipt['changed'])
 def test_legacy_cleanup_preserves_report_content_and_slots(self):
  raw=legacy_image_loader(RAW);final,receipt=prepare(raw)
  self.assertTrue(receipt['changed']);self.assertNotIn('<input',final);self.assertNotIn('pdfjsLib',final);self.assertNotIn('class="figure-status"',final);self.assertIn('.figure img { display: block;',final)
  self.assertEqual([s[2] for s in ImageSlots(raw).slots],[s[2] for s in ImageSlots(final).slots])
  self.assertIn('모델 캡션 B',final)
  self.assertIn('<table><tr><td>120 mm</td></tr></table>',final);self.assertTrue(final.startswith('<!doctype html>'))
 def test_unknown_file_ui_or_prose_not_silently_removed(self):
  for raw in [RAW.replace('</body>','<input type="file"></body>'),RAW.replace('</body>','<p>PDF.js 안내</p></body>')]:self.assertEqual(prepare(raw)[0],raw)
 def test_missing_end_is_not_manufactured(self):
  raw=legacy_image_loader(RAW).replace('</html>','');self.assertNotIn('</html>',prepare(raw)[0])
 def test_captions_and_normal_scripts_are_preserved(self):
  raw=legacy_image_loader(RAW).replace('</body>','<p>원본 PDF 선택이란 단어는 본문에 남습니다.</p><script>const keep=42;</script></body>');final,_=prepare(raw)
  self.assertIn('원본 PDF 선택이란 단어는 본문에 남습니다.',final);self.assertIn('<script>const keep=42;</script>',final)
 def test_picker_container_with_report_table_is_not_deleted(self):
  raw=legacy_image_loader(RAW).replace('<h1>원본 PDF 그림 불러오기</h1>','<table><tr><td>보존해야 할 사양</td></tr></table>');final,_=prepare(raw);self.assertIn('<table><tr><td>보존해야 할 사양</td></tr></table>',final);self.assertIn('id="pdf-file"',final)
 def test_generation_storage_integrity_and_tamper_detection(self):
  with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',side_effect=AssertionError('no API')):
   w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('a','fixture-password-123');p=w.create_project('a','Synthetic');doc=w.upload('a',p,'fixture.pdf',visual_pdf());w.save_report_settings('a',PROMPT)
   raw=legacy_image_loader(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));w.processing.provider=ReportAI(raw);w.run('a',doc,'report')
   self.assertEqual(w.report_html('a',doc,True),raw.encode());self.assertEqual(w.processing.get(doc,'layout-audit')['status'],'PASS')
   expected=bind_images(prepare(raw)[0],w.processing.get(doc,'report-images'))[0];self.assertEqual(w.report_html('a',doc),expected.encode());self.assertEqual(w.processing.checked_html(doc),expected.encode())
   self.assertFalse(w.processing.get(doc,'image-bindings')['only_image_addresses_changed'])
   from urs import corrections
   target=f'displayed:{doc}:1'
   with w.workflow.connect() as db:attempt=db.execute('INSERT INTO target_reviews(target,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?)',(target,'verify','finished','FAIL',json.dumps({'status':'FAIL','issues':[{'page':1,'severity':'오류','before':'120 mm','after':'125 mm'}]}),'{}','2026-11-18T00:00:00+00:00')).lastrowid
   plan=corrections.preview(w,'a',doc,target,attempt,[{'issue_id':'0','before':'120 mm','after':'125 mm'}]);new=corrections.apply(w,'a',doc,plan['plan_id']);self.assertEqual(new['revision'],2);self.assertEqual(w.report_html('a',doc),expected.replace('120 mm','125 mm').encode())
   with w.workflow.connect() as db:db.execute("UPDATE artifacts SET payload=? WHERE document=? AND kind='report.prepared.html'",(b'altered',doc))
   with self.assertRaises(Blocked):w.report_html('a',doc)

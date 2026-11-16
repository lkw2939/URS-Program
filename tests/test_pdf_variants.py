import io
import unittest
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from urs.extraction import extract_pdf


class PDFVariantTests(unittest.TestCase):
    def test_merged_cell_identity_and_geometry_preserved(self):
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(400,400))
        for x in (40,340):c.line(x,180,x,300)
        c.line(190,180,190,240)
        for y in (180,240,300):c.line(40,y,340,y)
        c.drawString(50,270,'Merged header');c.drawString(50,210,'Left');c.drawString(200,210,'Right')
        c.save();extracted,_=extract_pdf(stream.getvalue())
        table=extracted['pages'][0]['tables'][0]
        self.assertEqual(len(table['cells']),3)
        self.assertEqual(table['grid'][0][0],table['grid'][0][1])
        self.assertNotEqual(table['grid'][1][0],table['grid'][1][1])
        self.assertEqual({c['text'] for c in table['cells']},{'Merged header','Left','Right'})

    def test_image_only_page_retained_and_review_required(self):
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(400,400))
        image=Image.new('RGB',(100,100),'orange')
        c.drawImage(ImageReader(image),40,40,200,200);c.save()
        extracted,previews=extract_pdf(stream.getvalue())
        self.assertEqual(extracted['coverage'],'NEEDS_REVIEW')
        self.assertEqual(extracted['pages'][0]['blocks'],[])
        self.assertEqual(len(extracted['pages'][0]['images']),1)
        self.assertTrue(any('그림' in w['reason'] for w in extracted['warnings']))
        self.assertTrue(previews[0].startswith(b'\x89PNG'))

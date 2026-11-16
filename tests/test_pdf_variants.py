import base64
import io
import unittest
from PIL import Image
from unittest.mock import patch
from html_fixtures import visual_pdf
from urs.images import crop_images

class PDFVariantTests(unittest.TestCase):
    def test_two_raster_regions_are_distinct_and_in_reading_order(self):
        assets=crop_images(visual_pdf())
        self.assertEqual([a['uri'] for a in assets],['urs-image:1:1','urs-image:1:2'])
        self.assertEqual(assets[0]['bbox'],[20.,100.,120.,200.])
        self.assertNotEqual(assets[0]['sha256'],assets[1]['sha256'])
        for a,color in zip(assets,[(255,0,0),(0,0,255)]):
            with Image.open(io.BytesIO(base64.b64decode(a['data_url'].split(',')[1]))) as img:
                self.assertEqual(img.convert('RGB').getpixel((70,70)),color)

    def test_vector_diagram_retained_without_text_access(self):
        with patch('pdfplumber.page.Page.extract_text',side_effect=AssertionError('No text extraction')),patch('pdfplumber.page.Page.extract_text_lines',side_effect=AssertionError('No text extraction')):
            assets=crop_images(visual_pdf(blank=True,vector=True))
        self.assertEqual(len(assets),1)
        self.assertEqual(assets[0]['bbox'],[30.,280.,100.,360.])
        self.assertNotIn('text',assets[0])

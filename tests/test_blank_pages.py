import unittest
from unittest.mock import patch
from html_fixtures import visual_pdf
from urs.images import crop_images

class BlankPageTests(unittest.TestCase):
    def test_blank_page_does_not_invent_a_picture_or_ocr_text(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            self.assertEqual(crop_images(visual_pdf(blank=True)),[])
    def test_scan_like_raster_is_preserved_without_transcription(self):
        assets=crop_images(visual_pdf())
        self.assertEqual(len(assets),2)
        self.assertTrue(all(set(a)=={'uri','page','index','bbox','sha256','data_url'} for a in assets))

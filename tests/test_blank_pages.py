import io
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader,PdfWriter
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from fixtures import urs_pdf,FixtureAI
from urs.ai import AIBlocked
from urs.workspace import Workspace
from urs.workflow import Blocked


def with_blank():
    writer=PdfWriter();writer.append(io.BytesIO(urs_pdf()));writer.add_blank_page(612,792)
    out=io.BytesIO();writer.write(out);return out.getvalue()


class NoVision:
    def __init__(self):self.calls=0
    def call(self,*args,**kwargs):
        self.calls+=1
        raise AIBlocked('isolated test: live AI disabled')


class BlankPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=Workspace(Path(self.tmp.name)/'test.sqlite')
        self.w.add_user('reviewer','synthetic-test-password')
        self.project=self.w.create_project('reviewer','blank page fixture')
        self.provider=NoVision();self.w.processing.provider=self.provider

    def upload(self,payload):
        document=self.w.upload('reviewer',self.project,'fixture.pdf',payload)
        self.w.run('reviewer',document,'extract')
        return document

    def test_blank_page_requires_explicit_confirmation_without_vision_call(self):
        payload=with_blank();doc=self.upload(payload)
        extracted=self.w.artifact('reviewer',doc,'extraction')
        self.assertTrue(extracted['pages'][2]['blank_candidate'])
        self.assertEqual(self.provider.calls,0)
        with self.assertRaises(ValueError):self.w.review_extraction('reviewer',doc,1,[1,2,3],'checked',{})
        self.assertEqual(self.w.status('reviewer',doc)['revision'],1)
        state=self.w.review_extraction('reviewer',doc,1,[1,2,3],'all original pages compared',{},blank_pages=[3])
        self.assertTrue(next(s['passed'] for s in state['stages'] if s['id']=='extract'))
        self.assertEqual(self.w.original('reviewer',doc)['original'],payload)
        self.assertEqual(len(self.w.processing.previews(doc)),3)

    def test_text_page_cannot_be_hidden_as_blank(self):
        doc=self.upload(with_blank())
        with self.assertRaises(ValueError):self.w.review_extraction('reviewer',doc,1,[1,2,3],'attempt',{},blank_pages=[1,3])
        self.assertEqual(self.w.status('reviewer',doc)['revision'],1)

    def test_image_scan_cannot_be_hidden_as_blank(self):
        out=io.BytesIO();c=canvas.Canvas(out,pagesize=(400,400))
        c.drawImage(ImageReader(Image.new('RGB',(100,100),'white')),40,40,200,200);c.save()
        doc=self.upload(out.getvalue())
        self.assertFalse(self.w.artifact('reviewer',doc,'extraction')['pages'][0]['blank_candidate'])
        with self.assertRaises(ValueError):self.w.review_extraction('reviewer',doc,1,[1],'attempt',{},blank_pages=[1])

    def test_vector_diagram_cannot_be_hidden_as_blank(self):
        out=io.BytesIO();c=canvas.Canvas(out,pagesize=(400,400));c.line(10,10,300,300);c.save()
        doc=self.upload(out.getvalue())
        with self.assertRaises(ValueError):self.w.review_extraction('reviewer',doc,1,[1],'attempt',{},blank_pages=[1])

    def test_entirely_blank_pdf_does_not_become_translated_urs(self):
        writer=PdfWriter();writer.add_blank_page(300,400);out=io.BytesIO();writer.write(out)
        doc=self.upload(out.getvalue())
        self.w.review_extraction('reviewer',doc,1,[1],'true blank',{},blank_pages=[1])
        state=self.w.run('reviewer',doc,'translate')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='translate'),'NEEDS_REVIEW')
        with self.assertRaises(Blocked):self.w.run('reviewer',doc,'verify')

    def test_report_keeps_confirmed_blank_page_and_all_images(self):
        doc=self.upload(with_blank())
        self.w.review_extraction('reviewer',doc,1,[1,2,3],'checked',{},blank_pages=[3])
        self.w.processing.provider=FixtureAI()
        for stage in ('translate','verify','analyze','report'):
            state=self.w.run('reviewer',doc,stage)
            self.assertEqual(next(r['status'] for r in state['results'] if r['stage']==stage),'PASS')
        from docx import Document
        word=Document(io.BytesIO(self.w.export('reviewer',doc,'translation.docx')))
        self.assertEqual(len(word.inline_shapes),3)
        pdf=PdfReader(io.BytesIO(self.w.export('reviewer',doc,'translation.pdf')))
        self.assertIn('확인한 빈 페이지',''.join(p.extract_text() or '' for p in pdf.pages))

    def test_invalid_blank_page_list_does_not_change_revision(self):
        doc=self.upload(with_blank())
        for values in ([3,3],[99],[True],'3'):
            with self.subTest(values=values),self.assertRaises(ValueError):
                self.w.review_extraction('reviewer',doc,1,[1,2,3],'checked',{},blank_pages=values)
        self.assertEqual(self.w.status('reviewer',doc)['revision'],1)

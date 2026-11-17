"""Synthetic PDF/HTML only; never calls a paid API."""
import io
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

PROMPT='  내 프롬프트 원문\nHTML/CSS와 번역은 직접 작성하세요.\n  '
RAW='''<!doctype html>\r\n<html><head><style>body { font-family: serif; margin: 23px; } .p { break-after:page; } [data-urs-page]{width:210mm;height:297mm;box-sizing:border-box;padding:12mm;font-size:14px;line-height:1.4}img{width:100px;height:auto}table{font-size:14px}</style></head><body><section data-urs-page="1"><h1>모델 제목 &amp; 원문</h1><table><tr><td>120 mm</td></tr></table><!-- urs-image:1:2 --><figure><img alt='two' src = "urs-image:1:2"><figcaption>모델 캡션 B</figcaption></figure><p>Literal urs-image:1:1</p><img src='urs-image:1:1' alt="first"><img src=urs-image:9:8><script>const x="urs-image:1:1";</script></section></body></html>'''

def visual_pdf(blank=False, vector=False):
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=(400,400))
    if not blank:
        c.drawString(20,380,'DO NOT EXTRACT THIS TEXT')
        for color,x in [('red',20),('blue',220)]:
            image=Image.new('RGB',(80,80),color)
            c.drawImage(ImageReader(image),x,200,100,100)
            image.close()
    if vector:
        c.rect(30,40,70,80);c.line(30,40,100,120)
    c.showPage();c.save();return out.getvalue()

class ReportAI:
    def __init__(self,raw=RAW):self.raw=raw;self.calls=[]
    def report_html(self,pdf,filename,prompt,image_guide):
        self.calls.append(('report',pdf,filename,prompt,image_guide))
        return self.raw
    def review_pdf(self,task,pdf,filename,html):
        self.calls.append((task,pdf,filename,html))
        return {'status':'PASS','issues':[],'sections':[{'page':1,'text':'fixture analysis'}],'conflicts':[],'questions':[]}

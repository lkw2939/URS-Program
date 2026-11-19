"""Existing stored reports only: no report-generation or paid-review calls."""
import io,json,hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image
from urs.images import crop_images,bind_images
from urs.gates import Status

def seed(workspace,owner='viewer',legacy=True):
    project=workspace.create_project(owner,'Saved report fixture');buf=io.BytesIO();c=canvas.Canvas(buf,pagesize=(400,400))
    for page in range(1,24):
        c.drawString(20,380,'Synthetic source page '+str(page))
        if page==9:c.rect(30,120,200,150);c.line(30,120,230,270)
        if page==23:
            for color,x in [('red',20),('blue',220)]:
                im=Image.new('RGB',(80,80),color);c.drawImage(ImageReader(im),x,100,100,100);im.close()
        c.showPage()
    c.save();pdf=buf.getvalue();doc=workspace.upload(owner,project,'Saved SG6 fixture.pdf',pdf);assets=crop_images(pdf)
    raw='<!doctype html><html><head><meta charset="utf-8"><style>body{font:14px/1.5 sans-serif;margin:24px}.source-page{padding:30px;border:1px solid #ccc;margin:20px 0;min-height:600px}.figure img{width:320px;height:auto;display:'+('none' if legacy else 'block')+'}.figure img.ready{display:block}</style></head><body>'
    if legacy:raw+='<aside class="toolbar"><input type="file" id="pdf-file"><p>원본 PDF 선택 필요</p></aside>'
    for page in range(1,24):
        raw+='<section class="source-page" id="page-'+str(page)+'"><h2>원문 '+str(page)+'쪽 모의 보고서</h2><p>직원용 저장 본문</p>'
        for a in assets:
            if a['page']==page:raw+='<figure class="figure"><img src="'+a['uri']+'"><figcaption>모의 원본 그림</figcaption></figure>'
        raw+='</section>'
    raw+='</body></html>';final,comparison=bind_images(raw,assets)
    meta={'raw_sha256':comparison['raw_sha256'],'final_sha256':comparison['final_sha256'],'source_sha256':hashlib.sha256(pdf).hexdigest(),'model':'historical-fixture','max_output_tokens':16000}
    artifacts={'report.raw.html':raw.encode(),'report.html':final.encode(),'report-metadata':meta,'report-images':assets,'image-bindings':comparison}
    payload={'status':'NEEDS_REVIEW','issues':[{'page':1,'severity':'오류','reason':'모의 번역 문구 확인','before':'직원용 저장 본문','after':'수정 제안'}, {'page':7,'category':'source_ambiguity','severity':'확인 필요','reason':'원문 4시간과 2시간의 적용 확인','question_ko':'4시간과 2시간은 각각 어느 시험에 적용되나요?'}, {'page':9,'category':'image_visibility','severity':'오류','reason':'숨김 CSS 확인'}]}
    target=f'displayed:{doc}:1'
    with workspace.workflow.connect() as db:
        for kind,value in artifacts.items():db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(doc,1,kind,value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()))
        workspace.workflow._record(db,doc,'report',1,'html-v1',Status.PASS,{'reason':'Synthetic saved history; no generation call'},'seed-existing','1')
        db.execute('INSERT INTO target_reviews(target,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?)',(target,'verify','finished','NEEDS_REVIEW',json.dumps(payload,ensure_ascii=False),'{}','2026-11-19T00:00:00+00:00'))
    return doc,project,raw.encode(),final.encode(),target

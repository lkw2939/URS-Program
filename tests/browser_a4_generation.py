"""One real UI generation/save/view/download flow; all model HTTP is mocked."""
import base64,hashlib,io,json,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image
from urs.workspace import Workspace
from urs.web import make_app
from urs.images import crop_images
from html_fixtures import legacy_image_loader
ROOT=Path(__file__).resolve().parents[1]
def fixture():
 out=io.BytesIO();c=canvas.Canvas(out,pagesize=(400,500))
 for n in range(1,26):
  c.drawString(20,480,'Synthetic source page '+str(n))
  if n==9:c.rect(30,50,180,250);c.line(30,50,210,300)
  if n==23:
   for color,x in [('red',20),('blue',220)]:
    image=Image.new('RGB',(80,80),color);c.drawImage(ImageReader(image),x,200,100,100);image.close()
  c.showPage()
 c.save();pdf=out.getvalue();assets=crop_images(pdf)
 raw='<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>body{font:16px/1.6 sans-serif;color:#173a61;background:#e8edf2}section{width:1000px;padding:40px;background:white;margin:20px}figure{margin:12px 0}img{width:240px;height:auto}table{border-collapse:collapse;font-size:14px;width:100%}td,th{border:1px solid #aaa;padding:6px}h1{font-size:24px}</style></head><body>'
 for n in range(1,26):
  raw+=f'<section data-urs-page="{n}"><h1>원문 {n}쪽 · 모의 번역 보고서</h1><p>시험용 본문 {n}. 번역 정확도 검증 자료가 아닙니다.</p>'
  if n==7:raw+=''.join(f'<p>긴 내용 {i}: 수치 120 mm와 필수 조건을 그대로 보존합니다.</p>' for i in range(65))
  if n==12:raw+='<table><caption>사양 전체 목록</caption><thead><tr><th>항목</th><th>조건</th></tr></thead><tbody>'+''.join(f'<tr><td>사양 {i}</td><td>조건 {i}: 230 V · 50 Hz</td></tr>' for i in range(65))+'</tbody><tfoot><tr><td>끝</td><td>표 마지막 조건 보존</td></tr></tfoot></table>'
  if n==16:raw+='<p>'+''.join(f'분할 대상 긴 문장 {i}: 생략하지 않고 다음 A4 장으로 이어갑니다. ' for i in range(100))+'</p>'
  for asset in assets:
   if asset['page']==n:raw+=f'<figure><img src="{asset["uri"]}" alt="원문 {n}쪽 그림 {asset["index"]}"><figcaption>원문 {n}쪽 사진·도면 설명</figcaption></figure>'
  raw+='</section>'
 raw+='</body></html>';return pdf,legacy_image_loader(raw)
def main(pdf=None,raw=None,evidence=None):
 if pdf is None:pdf,raw=fixture()
 evidence=Path(evidence or ROOT/'docs/evidence');evidence.mkdir(parents=True,exist_ok=True)
 calls=[];prompt='사진이 보이는 한국어 기술 보고서를 작성하세요.'
 def network(req,**kwargs):
  wire=json.loads(req.data);content=wire['input'][0]['content'];assert base64.b64decode(content[0]['file_data'].split(',')[1])==pdf;assert content[1]['text']==prompt;calls.append(req.full_url)
  if not req.full_url.endswith('/input_tokens'):assert wire['max_output_tokens']==16000
  value={'input_tokens':15000} if req.full_url.endswith('/input_tokens') else {'status':'completed','usage':{'input_tokens':15000,'output_tokens':14000},'output':[{'content':[{'type':'output_text','text':raw}]}]}
  response=io.BytesIO(json.dumps(value).encode());response.status=200;return response
 env={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'fixture-terra','URS_OPENAI_MAX_OUTPUT_TOKENS':'16000','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True),patch('urllib.request.urlopen',side_effect=network):
  w=Workspace(Path(tmp)/'test.sqlite');w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','A4 generation fixture');doc=w.upload('fixture',project,'source.pdf',pdf);w.save_report_settings('fixture',prompt)
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='A4 generation fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click();page.get_by_role('button',name='HTML 보고서 비용 확인 (무료)',exact=True).click();page.wait_for_function("() => ![...document.querySelectorAll('#process-buttons button')].find(b=>b.textContent==='보고서 생성').disabled")
    page.get_by_role('button',name='보고서 생성',exact=True).click();page.wait_for_function("() => !document.querySelector('#view-html').disabled",timeout=90000);page.locator('#view-html').click();frame=page.locator('#report-preview').element_handle().content_frame();frame.locator('img').first.wait_for()
    measure="""() => ({pages:[...document.querySelectorAll('[data-urs-page]')].map(p=>{const r=p.getBoundingClientRect();return {source:p.dataset.ursPage,w:r.width,h:r.height,overflow:p.scrollHeight>p.clientHeight+2||p.scrollWidth>p.clientWidth+2}}),images:[...document.images].map(i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);return {source:i.closest('[data-urs-page]').dataset.ursPage,visible:i.complete&&i.naturalWidth>0&&r.width>0&&r.height>0&&s.display!=='none'&&s.visibility==='visible',src:i.getAttribute('src').slice(0,22)}})})"""
    shown=frame.evaluate(measure);assert len(shown['pages'])>25 and all(abs(x['w']-210*96/25.4)<2 and abs(x['h']-297*96/25.4)<2 and not x['overflow'] for x in shown['pages']),shown
    assert all(x['visible'] for x in shown['images']) and any(x['source']=='9' for x in shown['images']) and any(x['source']=='23' for x in shown['images']);assert frame.locator('input[type=file],script[src*="pdf"]').count()==0
    final=w.report_html('fixture',doc);assert w.report_html('fixture',doc,True)==raw.encode();assert w.processing.checked_html(doc)==final
    audit=w.processing.get(doc,'layout-audit');assert audit['status']=='PASS',audit;assert audit['visible_image_count']==len(shown['images'])
    page.locator('#view-html').focus();page.locator('#html-files summary').focus();page.locator('#html-files summary').press('Enter');page.wait_for_function("() => document.querySelector('#html-files').open")
    with page.expect_download() as download:page.locator('#final-html').click()
    saved=Path(tmp)/'report.html';download.value.save_as(saved);assert saved.read_bytes()==final
    offline=b.new_context(offline=True,java_script_enabled=False,viewport={'width':1280,'height':1000});local=offline.new_page();local.set_content(saved.read_text(),wait_until="load");local.wait_for_function('() => [...document.images].every(i=>i.complete)');assert local.evaluate(measure)==shown
    for n in (9,23):local.locator(f'[data-urs-page="{n}"]').filter(has=local.locator('img')).first.screenshot(path=str(evidence/f'a4-generation-page{n}.png'))
    local.set_viewport_size({'width':390,'height':844});narrow=local.evaluate(measure);assert narrow==shown
    # Original sentences, last table row, and short source page all survive automatic pagination.
    if '분할 대상 긴 문장 99' in raw:
     assert '분할 대상 긴 문장 99' in local.locator('body').inner_text();assert '표 마지막 조건 보존' in local.locator('body').inner_text();assert local.locator('[data-urs-page="1"]').count()==1
    assert calls==['https://api.openai.com/v1/responses/input_tokens','https://api.openai.com/v1/responses'];offline.close();b.close()
    result={'scope':'local actual web route; mock OpenAI, no paid call; temporary DB only','source_pages':25,'final_sheets':len(shown['pages']),'visible_images':len(shown['images']),'page9_and_page23_visible':True,'a4_screen_both_dimensions':True,'overflow':False,'download_same_bytes':True,'downloaded_bytes_offline_no_javascript':True,'narrow_screen_same_dimensions':True,'sha256':hashlib.sha256(final).hexdigest()};(evidence/'a4-generation-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

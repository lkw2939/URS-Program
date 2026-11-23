"""Real web generation route with mock OpenAI; inspect displayed pixels and offline download."""
import base64,hashlib,io,json,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from urs.images import crop_images,bind_images
from urs.report_contract import TEXT
from html_fixtures import visual_pdf,legacy_image_loader
ROOT=Path(__file__).resolve().parents[1]
def main(legacy=False):
 pdf=visual_pdf(vector=True);assets=crop_images(pdf);assert len(assets)==3
 prompt='기존 저장 프롬프트 원문. 이전 방식은 PDF.js와 원본 PDF 재선택을 요청했습니다. 번역과 디자인은 직접 작성하세요.'
 raw='''<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>body{margin:18px;background:#eef3f7;color:#17364e;font:16px/1.5 sans-serif}section{box-sizing:border-box;width:210mm;height:297mm;padding:14mm;background:white}h1{font-size:24px}h2{font-size:18px}.figures{display:flex;gap:12px;align-items:flex-start}figure{margin:0;width:160px}img{display:block;width:160px;height:auto;object-fit:contain}figcaption{font-size:14px}</style></head><body><section data-urs-page="1"><h1>사진·도면 즉시 표시 모의 보고서</h1><p>원본 1쪽 · 이 문장은 실제 번역이 아닌 화면 시험용 본문입니다.</p><h2>처음 업로드한 PDF의 사진과 벡터 도면</h2><div class="figures">'''
 for a,label in zip(assets,['첫 번째 원본 사진','두 번째 원본 사진','원본 벡터 도면']):raw+=f'<figure><img src="{a["uri"]}" alt="{label}"><figcaption>{label}</figcaption></figure>'
 raw+='</div><p>파일 다시 선택, PDF.js, 인터넷 연결 없이 표시됩니다.</p></section></body></html>'
 if legacy:raw=legacy_image_loader(raw)
 calls=[]
 def network(req,**kwargs):
  wire=json.loads(req.data);content=wire['input'][0]['content'];assert base64.b64decode(content[0]['file_data'].split(',')[1])==pdf;assert content[1]['text']==prompt;assert content[3]['text']==TEXT;calls.append(req.full_url)
  value={'input_tokens':2100} if req.full_url.endswith('/input_tokens') else {'status':'completed','usage':{'input_tokens':2100,'output_tokens':1800},'output':[{'content':[{'type':'output_text','text':(__import__('urs.image_presentation',fromlist=['prepare']).prepare(raw)[0] if legacy and len(calls)>2 else raw)}]}]}
  response=io.BytesIO(json.dumps(value).encode());response.status=200;return response
 def visible(page):
  page.locator('img').first.wait_for();page.wait_for_function('() => [...document.images].every(i=>i.complete&&i.naturalWidth>0)')
  result=page.locator('img').evaluate_all("xs=>xs.map(i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);const c=document.createElement('canvas');c.width=i.naturalWidth;c.height=i.naturalHeight;const x=c.getContext('2d');x.drawImage(i,0,0);const bytes=x.getImageData(0,0,c.width,c.height).data;let dark=0;for(let n=0;n<bytes.length;n+=4)if(bytes[n]<100&&bytes[n+1]<100&&bytes[n+2]<100)dark++;const m=(Math.floor(c.height/2)*c.width+Math.floor(c.width/2))*4;return {visible:r.width>0&&r.height>0&&s.display!=='none'&&s.visibility==='visible'&&Number(s.opacity)>0,rgb:[...bytes.slice(m,m+3)],dark}})")
  assert len(result)==3 and all(r['visible'] for r in result);assert result[0]['rgb']==[255,0,0] and result[1]['rgb']==[0,0,255];assert result[2]['dark']>100,result
  assert page.locator('input[type=file],script,canvas,iframe,embed,object').count()==0
  return result
 env={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'fixture-terra','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True),patch('urllib.request.urlopen',side_effect=network):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','Immediate image fixture');doc=w.upload('fixture',project,'source.pdf',pdf);w.save_report_settings('fixture',prompt)
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});__import__("component_harness").install(page);page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='Immediate image fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    page.wait_for_function("() => document.querySelector('#generation-contract').textContent.includes('terra-layout-refinement-v1')")
    assert calls==[];page.get_by_role('button',name='HTML 보고서 비용 확인 (무료)',exact=True).click();page.wait_for_function("() => ![...document.querySelectorAll('#process-buttons button')].find(b=>b.textContent==='보고서 생성').disabled")
    page.get_by_role('button',name='보고서 생성',exact=True).click();page.get_by_role('button',name='최종 보고서 보기(사진 포함)',exact=True).wait_for();page.wait_for_function("() => !document.querySelector('#view-html').disabled")
    page.get_by_role('button',name='최종 보고서 보기(사진 포함)',exact=True).click();frame=page.frame_locator('#report-preview');frame.locator('img').first.wait_for();actual_frame=page.locator('#report-preview').element_handle().content_frame();displayed=visible(actual_frame)
    assert calls==['https://api.openai.com/v1/responses/input_tokens','https://api.openai.com/v1/responses']*(2 if legacy else 1);assert w.status('fixture',doc)['revision']==1
    saved=w.report_html('fixture',doc);from urs.image_presentation import prepare
    assert saved==bind_images(prepare(raw)[0],assets)[0].encode();assert w.report_html('fixture',doc,True)==raw.encode();assert w.report_settings('fixture')['prompt']==prompt
    audit=w.processing.get(doc,'layout-audit');assert audit['status']=='PASS' and audit['visible_image_count']==3
    page.locator('#html-files summary').focus();page.locator('#html-files summary').press('Enter');page.wait_for_function("() => document.querySelector('#html-files').open")
    with page.expect_download() as download:page.locator('#final-html').click()
    downloaded=Path(download.value.path()).read_bytes();assert downloaded==saved;local=Path(tmp)/'report.html';local.write_bytes(downloaded)
    offline=b.new_context(offline=True,java_script_enabled=False,viewport={'width':1000,'height':1200});standalone=offline.new_page();standalone.set_content(local.read_text(),wait_until='load');assert visible(standalone)==displayed
    standalone.screenshot(path=str(ROOT/'docs/evidence/immediate-original-images.png'),full_page=True);offline.close();b.close()
    (ROOT/'docs/evidence/immediate-image-check.json').write_text(json.dumps({'scope':'Synthetic PDF/text, mock OpenAI transport; no paid calls or operating data changes','mock_generation_requests':1,'html_check_clicked':True,'original_photos_visible':2,'original_vector_diagrams_visible':1,'same_page_pixel_checks':displayed,'offline_without_javascript':True,'pdf_reselection_controls':0,'pdfjs_dependencies':0,'legacy_pdf_loader_fixed_by_mock_model':legacy,'only_image_addresses_changed':not legacy,'stored_final_sha256':hashlib.sha256(saved).hexdigest()},ensure_ascii=False,indent=2)+'\n')
    print('PASS: login -> one report generation(mock) -> original PDF crop binding -> final save -> HTML 확인 click; 2 source photos with distinct red/blue pixels + source vector diagram visibly rendered in correct slots; byte-identical downloaded HTML renders in an offline browser document with JavaScript disabled and no PDF selection/PDF.js; raw HTML/prompt preserved, paid calls=0.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main();main(legacy=True)

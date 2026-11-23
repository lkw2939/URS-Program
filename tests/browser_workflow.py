"""Unmodified employee wizard: stored report -> review -> typed correction -> CSS -> final check.
No component host. Only real visible clicks, a temporary DB and mocked Responses transport.
"""
import sys,io,json,tempfile,threading,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
BEFORE='고객은 시험을 반드시 수행해야 합니다.'
AFTER='고객의 시험 수행을 권장합니다.'
def main():
 env={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'mock-terra','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 paid=[]
 def wire(req,**kw):
  body=json.loads(req.data)
  if req.full_url.endswith('/input_tokens'):result={'input_tokens':12000}
  else:
   parts=body['input'][0]['content'];paid.append(body);texts=[p['text'] for p in parts if p['type']=='input_text'];html=next((t for t in texts if '<html' in t.lower() and '<body' in t.lower()),'')
   if 'Independently' in texts[0]:
    value={'status':'FAIL','issues':[{'page':1,'severity':'오류','issue_type':'translation','category':'obligation','before':BEFORE,'after':AFTER,'reason':'권장 사항이 의무로 번역됐습니다.','source_en':'The customer should perform the test.'},{'page':1,'issue_type':'customer','severity':'확인 필요','question_ko':'시험 시간의 적용 기준은 무엇인가요?','reason':'원문 기준 확인 필요'}]} if BEFORE in html else {'status':'PASS','issues':[]}
    value=json.dumps(value,ensure_ascii=False)
   elif 'Analyze equipment' in texts[0]:
    assert any('시험 시간의 적용 기준은 무엇인가요?' in t for t in texts),'Pending questions must survive correction/CSS versions'
    value=json.dumps({'status':'PASS','issues':[],'sections':[{'page':1,'text':'모의 사양 분석 완료'}],'conflicts':[],'questions':[]},ensure_ascii=False)
   else:
    assert AFTER in html and BEFORE not in html,'CSS must use the saved employee correction'
    value=html.replace('margin: 23px','margin: 25px')
   result={'status':'completed','usage':{'input_tokens':12000,'output_tokens':500},'output':[{'content':[{'type':'output_text','text':value}]}]}
  response=io.BytesIO(json.dumps(result).encode());response.status=200;return response
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True),patch('urllib.request.urlopen',side_effect=wire):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','단계별 검토 시험');doc=w.upload('fixture',project,'모의 기술사양서.pdf',visual_pdf());w.save_report_settings('fixture',PROMPT)
  raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</section>','<p>'+BEFORE+'</p></section>');w.processing.provider=ReportAI(raw);w.run('fixture',doc,'report');original=w.report_html('fixture',doc,revision=1);w.processing.provider=None
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.get_by_role('button',name='단계별 검토 시험',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click();page.wait_for_function("()=>document.querySelector('#review').getAttribute('aria-busy')==='false'")
    def screen(index):
     page.wait_for_function('(i)=>document.querySelector("#flow-panel-"+i).hidden===false',arg=index)
     assert page.locator('.flow-panel:visible').count()==1
    def next_step(index):page.locator('#flow-next').click();screen(index)
    def run_review(name):
     page.get_by_role('button',name=name,exact=True).click();dialog=page.locator('#confirm-review-run');dialog.wait_for();dialog.click();page.wait_for_function("()=>document.querySelector('#message').textContent==='처리를 완료했습니다.'")
    screen(0);assert page.locator('#workspace').is_hidden();assert page.get_by_role('button',name='CSS·배치 다듬기',exact=True).is_hidden();assert page.get_by_role('button',name='기술 분석 실행',exact=True).is_hidden()
    # A forged forward jump is rejected on the server, without invoking OpenAI.
    rejected=page.evaluate('''async doc=>{const me=await(await fetch('/api/me')).json();const r=await fetch('/api/documents/'+doc+'/workflow-step',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf},body:JSON.stringify({step:4,revision:1})});return r.status}''',doc);assert rejected==409 and len(paid)==0
    guards=page.evaluate('''async ({doc,sha})=>{const me=await(await fetch('/api/me')).json();const send=async(action,body)=>(await fetch('/api/documents/'+doc+'/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf},body:JSON.stringify(body)})).status;return [await send('layout-edit',{revision:1,notes:''}),await send('review-prepare',{stage:'analyze',expected_revision:1,expected_sha256:sha}),await send('approve',{revision:1,note:'먼저 승인 불가',reviewed_outputs:['report.html']})]}''',{'doc':doc,'sha':hashlib.sha256(original).hexdigest()});assert guards==[409,409,409] and len(paid)==0
    page.frame_locator('#report-preview').locator('img').first.wait_for();assert page.frame_locator('#report-preview').locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.complete&&i.naturalWidth>0&&getComputedStyle(i).display!=="none")')
    page.screenshot(path=str(ROOT/'docs/evidence/workflow-report.png'),full_page=True);next_step(1);assert page.locator('#flow-next').is_disabled();run_review('독립 검증 실행');assert len(paid)==1 and page.locator('#flow-next').is_disabled()
    with page.context.expect_page() as opened:page.get_by_role('button',name='독립검증 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();result.locator('[data-before]').fill(BEFORE);result.locator('[data-after]').fill(AFTER);result.locator('[data-select]').check();result.locator('#preview-corrections').click();result.locator('#apply-corrections').wait_for(state='visible');result.locator('#apply-corrections').click();result.wait_for_function("()=>document.querySelector('#correction-status').textContent.includes('버전 2')")
    page.wait_for_function("()=>!document.querySelector('#flow-next').disabled");assert len(paid)==1;assert AFTER.encode() in w.report_html('fixture',doc,revision=2);assert original==w.report_html('fixture',doc,revision=1);result.close()
    page.screenshot(path=str(ROOT/'docs/evidence/workflow-corrected.png'),full_page=True);next_step(2);assert page.locator('#flow-next').is_disabled();assert '버전 2' in page.locator('#layout-edit-state').inner_text();page.locator('#edit-layout').click();page.wait_for_function("()=>document.querySelector('#layout-edit-state').textContent.includes('새 버전 3')",timeout=60000);assert len(paid)==2
    page.screenshot(path=str(ROOT/'docs/evidence/workflow-css.png'),full_page=True);next_step(3);assert page.locator('#flow-next').is_disabled();run_review('독립 검증 실행');assert len(paid)==3;next_step(4);assert page.locator('#flow-next').is_disabled();run_review('기술 분석 실행');assert len(paid)==4
    with page.context.expect_page() as opened:page.get_by_role('button',name='기술분석 결과 보기',exact=True).click()
    technical=opened.value;technical.wait_for_load_state();assert '시험 시간의 적용 기준은 무엇인가요?' in technical.locator('body').inner_text();technical.close()
    # All previous stages remain freely accessible, with no API or report writes.
    next_step(5)
    for i in (4,3,2,1,0):page.locator('#flow-back').click();screen(i)
    assert len(paid)==4;assert page.locator('#flow-back').is_disabled();assert original==w.report_html('fixture',doc,revision=1)
    final=w.report_html('fixture',doc,revision=3);assert AFTER.encode() in final and BEFORE.encode() not in final and b'margin: 25px' in final
    with page.expect_download() as download:page.locator('#final-html').click()
    assert Path(download.value.path()).read_bytes()==final
    # Offline HTML opens with visible photos and measured A4 geometry.
    saved=Path(tmp)/'report.html';saved.write_bytes(final);offline=browser.new_context(offline=True,java_script_enabled=False);local=offline.new_page();local.set_content(saved.read_text(),wait_until='load');local.locator('img').first.wait_for();assert local.locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.complete&&i.naturalWidth>0&&getComputedStyle(i).display!=="none")');box=local.locator('[data-urs-page]').bounding_box();assert abs(box['width']-210*96/25.4)<2 and abs(box['height']-297*96/25.4)<2
    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(ROOT/'docs/evidence/workflow-mobile.png'),full_page=True)
    page.locator('#close-review').click();page.locator('#workspace').wait_for(state='visible');assert page.locator('#review').is_hidden()
    assert not errors,errors;browser.close();print('PASS: unmodified logged-in wizard; exactly one stage visible; forged jump blocked HTTP409; stored report -> FAIL -> typed correction saved v2 -> CSS on corrected v2 saves v3 -> final verification PASS -> analysis -> approval screen; free back navigation; earlier reports preserved; exact downloaded HTML bytes render offline with visible photos and A4 dimensions. Four mocked paid requests, zero real API calls. Approval remains subject to existing real qualification requirements.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

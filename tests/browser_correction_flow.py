"""Actual buttons -> source request manifest -> selective correction -> corrected-target recheck."""
import sys,io,json,base64,tempfile,threading,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from urs.ai import AIError
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
BEFORE='고객은 시험을 반드시 수행해야 합니다.'
AFTER='고객의 시험 수행을 권장합니다.'
TYPED_AFTER='시험 수행은 고객에게 권장되는 사항입니다.'
FINDINGS=[{'page':1,'severity':'오류','category':'obligation','title_ko':'원문은 권장인데 번역은 의무로 바뀌었습니다','problem_ko':'should가 반드시 수행해야 한다는 표현으로 바뀌었습니다.','why_ko':'계약상 의무와 검수 책임이 달라집니다.','fix_ko':'원문의 권장 강도를 유지하는 문장으로 고치세요.','before':BEFORE,'after':AFTER,'source_en':'The customer should perform the test.'},
{'page':7,'severity':'오류','category':'source_ambiguity','title_ko':'시험 시간의 적용 기준을 확인해야 합니다.','reason':'원문에서 4시간과 2시간의 적용 관계가 불명확합니다.','question_ko':'4시간과 2시간은 각각 어떤 시험 조건에 적용되나요?','before':'4시간','after':'2시간','needs_confirmation':True},
{'page':1,'severity':'오류','category':'pagination','reason':'인쇄 쪽수만 다릅니다.'},
{'page':1,'severity':'오류','category':'image_reference','title_ko':'검증용 그림 주소의 표시를 확인해야 합니다.','reason':'urs-review-image: 주소와 숨김 CSS 점검','source_en':'  ','before':'120 mm','after':'수정하지 않음'},
{'page':12,'pages':[12,16],'severity':'확인 필요','category':'customer_confirmation','title_ko':'장비의 공급·통합 책임을 확인해야 합니다.','question_ko':'기존 장비의 재사용과 추가 장비의 공급·통합 책임은 누가 맡나요?','evidence':[{'page':12,'source_en':'The existing equipment is reused.'},{'page':16,'source_en':'Equipment must be supplied and integrated.'}]},
{'page':1,'severity':'오류','title_ko':'추가 번역 문구 확인','problem_ko':'추가 번역 문구 확인','source_en':' ','before':'','after':''}]
def main():
 env={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'fixture-model','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 calls=[]
 def network(req,**kw):
  assert kw['timeout'] is None;wire=json.loads(req.data);calls.append((req.full_url,wire,hashlib.sha256(req.data).hexdigest()))
  if req.full_url.endswith('/input_tokens'):body={'input_tokens':12000}
  else:
   text=wire['input'][0]['content'][2]['text'];assert 'data:image/' not in text;assert len([p for p in wire['input'][0]['content'] if p['type']=='input_image'])==3
   corrected=TYPED_AFTER in text;result={'status':'PASS' if corrected else 'FAIL','issues':[] if corrected else FINDINGS}
   body={'status':'completed','usage':{'input_tokens':12000,'output_tokens':400},'output':[{'content':[{'type':'output_text','text':json.dumps(result,ensure_ascii=False)}]}]}
  r=io.BytesIO(json.dumps(body).encode());r.status=200;return r
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True),patch('urllib.request.urlopen',side_effect=network):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','Correction workflow');pdf=visual_pdf()
  from pypdf import PdfReader,PdfWriter
  writer=PdfWriter();writer.add_page(PdfReader(io.BytesIO(pdf)).pages[0])
  for _ in range(15):writer.add_blank_page(width=400,height=400)
  output=io.BytesIO();writer.write(output);pdf=output.getvalue();doc=w.upload('fixture',project,'SG6 모의 기술사양서.pdf',pdf);w.save_report_settings('fixture',PROMPT)
  raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</section>','<p>'+BEFORE+'</p></section>');raw=raw.replace('</body>',''.join('<section data-urs-page="'+str(n)+'"><p>원문 '+str(n)+'쪽 모의 본문</p></section>' for n in range(2,17))+'</body>');provider=ReportAI(raw);w.processing.provider=provider;w.run('fixture',doc,'report');old=w.report_html('fixture',doc,revision=1)
  with patch.object(provider,'report_html',side_effect=AIError('기존 실패 시도 보존')):w.run('fixture',doc,'report')
  w.processing.provider=None;w.save_ai_settings('fixture',{'model':'fixture-model','effort':'high','max_output_tokens':16000})
  with w.workflow.connect() as db:old_artifacts=[tuple(r) for r in db.execute('SELECT * FROM artifacts')]
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='Correction workflow',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    page.get_by_role('button',name='독립 검증 실행',exact=True).click();page.locator('#confirm-review-run').wait_for();assert len(calls)==1 and calls[0][0].endswith('/input_tokens')
    page.locator('#confirm-review-run').click();page.wait_for_function("() => !document.querySelector('#view-verification').disabled")
    with page.context.expect_page() as opened:page.get_by_role('button',name='독립검증 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();result.on('pageerror',lambda e:errors.append(str(e)));result.locator('.summary').wait_for()
    assert '보고서 버전 1' in result.locator('header').inner_text();assert 'SHA' not in result.locator('header').inner_text();assert '오류 2건' in result.locator('.summary').inner_text() and '확인 필요 2건' in result.locator('.summary').inner_text()
    assert not result.locator('.technical').evaluate('(e)=>e.open');assert result.locator('select,input[type=file]').count()==0
    assert result.locator('[data-issue="1"] textarea').count()==0;assert result.locator('[data-issue="3"] textarea').count()==0
    assert '4시간과 2시간' in result.locator('[data-issue="1"]').inner_text();assert '12쪽 · 16쪽' in result.locator('[data-issue="4"]').inner_text();assert result.locator('[data-issue="3"] .source').count()==0
    assert result.locator('[data-issue="5"] .proposal summary').inner_text()=='수정 문구 직접 입력';assert not result.locator('[data-issue="5"] .proposal').evaluate('(e)=>e.open')
    assert '판단 근거가 기록에 없습니다' not in result.locator('body').inner_text()
    assert '그림 주소만 다르고 본문·CSS는 같습니다' in result.locator('[data-issue="3"]').inner_text()
    assert abs(result.locator('main').evaluate('(e)=>e.getBoundingClientRect().width')-210*96/25.4)<2
    result.locator('.technical summary').click();assert '별도 이미지 입력 3개' in result.locator('.technical').inner_text();assert '변환 PDF: 전송하지 않음' in result.locator('.technical').inner_text();assert calls[1][2] in result.locator('.technical').inner_text();result.locator('.technical summary').click()
    result.set_viewport_size({'width':390,'height':844});assert result.evaluate('document.documentElement.scrollWidth<=innerWidth');result.screenshot(path=str(ROOT/'docs/evidence/correction-result-mobile.png'),full_page=True);result.set_viewport_size({'width':1280,'height':1000});result.screenshot(path=str(ROOT/'docs/evidence/correction-result-before.png'),full_page=True)
    result.locator('[data-issue="0"] [data-before]').fill(BEFORE);result.locator('[data-issue="0"] [data-after]').fill('');result.locator('[data-issue="0"] [data-select]').check();result.locator('#preview-corrections').click();result.wait_for_function("() => document.querySelector('#correction-status').textContent.includes('삭제는 별도로')");assert w.status('fixture',doc)['revision']==2;result.locator('[data-issue="0"] [data-after]').fill(TYPED_AFTER);result.locator('#preview-corrections').click();result.locator('#apply-corrections').wait_for(state='visible');assert BEFORE in result.locator('#correction-preview').inner_text() and TYPED_AFTER in result.locator('#correction-preview').inner_text();assert w.status('fixture',doc)['revision']==2;assert len(calls)==2
    printed=result.pdf(print_background=True,prefer_css_page_size=True);(ROOT/'docs/evidence/review-result-a4-print.pdf').write_bytes(printed);reader=PdfReader(io.BytesIO(printed));assert len(reader.pages)<6;assert all(abs(float(p.mediabox.width)-595.276)<2 and abs(float(p.mediabox.height)-841.89)<2 for p in reader.pages);assert ''.join(TYPED_AFTER.split()) in ''.join(''.join(p.extract_text() for p in reader.pages).split());printed_text=''.join(''.join(p.extract_text() for p in reader.pages).split());assert all(''.join(text.split()) in printed_text for text in ['4시간과 2시간은 각각 어떤 시험 조건에 적용되나요?','The existing equipment is reused.','Equipment must be supplied and integrated.','AI의 지적을 확정 오류로 처리하지 않습니다.'])
    result.locator('#apply-corrections').click();result.wait_for_function("() => document.querySelector('#correction-status').textContent.includes('버전 3')");assert '수정 전' in result.locator('#historical-note').inner_text();assert result.locator('#analyze-current').is_disabled()
    assert w.report_html('fixture',doc,revision=1)==old;assert w.report_html('fixture',doc,revision=3)==old.replace(BEFORE.encode(),TYPED_AFTER.encode());assert len(calls)==2
    with page.context.expect_page() as opened:result.locator('#corrected-report').click()
    report=opened.value;report.wait_for_load_state();assert TYPED_AFTER in report.locator('body').inner_text() and BEFORE not in report.locator('body').inner_text();assert report.locator('img').count()==3;report.wait_for_function('() => [...document.images].every(i=>i.complete&&i.naturalWidth>0&&i.getBoundingClientRect().width>0&&i.getBoundingClientRect().height>0&&getComputedStyle(i).display!=="none"&&getComputedStyle(i).visibility==="visible")');report.screenshot(path=str(ROOT/'docs/evidence/correction-report-images.png'));report.close()
    result.locator('#next-actions').screenshot(path=str(ROOT/'docs/evidence/correction-result-applied.png'))
    result.locator('#reverify').click();result.locator('#confirm-review-run').wait_for();assert len(calls)==3;result.locator('#confirm-review-run').click();result.locator('#new-result').wait_for(state='visible');result.wait_for_function("() => !document.querySelector('#analyze-current').disabled")
    assert len(calls)==4 and TYPED_AFTER in calls[-1][1]['input'][0]['content'][2]['text'];assert base64.b64decode(calls[-1][1]['input'][0]['content'][0]['file_data'].split(',')[1])==pdf
    result.locator('#new-result').click();result.wait_for_load_state();assert '보고서 버전 3' in result.locator('header').inner_text();assert '오류 0건' in result.locator('.summary').inner_text();result.screenshot(path=str(ROOT/'docs/evidence/correction-result-reverified.png'),full_page=True)
    with w.workflow.connect() as db:assert old_artifacts==[tuple(r) for r in db.execute('SELECT * FROM artifacts WHERE revision<=2')]
    assert not errors,errors;b.close();print('PASS: real logged-in buttons, no separate mandatory cost button; exact PDF + prepared final HTML + PNG image inputs recorded at request boundary; Korean result cards -> preview (no mutation) -> selected error applied to new version3 preserving versions1/2 -> corrected report opens -> integrated-cost recheck(mock) uses version3 -> new result and technical-analysis unlock; uncertain/layout items untouched; paid API calls=0.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

"""Login -> mocked verification -> automatic persistence -> easy single-item edit -> restart/reopen."""
import sys,threading,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from urs import targets
from urs.ai import AIError
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
BEFORE='고객은 반드시 시험합니다.';AFTER='고객의 시험을 권장합니다.';TYPED='고객은 시험을 수행하는 것이 권장됩니다.'

def start(w):
 server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();return server,thread,f'http://127.0.0.1:{server.server_port}'
def stop(server,thread):server.shutdown();server.server_close();thread.join()
def main():
 env={'URS_OPENAI_MODEL':'mock-terra','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True),patch('urllib.request.urlopen',side_effect=AssertionError('Paid API forbidden')),patch('urs.costing.count_input_tokens',return_value=12000):
  path=Path(tmp)/'fixture.sqlite';w=Workspace(path);w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','저장·간편 수정 시험');doc=w.upload('fixture',project,'모의 저장 시험.pdf',visual_pdf());w.save_report_settings('fixture',PROMPT)
  raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</section>','<p>'+BEFORE+'</p></section>');provider=ReportAI(raw);w.processing.provider=provider;w.run('fixture',doc,'report');original=w.report_html('fixture',doc,revision=1)
  answers=[]
  def review(*args,**kwargs):answers.append(args);return {'status':'FAIL','issues':[{'page':1,'severity':'오류','issue_type':'translation','title_ko':'권장 사항을 의무로 번역했습니다.','before':BEFORE,'after':AFTER,'reason':'원문은 시험을 권장하지만 현재 번역은 의무로 표현합니다.','source_en':'The customer should perform the test.'}]}
  provider.review_pdf=review;server,thread,base=start(w)
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);context=browser.new_context(viewport={'width':1280,'height':1000});page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def login(url):
     page.goto(url);page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible')
    login(base);page.goto(base+f'/?document={doc}&step=2');page.wait_for_function("()=>document.querySelector('#review').dataset.currentStep==='2'&&document.querySelector('#review').getAttribute('aria-busy')==='false'")
    page.get_by_role('button',name='독립 검증 실행',exact=True).click();page.locator('#confirm-review-run').wait_for();page.locator('#confirm-review-run').click();page.wait_for_function("()=>document.querySelector('#message').textContent==='처리를 완료했습니다.'");assert len(answers)==1
    page.wait_for_function("()=>document.querySelector('#saved-reviews-link').textContent.includes('1건')")
    receipt=targets.overview(w,'fixture',doc,f'displayed:{doc}:1')['reviews']['verify'];assert receipt['saved'] and receipt['saved_sha256']
    with page.context.expect_page() as opened:page.get_by_role('button',name='독립검증 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();result.set_viewport_size({'width':1280,'height':1600});assert '수정은 이렇게' in result.locator('.edit-guide').inner_text();finding=result.locator('[data-issue="0"]')
    finding.locator('[data-edit-item]').click();finding.locator('[data-after]').fill(TYPED);finding.locator('[data-preview-item]').click();finding.locator('[data-apply-item]').wait_for(state='visible');assert TYPED in finding.locator('[data-item-preview]').inner_text();assert w.status('fixture',doc)['revision']==1
    finding.screenshot(path=str(ROOT/'docs/evidence/saved-review-easy-edit.png'));finding.locator('[data-apply-item]').click();result.wait_for_function("()=>document.querySelector('#correction-status').textContent.includes('버전 2')");assert finding.locator('[data-edit-item]').is_disabled();assert not finding.locator('[data-select]').is_checked(),'Single-item path must not require a selection checkbox'
    with result.context.expect_page() as opened:result.locator('#corrected-report').click()
    corrected=opened.value;corrected.wait_for_load_state();assert TYPED in corrected.locator('body').inner_text() and BEFORE not in corrected.locator('body').inner_text();corrected.close()
    assert w.report_html('fixture',doc,revision=1)==original;assert TYPED.encode() in w.report_html('fixture',doc,revision=2)
    page.reload();page.wait_for_function("()=>document.querySelector('#review').getAttribute('aria-busy')==='false'");assert '1건' in page.locator('#saved-reviews-link').inner_text()
    with page.context.expect_page() as opened:page.locator('#saved-reviews-link').click()
    history=opened.value;history.wait_for_load_state();assert '보고서 버전 1' in history.locator('article').inner_text();assert '이전 보고서 버전' in history.locator('article').inner_text()
    with history.expect_download() as downloaded:history.get_by_role('link',name='HTML 내려받기',exact=True).click()
    saved_bytes=Path(downloaded.value.path()).read_bytes();assert '저장 당시 결과의 읽기 전용 사본'.encode() in saved_bytes
    with w.workflow.connect() as db:record=dict(db.execute('SELECT * FROM review_archive').fetchone());source=tuple(db.execute('SELECT * FROM target_reviews WHERE id=?',(receipt['attempt'],)).fetchone())
    key=record['key'];history.close();result.close();stop(server,thread);w=Workspace(path);w.processing.provider=provider;server,thread,base=start(w);context.clear_cookies();login(base)
    # A later failed review has no result to archive; the earlier completed result stays accessible.
    with patch.object(provider,'review_pdf',side_effect=AIError('모의 재검증 실패')):targets.run(w,'fixture',doc,f'displayed:{doc}:2','verify')
    page.goto(base+f'/?document={doc}&step=2');page.wait_for_function("()=>document.querySelector('#review').getAttribute('aria-busy')==='false'");assert '1건' in page.locator('#saved-reviews-link').inner_text()
    with page.context.expect_page() as opened:page.locator('#saved-reviews-link').click()
    history=opened.value;history.wait_for_load_state();history.screenshot(path=str(ROOT/'docs/evidence/saved-review-history.png'),full_page=True)
    with history.expect_download() as downloaded:history.get_by_role('link',name='HTML 내려받기',exact=True).click()
    assert Path(downloaded.value.path()).read_bytes()==saved_bytes
    with history.context.expect_page() as opened:history.get_by_role('link',name='독립검증 결과 보기',exact=True).click()
    restored_result=opened.value;restored_result.wait_for_load_state();assert '수정은 이렇게' in restored_result.locator('.edit-guide').inner_text();assert '버전 1' in restored_result.locator('#report-version-context').inner_text();restored_result.close()
    with w.workflow.connect() as db:
     assert dict(db.execute('SELECT * FROM review_archive WHERE key=?',(key,)).fetchone())==record
     assert tuple(db.execute('SELECT * FROM target_reviews WHERE id=?',(receipt['attempt'],)).fetchone())==source
    assert len(answers)==1 and not errors,errors;browser.close();print('PASS: actual logged-in review button with mocked response -> automatic durable-save receipt -> per-item edit without selection checkbox -> before/after preview -> typed sentence saved and reopened in report version2 -> old report preserved -> logout/server reconstruction/login -> failed later review -> saved-history link and identical HTML download remain available. Stored FAIL not reused as a new PASS. Zero paid API calls.')
  finally:stop(server,thread)
if __name__=='__main__':main()

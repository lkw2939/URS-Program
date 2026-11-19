"""Login -> stored report button -> exact legacy report bytes, no generation or review."""
import sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from report_view_fixtures import seed
ROOT=Path(__file__).resolve().parents[1]
def main():
 with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',side_effect=AssertionError('No API or paid calls allowed')) as network:
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('viewer','fixture-password-123');doc,project,raw,final,target=seed(w)
  with w.workflow.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','target_reviews','ai_usage','documents')}
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('viewer');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='Saved report fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    primary=page.get_by_role('button',name='최종 보고서 보기(사진 포함)',exact=True);primary.wait_for();assert primary.count()==1;assert page.get_by_role('button',name='HTML 확인',exact=True).count()==0
    assert not page.locator('#html-files').evaluate('(e)=>e.open');assert page.locator('#final-html').is_hidden() and page.locator('#raw-html').is_hidden()
    assert 'report.html' in page.locator('#report-file-identity').inner_text() and '버전 1' in page.locator('#report-file-identity').inner_text();assert '사진 데이터 3개' in page.locator('#report-photo-facts').inner_text();assert '숨김 CSS' in page.locator('#report-photo-facts').inner_text()
    page.locator('#html-access').screenshot(path=str(ROOT/'docs/evidence/staff-report-primary.png'))
    primary.click();frame=page.frame_locator('#report-preview');frame.locator('#page-23').wait_for()
    src=page.locator('#report-preview').get_attribute('src');assert src==f'/api/documents/{doc}/report.html?revision=1';assert page.request.get(f'http://127.0.0.1:{server.server_port}'+src).body()==final
    rows=[]
    for n in [9,23]:
     frame.locator('#page-'+str(n)).scroll_into_view_if_needed();items=frame.locator('#page-'+str(n)+' img').evaluate_all('xs=>xs.map(i=>({embedded:i.src.startsWith("data:image/"),display:getComputedStyle(i).display,width:i.getBoundingClientRect().width}))');rows.extend(items);assert len(items)==(1 if n==9 else 2);assert all(i['embedded'] and i['display']=='none' and i['width']==0 for i in items)
    page.locator('#report-preview').screenshot(path=str(ROOT/'docs/evidence/staff-report-hidden-page23.png'))
    # Return focus from the sandboxed document before testing its parent disclosure.
    page.locator('#html-files summary').evaluate('(e)=>{e.scrollIntoView({block:"center",behavior:"instant"});e.focus({preventScroll:true})}');page.locator('#html-files summary').press('Enter');page.wait_for_function("() => document.querySelector('#html-files').open");assert '다른 파일' in page.locator('#html-files').inner_text()
    with page.expect_download() as download:page.locator('#final-html').click()
    assert Path(download.value.path()).read_bytes()==final
    with page.expect_download() as download:page.locator('#raw-html').click()
    assert Path(download.value.path()).read_bytes()==raw;assert raw!=final;assert page.locator('#final-html').get_attribute('href')==src
    guide=page.locator('#verification-guide').inner_text();assert '저장 보고서 확인됨' in guide and 'NEEDS_REVIEW' in guide and '실행 가능 상태는 PASS와 다릅니다' in guide;assert '고객 답변·근거를 저장하는 전용 입력칸이 없습니다' in guide;assert '번역 문구 수정칸에서 고치지 않습니다' in guide
    page.locator('#verification-guide').screenshot(path=str(ROOT/'docs/evidence/staff-report-pass-guide.png'))
    with page.context.expect_page() as opened:page.get_by_role('button',name='독립검증 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();assert result.locator('.finding.error textarea').count()==2;assert result.locator('.finding.review textarea,.finding.program textarea').count()==0;assert result.locator('#corrected-report').is_hidden();assert '버전 1' in result.locator('#verified-report').inner_text();assert not errors,errors
    # New static UI with an older server response must not claim the saved report is absent.
    def older_api(route):
     response=route.fetch();data=response.json();data.pop('staff_report',None);route.fulfill(response=response,json=data)
    page.route('**/api/documents/*/detail',older_api);page.reload();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='Saved report fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click();page.wait_for_function("() => document.querySelector('#report-photo-facts').textContent.includes('새 사진 진단 정보')");assert 'report.html' in page.locator('#report-file-identity').inner_text();assert '저장 보고서는 있습니다' in page.locator('#report-photo-facts').inner_text();assert page.get_by_role('button',name='최종 보고서 보기(사진 포함)',exact=True).is_enabled();b.close()
   with w.workflow.connect() as db:assert before=={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
   network.assert_not_called();print('PASS: existing-history-only login -> one primary employee report button -> report.html revision1 exact bytes; page9 diagram and page23 photos are embedded but CSS-hidden in legacy fixture; final download matches preview, raw download differs and all secondary files are in closed details; can-run vs NEEDS_REVIEW separated, customer-recording gap disclosed, program issues excluded from translation fields; artifacts/results unchanged; generation/review/API calls=0.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

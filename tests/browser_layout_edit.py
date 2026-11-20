"""Logged-in CSS button -> model mock -> append-only version -> real preview/download."""
import sys,tempfile,threading
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
from urs.workspace import Workspace
from urs.web import make_app
ROOT=Path(__file__).resolve().parents[1]
def main():
 with tempfile.TemporaryDirectory() as tmp:
  w=Workspace(Path(tmp)/'t.sqlite');w.add_user('a','fixture-password-123');project=w.create_project('a','Layout fixture');doc=w.upload('a',project,'source.pdf',visual_pdf());w.save_report_settings('a',PROMPT);provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));w.processing.provider=provider;w.run('a',doc,'report');old=w.report_html('a',doc,revision=1);calls=[]
  def refine(*args):calls.append(args);return args[4].replace('margin: 23px','margin: 25px')
  provider.refine_report_html=refine;server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('a');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.get_by_role('button',name='Layout fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click();page.wait_for_function("()=>document.querySelector('#review').getAttribute('aria-busy')==='false'")
    assert not page.locator('#technical-details').evaluate('(e)=>e.open');page.locator('#layout-options > summary').click();page.locator('#layout-notes').fill('여백을 25px로 다듬어 주세요.');page.locator('#edit-layout').click();page.wait_for_function("()=>document.querySelector('#layout-edit-state').textContent.includes('새 버전 2')",timeout=60000);assert len(calls)==1 and calls[0][5]['employee_layout_request']=='여백을 25px로 다듬어 주세요.'
    assert len(provider.calls)==1;assert w.report_html('a',doc,revision=1)==old;new=w.report_html('a',doc,revision=2);assert b'margin: 25px' in new
    assert page.locator('#layout-edited-report').is_visible();assert 'revision=2' in page.locator('#layout-edited-report').get_attribute('href')
    with page.context.expect_page() as result:page.locator('#layout-edited-report').click()
    opened=result.value;opened.wait_for_load_state();assert opened.locator('img').count()==3;opened.close()
    page.locator('#view-html').click();frame=page.frame_locator('#report-preview');frame.locator('h1').wait_for();assert 'revision=2' in page.locator('#report-preview').get_attribute('src');assert frame.locator('img').count()==3
    page.locator('#html-files summary').focus();page.locator('#html-files summary').press('Enter')
    with page.expect_download() as dl:page.locator('#final-html').focus();page.locator('#final-html').press('Enter')
    assert Path(dl.value.path()).read_bytes()==new;page.locator('#html-files summary').focus();page.locator('#html-files summary').press('Enter');page.locator('#layout-options > summary').click();page.locator('#html-access').screenshot(path=str(ROOT/'docs/evidence/layout-editor.png'));b.close();print('PASS: logged-in CSS edit button -> one mock layout API -> preserved text/photos -> new version2 -> preview/download exact saved bytes; version1 retained; no generation/reverification/paid calls; technical details collapsed.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

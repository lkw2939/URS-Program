"""Stored/current/previous/absent HTML browser flow, fixture data only."""
from pathlib import Path
import sys,tempfile,threading
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.ai import AIError
from urs.workspace import Workspace
from urs.web import make_app
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',side_effect=AssertionError('Paid API disabled')):
        w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123')
        project=w.create_project('fixture','Stored HTML browser fixture')
        doc=w.upload('fixture',project,'fixture.pdf',visual_pdf());w.save_report_settings('fixture',PROMPT)
        provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));w.processing.provider=provider
        server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        out=ROOT/'docs/evidence'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1280,'height':960});errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123')
                page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible')
                def open_review():
                    page.get_by_role('button',name='Stored HTML browser fixture',exact=True).click()
                    page.get_by_role('button',name='보고서 검토',exact=True).click()
                    page.locator('#html-availability').wait_for(state='visible')
                open_review()
                assert page.get_by_role('button',name='HTML 확인',exact=True).is_disabled()
                assert page.locator('#html-availability').inner_text()=='아직 열 수 있는 완성 HTML이 없습니다'
                page.screenshot(path=str(out/'saved-html-none.png'),full_page=True)
                w.run('fixture',doc,'report');current=w.report_html('fixture',doc,revision=1)
                page.reload();page.locator('#workspace').wait_for(state='visible');open_review()
                assert page.get_by_role('button',name='HTML 확인',exact=True).is_enabled()
                page.get_by_role('button',name='HTML 확인',exact=True).click()
                assert 'revision=1' in page.locator('#report-preview').get_attribute('src')
                page.frame_locator('#report-preview').locator('h1').wait_for()
                page.locator('#html-access').scroll_into_view_if_needed();page.screenshot(path=str(out/'saved-html-current.png'),full_page=True)
                class Failure:
                    def report_html(self,*args):raise AIError('출력 토큰 한도(16,000)에 도달했습니다.')
                w.processing.provider=Failure();w.run('fixture',doc,'report')
                page.reload();page.locator('#workspace').wait_for(state='visible');open_review()
                button=page.get_by_role('button',name='이전 보고서 보기',exact=True)
                assert button.is_enabled();assert '최신 결과가 아닙니다' in page.locator('#html-availability').inner_text()
                assert '16,000' in page.locator('#html-failure').inner_text()
                assert page.locator('#html-result').is_hidden();assert page.locator('#approval-panel').is_hidden()
                button.click();page.frame_locator('#report-preview').locator('h1').wait_for()
                assert 'revision=1' in page.locator('#final-html').get_attribute('href')
                assert 'revision=1' in page.locator('#raw-html').get_attribute('href')
                with page.expect_download() as download:page.locator('#final-html').click()
                assert Path(download.value.path()).read_bytes()==current
                with page.expect_download() as download:page.locator('#raw-html').click()
                assert Path(download.value.path()).read_bytes()==provider.raw.encode()
                page.locator('#html-access').scroll_into_view_if_needed();page.screenshot(path=str(out/'saved-html-previous.png'),full_page=True)
                assert w.report_html('fixture',doc,revision=1)==current
                assert len(provider.calls)==1,'Read/reload/download must never generate a report'
                assert not errors,errors
                browser.close()
                print('PASS: no-result message; current HTML opens before verification/approval; failed regeneration shows failure and explicitly previous revision; previous final/raw downloads match saved bytes; no auto generation or paid calls.')
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':main()

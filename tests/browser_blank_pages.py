"""Actual browser blank-page confirmation, without any live AI transport."""
import secrets
import sys
import tempfile
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from test_blank_pages import with_blank,NoVision
from urs.workspace import Workspace
from urs.web import make_app


def main():
    with tempfile.TemporaryDirectory() as folder:
        w=Workspace(Path(folder)/'browser.sqlite');password=secrets.token_urlsafe(24)
        w.add_user('blank-test',password);provider=NoVision();w.processing.provider=provider
        server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1360,'height':960});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.get_by_label('직원 ID').fill('blank-test');page.get_by_label('비밀번호',exact=True).fill(password)
                page.get_by_role('button',name='로그인',exact=True).click()
                page.get_by_label('새 프로젝트 이름').fill('합성 빈 페이지 검증')
                page.get_by_role('button',name='프로젝트 만들기').click()
                page.get_by_label('고객 원본 PDF',exact=True).set_input_files({'name':'blank-sample.pdf','mimeType':'application/pdf','buffer':with_blank()})
                page.get_by_role('button',name='원본 등록',exact=True).click()
                page.get_by_role('button',name='원문·번역 검토',exact=True).click()
                page.get_by_role('button',name='추출 실행',exact=True).click()
                page.locator('#check-results').get_by_text('추출 · NEEDS_REVIEW',exact=False).wait_for()
                page.locator('#source-review summary').click()
                for check in page.locator('#page-checks input[data-reviewed-page]').all():check.check()
                page.locator('#source-note').fill('원본 3페이지 모두 확인: 마지막 페이지에 문자·그림·도형 없음')
                page.get_by_role('button',name='원문 대조 기록 · 다음 단계 준비',exact=True).click()
                page.locator('#message').get_by_text('요청을 확인해 주세요.',exact=False).wait_for()
                page.locator('#page-checks input[data-blank-page]').check()
                page.get_by_role('button',name='원문 대조 기록 · 다음 단계 준비',exact=True).click()
                page.get_by_role('heading',name='blank-sample.pdf · 리비전 2',exact=True).wait_for()
                page.locator('#check-results').get_by_text('추출 · PASS',exact=False).wait_for()
                page.locator('#page-select').select_option('3')
                page.get_by_text('원본 대조로 확인한 빈 페이지입니다. 원본 이미지는 그대로 보관합니다.',exact=True).wait_for()
                assert provider.calls==0
                assert not errors,errors
                path=Path(__file__).resolve().parents[1]/'docs/evidence/blank-page-review.png'
                page.screenshot(path=str(path),full_page=True)
                browser.close()
                print('PASS: Chromium rejects unconfirmed blank page, accepts explicit blank confirmation, preserves original page preview; no AI calls and no page errors.')
        finally:
            server.shutdown();thread.join();server.server_close()


if __name__=='__main__':main()

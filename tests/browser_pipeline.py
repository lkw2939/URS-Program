"""Browser acceptance for PDF -> model HTML -> source-image address binding."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from html_fixtures import ReportAI,visual_pdf,PROMPT,RAW
from urs.workspace import Workspace
from urs.web import make_app

ROOT=Path(__file__).resolve().parents[1]
def main():
    evidence=ROOT/'docs/evidence';evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory,patch('urllib.request.urlopen',side_effect=AssertionError('Paid/network API disabled in browser test')):
        workspace=Workspace(Path(directory)/'synthetic.sqlite')
        password='synthetic-browser-password-123'
        workspace.add_user('browser-fixture',password)
        provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'))
        workspace.processing.provider=provider
        server=make_app(workspace,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1080});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                assert '추출' not in page.locator('body').inner_text()
                page.get_by_label('직원 ID').fill('browser-fixture');page.get_by_label('비밀번호',exact=True).fill(password)
                page.get_by_role('button',name='로그인',exact=True).click()
                page.locator('#workspace').wait_for(state='visible')
                page.locator('#report-settings summary').click()
                page.locator('#report-prompt').fill(PROMPT)
                page.get_by_role('button',name='프롬프트 저장',exact=True).click()
                page.wait_for_function("document.getElementById('prompt-version').textContent.includes('1')")
                page.get_by_label('새 프로젝트 이름').fill('HTML 생성 검증 · 합성 자료')
                page.get_by_role('button',name='프로젝트 만들기').click()
                page.get_by_label('고객 원본 PDF',exact=True).set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':visual_pdf()})
                page.get_by_role('button',name='원본 등록',exact=True).click()
                page.get_by_role('button',name='보고서 검토',exact=True).click()
                page.get_by_role('button',name='보고서 생성',exact=True).click()
                page.locator('#html-result').wait_for(state='visible')
                frame=page.frame_locator('#report-preview')
                frame.locator('h1').wait_for()
                assert frame.locator('h1').inner_text()=='모델 제목 & 원문'
                assert frame.locator('figcaption').inner_text()=='모델 캡션 B'
                assert frame.locator('img').count()==3
                assert frame.locator('img').evaluate_all('(xs)=>xs.every(x=>x.complete && x.naturalWidth>0)')
                assert frame.locator('body').evaluate('(e)=>getComputedStyle(e).marginTop')=='23px'
                assert '추출' not in page.locator('#workspace').inner_text()+page.locator('#review').inner_text()
                assert page.locator('#checklist-steps li').count()==5
                assert page.get_by_role('button',name='현재 리비전 최종 승인').is_disabled()
                for label,stage in [('독립 검증 실행','verify'),('기술 분석 실행','analyze')]:
                    page.get_by_role('button',name=label,exact=True).click()
                    page.wait_for_function("([stage])=>[...document.querySelectorAll('#check-results .result')].some(x=>x.textContent.includes(stage+' · PASS'))",arg=[{'verify':'독립 검증','analyze':'기술 분석'}[stage]])
                assert workspace.report_settings('browser-fixture')['prompt']==PROMPT
                assert [c[0] for c in provider.calls]==['report','independent_verify','technical_analysis']
                doc=workspace.documents('browser-fixture',workspace.projects('browser-fixture')[0]['id'])[0]['id']
                before=workspace.report_html('browser-fixture',doc)
                page.locator('#report-settings summary').click()
                page.locator('#html-result').scroll_into_view_if_needed()
                page.screenshot(path=str(evidence/'html-report-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(evidence/'html-report-mobile.png'),full_page=True)
                page.reload();page.locator('#workspace').wait_for(state='visible')
                assert len(provider.calls)==3,'Reload must never regenerate reports'
                assert workspace.report_html('browser-fixture',doc)==before
                assert not errors,errors
                browser.close()
                print('PASS: login, verbatim prompt saving, original PDF upload, report generation, sandboxed final HTML with 3 original crops, model CSS/caption retained, 5 stages with no text extraction, separate verification/analysis, blocked unqualified approval, responsive desktop/mobile, reload preserves output; no paid API calls.')
        finally:
            server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

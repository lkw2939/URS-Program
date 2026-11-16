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
        client_controls='<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script><section><label>원본 PDF 선택<input id="local-pdf" type="file" accept="application/pdf"></label><p id="file-proof"></p><canvas id="local-render"></canvas></section><script>\ntry { void parent.document.body; document.body.dataset.parentAccess=\'allowed\'; } catch(e) { document.body.dataset.parentAccess=\'blocked\'; }\ndocument.getElementById(\'local-pdf\').addEventListener(\'change\',async function(){\nconst bytes=new Uint8Array(await this.files[0].arrayBuffer()); const proof=document.getElementById(\'file-proof\');\nproof.textContent=new TextDecoder().decode(bytes.slice(0,5)); proof.dataset.bytes=String(bytes.length);\npdfjsLib.GlobalWorkerOptions.workerSrc=\'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js\';\ntry { const task=pdfjsLib.getDocument({data:bytes}); const pdf=await task.promise; const first=await pdf.getPage(1); const viewport=first.getViewport({scale:1});\nconst canvas=document.getElementById(\'local-render\'); canvas.width=viewport.width; canvas.height=viewport.height;\nawait first.render({canvasContext:canvas.getContext(\'2d\'),viewport}).promise; proof.dataset.pages=String(pdf.numPages); } catch(e) { proof.dataset.error=String(e); throw e; }\n});\n</script>'
        provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</body>',client_controls+'</body>'))
        workspace.processing.provider=provider
        server=make_app(workspace,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1080},reduced_motion='reduce');errors=[]
                def pdfjs_asset(route):
                    name=route.request.url.rsplit('/',1)[-1]
                    route.fulfill(status=200,content_type='text/javascript',headers={'Access-Control-Allow-Origin':'*'},body=(ROOT/'tests/vendor/pdfjs'/name).read_bytes())
                page.context.route('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/*',pdfjs_asset)
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                assert '추출' not in page.locator('body').inner_text()
                page.get_by_label('직원 ID').fill('browser-fixture');page.get_by_label('비밀번호',exact=True).fill(password)
                page.get_by_role('button',name='로그인',exact=True).click()
                page.locator('#workspace').wait_for(state='visible')
                page.locator('#report-settings summary').click()
                page.locator('#report-prompt').fill(PROMPT)
                page.get_by_role('button',name='프롬프트 저장',exact=True).click()
                page.wait_for_function("() => document.getElementById('prompt-version').textContent.includes('1')")
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
                assert frame.locator('body').get_attribute('data-parent-access')=='blocked'
                requests=[]
                page.on('request',lambda request:requests.append(request.method))
                fixture_pdf=visual_pdf()
                page.locator('#report-preview').scroll_into_view_if_needed()
                frame.locator('#local-pdf').scroll_into_view_if_needed()
                frame.locator('#local-pdf').set_input_files({'name':'local-only.pdf','mimeType':'application/pdf','buffer':fixture_pdf})
                frame.locator('#file-proof').filter(has_text='%PDF-').wait_for()
                frame.locator('#file-proof[data-error], #file-proof[data-pages]').wait_for(state='visible',timeout=15000)
                assert frame.locator('#file-proof').get_attribute('data-error') is None, (frame.locator('#file-proof').get_attribute('data-error'),errors)
                assert frame.locator('#file-proof').get_attribute('data-pages')=='1'
                assert frame.locator('#file-proof').get_attribute('data-bytes')==str(len(fixture_pdf))
                assert frame.locator('#local-render').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(70,150,1,1).data).slice(0,3)')==[255,0,0]
                assert frame.locator('#local-render').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(270,150,1,1).data).slice(0,3)')==[0,0,255]
                assert 'POST' not in requests,'Report file selection must stay in the browser'
                assert '추출' not in page.locator('#workspace').inner_text()+page.locator('#review').inner_text()
                assert page.locator('#checklist-steps li').count()==5
                assert page.get_by_role('button',name='현재 리비전 최종 승인').is_disabled()
                for label,stage in [('독립 검증 실행','verify'),('기술 분석 실행','analyze')]:
                    control=page.get_by_role('button',name=label,exact=True)
                    control.focus()
                    control.press('Enter')
                    try:
                        page.wait_for_function("([stage])=>[...document.querySelectorAll('#check-results .result')].some(x=>x.textContent.includes(stage+' · PASS'))",arg=[{'verify':'독립 검증','analyze':'기술 분석'}[stage]],timeout=5000)
                    except Exception:
                        print('UI ERROR:',page.locator('#message').inner_text(),page.locator('#check-results').inner_text(),flush=True)
                        raise
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
                print('PASS: login, verbatim prompt saving, original PDF upload, report generation, sandboxed final HTML with 3 original crops, model CSS/caption retained, 5 stages with no text extraction, separate verification/analysis, blocked unqualified approval, responsive desktop/mobile, reload preserves output, sandboxed inline scripts and local PDF File API and real PDF.js page rendering work without upload and parent access remains blocked; no paid API calls.')
        finally:
            server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

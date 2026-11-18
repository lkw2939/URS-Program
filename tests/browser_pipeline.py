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
    with patch('urs.costing.count_input_tokens',return_value=12000),patch.dict('os.environ',{'URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'},clear=False),tempfile.TemporaryDirectory() as directory,patch('urllib.request.urlopen',side_effect=AssertionError('Paid/network API disabled in browser test')):
        workspace=Workspace(Path(directory)/'synthetic.sqlite')
        password='synthetic-browser-password-123'
        workspace.add_user('browser-fixture',password)
        probe="<script>try { void parent.document.body; document.body.dataset.parentAccess='allowed'; } catch(e) { document.body.dataset.parentAccess='blocked'; }</script>"
        provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</body>',probe+'</body>'))
        workspace.processing.provider=provider
        server=make_app(workspace,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1080},reduced_motion='reduce');errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                assert '추출' not in page.locator('body').inner_text()
                page.get_by_label('직원 ID').fill('browser-fixture');page.get_by_label('비밀번호',exact=True).fill(password)
                page.get_by_role('button',name='로그인',exact=True).click()
                page.locator('#workspace').wait_for(state='visible')
                page.locator('#ai-model').fill('fixture-terra')
                page.locator('#ai-effort').select_option('xhigh')
                page.get_by_role('button',name='32,000',exact=True).click()
                page.get_by_role('button',name='AI 설정 저장',exact=True).click()
                page.wait_for_function("() => document.getElementById('ai-settings-summary').textContent.includes('저장 버전 1')")
                assert workspace.ai_settings('browser-fixture')['max_output_tokens']==32000
                assert workspace.ai_settings('browser-fixture')['model']=='fixture-terra'
                assert provider.calls==[],'Saving settings must not invoke AI'
                page.locator('#report-settings summary').click()
                page.locator('#report-prompt').fill(PROMPT)
                page.get_by_role('button',name='프롬프트 저장',exact=True).click()
                page.wait_for_function("() => document.getElementById('prompt-version').textContent.includes('1')")
                page.get_by_label('새 프로젝트 이름').fill('HTML 생성 검증 · 합성 자료')
                page.get_by_role('button',name='프로젝트 만들기').click()
                page.get_by_label('고객 원본 PDF',exact=True).set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':visual_pdf()})
                page.get_by_role('button',name='원본 등록',exact=True).click()
                page.get_by_role('button',name='보고서 검토',exact=True).click()
                page.get_by_role('button',name='HTML 보고서 비용 확인 (무료)',exact=True).click();page.wait_for_function("() => ![...document.querySelectorAll('#process-buttons button')].find(b=>b.textContent==='보고서 생성').disabled");page.get_by_role('button',name='보고서 생성',exact=True).click()
                page.get_by_role('button',name='HTML 확인',exact=True).click()
                page.locator('#html-result').wait_for(state='visible')
                frame=page.frame_locator('#report-preview')
                frame.locator('h1').wait_for()
                assert frame.locator('h1').inner_text()=='모델 제목 & 원문'
                assert frame.locator('figcaption').inner_text()=='모델 캡션 B'
                assert frame.locator('img').count()==3
                assert frame.locator('img').evaluate_all('(xs)=>xs.every(x=>x.complete && x.naturalWidth>0)')
                assert frame.locator('body').evaluate('(e)=>getComputedStyle(e).marginTop')=='23px'
                assert frame.locator('body').get_attribute('data-parent-access')=='blocked'
                assert frame.locator('input[type=file]').count()==0
                assert frame.locator('script[src]').count()==0
                assert frame.locator('img').evaluate_all("(xs)=>xs.every(i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility==='visible'&&Number(s.opacity)>0})")
                colors=frame.locator('img').evaluate_all("xs=>xs.map(i=>{const c=document.createElement('canvas');c.width=c.height=1;const x=c.getContext('2d');x.drawImage(i,0,0,1,1);return [...x.getImageData(0,0,1,1).data].slice(0,3)})")
                assert colors==[[0,0,255],[255,0,0],[255,0,0]],colors
                assert '추출' not in page.locator('#workspace').inner_text()+page.locator('#review').inner_text()
                assert page.locator('#checklist-steps li').count()==5
                assert page.get_by_role('button',name='현재 리비전 최종 승인').is_disabled()
                for label,stage in [('독립 검증 실행','verify'),('기술 분석 실행','analyze')]:
                    with page.expect_response(lambda r:r.url.endswith('/cost-preview')) as response:
                        page.get_by_role('button',name=label.replace(' 실행',' 비용 확인 (무료)'),exact=True).focus();page.get_by_role('button',name=label.replace(' 실행',' 비용 확인 (무료)'),exact=True).press('Enter')
                    assert response.value.status==200 and response.value.json()['status']=='READY'
                    try:page.wait_for_function("([label])=>![...document.querySelectorAll('#process-buttons button')].find(b=>b.textContent===label).disabled",arg=[label],timeout=5000)
                    except Exception:
                        print('COST UI:',page.locator('#message').inner_text(),page.locator('#process-buttons').inner_text(),flush=True)
                        raise
                    control=page.get_by_role('button',name=label,exact=True)
                    control.focus()
                    control.press('Enter')
                    try:
                        page.wait_for_function("([stage])=>[...document.querySelectorAll('#check-results .result')].some(x=>x.textContent.includes(stage+' · PASS'))",arg=[{'verify':'독립 검증','analyze':'기술 분석'}[stage]],timeout=5000)
                    except Exception:
                        print('UI ERROR:',page.locator('#message').inner_text(),page.locator('#process-buttons').inner_text(),page.locator('#check-results').inner_text(),flush=True)
                        raise
                assert workspace.report_settings('browser-fixture')['prompt']==PROMPT
                assert [c[0] for c in provider.calls]==['report','independent_verify','technical_analysis']
                doc=workspace.documents('browser-fixture',workspace.projects('browser-fixture')[0]['id'])[0]['id']
                before=workspace.report_html('browser-fixture',doc)
                metadata=workspace.artifact('browser-fixture',doc,'report-metadata')
                assert metadata['model']=='fixture-terra' and metadata['max_output_tokens']==32000 and metadata['reasoning_effort']=='xhigh'
                page.locator('#report-settings summary').click()
                page.locator('#html-result').scroll_into_view_if_needed()
                page.screenshot(path=str(evidence/'html-report-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate("() => ({w:innerWidth,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth,items:[...document.querySelectorAll('body *')].filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>({tag:e.tagName,id:e.id,sw:e.scrollWidth,cw:e.clientWidth,vis:getComputedStyle(e).display,text:e.textContent.slice(0,70)})).slice(0,20)})")
                page.screenshot(path=str(evidence/'html-report-mobile.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1080})
                page.locator('#ai-settings').scroll_into_view_if_needed()
                page.screenshot(path=str(evidence/'ai-settings-desktop.png'),full_page=False)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.locator('body *').evaluate_all('(xs)=>xs.filter(x=>x.getBoundingClientRect().right>innerWidth+.1).slice(0,15).map(x=>({tag:x.tagName,id:x.id,right:x.getBoundingClientRect().right,scroll:x.scrollWidth,width:x.getBoundingClientRect().width,text:x.textContent.slice(0,50)}))')
                page.screenshot(path=str(evidence/'ai-settings-mobile.png'),full_page=False)
                page.reload();page.locator('#workspace').wait_for(state='visible')
                page.wait_for_function("() => document.getElementById('ai-output-tokens').value==='32000'")
                assert page.locator('#ai-model').input_value()=='fixture-terra'
                assert page.locator('#ai-effort').input_value()=='xhigh'
                assert len(provider.calls)==3,'Reload must never regenerate reports'
                assert workspace.report_html('browser-fixture',doc)==before
                assert not errors,errors
                browser.close()
                print('PASS: login, employee model/effort/output settings UI and presets, persistence across reload and no call on save, verbatim prompt saving, original PDF upload, report generation, sandboxed final HTML with 3 original crops, model CSS/caption retained, 5 stages with no text extraction, separate verification/analysis, blocked unqualified approval, responsive desktop/mobile, reload preserves output, HTML 확인 opens visible original photos without PDF reselection/PDF.js; rendered image pixels and parent sandbox isolation checked; no paid API calls.')
        finally:
            server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

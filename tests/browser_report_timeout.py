"""Login/button -> actual adapter with wire interception. No paid network."""
import io,json,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from html_fixtures import RAW,PROMPT,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
def main():
    env={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'mock-terra','URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
    calls=[]
    def mock(req,**kwargs):
        calls.append((json.loads(req.data),kwargs))
        body=io.BytesIO(json.dumps({'status':'completed','output':[{'content':[{'type':'output_text','text':RAW.replace('src=urs-image:9:8','src=urs-image:1:1')}]}]}).encode());body.status=200;return body
    with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True),patch('urllib.request.urlopen',side_effect=mock):
        w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');p=w.create_project('fixture','Mock timeout audit')
        doc=w.upload('fixture',p,'fixture.pdf',visual_pdf());w.save_report_settings('fixture',PROMPT)
        server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':960})
                page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible')
                page.locator('#ai-output-tokens').fill('16000');page.get_by_role('button',name='AI 설정 저장',exact=True).click();page.wait_for_function("() => document.querySelector('#ai-settings-summary').textContent.includes('저장 버전')")
                page.locator('#report-timeout').fill('900');page.get_by_role('button',name='대기시간 저장',exact=True).click();page.wait_for_function("() => document.querySelector('#timeout-summary').textContent.includes('900초')")
                assert calls==[]
                page.locator('#save-report-timeout').screenshot(path=str(ROOT/'docs/evidence/report-timeout-settings.png'))
                page.get_by_role('button',name='Mock timeout audit',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click();page.get_by_role('button',name='보고서 생성',exact=True).click();page.frame_locator('#report-preview').locator('h1').wait_for(timeout=10000)
                assert len(calls)==1 and calls[0][0]['max_output_tokens']==16000 and calls[0][1]['timeout']==900
                assert calls[0][0]['input'][0]['content'][1]['text']==PROMPT
                assert w.report_timeout('fixture')['timeout_seconds']==900
                b.close();print('PASS: actual browser button -> asynchronous HTTP -> real OpenAI adapter -> mock wire max_output_tokens=16000, timeout=900; prompt exact; no API call on settings save; paid calls=0')
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

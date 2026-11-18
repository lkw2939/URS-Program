"""Register/select an A4 target with failed r2, without regenerating anything."""
import sys,tempfile,threading,json
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
def main(a4_payload=None,pdf_payload=None,raw_payload=None):
 with patch('urs.costing.count_input_tokens',return_value=12000),patch.dict('os.environ',{'URS_OPENAI_MODEL':'fixture-model','URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'},clear=False),tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'URS_OPENAI_MODEL':'fixture-model','URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}),patch('urllib.request.urlopen',side_effect=AssertionError('Paid API forbidden')):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');p=w.create_project('fixture','A4 registration fixture');doc=w.upload('fixture',p,'source.pdf',pdf_payload if pdf_payload is not None else visual_pdf());w.save_report_settings('fixture',PROMPT)
  provider=ReportAI((raw_payload if raw_payload is not None else RAW).replace('src=urs-image:9:8','src=urs-image:1:1'));w.processing.provider=provider;w.run('fixture',doc,'report')
  with w.workflow.connect() as db:
   job=w.workflow._job(db,doc);content=json.loads(job['content']);content['revision']=2;db.execute('UPDATE jobs SET revision=2,content=? WHERE id=?',(json.dumps(content),doc))
   before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','events','approvals','jobs','documents','report_settings','ai_usage')}
  a4=a4_payload if a4_payload is not None else b'<!doctype html><html lang="ko"><body><h1>A4 registered copy</h1></body></html>'
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});page.goto(f'http://127.0.0.1:{server.server_port}')
    page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='A4 registration fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    page.locator('#advanced-targets > summary').click()
    page.locator('#a4-import-options summary').click()
    page.locator('#a4-parent').select_option('1');page.locator('#a4-file').set_input_files({'name':'report-a4.html','mimeType':'text/html','buffer':a4});page.get_by_role('button',name='A4 검증 대상 등록',exact=True).click()
    page.wait_for_function("() => document.querySelector('#a4-target-info').textContent.includes('부모 리비전 1')")
    assert '현재 작업 리비전 2와 별도' in page.locator('#a4-target-info').inner_text()
    page.get_by_role('button',name='누적 사용량·정산 이력 (조회만)',exact=True).click();page.locator('#usage-preview').wait_for(state='visible')
    assert '누적 사용량 정산액' in page.locator('#usage-preview').inner_text()
    assert len(provider.calls)==1,'Registration must not call report/review AI'
    with page.expect_download() as download:page.get_by_role('link',name='선택 보고서 HTML 내려받기',exact=True).click()
    assert Path(download.value.path()).read_bytes()==a4
    with w.workflow.connect() as db:assert before=={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
    assert page.get_by_role('button',name='독립 검증 실행',exact=True).is_enabled()
    assert page.get_by_role('button',name='A4 독립검증 실행',exact=True).is_disabled()
    page.get_by_role('button',name='A4 독립검증 비용 확인 (무료)',exact=True).click();page.wait_for_timeout(200)
    assert page.get_by_role('button',name='A4 기술분석 실행',exact=True).is_disabled()
    page.locator('#a4-target-panel').screenshot(path=str(ROOT/'docs/evidence/a4-target-registration.png'))
    page.get_by_role('button',name='A4 독립검증 실행',exact=True).click();page.wait_for_function("() => ![...document.querySelectorAll('#a4-target-results button')][0].disabled")
    page.get_by_role('button',name='A4 기술분석 비용 확인 (무료)',exact=True).click();page.wait_for_timeout(200)
    page.get_by_role('button',name='A4 기술분석 실행',exact=True).click();page.wait_for_function("() => ![...document.querySelectorAll('#a4-target-results button')][1].disabled")
    with page.context.expect_page() as opened:page.get_by_role('button',name='A4 기술분석 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();assert '등록 A4 HTML' in result.locator('body').inner_text();assert '부모 리비전 1' in result.locator('body').inner_text()
    assert len(provider.calls)==3
    for c in provider.calls[1:]:assert c[3]==a4.decode()
    with w.workflow.connect() as db:assert before=={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
    b.close();print('PASS: failed current r2 preserved; r1 parent A4 import/select/download byte-exact and zero AI; separate A4 verify/analyze mock execution and HTML results; raw report/legacy records/budget untouched; paid calls=0.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

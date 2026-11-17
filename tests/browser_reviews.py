"""Actual login/buttons -> HTTP -> production adapter(mock wire) -> DB -> separate HTML tabs."""
import sys,json,io,tempfile,threading,base64
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
def main():
 env={'URS_OPENAI_API_KEY':'MOCK-ONLY','URS_OPENAI_MODEL':'mock-terra','URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');p=w.create_project('fixture','Review fixture');pdf=visual_pdf();doc=w.upload('fixture',p,'fixture.pdf',pdf);w.save_report_settings('fixture',PROMPT)
  w.processing.provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));w.run('fixture',doc,'report');raw=w.processing.get(doc,'report.raw.html');final=w.processing.get(doc,'report.html');w.processing.provider=None
  w.save_ai_settings('fixture',{'model':'mock-terra','effort':None,'max_output_tokens':16000})
  with w.workflow.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','events','approvals','documents','report_settings')}
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();gate=threading.Event();calls=[]
  def mock(req,**kwargs):
   body=json.loads(req.data);content=body['input'][0]['content'];assert base64.b64decode(content[0]['file_data'].split(',')[1])==pdf;assert content[2]['text']==raw.decode();calls.append(body)
   if 'Independently' in content[1]['text']:
    gate.wait(8);result={'status':'PASS','issues':[]}
   else:result={'status':'PASS','issues':[],'sections':[{'page':1,'text':'주요 사양: 합성 치수 120 mm','reason':'원문 사양과 대조','source_en':'120 mm'}],'conflicts':[{'page':1,'text':'조건 A와 조건 B 확인','reason':'동시 충족 여부 확인 필요'}],'questions':[{'page':1,'question_ko':'요구 치수 기준을 확인해 주세요.','reason_ko':'검수 기준을 확정하기 위해 필요합니다.','source_en':'120 mm'}]}
   value=io.BytesIO(json.dumps({'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(result,ensure_ascii=False)}]}]}).encode());value.status=200;return value
  try:
   with patch('urllib.request.urlopen',side_effect=mock),sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible')
    page.get_by_role('button',name='Review fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    assert page.get_by_role('button',name='독립 검증 실행',exact=True).is_enabled();assert page.get_by_role('button',name='기술 분석 실행',exact=True).is_disabled()
    assert '독립검증' in page.locator('#process-buttons').inner_text()
    page.get_by_role('button',name='독립 검증 실행',exact=True).click();page.wait_for_function("() => document.querySelector('#process-buttons').textContent.includes('실행 중')")
    gate.set();page.get_by_role('button',name='독립검증 결과 보기',exact=True).wait_for();page.wait_for_function("() => !document.querySelector('#view-verification').disabled")
    with page.context.expect_page() as opened:page.get_by_role('button',name='독립검증 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();assert '보고서 리비전 1' in result.locator('body').inner_text();assert '독립검증 결과' in result.title();result.screenshot(path=str(ROOT/'docs/evidence/review-verification.png'),full_page=True)
    page.get_by_role('button',name='기술 분석 실행',exact=True).click();page.wait_for_function("() => !document.querySelector('#view-analysis').disabled")
    with page.context.expect_page() as opened:page.get_by_role('button',name='기술분석 결과 보기',exact=True).click()
    analysis=opened.value;analysis.wait_for_load_state();assert '검수 기준을 확정하기 위해 필요합니다' in analysis.locator('body').inner_text();assert '주요 사양' in analysis.locator('body').inner_text();assert '120 mm' in analysis.locator('body').inner_text();assert analysis.locator('pre').count()==0;assert analysis.locator('body').evaluate('(e)=>getComputedStyle(e).maxWidth')=='1000px'
    analysis.screenshot(path=str(ROOT/'docs/evidence/review-analysis.png'),full_page=True)
    page.locator('#review-results').screenshot(path=str(ROOT/'docs/evidence/review-result-buttons.png'))
    assert len(calls)==2;assert w.processing.get(doc,'report.raw.html')==raw and w.processing.get(doc,'report.html')==final
    with w.workflow.connect() as db:
     assert before=={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
     assert db.execute('SELECT COUNT(*) FROM review_attempts WHERE payload IS NOT NULL').fetchone()[0]==2
    assert not errors,errors;b.close();print('PASS: login, actual verify/analyze buttons, explicit analysis prerequisites, running status, async HTTP, real OpenAI adapter(mock network), exact PDF/raw HTML inputs, DB result JSON stored append-only, both separate readable Korean HTML result tabs open, question reasons shown, revision labels, reports/legacy records unchanged, no paid calls.')
  finally:gate.set();server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

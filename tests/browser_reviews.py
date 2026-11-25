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
 with patch('urs.costing.count_input_tokens',return_value=12000),patch.dict('os.environ',{'URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'},clear=False),tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');p=w.create_project('fixture','Review fixture');pdf=visual_pdf();doc=w.upload('fixture',p,'fixture.pdf',pdf);w.save_report_settings('fixture',PROMPT)
  w.processing.provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));w.run('fixture',doc,'report');__import__('urs.targets',fromlist=['run']).run(w,'fixture',doc,f'displayed:{doc}:1','verify');w.processing.provider.refine_report_html=lambda *a:a[4].replace('margin: 23px','margin: 25px');__import__('urs.layout_edit',fromlist=['run']).run(w,'fixture',doc,1,'fixture CSS');raw=w.processing.get(doc,'report.raw.html');final=w.processing.get(doc,'report.html');w.processing.provider=None
  w.save_ai_settings('fixture',{'model':'mock-terra','effort':None,'max_output_tokens':16000})
  with w.workflow.connect() as db:db.execute('INSERT INTO target_reviews(target,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?)',(f'displayed:{doc}:2','verify','failed','FAIL',None,json.dumps({'reason':'OpenAI 검토 응답 대기시간(90초) 초과. 자동 재시도하지 않습니다.'}),'fixture-history'))
  with w.workflow.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('artifacts','results','events','approvals','documents','report_settings')}
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();gate=threading.Event();calls=[]
  def mock(req,**kwargs):
   assert kwargs['timeout'] is None
   body=json.loads(req.data);content=body['input'][0]['content'];assert base64.b64decode(content[0]['file_data'].split(',')[1])==pdf;from urs.costing import review_parts
   from urs.review_policy import customer_context
   findings=customer_context(w,f'displayed:{doc}:2') if 'Independently' not in content[1]['text'] else None
   assert content[1:]==review_parts('independent_verify' if 'Independently' in content[1]['text'] else 'technical_analysis',final.decode(),findings);calls.append(body)
   if 'Independently' in content[1]['text']:
    gate.wait(8);result={'status':'NEEDS_REVIEW','issues':[{'page':1,'issue_type':'customer','severity':'확인 필요','reason':'원문에 두 시험 시간이 있습니다.','question_ko':'시험 시간을 확정해 주세요.'}]}
   else:result={'status':'PASS','issues':[],'sections':[{'page':1,'text':'주요 사양: 합성 치수 120 mm','reason':'원문 사양과 대조','source_en':'120 mm'}],'conflicts':[{'page':1,'text':'조건 A와 조건 B 확인','reason':'동시 충족 여부 확인 필요'}],'questions':[{'page':1,'question_ko':'요구 치수 기준을 확인해 주세요.','reason_ko':'검수 기준을 확정하기 위해 필요합니다.','source_en':'120 mm'}]}
   value=io.BytesIO(json.dumps({'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(result,ensure_ascii=False)}]}]}).encode());value.status=200;return value
  try:
   with patch('urllib.request.urlopen',side_effect=mock),sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});__import__("component_harness").install(page);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible')
    page.get_by_role('button',name='Review fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    assert page.get_by_role('button',name='독립 검증 실행',exact=True).is_enabled();assert page.get_by_role('button',name='기술 분석 실행',exact=True).is_disabled()
    assert '독립검증' in page.locator('#process-buttons').inner_text()
    assert '이전 실행 실패 기록 (당시 90초 제한)' in page.locator('#process-buttons').inner_text()
    page.get_by_role('button',name='독립 검증 비용 확인 (무료)',exact=True).click();page.wait_for_function("() => document.querySelector('#process-buttons').textContent.includes('이번 1회 (설정 단가 기준)')")
    # A stale/different screen identity must be rejected before any model request.
    rejected=page.evaluate('''async (doc) => {const me=await (await fetch('/api/me')).json();const r=await fetch('/api/documents/'+doc+'/current-review-run',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf},body:JSON.stringify({stage:'verify',expected_revision:99,expected_sha256:'wrong'})});return {status:r.status,body:await r.json()};}''',doc)
    assert rejected['status']==409 and not calls,rejected
    page.get_by_role('button',name='독립 검증 실행',exact=True).click();page.wait_for_function("() => document.querySelector('#process-buttons').textContent.includes('실행 중')")
    gate.set();page.get_by_role('button',name='독립검증 결과 보기',exact=True).wait_for();page.wait_for_function("() => !document.querySelector('#view-verification').disabled")
    with page.context.expect_page() as opened:page.get_by_role('button',name='독립검증 결과 보기',exact=True).click()
    result=opened.value;result.wait_for_load_state();assert '보고서 버전 2' in result.locator('header').inner_text();assert '독립검증' in result.title();assert '독립검증 적용 판정: PASS' in result.locator('#verification-verdict').text_content();assert result.locator('.finding:not(.manual)').count()==0;assert '1건' in result.locator('#customer-handoff').inner_text();result.screenshot(path=str(ROOT/'docs/evidence/review-verification.png'),full_page=True)
    page.get_by_role('button',name='기술 분석 비용 확인 (무료)',exact=True).click();page.wait_for_timeout(200)
    page.get_by_role('button',name='기술 분석 실행',exact=True).click();page.wait_for_function("() => !document.querySelector('#view-analysis').disabled")
    page.bring_to_front()
    with page.context.expect_page() as opened:page.get_by_role('button',name='기술분석 결과 보기',exact=True).click()
    analysis=opened.value;analysis.wait_for_load_state();assert '시험 시간을 확정해 주세요.' in analysis.locator('body').inner_text();assert '검수 기준을 확정하기 위해 필요합니다' in analysis.locator('body').inner_text();assert '주요 사양' in analysis.locator('body').inner_text();assert '120 mm' in analysis.locator('body').inner_text();assert analysis.locator('pre').count()==0;assert analysis.locator('body').evaluate('(e)=>getComputedStyle(e).maxWidth')=='1000px'
    analysis.screenshot(path=str(ROOT/'docs/evidence/review-analysis.png'),full_page=True)
    page.locator('#flow-panel-4').screenshot(path=str(ROOT/'docs/evidence/review-result-buttons.png'))
    assert len(calls)==2;assert w.processing.get(doc,'report.raw.html')==raw and w.processing.get(doc,'report.html')==final
    with w.workflow.connect() as db:
     assert before=={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
     assert db.execute('SELECT COUNT(*) FROM target_reviews WHERE payload IS NOT NULL').fetchone()[0]==3
    # Failed new generation must not displace the displayed report or require selection/upload.
    from urs.ai import AIError
    with patch.object(w.processing,'provider_for') as factory:
     factory.return_value.report_html.side_effect=AIError('모의 새 보고서 생성 실패')
     w.run('fixture',doc,'report')
    page.reload();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='Review fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    page.wait_for_function("() => document.querySelector('#review-title').textContent.includes('현재 직원용 보고서 버전 2')")
    assert '현재 직원용 보고서 버전 2' in page.locator('#review-title').inner_text()
    assert '새 생성 실패/미완료로 기존 보고서 유지' in page.locator('#html-availability').inner_text()
    assert 'revision=2' in page.locator('#report-preview').get_attribute('src')
    assert not page.locator('#advanced-targets').evaluate('(e)=>e.open')
    with w.workflow.connect() as db:before_retry={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
    page.get_by_role('button',name='독립 검증 실행',exact=True).click();page.wait_for_function("() => document.querySelector('#message').textContent==='처리를 완료했습니다.'")
    assert len(calls)==3 and w.status('fixture',doc)['revision']==3
    with w.workflow.connect() as db:assert before_retry=={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before_retry}
    page.frame_locator('#report-preview').locator('h1').wait_for()
    page.frame_locator('#report-preview').locator('img').first.wait_for()
    page.locator('#review').screenshot(path=str(ROOT/'docs/evidence/current-report-binding.png'))
    assert not errors,errors;b.close();print('PASS: login, actual verify/analyze buttons, explicit analysis prerequisites, running status, async HTTP, real OpenAI adapter(mock network), exact PDF/displayed final HTML inputs, DB result JSON stored append-only, both separate readable Korean HTML result tabs open, question reasons shown, revision labels, reports/legacy records unchanged, no paid calls.')
  finally:gate.set();server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

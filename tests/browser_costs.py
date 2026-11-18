"""Logged-in preflight -> exact multimodal counter -> mock execution -> settled ledger."""
import sys,json,io,tempfile,threading,base64
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from urs.workspace import Workspace
from urs.web import make_app
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
def main():
 env={'URS_OPENAI_API_KEY':'MOCK-NOT-A-KEY','URS_OPENAI_MODEL':'fixture-model','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
 calls=[]
 def network(req,**kw):
  data=json.loads(req.data);calls.append((req.full_url,data))
  if req.full_url.endswith('/input_tokens'):result={'input_tokens':12000}
  else:result={'status':'completed','usage':{'input_tokens':12000,'output_tokens':400},'output':[{'content':[{'type':'output_text','text':json.dumps({'status':'PASS','issues':[]})}]}]}
  r=io.BytesIO(json.dumps(result).encode());r.status=200;return r
 with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',env,clear=True):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');p=w.create_project('fixture','Cost fixture');doc=w.upload('fixture',p,'source.pdf',visual_pdf());w.save_report_settings('fixture',PROMPT);w.processing.provider=ReportAI(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'));w.run('fixture',doc,'report');w.processing.provider=None;w.save_ai_settings('fixture',{'model':'fixture-model','effort':'high','max_output_tokens':16000})
  with w.workflow.connect() as db:
   for state,amount in [('failed',3),('failed',2),('failed',1.562085),('completed',2.445695)]:db.execute('INSERT INTO ai_usage(document,task,model,reserved,state) VALUES(?,?,?,?,?)',(doc,'old','old-model',amount,state))
   before=[tuple(r) for r in db.execute('SELECT * FROM ai_usage')]
  raw=w.processing.get(doc,'report.raw.html');final=w.processing.get(doc,'report.html');server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with patch('urllib.request.urlopen',side_effect=network),sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=b.new_page(viewport={'width':1280,'height':1000});page.goto(f'http://127.0.0.1:{server.server_port}');page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.get_by_role('button',name='Cost fixture',exact=True).click();page.get_by_role('button',name='보고서 검토',exact=True).click()
    assert not calls;assert page.get_by_role('button',name='독립 검증 실행',exact=True).is_disabled()
    page.get_by_role('button',name='독립 검증 비용 확인 (무료)',exact=True).click();page.wait_for_function("() => ![...document.querySelectorAll('#process-buttons button')].find(b=>b.textContent==='독립 검증 실행').disabled")
    assert len(calls)==1 and calls[0][0].endswith('/input_tokens');assert '예상 상한 $0.092000 / 1회 실행 한도 $10.00' in page.locator('#process-buttons').inner_text()
    with w.workflow.connect() as db:assert before==[tuple(r) for r in db.execute('SELECT * FROM ai_usage')]
    parts=calls[0][1]['input'][0]['content'];assert len([x for x in parts if x['type']=='input_image'])==3;assert 'data:image/' not in parts[2]['text'];assert base64.b64decode(parts[0]['file_data'].split(',')[1])==w.original('fixture',doc)['original']
    page.locator('#process-buttons').screenshot(path=str(ROOT/'docs/evidence/cost-preview.png'))
    page.get_by_role('button',name='독립 검증 실행',exact=True).click();page.wait_for_function("() => !document.querySelector('#view-verification').disabled")
    assert len(calls)==2 and calls[1][0].endswith('/responses');assert calls[0][1]['input']==calls[1][1]['input'];assert calls[1][1]['max_output_tokens']==16000 and calls[1][1]['reasoning']=={'effort':'high'}
    page.get_by_role('button',name='누적 사용량·정산 이력 (조회만)',exact=True).click();page.locator('#usage-preview').wait_for(state='visible');assert '정산 완료' in page.locator('#usage-preview').inner_text();assert '$0.014000' in page.locator('#usage-preview').inner_text();assert '미정산 4건' in page.locator('#usage-preview').inner_text()
    page.locator('#usage-preview').screenshot(path=str(ROOT/'docs/evidence/cost-ledger.png'))
    with w.workflow.connect() as db:assert before==[tuple(r) for r in db.execute('SELECT * FROM ai_usage WHERE id<=4')]
    assert w.processing.get(doc,'report.raw.html')==raw and w.processing.get(doc,'report.html')==final
    b.close();print('PASS: actual login/buttons -> free exact-input count(mock) without inference/ledger reservation -> $0.092000 per-call estimate under $10 despite $9.00778 history -> same multimodal request -> mock usage settlement $0.014000, four unknown legacy calls retained, no report/old-ledger overwrite, paid calls=0.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

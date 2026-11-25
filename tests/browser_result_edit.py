"""Result editing as a user: partial apply -> remaining uncertain/text items -> CSS navigation.
Synthetic PDF/temp DB only; all network AI calls are forbidden.
"""
import sys,io,json,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from pypdf import PdfReader,PdfWriter
from urs.workspace import Workspace
from urs.targets import run,overview
from urs.web import make_app
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
ROOT=Path(__file__).resolve().parents[1]
BEFORE='고객은 반드시 시험합니다.';AFTER='고객의 시험을 권장합니다.';EMAIL='engineer@\u200bexample.test'
def main():
 with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',side_effect=AssertionError('Paid API forbidden')):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','검증 결과 수정 시험')
  writer=PdfWriter();writer.add_page(PdfReader(io.BytesIO(visual_pdf())).pages[0]);writer.add_blank_page(width=400,height=400);out=io.BytesIO();writer.write(out);pdf=out.getvalue();doc=w.upload('fixture',project,'모의 검증 결과.pdf',pdf);w.save_report_settings('fixture',PROMPT)
  raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1').replace('</section>','<p>고객은 <strong>반드시</strong> 시험합니다.</p><p>폼 그리퍼 완제품 5개</p><p>'+EMAIL+'</p></section>');raw=raw.replace('</body>','<section data-urs-page="2"><p>두 번째 원문 쪽 모의 본문</p></section></body>');provider=ReportAI(raw);w.processing.provider=provider;w.run('fixture',doc,'report');old=w.report_html('fixture',doc,revision=1)
  findings=[{'page':1,'severity':'오류','issue_type':'translation','before':BEFORE,'after':AFTER,'reason':'원문은 권장인데 번역이 의무로 바뀌었습니다.'}, {'issue_type':'translation','category':'quantity','needs_confirmation':True,'severity':'확인 필요','title_ko':'폼 그리퍼 수량 해석','before':'폼 그리퍼 완제품 5개','after':'폼 그리퍼 5개 (대상 확인 필요)','reason':'원문은 수량의 대상을 명확히 밝히지 않았습니다.','evidence':[{'page':1,'source_en':'A foam gripper with ejector (5 pieces).'}, {'page':2,'source_en':'Maximum 5 packages.'}]}, {'page':1,'issue_type':'program','severity':'확인 필요','title_ko':'이메일 표시 문자열의 숨은 문자','reason':'이메일 주소 중간에 폭이 없는 문자가 있어 복사한 주소가 달라집니다.','before':EMAIL}]
  target=f'displayed:{doc}:1'
  with patch.object(provider,'review_pdf',return_value={'status':'FAIL','issues':findings}):run(w,'fixture',doc,target,'verify')
  attempt=overview(w,'fixture',doc,target)['reviews']['verify']['attempt']
  with w.workflow.connect() as db:original_review=bytes(db.execute('SELECT CAST(payload AS BLOB) FROM target_reviews WHERE id=?',(attempt,)).fetchone()[0])
  server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    base=f'http://127.0.0.1:{server.server_port}';page.goto(base);page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible');page.goto(base+f'/api/documents/{doc}/target-result.html?target={target}&stage=verify&attempt={attempt}');page.locator('#next-stage').wait_for()
    for ident in ('0','1','2'):assert page.locator(f'[data-issue="{ident}"] [data-select]').count()==1
    page.locator('[data-issue="0"] [data-edit-item]').click();assert page.locator('#next-stage').is_disabled();assert page.locator('[data-issue="0"] [data-before]').evaluate('(e)=>e.getBoundingClientRect().width')>600
    row=page.locator('[data-issue="0"]');row.locator('[data-select]').check();page.locator('#preview-corrections').click();page.locator('#apply-corrections').wait_for(state='visible');page.locator('#apply-corrections').click();page.wait_for_function("()=>document.querySelector('#correction-status').textContent.includes('버전 2')")
    page.wait_for_function("()=>document.querySelector('[data-issue=\"0\"] [data-select]').disabled");assert row.locator('[data-select]').is_disabled();assert page.locator('[data-issue="1"] [data-select]').is_enabled();assert page.locator('[data-issue="2"] [data-select]').is_enabled();assert page.locator('#next-stage').is_disabled()
    uncertain=page.locator('[data-issue="1"]');uncertain.locator('[data-select]').check();uncertain.locator('[data-page]').select_option('1');page.locator('#preview-corrections').click();page.wait_for_function("()=>document.querySelector('#correction-status').textContent.includes('원문 확인')");assert w.status('fixture',doc)['revision']==2
    uncertain.locator('[data-confirm]').check();uncertain.locator('[data-basis]').fill('원문이 수량의 대상을 단정하지 않아 확인 필요 표현을 보존합니다.')
    email=page.locator('[data-issue="2"]');email.locator('[data-select]').check();email.locator('[data-confirm]').check();email.locator('[data-basis]').fill('원문 이메일과 대조하여 주소 중간의 보이지 않는 문자를 제거합니다.');email.locator('[data-clean-invisible]').click();assert email.locator('[data-after]').input_value()=='engineer@example.test'
    page.locator('[data-issue=\"1\"]').scroll_into_view_if_needed();page.screenshot(path=str(ROOT/'docs/evidence/result-edit-remaining.png'));page.locator('#preview-corrections').click();page.locator('#apply-corrections').wait_for(state='visible');page.locator('#apply-corrections').click();page.wait_for_function("()=>document.querySelector('#correction-status').textContent.includes('버전 3')");page.wait_for_function("()=>!document.querySelector('#next-stage').disabled");assert page.locator('#next-stage').is_enabled()
    manual=page.locator('.finding.manual');manual.locator('[data-select]').check();manual.locator('[data-page]').select_option('1');manual.locator('[data-confirm]').check();manual.locator('[data-basis]').fill('원문 그림의 설명을 대조해 직원이 확인한 캡션을 입력합니다.');manual.locator('[data-before]').fill('모델 캡션 B');manual.locator('[data-after]').fill('직원이 확인한 캡션');page.locator('#preview-corrections').click();page.locator('#apply-corrections').wait_for(state='visible');page.locator('#apply-corrections').click();page.wait_for_function("()=>document.querySelector('#correction-status').textContent.includes('버전 4')")
    current=w.report_html('fixture',doc,revision=4).decode();assert EMAIL not in current and 'engineer@example.test' in current;assert '폼 그리퍼 5개 (대상 확인 필요)' in current;assert '직원이 확인한 캡션' in current;assert '<strong>' in current;assert current.count('data:image/')==old.decode().count('data:image/');assert old==w.report_html('fixture',doc,revision=1)
    page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(ROOT/'docs/evidence/result-edit-applied.png'));page.locator('#next-stage').click();page.wait_for_function("()=>document.querySelector('#review')?.dataset.currentStep==='3'&&document.querySelector('#review').getAttribute('aria-busy')==='false'");assert 'step=3' in page.url;assert page.locator('.flow-panel').count()==1;assert page.locator('#layout-editor').is_visible();assert '버전 4' in page.locator('#layout-edit-state').inner_text()
    with w.workflow.connect() as db:assert bytes(db.execute('SELECT CAST(payload AS BLOB) FROM target_reviews WHERE id=?',(attempt,)).fetchone()[0])==original_review
    assert len(provider.calls)==1 and not errors,errors;browser.close();print('PASS: all eligible findings selectable; full-width editors; first apply preserves editable remaining items; source confirmation and basis required; multi-page quantity uncertainty edited without inventing a quantity; invisible email character removed by explicit draft/preview/apply; free text correction saved in version4; prior versions and raw FAIL verdict preserved; result-screen next button opens CSS for current version4. No regeneration or paid API calls.')
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()

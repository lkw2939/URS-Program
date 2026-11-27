"""A short action queue, approved suggested edits, explicit finish state and readable analysis."""
import sys,io,json,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from urs.workspace import Workspace
from urs import targets
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from browser_saved_reviews import start,stop,BEFORE,AFTER
ROOT=Path(__file__).resolve().parents[1]

def main():
 with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',side_effect=AssertionError('Paid API forbidden')):
  w=Workspace(Path(tmp)/'fixture.sqlite');w.add_user('fixture','fixture-password-123');project=w.create_project('fixture','간단 수정 시험');w.save_report_settings('fixture',PROMPT)
  base_raw=RAW.replace('src=urs-image:9:8','src=urs-image:1:1')
  finding={'page':1,'severity':'오류','issue_type':'translation','title_ko':'권장 사항을 의무로 번역했습니다.','before':BEFORE,'after':AFTER,'reason':'원문은 권장 사항입니다. 의무 조건으로 견적하지 않도록 수정합니다.','source_en':'The customer should perform the test.'}
  def fixture(name,extra,items):
   doc=w.upload('fixture',project,name,visual_pdf());provider=ReportAI(base_raw.replace('</section>',extra+'</section>'));w.processing.provider=provider;w.run('fixture',doc,'report');target=f'displayed:{doc}:1'
   with patch.object(provider,'review_pdf',return_value={'status':'FAIL','issues':items}):targets.run(w,'fixture',doc,target,'verify')
   return doc,target,targets.overview(w,'fixture',doc,target)['reviews']['verify']['attempt']
  doc,target,attempt=fixture('모의 간단 수정.pdf','<p>'+BEFORE+'</p>',[finding,{'page':1,'issue_type':'customer','severity':'확인 필요','reason':'원문의 시험 시간 확인 필요','question_ko':'4시간과 2시간 중 어느 시험 기준을 적용하나요?'}]);original=w.report_html('fixture',doc,revision=1)
  duplicate,duplicate_target,duplicate_attempt=fixture('모의 반복 문구.pdf','<p>'+BEFORE+'</p><p>'+BEFORE+'</p>',[finding])
  unknown,unknown_target,unknown_attempt=fixture('모의 수정안 없음.pdf','<p>'+BEFORE+'</p>',[{**finding,'after':''}])
  server,thread,base=start(w)
  try:
   with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);context=b.new_context(viewport={'width':1280,'height':1100});page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base);page.get_by_label('직원 ID').fill('fixture');page.get_by_label('비밀번호',exact=True).fill('fixture-password-123');page.get_by_role('button',name='로그인',exact=True).click();page.locator('#workspace').wait_for(state='visible')
    def open_result(d,t,a):page.goto(base+f'/api/documents/{d}/target-result.html?target={t}&stage=verify&attempt={a}');page.locator('#work-title').wait_for()
    open_result(doc,target,attempt);assert '남은 필수 수정 1개'==page.locator('#work-title').inner_text();assert page.locator('#next-stage').is_disabled()
    card=page.locator('[data-issue="0"]');assert card.locator('[data-recommendation-before]').inner_text()==BEFORE and card.locator('[data-recommendation-after]').inner_text()==AFTER
    assert page.locator('textarea:visible,input[type=checkbox]:visible').count()==0;assert not card.locator('.finding-explanation').evaluate('(e)=>e.open');assert not page.locator('.review-records').evaluate('(e)=>e.open');assert page.locator('#bulk-corrections,[data-select]').count()==0;assert '여러 항목을 함께 저장할 때 선택' not in page.locator('body').text_content()
    assert page.locator('#new-result').is_hidden()
    assert '실제 전송' not in page.locator('body').inner_text() and 'SHA-256' not in page.locator('body').inner_text()
    paragraph=card.locator('[data-recommendation-before]');assert paragraph.evaluate('(e)=>parseFloat(getComputedStyle(e).lineHeight)')>=32;assert paragraph.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')>=16
    card.locator('[data-edit-item]').click();assert card.locator('textarea').first.is_visible();assert page.locator('[data-select],#bulk-corrections').count()==0;card.locator('.proposal').evaluate('(e)=>e.open=false');card.evaluate('(e)=>e.classList.remove("advanced-mode")')
    page.screenshot(path=str(ROOT/'docs/evidence/simple-review-before.png'),full_page=True)
    with w.workflow.connect() as db:old=tuple(db.execute('SELECT * FROM target_reviews WHERE id=?',(attempt,)).fetchone())
    card.locator('[data-use-recommendation]').click();page.wait_for_function("()=>document.querySelector('#work-title').textContent.includes('모두 고쳤습니다')")
    assert page.locator('#next-stage').is_enabled();assert 'CSS로 이동' in page.locator('#next-stage').inner_text();assert page.locator('.finish-rule').count()==0
    assert AFTER.encode() in w.report_html('fixture',doc,revision=2) and BEFORE.encode() not in w.report_html('fixture',doc,revision=2);assert w.report_html('fixture',doc,revision=1)==original
    with w.workflow.connect() as db:assert tuple(db.execute('SELECT * FROM target_reviews WHERE id=?',(attempt,)).fetchone())==old
    page.screenshot(path=str(ROOT/'docs/evidence/simple-review-done.png'),full_page=True);page.locator('#next-stage').click();page.wait_for_function("()=>document.querySelector('#review')?.dataset.currentStep==='3'&&document.querySelector('#review').getAttribute('aria-busy')==='false'");assert '버전 2' in page.locator('#layout-edit-state').inner_text()
    # Duplicate locations and missing proposals must never be silently guessed or marked done.
    open_result(duplicate,duplicate_target,duplicate_attempt);page.locator('[data-use-recommendation]').click();page.wait_for_function("()=>document.querySelector('[data-recommendation-status]').textContent.includes('2곳')");assert w.status('fixture',duplicate)['revision']==1 and page.locator('#next-stage').is_disabled()
    open_result(unknown,unknown_target,unknown_attempt);assert page.locator('[data-use-recommendation]').count()==0;assert page.locator('.manual-needed').is_visible();assert page.locator('#next-stage').is_disabled()
    # Analysis formatting uses stored mocked data, without rewriting it or invoking a provider.
    report=w.report_html('fixture',doc,revision=2).decode();analysis={'status':'PASS','issues':[],'sections':[{'title_ko':'주요 사양','text':'첫 문단: 치수 120 mm를 유지합니다.\n\n두 번째 문단: 모델 SKU-5를 사용합니다.'}],'conflicts':[{'page':1,'text':'시운전 조건은 4시간, 실제 인수 시험은 2시간입니다.','reason':'적용 기준을 고객에게 확인해야 합니다.'}],'questions':[{'question_ko':'어느 시험 시간을 적용하나요?','reason_ko':'견적과 인수 조건을 확정하기 위해 필요합니다.'}]}
    with patch.object(w.processing.provider,'review_pdf',return_value={'status':'PASS','issues':[]}):targets.run(w,'fixture',doc,f'displayed:{doc}:2','verify')
    with patch.object(w.processing.provider,'review_pdf',return_value=analysis):targets.run(w,'fixture',doc,f'displayed:{doc}:2','analyze')
    a=targets.overview(w,'fixture',doc,f'displayed:{doc}:2')['reviews']['analyze']['attempt'];page.goto(base+f'/api/documents/{doc}/target-result.html?target=displayed:{doc}:2&stage=analyze&attempt={a}')
    assert page.locator('.readable-entry').count()>=3;assert page.locator('.readable-text').first.evaluate('(e)=>parseFloat(getComputedStyle(e).lineHeight)')>=28;assert page.locator('.readable-entry').first.evaluate('(e)=>parseFloat(getComputedStyle(e).marginBottom)')>=20
    text=page.locator('body').inner_text();assert all(v in text for v in ['120 mm','SKU-5','4시간','2시간','견적과 인수 조건']);page.screenshot(path=str(ROOT/'docs/evidence/technical-readable.png'),full_page=True)
    pdf=PdfReader(io.BytesIO(page.pdf(prefer_css_page_size=True,print_background=True)));assert all(abs(float(p.mediabox.width)-595.276)<2 and abs(float(p.mediabox.height)-841.89)<2 for p in pdf.pages);printed=''.join(''.join(p.extract_text() for p in pdf.pages).split());assert all(''.join(v.split()) in printed for v in ['120 mm','SKU-5','4시간','2시간','견적과 인수 조건'])
    with w.workflow.connect() as db:assert json.loads(db.execute('SELECT payload FROM target_reviews WHERE id=?',(a,)).fetchone()[0])==analysis
    w.processing.provider=ReportAI(base_raw.replace('</section>','<p>'+AFTER+'</p></section>'));w.run('fixture',doc,'report');open_result(doc,target,attempt);assert '이전 검증 결과' in page.locator('#work-title').inner_text();assert page.locator('[data-use-recommendation]').count()==0;assert '현재 보고서 작업으로' in page.locator('#next-stage').inner_text()
    assert w.report_html('fixture',doc,revision=2).decode()==report and not errors,errors;b.close();print('PASS: short action queue shows only one required edit; no textarea/checkbox required; one click saves the stored proposal to version2, preserves version1 and original FAIL, and unlocks CSS for that exact version. Duplicate locations and missing proposals stay blocked. Customer questions do not block correction completion. Technical analysis has separate paragraphs/cards, readable line/section gaps, preserved numbers/model codes and complete A4 print text. No real API calls.')
  finally:stop(server,thread)
if __name__=='__main__':main()

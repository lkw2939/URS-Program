"""Isolated full-flow Chromium test with explicit synthetic AI transport."""
import io
import json
import hashlib
import secrets
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from fixtures import FixtureAI, urs_pdf
from urs.evaluation import record
from urs.web import make_app
from urs.workspace import Workspace
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'URS_OPENAI_MODEL':'fixture-only'}):
        w=Workspace(Path(folder)/'test.sqlite');password=secrets.token_urlsafe(24)
        w.add_user('pipeline-test',password);w.processing.provider=FixtureAI(wrong_number=True)
        server=make_app(w,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        evidence=Path(__file__).resolve().parents[1]/'docs/evidence';evidence.mkdir(exist_ok=True)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.get_by_role('button',name='로그인',exact=True).wait_for()
                page.keyboard.press('Tab')
                assert page.locator('.skip-link').evaluate('(e)=>e===document.activeElement')
                page.keyboard.press('Enter')
                assert page.locator('#main-content').evaluate('(e)=>e===document.activeElement')
                page.screenshot(path=str(evidence/'ui-login-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(evidence/'ui-login-mobile.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1100})

                page.get_by_label('직원 ID').fill('pipeline-test');page.get_by_label('비밀번호',exact=True).fill(password)
                page.get_by_role('button',name='로그인',exact=True).click()
                page.get_by_label('새 프로젝트 이름').fill('합성 URS 통합시험 · 실제 API 아님')
                page.get_by_role('button',name='프로젝트 만들기').click()
                page.get_by_label('고객 원본 PDF',exact=True).set_input_files({'name':'synthetic-urs.pdf','mimeType':'application/pdf','buffer':urs_pdf()})
                page.get_by_role('button',name='원본 등록',exact=True).click()

                page.get_by_role('button',name='원문·번역 검토',exact=True).wait_for()
                page.wait_for_function("document.getElementById('metric-documents').textContent==='1'")
                assert page.locator('#metric-projects').inner_text()=='1'
                assert page.locator('#metric-approved').inner_text()=='0'
                page.screenshot(path=str(evidence/'ui-dashboard-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(evidence/'ui-dashboard-mobile.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1100})
                page.get_by_role('button',name='원문·번역 검토',exact=True).click()
                page.locator('#checklist-steps li').last.wait_for()
                assert page.locator('#checklist-steps li').count()==7
                assert page.locator('#checklist-steps input').count()==0
                assert page.locator('#checklist-summary').inner_text().startswith('필수 확인 완료 1 / 7단계')
                assert page.locator('#checklist-steps [data-stage=translate] .checklist-status').inner_text()=='이전 단계 대기'
                page.get_by_role('button',name='추출 실행',exact=True).click()
                page.locator('#check-results').get_by_text('추출 · NEEDS_REVIEW',exact=False).wait_for()
                assert page.locator('#checklist-steps [data-stage=extract] .checklist-status').inner_text()=='검토 필요'
                page.locator('#source-review summary').click()
                for check in page.locator('#page-checks input').all():check.check()
                page.locator('#source-note').fill('알려진 합성 정답의 전체 페이지·표·원문 위치 대조 시험')
                page.get_by_role('button',name='원문 대조 기록 · 다음 단계 준비',exact=True).click()
                page.get_by_role('heading',name='synthetic-urs.pdf · 리비전 2',exact=True).wait_for()
                for stage in ('번역','독립 검증','기술 분석','보고서'):
                    page.get_by_role('button',name=stage+' 실행',exact=True).click()
                    page.locator('#check-results').get_by_text(stage+' · PASS',exact=False).wait_for(timeout=30000)
                assert page.locator('#checklist-summary').inner_text().startswith('필수 확인 완료 6 / 7단계')
                assert page.locator('#checklist-steps [data-stage=approval] .checklist-status').inner_text()=='승인 대기'
                page.locator('#document-checklist').screenshot(path=str(evidence/'checklist-review-ready.png'))
                # Both conflict references navigate to their exact source pages/boxes.
                refs=page.locator('.conflict-item button[data-source-id]')
                assert refs.count()==2
                for index in range(2):
                    ref=refs.nth(index);source_id=ref.get_attribute('data-source-id');ref.click()
                    assert page.locator('#page-select').input_value()==source_id.split('-')[0][1:]
                    assert float(page.locator('#highlight-rect').get_attribute('width'))>0
                page.locator('#page-select').select_option('1')
                draft=page.locator('#translation-blocks textarea[data-block-id]').first
                original_value=draft.input_value();draft.fill(original_value+' 임시 편집')
                page.locator('#page-select').select_option('2')
                page.locator('#page-select').select_option('1')
                assert page.locator('#translation-blocks textarea[data-block-id]').first.input_value()==original_value+' 임시 편집'
                page.locator('#translation-blocks textarea[data-block-id]').first.fill(original_value)
                error=page.locator('.issue-detail').first;error.locator('summary').click()
                assert '당시 번역:' in error.inner_text() and '수정 후 번역:' in error.inner_text()
                assert '102' in error.inner_text() and '120' in error.inner_text()
                page.locator('.compare').screenshot(path=str(evidence/'source-reference-navigation.png'))

                with page.expect_download() as info:
                    page.get_by_role('link',name='검증 기록 원본(JSON)',exact=True).click()
                audit_json=Path(info.value.path()).read_bytes()
                audit=json.loads(audit_json)
                canonical=json.dumps(audit['record'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
                assert hashlib.sha256(canonical).hexdigest()==audit['record_sha256']
                assert audit['record']['snapshot']['revision']==2 and not audit['record']['snapshot']['approved']
                assert audit['record']['verification_history'][0]['verification']['history'][0]['issues']
                (evidence/'synthetic-verification.json').write_bytes(audit_json)
                with page.expect_download() as info:
                    page.get_by_role('link',name='검증 기록 내려받기',exact=True).click()
                audit_html=Path(info.value.path()).read_bytes()
                assert audit['record_sha256'].encode() in audit_html
                html_path=evidence/'synthetic-verification.html';html_path.write_bytes(audit_html)
                report_page=browser.new_page(viewport={'width':1300,'height':1000})
                report_page.set_content(audit_html.decode('utf-8'))
                report_page.get_by_role('heading',name='문서 검증·수정 기록',exact=True).wait_for()
                assert report_page.locator('script').count()==0
                report_page.screenshot(path=str(evidence/'verification-record-readable.png'),full_page=False)
                report_page.close()

                page.locator('#translation-blocks textarea[data-block-id]').first.focus()
                assert float(page.locator('#highlight-rect').get_attribute('width'))>0
                page.locator('.compare').screenshot(path=str(evidence/'pipeline-source-highlight.png'))
                for link in page.locator('#export-links a').all():
                    with page.expect_download() as info:link.click()
                    data=Path(info.value.path()).read_bytes();name=info.value.suggested_filename
                    (evidence/('synthetic-'+name)).write_bytes(data)
                    if name.endswith('.pdf'):assert len(PdfReader(io.BytesIO(data)).pages)>0
                    else:assert len(Document(io.BytesIO(data)).inline_shapes)==2
                page.get_by_label('원문에 근거한 질문 또는 수정 요청').fill('최소 속도 원문을 다시 확인해 주세요.')
                page.get_by_role('button',name='AI에 검토 요청',exact=True).click()
                page.locator('#chat-result').get_by_text('원문 RQ-02의 최소 속도는 120 packs/min입니다.',exact=True).wait_for()
                for check in page.locator('#output-checks input').all():check.check()
                page.locator('#approval-note').fill('합성 출력물 4개와 정답을 확인한 제어 로직 시험. 실제 업무 승인 아님.')
                page.get_by_role('button',name='현재 리비전 최종 승인',exact=True).click()
                page.locator('#message').get_by_text('현재 코드·모델의 전문가 평가집 검증 근거가 없습니다.',exact=False).wait_for()
                page.screenshot(path=str(evidence/'pipeline-approval-blocked.png'),full_page=True)
                # Synthetic qualification exists only inside this temporary test DB.
                samples=[{'id':str(i),'source':f'fixture {i}','expected_meaning':f'정답 {i}','observed_translation':f'정답 {i}','language':'en' if i%2 else 'id','verdict':'PASS','critical_error':False,'evidence':'제어 로직 합성 시험'} for i in range(100)]
                record(w.workflow,'fixture-only',{'reviewer':'synthetic-not-human','samples':samples})
                page.get_by_role('button',name='현재 리비전 최종 승인',exact=True).click()
                page.locator('#export-links a').first.get_by_text('번역본 PDF · 승인본',exact=True).wait_for()
                assert page.locator('#checklist-summary').inner_text().startswith('필수 확인 완료 7 / 7단계')
                page.wait_for_function("document.getElementById('metric-approved').textContent==='1'")
                for link in page.locator('#export-links a').all():
                    with page.expect_download() as info:link.click()
                    data=Path(info.value.path()).read_bytes();name=info.value.suggested_filename
                    (evidence/('synthetic-'+name)).write_bytes(data)
                    if name.endswith('.pdf'):
                        pdf=PdfReader(io.BytesIO(data));text=''.join(p.extract_text() or '' for p in pdf.pages)
                        assert any(p.get('/Annots') for p in pdf.pages)
                    else:text=''.join(p.text for p in Document(io.BytesIO(data)).paragraphs)
                    assert '직원최종승인기록' in ''.join(text.split())
                    assert '승인자:pipeline-test' in ''.join(text.split())

                page.locator('#document-checklist').screenshot(path=str(evidence/'checklist-approved-fixture.png'))
                page.screenshot(path=str(evidence/'pipeline-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(evidence/'pipeline-mobile.png'),full_page=True)
                page.get_by_role('button',name='이 수정안 적용 · 기존 검증 무효화',exact=True).click()
                page.get_by_role('heading',name='synthetic-urs.pdf · 리비전 3',exact=True).wait_for()
                assert page.locator('#exports').is_hidden()
                assert page.locator('#checklist-summary').inner_text().startswith('필수 확인 완료 2 / 7단계')
                with page.expect_download() as info:
                    page.get_by_role('link',name='검증 기록 원본(JSON)',exact=True).click()
                revised_record=json.loads(Path(info.value.path()).read_bytes())['record']
                (evidence/'synthetic-verification-after-edit.json').write_text(json.dumps(revised_record,ensure_ascii=False,indent=2))
                assert revised_record['snapshot']['revision']==3 and not revised_record['snapshot']['approved']
                assert any(event['action']=='approved' for event in revised_record['snapshot']['events'])
                assert any(event['action']=='translation_edited' for event in revised_record['snapshot']['events'])

                for stage in ('번역','독립 검증','기술 분석','보고서'):
                    page.get_by_role('button',name=stage+' 실행',exact=True).click()
                    page.locator('#check-results').get_by_text(stage+' · PASS',exact=False).wait_for(timeout=30000)
                page.get_by_label('원문에 근거한 질문 또는 수정 요청').fill('보고서 설명을 쉽게 고쳐 주세요.')
                page.get_by_role('button',name='AI에 검토 요청',exact=True).click()
                page.get_by_role('button',name='보고서 수정안 적용 · 독립 재검증 대기',exact=True).click()
                page.get_by_role('heading',name='synthetic-urs.pdf · 리비전 4',exact=True).wait_for()
                assert page.locator('#exports').is_hidden()
                page.get_by_role('button',name='로그아웃',exact=True).click()
                page.get_by_role('button',name='로그인',exact=True).wait_for()
                assert not errors,errors
                browser.close()
                print('PASS: synthetic full Chromium flow, extraction review, translation, independent correction, analysis, 4 real output downloads, source highlight, AI dialogue, qualification gate, final approval, mobile layout, translation edit invalidation, AI report proposal invalidation, verification HTML/JSON downloads, matching record hashes and audit revision history. Real OpenAI/customer accuracy NOT tested.')
        finally:
            server.shutdown();thread.join();server.server_close()


if __name__=='__main__':
    main()
    from browser_blank_pages import main as check_blank_pages
    check_blank_pages()

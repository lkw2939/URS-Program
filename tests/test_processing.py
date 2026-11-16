import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from pypdf import PdfReader
from fixtures import FixtureAI, TRANSLATIONS, urs_pdf
from urs.ai import AIBlocked, OpenAI
from urs.extraction import extract_pdf
from urs.quality import translation_issues
from urs.workflow import Blocked
from urs.workspace import Workspace


class ProcessingTests(unittest.TestCase):
    def test_table_context_uses_employee_corrected_source_text(self):
        from urs.processing import layout_of
        extracted,_=extract_pdf(urs_pdf())
        block=next(b for p in extracted['pages'] for b in p['blocks'] if b['text']=='165')
        block['text']='166'
        cells=layout_of(extracted)[0]['tables'][0]['cells']
        self.assertEqual(next(c['text'] for c in cells if c['id']==block['id']),'166')

    def test_blank_independent_reason_cannot_pass_verification(self):
        self.extract_and_review();self.w.run('engineer',self.document,'translate')
        original=self.ai.call
        def blank(task,data,images=()):
            value=original(task,data,images)
            if task=='independent_verify':value['checks'][0]['reason']='   '
            return value
        self.ai.call=blank
        state=self.w.run('engineer',self.document,'verify')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='verify'),'FAIL')
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'analyze')

    def test_verification_and_analysis_receive_exact_table_relationships(self):
        original=self.ai.call;seen={}
        def capture(task,data,images=()):
            if task in ('independent_document_verify','analyze','independent_analysis_verify'):seen[task]=data['source_layout']
            return original(task,data,images)
        self.ai.call=capture;self.run_to_report()
        extracted=self.w.artifact('engineer',self.document,'extraction')
        expected=extracted['pages'][0]['tables'][0]
        self.assertEqual(len(seen),3)
        for layout in seen.values():
            self.assertEqual(layout[0]['tables'][0]['grid'],expected['grid'])
            self.assertEqual(layout[0]['tables'][0]['cells'],expected['cells'])
            self.assertEqual(layout[0]['preview_sha256'],extracted['pages'][0]['preview_sha256'])

    def test_preview_damage_blocks_verify_before_ai_request(self):
        self.extract_and_review();self.w.run('engineer',self.document,'translate')
        before=list(self.ai.calls)
        with self.w.workflow.connect() as db:db.execute('UPDATE page_assets SET payload=? WHERE document=? AND page=1',(b'damaged',self.document))
        state=self.w.run('engineer',self.document,'verify')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='verify'),'FAIL')
        self.assertEqual(self.ai.calls,before)
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'analyze')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=Workspace(Path(self.tmp.name)/'state.sqlite')
        self.w.add_user('engineer','fixture-engineer-password')
        self.project=self.w.create_project('engineer','Synthetic URS')
        self.payload=urs_pdf()
        self.document=self.w.upload('engineer',self.project,'synthetic.pdf',self.payload)
        self.env=patch.dict(os.environ,{'URS_OPENAI_MODEL':'fixture-only'});self.env.start();self.addCleanup(self.env.stop)
        self.ai=FixtureAI();self.w.processing.provider=self.ai

    def extract_and_review(self):
        self.w.run('engineer',self.document,'extract')
        self.w.review_extraction('engineer',self.document,1,[1,2],'시험 정답 텍스트·표와 모든 페이지 대조',{})

    def register_synthetic_evaluation(self):
        from urs.evaluation import record
        samples=[{'id':str(i),'source':f'fixture requirement {i}', 'expected_meaning':f'시험 요구 {i}', 'observed_translation':f'시험 요구 {i}', 'language':'en' if i%2 else 'id', 'verdict':'PASS', 'critical_error':False, 'evidence':'합성 게이트 시험이며 실제 의미 정확도 평가 아님'} for i in range(100)]
        return record(self.w.workflow,'fixture-only',{'reviewer':'synthetic-test-not-a-human','samples':samples})

    def run_to_report(self):
        self.extract_and_review()
        for stage in ('translate','verify','analyze','report'):
            state=self.w.run('engineer',self.document,stage)
            result=next(r for r in state['results'] if r['stage']==stage)
            self.assertEqual(result['status'],'PASS',result['evidence'])
        return state

    def test_all_source_text_tables_coordinates_and_preview(self):
        extracted,previews=extract_pdf(urs_pdf())
        self.assertEqual(len(extracted['pages']),2)
        self.assertEqual(len(previews),2)
        blocks=[b for p in extracted['pages'] for b in p['blocks']]
        self.assertEqual({b['text'] for b in blocks},set(TRANSLATIONS))
        for block in blocks:
            self.assertEqual(len(block['bbox']),4)
            self.assertIn(block['page'],(1,2))
        table=extracted['pages'][0]['tables'][0]
        self.assertEqual(table['text_grid'],[['Product','Length (mm)'],['AB-12','165']])
        self.assertEqual([len(row) for row in table['grid']],[2,2])
        for page,image in zip(extracted['pages'],previews):
            self.assertEqual(page['preview_sha256'],hashlib.sha256(image).hexdigest())
            self.assertTrue(image.startswith(b'\x89PNG'))

    def test_missing_analysis_topic_blocks_audit_and_report(self):
        self.extract_and_review()
        for stage in ('translate','verify'):self.w.run('engineer',self.document,stage)
        original=self.ai.call
        def incomplete(task,data,images=()):
            result=original(task,data,images)
            if task=='analyze':result['sections']=[s for s in result['sections'] if s['topic']!='products']
            return result
        self.ai.call=incomplete
        state=self.w.run('engineer',self.document,'analyze')
        self.assertFalse(next(s['passed'] for s in state['stages'] if s['id']=='analyze'))
        self.assertNotIn('independent_analysis_verify',self.ai.calls)
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'report')

    def test_conflict_without_technical_impact_cannot_pass(self):
        self.extract_and_review()
        for stage in ('translate','verify'):self.w.run('engineer',self.document,stage)
        original=self.ai.call
        def incomplete(task,data,images=()):
            result=original(task,data,images)
            if task=='analyze':result['conflicts'][0].pop('technical_impact')
            return result
        self.ai.call=incomplete
        state=self.w.run('engineer',self.document,'analyze')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='analyze'),'FAIL')
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'report')

    def test_translation_preserves_text_table_text_order(self):
        from urs.reports import build_reports
        self.run_to_report()
        extraction=self.w.artifact('engineer',self.document,'extraction')
        page=extraction['pages'][0]
        after=next(b for b in page['blocks'] if '120 packs/min' in b['text'])
        after['bbox']=[40,300,350,315]
        output=build_reports(extraction,self.w.artifact('engineer',self.document,'translation'),self.w.artifact('engineer',self.document,'analysis'),self.w.processing.previews(self.document),2)
        from zipfile import ZipFile
        with ZipFile(io.BytesIO(output['translation.docx'])) as z:xml=z.read('word/document.xml').decode()
        self.assertLess(xml.index('안전 가드'),xml.index('w:tbl>'))
        self.assertLess(xml.index('w:tbl>'),xml.index('최소 속도'))
        pdf=''.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(output['translation.pdf'])).pages)
        self.assertLess(pdf.index('안전 가드'),pdf.index('AB-12'))
        self.assertLess(pdf.index('AB-12'),pdf.index('최소 속도'))

    def _approve_fixture(self):
        self.register_synthetic_evaluation()
        reviewed=['translation.pdf','translation.docx','analysis.pdf','analysis.docx']
        revision=self.w.status('engineer',self.document)['revision']
        return self.w.approve_document('engineer',self.document,revision,'합성 출력 대조 시험 — 실제 업무 승인 아님.',reviewed)

    def test_final_files_include_approval_and_preserve_reviewed_content(self):
        self.run_to_report()
        kinds=['translation.pdf','translation.docx','analysis.pdf','analysis.docx']
        drafts={kind:self.w.export('engineer',self.document,kind) for kind in kinds}
        state=self._approve_fixture()
        evidence=json.loads(next(r['evidence'] for r in state['results'] if r['stage']=='approval'))
        for kind in kinds:
            final=self.w.export('engineer',self.document,kind,True)
            self.assertEqual(final,self.w.export('engineer',self.document,kind,True))
            self.assertEqual(drafts[kind],self.w.export('engineer',self.document,kind))
            self.assertEqual(hashlib.sha256(final).hexdigest(),evidence['outputs']['final-'+kind])
            if kind.endswith('.pdf'):
                original=PdfReader(io.BytesIO(drafts[kind]));approved=PdfReader(io.BytesIO(final))
                for before,after in zip(original.pages,approved.pages):self.assertEqual(before.extract_text(),after.extract_text())
                text=''.join(p.extract_text() or '' for p in approved.pages)
            else:
                doc=Document(io.BytesIO(final));text=''.join(p.text for p in doc.paragraphs)
                self.assertEqual(len(doc.inline_shapes),2)
            compact=''.join(text.split())
            for value in ('직원 최종 승인 기록','승인자: engineer','승인 시각(KST)',evidence['approved_at_kst'],hashlib.sha256(drafts[kind]).hexdigest()):
                self.assertIn(''.join(value.split()),compact)
        from urs.backup import backup_database,restore_database
        backup=Path(self.tmp.name)/'approved-backup.sqlite';restored=Path(self.tmp.name)/'approved-restored.sqlite'
        backup_database(self.w.workflow.path,backup);restore_database(backup,restored)
        recovered=Workspace(restored)
        for kind in kinds:self.assertEqual(recovered.export('engineer',self.document,kind,True),self.w.export('engineer',self.document,kind,True))

    def test_failed_final_generation_cannot_record_approval(self):
        self.run_to_report()
        with patch('urs.reports.attach_approval',side_effect=ValueError('synthetic export failure')):
            with self.assertRaises(ValueError):self._approve_fixture()
        state=self.w.status('engineer',self.document)
        self.assertFalse(state['approved'])
        self.assertFalse(any(r['stage']=='approval' for r in state['results']))

    def test_edit_during_final_generation_discards_prepared_approval(self):
        from urs.reports import attach_approval
        self.run_to_report()
        def changed(outputs,record):
            final=attach_approval(outputs,record)
            translation=self.w.artifact('engineer',self.document,'translation')
            key=next(iter(translation))
            self.w.edit_translation('engineer',self.document,record['revision'],{key:translation[key]+' 수정'})
            return final
        with patch('urs.reports.attach_approval',side_effect=changed):
            with self.assertRaises(Blocked):self._approve_fixture()
        self.assertFalse(self.w.status('engineer',self.document)['approved'])
        with self.w.workflow.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM artifacts WHERE kind LIKE 'final-%'").fetchone()[0],0)

    def test_tampered_final_file_blocks_download_and_backup(self):
        from urs.backup import backup_database
        self.run_to_report();state=self._approve_fixture()
        self.w.processing.put(self.document,state['revision'],'final-analysis.pdf',b'damaged approved report')
        with self.assertRaises(Blocked):self.w.export('engineer',self.document,'analysis.pdf',True)
        output=Path(self.tmp.name)/'backup.sqlite'
        with self.assertRaises(ValueError):backup_database(self.w.workflow.path,output)
        self.assertFalse(output.exists())

    def test_missing_information_cannot_contain_invented_claims_or_citations(self):
        from urs.reports import validate_analysis_sections
        self.run_to_report()
        import copy
        analysis=self.w.artifact('engineer',self.document,'analysis')
        extraction=self.w.artifact('engineer',self.document,'extraction')
        ids={b['id'] for p in extraction['pages'] for b in p['blocks']}
        validate_analysis_sections(analysis,ids)
        for changes in ({'text':'고객사는 가상 회사입니다.'},{'source_ids':[next(iter(ids))]},{'coverage':'unknown'}):
            damaged=copy.deepcopy(analysis)
            next(s for s in damaged['sections'] if s['topic']=='overview').update(changes)
            with self.assertRaises(ValueError):validate_analysis_sections(damaged,ids)

    def test_analysis_outputs_have_twelve_sections_and_honest_approval_state(self):
        from urs.reports import ANALYSIS_HEADINGS,NOT_STATED
        self.run_to_report()
        doc=Document(io.BytesIO(self.w.export('engineer',self.document,'analysis.docx')))
        headings=[p.text for p in doc.paragraphs if p.style.name=='Heading 1']
        self.assertEqual(headings,list(ANALYSIS_HEADINGS))
        pdf=PdfReader(io.BytesIO(self.w.export('engineer',self.document,'analysis.pdf')))
        texts=[''.join(p.text for p in doc.paragraphs),''.join(p.extract_text() or '' for p in pdf.pages)]
        for text in texts:
            compact=''.join(text.split())
            for heading in ANALYSIS_HEADINGS:self.assertIn(''.join(heading.split()),compact)
            self.assertIn(''.join(NOT_STATED.split()),compact)
            self.assertIn('최종승인:파일생성시점미완료',compact)
            self.assertIn('번역독립검증:필수검사통과',compact)

    def test_report_rejects_missing_topic_even_if_analysis_artifact_is_changed(self):
        self.run_to_report()
        analysis=self.w.artifact('engineer',self.document,'analysis')
        analysis['sections']=[s for s in analysis['sections'] if s['topic']!='overview']
        revision=self.w.status('engineer',self.document)['revision']
        self.w.processing.put(self.document,revision,'analysis',analysis)
        state=self.w.run('engineer',self.document,'report')
        self.assertFalse(next(s['passed'] for s in state['stages'] if s['id']=='report'))
        with self.assertRaises(Blocked):self.w.export('engineer',self.document,'analysis.pdf')

    def test_source_review_gate_missing_pages_and_missing_api(self):
        self.w.run('engineer',self.document,'extract')
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'translate')
        with self.assertRaises(ValueError):self.w.review_extraction('engineer',self.document,1,[1],'incomplete',{})
        self.w.review_extraction('engineer',self.document,1,[1,2],'all pages checked',{})
        self.w.processing.provider=None
        with patch.dict(os.environ,{},clear=True):
            state=self.w.run('engineer',self.document,'translate')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='translate'),'BLOCKED')
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'verify')
        self.assertFalse(state['approved'])

    def test_independent_correction_and_reverification(self):
        self.ai.wrong_number=True
        self.extract_and_review()
        self.w.run('engineer',self.document,'translate')
        state=self.w.run('engineer',self.document,'verify')
        self.assertTrue(next(s['passed'] for s in state['stages'] if s['id']=='verify'))
        self.assertIn('correct_translation',self.ai.calls)
        self.assertGreaterEqual(self.ai.calls.count('independent_verify'),2)
        history=self.w.artifact('engineer',self.document,'verification')['history']
        self.assertTrue(history[0]['issues'])
        self.assertFalse(history[-1]['issues'])
        self.assertTrue(any('102' in t for t in history[0]['translations'].values()))
        self.assertFalse(any('102' in t for t in history[-1]['translations'].values()))

    def test_persistent_errors_stop_after_two_corrections(self):
        self.ai.wrong_number=True;self.ai.persistent_failure=True
        self.extract_and_review();self.w.run('engineer',self.document,'translate')
        state=self.w.run('engineer',self.document,'verify')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='verify'),'NEEDS_REVIEW')
        self.assertEqual(self.ai.calls.count('correct_translation'),2)
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'analyze')

    def test_report_open_links_body_images_final_approval_edit_invalidation(self):
        self.run_to_report()
        for kind in ('translation.pdf','analysis.pdf','translation.docx','analysis.docx'):
            with self.assertRaises(Blocked):self.w.export('engineer',self.document,kind,True)
            payload=self.w.export('engineer',self.document,kind)
            self.assertGreater(len(payload),1000)
            if kind.endswith('.pdf'):
                reader=PdfReader(io.BytesIO(payload))
                self.assertTrue(any(p.get('/Annots') for p in reader.pages))
                self.assertIn('원본 시각자료',''.join(p.extract_text() for p in reader.pages))
            else:
                doc=Document(io.BytesIO(payload));self.assertEqual(len(doc.inline_shapes),2)
        reviewed=['translation.pdf','translation.docx','analysis.pdf','analysis.docx']
        with self.assertRaises(Blocked):self.w.approve_document('engineer',self.document,2,'no expert corpus',reviewed)
        self.register_synthetic_evaluation()
        state=self.w.approve_document('engineer',self.document,2,'합성 정답과 출력 구조 대조 시험. 실제 고객 문서 승인 아님.',reviewed)
        self.assertTrue(state['approved'])
        self.assertTrue(self.w.export('engineer',self.document,'translation.pdf',True))
        translation=self.w.artifact('engineer',self.document,'translation')
        key=next(k for k,v in translation.items() if '120 packs' in v)
        state=self.w.edit_translation('engineer',self.document,2,{key:translation[key]+' (직원 수정)'})
        self.assertEqual(state['revision'],3)
        self.assertFalse(state['approved'])
        with self.assertRaises(Blocked):self.w.export('engineer',self.document,'translation.pdf',True)
        with self.assertRaises(Blocked):self.w.approve_document('engineer',self.document,2,'old',reviewed)
        self.assertEqual(self.w.original('engineer',self.document)['original'],self.payload)
        self.w.run('engineer',self.document,'translate')
        self.assertEqual(self.w.artifact('engineer',self.document,'translation')[key],translation[key]+' (직원 수정)')

    def test_numeric_safety_and_code_guards(self):
        blocks=[{'id':'safe','text':'AB-12 shall not run at 120 packs/min.'}]
        issues=translation_issues(blocks,{'safe':'AB-13은 102 packs/min에서 작동합니다.'})
        self.assertEqual({i['type'] for i in issues},{'numbers','quantity_unit','product_code','safety_negation'})

    def test_ai_requires_configuration_and_never_calls_without_it(self):
        with patch.dict(os.environ,{},clear=True), patch('urllib.request.urlopen') as call:
            with self.assertRaises(AIBlocked):OpenAI(self.w.workflow,self.document).call('translate',{})
            call.assert_not_called()


    def test_invented_analysis_reference_is_rejected(self):
        self.extract_and_review()
        self.w.run('engineer',self.document,'translate')
        self.w.run('engineer',self.document,'verify')
        original=self.ai.call
        def tampered(task,data,images=()):
            value=original(task,data,images)
            if task=='analyze':value['sections'][0]['source_ids']=['invented-source']
            return value
        self.ai.call=tampered
        state=self.w.run('engineer',self.document,'analyze')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='analyze'),'FAIL')
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'report')

    def test_duplicate_translation_ids_fail_coverage(self):
        self.extract_and_review()
        original=self.ai.call
        def duplicate(task,data,images=()):
            value=original(task,data,images)
            if task=='translate':value['translations'].append(value['translations'][0])
            return value
        self.ai.call=duplicate
        state=self.w.run('engineer',self.document,'translate')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='translate'),'FAIL')
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'verify')

    def test_whole_document_uncertainty_does_not_pass(self):
        self.extract_and_review();self.w.run('engineer',self.document,'translate')
        original=self.ai.call
        def uncertain(task,data,images=()):
            if task=='independent_document_verify':return {'status':'NEEDS_REVIEW','issues':[]}
            return original(task,data,images)
        self.ai.call=uncertain
        state=self.w.run('engineer',self.document,'verify')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='verify'),'NEEDS_REVIEW')
        self.assertNotIn('correct_translation',self.ai.calls)

    def test_analysis_edit_invalidates_approval_and_rechecks_changed_analysis(self):
        self.run_to_report()
        analysis=self.w.artifact('engineer',self.document,'analysis')
        analysis['questions']=[]
        state=self.w.edit_analysis('engineer',self.document,2,analysis)
        self.assertEqual(state['revision'],3)
        self.assertFalse(state['approved'])
        with self.assertRaises(Blocked):self.w.export('engineer',self.document,'analysis.pdf')
        before=self.ai.calls.count('analyze')
        for stage in ('translate','verify','analyze'):
            self.w.run('engineer',self.document,stage)
        self.assertEqual(self.ai.calls.count('analyze'),before)
        self.assertEqual(self.w.artifact('engineer',self.document,'analysis')['questions'],[])
        self.assertGreaterEqual(self.ai.calls.count('independent_analysis_verify'),2)


    def test_source_transcription_correction_preserves_pdf_and_invalidates_results(self):
        self.w.run('engineer',self.document,'extract')
        extracted=self.w.artifact('engineer',self.document,'extraction')
        first=extracted['pages'][0]['blocks'][0]
        corrected=first['text']+' [원문 대조 보완 시험]'
        state=self.w.review_extraction('engineer',self.document,1,[1,2],'원문 문자 대조 근거',{}, {first['id']:corrected})
        self.assertEqual(state['revision'],2)
        self.assertEqual(self.w.original('engineer',self.document)['original'],self.payload)
        revised=self.w.artifact('engineer',self.document,'extraction')
        self.assertEqual(revised['pages'][0]['blocks'][0]['text'],corrected)
        self.assertEqual(revised['pages'][0]['blocks'][0]['bbox'],first['bbox'])
        self.assertFalse(any(s['passed'] for s in state['stages'] if s['id'] not in ('source','extract')))

    def test_visual_source_supplement_coordinates_still_require_review(self):
        from PIL import Image,ImageDraw
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        image=Image.new('RGB',(300,100),'white');ImageDraw.Draw(image).text((10,40),'RQ-06 Speed 120 packs/min',fill='black')
        stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=(400,400));c.drawImage(ImageReader(image),40,240,300,100);c.save()
        document=self.w.upload('engineer',self.project,'visual.pdf',stream.getvalue())
        class VisualFixture:
            def call(inner,task,data,images=()):
                self.assertEqual(task,'extract_visual');self.assertEqual(len(images),1)
                return {'blocks':[{'text':'RQ-06 Speed 120 packs/min','bbox':[.1,.15,.85,.4]}],'needs_review':True,'reason':'합성 좌표 매핑 시험'}
        self.w.processing.provider=VisualFixture()
        state=self.w.run('engineer',document,'extract')
        extracted=self.w.artifact('engineer',document,'extraction');block=extracted['pages'][0]['blocks'][0]
        self.assertEqual(block['origin'],'openai-visual-transcription')
        self.assertEqual(block['bbox'],[40.0,60.0,340.0,160.0])
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='extract'),'NEEDS_REVIEW')
        with self.assertRaises(Blocked):self.w.run('engineer',document,'translate')


    def test_ai_report_proposal_applies_as_unverified_new_revision(self):
        import copy
        self.run_to_report()
        proposed=copy.deepcopy(self.w.artifact('engineer',self.document,'analysis'))
        proposed['sections'][0]['text']='안전 가드가 열리면 컨베이어가 작동하지 않도록 하는 고객 요구입니다.'
        source_id=proposed['sections'][0]['source_ids'][0]
        original=self.ai.call
        def proposal(task,data,images=()):
            if task=='dialogue':
                self.assertIsNotNone(data['analysis'])
                return {'reply':'보고서 설명 수정안입니다. 재검증이 필요합니다.','source_ids':[source_id],'changes':[],'analysis_proposal':proposed}
            return original(task,data,images)
        self.ai.call=proposal
        response=self.w.chat('engineer',self.document,2,'보고서의 안전 설명을 쉽게 다시 써 주세요.')
        state=self.w.edit_analysis('engineer',self.document,response['revision'],response['analysis_proposal'])
        self.assertEqual(state['revision'],3)
        self.assertFalse(state['approved'])
        self.assertFalse(next(s['passed'] for s in state['stages'] if s['id']=='verify'))
        with self.assertRaises(Blocked):self.w.export('engineer',self.document,'analysis.pdf')

    def test_corrupted_page_preview_blocks_translation_before_ai_request(self):
        self.extract_and_review()
        before=list(self.ai.calls)
        with self.w.workflow.connect() as db:
            db.execute('UPDATE page_assets SET payload=? WHERE document=? AND page=1',(b'wrong-image',self.document))
        with self.assertRaises(ValueError):self.w.page_image('engineer',self.document,1)
        state=self.w.run('engineer',self.document,'translate')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='translate'),'FAIL')
        self.assertEqual(before,self.ai.calls)
        with self.assertRaises(Blocked):self.w.run('engineer',self.document,'verify')

    def test_missing_page_preview_cannot_produce_a_report(self):
        self.run_to_report()
        with self.w.workflow.connect() as db:
            db.execute('DELETE FROM page_assets WHERE document=? AND page=2',(self.document,))
        state=self.w.run('engineer',self.document,'report')
        self.assertEqual(next(r['status'] for r in state['results'] if r['stage']=='report'),'FAIL')
        with self.assertRaises(Blocked):self.w.export('engineer',self.document,'translation.pdf')

    def test_verification_export_includes_actual_correction_attempt_history(self):
        self.ai.wrong_number=True
        self.extract_and_review();self.w.run('engineer',self.document,'translate')
        self.w.run('engineer',self.document,'verify')
        bundle=self.w.verification_record('engineer',self.document)
        entry=bundle['record']['verification_history'][0]
        self.assertEqual(entry['revision'],2)
        history=entry['verification']['history']
        self.assertTrue(history[0]['issues'])
        self.assertFalse(history[-1]['issues'])
        self.assertTrue(any('102' in value for value in history[0]['translations'].values()))
        self.assertFalse(any('102' in value for value in history[-1]['translations'].values()))

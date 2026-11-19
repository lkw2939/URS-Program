"""Read-only discovery of stored HTML. Never generate, repair or rewrite artifacts."""
import hashlib
import json
import re
from urs.images import bind_images
from urs.workflow import Blocked


def read_final(db, document, revision):
    rows={r['kind']:bytes(r['payload']) for r in db.execute(
        "SELECT kind,payload FROM artifacts WHERE document=? AND revision=? AND kind IN ('report.html','report.raw.html','report-metadata','report-images','correction-patch','report.prepared.html','image-presentation','a4-pagination')",(document,revision))}
    final=rows.get('report.html')
    if not final:raise Blocked('저장된 최종 HTML이 없습니다.')
    try:text=final.decode('utf-8')
    except UnicodeError:raise Blocked('저장 HTML의 문자 형식을 확인할 수 없습니다.') from None
    # A document boundary check, not a translation or HTML quality certification.
    if not re.search(r'<html(?:\s|>)',text,re.I) or not re.search(r'</html\s*>\s*(?:```\s*)?$',text,re.I):
        raise Blocked('저장 HTML의 문서 끝을 확인할 수 없습니다. 불완전한 파일일 수 있습니다.')
    metadata={};integrity='unrecorded'
    if 'report-metadata' in rows:
        try:
            metadata=json.loads(rows['report-metadata'])
            if hashlib.sha256(final).hexdigest()!=metadata['final_sha256']:raise ValueError()
            raw=rows['report.raw.html']
            if hashlib.sha256(raw).hexdigest()!=metadata['raw_sha256']:raise ValueError()
            assets=json.loads(rows['report-images'])
            if 'correction-patch' in rows:
                receipt_bytes=rows['correction-patch'];receipt=json.loads(receipt_bytes)
                if hashlib.sha256(receipt_bytes).hexdigest()!=metadata['correction_patch_sha256']:raise ValueError()
                parent_revision=receipt['parent_revision']
                if type(parent_revision) is not int or not 0<parent_revision<revision:raise ValueError()
                parent,_=read_final(db,document,parent_revision)
                if hashlib.sha256(parent).hexdigest()!=receipt['parent_sha256']:raise ValueError()
                from urs.review_results import replay
                expected=replay(parent.decode(),receipt['patches'])
            elif metadata.get('image_presentation_version'):
                from urs.image_presentation import prepare,VERSION
                if metadata['image_presentation_version']!=VERSION:raise ValueError()
                prepared,receipt=prepare(raw.decode())
                if rows['report.prepared.html']!=prepared.encode() or hashlib.sha256(prepared.encode()).hexdigest()!=metadata['prepared_sha256']:raise ValueError()
                if json.loads(rows['image-presentation'])!=receipt or hashlib.sha256(rows['image-presentation']).hexdigest()!=metadata['image_presentation_sha256']:raise ValueError()
                expected,_=bind_images(prepared,assets)
            else:expected,_=bind_images(raw.decode(),assets)
            if metadata.get('a4_pagination_version') and 'correction-patch' not in rows:
                from urs.a4_pages import VERSION
                receipt=json.loads(rows['a4-pagination'])
                if metadata['a4_pagination_version']!=VERSION or receipt['version']!=VERSION:raise ValueError()
                if hashlib.sha256(rows['a4-pagination']).hexdigest()!=metadata['a4_pagination_sha256']:raise ValueError()
                if hashlib.sha256(expected.encode()).hexdigest()!=receipt['input_sha256'] or hashlib.sha256(final).hexdigest()!=receipt['final_sha256']:raise ValueError()
                if receipt['changed']:expected=final.decode()
            if expected.encode()!=final:raise ValueError()
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise Blocked('저장 HTML 원본/최종본 무결성 검사 실패') from None
        integrity='verified'
    return final,{'revision':revision,'metadata':metadata,'integrity':integrity,
                  'raw_available':'report.raw.html' in rows}


def inspect_document(db, document, current):
    revisions=[r[0] for r in db.execute("SELECT revision FROM artifacts WHERE document=? AND kind='report.html' ORDER BY revision DESC",(document,)) if r[0]<=current]
    available=[];invalid=[]
    for revision in revisions:
        try:
            _,info=read_final(db,document,revision)
            if info['metadata'].get('layout_contract') and info['metadata'].get('layout_status')!='PASS':raise Blocked('최종 HTML A4 배치 확인 필요. 이전 정상 보고서를 유지합니다.')
            available.append(info)
        except Blocked as exc:invalid.append({'revision':revision,'reason':str(exc)})
    failure=None
    for row in db.execute("SELECT status,evidence FROM results WHERE job=? AND revision=? AND stage='report' ORDER BY rowid DESC",(document,current)):
        if row['status']!='PASS':
            try:reason=json.loads(row['evidence']).get('reason','보고서 생성 실패')
            except (ValueError,TypeError):reason='보고서 생성 실패 (상세 기록 확인 필요)'
            failure={'status':row['status'],'reason':reason};break
    selected=available[0] if available else None
    return {'current_revision':current,'selected':selected,'available':available,'invalid':invalid,
            'stored_revisions':revisions,'current_failure':failure,'state':'current' if selected and selected['revision']==current else 'previous' if selected else 'none'}


def stored_review(db,document,revision):
    """Inspect exact stored bytes, including blocked files; not a quality verdict."""
    rows={r['kind']:bytes(r['payload']) for r in db.execute(
        "SELECT kind,payload FROM artifacts WHERE document=? AND revision=? AND kind IN ('report.html','report.raw.html','report-metadata','report-images','correction-patch','report.prepared.html','image-presentation','a4-pagination')",(document,revision))}
    if not rows:raise Blocked('저장된 HTML 결과가 없습니다.')
    files={kind:value for kind,value in rows.items() if kind in ('report.html','report.raw.html')}
    if not files:raise Blocked('저장된 HTML 결과가 없습니다.')
    inspection={'revision':revision,'files':{},'only_image_addresses_changed':None,'api_diagnostics':[],
                'content_completeness':'미확인: 원본 PDF의 마지막 내용과 대조해야 합니다. 끝 태그나 API completed만으로 판단하지 않습니다.'}
    for kind,value in files.items():
        text=value.decode('utf-8',errors='replace')
        matches=list(re.finditer(r'</html\s*>',text,re.I))
        inspection['files'][kind]={'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest(),
            'has_closing_body_tag':bool(re.search(r'</body\s*>',text,re.I)),'has_closing_html_tag':bool(matches),'passes_existing_end_check':bool(re.search(r'</html\s*>\s*$',text,re.I)),
            'trailing_after_last_html_tag':text[matches[-1].end():] if matches else None,'tail':text[-4000:]}
    if all(k in rows for k in ('report.html','report.raw.html','report-images')):
        try:
            expected,comparison=bind_images(rows['report.raw.html'].decode(),json.loads(rows['report-images']))
            inspection['only_image_addresses_changed']=expected.encode()==rows['report.html']
            inspection['image_replacements']=len(comparison['replacements'])
            inspection['unresolved_images']=comparison['unresolved']
        except (ValueError,TypeError,KeyError):inspection['comparison_error']='저장된 비교 자료를 읽지 못했습니다.'
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='report_diagnostics'").fetchone()
    if exists:
        inspection['api_diagnostics']=[json.loads(r[0]) for r in db.execute('SELECT payload FROM report_diagnostics WHERE document=? ORDER BY call_id',(document,)) if json.loads(r[0]).get('revision')==revision]
    if 'image-presentation' in rows:inspection['image_presentation']=json.loads(rows['image-presentation'])
    if 'correction-patch' in rows:inspection['employee_correction']=json.loads(rows['correction-patch'])
    if 'report-metadata' in rows:
        try:
            meta=json.loads(rows['report-metadata'])
            inspection['generation_settings']={k:meta[k] for k in ('model','reasoning_effort','max_output_tokens','settings_version') if k in meta}
        except (ValueError,TypeError):inspection['generation_settings']=None
    return files,inspection

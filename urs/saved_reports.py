"""Read-only discovery of stored HTML. Never generate, repair or rewrite artifacts."""
import hashlib
import json
import re
from urs.images import bind_images
from urs.workflow import Blocked


def read_final(db, document, revision):
    rows={r['kind']:bytes(r['payload']) for r in db.execute(
        "SELECT kind,payload FROM artifacts WHERE document=? AND revision=? AND kind IN ('report.html','report.raw.html','report-metadata','report-images')",(document,revision))}
    final=rows.get('report.html')
    if not final:raise Blocked('저장된 최종 HTML이 없습니다.')
    try:text=final.decode('utf-8')
    except UnicodeError:raise Blocked('저장 HTML의 문자 형식을 확인할 수 없습니다.') from None
    # A document boundary check, not a translation or HTML quality certification.
    if not re.search(r'<html(?:\s|>)',text,re.I) or not re.search(r'</html\s*>\s*$',text,re.I):
        raise Blocked('저장 HTML의 문서 끝을 확인할 수 없습니다. 불완전한 파일일 수 있습니다.')
    metadata={};integrity='unrecorded'
    if 'report-metadata' in rows:
        try:
            metadata=json.loads(rows['report-metadata'])
            if hashlib.sha256(final).hexdigest()!=metadata['final_sha256']:raise ValueError()
            raw=rows['report.raw.html']
            if hashlib.sha256(raw).hexdigest()!=metadata['raw_sha256']:raise ValueError()
            assets=json.loads(rows['report-images'])
            expected,_=bind_images(raw.decode(),assets)
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
        try:_,info=read_final(db,document,revision);available.append(info)
        except Blocked as exc:invalid.append({'revision':revision,'reason':str(exc)})
    failure=None
    for row in db.execute("SELECT status,evidence FROM results WHERE job=? AND revision=? AND stage='report' ORDER BY rowid DESC",(document,current)):
        if row['status']!='PASS':
            try:reason=json.loads(row['evidence']).get('reason','보고서 생성 실패')
            except (ValueError,TypeError):reason='보고서 생성 실패 (상세 기록 확인 필요)'
            failure={'status':row['status'],'reason':reason};break
    selected=available[0] if available else None
    return {'current_revision':current,'selected':selected,'available':available,'invalid':invalid,
            'current_failure':failure,'state':'current' if selected and selected['revision']==current else 'previous' if selected else 'none'}

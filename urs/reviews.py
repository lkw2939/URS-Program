"""Append-only review attempts, preflight explanations and safe readable output."""
import hashlib,json,time,uuid
from datetime import datetime,timezone
from html import escape
from urs.workflow import Blocked
from urs.ai import AIBlocked,AIError
from urs.gates import Status

INSTANCE=uuid.uuid4().hex
NAMES={'verify':'독립검증','analyze':'기술분석'}
def history(db,document,stage):
    return [dict(r) for r in db.execute('SELECT * FROM review_attempts WHERE document=? AND stage=? ORDER BY id DESC',(document,stage))]

def overview(workspace,owner,document):
    workspace.original(owner,document)
    with workspace.workflow.connect() as db:
        revision=workspace.workflow._job(db,document)['revision'];items={}
        for stage,kind in [('verify','verification'),('analyze','analysis')]:
            entries=history(db,document,stage)
            for r in db.execute('SELECT revision,payload FROM artifacts WHERE document=? AND kind=? ORDER BY revision DESC',(document,kind)):
                entries.append({'id':None,'revision':r['revision'],'state':'finished','payload':r['payload'].decode(),'status':json.loads(r['payload']).get('status','NEEDS_REVIEW'),'created':'미기록','evidence':'{}'})
            entries.sort(key=lambda x:(x['revision'],x['id'] or -1),reverse=True)
            stored=next((r for r in entries if r['payload']),None)
            current=next((r for r in entries if r['revision']==revision),None)
            items[stage]={'available':stored is not None,'revision':stored['revision'] if stored else None,'attempt':stored['id'] if stored else None,
                'previous':bool(stored and stored['revision']!=revision),'older_attempt':bool(current and stored and current['id']!=stored['id']),'running':bool(current and current['state']=='running' and json.loads(current['evidence']).get('server_instance')==INSTANCE),
                'failure':json.loads(current['evidence']).get('reason') if current and current['state']=='failed' else None}
    state=workspace.status(owner,document)
    for stage,item in items.items():
        if not item['running']:
            with workspace.workflow.connect() as db:
                last=db.execute('SELECT state,evidence FROM review_attempts WHERE document=? AND revision=? AND stage=? ORDER BY id DESC LIMIT 1',(document,state['revision'],stage)).fetchone()
            if last and last['state']=='running':item['failure']='이전 서버의 작업 완료 여부를 확인할 수 없습니다. 기존 기록과 API 사용 내역을 확인한 뒤 필요할 때만 수동 실행하세요. 자동 재시도하지 않습니다.'
        required=['source','report']+(['verify'] if stage=='analyze' else [])
        missing=[NAMES.get(s,{'source':'원본 무결성 확인','report':'현재 리비전 HTML 저장'} .get(s,s)) for s in required if not next((x['passed'] for x in state['stages'] if x['id']==s),False)]
        reason='먼저 '+', '.join(missing)+' 단계를 통과해야 합니다. 해당 단계의 실패/검토 필요 항목을 확인하세요.' if missing else ''
        try:workspace.processing.checked_html(document,state['revision'])
        except (Blocked,ValueError):reason=reason or '현재 리비전의 원본/최종 HTML 및 이미지 연결 무결성을 확인할 수 없습니다. 저장 HTML 점검 파일과 실패 기록을 확인하세요.'
        if state['approved']:reason='이미 승인된 리비전입니다. 기존 승인·답변 보존을 위해 이 리비전의 재실행은 막습니다. 새 리비전 검토가 필요합니다.'
        if item['running']:reason='실행 중입니다. 결과가 저장될 때까지 기다려 주세요. 새로고침해도 자동 재실행하지 않습니다.'
        item['superseded']=stage=='analyze' and item['available'] and not next((x['passed'] for x in state['stages'] if x['id']=='analyze'),False)
        item['can_run']=not reason;item['blocked_reason']=reason
        item['input_note']=f"리비전 {state['revision']}의 원본 PDF + 저장된 Terra 원본 HTML(report.raw.html). A4 별도 수정본과 변환 PDF는 사용하지 않습니다."
    return items

def run(workspace,owner,document,stage):
    workspace.original(owner,document)
    with workspace._locks_guard:lock=workspace._run_locks.setdefault(document,__import__('threading').Lock())
    if not lock.acquire(False):raise Blocked('이 문서의 다른 처리가 진행 중입니다. 완료 후 결과를 확인하세요.')
    try:
        item=overview(workspace,owner,document)[stage]
        if not item['can_run']:raise Blocked(item['blocked_reason'])
        with workspace.workflow.connect() as db:
            job=workspace.workflow._job(db,document);revision=job['revision'];content=job['content']
            attempt=db.execute('INSERT INTO review_attempts(document,revision,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?,?)',(document,revision,stage,'running','UNVERIFIED',None,json.dumps({'server_instance':INSTANCE,'reason':'실행 중'}),datetime.now(timezone.utc).isoformat())).lastrowid
        start=time.monotonic();payload=None
        try:
            status,evidence=workspace.processing._review(content,'independent_verify' if stage=='verify' else 'technical_analysis','verification' if stage=='verify' else 'analysis',persist=False)
            payload=evidence.pop('review_result');phase='finished'
        except Exception as exc:
            status=Status.FAIL;phase='failed';evidence={'reason':str(exc) if isinstance(exc,(AIError,AIBlocked,Blocked)) else '검토 결과 처리 실패. 오류 종류: '+type(exc).__name__,'error_type':type(exc).__name__}
            if getattr(exc,'diagnostics',None):evidence['api_diagnostics']=exc.diagnostics
        evidence['elapsed_seconds']=round(time.monotonic()-start,3)
        evidence['input_revision']=revision
        if payload is None:evidence['next_action']='기존 파일을 재생성하지 말고 실행 실패 기록과 입력 무결성·모델 접근·API 설정을 확인하세요.'
        with workspace.workflow.connect() as db:
            if workspace.workflow._job(db,document)['revision']!=revision:
                phase='failed';status=Status.FAIL;evidence['reason']='작업 중 리비전이 변경됐습니다. 결과는 이전 리비전 기록으로 보존합니다.'
            encoded=json.dumps(evidence,ensure_ascii=False)
            db.execute('UPDATE review_attempts SET state=?,status=?,payload=?,evidence=?,digest=? WHERE id=?',(phase,status.value,json.dumps(payload,ensure_ascii=False) if payload is not None else None,encoded,hashlib.sha256(encoded.encode()).hexdigest(),attempt))
        return workspace.status(owner,document)
    finally:lock.release()

LABELS={'page':'원문 쪽','reason':'판단 이유','severity':'항목 구분','type':'구분','text':'설명','title':'제목','description':'설명','question':'고객 질문','why':'질문이 필요한 이유','rationale':'판단 근거','evidence':'근거','source':'원문 근거','source_en':'영어 원문 근거','english':'영어 원문 근거','original':'원문 근거','before':'수정 전(모델 제안)','after':'수정 후(모델 제안)','requirement':'요구사항','specification':'사양','value':'값','unit':'단위','ko':'한국어 설명','en':'영어 원문 근거','question_ko':'고객 질문','reason_ko':'판단 이유','question_en':'질문 영어 근거'}
def readable(value):
    if isinstance(value,dict):
        keys=sorted(value,key=lambda k:(k in ('en','english','source_en','question_en'),list(value).index(k)))
        return '<dl>'+''.join('<dt>'+escape(LABELS.get(k,'추가 항목 · '+k))+'</dt><dd>'+readable(value[k])+'</dd>' for k in keys)+'</dl>'
    if isinstance(value,list):return '<ul>'+''.join('<li>'+readable(v)+'</li>' for v in value)+'</ul>'
    return escape(str(value)) if value is not None else '미기록'

def result_html(workspace,owner,document,stage,attempt=None,revision=None):
    workspace.original(owner,document)
    with workspace.workflow.connect() as db:
        current=workspace.workflow._job(db,document)['revision']
        rows=history(db,document,stage)
        row=next((r for r in rows if r['payload'] and (attempt is None or r['id']==attempt) and (revision is None or r['revision']==revision)),None)
        if row is None and attempt is None:
            q=db.execute('SELECT revision,payload FROM artifacts WHERE document=? AND kind=?'+(' AND revision=?' if revision is not None else '')+' ORDER BY revision DESC',(document,'verification' if stage=='verify' else 'analysis',revision) if revision is not None else (document,'verification' if stage=='verify' else 'analysis')).fetchone()
            if q:row={'revision':q['revision'],'id':None,'payload':q['payload'],'status':json.loads(q['payload']).get('status','NEEDS_REVIEW'),'evidence':'{}'}
        if row is None:raise Blocked('저장된 '+NAMES[stage]+' 결과가 없습니다. 실행 조건과 실패 이유를 확인하세요.')
        body=json.loads(row['payload']);rev=row['revision'];evidence=json.loads(row['evidence'])
        attempts=rows
    input_label='직원 수정이 반영된 최종 HTML' if evidence.get('input_html_kind')=='report.html' else 'Terra 원본 HTML'
    parts=[f'<h1>{NAMES[stage]} 결과</h1>',f'<p><strong>보고서 리비전 {rev}</strong> · 현재 리비전 {current} · '+('이전 결과 — 최신 결과가 아닙니다' if rev!=current else '현재 리비전 결과')+'</p>',
        '<p>입력: 해당 리비전의 원본 PDF와 '+input_label+'. A4 별도 수정본·변환 PDF를 검토한 결과가 아닙니다.</p>',
        '<p>보고서 본문은 수정하지 않았습니다. 수정 전후가 있으면 모델 제안이며 실제 적용된 수정이 아닙니다.</p>',
        '<p>판정: '+escape({'PASS':'통과','FAIL':'오류 발견','NEEDS_REVIEW':'확인 필요'}.get(row['status'],row['status']))+'</p>']
    if attempts and row['id']!=attempts[0]['id'] and attempts[0]['revision']==rev:parts.append('<p class="note">같은 리비전의 이전 실행 결과입니다. 최근 실행 상태: '+escape(attempts[0]['state'])+'</p>')
    parts.append('<details><summary>검토 입력 파일 식별</summary><p>검토 HTML SHA-256: '+escape(evidence.get('input_html_sha256','미기록'))+'</p><p>원본 PDF SHA-256: '+escape(evidence.get('input_pdf_sha256','미기록'))+'</p></details>')
    for key,title in [('issues','발견 사항 · 오류 및 확인 필요'),('sections','주요 사양 · 설비와 공정'),('conflicts','충돌하는 조건'),('questions','고객에게 확인할 질문')]:
        if key not in body:continue
        parts.append('<h2>'+title+'</h2>')
        if not body[key]:parts.append('<p>기록된 항목이 없습니다. 전체 내용의 정확성을 보증한다는 뜻은 아닙니다.</p>')
        for n,item in enumerate(body[key],1):
            parts.append(f'<article><h3>항목 {n}</h3>'+readable(item))
            if not isinstance(item,dict) or not any(k in item for k in ('reason','why','rationale','reason_ko')):parts.append('<p class="note">판단/질문 이유가 응답에 기록되지 않았습니다.</p>')
            if key=='issues' and isinstance(item,dict) and not any(k in item for k in ('severity','type')):parts.append('<p class="note">개별 오류/확인 필요 구분은 미기록입니다. 위 판정과 구분해 검토하세요.</p>')
            parts.append('</article>')
    if attempts:
        parts.append('<h2>보존된 실행 이력</h2><ul>')
        for old in attempts:
            url=f'/api/documents/{document}/{"review-verification.html" if stage=="verify" else "review-analysis.html"}?attempt={old["id"]}'
            parts.append('<li>'+ (f'<a href="{escape(url)}">실행 {old["id"]}</a>' if old['payload'] else f'실행 {old["id"]}')+f' · 리비전 {old["revision"]} · '+escape(old['state'])+' · '+escape(json.loads(old['evidence']).get('reason',''))+'</li>')
        parts.append('</ul>')
    return ('<!doctype html><html lang="ko"><meta charset="utf-8"><title>'+NAMES[stage]+' 결과</title><style>body{font:16px/1.75 sans-serif;max-width:1000px;margin:32px auto;padding:0 24px;color:#233747}h1,h2,h3{color:#17496f}article{border:1px solid #ccd7df;padding:16px;margin:14px 0}dt{font-weight:bold}dd{margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}.note{color:#8a4b00}a{color:#175a93}</style>'+''.join(parts)+'</html>').encode()

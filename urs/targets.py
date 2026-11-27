"""Immutable imported review targets. Never replace report revisions or generate HTML."""
import hashlib,json,uuid,io,zipfile,os,math
from datetime import datetime,timezone
from html import escape
from urs.workflow import Blocked
from urs.review_policy import decision,for_row,customer_context

MAX_HTML=12*1024*1024

def register(workspace,owner,document,parent_revision,name,payload):
    original=workspace.original(owner,document)
    if type(parent_revision) is not int or parent_revision<1:raise ValueError('부모 리비전을 선택하세요.')
    if not isinstance(payload,bytes) or not 0<len(payload)<=MAX_HTML:raise ValueError('HTML은 최대 12MB입니다.')
    try:text=payload.decode('utf-8')
    except UnicodeError:raise ValueError('UTF-8 HTML 파일이 필요합니다.') from None
    if '<html' not in text.lower() or '</html>' not in text.lower():raise ValueError('HTML 문서 시작과 끝 표시를 확인하세요. 파일을 자동 보정하지 않습니다.')
    if not isinstance(name,str) or not name.lower().endswith('.html') or len(name)>160:raise ValueError('HTML 파일명을 확인하세요.')
    digest=hashlib.sha256(payload).hexdigest()
    with workspace.workflow.connect() as db:
        parent=db.execute("SELECT 1 FROM artifacts WHERE document=? AND revision=? AND kind='report.html'",(document,parent_revision)).fetchone()
        if not parent:raise Blocked('선택한 부모 리비전의 저장 보고서가 없습니다. 보고서를 재생성하지 말고 기존 리비전을 확인하세요.')
        existing=db.execute('SELECT id FROM review_targets WHERE document=? AND parent_revision=? AND sha256=?',(document,parent_revision,digest)).fetchone()
        if existing:return existing['id']
        target=uuid.uuid4().hex
        db.execute('INSERT INTO review_targets VALUES(?,?,?,?,?,?,?,?,?)',(target,document,parent_revision,name,payload,digest,original['sha256'],owner,datetime.now(timezone.utc).isoformat()))
    return target

def get(workspace,owner,document,target):
    original=workspace.original(owner,document)
    if target.startswith(('stored:','displayed:')):
        parts=target.split(':')
        if len(parts)!=3 or parts[1]!=document or not parts[2].isdigit():raise Blocked('저장 리비전 식별자를 확인하세요.')
        revision=int(parts[2])
        workspace.processing.checked_html(document,revision)
        raw=workspace.processing.get(document,'report.html' if parts[0]=='displayed' else 'report.raw.html',revision)
        return {'id':target,'document':document,'parent_revision':revision,'name':f'URS 저장 리비전 {revision} · '+('사진 삽입 최종 HTML' if parts[0]=='displayed' else 'Terra 원본 HTML'),'payload':raw,'sha256':hashlib.sha256(raw).hexdigest(),'source_sha256':original['sha256'],'created':'기존 저장 파일','kind':'stored_final' if parts[0]=='displayed' else 'stored_revision'},original
    with workspace.workflow.connect() as db:row=db.execute('SELECT * FROM review_targets WHERE id=? AND document=?',(target,document)).fetchone()
    if row is None:raise Blocked('등록된 검증 대상을 찾을 수 없습니다.')
    row=dict(row);row['kind']='a4_import'
    if row['source_sha256']!=original['sha256'] or hashlib.sha256(row['payload']).hexdigest()!=row['sha256']:raise Blocked('등록된 검증 대상/원본 PDF 무결성 검사 실패')
    return row,original

def listing(workspace,owner,document):
    workspace.original(owner,document)
    with workspace.workflow.connect() as db:return [dict(r) for r in db.execute('SELECT id,parent_revision,name,sha256,source_sha256,created,length(payload) AS bytes FROM review_targets WHERE document=? ORDER BY rowid',(document,))]

def overview(workspace,owner,document,target):
    row,original=get(workspace,owner,document,target)
    from urs.reviews import INSTANCE
    with workspace.workflow.connect() as db:
        attempts=[dict(r) for r in db.execute('SELECT * FROM target_reviews WHERE target=? ORDER BY id DESC',(target,))]
    budget={}
    try:
        from urs.costing import review_quote
        for stage in ('verify','analyze'):
            budget[stage]=review_quote(workspace,owner,document,target,stage)
    except (ValueError,TypeError,KeyError) as exc:
        budget={stage:{'status':'UNVERIFIED','reason':str(exc),'budget_scope':'per_execution'} for stage in ('verify','analyze')}
    with workspace.workflow.connect() as db:request_count=db.execute('SELECT COUNT(*) FROM ai_usage WHERE document=?',(document,)).fetchone()[0]
    info={k:row[k] for k in ('id','parent_revision','name','sha256','source_sha256','created','kind')};info['bytes']=len(row['payload']);info['reviews']={}
    import re
    text=row['payload'].decode('utf-8',errors='replace');ends=list(re.finditer(r'</html\s*>',text,re.I))
    suffix=text[ends[-1].end():].strip() if ends else None
    info['document_end']={'closing_html_present':bool(ends),'trailing_code_fence_only':bool(ends and suffix=='```'),'trailing_text':suffix,'content_omission':'미확인 · 원본 PDF와 대조할 독립검증 대상입니다.'}
    for stage in ('verify','analyze'):
        current=next((r for r in attempts if r['stage']==stage),None)
        stored=next((r for r in attempts if r['stage']==stage and r['payload']),None)
        running=bool(current and current['state']=='running' and json.loads(current['evidence']).get('server_instance')==INSTANCE)
        verification=next((r for r in attempts if r['stage']=='verify'),None)
        blocked='실행 중입니다. 자동 재실행하지 않습니다.' if running else ''
        if stage=='analyze' and (not verification or verification['state']!='finished' or for_row(verification)!='PASS'):blocked='이 선택 대상의 독립검증이 PASS여야 합니다. 다른 보고서·다른 리비전 결과는 재사용하지 않습니다.'
        if request_count>=120:blocked=(blocked+' · ' if blocked else '')+'문서 요청 횟수 안전 상한(120회)입니다. 비용과 별개입니다.'
        failure=json.loads(current['evidence']).get('reason') if current and current['state']=='failed' else None
        if current and current['state']=='running' and not running:failure='이전 서버 작업의 완료 여부가 미확인입니다. API 사용 내역 확인 후 필요할 때만 수동 실행하세요.'
        if not running and budget.get(stage,{}).get('blocked'):
            blocked=(blocked+' · ' if blocked else '')+'이번 1회 예상 비용이 실행 한도를 넘습니다. 누적 사용액 때문이 아닙니다.'
        info['reviews'][stage]={'budget_preview':budget.get(stage),'status':for_row(current) if stage=='verify' else current['status'] if current else 'UNVERIFIED','can_run':not blocked,'blocked_reason':blocked,'running':running,'failure':failure,'available':stored is not None,'attempt':stored['id'] if stored else None,'older_attempt':bool(current and stored and current['id']!=stored['id'])}
        with workspace.workflow.connect() as db:receipt=db.execute('SELECT payload_sha256,completed FROM review_archive WHERE key=?',('target_reviews:'+str(stored['id']),)).fetchone() if stored else None
        info['reviews'][stage].update(saved=receipt is not None,saved_sha256=receipt['payload_sha256'] if receipt else None,saved_at=receipt['completed'] if receipt else None)
    return info

def run(workspace,owner,document,target,stage):
    import threading,time
    from urs.ai_settings import effective,signature
    from urs.ai import AIError,AIBlocked
    from urs.reviews import INSTANCE
    from urs.evaluation import fingerprint
    row,original=get(workspace,owner,document,target)
    with workspace._locks_guard:lock=workspace._run_locks.setdefault(document,threading.Lock())
    if not lock.acquire(False):raise Blocked('같은 문서의 다른 처리가 진행 중입니다. 완료 후 확인하세요.')
    try:
        ready=overview(workspace,owner,document,target)['reviews'][stage]
        if not ready['can_run']:raise Blocked(ready['blocked_reason'])
        with workspace.workflow.connect() as db:
            attempt=db.execute('INSERT INTO target_reviews(target,stage,state,status,payload,evidence,created) VALUES(?,?,?,?,?,?,?)',(target,stage,'running','UNVERIFIED',None,json.dumps({'server_instance':INSTANCE}),datetime.now(timezone.utc).isoformat())).lastrowid
        start=time.monotonic();result=None;provider=None
        evidence={'api_timeout_seconds':None,'api_wait_policy':'unlimited','target_id':target,'input_kind':'URS final HTML with source images' if row['kind']=='stored_final' else 'stored Terra raw HTML' if row['kind']=='stored_revision' else 'A4 imported HTML','input_revision':row['parent_revision'],'input_html_sha256':row['sha256'],'input_pdf_sha256':row['source_sha256']}
        try:
            config=effective(workspace.workflow,document=document)
        except Exception:
            config=None
        if config:evidence.update(model=config['model'],reasoning_effort=config['effort'],max_output_tokens=config['max_output_tokens'],ai_settings_signature=signature(config),pipeline_fingerprint=fingerprint())
        try:
            if config is None:raise AIBlocked('모델·effort·출력 한도 설정을 확인하세요. 유료 호출하지 않았습니다.')
            provider=workspace.processing.provider_for(document,config)
            findings=customer_context(workspace,target) if stage=='analyze' else []
            kwargs={'customer_findings':findings} if findings else {}
            result=provider.review_pdf('independent_verify' if stage=='verify' else 'technical_analysis',original['original'],original['name'],row['payload'].decode(),**kwargs)
            if stage=='analyze':evidence['customer_handoff']={'from_target':target,'findings':findings}
            if not isinstance(result,dict) or result.get('status') not in ('PASS','FAIL','NEEDS_REVIEW') or not isinstance(result.get('issues'),list):raise ValueError('검토 JSON의 status/issues 형식이 올바르지 않습니다.')
            if result['status']=='PASS' and result['issues'] and (stage!='verify' or decision(result)['blocking_count']):raise ValueError('PASS와 오류 목록이 모순됩니다.')
            if stage=='analyze' and any(not isinstance(result.get(k),list) for k in ('sections','conflicts','questions')):raise ValueError('분석 JSON의 sections/conflicts/questions 목록이 필요합니다.')
            status=decision(result)['status'] if stage=='verify' else result['status'];state='finished'
            if stage=='verify':evidence['acceptance_policy']={k:v for k,v in decision(result).items() if k!='customer_findings'}
        except Exception as exc:
            result=None;status='FAIL';state='failed'
            evidence['reason']=str(exc) if isinstance(exc,(AIError,AIBlocked,Blocked)) else '검토 결과 처리 실패: '+type(exc).__name__
            if getattr(exc,'diagnostics',None):evidence['api_diagnostics']=exc.diagnostics
        if getattr(provider,'request_manifest',None):evidence['transport_manifest']=provider.request_manifest
        evidence['finished_at']=datetime.now(timezone.utc).isoformat()
        evidence['elapsed_seconds']=round(time.monotonic()-start,3)
        from urs.review_archive import finish_attempt
        finish_attempt(workspace,'target_reviews',attempt,state,status,result,evidence)
    finally:lock.release()
    return overview(workspace,owner,document,target)

class Tasks:
    def __init__(self,workspace):self.workspace=workspace;self.lock=__import__('threading').Lock();self.active=set();self.errors={}
    def start(self,owner,document,target,stage):
        self.workspace.original(owner,document)
        key=(document,target,stage)
        with self.lock:
            if key in self.active:return {'state':'running'}
            info=overview(self.workspace,owner,document,target)['reviews'][stage]
            if not info['can_run']:raise Blocked(info['blocked_reason'])
            self.active.add(key);self.errors.pop(key,None)
        def worker():
            try:run(self.workspace,owner,document,target,stage)
            except Exception as exc:
                with self.lock:self.errors[key]=str(exc) if isinstance(exc,Blocked) else '작업을 접수했으나 실행에 실패했습니다. 상태/실패 기록을 확인하세요.'
            finally:
                with self.lock:self.active.discard(key)
        __import__('threading').Thread(target=worker,daemon=True).start()
        return {'state':'running'}
    def status(self,owner,document,target):
        info=overview(self.workspace,owner,document,target)
        with self.lock:
            for stage in ('verify','analyze'):
                if (document,target,stage) in self.errors:info['reviews'][stage].update(failure=self.errors[(document,target,stage)],running=False,can_run=False,blocked_reason=self.errors[(document,target,stage)])
                if (document,target,stage) in self.active:info['reviews'][stage].update(running=True,can_run=False,blocked_reason='실행 중입니다.')
        return info

def result_html(workspace,owner,document,target,stage,attempt):
    from urs.reviews import readable,NAMES,READABLE_CSS
    if stage=='verify' and target.startswith('displayed:'):
        from urs.review_results import render
        return render(workspace,owner,document,target,attempt)
    target_row,original=get(workspace,owner,document,target)
    with workspace.workflow.connect() as db:
        row=db.execute('SELECT * FROM target_reviews WHERE id=? AND target=? AND stage=?',(attempt,target,stage)).fetchone()
        latest=db.execute('SELECT id FROM target_reviews WHERE target=? AND stage=? ORDER BY id DESC LIMIT 1',(target,stage)).fetchone()
    if row is None or not row['payload']:raise Blocked('저장된 A4 검토 결과가 없습니다. 실패 이유를 확인하세요.')
    body=json.loads(row['payload']);ev=json.loads(row['evidence'])
    label='저장 리비전' if target_row['kind'] in ('stored_revision','stored_final') else 'A4'
    input_note=('화면에서 열람한 URS 최종 HTML(사진 포함)과 원본 PDF를 사용했습니다. 별도 A4 파일은 사용하지 않았습니다.' if target_row['kind']=='stored_final' else '선택 리비전의 원본 PDF + 저장 Terra 원본 HTML을 사용했습니다. 별도 A4 파일은 사용하지 않았습니다.') if target_row['kind'] in ('stored_revision','stored_final') else '원본 PDF + 등록 A4 HTML을 사용했습니다. 기존 Terra 원본 HTML의 검토 결과가 아닙니다.'
    verdict=for_row(row) if stage=='verify' else row['status']
    s='<header><h1>'+NAMES[stage]+' 결과</h1><p>'+escape(original['name'])+' · 보고서 버전 '+str(target_row['parent_revision'])+'</p><p class="result-verdict">'+escape({'PASS':'완료','FAIL':'오류 발견','NEEDS_REVIEW':'확인 필요'}.get(verdict,verdict))+'</p></header>'
    meta='<p>대상: '+escape(target_row['name'])+' · 부모 리비전 '+str(target_row['parent_revision'])+'</p><p>'+input_note+'</p><p>입력 HTML SHA-256: '+escape(ev.get('input_html_sha256','미기록'))+'</p><p>판정: '+escape(verdict)+'</p>'
    if stage=='analyze':
        transferred=ev.get('customer_handoff',{}).get('findings',[])
        if 'customer_handoff' not in ev:
            transferred=customer_context(workspace,target)
            if transferred:meta+='<p>이 과거 호출에 고객 확인 자료가 전송됐다는 기록은 없습니다.</p>'
        from urs.review_policy import analysis_body
        body=analysis_body(body,transferred)
    if latest['id']!=attempt:s+='<p class="note">이전 실행 결과</p>'
    meta+='<p>보고서 본문은 수정하지 않았습니다. 수정 전후는 제안이며 실제 적용되지 않았습니다.</p>'
    for key,title in [('issues','발견 사항'),('sections','주요 사양'),('conflicts','조건 충돌'),('questions','고객 질문과 필요한 이유')]:
        if body.get(key):s+='<h2>'+title+'</h2>'+readable(body[key])
    s+='<details class="technical"><summary>상세 정보</summary>'+meta+'</details>'
    return ('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+label+' '+NAMES[stage]+'</title><style>body{font:16px/1.7 sans-serif;max-width:1000px;margin:32px auto;padding:24px;color:#21405a}dt{font-weight:bold}dd{margin-bottom:16px;white-space:pre-wrap;overflow-wrap:anywhere}'+READABLE_CSS+'</style><main class="readable-document">'+s+'</main></html>').encode()

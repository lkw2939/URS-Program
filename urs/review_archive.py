"""Durable, owner-scoped review snapshots; independent of the current report selection."""
import hashlib,json
from datetime import datetime,timezone
from html import escape
from urs.workflow import Blocked


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS review_archive(
      key TEXT PRIMARY KEY, document TEXT NOT NULL, revision INTEGER NOT NULL,
      stage TEXT NOT NULL, target TEXT, attempt INTEGER, source TEXT NOT NULL,
      payload TEXT NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL,
      created TEXT NOT NULL, completed TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS review_archive_document ON review_archive(document,completed);
    CREATE TRIGGER IF NOT EXISTS preserve_review_archive_update BEFORE UPDATE ON review_archive
      BEGIN SELECT RAISE(ABORT,'saved review is immutable'); END;
    CREATE TRIGGER IF NOT EXISTS preserve_review_archive_delete BEFORE DELETE ON review_archive
      BEGIN SELECT RAISE(ABORT,'saved review cannot be deleted'); END;
    ''')
    for table,identity in [('target_reviews',['id','target','stage','created']),('review_attempts',['id','document','revision','stage','created'])]:
        same=' OR '.join(f'NEW.{name} IS NOT OLD.{name}' for name in identity)
        db.executescript(f'''
        CREATE TRIGGER IF NOT EXISTS preserve_{table}_delete BEFORE DELETE ON {table}
          BEGIN SELECT RAISE(ABORT,'review history cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS preserve_{table}_update BEFORE UPDATE ON {table}
          WHEN OLD.state!='running' OR OLD.payload IS NOT NULL OR {same}
          BEGIN SELECT RAISE(ABORT,'finished review is immutable'); END;
        ''')
    # Non-destructive migration: copy existing results; do not infer a missing completion date.
    for table in ('target_reviews','review_attempts'):
        for row in db.execute(f'SELECT id FROM {table} WHERE payload IS NOT NULL').fetchall():capture_attempt(db,table,row['id'])
    for row in db.execute("SELECT document,revision,kind,payload FROM artifacts WHERE kind IN ('verification','analysis')").fetchall():
        capture_artifact(db,row['document'],row['revision'],row['kind'],row['payload'])


def _store(db,key,document,revision,stage,target,attempt,source,payload,evidence,status,created,completed):
    if isinstance(payload,bytes):payload=payload.decode()
    digest=hashlib.sha256(payload.encode()).hexdigest()
    existing=db.execute('SELECT payload_sha256 FROM review_archive WHERE key=?',(key,)).fetchone()
    if existing:
        if existing['payload_sha256']!=digest:raise Blocked('저장된 검증 결과와 새 기록의 해시가 다릅니다. 기존 결과를 보존했습니다.')
        return
    db.execute('INSERT INTO review_archive VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(key,document,revision,stage,target,attempt,source,payload,evidence,status or 'UNVERIFIED',created,completed,digest))


def finish_attempt(workspace,table,attempt,state,status,payload,evidence):
    """Publish completion and its immutable snapshot in one SQLite transaction."""
    import sqlite3
    if table not in ('target_reviews','review_attempts'):raise ValueError('review source')
    encoded=json.dumps(evidence,ensure_ascii=False);result=json.dumps(payload,ensure_ascii=False) if payload is not None else None
    def update(db,phase,verdict,body,details):
        digest=(',digest=?' if table=='review_attempts' else '')
        args=[phase,verdict,body,details]
        if table=='review_attempts':args.append(hashlib.sha256(details.encode()).hexdigest())
        db.execute(f'UPDATE {table} SET state=?,status=?,payload=?,evidence=?{digest} WHERE id=?',(*args,attempt))
    try:
        with workspace.workflow.connect() as db:
            update(db,state,status,result,encoded);capture_attempt(db,table,attempt)
    except sqlite3.Error as error:
        reason='검토 응답 후 결과 DB 저장에 실패했습니다. 완료로 처리하지 않았으며 이전 저장 결과는 보존했습니다. 자동 유료 재시도하지 않습니다.'
        failure=json.dumps({**evidence,'reason':reason,'storage_error_type':type(error).__name__},ensure_ascii=False)
        try:
            with workspace.workflow.connect() as db:update(db,'failed','FAIL',None,failure)
        except sqlite3.Error:pass
        raise Blocked(reason) from None


def capture_attempt(db,table,attempt):
    if table not in ('target_reviews','review_attempts'):raise ValueError('review source')
    row=db.execute(f'SELECT * FROM {table} WHERE id=?',(attempt,)).fetchone()
    if not row or row['payload'] is None:return
    target=row['target'] if table=='target_reviews' else None
    if table=='review_attempts':document,revision=row['document'],row['revision']
    elif target.startswith(('stored:','displayed:')):
        parts=target.split(':')
        if len(parts)!=3 or not parts[2].isdigit():return
        document,revision=parts[1],int(parts[2])
    else:
        parent=db.execute('SELECT document,parent_revision FROM review_targets WHERE id=?',(target,)).fetchone()
        if not parent:return
        document,revision=parent['document'],parent['parent_revision']
    try:ev=json.loads(row['evidence'] or '{}')
    except (ValueError,TypeError):ev={}
    if not isinstance(ev,dict):ev={}
    _store(db,f'{table}:{attempt}',document,revision,row['stage'],target,attempt,table,row['payload'],row['evidence'] or '{}',row['status'],row['created'] or '',ev.get('finished_at',''))


def capture_artifact(db,document,revision,kind,payload):
    if kind not in ('verification','analysis'):return
    value=bytes(payload).decode() if not isinstance(payload,str) else payload
    digest=hashlib.sha256(value.encode()).hexdigest();body=json.loads(value)
    _store(db,f'artifact:{document}:{revision}:{kind}:{digest}',document,revision,'verify' if kind=='verification' else 'analyze',None,None,'legacy_artifact',value,'{}',body.get('status','UNVERIFIED'),'','')


def listing(workspace,owner,document):
    workspace.original(owner,document)
    with workspace.workflow.connect() as db:
        rows=db.execute('SELECT key,revision,stage,target,attempt,source,status,created,completed,payload_sha256 FROM review_archive WHERE document=? ORDER BY revision DESC,completed DESC,created DESC,key DESC',(document,)).fetchall()
    from urllib.parse import quote
    base=f'/api/documents/{document}/saved-review'
    return [{**dict(row),'input_label':('직원용 최종 HTML' if (row['target'] or '').startswith('displayed:') else 'Terra 원본 HTML' if (row['target'] or '').startswith('stored:') else '별도 등록 HTML' if row['source']=='target_reviews' else '과거 검증 자료 · 입력 형식 상세 확인'),'url':base+'.html?key='+quote(row['key'],safe=''),'json_url':base+'.json?key='+quote(row['key'],safe='')} for row in rows]


def saved(workspace,owner,document,key):
    original=workspace.original(owner,document)
    with workspace.workflow.connect() as db:row=db.execute('SELECT * FROM review_archive WHERE key=? AND document=?',(key,document)).fetchone()
    if not row:raise Blocked('이 문서에 저장된 검증 결과를 찾을 수 없습니다.')
    data=dict(row)
    if hashlib.sha256(data['payload'].encode()).hexdigest()!=data['payload_sha256']:raise Blocked('저장된 검증 결과의 무결성 확인이 필요합니다.')
    return data,original


def _date(value):
    if not value:return '과거 기록 · 완료 시각 미기록'
    try:
        from datetime import timedelta
        return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S (한국시간)')
    except (ValueError,TypeError):return '과거 기록 · 시각 확인 필요'


CSS='''body{font:16px/1.95 system-ui,sans-serif;background:#edf2f5;color:#183449;margin:0}main{max-width:210mm;margin:24px auto;padding:32px;background:white;box-sizing:border-box}h1{font-size:24px;overflow-wrap:anywhere}h2{font-size:20px}article{border:1px solid #ccdae4;padding:16px;margin:14px 0;border-radius:6px}p,dd,code{overflow-wrap:anywhere}p{margin:18px 0}article{margin:26px 0!important;padding:24px!important}dd{margin:0 0 12px;white-space:pre-wrap}dt{font-weight:600}.note{padding:12px;background:#edf5f8}a{color:#075b7b;margin-right:18px}details{margin:12px 0}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #d9e3ea;padding:12px 8px}small{display:block;color:#526b7c}@media(max-width:600px){main{margin:0;padding:18px}td,th{padding:8px 4px}a{display:inline-block}}@page{size:A4 portrait;margin:14mm}@media print{body{background:white}main{margin:0;padding:0}.actions{display:none}h2,h3{break-after:avoid}article{break-inside:auto}}'''

def _page(title,content):return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(title)+'</title><style>'+CSS+'</style></head><body><main>'+content+'</main></body></html>').encode()


def history_html(workspace,owner,document):
    rows=listing(workspace,owner,document);original=workspace.original(owner,document)
    selected=workspace.report_availability(owner,document)['selected'];current=selected['revision'] if selected else None
    s='<h1>저장된 검증 결과</h1><p>'+escape(original['name'])+'</p>'
    s+='<p>현재 직원용 보고서: '+('버전 '+str(current) if current else '열람 가능한 보고서 없음')+' · 저장 결과 '+str(len(rows))+'건</p>'
    if not rows:s+='<p>저장된 결과가 없습니다.</p>'
    for r in rows:
        from urllib.parse import quote
        open_url=f'/api/documents/{document}/saved-review-open.html?key='+quote(r['key'],safe='')
        name='독립검증' if r['stage']=='verify' else '기술분석'
        scope='현재 보고서 버전' if r['revision']==current else '이전 보고서 버전'
        s+='<article data-saved-key="'+escape(r['key'],quote=True)+'"><h2>'+name+' · 보고서 버전 '+str(r['revision'])+'</h2><p>입력 대상: '+escape(r['input_label'])+'</p><p>'+scope+' · 저장 판정 '+escape(r['status'])+'</p><p>'+_date(r['completed'])+'</p><p class="actions"><a href="'+escape(open_url,quote=True)+'" target="_blank" rel="noopener">'+name+' 결과 보기</a><a download="'+r['stage']+'-result-v'+str(r['revision'])+'.html" href="'+escape(r['url'],quote=True)+'">HTML 내려받기</a></p></article>'
    return _page('저장된 검증 결과',s)


def result_html(workspace,owner,document,key,allow_edit=True):
    row,original=saved(workspace,owner,document,key);body=json.loads(row['payload'])
    from urs.reviews import readable,NAMES
    from urllib.parse import quote
    base=f'/api/documents/{document}'
    s='<h1>'+NAMES[row['stage']]+' 저장 결과</h1><h2>'+escape(original['name'])+'</h2><p>검증한 보고서 버전 '+str(row['revision'])+' · 저장 판정 '+escape(row['status'])+'</p><p>검증 완료 '+_date(row['completed'])+'</p><p class="note">보기 전용</p>'
    s+='<p class="actions"><a href="/?document='+escape(document,quote=True)+'&amp;step=2">URS 보고서 검토로 돌아가기</a><a href="'+base+'/saved-reviews.html">저장된 검증 결과 목록</a><a download="'+row['stage']+'-result-v'+str(row['revision'])+'.html" href="'+base+'/saved-review.html?key='+quote(key,safe='')+'">HTML 내려받기</a></p>'
    for field,title in [('issues','발견 사항'),('sections','주요 사양'),('conflicts','조건 충돌'),('questions','고객 질문')]:
        if field in body:s+='<h2>'+title+'</h2>'+(readable(body[field]) if body[field] else '<p>기록된 항목이 없습니다.</p>')
    try:details=json.loads(row['evidence'])
    except (ValueError,TypeError):details={'note':'과거 전송 상세를 읽을 수 없습니다. 저장 결과 본문과 구분해 확인하세요.'}
    if allow_edit and row['source']=='target_reviews':s+='<p class="actions"><a href="'+base+'/saved-review-open.html?key='+quote(key,safe='')+'">URS에서 이 검증 결과 열기 · 문구 수정</a></p>'
    if not allow_edit:s+='<p class="note">원래 보고서를 열 수 없어 읽기 전용 보관본을 표시합니다.</p>'
    s+='<details><summary>상세 정보</summary><p>저장 당시 결과의 읽기 전용 사본입니다. 현재 보고서의 새 검증 판정으로 사용하지 않습니다.</p><p>검증 결과 JSON SHA-256: '+escape(row['payload_sha256'])+'</p><p>기록 출처: '+escape(row['source'])+' · 실행 '+escape(str(row['attempt'] or '과거 파일'))+'</p>'+readable(details)+'</details>'
    page=_page(NAMES[row['stage']]+' 저장 결과',s)
    from urs.reviews import READABLE_CSS
    return page.replace(b'</style>',READABLE_CSS.encode()+b'</style>',1)


def open_html(workspace,owner,document,key):
    row,_=saved(workspace,owner,document,key)
    try:
        if row['source']=='target_reviews':
            from urs.targets import result_html as original_result
            return original_result(workspace,owner,document,row['target'],row['stage'],row['attempt'])
        if row['source']=='review_attempts':
            from urs.reviews import result_html as original_result
            return original_result(workspace,owner,document,row['stage'],row['attempt'])
    except Blocked:pass
    return result_html(workspace,owner,document,key,allow_edit=False)

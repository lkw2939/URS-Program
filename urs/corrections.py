"""Explicit, append-only employee corrections. Never calls a model or changes old artifacts."""
import hashlib,json,uuid
from datetime import datetime,timezone
from urs.workflow import Blocked
from urs.gates import Status
from urs.review_results import load,plan_changes,replay


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS correction_plans(id TEXT PRIMARY KEY,document TEXT,owner TEXT,target TEXT,attempt INTEGER,parent_revision INTEGER,parent_sha TEXT,patches TEXT,created TEXT,result_revision INTEGER)')

def preview(workspace,owner,document,target,attempt,changes):
    data=load(workspace,owner,document,target,attempt)
    if not data['can_edit']:raise Blocked('이 검증 결과의 보고서가 현재 보고서와 다르거나 이전 실행 결과입니다. 현재 보고서의 결과에서 수정하세요.')
    original=workspace.original(owner,document)
    with workspace.workflow.connect() as db:
        from urs.saved_reports import read_final
        payload,info=read_final(db,document,data['editable_revision'])
    if info['integrity']!='verified':raise Blocked('원본/최종 HTML 무결성 자료가 없어 자동 수정을 적용할 수 없습니다.')
    if isinstance(changes,list) and any(str(c.get('issue_id')) in data['applied_issue_ids'] for c in changes if isinstance(c,dict)):raise Blocked('이미 반영한 항목입니다. 남은 항목이나 새 직접 수정 항목을 선택하세요.')
    patches=plan_changes(payload.decode(),data['issues'],changes,single_page=original['pages']==1,page_count=original['pages'])
    ident=uuid.uuid4().hex
    with workspace.workflow.connect() as db:db.execute('INSERT INTO correction_plans VALUES(?,?,?,?,?,?,?,?,?,NULL)',(ident,document,owner,target,attempt,data['editable_revision'],data['editable_sha256'],json.dumps(patches,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
    return {'plan_id':ident,'revision':data['editable_revision'],'changes':[{'issue_id':p['issue_id'],'page':p['page'],'before':p['before'],'after':p['after'],'basis':p.get('basis',''),'occurrence':p.get('occurrence',1)} for p in patches],'note':'아직 보고서에 반영하지 않았습니다. 선택한 수정 적용을 눌러야 새 이력으로 저장됩니다.'}


def apply(workspace,owner,document,ident):
    import threading
    original=workspace.original(owner,document)
    if hashlib.sha256(original['original']).hexdigest()!=original['sha256']:raise Blocked('원본 PDF 무결성 검사 실패')
    with workspace._locks_guard:lock=workspace._run_locks.setdefault(document,threading.Lock())
    if not lock.acquire(False):raise Blocked('다른 작업이 실행 중입니다. 완료 후 수정 사항을 적용하세요.')
    try:
        with workspace.workflow.connect() as db:row=db.execute('SELECT * FROM correction_plans WHERE id=? AND owner=? AND document=?',(ident,owner,document)).fetchone()
        if row is None:raise Blocked('수정안이 없거나 접근할 수 없습니다.')
        plan=dict(row)
        if plan['result_revision'] is not None:return {'revision':plan['result_revision'],'report_url':f"/api/documents/{document}/report.html?revision={plan['result_revision']}",'already_applied':True}
        state=load(workspace,owner,document,plan['target'],plan['attempt'])
        if not state['can_edit'] or state['editable_sha256']!=plan['parent_sha']:raise Blocked('보고서 또는 검증 결과가 바뀌었습니다. 수정안을 다시 확인하세요.')
        parent=workspace.report_html(owner,document,revision=plan['parent_revision']);patches=json.loads(plan['patches']);final=replay(parent.decode(),patches).encode()
        if hashlib.sha256(parent).hexdigest()!=plan['parent_sha']:raise Blocked('부모 보고서 무결성 검사 실패')
        with workspace.workflow.connect() as db:items={r['kind']:bytes(r['payload']) for r in db.execute('SELECT kind,payload FROM artifacts WHERE document=? AND revision=?',(document,plan['parent_revision']))}
        metadata=json.loads(items['report-metadata']);quality={'status':'UNVERIFIED','reason':'기존 보고서의 배치 상태를 유지합니다. 수정은 선택한 본문에만 적용했습니다.','pages':[]}
        if metadata.get('layout_contract') and metadata.get('layout_status')=='PASS':
            from urs.layout_audit import inspect
            quality=inspect(final.decode(),workspace.original(owner,document)['pages'])
            if quality['status']!='PASS':raise Blocked('수정문 적용 후 페이지 넘침 또는 사진 표시 확인이 필요합니다. 기존 보고서는 유지했습니다. 문장/배치를 검토하세요.')
        receipt={'parent_revision':plan['parent_revision'],'parent_sha256':plan['parent_sha'],'source_attempt':plan['attempt'],'source_target':plan['target'],'plan_id':ident,'patches':patches,'source_revision':state['revision'],'resolved_issue_ids':list(set(state['applied_issue_ids'])|{p['issue_id'] for p in patches if not p['issue_id'].startswith('manual:')})}
        receipt_bytes=json.dumps(receipt,ensure_ascii=False).encode()
        metadata.update(generation_kind='employee_selected_correction',parent_revision=plan['parent_revision'],raw_model_revision=metadata.get('raw_model_revision',plan['parent_revision']),final_sha256=hashlib.sha256(final).hexdigest(),correction_patch_sha256=hashlib.sha256(receipt_bytes).hexdigest())
        if metadata.get('layout_contract'):metadata['layout_status']=quality['status']
        new_items={k:items[k] for k in ('report.raw.html','report-images','image-bindings')}
        new_items.update({'report.html':final,'correction-patch':receipt_bytes,'report-metadata':json.dumps(metadata,ensure_ascii=False).encode(),'layout-audit':json.dumps(quality,ensure_ascii=False).encode()})
        with workspace.workflow.connect() as db:
            from urs.saved_reports import inspect_document
            job=workspace.workflow._job(db,document);selected=inspect_document(db,document,job['revision'])['selected']
            if not selected or selected['revision']!=plan['parent_revision']:raise Blocked('현재 보고서가 변경되었습니다. 수정안을 다시 확인하세요.')
            revision=job['revision']+1;content=json.loads(job['content']);content['revision']=revision
            for kind,value in new_items.items():db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(document,revision,kind,value))
            db.execute('UPDATE jobs SET revision=?,content=? WHERE id=?',(revision,json.dumps(content),document))
            workspace.workflow._record(db,document,'source',revision,'integrity',Status.PASS,{'source_sha256':metadata['source_sha256'],'reason':'기존 원본 PDF 보존'},'original-preserved','1')
            workspace.workflow._record(db,document,'report',revision,'html-v1',Status.PASS,{'reason':'직원이 선택한 오류 수정 적용 · 독립 재검증 필요','parent_revision':plan['parent_revision'],'source_attempt':plan['attempt'],'outputs':{k:hashlib.sha256(v).hexdigest() for k,v in new_items.items()},'only_selected_text_changed':True,'final_sha256':metadata['final_sha256']},'employee-selected-correction','1')
            workspace.workflow._event(db,document,revision,'selected_corrections_applied',{'parent_revision':plan['parent_revision'],'attempt':plan['attempt'],'plan_id':ident,'issue_ids':[p['issue_id'] for p in patches]})
            db.execute('UPDATE correction_plans SET result_revision=? WHERE id=?',(revision,ident))
        return {'revision':revision,'report_url':f'/api/documents/{document}/report.html?revision={revision}','needs_reverification':True}
    finally:lock.release()

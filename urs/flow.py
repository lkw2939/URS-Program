"""Server-derived screen prerequisites. Navigation never changes a report or calls AI."""
import hashlib,json
from urs.workflow import Blocked
from urs.review_policy import for_row

TITLES=['보고서 확인','독립검증·문구 수정','CSS 배치','최종 독립검증','기술분석','직원 승인']

def state(workspace,owner,document):
    original=workspace.original(owner,document)
    selected=workspace.report_availability(owner,document)['selected']
    def artifact(rev,kind):
        with workspace.workflow.connect() as db:r=db.execute('SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind=?',(document,rev,kind)).fetchone()
        return json.loads(r['payload']) if r else {}
    def review(rev,stage):
        with workspace.workflow.connect() as db:return db.execute('SELECT * FROM target_reviews WHERE target=? AND stage=? ORDER BY id DESC LIMIT 1',(f'displayed:{document}:{rev}',stage)).fetchone()
    def text_ready(rev):
        r=review(rev,'verify')
        if r:
            if r['state']!='finished' or not r['payload']:return False,'독립검증이 정상 완료돼야 합니다. 실행 상태와 실패 이유를 확인하세요.'
            if for_row(r)=='PASS':return True,'독립검증 통과'
            from urs.review_results import issues
            entries=issues(json.loads(r['payload']),original['pages'])
            if entries and all(i['customer_confirmation'] or i['kind']=='layout' or (i['kind']=='program' and not i.get('text_integrity')) for i in entries):return True,'번역 지적 없음 · 표시 문제는 CSS 단계와 최종 검증에서 확인합니다.'
            return False,'독립검증 결과에서 남은 번역 오류·확인 항목과 본문의 숨은 문자 문제를 수정하고 저장하세요.'
        meta=artifact(rev,'report-metadata')
        if meta.get('generation_kind')=='employee_selected_correction':
            receipt=artifact(rev,'correction-patch');target=receipt.get('source_target','')
            with workspace.workflow.connect() as db:source=db.execute("SELECT * FROM target_reviews WHERE id=? AND target=? AND stage='verify'",(receipt.get('source_attempt'),target)).fetchone()
            if source and source['state']=='finished' and source['payload'] and target.startswith(f'displayed:{document}:'):
                from urs.correction_context import continuation
                from urs.review_results import issues
                root=int(target.rsplit(':',1)[1]);valid,applied=continuation(workspace,owner,document,rev,root,target,source['id'])
                body=json.loads(source['payload']);entries=issues(body,original['pages'])
                def resolved(item):
                    patch=applied.get(item['id'],{})
                    return item['customer_confirmation'] or item['kind']=='layout' or (item['kind']=='program' and not item.get('text_integrity')) or (item['kind']=='error' and bool(patch)) or (item.get('can_manual') and patch.get('confirmed') and len(patch.get('basis',''))>=5)
                if valid and (entries or body.get('status')=='PASS') and all(resolved(i) for i in entries):return True,'문구 수정 저장 완료 · CSS 후 최종 재검증은 필수입니다.'
                if valid:return False,'기존 검증 결과에서 아직 적용하지 않은 번역·본문 수정 항목을 확인하고 저장하세요. 이 단계에서 유료 검증을 다시 실행할 필요는 없습니다.'
        return False,'이 보고서의 독립검증을 실행하고 결과를 확인하세요.'
    report=bool(selected);revision=selected['revision'] if selected else None
    meta=artifact(revision,'report-metadata') if report else {}
    css_kind=meta.get('generation_kind')=='model_layout_edit'
    parent=meta.get('parent_revision') if css_kind else revision
    text,why=text_ready(parent) if parent else (False,'먼저 저장된 보고서가 필요합니다.')
    quality=artifact(revision,'layout-audit') if report else {}
    receipt=artifact(revision,'layout-refinement') if report else {}
    css=bool(css_kind and quality.get('status')=='PASS' and receipt.get('accepted') and receipt.get('parent_revision')==parent and receipt.get('final_sha256')==hashlib.sha256(workspace.report_html(owner,document,revision=revision)).hexdigest())
    verify=review(revision,'verify') if report else None;analysis=review(revision,'analyze') if report else None
    final=bool(css and verify and verify['state']=='finished' and for_row(verify)=='PASS')
    analyzed=bool(final and analysis and analysis['state']=='finished' and analysis['status']=='PASS')
    legacy=workspace.status(owner,document)
    approved=bool(legacy['approved'])
    done=[report,text,css,final,analyzed,approved]
    reasons=['먼저 원본으로 HTML 보고서를 생성해 저장하세요.',why,'이 보고서의 CSS·배치 다듬기를 실행하고 화면 검사를 통과해야 합니다.','CSS가 반영된 현재 보고서의 최종 독립검증이 PASS여야 합니다.','현재 보고서의 기술분석을 실행하고 남은 항목을 확인하세요.',legacy.get('qualification',{}).get('blocked') or '최종 HTML 확인과 직원 승인 조건을 충족해야 합니다.']
    steps=[];reachable=True
    for i,title in enumerate(TITLES):
        steps.append({'index':i,'title':title,'passed':bool(done[i]),'can_enter':reachable,'reason':'' if done[i] else reasons[i]})
        reachable=reachable and bool(done[i])
    initial=review(parent,'verify') if parent else None
    if not initial and parent:
        patch=artifact(parent,'correction-patch')
        if patch.get('source_attempt'):
            with workspace.workflow.connect() as db:initial=db.execute('SELECT * FROM target_reviews WHERE id=?',(patch['source_attempt'],)).fetchone()
    initial_info={'target':initial['target'],'attempt':initial['id'],'revision':int(initial['target'].rsplit(':',1)[1])} if initial and initial['payload'] and initial['state']=='finished' else None
    return {'document_name':original['name'],'initial_review':initial_info,'revision':revision,'steps':steps,'frontier':next((s['index'] for s in steps if not s['passed']),5),'text_note':why}

def enter(workspace,owner,document,index,revision):
    info=state(workspace,owner,document)
    if type(index) is not int or not 0<=index<len(TITLES):raise ValueError('단계를 확인하세요.')
    if revision!=info['revision']:raise Blocked('보고서가 변경됐습니다. 현재 보고서 상태를 다시 확인하세요.')
    if not info['steps'][index]['can_enter']:
        missing=next(s for s in info['steps'][:index] if not s['passed'])
        raise Blocked(str(missing['index']+1)+'단계를 먼저 완료하세요. '+missing['reason'])
    return {**info,'active':index}

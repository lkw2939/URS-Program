"""Separate source/customer questions from translation acceptance, without rewriting history."""
import json

VERSION='translation-only-v1'

def decision(body):
    from urs.review_results import issues
    entries=issues(body)
    deferred=[i for i in entries if i['customer_confirmation']]
    blocking=[i for i in entries if not i['customer_confirmation']]
    status=body.get('status','UNVERIFIED')
    # A bare failure, unknown finding, program defect or uncertain translation stays blocked.
    if deferred and not blocking and status in ('PASS','FAIL','NEEDS_REVIEW'):status='PASS'
    elif status=='PASS' and blocking:status='NEEDS_REVIEW'
    return {'status':status,'model_status':body.get('status','UNVERIFIED'),'policy':VERSION,'customer_findings':deferred,'blocking_count':len(blocking)}

def for_row(row):
    if not row or row['state']!='finished' or not row['payload']:return row['status'] if row else 'UNVERIFIED'
    return decision(json.loads(row['payload']))['status']

def customer_context(workspace,target):
    """Carry pending source questions through CSS/correction ancestry, never old verdicts."""
    result=[];seen=set();visited=set();current=target
    while current and current not in visited and len(visited)<100:
        visited.add(current)
        with workspace.workflow.connect() as db:
            row=db.execute("SELECT * FROM target_reviews WHERE target=? AND stage='verify' ORDER BY id DESC LIMIT 1",(current,)).fetchone()
            meta=None
            if current.startswith('displayed:'):
                _,document,revision=current.split(':')
                meta=db.execute("SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind='report-metadata'",(document,int(revision))).fetchone()
        if current==target and row and row['state']!='finished':return []
        if row and row['state']=='finished' and row['payload']:
            for item in decision(json.loads(row['payload']))['customer_findings']:
                key=(''.join((item['question'] or item['problem'] or item['title']).split()),tuple(item['pages']))
                if key not in seen:
                    seen.add(key);result.append({**item,'origin_target':current,'origin_attempt':row['id']})
        value=json.loads(meta['payload']) if meta else {}
        parent=value.get('parent_revision')
        current=f'displayed:{document}:{parent}' if value.get('generation_kind') in ('model_layout_edit','employee_selected_correction') and type(parent) is int and parent>0 else None
    return result

def context_part(findings):
    return {'type':'input_text','text':'독립검증에서 기술분석으로 이관한 고객 확인 사항입니다. 원문과 대조하여 questions에 중복 없이 포함하고 필요한 이유를 설명하세요. 고객 답변을 받은 것으로 간주하거나 보고서 문장을 임의로 바꾸지 마세요.\n'+json.dumps(findings,ensure_ascii=False)}


def analysis_body(body,findings):
    """Render carried questions once even if the model omitted them; preserve raw model JSON."""
    result=dict(body);questions=list(body.get('questions',[]))
    def key(value):
        text=value.get('question_ko',value.get('question','')) if isinstance(value,dict) else str(value)
        return ''.join(str(text).split()).rstrip('?.。')
    seen={key(q) for q in questions}
    for item in findings:
        question=item['question'] or item['problem'] or item['title']
        q={'page':item['page'],'question_ko':question,'reason_ko':item['why'] or item['problem'],'origin':'독립검증에서 이관 · 고객 답변 미확인'}
        if item['references']:q['evidence']=item['references']
        if item['source_en']:q['source_en']=item['source_en']
        if key(q) not in seen:questions.append(q);seen.add(key(q))
    result['questions']=questions
    return result

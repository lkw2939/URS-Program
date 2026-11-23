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
    """Only the latest finished verification of this exact immutable target; no old-version mixing."""
    with workspace.workflow.connect() as db:
        row=db.execute("SELECT * FROM target_reviews WHERE target=? AND stage='verify' ORDER BY id DESC LIMIT 1",(target,)).fetchone()
    if not row or row['state']!='finished' or not row['payload']:return []
    return decision(json.loads(row['payload']))['customer_findings']

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

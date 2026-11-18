"""Read-only settlement preview. Missing usage is never treated as zero cost."""
import json
from decimal import Decimal

def preview(db,document,input_rate,output_rate):
    items=[]
    for row in db.execute('SELECT id,task,model,state,reserved,usage FROM ai_usage WHERE document=? ORDER BY id',(document,)):
        r=dict(row)
        try:usage=json.loads(r['usage']) if r['usage'] else {}
        except (ValueError,TypeError):usage={}
        if not isinstance(usage,dict):usage={}
        incoming=usage.get('input_tokens');outgoing=usage.get('output_tokens')
        valid=r['state'] in ('completed','failed') and type(incoming) is int and incoming>=0 and type(outgoing) is int and outgoing>=0
        estimate=(Decimal(incoming)*Decimal(str(input_rate))+Decimal(outgoing)*Decimal(str(output_rate)))/Decimal(1000000) if valid else None
        items.append({'call_id':r['id'],'task':r['task'],'model':r['model'],'state':r['state'],'reserved_usd':r['reserved'],
                      'usage_available':valid,'input_tokens':incoming if valid else None,'output_tokens':outgoing if valid else None,
                      'cost_at_current_configured_rates_usd':float(estimate) if estimate is not None else None,
                      'settlement_action':'단가/서비스 조건 확인 후 개별 정산 검토 가능' if valid else '사용량 미확인: 예약 유지, 0원 처리 불가'})
    known=sum(x['cost_at_current_configured_rates_usd'] for x in items if x['usage_available'])
    unknown=sum(x['reserved_usd'] for x in items if not x['usage_available'])
    return {'calls':items,'known_usage_estimate_usd':known,'unknown_usage_reservations_kept_usd':unknown,
            'hypothetical_total_at_current_rates_usd':known+unknown,'applied':False,
            'rate_caveat':'현재 설정 단가로만 계산한 미리보기입니다. 과거 적용 단가·캐시·서비스 계층·일괄 처리·실제 청구액을 입증하지 않습니다. 장부나 예산은 바꾸지 않았습니다.'}


def ledger(db,document):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='ai_call_costs'").fetchone()
    snapshots={r['call_id']:json.loads(r['payload']) for r in db.execute('SELECT * FROM ai_call_costs')} if exists else {}
    calls=[]
    for row in db.execute('SELECT id,task,model,state,reserved,usage FROM ai_usage WHERE document=? ORDER BY id',(document,)):
        r=dict(row);snapshot=snapshots.get(r['id'],{});usage=snapshot.get('usage')
        if usage is None:
            try:usage=json.loads(r['usage'] or '{}')
            except (TypeError,ValueError):usage={}
        if not isinstance(usage,dict):usage={}
        reason=snapshot.get('settlement_state','legacy_rates_unknown' if 'input_tokens' in usage and 'output_tokens' in usage else 'usage_unknown')
        calls.append({'call_id':r['id'],'task':r['task'],'model':r['model'],'state':r['state'],'original_estimate_usd':r['reserved'],'settlement_state':reason,'actual_cost_usd':snapshot.get('actual_cost_usd'),'usage':usage,'price_snapshot':snapshot.get('quote',{}).get('pricing'),'note':'사용량과 요청 당시 단가로 정산' if reason=='settled' else '미확인 금액: 0원 처리하지 않으며 실제 지출에도 합산하지 않습니다.'})
    return {'calls':calls,'settled_usage_cost_usd':sum(c['actual_cost_usd'] for c in calls if c['actual_cost_usd'] is not None),'unresolved_count':sum(c['actual_cost_usd'] is None for c in calls),'unresolved_original_estimates_usd':sum(c['original_estimate_usd'] for c in calls if c['actual_cost_usd'] is None),'request_count':len(calls),'request_count_limit':120,'note':'문서 누적 사용 이력입니다. 합계는 1회 실행 한도에서 빼지 않습니다. 미확인 예약액은 실지출이 아닙니다. 실제 청구서/잔액은 OpenAI에서 별도 확인하세요.'}

def server_preview(workspace,owner,document):
    from urs.costing import rates
    workspace.original(owner,document)
    with workspace.workflow.connect() as db:result=ledger(db,document)
    return {**result,'per_execution_cap_usd':rates()['cap_usd'],'budget_scope':'per_execution','provider_balance_usd':None,'read_only':True}

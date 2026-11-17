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


def server_preview(workspace,owner,document):
    import os,math
    workspace.original(owner,document)
    budget=float(os.environ.get('URS_AI_BUDGET_USD','0'));ir=float(os.environ.get('URS_AI_INPUT_USD_PER_MILLION','0'));out=float(os.environ.get('URS_AI_OUTPUT_USD_PER_MILLION','0'))
    if not all(math.isfinite(v) and v>0 for v in (budget,ir,out)):raise ValueError('예산·단가 설정을 확인하세요.')
    with workspace.workflow.connect() as db:
        result=preview(db,document,ir,out)
        count,total=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0) FROM ai_usage WHERE document=?',(document,)).fetchone()
    result.update(document_budget_usd=budget,request_count=count,request_count_limit=120,reserved_total_usd=total,input_rate_per_million=ir,output_rate_per_million=out,rate_source='실행 중인 서버의 현재 설정',read_only=True)
    return result

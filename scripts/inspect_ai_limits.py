"""Operator-only read-only AI reservation audit. Never imports Workspace or calls AI."""
import argparse,ast,json,math,os,sqlite3,sys
from pathlib import Path
from dotenv import dotenv_values
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urs.usage_audit import preview
ROOT=Path(__file__).resolve().parents[1]
KEYS=('URS_AI_BUDGET_USD','URS_AI_INPUT_USD_PER_MILLION','URS_AI_OUTPUT_USD_PER_MILLION','URS_OPENAI_MAX_OUTPUT_TOKENS')

def instruction(stage):
    from urs.ai import review_text
    return review_text('independent_verify' if stage=='verify' else 'technical_analysis')

def audit(root,data,document,revision=None,stage='verify'):
    config=dotenv_values(root/'.env',interpolate=False)
    values={k:os.environ[k] if k in os.environ else config.get(k) for k in KEYS}
    result={'read_only':True,'api_calls':0,'document_id':document,'evaluation_scope':'Current CLI environment and current .env; not a snapshot of the historical failed request or proof of the running server environment.'}
    with sqlite3.connect(data.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        doc=db.execute('SELECT d.original,p.owner,j.revision FROM documents d JOIN projects p ON p.id=d.project JOIN jobs j ON j.id=d.id WHERE d.id=?',(document,)).fetchone()
        if doc is None:raise ValueError('문서를 찾지 못했습니다.')
        current=doc['revision'];target=current if revision is None else revision
        raw=db.execute("SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind='report.raw.html'",(document,target)).fetchone()
        web=db.execute('SELECT payload FROM ai_settings WHERE owner=? ORDER BY version DESC LIMIT 1',(doc['owner'],)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='ai_settings'").fetchone() else None
        tokens=json.loads(web[0])['max_output_tokens'] if web else int(values['URS_OPENAI_MAX_OUTPUT_TOKENS'] or '5000')
        budget=float(values['URS_AI_BUDGET_USD'] or '0');ir=float(values['URS_AI_INPUT_USD_PER_MILLION'] or '0');out=float(values['URS_AI_OUTPUT_USD_PER_MILLION'] or '0')
        if not all(math.isfinite(n) and n>0 for n in (budget,ir,out)) or type(tokens) is not int or tokens<1:raise ValueError('현재 숫자 설정이 올바르지 않습니다.')
        counts=[dict(r) for r in db.execute('SELECT state,COUNT(*) AS calls,COALESCE(SUM(reserved),0) AS reserved_usd FROM ai_usage WHERE document=? GROUP BY state',(document,))]
        calls=sum(x['calls'] for x in counts);reserved=sum(x['reserved_usd'] for x in counts)
        reserve=((len(doc['original'])+len(bytes(raw[0]))+len(instruction(stage).encode()))*ir+tokens*out)/1_000_000 if raw else None
        if db.execute("SELECT 1 FROM pragma_table_info('ai_usage') WHERE name='usage'").fetchone():result['settlement_preview']=preview(db,document,ir,out)
        else:result['settlement_preview']={'applied':False,'reason':'usage 필드가 없어 정산 자료를 확인할 수 없습니다.'}
        result.update(current_revision=current,target_revision=target,target_is_previous=target!=current,target_raw_html_exists=bool(raw),stage=stage,max_output_tokens=tokens,output_setting_source='web' if web else 'environment/default',
            budget_usd=budget,input_usd_per_million=ir,output_usd_per_million=out,request_count=calls,request_count_limit=120,reserved_usd=reserved,ledger_by_state=counts,
            next_reservation_usd=reserve,request_count_limit_reached=calls>=120,budget_limit_for_target=(reserved+reserve>budget) if reserve is not None else None,
            historical_limit_cause='Unverified: the old generic failure does not snapshot request count, reserved total and budget.',
            reservation_note='Application reservation estimate, not OpenAI billing. PDF byte length is used as a token proxy; failed/reserved calls also count. No reservation is reset or released.')
    return result

def main():
    p=argparse.ArgumentParser(description='실제 DB 요청 수/예약예산과 현재 설정 읽기 전용 점검; API 호출 없음')
    p.add_argument('--document',required=True);p.add_argument('--data',type=Path,default=ROOT/'.runtime/workspace.sqlite');p.add_argument('--revision',type=int);p.add_argument('--stage',choices=['verify','analyze'],default='verify');args=p.parse_args()
    try:print(json.dumps(audit(ROOT,args.data,args.document,args.revision,args.stage),ensure_ascii=False,indent=2));return 0
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):print('읽기 전용 점검 실패: DB 경로·문서 ID·숫자 설정을 확인하세요. DB/설정은 변경하지 않았습니다.',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())

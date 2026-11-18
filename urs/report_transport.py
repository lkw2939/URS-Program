"""Unlimited AI response waiting and safe per-attempt diagnostics; no body logging."""
import json,os,time,socket,urllib.request,urllib.error,http.client
from urs.ai import AIError,AIBlocked

NETWORK_TIMEOUT=None # Explicit None disables the client socket deadline on every OpenAI route.

def timeout_value(value):
    if value is None:return None
    if type(value) is not int or not 10<=value<=3600:raise ValueError('보고서 API 대기시간은 10~3600초의 정수입니다.')
    return value

def settings(workflow,owner=None,document=None):
    with workflow.connect() as db:
        if owner is None:
            row=db.execute('SELECT p.owner FROM documents d JOIN projects p ON p.id=d.project WHERE d.id=?',(document,)).fetchone()
            owner=row[0] if row else None
        row=db.execute('SELECT version,seconds FROM report_timeouts WHERE owner=? ORDER BY version DESC LIMIT 1',(owner,)).fetchone()
    legacy=row['seconds'] if row else None
    if row is None:
        raw=os.environ.get('URS_OPENAI_REPORT_TIMEOUT_SECONDS','').strip()
        legacy=int(raw) if raw.isdigit() else None
    return {'timeout_seconds':NETWORK_TIMEOUT,'unlimited':True,'version':row['version'] if row else 0,
            'source':'unlimited_policy','scope':['report_html','independent_verify','technical_analysis','input_token_count'],
            'legacy_timeout_seconds':legacy,'legacy_source':'web' if row else 'server','legacy_value_applied':False}


def diagnostics(workflow,document):
    with workflow.connect() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT payload FROM report_diagnostics WHERE document=? ORDER BY call_id',(document,))]

def request(client,req,call_id,limit,timeout):
    from datetime import datetime,timezone
    with client.workflow.connect() as db:
        row=db.execute('SELECT revision FROM jobs WHERE id=?',(client.document,)).fetchone()
        revision=row[0] if row else None
    d={'call_id':call_id,'revision':revision,'max_output_tokens':limit,'timeout_seconds':timeout,'started_at':datetime.now(timezone.utc).isoformat(),
       'elapsed_seconds':0,'elapsed_scope':'api_exchange','timeout_kind':'none' if timeout is None else 'socket_io','timeout_policy':'unlimited' if timeout is None else 'finite','http_status':None,'response_status':None,'incomplete_reason':None,'outcome':'waiting_response','error_type':None}
    def save():
        with client.workflow.connect() as db:db.execute('INSERT OR REPLACE INTO report_diagnostics VALUES(?,?,?)',(call_id,client.document,json.dumps(d)))
    save();start=time.monotonic();result=None;phase='waiting_response';error=None
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            status=getattr(response,'status',None)
            d['http_status']=status if type(status) is int else None
            phase='reading_response';result=json.load(response)
        phase='parsing_response'
        if not isinstance(result,dict):raise ValueError()
        status=result.get('status');d['response_status']=status if status in ('completed','incomplete','failed','cancelled','queued','in_progress') else 'unknown'
        reason=(result.get('incomplete_details') or {}).get('reason')
        d['incomplete_reason']=reason if reason in ('max_output_tokens','content_filter') else 'unknown' if reason else None
        if status!='completed':
            if reason=='max_output_tokens':
                d['outcome']='max_output_tokens';error=f'출력 토큰 한도({limit:,})에 도달했습니다. 웹의 AI 호출 설정에서 출력 한도를 확인하세요.'
            else:d['outcome']='incomplete_response';error='OpenAI 응답이 완료되지 않았습니다.'
        else:
            phase='html_processing'
            raw=''.join(c['text'] for item in result.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
            if not raw or not any(t in raw.lower() for t in ('<html','<!doctype','<body')):raise ValueError()
            d['outcome']='completed'
    except urllib.error.HTTPError as exc:
        d['http_status']=exc.code;d['outcome']='http_error';d['error_type']='HTTPError';error=f'OpenAI HTTP 오류 ({exc.code}).';exc.close()
    except Exception as exc:
        timed=isinstance(exc,(TimeoutError,socket.timeout)) or isinstance(exc,urllib.error.URLError) and isinstance(exc.reason,(TimeoutError,socket.timeout))
        d['error_type']=type(exc).__name__
        if timed:
            d['outcome']='timeout_before_response' if d['http_status'] is None else 'timeout_reading_response'
            d['timeout_origin']='upstream_or_network' if timeout is None else 'unverified'
            error=('연결/제공자 측 시간 초과 또는 연결 종료입니다. 앱의 응답 대기 제한은 없습니다. 자동 재시도하지 않습니다.' if timeout is None else 'OpenAI 응답 전 대기시간 초과.' if d['http_status'] is None else 'OpenAI 응답 수신 중 대기시간 초과.')
        elif phase=='reading_response' and isinstance(exc,(ConnectionError,http.client.IncompleteRead)):
            d['outcome']='response_read_error';error='OpenAI 응답 수신 도중 연결이 끊겼습니다.'
        elif phase=='html_processing':d['outcome']='html_processing_error';error='OpenAI 응답 후 HTML 형식 처리 실패.'
        elif phase in ('reading_response','parsing_response'):d['outcome']='response_parse_error';error='OpenAI 응답 데이터 해석 실패.'
        else:d['outcome']='connection_error';error='OpenAI 연결 실패 (HTTP 응답 미확인).'
    d['elapsed_seconds']=round(time.monotonic()-start,3);save()
    from urs.costing import finish
    finish(client.workflow,call_id,'failed' if error else 'completed',result)
    if error:
        exc=AIError(error);exc.diagnostics=dict(d);raise exc
    return raw

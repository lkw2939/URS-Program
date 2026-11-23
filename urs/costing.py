"""Exact request token preflight, per-execution cap, and usage-based cost snapshots.

No byte-to-token heuristic. Only an explicit preflight or execution contacts the free
Responses input_tokens endpoint. Read-only status/quotes never upload documents.
"""
import base64,hashlib,io,json,math,os,re,time,urllib.request
from decimal import Decimal
from PIL import Image

TTL=1800
class CostError(ValueError):pass

def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS ai_cost_quotes(fingerprint TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS ai_call_costs(call_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);''')

def rates():
    def value(key,optional=False):
        raw=os.environ.get(key,'').strip()
        if optional and not raw:return None
        try:v=float(raw)
        except ValueError:raise CostError('1회 실행 한도·단가 설정을 확인하세요.') from None
        if not math.isfinite(v) or v<0 or (not optional and v==0):raise CostError('1회 실행 한도·단가 설정을 확인하세요.')
        return v
    return {'cap_usd':value('URS_AI_BUDGET_USD'),'input_rate':value('URS_AI_INPUT_USD_PER_MILLION'),'output_rate':value('URS_AI_OUTPUT_USD_PER_MILLION'),'cached_input_rate':value('URS_AI_CACHED_INPUT_USD_PER_MILLION',True)}

def review_parts(task,html,customer_findings=None):
    """Transport copy only: replace embedded src bytes with IDs, attach same PNGs.

    Stored HTML remains immutable. No resizing, recompression, or model change.
    """
    from urs.ai import review_text
    images={}
    from urs.images import ImageSlots
    text=html
    for start,end,url in reversed(ImageSlots(html,prefix='data:image/').slots):
        try:
            header,b64=url.split(',',1)
            if not re.fullmatch(r'data:image/(png|jpeg|jpg|webp|gif);base64',header,re.I):raise ValueError()
            raw=base64.b64decode(re.sub(r'\s','',b64),validate=True)
            with Image.open(io.BytesIO(raw)) as im:im.verify()
        except Exception:raise CostError('보고서 내장 이미지 형식을 확인할 수 없습니다. 유료 호출하지 않았습니다.') from None
        key=hashlib.sha256(raw).hexdigest()+':'+str(start);images[key]=header+','+base64.b64encode(raw).decode()
        text=text[:start]+'urs-review-image:'+key+text[end:]
    # Never silently bill remaining embedded image base64 as report prose.
    if re.search(r'data:image/[^;,\s]+;base64,',text,re.I):raise CostError('분리하지 못한 내장 이미지가 있습니다. 전송 형식 확인 전 유료 호출하지 않습니다.')
    parts=[{'type':'input_text','text':review_text(task)},{'type':'input_text','text':text}]
    if task=='technical_analysis' and customer_findings:
        from urs.review_policy import context_part
        parts.append(context_part(customer_findings))
    for key,url in images.items():
        parts.extend([{'type':'input_text','text':'HTML image reference: urs-review-image:'+key},{'type':'input_image','image_url':url,'detail':'auto'}])
    return parts

def payload(config,pdf,filename,parts,json_response=False):
    result={'model':config['model'],'input':[{'role':'user','content':[{'type':'input_file','filename':filename,'file_data':'data:application/pdf;base64,'+base64.b64encode(pdf).decode()},*parts]}],'max_output_tokens':config['max_output_tokens'],'store':False}
    if config['effort'] is not None:result['reasoning']={'effort':config['effort']}
    if json_response:result['text']={'format':{'type':'json_object'}}
    return result

def fingerprint(request,pricing):
    return hashlib.sha256(json.dumps({'request':request,'pricing':pricing},sort_keys=True,separators=(',',':')).encode()).hexdigest()

def count_input_tokens(request):
    key=os.environ.get('URS_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not key:raise CostError('무료 비용 계산에 사용할 API 연결 설정을 확인하세요.')
    body={k:request[k] for k in ('model','input','reasoning','text') if k in request}
    req=urllib.request.Request('https://api.openai.com/v1/responses/input_tokens',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        from urs.report_transport import NETWORK_TIMEOUT
        with urllib.request.urlopen(req,timeout=NETWORK_TIMEOUT) as response:result=json.load(response)
        tokens=result.get('input_tokens')
        if type(tokens) is not int or tokens<0:raise ValueError()
        return tokens
    except Exception:raise CostError('무료 입력 토큰 계산에 실패했습니다. 예상액 미확인으로 유료 호출하지 않습니다. 자동 재시도하지 않습니다.') from None

def quote(workflow,request,count=False):
    pricing=rates();key=fingerprint(request,pricing)
    with workflow.connect() as db:
        row=db.execute('SELECT payload,created FROM ai_cost_quotes WHERE fingerprint=?',(key,)).fetchone()
    if row and time.time()-row['created']<TTL:return json.loads(row['payload'])
    if not count:return {'status':'UNVERIFIED','fingerprint':key,'cap_usd':pricing['cap_usd'],'reason':'먼저 무료 비용 계산으로 이번 실행의 예상액을 확인하세요.','budget_scope':'per_execution','provider_balance_usd':None}
    tokens=count_input_tokens(request)
    ir=Decimal(str(pricing['input_rate']));ou=Decimal(str(pricing['output_rate']));million=Decimal(1000000)
    input_cost=Decimal(tokens)*ir/million;max_output=Decimal(request['max_output_tokens'])*ou/million
    parts=request['input'][0]['content']
    result={'status':'READY','fingerprint':key,'created':time.time(),'input_tokens':tokens,'input_cost_usd':float(input_cost),'max_output_tokens':request['max_output_tokens'],'max_output_cost_usd':float(max_output),'estimated_max_usd':float(input_cost+max_output),'cap_usd':pricing['cap_usd'],'blocked':input_cost+max_output>Decimal(str(pricing['cap_usd'])),'pricing':pricing,'budget_scope':'per_execution','provider_balance_usd':None,'token_source':'OpenAI free responses/input_tokens','pdf_count':sum(p['type']=='input_file' for p in parts),'image_count':sum(p['type']=='input_image' for p in parts),'model':request['model'],'reasoning_effort':request.get('reasoning',{}).get('effort'),'note':'이번 입력 토큰 계산액 + 최대 출력 비용. 캐시 할인 미적용 상한 예상이며 실제 청구액·OpenAI 잔액은 아닙니다.'}
    with workflow.connect() as db:db.execute('INSERT OR REPLACE INTO ai_cost_quotes VALUES(?,?,?)',(key,json.dumps(result),time.time()))
    return result

def reserve(workflow,document,task,request):
    q=quote(workflow,request,True)
    if q['blocked']:raise CostError(f"이번 1회 예상 상한 ${q['estimated_max_usd']:.6f}가 실행 한도 ${q['cap_usd']:.6f}를 넘습니다. 유료 호출하지 않았습니다.")
    with workflow.connect() as db:
        # A separate request-count guard, not a dollar limit or a charge.
        if db.execute('SELECT COUNT(*) FROM ai_usage WHERE document=?',(document,)).fetchone()[0]>=120:raise CostError('문서의 요청 횟수 안전 상한(120회)입니다. 비용 한도와 별개입니다.')
        ident=db.execute('INSERT INTO ai_usage(document,task,model,reserved,state) VALUES(?,?,?,?,?)',(document,task,request['model'],q['estimated_max_usd'],'reserved')).lastrowid
        db.execute('INSERT INTO ai_call_costs VALUES(?,?)',(ident,json.dumps({'quote':q,'settlement_state':'pending','actual_cost_usd':None,'rate_source':'request-time configured rates'})))
    return ident

def finish(workflow,call_id,state,result):
    """Keep original reservation as evidence; settlement is separate and never zero-by-default."""
    usage=result.get('usage',{}) if isinstance(result,dict) else {}
    if not isinstance(usage,dict):usage={}
    safe={k:usage[k] for k in ('input_tokens','output_tokens','total_tokens') if type(usage.get(k)) is int and usage[k]>=0}
    cached=(usage.get('input_tokens_details') or {}).get('cached_tokens') if isinstance(usage.get('input_tokens_details'),dict) else None
    if type(cached) is int and cached>=0:safe['input_tokens_details']={'cached_tokens':cached}
    with workflow.connect() as db:
        db.execute('UPDATE ai_usage SET state=?,usage=? WHERE id=?',(state,json.dumps(safe),call_id))
        row=db.execute('SELECT payload FROM ai_call_costs WHERE call_id=?',(call_id,)).fetchone()
        if not row:return
        data=json.loads(row['payload']);p=data['quote']['pricing'];actual=None;status='usage_unknown'
        if 'input_tokens' in safe and 'output_tokens' in safe:
            cache=0 if cached is None else cached
            if cache>safe['input_tokens']:status='usage_invalid'
            elif cache and p['cached_input_rate'] is None:status='cached_rate_unknown'
            elif isinstance(result,dict) and result.get('service_tier') not in (None,'auto','default'):status='service_tier_rate_unknown'
            else:
                actual=float((Decimal(safe['input_tokens']-cache)*Decimal(str(p['input_rate']))+Decimal(cache)*Decimal(str(p['cached_input_rate'] or 0))+Decimal(safe['output_tokens'])*Decimal(str(p['output_rate'])))/Decimal(1000000));status='settled'
        data.update(settlement_state=status,actual_cost_usd=actual,usage=safe,response_status=result.get('status') if isinstance(result,dict) else None)
        db.execute('UPDATE ai_call_costs SET payload=? WHERE call_id=?',(json.dumps(data),call_id))

def review_quote(workspace,owner,document,target,stage,count=False):
    from urs.targets import get
    from urs.ai_settings import effective
    row,original=get(workspace,owner,document,target);config=effective(workspace.workflow,document=document)
    from urs.review_policy import customer_context
    findings=customer_context(workspace,target) if stage=='analyze' else None
    request=payload(config,original['original'],original['name'],review_parts('independent_verify' if stage=='verify' else 'technical_analysis',row['payload'].decode(),findings),True)
    result=quote(workspace.workflow,request,count)
    return {**result,'target':target,'revision':row['parent_revision'],'stored_html_sha256':row['sha256']}

def image_guide(assets):
    inventory=[]
    for a in assets:
        item={k:a[k] for k in ('uri','page','index','bbox')}
        # Old immutable asset records may lack dimensions; inspect the same PNG bytes.
        if 'width_px' in a and 'height_px' in a:w,h=a['width_px'],a['height_px']
        else:
            with Image.open(io.BytesIO(base64.b64decode(a['data_url'].split(',')[1]))) as im:w,h=im.size
        item.update(width_px=w,height_px=h,aspect_ratio=w/h)
        inventory.append(item)
    return 'Image address mapping only: use <img src="urs-image:PAGE:INDEX"> for a source picture/diagram at the corresponding original PDF page and region. Available image addresses, bounding boxes (PDF points from top-left), actual crop pixel width/height and width-to-height ratio (no resizing):\n'+json.dumps(inventory,ensure_ascii=False)

def report_quote(workspace,owner,document,count=False):
    from urs.ai_settings import effective
    from urs.images import crop_images
    from urs.report_contract import TEXT
    original=workspace.original(owner,document);config=effective(workspace.workflow,document=document);prompt=workspace.report_settings(owner)['prompt']
    if not prompt.strip():raise CostError('보고서 프롬프트를 먼저 저장하세요.')
    request=payload(config,original['original'],original['name'],[{'type':'input_text','text':prompt},{'type':'input_text','text':image_guide(crop_images(original['original']))},{'type':'input_text','text':TEXT}])
    result=quote(workspace.workflow,request,count)
    return {**result,'layout_refinement_max_calls':1,'refinement_cost_note':'위 금액은 최초 생성 요청의 예상 상한입니다. 배치 문제가 있으면 같은 모델로 최대 1회 추가 다듬기합니다. 실제 다듬기 자료로 비용을 다시 계산하고, 최초 사용액(미정산이면 예약 상한)+다듬기 예상액이 같은 실행 한도를 넘으면 추가 유료 호출하지 않습니다.'}

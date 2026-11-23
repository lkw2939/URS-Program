"""Readable verification data, with request-boundary evidence and safe text-only plans."""
import hashlib,html,json,re
from datetime import datetime,timezone,timedelta
from html.parser import HTMLParser
from urs.workflow import Blocked


def ko(value,fallback):
    return value.strip() if isinstance(value,str) and re.search('[가-힣]',value) else fallback

def clean(value,placeholders=True):
    if not isinstance(value,str):return ''
    text=value.strip()
    if placeholders and text.lower() in ('미기록','없음','-','[]','{}','""'):return ''
    return text

def page_number(value):
    if type(value) is int and value>0:return value
    if isinstance(value,str) and value.strip().isdigit() and int(value)>0:return int(value)
    return None

def issues(body,page_count=None):
    result=[]
    for index,item in enumerate(body.get('issues',[])):
        item=item if isinstance(item,dict) else {'reason':str(item)}
        severity=str(item.get('severity','')).lower().replace(' ','_')
        kind='error' if severity in ('오류','오역','error','critical','major') else 'review'
        if item.get('needs_confirmation') is True:kind='review'
        category=str(item.get('category',item.get('issue_type',''))).lower().replace('-','_')
        declared=str(item.get('issue_type','')).lower()
        if declared=='customer':kind='review'
        problem=ko(clean(item.get('problem_ko')) or clean(item.get('reason')),'')
        title=ko(clean(item.get('title_ko')),'')
        combined=' '.join(str(item.get(k,'')) for k in ('title_ko','problem_ko','reason','category'))
        if category in ('source_ambiguity','source_conflict','customer_confirmation','customer','ambiguous_source','원문 모호성','고객 확인') or (declared!='translation' and re.search(r'원문(?:\s*자체)?(?:의|에서|에|은|이|가)?[^.]{0,24}(?:모호|불명확|상충)',combined)):kind='review'
        if category in ('layout','pagination','line_break','page_number','서식','쪽수','줄바꿈') or item.get('layout_only') is True:kind='layout'
        if declared=='program' or category in ('image','image_reference','image_mapping','image_visibility','css','program','pipeline','rendering','html','placeholder','program_issue','프로그램 문제') or re.search(r'urs-(?:review-)?image:|display\s*:\s*none|숨김\s*CSS|(?:그림|이미지)\s*주소|PDF\.js',combined,re.I):kind='program'
        customer_confirmation=kind=='review' and (declared=='customer' or (declared!='translation' and category in ('source_ambiguity','source_conflict','customer_confirmation','customer','ambiguous_source','원문 모호성','고객 확인')))
        page=page_number(item.get('page'))
        if page_count and page and page>page_count:page=None
        references=[]
        raw_refs=item.get('evidence',item.get('references',[]))
        if isinstance(raw_refs,list):
            for ref in raw_refs:
                if not isinstance(ref,dict):continue
                n=page_number(ref.get('page'));quote=clean(ref.get('source_en')) or clean(ref.get('quote'))
                if n and quote and (not page_count or n<=page_count):references.append({'page':n,'quote':quote})
        pages=sorted(set(([page] if page else [])+[r['page'] for r in references]))
        # Unquoted related page numbers are not promoted to confirmed source evidence.
        claimed=item.get('pages',item.get('related_pages',[]));claimed=claimed if isinstance(claimed,list) else []
        pending_pages=sorted({n for value in claimed if (n:=page_number(value)) and n not in pages and (not page_count or n<=page_count)})
        before=clean(item.get('before',item.get('current_ko','')),False);after=clean(item.get('after',item.get('suggested_ko','')),False)
        why=ko(clean(item.get('why_ko')) or clean(item.get('why')) or clean(item.get('impact_ko')),'')
        how=ko(clean(item.get('fix_ko')) or clean(item.get('how_to_fix_ko')),'')
        question=ko(clean(item.get('question_ko')) or clean(item.get('customer_question_ko')),'')
        if customer_confirmation and not question:
            times=list(dict.fromkeys(re.findall(r'\d+(?:\.\d+)?\s*(?:시간|hours?)(?![A-Za-z])',problem,re.I)))
            if len(times)>=2:question='원문에 나온 '+', '.join(times)+'은 각각 어떤 조건에 적용되며, 견적과 검수에는 어느 기준을 사용해야 하나요?'
            elif before:question='원문 '+str(page or '해당')+'쪽의 “'+before+'”는 어떤 기준으로 적용해야 하나요?'
            elif problem:question='원문 '+str(page or '해당')+'쪽에서 지적한 조건의 적용 기준을 확인해 주세요.'
        if not title:title={'error':'번역 문구 수정','review':('고객에게 조건 확인' if customer_confirmation else '번역 내용과 근거 확인'),'program':'프로그램 표시·전송 점검','layout':'쪽수·줄바꿈 등 표시 차이'}[kind]
        # Keep a supplied title once; do not repeat it as the problem paragraph.
        if re.sub(r'[\s.。]+','',title)==re.sub(r'[\s.。]+','',problem):problem=''
        if why in (title,problem):why=''
        if how in (title,problem,why,question):how=''
        english=clean(item.get('source_en'))
        if not english and not references:
            reason=clean(item.get('reason'))
            if reason and not re.search('[가-힣]',reason):english=reason
        result.append({'id':str(index),'page':page,'pages':pages,'pending_pages':pending_pages,'references':references,'kind':kind,'customer_confirmation':customer_confirmation,'category':category,'title':title,'problem':problem,'why':why,'how':how,'question':question,'before':before,'after':after,'source_en':english,'can_propose':kind=='error' and page is not None})
    return sorted(result,key=lambda x:({'error':0,'review':1,'program':2,'layout':3}[x['kind']],x['page'] or 999999,int(x['id'])))


def load(workspace,owner,document,target,attempt):
    from urs.targets import get,overview
    selected,original=get(workspace,owner,document,target)
    with workspace.workflow.connect() as db:
        row=db.execute("SELECT * FROM target_reviews WHERE id=? AND target=? AND stage='verify'",(attempt,target)).fetchone()
        latest=db.execute("SELECT id FROM target_reviews WHERE target=? AND stage='verify' AND payload IS NOT NULL ORDER BY id DESC LIMIT 1",(target,)).fetchone()
    if row is None or not row['payload']:raise Blocked('저장된 독립검증 결과가 없습니다.')
    body=json.loads(row['payload']);evidence=json.loads(row['evidence']);entries=issues(body,original['pages'])
    from urs.review_policy import decision
    policy=decision(body)
    current=workspace.report_availability(owner,document)['selected']
    current_target=f"displayed:{document}:{current['revision']}" if current else None
    state=overview(workspace,owner,document,current_target) if current else None
    same=bool(current and selected['kind']=='stored_final' and current['revision']==selected['parent_revision'] and hashlib.sha256(workspace.report_html(owner,document,revision=current['revision'])).hexdigest()==selected['sha256'])
    try:when=datetime.fromisoformat(evidence.get('finished_at',row['created'])).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S (한국시간)')
    except (TypeError,ValueError):when='기록 일시 미확인'
    transport=evidence.get('transport_manifest')
    from urs.review_evidence import compare
    presentation=compare(selected['payload'].decode(),transport)
    return {'document':document,'target':target,'attempt':attempt,'report_name':original['name'],'revision':selected['parent_revision'],'verified_at':when,'status':policy['status'],'stored_status':row['status'],'model_status':body.get('status','UNVERIFIED'),'customer_count':len(policy['customer_findings']),'issues':entries,'error_count':sum(x['kind']=='error' for x in entries),'review_count':sum(x['kind']=='review' for x in entries),'program_count':sum(x['kind']=='program' for x in entries),'layout_count':sum(x['kind']=='layout' for x in entries),'current_matches':same,'older_attempt':bool(latest and latest['id']!=attempt),'can_edit':same and bool(latest and latest['id']==attempt),'stored_html_sha256':selected['sha256'],'transport':transport,'presentation_comparison':presentation,'source_pdf_sha256':original['sha256'],'output_format':'브라우저에서 읽는 HTML 결과 화면 · 내려받기도 HTML','execution_report':{'revision':current['revision'],'sha256':state['sha256'],'target':current_target,'reviews':state['reviews']} if state else None}


class TextRanges(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=False);self.text=text;self.lines=[0]+[m.end() for m in re.finditer('\n',text)];self.stack=[];self.ranges=[];self.feed(text);self.close()
    def source_pos(self):
        line,col=self.getpos();return self.lines[line-1]+col
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);page=self.stack[-1][1] if self.stack else None
        marker=attrs.get('data-urs-page') or attrs.get('data-page')
        if marker and str(marker).isdigit():page=int(marker)
        else:
            match=re.fullmatch(r'(?:page[-_]?|p)([1-9]\d*)',attrs.get('id',''),re.I)
            if match:page=int(match[1])
        if tag not in ('img','input','br','hr','meta','link','source','embed','area','wbr'):self.stack.append((tag,page))
    def handle_startendtag(self,tag,attrs):pass
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:self.stack=self.stack[:index];break
    def add(self,start,end):
        if any(t in ('script','style','textarea','template','noscript') for t,_ in self.stack):return
        if not any(t=='body' for t,_ in self.stack):return
        page=self.stack[-1][1] if self.stack else None
        if self.ranges and self.ranges[-1][1]==start and self.ranges[-1][2]==page:self.ranges[-1]=(self.ranges[-1][0],end,page)
        else:self.ranges.append((start,end,page))
    def handle_data(self,data):self.add(self.source_pos(),self.source_pos()+len(data))
    def handle_entityref(self,name):
        start=self.source_pos();self.add(start,start+len(name)+1+(self.text[start+len(name)+1:start+len(name)+2]==';'))
    def handle_charref(self,name):
        start=self.source_pos();self.add(start,start+len(name)+2+(self.text[start+len(name)+2:start+len(name)+3]==';'))


def decoded_map(text):
    chars=[];spans=[]
    for m in re.finditer(r'&(?:#[xX][0-9A-Fa-f]+|#\d+|[A-Za-z][A-Za-z0-9]+);?|[^&]+|&',text):
        raw=m.group();decoded=html.unescape(raw)
        if raw==decoded:
            for i,c in enumerate(raw):chars.append(c);spans.append((m.start()+i,m.start()+i+1))
        else:
            for c in decoded:chars.append(c);spans.append((m.start(),m.end()))
    return ''.join(chars),spans


class CorrectionInputError(ValueError):
    pass

def plan_changes(text,entries,changes,single_page=False):
    if not isinstance(changes,list) or not 1<=len(changes)<=100:raise CorrectionInputError('수정할 오류 항목을 선택하세요.')
    by_id={x['id']:x for x in entries};ranges=TextRanges(text).ranges;patches=[];seen=set()
    mapped=any(p is not None for _,_,p in ranges)
    for change in changes:
        if not isinstance(change,dict):raise CorrectionInputError('수정 항목 형식을 확인하세요.')
        ident=str(change.get('issue_id'));issue=by_id.get(ident)
        if not issue or not issue['can_propose'] or ident in seen:raise Blocked('확인 필요·표시 차이 항목이나 중복 항목은 자동 수정할 수 없습니다.')
        seen.add(ident);before=change.get('before');after=change.get('after')
        if not isinstance(before,str) or not before.strip() or len(before)>50000 or not isinstance(after,str) or len(after)>50000 or (not after.strip() and change.get('delete') is not True):raise CorrectionInputError('현재 문장과 수정문을 입력하세요. 삭제는 별도로 선택해야 합니다.')
        if change.get('delete') is True and after.strip():raise CorrectionInputError('이 문구만 삭제하려면 바꿀 문구를 비워 주세요. 대체 문구와 삭제를 동시에 선택할 수 없습니다.')
        if before==after:raise CorrectionInputError('수정 전후가 같습니다.')
        matches=[]
        for start,end,page in ranges:
            if page!=issue['page'] and not (not mapped and single_page and issue['page']==1):continue
            decoded,spans=decoded_map(text[start:end]);cursor=0
            while True:
                pos=decoded.find(before,cursor)
                if pos<0:break
                finish=pos+len(before);a,b=spans[pos][0],spans[finish-1][1]
                if (pos==0 or spans[pos-1][1]<=a) and (finish==len(spans) or spans[finish][0]>=b):matches.append((start+a,start+b))
                cursor=pos+1
        if len(matches)!=1:raise Blocked(f"원문 {issue['page']}쪽에서 현재 문장을 한 곳으로 특정할 수 없습니다. 여러 태그로 나뉘거나 반복된 문장은 문제가 있는 표현 단위로 입력하세요.")
        start,end=matches[0];patches.append({'issue_id':ident,'page':issue['page'],'start':start,'end':end,'original_html_text':text[start:end],'before':before,'after':after,'replacement':html.escape(after,quote=False)})
    patches.sort(key=lambda p:p['start'])
    if any(a['end']>b['start'] for a,b in zip(patches,patches[1:])):raise Blocked('선택한 수정 범위가 겹칩니다. 항목을 나누어 적용하세요.')
    return patches


def replay(text,patches):
    for patch in reversed(patches):
        if text[patch['start']:patch['end']]!=patch['original_html_text']:raise Blocked('수정 대상 문장이 변경되었습니다. 다시 확인하세요.')
        text=text[:patch['start']]+patch['replacement']+text[patch['end']:]
    return text


def render(workspace,owner,document,target,attempt):
    data=load(workspace,owner,document,target,attempt);esc=html.escape;base=f'/api/documents/{document}'
    ready=data['execution_report'];editable=data['can_edit']
    next_step='오류 항목의 수정안을 확인하고 필요한 항목만 선택해 적용하세요.' if data['error_count'] else '미확인 번역 항목의 근거를 확인하세요.' if data['review_count']>data['customer_count'] else '프로그램 점검 항목의 발생 위치를 확인하세요. 번역문은 바꾸지 않습니다.' if data['program_count'] else '이 보고서의 독립검증이 통과했다면 기술분석으로 이어갈 수 있습니다.'
    current_version='보고서 버전 '+str(ready['revision']) if ready else '열람 가능한 보고서 없음'
    s=f'<header><p class="eyebrow">독립검증 결과</p><h1>{esc(data["report_name"])}</h1><p id="report-version-context">검증 대상: 보고서 버전 {data["revision"]} · 현재 직원용: {esc(current_version)}</p><p>검증 일시 {esc(data["verified_at"])}</p></header>'
    if not data['current_matches']:s+='<p class="notice" id="historical-note">수정 전 또는 이전 보고서의 검증 결과입니다. 현재 보고서의 검증 결과로 사용하지 않습니다.</p>'
    elif data['older_attempt']:s+='<p class="notice">같은 보고서의 이전 실행 결과입니다. 최신 검증 결과를 확인하세요.</p>'
    s+=f'<section class="summary"><strong>번역 오류 {data["error_count"]}건</strong><strong>번역 확인 필요 {data["review_count"]-data["customer_count"]}건</strong><strong>기술분석으로 이관 {data["customer_count"]}건</strong><strong>프로그램 점검 {data["program_count"]}건</strong><p>다음에 할 일 · {esc(next_step)}</p></section>'
    verdict={'PASS':'통과','NEEDS_REVIEW':'확인 필요','FAIL':'해결할 항목 있음'}.get(data['status'],'미확인')
    s+='<p id="verification-verdict">독립검증 적용 판정: '+esc(data['status'])+' · '+verdict+'. 원문 조건에 대한 고객 확인은 기술분석에서 다루며 이 판정을 막지 않습니다. 번역 오류·미확인 번역·프로그램 문제는 별도 해결이 필요합니다.</p>'
    s+=f'<nav class="screen-only"><a id="verified-report" href="{base}/report.html?revision={data["revision"]}" target="_blank" rel="noopener">검증에 사용한 직원용 보고서 보기 · 버전 {data["revision"]}</a><a href="/">URS 보고서 검토로 돌아가기</a></nav>'
    if data['status']!=data['stored_status']:s+='<p class="notice">과거 저장 판정 '+esc(data['stored_status'])+'은 보존했습니다. 고객 확인 분리 정책을 적용한 현재 판정입니다. 새 AI 검증을 실행한 결과는 아닙니다.</p>'
    if data['customer_count']:s+='<p class="notice" id="customer-handoff">고객 확인 '+str(data['customer_count'])+'건은 기술분석으로 이관했습니다. 답변 대기는 독립검증 통과를 막지 않습니다. 다음 단계의 기술분석 실행 후 결과에서 확인하세요.</p>'
    s+='<section id="findings"><h2>확인할 내용</h2>'
    if data['customer_count'] and all(i['customer_confirmation'] for i in data['issues']):s+='<p>고객 확인 외에 남은 독립검증 지적은 없습니다. 기술분석으로 진행할 수 있습니다.</p>'
    if not data['issues']:s+='<p>저장된 발견 항목이 없습니다. 본문 전체의 정확성을 자동 보증한다는 뜻은 아닙니다.</p>'
    for item in data['issues']:
        if item['kind']=='layout' or item['customer_confirmation']:continue
        n=item['id'];kind={'error':'번역 오류','review':'번역 확인 필요','program':'프로그램 문제'}[item['kind']];can=editable and item['can_propose']
        page_label=' · '.join(str(p)+'쪽' for p in item['pages']) or '쪽 미확인'
        s+=f'<article class="finding {item["kind"]}" data-issue="{n}"><div class="finding-top"><span>{kind} · 원문 {page_label}</span></div><h3>{esc(item["title"])}</h3>'
        if item['problem'] and not (item['kind']=='review' and item['question'].endswith(item['problem'].rstrip('. '))):s+='<p>'+esc(item['problem'])+'</p>'
        if item['why']:s+='<p class="impact"><strong>실무 영향</strong> · '+esc(item['why'])+'</p>'
        if item['kind']=='review' and item['question']:s+='<aside class="customer-question"><strong>확인할 질문</strong><p>'+esc(item['question'])+'</p></aside>'
        if item['kind']=='program':
            from urs.review_evidence import explanation
            s+='<section class="program-diagnosis"><strong>직원용 HTML · 실제 검증 사본 비교</strong>'+''.join('<p>'+esc(line)+'</p>' for line in explanation(item,data['presentation_comparison']))+'</section>'
        elif item['how'] and item['how'] not in (item['problem'],item['question']):s+='<p><strong>다음 조치</strong> · '+esc(item['how'])+'</p>'
        if item['kind']=='error' and can:
            summary='수정안 보기' if item['before'] or item['after'] else '수정 문구 직접 입력'
            opened='open' if item['before'] or item['after'] else ''
            s+=f'<details class="proposal" {opened}><summary>{summary}</summary><div class="compare"><label>현재 보고서에서 바꿀 문구<textarea data-before placeholder="보고서에서 바꿀 문구를 정확히 입력하세요.">{esc(item["before"])}</textarea><p class="print-value" data-print-before>{esc(item["before"])}</p></label><label>바꿀 문구<textarea data-after placeholder="원하는 수정문을 입력하세요. 빈칸은 삭제가 아닙니다.">{esc(item["after"])}</textarea><p class="print-value" data-print-after>{esc(item["after"])}</p></label></div><label class="check"><input type="checkbox" data-delete>이 문구만 삭제 — 대체 문구 없이 지웁니다</label><label class="check"><input type="checkbox" data-select>이 수정 선택</label><p class="muted">입력한 문구가 해당 쪽에서 한 곳으로 확인될 때만 적용합니다. 여러 태그로 나뉘거나 반복된 문장은 바꿀 표현만 좁혀 입력하세요.</p></details>'
        elif item['kind']=='error' and (item['before'] or item['after']):
            s+='<div class="compare read-only">'
            if item['before']:s+='<div><strong>현재 보고서에서 바꿀 문구</strong><p>'+esc(item['before'])+'</p></div>'
            if item['after']:s+='<div><strong>바꿀 문구</strong><p>'+esc(item['after'])+'</p></div>'
            s+='</div><p class="muted">현재 보고서와 연결된 최신 결과에서 수정할 수 있습니다.</p>'
        quotes=[]
        for ref in item['references']:quotes.append('<p class="source-page-label">원문 '+str(ref['page'])+'쪽</p><blockquote>'+esc(ref['quote'])+'</blockquote>')
        if item['source_en'] and item['source_en'] not in [r['quote'] for r in item['references']]:quotes.append('<blockquote>'+esc(item['source_en'])+'</blockquote>')
        if quotes:s+='<details class="source"><summary>영어 원문 근거</summary>'+''.join(quotes)+'</details>'
        if item['pending_pages']:s+='<p class="muted">추가 대조 필요: '+', '.join(str(p)+'쪽' for p in item['pending_pages'])+' (원문 인용 미기록)</p>'
        s+='</article>'
    s+='</section>'
    if data['layout_count']:s+='<details class="layout-notes"><summary>쪽수·줄바꿈 등 표시 차이 '+str(data['layout_count'])+'건 (번역 오류 수에 포함하지 않음)</summary>'+''.join('<p>'+esc(i['problem'] or i['title'])+'</p>' for i in data['issues'] if i['kind']=='layout')+'</details>'
    s+='<section class="actions-panel screen-only" '+('hidden' if not data['error_count'] else '')+'><h2>선택한 오류 수정</h2><p>수정안을 비교한 뒤 적용해야 새 보고서로 저장됩니다. 원본 보고서와 검증 기록은 이력으로 남습니다.</p><button id="preview-corrections" '+'disabled'+'>선택 항목 수정 전후 확인</button><div id="correction-preview" hidden></div><button id="apply-corrections" hidden>선택한 수정 적용</button><p id="correction-status" role="status"></p></section>'
    current_link=base+'/report.html?revision='+str(ready['revision']) if ready else '#'
    s+='<section class="actions-panel screen-only" id="next-actions"><h2>'+('수정 후 확인·재검증' if data['error_count'] else '다음 단계')+'</h2><a id="corrected-report" '+('hidden' if ready and ready['revision']==data['revision'] else '')+' href="'+current_link+'" target="_blank" rel="noopener">'+('수정된 보고서 보기' if ready and ready['revision']!=data['revision'] else '현재 보고서 보기')+'</a><p id="verification-state">'+('수정된 보고서는 독립 재검증 전입니다. 아래 실행은 현재 보고서에 연결됩니다.' if ready and ready['revision']!=data['revision'] else '현재 보고서에 대해 다시 검증할 수 있습니다.')+'</p><button id="reverify" disabled>독립 재검증 실행</button><button id="analyze-current" disabled>기술분석 실행</button><p id="analysis-wait"></p><p id="run-status" role="status"></p><a id="new-result" hidden>새 독립검증 결과 보기</a></section>'
    s+='<details class="technical"><summary>검증 요청 자료·실제 전송·결과 형식 상세</summary><h3>1. 검증을 요청한 보고서</h3><p>'+esc(data['report_name'])+' · 저장 버전 '+str(data['revision'])+'</p><p>저장 최종 HTML SHA-256: <code>'+esc(data['stored_html_sha256'])+'</code></p><h3>2. AI에 실제 보낸 자료</h3>'
    s+='<p>모델 원판정: '+esc(data['model_status'])+' · 저장 판정: '+esc(data['stored_status'])+' · 고객 확인 분리 후 적용 판정: '+esc(data['status'])+'</p>'
    m=data['transport']
    if m and m.get('recording')=='inference_request_boundary':
        s+='<p>실제 추론 요청 경계에서 기록 · 송신 시도 '+('있음' if m.get('request_attempted') else '미확인')+' · HTTP 상태 '+esc(str(m.get('http_status') or '미확인'))+'</p><ul>'
        for file in m.get('files',[]):s+='<li>파일 입력: '+esc(file['filename'])+' ('+esc(file['format'])+') · SHA-256 '+esc(file['sha256'])+'</li>'
        s+=('<li>최종 HTML의 본문·표·CSS: 텍스트 입력. 그림 주소만 전송용 식별자로 바꾼 복사본입니다.</li>' if m.get('html_text') else '<li>HTML 텍스트 입력 기록 없음</li>')+'<li>사진·도면: 별도 이미지 입력 '+str(m.get('image_count',0))+'개, 원본 이미지 bytes 유지</li>'
        other=[f for f in m.get('files',[]) if f['sha256']!=data['source_pdf_sha256']]
        s+=('<li>원본 외 추가 파일 입력 있음: 위 파일 목록을 확인하세요. 변환 PDF인지 별도 확인이 필요합니다.</li>' if other else '<li>변환 PDF: 전송하지 않음</li>')+'</ul>'
        s+='<p>실제 요청 본문 SHA-256: <code>'+esc(m['body_sha256'])+'</code></p>'
    else:s+='<p>이 저장 결과에는 실제 요청 경계의 전송 상세 기록이 없습니다. 결과 화면이 HTML이라는 이유로 입력 형식을 추정하지 않습니다. 현재 코드의 전송 방식과 과거 요청을 구분해야 합니다.</p>'
    s+='<h3>3. 지금 보는 결과</h3><p>'+esc(data['output_format'])+'</p><a download="verification-result.html" href="'+base+'/target-result.html?target='+esc(target)+'&amp;stage=verify&amp;attempt='+str(attempt)+'">검증 결과 HTML 내려받기 (선택)</a></details>'
    from pathlib import Path
    css=(Path(__file__).resolve().parents[1]/'static/review.css').read_text()
    encoded=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>독립검증 결과 · '+esc(data['report_name'])+'</title><style>'+css+'</style><script defer src="/review.js"></script></head><body><main>'+s+'</main><script type="application/json" id="review-data">'+encoded+'</script></body></html>').encode()

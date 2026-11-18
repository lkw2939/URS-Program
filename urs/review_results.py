"""Readable verification data, with request-boundary evidence and safe text-only plans."""
import hashlib,html,json,re
from datetime import datetime,timezone,timedelta
from html.parser import HTMLParser
from urs.workflow import Blocked


def ko(value,fallback):
    return value.strip() if isinstance(value,str) and re.search('[가-힣]',value) else fallback

def issues(body):
    result=[]
    for index,item in enumerate(body.get('issues',[])):
        item=item if isinstance(item,dict) else {'reason':str(item)}
        severity=str(item.get('severity','')).lower().replace(' ','_')
        kind='error' if severity in ('오류','오역','error','critical','major') else 'review'
        if item.get('needs_confirmation') is True:kind='review'
        category=str(item.get('category','')).lower()
        if category in ('layout','pagination','line_break','page_number','서식','쪽수','줄바꿈') or item.get('layout_only') is True:kind='layout'
        page=item.get('page');page=page if type(page) is int and page>0 else int(page) if isinstance(page,str) and page.isdigit() and int(page)>0 else None
        before=item.get('before',item.get('current_ko',''));after=item.get('after',item.get('suggested_ko',''))
        before=before if isinstance(before,str) else '';after=after if isinstance(after,str) else ''
        reason=item.get('problem_ko',item.get('reason',''))
        title=ko(item.get('title_ko'),ko(reason,('원문 '+str(page)+'쪽의 요구사항을 확인해 주세요.' if page else '원문 위치와 요구사항을 확인해 주세요.')))
        if len(title)>110:title=title[:110]+'…'
        english=item.get('source_en','')
        if not english and isinstance(reason,str) and reason and not re.search('[가-힣]',reason):english=reason
        result.append({'id':str(index),'page':page,'kind':kind,'category':category,'title':title,'problem':ko(reason,'한국어 문제 설명이 저장되지 않았습니다. 원문 근거를 확인해 주세요.'),'why':ko(item.get('why_ko',item.get('why',item.get('impact_ko'))),'중요성에 대한 구체적인 판단 근거가 기록에 없습니다.'),'how':ko(item.get('fix_ko',item.get('how_to_fix_ko')),'아래 수정안을 원문과 대조한 뒤 필요한 항목만 선택하세요.' if kind=='error' else '고객 또는 직원에게 확인한 뒤 판단해야 합니다. 자동 수정하지 않습니다.'),'before':before,'after':after,'source_en':english if isinstance(english,str) else '', 'can_propose':kind=='error' and page is not None})
    return sorted(result,key=lambda x:({'error':0,'review':1,'layout':2}[x['kind']],x['page'] or 999999,int(x['id'])))


def load(workspace,owner,document,target,attempt):
    from urs.targets import get,overview
    selected,original=get(workspace,owner,document,target)
    with workspace.workflow.connect() as db:
        row=db.execute("SELECT * FROM target_reviews WHERE id=? AND target=? AND stage='verify'",(attempt,target)).fetchone()
        latest=db.execute("SELECT id FROM target_reviews WHERE target=? AND stage='verify' AND payload IS NOT NULL ORDER BY id DESC LIMIT 1",(target,)).fetchone()
    if row is None or not row['payload']:raise Blocked('저장된 독립검증 결과가 없습니다.')
    body=json.loads(row['payload']);evidence=json.loads(row['evidence']);entries=issues(body)
    current=workspace.report_availability(owner,document)['selected']
    current_target=f"displayed:{document}:{current['revision']}" if current else None
    state=overview(workspace,owner,document,current_target) if current else None
    same=bool(current and selected['kind']=='stored_final' and current['revision']==selected['parent_revision'] and hashlib.sha256(workspace.report_html(owner,document,revision=current['revision'])).hexdigest()==selected['sha256'])
    try:when=datetime.fromisoformat(evidence.get('finished_at',row['created'])).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S (한국시간)')
    except (TypeError,ValueError):when='기록 일시 미확인'
    transport=evidence.get('transport_manifest')
    return {'document':document,'target':target,'attempt':attempt,'report_name':original['name'],'revision':selected['parent_revision'],'verified_at':when,'status':row['status'],'issues':entries,'error_count':sum(x['kind']=='error' for x in entries),'review_count':sum(x['kind']=='review' for x in entries),'layout_count':sum(x['kind']=='layout' for x in entries),'current_matches':same,'older_attempt':bool(latest and latest['id']!=attempt),'can_edit':same and bool(latest and latest['id']==attempt),'stored_html_sha256':selected['sha256'],'transport':transport,'source_pdf_sha256':original['sha256'],'output_format':'브라우저에서 읽는 HTML 결과 화면 · 내려받기도 HTML','execution_report':{'revision':current['revision'],'sha256':state['sha256'],'target':current_target,'reviews':state['reviews']} if state else None}


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


def plan_changes(text,entries,changes,single_page=False):
    if not isinstance(changes,list) or not 1<=len(changes)<=100:raise ValueError('수정할 오류 항목을 선택하세요.')
    by_id={x['id']:x for x in entries};ranges=TextRanges(text).ranges;patches=[];seen=set()
    mapped=any(p is not None for _,_,p in ranges)
    for change in changes:
        if not isinstance(change,dict):raise ValueError('수정 항목 형식을 확인하세요.')
        ident=str(change.get('issue_id'));issue=by_id.get(ident)
        if not issue or not issue['can_propose'] or ident in seen:raise Blocked('확인 필요·표시 차이 항목이나 중복 항목은 자동 수정할 수 없습니다.')
        seen.add(ident);before=change.get('before');after=change.get('after')
        if not isinstance(before,str) or not before.strip() or len(before)>50000 or not isinstance(after,str) or len(after)>50000 or (not after.strip() and change.get('delete') is not True):raise ValueError('현재 문장과 수정문을 입력하세요. 삭제는 별도로 선택해야 합니다.')
        if before==after:raise ValueError('수정 전후가 같습니다.')
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
    next_step='오류 항목의 수정안을 확인하고 필요한 항목만 선택해 적용하세요.' if data['error_count'] else '확인 필요 항목을 고객·직원에게 확인하세요.' if data['review_count'] else '이 보고서의 독립검증이 통과했다면 기술분석으로 이어갈 수 있습니다.'
    s=f'<header><p class="eyebrow">독립검증 결과</p><h1>{esc(data["report_name"])}</h1><p>보고서 버전 {data["revision"]} · 검증 일시 {esc(data["verified_at"])}</p></header>'
    if not data['current_matches']:s+='<p class="notice" id="historical-note">수정 전 또는 이전 보고서의 검증 결과입니다. 현재 보고서의 검증 결과로 사용하지 않습니다.</p>'
    elif data['older_attempt']:s+='<p class="notice">같은 보고서의 이전 실행 결과입니다. 최신 검증 결과를 확인하세요.</p>'
    s+=f'<section class="summary"><strong>오류 {data["error_count"]}건</strong><strong>확인 필요 {data["review_count"]}건</strong><p>다음에 할 일 · {esc(next_step)}</p></section>'
    s+=f'<nav><a href="{base}/report.html?revision={data["revision"]}" target="_blank" rel="noopener">검증한 보고서 보기</a><a href="/">URS 보고서 검토로 돌아가기</a></nav>'
    s+='<section id="findings"><h2>오류와 확인할 항목</h2>'
    if not data['issues']:s+='<p>저장된 발견 항목이 없습니다. 본문 전체의 정확성을 자동 보증한다는 뜻은 아닙니다.</p>'
    for item in data['issues']:
        if item['kind']=='layout':continue
        n=item['id'];kind='오류' if item['kind']=='error' else '확인 필요';can=editable and item['can_propose']
        page_label=str(item['page'])+'쪽' if item['page'] else '쪽 미확인'
        s+=f'<article class="finding {item["kind"]}" data-issue="{n}"><div class="finding-top"><span>{kind} · 원문 {page_label}</span></div><h3>{esc(item["title"])}</h3><h4>무엇이 문제인가요?</h4><p>{esc(item["problem"])}</p><h4>왜 중요한가요?</h4><p>{esc(item["why"])}</p><h4>어떻게 고치나요?</h4><p>{esc(item["how"])}</p>'
        s+=f'<details class="proposal" {"open" if item["kind"]=="error" else ""}><summary>수정안 보기</summary><div class="compare"><label>현재 문장<textarea data-before placeholder="현재 문장 기록이 없으면 보고서의 정확한 표현을 입력하세요." {"" if can else "readonly"}>{esc(item["before"])}</textarea></label><label>권장 수정문<textarea data-after placeholder="권장 수정문 기록이 없으면 확인한 수정문을 입력하세요." {"" if can else "readonly"}>{esc(item["after"])}</textarea></label></div>'
        if can:s+='<p class="muted">문장이 여러 태그로 나뉘거나 반복되면 문제가 있는 표현 단위로 입력하세요. 수정은 본문 텍스트에만 적용됩니다.</p><label class="check"><input type="checkbox" data-delete>선택한 문구를 삭제하는 수정입니다</label><label class="check"><input type="checkbox" data-select>이 오류의 수정안 선택</label>'
        else:s+='<p class="muted">확인 필요 항목은 자동 수정하지 않습니다.</p>' if item['kind']=='review' else '<p class="muted">현재 보고서와 연결된 최신 결과에서만 수정할 수 있습니다. 원문 쪽 또는 수정 위치가 없으면 직접 확인이 필요합니다.</p>'
        s+='</details>'
        if item['source_en']:s+='<details class="source"><summary>영어 원문 근거</summary><blockquote>'+esc(item['source_en'])+'</blockquote></details>'
        s+='</article>'
    s+='</section>'
    if data['layout_count']:s+='<details><summary>쪽수·줄바꿈 등 표시 차이 '+str(data['layout_count'])+'건 (번역 오류 수에 포함하지 않음)</summary>'+''.join('<p>'+esc(i['problem'])+'</p>' for i in data['issues'] if i['kind']=='layout')+'</details>'
    s+='<section class="actions-panel"><h2>선택한 오류 수정</h2><p>수정안을 비교한 뒤 적용해야 새 보고서로 저장됩니다. 원본 보고서와 검증 기록은 이력으로 남습니다.</p><button id="preview-corrections" '+('' if editable and data['error_count'] else 'disabled')+'>선택 항목 수정 전후 확인</button><div id="correction-preview" hidden></div><button id="apply-corrections" hidden>선택한 수정 적용</button><p id="correction-status" role="status"></p></section>'
    current_link=base+'/report.html?revision='+str(ready['revision']) if ready else '#'
    s+='<section class="actions-panel" id="next-actions"><h2>수정 후 확인·재검증</h2><a id="corrected-report" href="'+current_link+'" target="_blank" rel="noopener">'+('수정된 보고서 보기' if ready and ready['revision']!=data['revision'] else '현재 보고서 보기')+'</a><p id="verification-state">'+('수정된 보고서는 독립 재검증 전입니다. 아래 실행은 현재 보고서에 연결됩니다.' if ready and ready['revision']!=data['revision'] else '현재 보고서에 대해 다시 검증할 수 있습니다.')+'</p><button id="reverify">독립 재검증 실행</button><button id="analyze-current">기술분석 실행</button><p id="analysis-wait"></p><p id="run-status" role="status"></p><a id="new-result" hidden>새 독립검증 결과 보기</a></section>'
    s+='<details class="technical"><summary>검증 요청 자료·실제 전송·결과 형식 상세</summary><h3>1. 검증을 요청한 보고서</h3><p>'+esc(data['report_name'])+' · 저장 버전 '+str(data['revision'])+'</p><p>저장 최종 HTML SHA-256: <code>'+esc(data['stored_html_sha256'])+'</code></p><h3>2. AI에 실제 보낸 자료</h3>'
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
    encoded=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>독립검증 결과 · '+esc(data['report_name'])+'</title><link rel="stylesheet" href="/review.css"><script defer src="/review.js"></script></head><body><main>'+s+'</main><script type="application/json" id="review-data">'+encoded+'</script></body></html>').encode()

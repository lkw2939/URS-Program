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
        text_integrity=kind=='program' and bool(re.search(r'(?:이메일|메일|email|e-mail|연락처)[^.]{0,80}(?:숨은|숨[김겨]|문자|zero.?width|invisible)',combined,re.I)) and not re.search(r'CSS|urs-(?:review-)?image:|그림|이미지|PDF\.js',combined,re.I)
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
        result.append({'id':str(index),'page':page,'pages':pages,'pending_pages':pending_pages,'references':references,'kind':kind,'customer_confirmation':customer_confirmation,'category':category,'title':title,'problem':problem,'why':why,'how':how,'question':question,'before':before,'after':after,'source_en':english,'can_propose':kind=='error' and page is not None,'can_manual':(kind=='review' and not customer_confirmation) or text_integrity,'text_integrity':text_integrity})
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
    from urs.correction_context import continuation
    editable_revision=current['revision'] if current else None
    derived,applied=continuation(workspace,owner,document,editable_revision,selected['parent_revision'],target,attempt) if current and selected['kind']=='stored_final' else (False,{})
    for entry in entries:entry['applied']=applied.get(entry['id'])
    from urs.flow import state as flow_state
    flow=flow_state(workspace,owner,document)
    return {'flow':flow,'page_count':original['pages'],'editable_revision':editable_revision,'editable_sha256':hashlib.sha256(workspace.report_html(owner,document,revision=editable_revision)).hexdigest() if current else None,'manual_index':max([int(k.split(':')[1]) for k in applied if re.fullmatch(r'manual:[0-9]{1,6}',k)],default=-1)+1,'applied_issue_ids':list(applied),'document':document,'target':target,'attempt':attempt,'report_name':original['name'],'revision':selected['parent_revision'],'verified_at':when,'status':policy['status'],'stored_status':row['status'],'model_status':body.get('status','UNVERIFIED'),'customer_count':len(policy['customer_findings']),'issues':entries,'error_count':sum(x['kind']=='error' and not x.get('applied') for x in entries),'applied_count':len(applied),'review_count':sum(x['kind']=='review' and not x.get('applied') for x in entries),'program_count':sum(x['kind']=='program' and not x.get('applied') for x in entries),'layout_count':sum(x['kind']=='layout' for x in entries),'current_matches':same,'older_attempt':bool(latest and latest['id']!=attempt),'can_edit':(same or derived) and bool(latest and latest['id']==attempt),'stored_html_sha256':selected['sha256'],'transport':transport,'presentation_comparison':presentation,'source_pdf_sha256':original['sha256'],'output_format':'브라우저에서 읽는 HTML 결과 화면 · 내려받기도 HTML','execution_report':{'revision':current['revision'],'sha256':state['sha256'],'target':current_target,'reviews':state['reviews']} if state else None}


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

def _text_groups(text,ranges,page,single_page):
    groups=[];nodes=[]
    for start,end,n in ranges:
        if n!=page and not (single_page and n is None and page==1):nodes=[];continue
        if nodes:
            gap=text[nodes[-1][1]:start]
            if re.sub(r'</?(?:b|strong|em|i|u|s|span|a|sub|sup)\b[^>]*>','',gap,flags=re.I).strip():nodes=[]
        if not nodes:groups.append([])
        nodes.append((start,end));groups[-1].append((start,end))
    return groups

def plan_changes(text,entries,changes,single_page=False,page_count=None):
    if not isinstance(changes,list) or not 1<=len(changes)<=100:raise CorrectionInputError('수정할 항목을 선택하세요.')
    by_id={x['id']:x for x in entries};ranges=TextRanges(text).ranges;patches=[];seen=set()
    for change in changes:
        if not isinstance(change,dict):raise CorrectionInputError('수정 항목 형식을 확인하세요.')
        ident=str(change.get('issue_id'));issue=by_id.get(ident);manual=bool(re.fullmatch(r'manual:[0-9]{1,6}',ident))
        if ident in seen or (not manual and (not issue or issue.get('applied') or not (issue.get('can_propose') or issue.get('can_manual')))):raise Blocked('이미 적용했거나 본문 수정으로 처리할 수 없는 항목입니다. 사진·CSS·고객 확인은 문장 수정으로 해결하지 않습니다.')
        confirmed=change.get('confirmed') is True;basis=clean(change.get('basis'))
        needs_confirmation=manual or issue.get('can_manual',False)
        if needs_confirmation and (not confirmed or len(basis)<5):raise Blocked('원문 확인 체크와 수정 판단 근거(5자 이상)를 입력하세요. 확인이 필요한 수량·조건을 임의로 확정하지 않습니다.')
        page=change.get('page',issue.get('page') if issue else None)
        if type(page) is not int or page<1 or (page_count and page>page_count):raise CorrectionInputError('원문 쪽을 선택하세요.')
        if issue and issue.get('pages') and page not in issue['pages']:raise Blocked('이 항목의 원문 쪽과 수정 위치가 다릅니다. 다른 쪽의 문구는 직접 수정 항목으로 추가하세요.')
        if issue and issue.get('page') and page!=issue['page'] and not needs_confirmation:raise Blocked('이 오류의 원문 쪽과 수정 위치가 다릅니다.')
        seen.add(ident);before=change.get('before');after=change.get('after')
        if not isinstance(before,str) or not before.strip() or len(before)>50000 or not isinstance(after,str) or len(after)>50000 or (not after.strip() and change.get('delete') is not True):raise CorrectionInputError('현재 문장과 수정문을 입력하세요. 삭제는 별도로 선택해야 합니다.')
        if change.get('delete') is True and after.strip():raise CorrectionInputError('이 문구만 삭제하려면 고칠 문장을 비워 주세요. 대체 문구와 삭제를 동시에 선택할 수 없습니다.')
        if before==after:raise CorrectionInputError('수정 전후가 같습니다.')
        matches=[]
        for nodes in _text_groups(text,ranges,page,single_page):
            decoded='';spans=[]
            for start,end in nodes:
                value,mapping=decoded_map(text[start:end]);decoded+=value;spans.extend((start+a,start+b) for a,b in mapping)
            cursor=0
            while True:
                pos=decoded.find(before,cursor)
                if pos<0:break
                finish=pos+len(before)
                if (pos==0 or spans[pos-1][1]<=spans[pos][0]) and (finish==len(spans) or spans[finish-1][1]<=spans[finish][0]):matches.append(spans[pos:finish])
                cursor=pos+1
        occurrence=change.get('occurrence')
        if occurrence is not None and (type(occurrence) is not int or not 1<=occurrence<=len(matches)):raise Blocked('반복 문구의 순번을 확인하세요.')
        if len(matches)!=1 and not (type(occurrence) is int and 1<=occurrence<=len(matches)):
            raise Blocked(f'원문 {page}쪽에서 문구를 {len(matches)}곳 찾았습니다. 보고서에서 현재 문구를 복사하거나, 반복 문구는 몇 번째인지 지정하세요. 서로 다른 문단·표 셀은 나누어 수정하세요.')
        selected=matches[(occurrence or 1)-1];edits=[]
        import difflib
        for op,a,b,c,d in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
            if op=='equal':continue
            if any(0<n<len(selected) and selected[n-1][1]>selected[n][0] for n in (a,b)):raise Blocked('특수 문자 전체를 하나의 수정 단위로 입력하세요.')
            if a==b:
                pos=selected[a][0] if a<len(selected) else selected[-1][1];edits.append({'start':pos,'end':pos,'original_html_text':'','replacement':html.escape(after[c:d],quote=False)});continue
            spans=selected[a:b];chunks=[]
            for start,end in spans:
                if chunks and start<=chunks[-1][1]:chunks[-1]=(chunks[-1][0],max(end,chunks[-1][1]))
                else:chunks.append((start,end))
            for i,(start,end) in enumerate(chunks):edits.append({'start':start,'end':end,'original_html_text':text[start:end],'replacement':html.escape(after[c:d],quote=False) if i==0 else ''})
        edits.sort(key=lambda x:x['start'])
        if any(a['end']>b['start'] for a,b in zip(edits,edits[1:])):raise Blocked('특수 문자 경계를 나눠 수정할 수 없습니다. 해당 표현 전체를 입력하세요.')
        start,end=selected[0][0],selected[-1][1]
        patches.append({'issue_id':ident,'page':page,'start':start,'end':end,'original_html_text':text[start:end],'before':before,'after':after,'replacement':html.escape(after,quote=False),'edits':edits,'confirmed':confirmed,'basis':basis,'manual':needs_confirmation,'occurrence':occurrence or 1})
    patches.sort(key=lambda p:p['start'])
    if any(a['end']>b['start'] for a,b in zip(patches,patches[1:])):raise Blocked('선택한 수정 범위가 겹칩니다. 항목을 나누어 적용하세요.')
    return patches


def replay(text,patches):
    edits=[edit for p in patches for edit in p.get('edits',[p])]
    for edit in sorted(edits,key=lambda p:p['start'],reverse=True):
        if text[edit['start']:edit['end']]!=edit['original_html_text']:raise Blocked('수정 대상 문장이 변경되었습니다. 다시 확인하세요.')
        text=text[:edit['start']]+edit['replacement']+text[edit['end']:]
    return text


def editor_html(item,data):
    esc=html.escape;manual=item.get('can_manual',False) or item['id'].startswith('manual:');page=item.get('page')
    if not page and len(item.get('pages',[]))==1:page=item['pages'][0]
    options='<option value="">쪽 선택</option>'+''.join(f'<option value="{n}"'+(' selected' if n==page else '')+f'>{n}쪽</option>' for n in range(1,data['page_count']+1))
    quick=bool(item.get('can_propose') and not manual and item.get('before') and item.get('after') and item['before']!=item['after'])
    controls=''
    if quick:controls+='<div class="recommendation"><div><strong>현재 문장</strong><p data-recommendation-before>'+esc(item['before'])+'</p></div><div><strong>추천 수정문</strong><p data-recommendation-after>'+esc(item['after'])+'</p></div></div><button type="button" data-use-recommendation>이대로 고치기</button><p data-recommendation-status role="status"></p>'
    elif not item['id'].startswith('manual:'):controls+='<p class="manual-needed">추천문이 없습니다. 직접 확인해 주세요.</p>'
    controls+='<button type="button" data-edit-item>직접 고치기</button><details class="proposal"><summary>수정 내용</summary>'
    controls+=('<details class="edit-location"><summary>수정 위치 확인 · 원문 '+str(page)+'쪽</summary>' if page else '<div>')+'<label>원문 쪽<select data-page>'+options+'</select></label>'+('</details>' if page else '</div>')
    if manual:controls+='<p class="notice">원문을 확인한 뒤 수정하세요.</p><label class="check"><input type="checkbox" data-confirm>원문 확인</label><label>확인한 내용<textarea data-basis rows="2" placeholder="예: 원문에 대상이 명시되지 않아 수량의 대상을 단정한 표현을 제거합니다."></textarea></label>'
    controls+='<div class="compare"><label>현재 문장<textarea data-before rows="4" placeholder="보고서에서 복사하세요.">'+esc(item.get('before',''))+'</textarea><p class="print-value" data-print-before>'+esc(item.get('before',''))+'</p></label><label>고칠 문장<textarea data-after rows="4" placeholder="고칠 내용을 입력하세요.">'+esc(item.get('after',''))+'</textarea><p class="print-value" data-print-after>'+esc(item.get('after',''))+'</p></label></div>'
    if item.get('text_integrity') or item['id'].startswith('manual:'):controls+='<button type="button" data-clean-invisible>보이지 않는 문자 지우기</button>'
    controls+='<div class="item-actions screen-only"><button type="button" data-preview-item>변경 내용 확인</button><p data-item-status role="status"></p><div data-item-preview hidden></div><button type="button" data-apply-item hidden>이 수정 저장</button></div>'
    controls+='<details class="edit-advanced"><summary>추가 옵션</summary><label>반복 문구의 순서<input type="number" min="1" max="10000" data-occurrence placeholder="예: 2"></label><label class="check"><input type="checkbox" data-delete>이 문구만 삭제 — 대체 문구 없이 지웁니다</label></details></details>'
    return controls



def source_context_html(item,base):
    """Show stored evidence verbatim; page links always use the uploaded original."""
    esc=html.escape
    refs=list(item.get('references',[]))
    english=item.get('source_en','')
    if english and english not in [r['quote'] for r in refs]:refs.append({'page':item.get('page'),'quote':english})
    def link(page):
        url=base+'/original?view=1'+('#page='+str(page) if page else '')
        return '<a class="source-pdf" href="'+esc(url,quote=True)+'" target="_blank" rel="noopener">'+('원문 '+str(page)+'쪽 PDF 보기' if page else '원본 PDF 보기')+'</a>'
    result='<section class="source-context" aria-label="영어 원문"><h4>영어 원문</h4>'
    for ref in refs:
        result+='<div class="source-excerpt">'+link(ref['page'])+'<blockquote lang="en">'+esc(ref['quote'])+'</blockquote></div>'
    quoted={r['page'] for r in refs if r['page']}
    missing=[n for n in sorted(set(item.get('pages',[])+item.get('pending_pages',[]))) if n not in quoted]
    if not refs:result+='<p class="source-missing">저장된 원문 인용이 없습니다.</p>'
    for page in missing:result+='<p class="source-missing">'+link(page)+' · 인용 미기록</p>'
    if not refs and not missing:result+='<p>'+link(item.get('page'))+'</p>'
    return result+'</section>'


def render(workspace,owner,document,target,attempt):
    data=load(workspace,owner,document,target,attempt);esc=html.escape;base=f'/api/documents/{document}'
    ready=data['execution_report'];editable=data['can_edit']
    next_step='항목별 수정안을 확인하세요.' if data['error_count'] else '미확인 번역 항목의 근거를 확인하세요.' if data['review_count']>data['customer_count'] else '프로그램 점검 항목의 발생 위치를 확인하세요. 번역문은 바꾸지 않습니다.' if data['program_count'] else '이 보고서의 독립검증이 통과했다면 CSS 단계를 진행할 수 있습니다.'
    current_version='보고서 버전 '+str(ready['revision']) if ready else '열람 가능한 보고서 없음'
    s=f'<header><p class="eyebrow">독립검증 결과</p><h1>{esc(data["report_name"])}</h1><p id="report-version-context">보고서 버전 {data["revision"]}{(' · 현재 버전 '+str(ready['revision'])) if ready and ready['revision']!=data['revision'] else ''}</p></header>'
    if not data['current_matches']:s+='<p class="notice" id="historical-note">이전 검증 결과입니다.</p>'
    elif data['older_attempt']:s+='<p class="notice">이전 실행 결과입니다.</p>'
    s+='<section class="action-progress" role="status"><h2 id="work-title">수정 항목을 확인하고 있습니다</h2><p id="work-instruction">필수 항목을 고쳐 저장하면 CSS 단계로 넘어갈 수 있습니다.</p></section>'
    s+='<details class="review-records"><summary>상세 정보</summary><p>검증 일시 '+esc(data['verified_at'])+'</p><p>문구 수정을 마친 뒤 CSS와 최종 검증을 진행합니다.</p>'
    s+=f'<section class="summary"><strong id="remaining-errors">번역 오류 {data["error_count"]}건</strong><strong id="applied-count">적용 {data["applied_count"]}건</strong><strong id="remaining-reviews">번역 확인 필요 {data["review_count"]-data["customer_count"]}건</strong><strong>기술분석으로 이관 {data["customer_count"]}건</strong><strong id="remaining-programs">프로그램 점검 {data["program_count"]}건</strong><p id="next-action-summary">다음에 할 일 · {esc(next_step)}</p></section>'
    verdict={'PASS':'통과','NEEDS_REVIEW':'확인 필요','FAIL':'해결할 항목 있음'}.get(data['status'],'미확인')
    s+='<p id="verification-verdict">독립검증 적용 판정: '+esc(data['status'])+' · '+verdict+'. 원문 조건에 대한 고객 확인은 기술분석에서 다루며 이 판정을 막지 않습니다. 번역 오류·미확인 번역·프로그램 문제는 별도 해결이 필요합니다.</p>'
    s+=f'<nav class="screen-only"><a id="verified-report" href="{base}/report.html?revision={data["revision"]}" target="_blank" rel="noopener">검증에 사용한 직원용 보고서 보기 · 버전 {data["revision"]}</a><a href="/?document={document}&amp;step=2">URS 보고서 검토로 돌아가기</a></nav>'
    s+='<p class="edit-guide screen-only">수정은 이렇게: 추천문이 맞으면 <strong>이대로 고치기</strong>를 누르세요. 직접 입력은 원할 때만 하세요.</p>'
    s+='<!-- review-record-details --></details>'
    s+='<section class="result-step-nav screen-only"><button type="button" id="next-stage" disabled>다음 단계 →</button><a id="return-workflow" href="/?document='+esc(document)+'&amp;step=2">작업 화면</a><p id="next-stage-reason" role="status"></p></section>'
    if data['status']!=data['stored_status']:s+='<details class="past-policy"><summary>이전 판정</summary><p class="notice">과거 저장 판정 '+esc(data['stored_status'])+'은 보존했습니다. 고객 확인 분리 정책을 적용한 현재 판정입니다. 새 AI 검증을 실행한 결과는 아닙니다.</p></details>'
    if data['customer_count']:s+='<p class="customer-handoff" id="customer-handoff">고객 확인 '+str(data['customer_count'])+'건 · 기술분석에서 확인</p>'
    s+='<section id="findings"><h2>고칠 항목</h2>'
    if data['customer_count'] and all(i['customer_confirmation'] for i in data['issues']):s+='<p>고칠 문구가 없습니다.</p>'
    if not data['issues']:s+='<p>고칠 문구가 없습니다.</p>'
    for item in data['issues']:
        if item['kind']=='layout' or item['customer_confirmation']:continue
        n=item['id'];kind='처리 완료' if item.get('applied') else {'error':'번역 오류','review':'번역 확인 필요','program':'프로그램 문제'}[item['kind']];can=editable and not item.get('applied') and (item['can_propose'] or item.get('can_manual'))
        page_label=' · '.join(str(p)+'쪽' for p in item['pages']) or '쪽 미확인'
        s+=f'<article class="finding {item["kind"]}" data-issue="{n}"><div class="finding-top"><span>{kind} · 원문 {page_label}</span></div><h3>{esc(item["title"])}</h3>'
        explanation=''
        if item['problem'] and not (item['kind']=='review' and item['question'].endswith(item['problem'].rstrip('. '))):explanation+='<p>'+esc(item['problem'])+'</p>'
        if item['why']:explanation+='<p class="impact"><strong>실무 영향</strong> · '+esc(item['why'])+'</p>'
        if item['kind']=='review' and item['question']:explanation+='<aside class="customer-question"><strong>확인할 질문</strong><p>'+esc(item['question'])+'</p></aside>'
        if item['kind']=='program':
            from urs.review_evidence import explanation as explain_program
            explanation+='<section class="program-diagnosis"><strong>직원용 HTML · 실제 검증 사본 비교</strong>'+''.join('<p>'+esc(line)+'</p>' for line in explain_program(item,data['presentation_comparison']))+'</section>'
        elif item['how'] and item['how'] not in (item['problem'],item['question']):explanation+='<p><strong>다음 조치</strong> · '+esc(item['how'])+'</p>'
        if item['kind'] in ('error','review') or item.get('can_manual') or item['references'] or item['source_en']:
            s+=source_context_html(item,base)
        quick=bool(item.get('can_propose') and not item.get('can_manual') and item['before'] and item['after'] and item['before']!=item['after'])
        if item['before'] and not quick:s+='<section class="current-translation"><h4>'+('수정 전 번역' if item.get('applied') else '현재 번역')+'</h4><p>'+esc(item['before'])+'</p></section>'
        if item.get('applied'):s+='<p class="applied-note">보고서 버전 '+str(item['applied']['applied_revision'])+'에 저장했습니다.</p>'
        elif can:s+=editor_html(item,data)
        elif item['kind']=='error' and (item['before'] or item['after']):
            s+='<div class="compare read-only">'
            if item['before']:s+='<div><strong>현재 문장</strong><p>'+esc(item['before'])+'</p></div>'
            if item['after']:s+='<div><strong>고칠 문장</strong><p>'+esc(item['after'])+'</p></div>'
            s+='</div><p class="muted">이전 결과는 수정할 수 없습니다.</p>'
        if explanation:s+='<details class="finding-explanation"><summary>왜 고쳐야 하나요? · 근거 보기</summary>'+explanation+'</details>'
        s+='</article>'
    if editable:
        manual={'id':'manual:'+str(data['manual_index']),'page':None,'pages':[],'before':'','after':'','can_manual':True}
        s+='<details id="manual-options"><summary>목록에 없는 문구 직접 고치기</summary><article class="finding manual" data-issue="'+manual['id']+'"><h3>다른 문구 직접 수정</h3>'+editor_html(manual,data)+'</article><button type="button" id="add-manual-correction">직접 수정 항목 추가</button></details>'
    s+='</section>'
    if data['layout_count']:s+='<details class="layout-notes"><summary>쪽수·줄바꿈 등 표시 차이 '+str(data['layout_count'])+'건 (번역 오류 수에 포함하지 않음)</summary>'+''.join('<p>'+esc(i['problem'] or i['title'])+'</p>' for i in data['issues'] if i['kind']=='layout')+'</details>'
    s+='<p id="correction-status" class="save-status screen-only" role="status"></p>'
    current_link=base+'/report.html?revision='+str(ready['revision']) if ready else '#'
    s+='<section class="actions-panel screen-only" id="next-actions"><h2>'+'저장한 보고서'+'</h2><a id="corrected-report" '+('hidden' if ready and ready['revision']==data['revision'] else '')+' href="'+current_link+'" target="_blank" rel="noopener">'+('수정된 보고서 보기' if ready and ready['revision']!=data['revision'] else '현재 보고서 보기')+'</a><details id="other-review-actions"><summary>다른 작업</summary><button id="reverify" disabled>독립 재검증 실행</button><button id="analyze-current" disabled>기술분석 실행</button><p id="analysis-wait"></p><p id="run-status" role="status"></p><a id="new-result" hidden>새 독립검증 결과 보기</a></details></section>'
    s+='<section class="result-step-nav result-step-nav-bottom screen-only"><button type="button" id="next-stage-bottom" disabled>다음 단계 →</button><p id="next-stage-reason-bottom"></p></section>'
    technical=''
    technical+='<details class="technical"><summary>검증 요청 자료·실제 전송·결과 형식 상세</summary><h3>1. 검증을 요청한 보고서</h3><p>'+esc(data['report_name'])+' · 저장 버전 '+str(data['revision'])+'</p><p>저장 최종 HTML SHA-256: <code>'+esc(data['stored_html_sha256'])+'</code></p><h3>2. AI에 실제 보낸 자료</h3>'
    technical+='<p>모델 원판정: '+esc(data['model_status'])+' · 저장 판정: '+esc(data['stored_status'])+' · 고객 확인 분리 후 적용 판정: '+esc(data['status'])+'</p>'
    m=data['transport']
    if m and m.get('recording')=='inference_request_boundary':
        technical+='<p>실제 추론 요청 경계에서 기록 · 송신 시도 '+('있음' if m.get('request_attempted') else '미확인')+' · HTTP 상태 '+esc(str(m.get('http_status') or '미확인'))+'</p><ul>'
        for file in m.get('files',[]):technical+='<li>파일 입력: '+esc(file['filename'])+' ('+esc(file['format'])+') · SHA-256 '+esc(file['sha256'])+'</li>'
        technical+=('<li>최종 HTML의 본문·표·CSS: 텍스트 입력. 그림 주소만 전송용 식별자로 바꾼 복사본입니다.</li>' if m.get('html_text') else '<li>HTML 텍스트 입력 기록 없음</li>')+'<li>사진·도면: 별도 이미지 입력 '+str(m.get('image_count',0))+'개, 원본 이미지 bytes 유지</li>'
        other=[f for f in m.get('files',[]) if f['sha256']!=data['source_pdf_sha256']]
        technical+=('<li>원본 외 추가 파일 입력 있음: 위 파일 목록을 확인하세요. 변환 PDF인지 별도 확인이 필요합니다.</li>' if other else '<li>변환 PDF: 전송하지 않음</li>')+'</ul>'
        technical+='<p>실제 요청 본문 SHA-256: <code>'+esc(m['body_sha256'])+'</code></p>'
    else:technical+='<p>이 저장 결과에는 실제 요청 경계의 전송 상세 기록이 없습니다. 결과 화면이 HTML이라는 이유로 입력 형식을 추정하지 않습니다. 현재 코드의 전송 방식과 과거 요청을 구분해야 합니다.</p>'
    technical+='<h3>3. 지금 보는 결과</h3><p>'+esc(data['output_format'])+'</p><a download="verification-result.html" href="'+base+'/target-result.html?target='+esc(target)+'&amp;stage=verify&amp;attempt='+str(attempt)+'">검증 결과 HTML 내려받기 (선택)</a></details>'
    s=s.replace('<!-- review-record-details -->',technical,1)
    from pathlib import Path
    css=(Path(__file__).resolve().parents[1]/'static/review.css').read_text()
    encoded=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>독립검증 결과 · '+esc(data['report_name'])+'</title><style>'+css+'</style><script defer src="/review.js?v=source-visible-review-6"></script></head><body><main>'+s+'</main><script type="application/json" id="review-data">'+encoded+'</script></body></html>').encode()

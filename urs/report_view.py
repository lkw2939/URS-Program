"""Read-only identity, photo facts and verification gates for the employee report."""
import hashlib,json,re
from html.parser import HTMLParser
from urs.review_results import issues
from urs.review_evidence import compare

class Pictures(HTMLParser):
    def __init__(self,text):
        super().__init__();self.images=[];self.pickers=0;self.stack=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);classes=(attrs.get('class') or '').split()
        if tag=='input' and attrs.get('type','').lower()=='file':self.pickers+=1
        if tag=='img':self.images.append({'embedded':(attrs.get('src') or '').startswith('data:image/'),'unresolved':(attrs.get('src') or '').startswith('urs-image:'),'waiting_for_ready':any('figure' in c for _,c in self.stack) and 'ready' not in classes})
        if tag not in ('img','input','br','hr','meta','link','source','area','embed','wbr'):self.stack.append((tag,classes))
    handle_startendtag=handle_starttag
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.stack=self.stack[:i];break

def picture_facts(text):
    parsed=Pictures(text);hidden_rule=bool(re.search(r'\.figure\s+img\s*\{[^{}]*display\s*:\s*none\b',text,re.I))
    embedded=sum(i['embedded'] for i in parsed.images);unresolved=sum(i['unresolved'] for i in parsed.images)
    suspected=sum(i['waiting_for_ready'] for i in parsed.images) if hidden_rule else 0
    selector=bool(re.search(r'''img\s*\[\s*src\s*\^=\s*["']urs-image:''',text))
    mismatch=bool(embedded and not unresolved and selector)
    if unresolved:message=f'연결되지 않은 원본 그림 주소가 {unresolved}개 있습니다. 이미지 연결 문제이며 번역 문구 수정으로 해결되지 않습니다.'
    elif suspected:message=f'사진 데이터 {embedded}개가 있지만, 숨김 CSS와 ready 대기 구조가 {suspected}개에 남아 있습니다. 기존 저장본의 프로그램 표시 문제를 확인해야 합니다.'
    elif embedded:message=f'내장 사진·도면 {embedded}개가 있습니다. 실제 화면 표시 여부는 아래 미리보기에서 확인하세요.'
    else:message='저장 HTML에 내장 사진 데이터가 없습니다. 원본에 그림이 있는지는 별도 대조해야 합니다.'
    if mismatch:message+=' 사진은 data:image로 연결됐지만 기존 스크립트는 urs-image 주소를 찾는 불일치도 있습니다.'
    return {'legacy_selector_mismatch':mismatch,'image_count':len(parsed.images),'embedded_images':embedded,'unresolved_slots':unresolved,'pdf_selection_controls':parsed.pickers,'legacy_hidden_rule':hidden_rule,'waiting_for_ready':suspected,'browser_visibility_verified':False,'message':message}

def context(workspace,owner,document,selected,current_review):
    if not selected:return None
    rev=selected['revision'];payload=workspace.report_html(owner,document,revision=rev);digest=hashlib.sha256(payload).hexdigest();base=f'/api/documents/{document}'
    target=f'displayed:{document}:{rev}'
    with workspace.workflow.connect() as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM target_reviews WHERE target=? AND stage='verify' ORDER BY id DESC",(target,))]
    latest=rows[0] if rows else None;stored=next((r for r in rows if r['payload']),None)
    findings=issues(json.loads(stored['payload']),workspace.original(owner,document)['pages']) if stored else []
    evidence=json.loads(stored['evidence']) if stored else {}
    from urs.review_policy import for_row
    verdict=for_row(stored) if stored else None
    return {'revision':rev,'filename':'report.html','sha256':digest,'report_url':base+f'/report.html?revision={rev}','raw_url':base+f'/report.raw.html?revision={rev}' if selected.get('raw_available') else None,'picture_facts':picture_facts(payload.decode()),'verification':{
        'can_execute':current_review['reviews']['verify']['can_run'] if current_review else False,'execution_blocked_reason':current_review['reviews']['verify']['blocked_reason'] if current_review else '검증 대상이 없습니다.',
        'latest_attempt_state':latest['state'] if latest else None,'latest_attempt_status':latest['status'] if latest else None,'latest_attempt_reason':json.loads(latest['evidence']).get('reason') if latest else None,
        'saved_result_status':verdict,'saved_attempt':stored['id'] if stored else None,'previous_attempt_result':bool(stored and latest and stored['id']!=latest['id']),
        'findings':[{'id':f['id'],'page':f['page'],'pages':f['pages'],'kind':f['kind'],'title':f['title'],'problem':f['problem'],'question':f['question']} for f in findings if not f['customer_confirmation']],
        'customer_handoff_count':sum(f['customer_confirmation'] for f in findings),
        'customer_answer_recording_available':False,'pass_rule':'현재 보고서 버전의 검토가 정상 완료되고 번역 오류·미확인 번역·프로그램 문제가 없어야 합니다. 원문 조건에 대한 고객 확인은 기술분석으로 이관하며 독립검증 PASS를 막지 않습니다. 실행 가능 상태는 PASS와 다릅니다. 직원 최종 승인 조건은 별도입니다.',
        'comparison':compare(payload.decode(),evidence.get('transport_manifest'))}}

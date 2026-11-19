"""One model-owned layout refinement; the program binds image addresses and audits only."""
import base64,hashlib,json,re,shutil,subprocess,sys
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urs.images import bind_images
from urs.layout_audit import inspect
from urs.report_contract import check
VERSION='terra-layout-refinement-v1'
INSTRUCTION='''사진 삽입 후 실제 브라우저 검사에서 배치 문제가 발견되었습니다. 아래 원본 HTML을 직접 다듬어 전체 완성 HTML을 다시 출력하세요.
번역 본문, 수치, 단위, 표의 내용, 캡션, 원문 쪽 소속과 이미지 식별 주소를 보존하세요. 내용을 삭제·요약하거나 확인되지 않은 내용을 추가하지 마세요. 원문의 기술 요구사항을 바꾸지 마세요.
각 원문 쪽을 210 × 297mm A4 세로 화면 안에 읽기 좋게 배치하세요. 제목·문단·표·그림·여백·CSS 배치는 직접 결정하세요. 프로그램은 장을 나누거나 글을 줄이지 않습니다. 읽을 수 있는 크기로 한 장에 담을 수 없다면 해당 쪽에 data-urs-unfit="구체적인 이유"를 표시하고 내용을 보존하세요. 잘라내기, 숨김, 극단적인 축소는 금지합니다.
첨부 화면은 프로그램이 원본 사진을 연결한 실제 렌더링입니다. 사진·도면 src는 제공된 urs-image:쪽:번호를 유지하는 일반 img로 작성하세요. PDF 재선택·PDF.js·ready 대기·사진 숨김을 제거하세요. 사진 자체는 프로그램이 다시 연결합니다.
마크다운 없이 <!DOCTYPE html>부터 </html>까지 전체 HTML만 반환하세요.'''
def sha(value):return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()
class Content(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.stack=[];self.text=defaultdict(str);self.images=defaultdict(list);self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);page=a.get('data-urs-page')
        if not page and tag=='section' and 'source-page' in a.get('class','').split() and re.fullmatch(r'page-\d+',a.get('id','')):page=a['id'][5:]
        current=page or (self.stack[-1][1] if self.stack else None)
        if tag=='img' and current:self.images[current].append(a.get('src',''))
        if tag not in ('img','br','input','hr','meta','link','source','wbr','area','embed'):self.stack.append((tag,current,bool({'figure-status','toolbar'} & set(a.get('class','').split())) or (self.stack[-1][2] if self.stack else False)))
    handle_startendtag=handle_starttag
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.stack=self.stack[:i];break
    def handle_data(self,value):
        if self.stack and not any(t in ('style','script') for t,_,_ in self.stack) and not self.stack[-1][2]:
            page=self.stack[-1][1]
            if page or any(t=='body' for t,_,_ in self.stack):self.text[page or '__outside_body__']+=value
def preserved(before,after):
    a,b=Content(before),Content(after)
    tokens=lambda texts:{k:re.findall(r'\d+(?:[.,]\d+)*|[A-Za-z]+|[가-힣]+|[^\s]',v) for k,v in texts.items() if v.strip()}
    return bool(tokens(a.text)) and tokens(a.text)==tokens(b.text) and dict(a.images)==dict(b.images)
def evaluate(raw,assets,expected):
    try:final,binding=bind_images(raw,assets)
    except Exception as error:
        from urs.ai import AIError
        exc=AIError('OpenAI 응답 후 이미지 연결 처리 실패.');exc.processing_phase='image_binding';exc.cause_type=type(error).__name__;raise exc from None
    audit=inspect(final,expected);problems=check(raw)
    if not re.search(r'</html\s*>\s*(?:```\s*)?$',raw,re.I):problems.append('HTML 문서 끝이 없습니다. 불완전 응답은 다듬기 대상으로 사용하지 않습니다.')
    if binding['unresolved']:problems.append('연결할 수 없는 원본 그림 주소가 있습니다.')
    if assets and not binding['replacements']:problems.append('원본 그림 후보가 있으나 연결된 그림이 없습니다.')
    if problems:
        audit['status']='NEEDS_REVIEW';audit.setdefault('issues',[]).extend(problems)
    audit.update(contract_issues=problems,source_image_candidates=len(assets),bound_image_slots=len(binding['replacements']))
    return final,binding,audit

def captures(html,audit):
    pages=list(dict.fromkeys(p['page'] for p in audit.get('pages',[]) if p['issues']))
    if not pages:pages=list(dict.fromkeys(p['page'] for p in audit.get('pages',[])))
    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),json.dumps(pages)],input=html.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=75)
    if result.returncode:raise ValueError('배치 다듬기용 실제 화면을 만들지 못했습니다. 추가 유료 호출하지 않았습니다.')
    return json.loads(result.stdout)
def refine(raw,assets,expected,provider,pdf,name,prompt,guide):
    final,binding,audit=evaluate(raw,assets,expected);chosen=raw;extras={}
    receipt={'version':VERSION,'max_refinements':1,'attempted':False,'accepted':False,'initial_raw_sha256':sha(raw),'initial_final_sha256':sha(final),'initial_audit':audit,'program_pagination':False,'screenshots':[]}
    can_refine=not binding['unresolved'] and audit['status']=='NEEDS_REVIEW' and re.search(r'</html\s*>\s*(?:```\s*)?$',raw,re.I)
    if can_refine and callable(getattr(provider,'refine_report_html',None)):
        try:
            screens=captures(final,audit)
            receipt['screenshots']=[{'page':s['page'],'sha256':s['sha256'],'bytes':s['bytes']} for s in screens]
            for i,s in enumerate(screens):extras[f'layout-before-{i+1}.png']=base64.b64decode(s['image_url'].split(',')[1])
            receipt['attempted']=True
            candidate=provider.refine_report_html(pdf,name,prompt,guide,raw,audit,screens)
            if not isinstance(candidate,str) or not candidate:raise ValueError('배치 다듬기 응답 HTML이 없습니다.')
            extras['report.refinement-response.html']=candidate.encode();receipt['response_sha256']=sha(candidate)
            if not preserved(raw,candidate):
                receipt['failure_reason']='다듬기 응답에서 원문 쪽별 본문·표·캡션 또는 이미지 식별자가 달라졌습니다. 수정본을 채택하지 않았습니다.'
            else:
                candidate_final,candidate_binding,candidate_audit=evaluate(candidate,assets,expected)
                receipt['refined_audit']=candidate_audit
                if candidate_audit['status']=='PASS':
                    chosen,final,binding,audit=candidate,candidate_final,candidate_binding,candidate_audit;receipt['accepted']=True
                else:receipt['failure_reason']='Terra 다듬기 후에도 사진 표시·A4 배치 문제가 남았습니다. 자동 재호출하지 않습니다.'
        except Exception as exc:
            from urs.ai import AIError,AIBlocked
            receipt['failure_reason']=str(exc) if isinstance(exc,(AIError,AIBlocked,ValueError)) else '배치 다듬기 처리 실패. 기존 정상 보고서를 유지합니다.'
            if getattr(exc,'diagnostics',None):receipt['api_diagnostics']=exc.diagnostics
            receipt['error_type']=type(exc).__name__
    if receipt.get('failure_reason'):audit={**audit,'issues':[*audit.get('issues',[]),receipt['failure_reason']]}
    receipt.update(chosen_raw_sha256=sha(chosen),final_sha256=sha(final),final_status=audit['status'])
    return chosen,final,binding,audit,receipt,extras

def worker(html,pages):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable=shutil.which('chromium') or shutil.which('chromium-browser');b=p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox','--disable-dev-shm-usage']);context=b.new_context(java_script_enabled=False,viewport={'width':1280,'height':1200});context.route('**/*',lambda r:r.abort());page=context.new_page();page.set_content(html,wait_until='load');page.wait_for_function('() => [...document.images].every(i=>i.complete)');page.evaluate('() => document.fonts.ready')
        screenshots=[]
        for n in pages:
            elements=page.locator('[data-urs-page="'+n+'"],section.source-page[id="page-'+n+'"]')
            if not elements.count():continue
            for element in elements.all():
                picture=element.screenshot(timeout=10000);screenshots.append({'page':n,'sha256':sha(picture),'bytes':len(picture),'image_url':'data:image/png;base64,'+base64.b64encode(picture).decode()})
        b.close()
    if not screenshots:raise ValueError('원문 페이지 화면을 찾지 못했습니다.')
    return screenshots
if __name__=='__main__':print(json.dumps(worker(sys.stdin.buffer.read().decode(),json.loads(sys.argv[1])),ensure_ascii=False))

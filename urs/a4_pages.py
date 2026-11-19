"""Offline, server-side A4 fragmentation of image-bound HTML; raw response stays immutable."""
import hashlib,json,re,shutil,subprocess,sys
from pathlib import Path
VERSION='a4-continuations-v1'
CSS='''
@page{size:A4 portrait;margin:0}
[data-urs-page]{box-sizing:border-box!important;width:210mm!important;height:297mm!important;min-width:210mm!important;max-width:210mm!important;min-height:297mm!important;max-height:297mm!important;overflow:visible!important;margin:0 auto 6mm!important;break-after:page;position:relative;background:white}
[data-urs-page] img{max-width:100%!important;object-fit:contain!important}
[data-urs-page] table{max-width:100%!important;overflow-wrap:anywhere}
[data-urs-page] [data-urs-flow]{height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important}
[data-urs-page] [data-urs-flow]>*{max-width:100%}
[data-urs-continuation-label]{font-size:13px;color:#586b7a;margin-bottom:8px}
@media print{html,body{margin:0!important;padding:0!important}[data-urs-page]{margin:0!important;box-shadow:none!important;break-before:auto!important;break-after:page!important}[data-urs-page]:last-child{break-after:auto!important}}
'''
SCRIPT=r'''({css,expected})=>{
 let roots=[...document.querySelectorAll('[data-urs-page]')];
 if(!roots.length)roots=[...document.querySelectorAll('section.source-page[id^="page-"]')];
 if(roots.length!==expected)return {changed:false,reason:'원문 구역 수를 확인할 수 없습니다.'};
 const a4=roots.every(p=>{let r=p.getBoundingClientRect();return p.hasAttribute('data-urs-page')&&Math.abs(r.width-210*96/25.4)<2&&Math.abs(r.height-297*96/25.4)<2&&p.scrollHeight<=p.clientHeight+2&&p.scrollWidth<=p.clientWidth+2});
 let imageVisibilityChanges=0;
 for(const img of document.images){
  for(let el=img;el&&el!==document.documentElement;el=el.parentElement){
   const s=getComputedStyle(el);
   for(const [property,bad,value] of [['display',s.display==='none','block'],['visibility',['hidden','collapse'].includes(s.visibility),'visible'],['opacity',Number(s.opacity)===0,'1'],['content-visibility',s.contentVisibility==='hidden','visible']]){
    if(bad){el.style.setProperty(property,value,'important');el.removeAttribute('hidden');imageVisibilityChanges++;}
   }
  }
 }
 if(a4)return {changed:imageVisibilityChanges>0,image_visibility_changes:imageVisibilityChanges,text_and_image_order_preserved:true};
 const beforeText=roots.map(p=>p.textContent.replace(/\s/g,''));
 const beforeImages=roots.flatMap(p=>[...p.querySelectorAll('img')].map(i=>i.getAttribute('src')));
 const style=document.createElement('style');style.id='urs-a4-pages';style.textContent=css;document.head.append(style);
 const issues=[],counts=[];
 roots.forEach((source,sourceIndex)=>{
  const number=source.getAttribute('data-urs-page')||source.id.replace('page-','');
  source.setAttribute('data-urs-page',number);
  const nodes=[...source.childNodes];source.replaceChildren();
  let page=source,part=1,flow;
  function makeFlow(){flow=document.createElement('div');flow.setAttribute('data-urs-flow','');page.append(flow);}
  makeFlow();
  function next(){page=source.cloneNode(false);page.removeAttribute('id');page.removeAttribute('data-urs-unfit');page.setAttribute('data-urs-continuation',String(++part));
   const label=document.createElement('div');label.setAttribute('data-urs-continuation-label','');label.textContent='원문 '+number+'쪽 · 이어짐 '+part;page.append(label);
   const previous=[...document.querySelectorAll('[data-urs-page]')].filter(p=>p.getAttribute('data-urs-page')===number).at(-1);previous.after(page);makeFlow();}
  function fits(){const r=page.getBoundingClientRect(),s=getComputedStyle(page);return flow.getBoundingClientRect().bottom<=r.bottom-parseFloat(s.paddingBottom)+.5&&page.scrollWidth<=page.clientWidth+1;}
  function add(node,chain=[],depth=0){
   if(depth>35)throw Error('페이지 분할 깊이 초과');
   const shell=()=>{let parent=flow;for(const a of chain){const copy=a.cloneNode(false);copy.removeAttribute('id');copy.style.setProperty('height','auto','important');copy.style.setProperty('min-height','0','important');copy.style.setProperty('overflow','visible','important');parent.append(copy);parent=copy;}return parent;};
   let parent=shell();parent.append(node);
   if(fits())return;
   node.remove();let empty=flow.textContent.trim()===''&&!flow.querySelector('img');
   // Remove empty cloned ancestry left by this attempt.
   if(chain.length){let outer=parent;while(outer.parentElement!==flow)outer=outer.parentElement;outer.remove();}
   if(!empty){next();parent=shell();parent.append(node);if(fits())return;node.remove();if(chain.length){let outer=parent;while(outer.parentElement!==flow)outer=outer.parentElement;outer.remove();}}
   if(node.nodeType===3){
    const text=node.textContent;let offset=0;
    while(offset<text.length){parent=shell();const piece=document.createTextNode('');parent.append(piece);let low=1,high=text.length-offset,best=0;
     while(low<=high){const middle=(low+high)>>1;piece.textContent=text.slice(offset,offset+middle);if(fits()){best=middle;low=middle+1;}else high=middle-1;}
     if(!best){piece.remove();issues.push({page:number,reason:'최소 한 글자도 읽을 크기로 담을 수 없습니다.'});parent.append(document.createTextNode(text.slice(offset)));break;}
     piece.textContent=text.slice(offset,offset+best);offset+=best;if(offset<text.length)next();
    }return;
   }
   if(node.nodeType!==1)return;
   // Images stay whole. Fit one oversize image proportionally within one content box.
   if(node.tagName==='IMG'){
    parent=shell();parent.append(node);const r=page.getBoundingClientRect(),s=getComputedStyle(page),available=r.bottom-parseFloat(s.paddingBottom)-node.getBoundingClientRect().top-2;
    node.style.setProperty('max-height',Math.max(1,available)+'px','important');node.style.setProperty('width','auto','important');node.style.setProperty('height','auto','important');
    if(!fits())issues.push({page:number,reason:'도면이 한 A4 장에 들어가지 않습니다.'});return;
   }
   // Preserve each table row; split tables between rows, repeating table headers.
   if(node.tagName==='TABLE'){
    const rows=[...node.querySelectorAll(':scope>tbody>tr,:scope>tr,:scope>tfoot>tr')];
    if(rows.length){let table=null,body=null;
     for(const row of rows){if(!table){parent=shell();table=node.cloneNode(false);for(const head of node.querySelectorAll(':scope>caption,:scope>colgroup,:scope>thead'))table.append(head.cloneNode(true));body=document.createElement('tbody');table.append(body);parent.append(table);}body.append(row);
      if(!fits()){row.remove();if(!body.children.length){body.append(row);issues.push({page:number,reason:'표 한 행이 A4 높이를 넘습니다. 내용을 자르지 않고 보존했습니다.'});table=null;continue;}
       next();parent=shell();table=node.cloneNode(false);for(const head of node.querySelectorAll(':scope>caption,:scope>colgroup,:scope>thead'))table.append(head.cloneNode(true));body=document.createElement('tbody');table.append(body);parent.append(table);body.append(row);
       if(!fits())issues.push({page:number,reason:'표 한 행이 A4 높이를 넘습니다. 내용을 자르지 않고 보존했습니다.'});}
     }return;}
   }
   if(node.childNodes.length){const children=[...node.childNodes];node.replaceChildren();for(const child of children)add(child,[...chain,node],depth+1);return;}
   parent=shell();parent.append(node);issues.push({page:number,reason:'분할할 수 없는 요소가 A4 영역을 넘습니다.'});
  }
  for(const node of nodes)add(node);
  counts.push({source_page:number,sheets:part});
 });
 const all=[...document.querySelectorAll('[data-urs-page]')];
 const afterText=roots.map(p=>all.filter(x=>x.getAttribute('data-urs-page')===p.getAttribute('data-urs-page')).map(x=>{const c=x.cloneNode(true);c.querySelectorAll('[data-urs-continuation-label]').forEach(y=>y.remove());return c.textContent.replace(/\s/g,'');}).join(''));
 const afterImages=all.flatMap(p=>[...p.querySelectorAll('img')].map(i=>i.getAttribute('src')));
 // Headers may repeat, but original text must remain in order. Never certify removed text.
 const contains=(a,b)=>{let n=0;for(const c of b)if(c===a[n])n++;return n===a.length;};
 if(!beforeText.every((t,i)=>contains(t,afterText[i]))||JSON.stringify(beforeImages)!==JSON.stringify(afterImages))throw Error('페이지 분할 중 본문/사진 보존 검사 실패');
 return {changed:true,counts,issues,image_visibility_changes:imageVisibilityChanges,text_and_image_order_preserved:true};
}'''
def paginate(html,expected):
    if not re.search(r'</html\s*>\s*(?:```\s*)?$',html,re.I):
        return html,{'changed':False,'version':VERSION,'input_sha256':hashlib.sha256(html.encode()).hexdigest(),'final_sha256':hashlib.sha256(html.encode()).hexdigest(),'issues':[{'reason':'HTML 응답의 문서 끝이 없어 A4 변환하지 않았습니다.'}]}
    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(expected)],input=html.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
    if result.returncode:raise ValueError('A4 페이지 제작 실패: 기존 보고서는 보존됩니다.')
    out=json.loads(result.stdout);return out['html'],out['receipt']
def worker(html,expected):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable=shutil.which('chromium') or shutil.which('chromium-browser')
        browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(java_script_enabled=False,viewport={'width':1280,'height':1200});context.route('**/*',lambda r:r.abort());page=context.new_page();page.set_content(html,wait_until='load');page.evaluate('() => document.fonts.ready');page.wait_for_function('() => [...document.images].every(i=>i.complete)')
        receipt=page.evaluate(SCRIPT,{'css':CSS,'expected':expected});output=page.content() if receipt['changed'] else html;browser.close()
    receipt.update(version=VERSION,input_sha256=hashlib.sha256(html.encode()).hexdigest(),final_sha256=hashlib.sha256(output.encode()).hexdigest())
    return {'html':output,'receipt':receipt}
if __name__=='__main__':
    print(json.dumps(worker(sys.stdin.buffer.read().decode(),int(sys.argv[1])),ensure_ascii=False))

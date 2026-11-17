"""Measure final HTML in Chromium, without changing any report byte or style."""
import json,subprocess,sys,shutil
from pathlib import Path

MEASURE=r'''() => {
 const pages=[...document.querySelectorAll('[data-urs-page]')];
 return {pages:pages.map((p,i)=>{
  const r=p.getBoundingClientRect();const problems=[];const n=p.getAttribute('data-urs-page');
  if(Math.abs(r.width-210*96/25.4)>2||Math.abs(r.height-297*96/25.4)>2)problems.push('A4 화면 크기 불일치');
  if(p.scrollHeight>p.clientHeight+2||p.scrollWidth>p.clientWidth+2)problems.push('페이지 내용 넘침');
  if(p.getAttribute('data-urs-unfit'))problems.push('모델 확인 필요: '+p.getAttribute('data-urs-unfit'));
  for(const e of [p,...p.querySelectorAll('*')]){
   if(['STYLE','SCRIPT'].includes(e.tagName))continue;
   const s=getComputedStyle(e),q=e.getBoundingClientRect();
   if(s.transform!=='none'){const m=new DOMMatrix(s.transform);if(Math.hypot(m.a,m.b)<.99||Math.hypot(m.c,m.d)<.99)problems.push('강제 축소 배치');}
   if(s.zoom&&Number(s.zoom)<.99)problems.push('강제 축소 배치');
   const own=[...e.childNodes].filter(x=>x.nodeType===3).map(x=>x.textContent).join('').trim();
   if(own&&(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0||q.width<1||q.height<1))problems.push('숨겨진 본문');
   if(own&&s.display!=='none'&&parseFloat(s.fontSize)<(e.closest('table,figcaption')?12:13)-.1)problems.push('작은 글자');
   if(s.display!=='none'&&q.width&&q.height&&(q.bottom>r.bottom+2||q.right>r.right+2||q.left<r.left-2))problems.push('페이지 밖 내용');
   if((e.scrollHeight>e.clientHeight+2&&/hidden|clip/.test(s.overflowY))||(e.scrollWidth>e.clientWidth+2&&/hidden|clip/.test(s.overflowX)))problems.push('영역에서 내용 잘림');
   if(e.tagName==='IMG'){
    if(!e.complete||!e.naturalWidth)problems.push('이미지 로딩 실패');
    if(s.display==='none'||s.visibility==='hidden'||q.width<1||q.height<1)problems.push('이미지 숨김');
    if(['cover','fill'].includes(s.objectFit)&&Math.abs(q.width/q.height-e.naturalWidth/e.naturalHeight)>.04)problems.push('이미지 비율/잘림 확인 필요');
   }
  }
  return {page:n||String(i+1),width_px:r.width,height_px:r.height,issues:[...new Set(problems)]};
 }),image_count:document.querySelectorAll('img').length};
}'''

def inspect(html,expected_pages):
    # Use a child process: synchronous Playwright must not run inside another event loop.
    try:
        proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(expected_pages)],input=html.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=50)
        if proc.returncode:raise ValueError()
        return json.loads(proc.stdout)
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {'status':'UNVERIFIED','reason':'브라우저 배치 검사를 완료하지 못했습니다. 브라우저 설치/실행 상태를 확인하세요.','pages':[]}

def worker(html,expected):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable=shutil.which('chromium') or shutil.which('chromium-browser')
        b=p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox','--disable-dev-shm-usage'])
        context=b.new_context(viewport={'width':1280,'height':1200},service_workers='block');context.route('**/*',lambda r:r.abort());page=context.new_page()
        page.set_content(html,wait_until='load',timeout=15000)
        page.wait_for_function("() => [...document.images].every(i=>i.complete)",timeout=10000)
        page.evaluate('() => document.fonts.ready');out=page.evaluate(MEASURE)
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(120)
        narrow=page.evaluate(MEASURE);out['narrow_pages']=narrow['pages']
        b.close()
    numbers=[str(i) for i in range(1,expected+1)]
    issues=[]
    if html.lstrip().startswith('```') or html.rstrip().endswith('```'):issues.append('마크다운 코드펜스가 HTML 바깥에 남아 있음')
    if [x['page'] for x in out['pages']]!=numbers:issues.append('원문 페이지 구역/번호 누락 또는 순서 불일치')
    if any(x['issues'] for x in out['narrow_pages']):issues.append('좁은 화면에서도 A4 크기/내용 유지 필요')
    if any(x['issues'] for x in out['pages']):issues.append('A4 크기/넘침/읽기 크기/이미지 확인 필요')
    return {**out,'status':'PASS' if not issues else 'NEEDS_REVIEW','issues':issues,'scope':'사진 삽입 후 최종 HTML의 Chromium 실측. 번역 정확도/도면 작은 글자의 완전성 인증이 아닙니다.'}
if __name__=='__main__':
    try:print(json.dumps(worker(sys.stdin.buffer.read().decode(),int(sys.argv[1])),ensure_ascii=False))
    except Exception:raise SystemExit(1)

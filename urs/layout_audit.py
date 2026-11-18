"""Measure final HTML in Chromium, without changing any report byte or style."""
import json,subprocess,sys,shutil
from pathlib import Path

MEASURE=r'''() => {
 const pages=[...document.querySelectorAll('[data-urs-page]')];
 const imageChecks=[...document.images].map((img,index)=>{
  const r=img.getBoundingClientRect(),issues=[];let e=img;
  while(e){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||Number(s.opacity)===0||s.contentVisibility==='hidden'||/opacity\(0(?:\.0+)?%?\)/.test(s.filter))issues.push('이미지 숨김');e=e.parentElement;}
  if(!img.complete||!img.naturalWidth)issues.push('이미지 로딩 실패');
  if(r.width<1||r.height<1)issues.push('이미지 표시 영역 없음');
  if(!img.closest('[data-urs-page]'))issues.push('그림이 원문 페이지 구역 밖에 있습니다.');
  return {index,page:img.closest('[data-urs-page]')?.getAttribute('data-urs-page')||null,loaded:img.complete&&img.naturalWidth>0,width_px:r.width,height_px:r.height,issues:[...new Set(issues)]};
 });
 return {images:imageChecks,visible_image_count:imageChecks.filter(i=>!i.issues.length).length,pages:pages.map((p,i)=>{
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
   if(s.display!=='none'&&q.width&&q.height&&(q.bottom>r.bottom+2||q.right>r.right+2||q.left<r.left-2||q.top<r.top-2))problems.push('페이지 밖 내용');
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
        context=b.new_context(java_script_enabled=False,viewport={'width':1280,'height':1200},service_workers='block');context.route('**/*',lambda r:r.abort());page=context.new_page()
        page.set_content(html,wait_until='load',timeout=15000)
        page.wait_for_function("() => [...document.images].every(i=>i.complete)",timeout=10000)
        page.evaluate('() => document.fonts.ready');out=page.evaluate(MEASURE)
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(120)
        narrow=page.evaluate(MEASURE);out['narrow_pages']=narrow['pages'];out['narrow_images']=narrow['images']
        enabled=b.new_context(java_script_enabled=True,viewport={'width':1280,'height':1200},service_workers='block');enabled.route('**/*',lambda r:r.abort());actual=enabled.new_page()
        actual.set_content(html,wait_until='load',timeout=15000);actual.wait_for_function("() => [...document.images].every(i=>i.complete)",timeout=10000)
        shown=actual.evaluate(MEASURE);out['script_enabled_images']=shown['images']
        actual.set_viewport_size({'width':390,'height':844});actual.wait_for_timeout(120);out['script_enabled_narrow_images']=actual.evaluate(MEASURE)['images']
        b.close()
    for pages,images in [(out['pages'],out['images']),(out['narrow_pages'],out['narrow_images']),(out['pages'],out['script_enabled_images']),(out['narrow_pages'],out['script_enabled_narrow_images'])]:
        for image in images:
            if image['issues']:
                for section in pages:
                    if section['page']==image['page']:
                        message='그림 '+str(image['index']+1)+': '+', '.join(image['issues'])
                        if message not in section['issues']:section['issues'].append(message)
    numbers=[str(i) for i in range(1,expected+1)]
    issues=[]
    if html.lstrip().startswith('```') or html.rstrip().endswith('```'):issues.append('마크다운 코드펜스가 HTML 바깥에 남아 있음')
    if [x['page'] for x in out['pages']]!=numbers:issues.append('원문 페이지 구역/번호 누락 또는 순서 불일치')
    if any(x['issues'] for x in out['narrow_pages']):issues.append('좁은 화면에서도 A4 크기/내용 유지 필요')
    if any(x['issues'] for x in out['pages']):issues.append('A4 크기/넘침/읽기 크기/이미지 확인 필요')
    if any(x['issues'] for x in out['images']+out['narrow_images']+out['script_enabled_images']+out['script_enabled_narrow_images']):issues.append('최종 HTML 사진 표시 확인 필요: JavaScript·PDF 재선택 없이 보여야 합니다.')
    if any(len(items)!=len(out['images']) for items in (out['narrow_images'],out['script_enabled_images'],out['script_enabled_narrow_images'])):issues.append('JavaScript 실행 또는 화면 크기 변경으로 사진·도면 개수가 달라졌습니다.')
    return {**out,'image_display_method':'chromium-js-on-off-offline-v2','status':'PASS' if not issues else 'NEEDS_REVIEW','issues':issues,'scope':'사진 삽입 후 최종 HTML의 Chromium 실측. 번역 정확도/도면 작은 글자의 완전성 인증이 아닙니다.'}
if __name__=='__main__':
    try:print(json.dumps(worker(sys.stdin.buffer.read().decode(),int(sys.argv[1])),ensure_ascii=False))
    except Exception:raise SystemExit(1)

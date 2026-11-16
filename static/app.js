'use strict';
let csrf = '', selected = null;
const $ = id => document.getElementById(id);
const stageNames = {source:'원본 보관',report:'HTML 보고서',verify:'독립 검증',analyze:'기술 분석',approval:'직원 승인'};
function message(text) { $('message').textContent = text; }
async function api(path, data) {
  const response = await fetch(path, {method:data === undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data === undefined?undefined:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== '/api/login') signedOut(); throw new Error(result.error || '요청에 실패했습니다.'); }
  return result;
}
function signedOut() {csrf='';selected=null;activeDoc=null;detail=null;$('workspace').hidden=true;$('identity').hidden=true;$('login-panel').hidden=false;$('review').hidden=true;$('report-preview').removeAttribute('src');$('report-prompt').value='';$('documents').replaceChildren();$('project-list').replaceChildren();$('project-body').hidden=true;}
function element(tag,text,cls) { const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node; }
async function signedIn() { const me=await api('/api/me');csrf=me.csrf;$('username').textContent=me.username;$('login-panel').hidden=true;$('workspace').hidden=false;$('identity').hidden=false;await projects();const settings=await api('/api/settings/report');$('report-prompt').value=settings.prompt;$('prompt-version').textContent=settings.version?`저장 버전 ${settings.version}`:'저장 전'; }
async function projects() {
  const list=await api('/api/projects');$('metric-projects').textContent=String(list.length);$('project-list').replaceChildren();
  if(!list.length)$('project-list').append(element('p','프로젝트가 없습니다. 새 프로젝트를 만들어 주세요.','muted small'));
  for(const project of list){const button=element('button',project.title,'project'+(selected?.id===project.id?' active':''));button.type='button';button.onclick=()=>choose(project).catch(e=>message(e.message));$('project-list').append(button);}
}
async function choose(project) { selected=project;$('project-title').textContent=project.title;$('project-body').hidden=false;document.querySelector('.selection-hint').hidden=true;await projects();await documents(); }
async function documents() {
  const project=selected;const docs=await api(`/api/projects/${project.id}/documents`);if(selected?.id!==project.id)return;
  $('documents').replaceChildren();$('metric-documents').textContent=String(docs.length);$('metric-approved').textContent='0';let approvedCount=0;
  if(!docs.length)$('documents').append(element('p','등록된 원본이 없습니다.','muted'));
  for(const doc of docs){
    const status=await api(`/api/documents/${doc.id}/status`);if(selected?.id!==project.id)return;
    if(status.approved){approvedCount++;$('metric-approved').textContent=String(approvedCount);}const row=element('article','','document');row.append(element('h4',doc.name),element('p',`${doc.pages}페이지 · 원본 바이트 보관`,'muted small'),element('p','SHA-256 '+doc.sha256,'hash'));
    const stages=element('div','','stages');
    for(const stage of status.stages){const result=status.results.filter(r=>r.stage===stage.id);const state=stage.passed?'PASS':result[0]?.status||'UNVERIFIED';stages.append(element('span',`${stageNames[stage.id]} · ${state}`,'stage'+(stage.passed?' pass':'')));}
    row.append(stages,element('p',status.approved?'현재 리비전의 직원 승인이 완료됐습니다.':'미검증 항목을 확인하고 보고서 검토에서 다음 작업을 진행하세요.','muted small'));
    const link=element('a','원본 다운로드','download');link.href=`/api/documents/${doc.id}/original`;link.download=doc.name;row.append(link);const review=element('button','보고서 검토');review.type='button';review.onclick=()=>openReview(doc).catch(e=>message(e.message));row.append(review);$('documents').append(row);
  }
}
async function submit(form, fn) { const button=form.querySelector('button');button.disabled=true;message('');try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;} }
$('login').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const data=new FormData(e.target);await api('/api/login',{username:data.get('username'),password:data.get('password')});e.target.reset();await signedIn();});};
$('new-project').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const title=new FormData(e.target).get('title');const project=await api('/api/projects',{title});e.target.reset();await choose({id:project.id,title});});};
$('upload').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const file=new FormData(e.target).get('pdf');if(!selected)throw new Error('프로젝트를 선택해 주세요.');if(!file||!file.size||file.size>20*1024*1024)throw new Error('최대 20MB의 PDF를 선택해 주세요.');const project=selected.id;const bytes=new Uint8Array(await file.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));await api(`/api/projects/${project}/documents`,{name:file.name,content:btoa(text)});e.target.reset();await documents();message('원본 등록 및 무결성 확인을 완료했습니다.');});};
$('logout').onclick=()=>submit($('identity'),async()=>{await api('/api/logout',{});signedOut();message('로그아웃했습니다.');});


let activeDoc=null,detail=null;
async function busy(button, fn){button.disabled=true;message('처리 중입니다.');try{await fn();message('처리를 완료했습니다.');}catch(e){message(e.message);}finally{button.disabled=false;}}
async function openReview(doc){activeDoc=doc;$('review').hidden=false;await refreshReview();$('review').scrollIntoView({behavior:'smooth'});}
async function refreshReview(){if(!activeDoc)return;detail=await api(`/api/documents/${activeDoc.id}/detail`);renderReview();await documents();}
function renderReview(){
 const state=detail.status;const base=`/api/documents/${activeDoc.id}`;
 $('review-title').textContent=`${activeDoc.name} · 리비전 ${state.revision}`;
 $('record-html').href=base+'/verification.html';$('record-json').href=base+'/verification.json';
 $('checklist-summary').textContent=`완료 ${state.stages.filter(s=>s.passed).length} / ${state.stages.length} · ${state.approved?'승인 완료':'승인 전'}`;
 $('checklist-steps').replaceChildren();$('process-buttons').replaceChildren();$('check-results').replaceChildren();
 for(const [index,stage] of state.stages.entries()){
  $('checklist-steps').append(element('li',`${stageNames[stage.id]} · ${stage.passed?'완료':'확인 전'}`));
  if(stage.id==='source'||stage.id==='approval')continue;
  const button=element('button',stage.id==='report'?(detail['report-metadata']?'새 리비전 보고서 생성':'보고서 생성'):stageNames[stage.id]+' 실행');
  button.disabled=state.stages.slice(0,index).some(s=>!s.passed);
  button.onclick=()=>busy(button,async()=>{await api(base+'/run',{stage:stage.id});await refreshReview();});$('process-buttons').append(button);
 }
 for(const result of state.results){const evidence=JSON.parse(result.evidence);const box=element('div',`${stageNames[result.stage]} · ${result.status} · ${evidence.reason||''}`,'result');for(const issue of evidence.issues||[])box.append(element('p',typeof issue==='string'?issue:JSON.stringify(issue)));$('check-results').append(box);}
 if(state.qualification?.blocked)$('check-results').append(element('p','최종 승인 조건: '+state.qualification.blocked,'muted small'));
 const ready=!!detail['report-metadata'];$('html-result').hidden=!ready;$('approval-panel').hidden=!ready;
 $('reviewed-html').checked=false;$('approval-note').value='';
 if(ready){
  const view=base+`/report.html?revision=${state.revision}`;
  if($('report-preview').getAttribute('src')!==view)$('report-preview').src=view;
  $('final-html').href=view;$('raw-html').href=base+`/report.raw.html?revision=${state.revision}`;
  const bindings=detail['image-bindings'];$('image-summary').textContent=`이미지 연결 ${bindings.replacements.length}개 · 미연결 ${bindings.unresolved.length}개 · 본문/표/캡션/CSS 유지`;
  $('missing-images').replaceChildren();for(const slot of bindings.unresolved)$('missing-images').append(element('li',`미연결: ${slot.uri} · HTML 위치 ${slot.offset}`));
 }else{$('report-preview').removeAttribute('src');}
 $('analysis-panel').hidden=!detail.analysis;$('analysis-content').replaceChildren();
 if(detail.analysis)for(const key of ['sections','conflicts','questions','issues']){if(detail.analysis[key]?.length){$('analysis-content').append(element('h4',({sections:'설비·공정 분석',conflicts:'사양 충돌',questions:'고객 질의',issues:'검토 항목'})[key]));for(const item of detail.analysis[key])$('analysis-content').append(element('pre',typeof item==='string'?item:JSON.stringify(item,null,2)));}}
 $('approve-document').disabled=state.approved||state.stages.filter(s=>s.id!=='approval').some(s=>!s.passed);
}
$('save-report-prompt').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const settings=await api('/api/settings/report',{prompt:$('report-prompt').value});$('prompt-version').textContent=`저장 버전 ${settings.version}`;message('보고서 프롬프트 원문을 저장했습니다. 기존 보고서는 변경하지 않았습니다.');});};
$('close-review').onclick=()=>{$('review').hidden=true;activeDoc=null;$('report-preview').removeAttribute('src');};
$('approve-document').onclick=()=>busy($('approve-document'),async()=>{if(!$('reviewed-html').checked)throw new Error('최종 HTML 검토를 확인해 주세요.');await api(`/api/documents/${activeDoc.id}/approve`,{revision:detail.status.revision,note:$('approval-note').value,reviewed_outputs:['report.html']});await refreshReview();});
(async()=>{try{await signedIn();}catch(e){signedOut();if(!e.message.includes('로그인'))message(e.message);}})();

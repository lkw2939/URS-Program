const flowBank=document.createDocumentFragment();
const flowControlTemplate=document.getElementById('review-controls');
if(flowControlTemplate){flowBank.append(flowControlTemplate.content);flowControlTemplate.remove();}
else for(const id of ['process-buttons','html-access','html-result','technical-details','review-results','check-results','analysis-panel','approval-panel']){const node=document.getElementById(id);if(node)flowBank.append(node);}
const flowOperations=new Map();
let flowRouteTicket=0,approvalDraftContext=null;
const flowScreens=new Map();
function mountFlow(){
 if(!activeDoc||!detail)return;
 if(!detail.flow)throw new Error('단계별 화면 API가 없는 이전 서버입니다. 서버 업데이트·재시작이 필요합니다.');
 const root=$('review');
 if(!$('flow-header')){
  const header=element('section','','flow-header');header.id='flow-header';const label=element('div');const count=element('p','','flow-kicker');count.id='flow-count';const title=element('h3');title.id='flow-title';label.append(count,title);const dots=element('div','','flow-dots');dots.id='flow-dots';dots.setAttribute('aria-label','작업 진행');header.append(label,dots);root.querySelector('.intro').after(header);
  let previous=header;for(let i=0;i<6;i++){const panel=element('section','','flow-panel');panel.id='flow-panel-'+i;panel.dataset.workflowPanel=i;panel.setAttribute('aria-labelledby','flow-title');flowBank.append(panel);previous=panel;}
  const nav=element('nav','','flow-nav');nav.id='flow-nav';nav.setAttribute('aria-label','단계 이동');const back=element('button','← 이전 단계');back.id='flow-back';back.type='button';const note=element('p','','flow-state');note.id='flow-state';note.setAttribute('role','status');const next=element('button','다음 단계 →','primary');next.id='flow-next';next.type='button';nav.append(back,note,next);root.append(nav);
  const historyLink=element('a','실행 기록 보기');historyLink.id='flow-history-link';historyLink.target='_blank';historyLink.rel='noopener';root.querySelector('.intro').append(historyLink);
  const archive=element('a');archive.id='saved-reviews-link';archive.target='_blank';archive.rel='noopener';root.querySelector('.intro').append(archive);
  const link=element('a');link.id='flow-report-link';link.target='_blank';link.rel='noopener';root.querySelector('.intro').append(link);
 }
 const info=detail.flow;let index=flowScreens.get(activeDoc.id)??0;
 while(index>0&&!info.steps[index].can_enter)index--;flowScreens.set(activeDoc.id,index);
 for(let i=0;i<6;i++){const page=$('flow-panel-'+i);page.hidden=false;if(i!==index&&page.parentNode!==flowBank)flowBank.append(page);}
 if($('flow-panel-'+index).parentNode!==root)root.insertBefore($('flow-panel-'+index),$('flow-nav').nextSibling);root.dataset.currentStep=String(index+1);
 document.title=`${index+1}단계 · ${info.steps[index].title} | URS`;
 writeFlowLocation(index,'replace');
 $('saved-reviews-link').href=`/api/documents/${activeDoc.id}/saved-reviews.html`;$('saved-reviews-link').textContent=`저장된 검증 결과 · ${(detail.saved_reviews||[]).length}건`;
 $('flow-history-link').href=`/api/documents/${activeDoc.id}/verification.html`;
 $('flow-count').textContent=`${index+1} / ${info.steps.length} 단계`;$('flow-title').textContent=info.steps[index].title;
 $('flow-dots').replaceChildren();for(const step of info.steps){const dot=element('span','','flow-dot'+(step.passed?' done':'')+(step.index===index?' active':''));dot.setAttribute('aria-label',`${step.index+1}단계 ${step.passed?'완료':'미완료'}`);if(step.index===index)dot.setAttribute('aria-current','step');$('flow-dots').append(dot);}
 const panels=Array.from({length:6},(_,i)=>$('flow-panel-'+i));
 for(const id of ['html-access','html-result'])if($(id).parentNode!==panels[0])panels[0].append($(id));if($('layout-editor').parentNode!==panels[2])panels[2].append($('layout-editor'));
 const verifyBox=$('view-verification').parentElement;const verifyPanel=panels[index===3?3:1];if(verifyBox.parentNode!==verifyPanel)verifyPanel.append(verifyBox);const analysisBox=$('view-analysis').parentElement;if(analysisBox.parentNode!==panels[4])panels[4].append(analysisBox);if($('approval-panel').parentNode!==panels[5])panels[5].append($('approval-panel'));
 $('review-results').hidden=true;$('advanced-targets').hidden=true;$('approval-panel').hidden=false;
 if($('process-buttons').parentNode!==panels[index])panels[index].prepend($('process-buttons'));
 for(const group of [...$('process-buttons').children])if(group.dataset.operation)flowOperations.set(group.dataset.operation,group);
 for(const [kind,group] of flowOperations){group.hidden=false;const belongs=kind==='report'&&index===0||kind==='verify'&&(index===1||index===3)||kind==='analyze'&&index===4;const host=belongs?$('process-buttons'):flowBank;if(group.parentNode!==host)host.append(group);
  if(!group.querySelector('.flow-cost')){const folded=element('details','','flow-cost');folded.append(element('summary','예상 비용·설정 상세'));for(const n of [...group.querySelectorAll('p.small')])if(n.textContent.startsWith('이번 1회')||n.textContent.startsWith('예상 비용'))folded.append(n);const estimate=[...group.querySelectorAll('button')].find(b=>b.textContent.includes('비용 확인'));if(estimate)folded.append(estimate);group.append(folded);}
 }
 // The second verification screen always operates on the final CSS version, not its parent.
 if(index===1&&info.initial_review){const r=info.initial_review;$('view-verification').disabled=false;$('view-verification').onclick=()=>window.open(`/api/documents/${activeDoc.id}/target-result.html?target=${encodeURIComponent(r.target)}&stage=verify&attempt=${r.attempt}`,'_blank','noopener');$('verification-result-note').textContent=`문구 검토에 사용한 보고서 버전 ${r.revision} · 수정은 결과 화면에서 전후 비교 후 적용하세요.`;}
 if(index===3)$('verification-result-note').textContent=detail.current_review?.reviews.verify.available?`현재 CSS 보고서 버전 ${info.revision}의 최종 검증 결과`:'CSS가 반영된 현재 보고서로 독립검증을 실행하세요. 이전 버전의 PASS는 재사용하지 않습니다.';
 $('edit-layout').disabled=$('edit-layout').disabled||!info.steps[2].can_enter;
 $('flow-back').disabled=index===0;$('flow-next').disabled=index===5||!info.steps[index].passed||!info.steps[index+1].can_enter;
 $('flow-state').textContent=info.steps[index].passed?(index===1?info.text_note+' 다음 CSS 단계로 이동하세요.':'이 단계가 완료됐습니다. 다음 단계로 이동하세요.'):info.steps[index].reason;$('flow-state').classList.toggle('passed',info.steps[index].passed);
 $('flow-report-link').hidden=!info.revision;if(info.revision){$('flow-report-link').href=`/api/documents/${activeDoc.id}/report.html?revision=${info.revision}`;$('flow-report-link').textContent=`사진 포함 보고서 열기 · 버전 ${info.revision}`;}
 const move=async step=>{const accepted=await api(`/api/documents/${activeDoc.id}/workflow-step`,{step,revision:info.revision});detail.flow=accepted;flowScreens.set(activeDoc.id,accepted.active);writeFlowLocation(accepted.active,'push');renderReview();$('flow-header').scrollIntoView({block:'start'});};
 const navigate=async target=>{root.inert=true;root.setAttribute('aria-busy','true');$('flow-back').disabled=true;$('flow-next').disabled=true;try{await move(target);}catch(error){message(error.message);}finally{mountFlow();root.inert=false;root.setAttribute('aria-busy','false');}};
 $('flow-back').onclick=()=>navigate(index-1);$('flow-next').onclick=()=>navigate(index+1);
}

function writeFlowLocation(index,method='replace'){
 if(!activeDoc)return;const url=new URL(location.href);url.searchParams.set('document',activeDoc.id);url.searchParams.set('step',String(index+1));
 if(method==='push'&&url.href===location.href)method='replace';history[method+'State']({document:activeDoc.id,step:index+1},'',url);
}
function closeFlowScreen(method=null){
 $('review').hidden=true;$('workspace').hidden=!csrf;activeDoc=null;$('report-preview').removeAttribute('src');
 for(let i=0;i<6;i++){const panel=$('flow-panel-'+i);if(panel)flowBank.append(panel);}
 document.title='URS AI REPORT SYSTEM';
 const url=new URL(location.href);url.searchParams.delete('document');url.searchParams.delete('step');
 if(method)history[method+'State']({},'',url);
}
async function restoreFlowLocation(){
 const ticket=++flowRouteTicket;const url=new URL(location.href),id=url.searchParams.get('document');
 if(!id){if(activeDoc)closeFlowScreen();return;}
 if(!/^[a-f0-9]{32}$/i.test(id)){closeFlowScreen('replace');message('문서 주소를 확인하세요.');return;}
 const value=Number(url.searchParams.get('step')||1),step=Number.isInteger(value)&&value>=1&&value<=6?value-1:0;
 try{
  if(activeDoc?.id===id){
   const accepted=await api(`/api/documents/${id}/workflow-step`,{step,revision:detail.flow.revision});if(ticket!==flowRouteTicket)return;
   detail.flow=accepted;flowScreens.set(id,accepted.active);renderReview();$('flow-header').scrollIntoView({block:'start'});
  }else{
   const found=await api(`/api/documents/${id}/detail`);if(ticket!==flowRouteTicket)return;
   if(!found.flow)throw new Error('현재 서버에 단계별 화면 API가 없습니다. 업데이트 후 서버를 재시작해 주세요.');
   await openReview({id,name:found.flow.document_name||'URS 보고서'},step,true);
  }
 }catch(error){
  if(ticket!==flowRouteTicket)return;
  if(activeDoc?.id===id){flowScreens.set(id,0);await refreshReview();writeFlowLocation(0,'replace');}else closeFlowScreen('replace');
  message(error.message);
 }
}
window.addEventListener('popstate',()=>{if(csrf)restoreFlowLocation().catch(error=>message(error.message));});

function failureText(reason){return reason.includes('대기시간(90초)')?'이전 실행 실패 기록 (당시 90초 제한): '+reason+' 다음 실행부터는 무제한 대기 정책을 적용합니다.':'최근 실패: '+reason;}
let reportCost=null;
function costText(q){if(!q||q.status!=='READY')return '예상 비용 미확인 · '+(q?.reason||'먼저 무료 비용 계산을 누르세요.')+' 입력 토큰 계산만 하며 보고서를 생성하지 않습니다.';
return `이번 1회 (설정 단가 기준): 입력 ${q.input_tokens.toLocaleString()} 토큰 $${q.input_cost_usd.toFixed(6)} + 최대 출력 ${q.max_output_tokens.toLocaleString()} 토큰 $${q.max_output_cost_usd.toFixed(6)} = 예상 상한 $${q.estimated_max_usd.toFixed(6)} / 1회 실행 한도 $${q.cap_usd.toFixed(2)}${q.blocked?' · 한도 초과':''}. 문서 누적액과 OpenAI 잔액은 별개이며 계정 잔액은 자동 조회하지 않습니다. 캐시 할인 전 예상 상한이며 실제 사용액은 응답 사용량으로 정산합니다.`+(q.layout_refinement_max_calls?" "+q.refinement_cost_note:"");}
'use strict';
let csrf = '', selected = null;
const a4Selections=new Map();
let a4PollTimer=null;
const $ = id => document.getElementById(id)||flowBank.querySelector('#'+id);
const stageNames = {source:'원본 보관',report:'HTML 보고서',verify:'독립 검증',analyze:'기술 분석',approval:'직원 승인'};
function message(text) { $('message').textContent = text; }
async function api(path, data) {
  const response = await fetch(path, {method:data === undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data === undefined?undefined:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== '/api/login') signedOut(); throw new Error(result.error || '요청에 실패했습니다.'); }
  return result;
}
function signedOut() {clearTimeout(a4PollTimer);a4Selections.clear();csrf='';selected=null;activeDoc=null;detail=null;$('workspace').hidden=true;$('identity').hidden=true;$('login-panel').hidden=false;$('review').hidden=true;$('report-preview').removeAttribute('src');$('report-prompt').value='';$('ai-model').value='';$('ai-effort').value='';$('ai-output-tokens').value='5000';$('ai-settings-summary').textContent='';$('documents').replaceChildren();$('project-list').replaceChildren();$('project-body').hidden=true;}
function element(tag,text,cls) { const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node; }
async function signedIn() { const me=await api('/api/me');csrf=me.csrf;$('username').textContent=me.username;$('login-panel').hidden=true;$('workspace').hidden=false;$('identity').hidden=false;await projects();renderReportTimeout(await api('/api/settings/report-timeout'));renderAISettings(await api('/api/settings/ai'));const settings=await api('/api/settings/report');$('report-prompt').value=settings.prompt;$('prompt-version').textContent=settings.version?`저장 버전 ${settings.version}`:'저장 전'; }
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
    if(status.approved){approvedCount++;$('metric-approved').textContent=String(approvedCount);}const row=element('article','','document');row.append(element('h4',doc.name),element('p',`${doc.pages}페이지 · 원본 보관`,'muted small'));
    const stages=element('div','','stages');
    stages.append(element('span',status.approved?'승인 완료':['current','previous'].includes(status.report_readability)?'보고서 검토 이어가기':'보고서 생성 대기','stage'+(status.approved?' pass':'')));
    const identity=element('details');identity.append(element('summary','원본 파일 정보'),element('p','SHA-256 '+doc.sha256,'hash'));row.append(identity);
    row.append(stages,element('p',status.approved?'현재 리비전의 직원 승인이 완료됐습니다.':'미검증 항목을 확인하고 보고서 검토에서 다음 작업을 진행하세요.','muted small'));
    const link=element('a','원본 다운로드','download');link.href=`/api/documents/${doc.id}/original`;link.download=doc.name;row.append(link);const review=element('button','보고서 검토');review.type='button';review.onclick=()=>openReview(doc).catch(e=>message(e.message));row.append(review);$('documents').append(row);
  }
}
async function submit(form, fn) { const button=form.querySelector('button[type="submit"]')||form.querySelector('button');button.disabled=true;message('');try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;} }
$('login').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const data=new FormData(e.target);await api('/api/login',{username:data.get('username'),password:data.get('password')});e.target.reset();await signedIn();await restoreFlowLocation();});};
$('new-project').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const title=new FormData(e.target).get('title');const project=await api('/api/projects',{title});e.target.reset();await choose({id:project.id,title});});};
$('upload').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const file=new FormData(e.target).get('pdf');if(!selected)throw new Error('프로젝트를 선택해 주세요.');if(!file||!file.size||file.size>20*1024*1024)throw new Error('최대 20MB의 PDF를 선택해 주세요.');const project=selected.id;const bytes=new Uint8Array(await file.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));await api(`/api/projects/${project}/documents`,{name:file.name,content:btoa(text)});e.target.reset();await documents();message('원본 등록 및 무결성 확인을 완료했습니다.');});};
$('logout').onclick=()=>submit($('identity'),async()=>{await api('/api/logout',{});signedOut();message('로그아웃했습니다.');});


let activeDoc=null,detail=null;
async function busy(button, fn){button.disabled=true;message('처리 중입니다.');try{await fn();message('처리를 완료했습니다.');}catch(e){message(e.message);}finally{button.disabled=false;}}
async function waitReport(){
 const doc=activeDoc;if(!doc)return;
 while(true){const task=await api(`/api/documents/${doc.id}/report-task`);if(task.state!=='running'){if(task.state==='failed')throw new Error(task.error);if(task.state==='none')throw new Error('서버에서 작업 상태를 확인할 수 없습니다. 기존 검증 기록을 확인하세요. 자동 재시도하지 않습니다.');break;}await new Promise(resolve=>setTimeout(resolve,1500));}
 if(activeDoc?.id===doc.id){await refreshReview();const latest=detail.status.results.find(r=>r.stage==='report'&&r.revision===detail.status.revision);if(latest&&latest.status!=='PASS')throw new Error(JSON.parse(latest.evidence).reason||'HTML 사진 표시/배치 확인이 필요합니다.');}
}
async function waitReview(stage){
 const doc=activeDoc;if(!doc)return;
 for(const button of $('process-buttons').querySelectorAll('button'))button.disabled=true;
 $('process-buttons').append(element('p',stageNames[stage]+' 실행 중입니다. 상태를 조회하고 있습니다.','muted small'));
 while(true){const task=await api(`/api/documents/${doc.id}/${stage}-task`);if(task.state!=='running'){if(activeDoc?.id===doc.id)await refreshReview();if(task.state==='failed')throw new Error(task.error);if(task.state==='none')throw new Error('작업 상태를 확인할 수 없습니다. 저장된 결과와 실패 기록을 확인하세요. 자동 재시도하지 않습니다.');break;}await new Promise(resolve=>setTimeout(resolve,1000));}
}
async function waitCurrentReview(stage,target){
 const doc=activeDoc;if(!doc)return;
 for(const button of $('process-buttons').querySelectorAll('button'))button.disabled=true;
 $('process-buttons').append(element('p',stageNames[stage]+' 실행 중입니다. 화면의 보고서를 검토합니다.','muted small'));
 while(true){await new Promise(resolve=>setTimeout(resolve,1000));const state=await api(`/api/documents/${doc.id}/target-status?target=${target}`);if(!state.reviews[stage].running)break;}
 if(activeDoc?.id===doc.id)await refreshReview();
}
async function openReview(doc,requestedStep=0,restoring=false){flowScreens.set(doc.id,0);if(!restoring){activeDoc=doc;writeFlowLocation(0,'push');}$('workspace').hidden=true;reportCost=null;activeDoc=doc;const panel=$('review');panel.hidden=false;panel.inert=true;panel.setAttribute('aria-busy','true');panel.scrollIntoView({behavior:'auto'});try{await refreshReview();if(requestedStep>0){try{const accepted=await api(`/api/documents/${doc.id}/workflow-step`,{step:requestedStep,revision:detail.flow.revision});detail.flow=accepted;flowScreens.set(doc.id,accepted.active);renderReview();}catch(error){message(error.message);writeFlowLocation(0,'replace');}}}catch(error){if(activeDoc?.id===doc.id){panel.hidden=true;$('workspace').hidden=false;$('report-preview').removeAttribute('src');}throw error;}finally{if(activeDoc?.id===doc.id){panel.inert=false;panel.setAttribute('aria-busy','false');}}if(activeDoc?.id!==doc.id)return;if(detail.report_task?.state==='running')await waitReport();for(const stage of ['verify','analyze'])if(detail.current_review?.reviews[stage]?.running)await waitCurrentReview(stage,detail.current_review.id);}
async function refreshReview(){const doc=activeDoc;if(!doc)return;const fresh=await api(`/api/documents/${doc.id}/detail`);if(activeDoc?.id!==doc.id)return;if(!fresh.flow)throw new Error('현재 서버에 단계별 화면 API가 없습니다. 업데이트 후 서버를 재시작해 주세요.');detail=fresh;renderReview();if(selected)await documents();}
function renderReview(){
 renderTargets();
 const state=detail.status;const current=detail.current_report;const currentReview=detail.current_review;const base=`/api/documents/${activeDoc.id}`;
 $('review-title').textContent=`${activeDoc.name} · ${current?'현재 직원용 보고서 버전 '+current.revision:'저장 보고서 없음'}`;
 $('current-report-context').textContent=current?`화면과 독립검증의 공통 대상: 직원용 report.html · 보고서 버전 ${current.revision} · 최근 생성 시도 ${state.revision}와 별도`:'정상 저장된 보고서가 없습니다. 최근 생성 결과를 확인하세요.';
 $('current-layout-status').textContent=detail.current_layout?.status==='PASS'?`사진 삽입 후 브라우저 A4 크기·넘침·표시 검사 통과 · 사진/도면 ${detail.current_layout.visible_image_count??detail.current_layout.image_count}개 표시 확인`:current?'기존 저장 보고서를 유지합니다. A4 배치/사진 표시는 확인 필요합니다. 새 보고서를 자동 생성하지 않습니다.':'';
 if(detail.current_layout?.design_warnings?.length)$('current-layout-status').textContent+=' · 글자 크기/축소 참고 경고 '+detail.current_layout.design_warnings.length+'건 (자동 차단하지 않음)';
 if(detail.latest_layout&&detail.latest_layout.status!=='PASS'){const pages=[...(detail.latest_layout.pages||[]),...(detail.latest_layout.narrow_pages||[]).map(p=>({...p,page:p.page+' (좁은 화면)'}))].filter(p=>p.issues.length).map(p=>`원문 ${p.page}쪽: ${p.issues.join(', ')}`).join(' · ');$('current-layout-status').textContent+=' 최근 생성의 배치 확인 필요: '+(pages||detail.latest_layout.reason||(detail.latest_layout.issues||[]).join(', '));}
 if(detail.current_layout?.status==='PASS'&&detail.current_layout.image_display_method!=='chromium-js-on-off-offline-v2')$('current-layout-status').textContent='기존 A4 배치 검사 기록입니다. 새 사진 표시 검사는 아직 하지 않았습니다. 저장된 파일은 그대로 유지합니다.';
 $('generation-contract').textContent=(detail.layout_refinement_version?'실행 중인 서버: '+detail.layout_refinement_version+' · 최초 이미지 크기 안내 → 사진 연결 → 실제 화면 검사 → 필요 시 Terra 다듬기 최대 1회. 프로그램 자동 분할 없음.':'실행 중인 서버의 Terra 배치 다듬기 지원은 미확인입니다. 서버 업데이트·재시작 상태를 확인하세요.')+'\n'+(detail.generation_contract||'');
 $('record-html').href=base+'/verification.html';$('record-json').href=base+'/verification.json';
 const displayPassed=s=>s.id==='report'?!!current&&detail.current_layout?.status==='PASS':s.id==='verify'||s.id==='analyze'?currentReview?.reviews[s.id]?.status==='PASS':s.passed;
 $('checklist-summary').textContent=`완료 ${state.stages.filter(displayPassed).length} / ${state.stages.length} · ${state.approved?'승인 완료':'승인 전'}`;
 for(const group of flowOperations.values())group.remove();flowOperations.clear();
 $('checklist-steps').replaceChildren();$('process-buttons').replaceChildren();$('check-results').replaceChildren();
 for(const [index,stage] of state.stages.entries()){
  $('checklist-steps').append(element('li',`${stageNames[stage.id]} · ${stage.id==='report'?(current?(detail.current_layout?.status==='PASS'?'저장·A4 확인 완료':'저장됨 · A4 확인 필요'):'정상 저장 보고서 없음'):displayPassed(stage)?'완료':'확인 전'}`));
  if(stage.id==='source'||stage.id==='approval')continue;
  const group=element('section',null,'execution-cost');group.dataset.operation=stage.id;group.append(element('h4',stageNames[stage.id]));const controls=element('div',null,'actions');group.append(controls);$('process-buttons').append(group);
  const button=element('button',stage.id==='report'?(current?'새 보고서 생성':'보고서 생성'):stageNames[stage.id]+' 실행');
  const reviewInfo=stage.id==='report'?null:currentReview?.reviews[stage.id]||{can_run:false,blocked_reason:'검증할 정상 저장 보고서가 없습니다. 생성 실패/배치 확인 이력을 확인하세요.'};
  const q=stage.id==='report'?reportCost:reviewInfo?.budget_preview;
  const runState=element('p','','muted small');group.append(runState);
  button.disabled=(reviewInfo?!reviewInfo.can_run:state.stages.slice(0,index).some(s=>!s.passed)||detail.report_task?.state==='running')||(stage.id==='report'&&(!q||q.status!=='READY'||q.blocked));
  const estimate=element('button',`${stageNames[stage.id]} 비용 확인 (무료)`);estimate.type='button';estimate.disabled=stage.id!=='report'&&!current;
  estimate.onclick=()=>busy(estimate,async()=>{const result=await api(base+'/cost-preview',{stage:stage.id});if(stage.id==='report')reportCost=result;await refreshReview();});controls.append(estimate);
  button.onclick=()=>busy(button,async()=>{if(stage.id==='report'){await api(base+'/run',{stage:'report',background:true});await waitReport();}else{await window.URSReview.run({base,stage:stage.id,revision:current.revision,sha256:currentReview.sha256,knownQuote:q,onProgress:text=>{message(text);runState.textContent=text;},onComplete:()=>{}});await refreshReview();}});controls.append(button);
  group.append(element('p',costText(q),'muted small'));
  if(reviewInfo){group.append(element('p',reviewInfo.running?'실행 중입니다.':reviewInfo.blocked_reason?'실행 불가 · '+reviewInfo.blocked_reason:q?.status==='READY'?'화면에서 열람하는 URS 최종 HTML과 원본 PDF를 사용합니다.':'실행을 누르면 예상 비용을 확인한 뒤 시작합니다.','muted small'));if(reviewInfo.failure)group.append(element('p',failureText(reviewInfo.failure),'result'));}

 }
 for(const result of state.results){const evidence=JSON.parse(result.evidence);const box=element('div',`${result.stage==='report'&&current&&state.revision!==current.revision?'최근 생성 시도 (현재 보고서 유지)':stageNames[result.stage]} · ${result.stage==='report'&&result.status==='PASS'&&detail.reports?.state!=='current'?'저장 성공 · A4 배치/문서 끝 확인 필요':result.status} · ${evidence.reason||''}`,'result');if(evidence.api_diagnostics)box.append(element('pre',JSON.stringify(evidence.api_diagnostics,null,2)));for(const issue of evidence.issues||[])box.append(element('p',typeof issue==='string'?issue:JSON.stringify(issue)));$('check-results').append(box);}
 for(const stage of ['verify','analyze']){const info=currentReview?.reviews[stage];if(info&&info.status!=='UNVERIFIED')$('check-results').append(element('div',`${stageNames[stage]} · ${info.status} · 화면의 현재 보고서 ${current.revision} 검토 결과${info.failure?' · '+info.failure:''}`,'result'));}
 if(state.qualification?.blocked)$('check-results').append(element('p','최종 승인 조건: '+state.qualification.blocked,'muted small'));
 const reports=detail.reports;const saved=reports?.selected;const ready=!!saved;
 $('html-result').hidden=true;$('approval-panel').hidden=!current||current.revision!==state.revision;
 const draftContext=activeDoc.id+':'+(current?.revision||'none');if(approvalDraftContext!==draftContext){$('reviewed-html').checked=false;$('approval-note').value='';approvalDraftContext=draftContext;}
 $('view-html').disabled=!ready;
 const history=$('generation-history');history.replaceChildren();
 const attempts=[...(detail.report_diagnostics||[])].reverse();const older=element('details');older.append(element('summary','이전 생성 이력'));for(const [index,attempt] of attempts.entries())(index?older:history).append(element('p',`생성 이력 · 대상 버전 ${attempt.revision} · ${attempt.started_at?new Date(attempt.started_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' (한국시간)':'시각 미기록'} · ${attempt.task==='report_layout_refine'?'배치 다듬기':'새 보고서 생성'} · API ${attempt.response_status||attempt.outcome} · ${attempt.elapsed_seconds??'?'}초 · 출력 한도 ${attempt.max_output_tokens}`));
 if(attempts.length>1)history.append(older);
 const latestStored=reports?.stored_revisions?.[0];
 if(latestStored&&(!ready||latestStored!==saved.revision)){
  history.append(element('p',`새 생성 버전 ${latestStored}은 검사 미완료/확인 필요입니다. 아래 기존 보고서는 새 생성 결과가 아닙니다. ${detail.latest_layout?.reason||''}`));
  const candidate=element('a',`새 생성 버전 ${latestStored} HTML 보기·다운로드 (검사 미완료)`,'download');candidate.href=base+`/report.html?revision=${latestStored}`;candidate.target='_blank';candidate.rel='noopener';history.append(candidate);
 }
 $('view-html').textContent=reports?.state==='previous'?`이전 보고서 보기 · 버전 ${saved.revision} (새 결과 아님)`:'최종 보고서 보기(사진 포함)';
 $('html-availability').textContent=!ready?(reports?.stored_revisions?.length?'저장된 HTML은 있으나 사진 표시·배치·문서 완전성 확인이 필요합니다':'아직 열 수 있는 완성 HTML이 없습니다'):`현재 직원용 보고서 · 버전 ${saved.revision}${reports.state==='previous'?' · 새 생성 실패/미완료로 기존 보고서 유지':''}`;
 const viewInfo=detail.staff_report||(ready?{filename:'report.html',revision:saved.revision,sha256:currentReview?.sha256||saved.metadata?.final_sha256||'미기록',report_url:base+`/report.html?revision=${saved.revision}`} :null);
 $('report-file-identity').textContent=viewInfo?`열람 파일: ${viewInfo.filename} · 저장 버전 ${viewInfo.revision} · 파일 지문 ${viewInfo.sha256.slice(0,12)}…`:'열 수 있는 직원용 최종 보고서가 없습니다.';
 $('report-download-identity').textContent=viewInfo?`${viewInfo.report_url} · SHA-256 ${viewInfo.sha256}`:'';
 $('report-preview-identity').textContent=viewInfo?`위 기본 버튼과 다운로드는 동일한 report.html · 저장 버전 ${viewInfo.revision}을 엽니다.`:'';
 $('report-photo-facts').textContent=viewInfo?.picture_facts?viewInfo.picture_facts.message+(viewInfo.picture_facts.pdf_selection_controls?' PDF 재선택 입력칸도 남아 있습니다.':''):ready?'저장 보고서는 있습니다. 현재 서버에서 새 사진 진단 정보를 제공하지 않아 표시 상태는 미확인입니다. 서버 업데이트·재시작 후 확인하세요.':'';
 renderVerificationGuide(viewInfo?.verification,ready);
 const editHistory=$('layout-edit-history');editHistory.replaceChildren();for(const entry of detail.layout_edit?.history||[]){const row=element('p',`${new Date(entry.created).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} · 원본 버전 ${entry.parent}${entry.result_revision?' → 새 버전 '+entry.result_revision:''} · ${entry.reason||entry.state}`);if(entry.result_revision){const link=element('a',' 결과 보기');link.href=base+`/report.html?revision=${entry.result_revision}`;link.target='_blank';row.append(link);}editHistory.append(row);}
 const editedLink=$('layout-edited-report');editedLink.hidden=!detail.layout_edit?.result_revision;if(detail.layout_edit?.result_revision)editedLink.href=base+`/report.html?revision=${detail.layout_edit.result_revision}`;
 const editRevision=reports?.selected?.revision;if(['running','queued'].includes(detail.layout_edit?.state)){const loadingDoc=activeDoc.id;setTimeout(()=>{if(activeDoc?.id===loadingDoc)refreshReview().catch(e=>message(e.message));},2000);}$('edit-layout').disabled=!detail.layout_edit||!editRevision||['running','queued'].includes(detail.layout_edit?.state);$('layout-edit-state').textContent=!detail.layout_edit?'현재 실행 중인 서버에 CSS 다듬기 기능이 적용되지 않았습니다. 업데이트·재시작을 확인하세요.':['running','queued'].includes(detail.layout_edit?.state)?'CSS·배치 다듬기 실행 중 · 기존 보고서는 유지됩니다.':detail.layout_edit?.state==='failed'?detail.layout_edit.reason:detail.layout_edit?.state==='finished'?`최근 배치 수정: 버전 ${detail.layout_edit.parent} → ${detail.layout_edit.result_revision} · 완료. 현재 대상 ${editRevision}.`:editRevision?`다듬기 대상: 저장 버전 ${editRevision}. 성공하면 새 버전으로 저장합니다.`:'먼저 HTML 보고서를 생성하세요.';
 $('edit-layout').onclick=()=>busy($('edit-layout'),async()=>{const docId=activeDoc.id;await api(base+'/layout-edit',{revision:editRevision,notes:$('layout-notes').value});$('layout-edit-state').textContent='CSS·배치 다듬기 접수 · 기존 보고서를 유지하며 실행 중입니다.';while(true){await new Promise(r=>setTimeout(r,1000));const job=await api(base+'/layout-edit');if(job.state==='failed'){$('layout-edit-state').textContent=job.reason;throw new Error(job.reason);}if(job.state==='finished'){if(activeDoc?.id===docId){await refreshReview();$('layout-edit-state').textContent=`배치 수정 완료 · 새 버전 ${job.result_revision}. 아래 CSS 수정 결과 보기에서 확인하세요. 다음 단계에서 최종 독립검증을 실행합니다.`;}return;}}throw new Error('작업 상태를 다시 확인하세요. 자동 재호출하지 않습니다.');});
 const storedRevision=reports?.stored_revisions?.[0];$('stored-review').hidden=!storedRevision;
 if(storedRevision){$('stored-review').href=base+`/stored-review.zip?revision=${storedRevision}`;$('stored-review').textContent=`진단용 저장 HTML·응답 기록 (.zip) · 저장 이력 ${storedRevision} · 직원용 보고서 아님`;}else $('stored-review').removeAttribute('href');
 $('html-failure').textContent=[reports?.current_failure?`현재 생성 실패: ${reports.current_failure.reason}`:'',...(reports?.invalid||[]).map(x=>`리비전 ${x.revision}: ${x.reason}`)].filter(Boolean).join(' · ');
 if(!ready)$('report-preview').removeAttribute('src');
 $('final-html').hidden=!ready;$('final-html').removeAttribute('href');$('raw-html').removeAttribute('href');
 $('view-html').onclick=null;
 if(ready){
  const view=base+`/report.html?revision=${saved.revision}`;
  if(reports.state==='previous'&&$('report-preview').getAttribute('src')!==view)$('report-preview').removeAttribute('src');
  const show=()=>{$('html-result').hidden=false;if($('report-preview').getAttribute('src')!==view)$('report-preview').src=view;};
  $('view-html').onclick=()=>{show();$('html-result').scrollIntoView({behavior:'auto',block:'start'});};
  show();
  $('final-html').textContent=reports.state==='previous'?`이전 보고서 다운로드 · 버전 ${saved.revision} (새 결과 아님)`:'직원용 최종 보고서 다운로드 (.html)';
  $('final-html').href=view;$('raw-html').hidden=!saved.raw_available;
  if(saved.raw_available)$('raw-html').textContent=saved.metadata?.generation_kind==='model_layout_edit'?'배치 수정에 보낸 HTML (이미지 연결 전 .html)':saved.metadata?.generation_kind==='employee_selected_correction'?'Terra 최초 응답 원문 (직원 수정 전·이미지 연결 전 .html)':(saved.metadata?.layout_refinement_accepted?'Terra 최초 응답 원문 (배치 다듬기 전 .html)':'Terra 응답 원문 다운로드 (이미지 연결 전 .html)');
  if(saved.raw_available)$('raw-html').href=base+`/report.raw.html?revision=${saved.revision}`;
  const meta=saved.metadata||{};
  const bindings=reports.state==='current'?detail['image-bindings']:null;
  $('image-summary').textContent=`${reports.state==='previous'?'이전 보고서':'현재 보고서'} · 리비전 ${saved.revision} · 생성 설정: ${meta.model||'미기록'} / ${meta.reasoning_effort||'기본 또는 미기록 effort'} / ${meta.max_output_tokens?meta.max_output_tokens+' 토큰':'출력 한도 미기록'} · ${saved.integrity==='verified'?'원본/최종본 무결성 확인':'복구 파일 · 무결성 메타데이터 미기록'}${meta.layout_refinement_version?(meta.layout_refinement_accepted?' · Terra 배치 다듬기 1회 채택 · 프로그램은 이미지 주소만 연결':' · Terra 최초 배치 사용 · 프로그램은 이미지 주소만 연결'):(meta.image_presentation_version?' · 이전 사진 표시 정리 적용':'')}`;
  $('missing-images').replaceChildren();for(const slot of bindings?.unresolved||[])$('missing-images').append(element('li',`미연결: ${slot.uri} · HTML 위치 ${slot.offset}`));
 }
 for(const [stage,buttonId,noteId,endpoint] of [['verify','view-verification','verification-result-note','review-verification.html'],['analyze','view-analysis','analysis-result-note','review-analysis.html']]){
  const info=currentReview?.reviews[stage];const button=$(buttonId);button.disabled=!info?.available;button.onclick=null;
  $(noteId).textContent=info?.available?`${info.previous?'이전 결과 · 최신 결과가 아닙니다':info.older_attempt?'같은 리비전의 이전 실행 결과 · 최근 실행 실패/진행 중':info.superseded?'보존된 기술분석 결과 · 최신 실행 조건은 충족하지 않음':'저장 완료'} · 보고서 리비전 ${current?.revision} · 화면의 최종 HTML 검토 결과 · 새 탭에서 읽기`:'저장된 결과가 없습니다. 실행 조건과 실패 이유를 확인하세요.';
  if(info?.available){button.onclick=()=>window.open(base+`/target-result.html?target=${currentReview.id}&stage=${stage}&attempt=${info.attempt}`,'_blank','noopener');}
 }
 mountFlow();
 $('analysis-panel').hidden=true;
 $('approve-document').disabled=state.approved||state.stages.filter(s=>s.id!=='approval').some(s=>!s.passed);
}
function renderVerificationGuide(info,available=false){
 $('verification-start-rule').textContent=info?(info.can_execute?'실행 선행 조건: 저장 보고서 확인됨. 실행 직전에 무료 비용 계산·API 설정·1회 한도를 확인하며, 이 과정에서 차단될 수 있습니다.':'실행 불가: '+info.execution_blocked_reason):available?'저장 보고서는 있으나 현재 서버에서 새 실행/PASS 진단 정보를 제공하지 않았습니다. 최신 서버로 재시작 후 확인하세요.':'실행하려면 정상적으로 열 수 있는 저장 보고서가 있어야 합니다.';
 $('verification-pass-rule').textContent=info?info.pass_rule:'PASS는 해당 보고서의 검토 완료 응답이 PASS이고 발견 항목이 없어야 합니다.';
 const box=$('verification-current-blockers');box.replaceChildren();if(!info)return;
 if(info.latest_attempt_state==='failed')box.append(element('p','최근 실행 실패: '+(info.latest_attempt_reason||'실패 이유 미기록')+' · 이전 결과가 있으면 별도로 보존합니다.'));
 box.append(element('p',info.saved_result_status?`${info.previous_attempt_result?'이전 저장 결과':'현재 적용 판정'}: ${info.saved_result_status} · 버전 ${detail.current_report.revision}`:'현재 보고서의 저장된 독립검증 결과가 없습니다. 실행 가능과 PASS는 별개입니다.'));
 for(const issue of info.findings){const kind={error:'번역 오류',review:'번역 확인 필요',program:'프로그램 점검',layout:'표시 차이'}[issue.kind];const text=element('p',`${kind} · ${issue.pages.length?issue.pages.join('·')+'쪽':'쪽 미기록'} · ${issue.problem||issue.title}`);if(issue.question)text.append(element('span',' · 질문: '+issue.question));box.append(text);}
 if(info.customer_handoff_count)box.append(element('p',`고객 확인 ${info.customer_handoff_count}건은 기술분석으로 이관했습니다. 고객 답변 대기는 독립검증 PASS를 막지 않습니다.`,'notice'));
 if(info.findings.some(i=>i.kind==='program'))box.append(element('p','프로그램 점검은 개발/운영 담당자가 직원용 report.html과 실제 전송 사본을 대조해야 합니다. 번역 문구 수정칸에서 고치지 않습니다.','notice'));
}
function renderAISettings(config){
 $('ai-model').value=config.model;$('ai-effort').value=config.effort||'';$('ai-output-tokens').value=String(config.max_output_tokens);
 $('ai-settings-summary').textContent=`${config.source==='web'?'저장 버전 '+config.version:'서버 기본값'} · 모델 ${config.model||'미설정'} · effort ${config.effort||'API 기본값'} · 출력 ${Number(config.max_output_tokens).toLocaleString()} 토큰${config.configuration_error?' · 설정 확인: '+config.configuration_error:''}`;
}
for(const preset of document.querySelectorAll('[data-output-tokens]'))preset.onclick=()=>{$('ai-output-tokens').value=preset.dataset.outputTokens;};
$('save-ai-settings').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{
 const config=await api('/api/settings/ai',{model:$('ai-model').value,effort:$('ai-effort').value,max_output_tokens:Number($('ai-output-tokens').value)});
 renderAISettings(config);message('AI 설정을 저장했습니다. 다음 호출부터 적용됩니다.');
});};
$('save-report-prompt').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const settings=await api('/api/settings/report',{prompt:$('report-prompt').value});$('prompt-version').textContent=`저장 버전 ${settings.version}`;message('보고서 프롬프트 원문을 저장했습니다. 기존 보고서는 변경하지 않았습니다.');});};
$('close-review').onclick=()=>closeFlowScreen('push');
$('approve-document').onclick=()=>busy($('approve-document'),async()=>{if(!$('reviewed-html').checked)throw new Error('최종 HTML 검토를 확인해 주세요.');await api(`/api/documents/${activeDoc.id}/approve`,{revision:detail.status.revision,note:$('approval-note').value,reviewed_outputs:['report.html']});await refreshReview();});
(async()=>{try{await signedIn();await restoreFlowLocation();}catch(e){signedOut();if(!e.message.includes('로그인'))message(e.message);}})();

function renderReportTimeout(config){
 if(config.unlimited!==true||config.timeout_seconds!==null){$('timeout-summary').textContent='현재 연결된 서버에서 무제한 대기 적용이 확인되지 않았습니다.';$('timeout-description').textContent='서버를 최신 버전으로 다시 시작한 뒤 새로고침해 주세요.';return;}
 $('timeout-summary').textContent='무제한 · HTML 보고서 생성·독립검증·기술분석·무료 비용 계산 전체 적용'+(config.legacy_timeout_seconds!==null?` · 이전 ${config.legacy_timeout_seconds}초 설정은 대기 한도로 사용하지 않습니다.`:'');
 $('timeout-description').textContent='완료 응답까지 기다리며 웹은 진행 상태를 계속 조회합니다. 연결/제공자 오류는 기록하고 자동 유료 재시도는 하지 않습니다.';
}


function renderTargets(){
 if(!activeDoc)return;
 $('usage-preview').hidden=true;$('usage-preview').replaceChildren();
 const oldParent=$('a4-parent').value;$('a4-parent').replaceChildren();
 for(const revision of detail.reports?.stored_revisions||[]){const option=element('option',`저장 보고서 리비전 ${revision}`);option.value=String(revision);$('a4-parent').append(option);}if([...$('a4-parent').options].some(o=>o.value===oldParent))$('a4-parent').value=oldParent;
 const select=$('a4-target-select');select.replaceChildren(element('option','검증 대상 선택'));select.firstChild.value='';
 for(const revision of detail.reports?.stored_revisions||[]){const option=element('option',`URS 저장 보고서 리비전 ${revision} · Terra 원본 HTML`);option.value=`stored:${activeDoc.id}:${revision}`;select.append(option);}
 for(const target of detail.targets||[]){const option=element('option',`A4 수정본 · ${target.name} · 부모 리비전 ${target.parent_revision}`);option.value=target.id;select.append(option);}
 select.value=a4Selections.get(activeDoc.id)||'';
 $('a4-target-controls').hidden=!select.value;
 $('a4-target-info').textContent=select.value?'선택한 A4 대상의 저장 상태를 확인 중입니다.':'검증할 저장 리비전 또는 A4 파일을 선택하세요. 아래 기존 실행 버튼과 별개이며 작업 리비전을 바꾸지 않습니다.';
 if(select.value)loadTarget().catch(e=>message(e.message));
}
async function loadTarget(){
 clearTimeout(a4PollTimer);
 const doc=activeDoc,target=$('a4-target-select').value;if(!doc||!target){$('a4-target-controls').hidden=true;return null;}
 const base=`/api/documents/${doc.id}`;const info=await api(base+'/target-status?target='+target);
 const targetLabel=info.kind==='stored_revision'?`리비전 ${info.parent_revision}`:'A4';
 if(activeDoc?.id!==doc.id||$('a4-target-select').value!==target)return null;
 $('a4-target-controls').hidden=false;$('a4-target-info').textContent=`선택된 입력: ${info.name} · ${(info.bytes/1024/1024).toFixed(2)} MB · 부모 리비전 ${info.parent_revision} · 현재 작업 리비전 ${detail.status.revision}와 별도 · HTML SHA-256 ${info.sha256}`;
 $('a4-target-download').href=base+'/target.html?target='+target;
 $('a4-target-actions').replaceChildren();$('a4-target-results').replaceChildren();const notes=[];
 for(const [stage,label] of [['verify','독립검증'],['analyze','기술분석']]){
  const state=info.reviews[stage];const button=element('button',`${targetLabel} ${label} 실행`);button.type='button';button.disabled=!state.can_run||state.budget_preview?.status!=='READY'||state.budget_preview?.blocked;
  const estimate=element('button',`${targetLabel} ${label} 비용 확인 (무료)`);estimate.type='button';estimate.onclick=()=>busy(estimate,async()=>{await api(base+'/target-cost-preview',{target,stage});await loadTarget();});$('a4-target-actions').append(estimate);
  button.onclick=()=>busy(button,async()=>{await api(base+'/target-run',{target,stage});$('a4-target-state').textContent=`${targetLabel} ${label} 실행 중입니다.`;await loadTarget();});$('a4-target-actions').append(button);
  if(state.budget_preview)notes.push(costText(state.budget_preview));
  if(state.blocked_reason)notes.push(label+': '+state.blocked_reason);if(state.failure)notes.push(label+': '+failureText(state.failure));
  const view=element('button',`${targetLabel} ${label} 결과 보기`);view.type='button';view.disabled=!state.available;
  if(state.available)view.onclick=()=>window.open(base+`/target-result.html?target=${target}&stage=${stage}&attempt=${state.attempt}`,'_blank','noopener');$('a4-target-results').append(view);
  if(state.older_attempt)notes.push(label+': 이전 실행 결과를 보존하고 있습니다. 최신 실행과 구분해 확인하세요.');
 }
 if(info.document_end?.trailing_code_fence_only)notes.unshift('문서 끝 점검: </html>은 있으며 그 뒤의 코드블록 표시 때문에 기존 열람 검사가 차단됐습니다. 본문 누락 여부는 독립검증으로 확인해야 합니다. 파일은 보정하지 않았습니다.');
 const statusNames={PASS:'통과',FAIL:'실패/오류',NEEDS_REVIEW:'확인 필요',UNVERIFIED:'미실행·미확인'};
 $('a4-target-state').textContent=notes.join(' · ')||`${targetLabel} 독립검증: ${statusNames[info.reviews.verify.status]} · 기술분석: ${statusNames[info.reviews.analyze.status]} · 현재 작업 리비전의 HTML을 대체하지 않습니다.`;
 if(Object.values(info.reviews).some(state=>state.running))a4PollTimer=setTimeout(()=>loadTarget().catch(e=>message(e.message)),1000);
 return info;
}
$('a4-target-select').onchange=()=>{if(!activeDoc)return;a4Selections.set(activeDoc.id,$('a4-target-select').value);if($('a4-target-select').value)loadTarget().catch(e=>message(e.message));else{ $('a4-target-controls').hidden=true;$('a4-target-info').textContent='A4 선택을 해제했습니다. 기존 프로그램의 현재 리비전은 변경하지 않았습니다.';}};
$('register-a4-target').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{
 if(!activeDoc)throw new Error('문서를 선택하세요.');const file=$('a4-file').files[0];const parent=Number($('a4-parent').value);
 if(!file||file.size>12*1024*1024||!parent)throw new Error('기존 부모 리비전과 12MB 이하 HTML을 선택하세요.');
 const doc=activeDoc.id,bytes=new Uint8Array(await file.arrayBuffer());let content='';for(let i=0;i<bytes.length;i+=8192)content+=String.fromCharCode(...bytes.subarray(i,i+8192));
 const registered=await api(`/api/documents/${doc}/review-targets`,{parent_revision:parent,name:file.name,content:btoa(content)});a4Selections.set(doc,registered.id);
 if(activeDoc?.id===doc){await refreshReview();await loadTarget();}message('A4 파일을 별도 검증 대상으로 등록했습니다. 기존 리비전·보고서·예산을 변경하지 않았으며 API 호출도 하지 않았습니다.');
});};

$('show-usage-preview').onclick=()=>busy($('show-usage-preview'),async()=>{
 if(!activeDoc)return;const doc=activeDoc.id;const info=await api(`/api/documents/${doc}/usage-preview`);if(activeDoc?.id!==doc)return;
 const box=$('usage-preview');box.hidden=false;box.replaceChildren(element('p',`1회 실행 한도 $${info.per_execution_cap_usd.toFixed(2)} · 문서 요청 ${info.request_count}/${info.request_count_limit} · 누적 사용량 정산액 $${info.settled_usage_cost_usd.toFixed(6)} · 미정산 ${info.unresolved_count}건 (실지출 아님)`));
 const table=element('table');const head=element('tr');for(const label of ['호출','상태','기존 예상액','입력/출력 토큰','사용량 정산액','정산 상태'])head.append(element('th',label));table.append(head);
 const labels={settled:'정산 완료',pending:'진행 중',usage_unknown:'사용량 미확인',legacy_rates_unknown:'과거 단가 미확인',cached_rate_unknown:'캐시 단가 미확인',service_tier_rate_unknown:'서비스 계층 단가 미확인',usage_invalid:'사용량 확인 필요'};
 for(const c of info.calls){const row=element('tr');for(const v of [c.call_id,c.state,'$'+c.original_estimate_usd.toFixed(6),`${c.usage.input_tokens??'미확인'} / ${c.usage.output_tokens??'미확인'}`,c.actual_cost_usd===null?'미확인':'$'+c.actual_cost_usd.toFixed(6),labels[c.settlement_state]||c.settlement_state])row.append(element('td',String(v)));table.append(row);}
 box.append(table,element('p',info.note,'muted small'));

});

if('BroadcastChannel' in window){const updates=new BroadcastChannel('urs-report-updates');updates.onmessage=e=>{if(activeDoc?.id===e.data?.document)refreshReview().catch(error=>message(error.message));};}

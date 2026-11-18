let reportCost=null;
function costText(q){if(!q||q.status!=='READY')return '예상 비용 미확인 · '+(q?.reason||'먼저 무료 비용 계산을 누르세요.')+' 입력 토큰 계산만 하며 보고서를 생성하지 않습니다.';
return `이번 1회 (설정 단가 기준): 입력 ${q.input_tokens.toLocaleString()} 토큰 $${q.input_cost_usd.toFixed(6)} + 최대 출력 ${q.max_output_tokens.toLocaleString()} 토큰 $${q.max_output_cost_usd.toFixed(6)} = 예상 상한 $${q.estimated_max_usd.toFixed(6)} / 1회 실행 한도 $${q.cap_usd.toFixed(2)}${q.blocked?' · 한도 초과':''}. 문서 누적액과 OpenAI 잔액은 별개이며 계정 잔액은 자동 조회하지 않습니다. 캐시 할인 전 예상 상한이며 실제 사용액은 응답 사용량으로 정산합니다.`;}
'use strict';
let csrf = '', selected = null;
const a4Selections=new Map();
let a4PollTimer=null;
const $ = id => document.getElementById(id);
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
    if(status.approved){approvedCount++;$('metric-approved').textContent=String(approvedCount);}const row=element('article','','document');row.append(element('h4',doc.name),element('p',`${doc.pages}페이지 · 원본 바이트 보관`,'muted small'),element('p','SHA-256 '+doc.sha256,'hash'));
    const stages=element('div','','stages');
    for(const stage of status.stages){const result=status.results.filter(r=>r.stage===stage.id);const state=stage.id==='report'&&stage.passed&&status.report_readability!=='current'?'저장됨 · 끝 확인 필요':stage.passed?'PASS':result[0]?.status||'UNVERIFIED';stages.append(element('span',`${stageNames[stage.id]} · ${state}`,'stage'+(stage.passed&&(stage.id!=='report'||status.report_readability==='current')?' pass':'')));}
    row.append(stages,element('p',status.approved?'현재 리비전의 직원 승인이 완료됐습니다.':'미검증 항목을 확인하고 보고서 검토에서 다음 작업을 진행하세요.','muted small'));
    const link=element('a','원본 다운로드','download');link.href=`/api/documents/${doc.id}/original`;link.download=doc.name;row.append(link);const review=element('button','보고서 검토');review.type='button';review.onclick=()=>openReview(doc).catch(e=>message(e.message));row.append(review);$('documents').append(row);
  }
}
async function submit(form, fn) { const button=form.querySelector('button[type="submit"]')||form.querySelector('button');button.disabled=true;message('');try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;} }
$('login').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const data=new FormData(e.target);await api('/api/login',{username:data.get('username'),password:data.get('password')});e.target.reset();await signedIn();});};
$('new-project').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const title=new FormData(e.target).get('title');const project=await api('/api/projects',{title});e.target.reset();await choose({id:project.id,title});});};
$('upload').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const file=new FormData(e.target).get('pdf');if(!selected)throw new Error('프로젝트를 선택해 주세요.');if(!file||!file.size||file.size>20*1024*1024)throw new Error('최대 20MB의 PDF를 선택해 주세요.');const project=selected.id;const bytes=new Uint8Array(await file.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));await api(`/api/projects/${project}/documents`,{name:file.name,content:btoa(text)});e.target.reset();await documents();message('원본 등록 및 무결성 확인을 완료했습니다.');});};
$('logout').onclick=()=>submit($('identity'),async()=>{await api('/api/logout',{});signedOut();message('로그아웃했습니다.');});


let activeDoc=null,detail=null;
async function busy(button, fn){button.disabled=true;message('처리 중입니다.');try{await fn();message('처리를 완료했습니다.');}catch(e){message(e.message);}finally{button.disabled=false;}}
async function waitReport(){
 const doc=activeDoc;if(!doc)return;
 while(true){const task=await api(`/api/documents/${doc.id}/report-task`);if(task.state!=='running'){if(task.state==='failed')throw new Error(task.error);if(task.state==='none')throw new Error('서버에서 작업 상태를 확인할 수 없습니다. 기존 검증 기록을 확인하세요. 자동 재시도하지 않습니다.');break;}await new Promise(resolve=>setTimeout(resolve,1500));}
 if(activeDoc?.id===doc.id)await refreshReview();
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
async function openReview(doc){reportCost=null;activeDoc=doc;$('review').hidden=false;await refreshReview();$('review').scrollIntoView({behavior:'smooth'});if(detail.report_task?.state==='running')await waitReport();for(const stage of ['verify','analyze'])if(detail.current_review?.reviews[stage]?.running)await waitCurrentReview(stage,detail.current_review.id);}
async function refreshReview(){if(!activeDoc)return;detail=await api(`/api/documents/${activeDoc.id}/detail`);renderReview();await documents();}
function renderReview(){
 renderTargets();
 const state=detail.status;const current=detail.current_report;const currentReview=detail.current_review;const base=`/api/documents/${activeDoc.id}`;
 $('review-title').textContent=`${activeDoc.name} · ${current?'현재 저장 보고서 '+current.revision:'저장 보고서 없음'}`;
 $('current-report-context').textContent=current?`화면과 독립검증의 공통 대상: URS 최종 HTML(사진 포함) · 저장 이력 ${current.revision} · 최근 생성 시도 ${state.revision}와 별도 · SHA-256 ${currentReview?.sha256||current.metadata.final_sha256||'미기록'}`:'정상 저장된 보고서가 없습니다. 최근 생성 결과를 확인하세요.';
 $('current-layout-status').textContent=detail.current_layout?.status==='PASS'?'사진 삽입 후 브라우저 A4 크기·넘침·표시 검사 통과':current?'기존 저장 보고서를 유지합니다. A4 배치/사진 표시는 확인 필요합니다. 새 보고서를 자동 생성하지 않습니다.':'';
 if(detail.latest_layout&&detail.latest_layout.status!=='PASS'){const pages=[...(detail.latest_layout.pages||[]),...(detail.latest_layout.narrow_pages||[]).map(p=>({...p,page:p.page+' (좁은 화면)'}))].filter(p=>p.issues.length).map(p=>`원문 ${p.page}쪽: ${p.issues.join(', ')}`).join(' · ');$('current-layout-status').textContent+=' 최근 생성의 배치 확인 필요: '+(pages||detail.latest_layout.reason||(detail.latest_layout.issues||[]).join(', '));}
 $('generation-contract').textContent=detail.generation_contract||'';
 $('record-html').href=base+'/verification.html';$('record-json').href=base+'/verification.json';
 const displayPassed=s=>s.id==='report'?!!current&&detail.current_layout?.status==='PASS':s.id==='verify'||s.id==='analyze'?currentReview?.reviews[s.id]?.status==='PASS':s.passed;
 $('checklist-summary').textContent=`완료 ${state.stages.filter(displayPassed).length} / ${state.stages.length} · ${state.approved?'승인 완료':'승인 전'}`;
 $('checklist-steps').replaceChildren();$('process-buttons').replaceChildren();$('check-results').replaceChildren();
 for(const [index,stage] of state.stages.entries()){
  $('checklist-steps').append(element('li',`${stageNames[stage.id]} · ${stage.id==='report'?(current?(detail.current_layout?.status==='PASS'?'저장·A4 확인 완료':'저장됨 · A4 확인 필요'):'정상 저장 보고서 없음'):displayPassed(stage)?'완료':'확인 전'}`));
  if(stage.id==='source'||stage.id==='approval')continue;
  const group=element('section',null,'execution-cost');group.append(element('h4',stageNames[stage.id]));const controls=element('div',null,'actions');group.append(controls);$('process-buttons').append(group);
  const button=element('button',stage.id==='report'?(current?'새 보고서 생성':'보고서 생성'):stageNames[stage.id]+' 실행');
  const reviewInfo=stage.id==='report'?null:currentReview?.reviews[stage.id]||{can_run:false,blocked_reason:'검증할 정상 저장 보고서가 없습니다. 생성 실패/배치 확인 이력을 확인하세요.'};
  const q=stage.id==='report'?reportCost:reviewInfo?.budget_preview;
  button.disabled=(reviewInfo?!reviewInfo.can_run:state.stages.slice(0,index).some(s=>!s.passed)||detail.report_task?.state==='running')||!q||q.status!=='READY'||q.blocked;
  const estimate=element('button',`${stageNames[stage.id]} 비용 확인 (무료)`);estimate.type='button';estimate.disabled=stage.id!=='report'&&!current;
  estimate.onclick=()=>busy(estimate,async()=>{const result=await api(base+'/cost-preview',{stage:stage.id});if(stage.id==='report')reportCost=result;await refreshReview();});controls.append(estimate);
  button.onclick=()=>busy(button,async()=>{if(stage.id==='report'){await api(base+'/run',{stage:'report',background:true});await waitReport();}else{const accepted=await api(base+'/current-review-run',{stage:stage.id,expected_revision:current.revision,expected_sha256:currentReview.sha256});await waitCurrentReview(stage.id,accepted.target);}});controls.append(button);
  group.append(element('p',costText(q),'muted small'));
  if(reviewInfo){group.append(element('p',reviewInfo.running?'실행 중입니다.':reviewInfo.blocked_reason?'실행 불가 · '+reviewInfo.blocked_reason:q?.status==='READY'?'화면에서 열람하는 URS 최종 HTML과 원본 PDF를 사용합니다.':'비용 확인 후 실행할 수 있습니다.','muted small'));if(reviewInfo.failure)group.append(element('p','최근 실패: '+reviewInfo.failure,'result'));}

 }
 for(const result of state.results){const evidence=JSON.parse(result.evidence);const box=element('div',`${result.stage==='report'&&current&&state.revision!==current.revision?'최근 생성 시도 (현재 보고서 유지)':stageNames[result.stage]} · ${result.stage==='report'&&result.status==='PASS'&&detail.reports?.state!=='current'?'저장 성공 · A4 배치/문서 끝 확인 필요':result.status} · ${evidence.reason||''}`,'result');if(evidence.api_diagnostics)box.append(element('pre',JSON.stringify(evidence.api_diagnostics,null,2)));for(const issue of evidence.issues||[])box.append(element('p',typeof issue==='string'?issue:JSON.stringify(issue)));$('check-results').append(box);}
 for(const stage of ['verify','analyze']){const info=currentReview?.reviews[stage];if(info&&info.status!=='UNVERIFIED')$('check-results').append(element('div',`${stageNames[stage]} · ${info.status} · 화면의 현재 보고서 ${current.revision} 검토 결과${info.failure?' · '+info.failure:''}`,'result'));}
 if(state.qualification?.blocked)$('check-results').append(element('p','최종 승인 조건: '+state.qualification.blocked,'muted small'));
 const reports=detail.reports;const saved=reports?.selected;const ready=!!saved;
 $('html-result').hidden=true;$('approval-panel').hidden=!current||current.revision!==state.revision;
 $('reviewed-html').checked=false;$('approval-note').value='';
 $('view-html').disabled=!ready;
 $('view-html').textContent='HTML 확인';
 $('html-availability').textContent=!ready?(reports?.stored_revisions?.length?'저장된 HTML은 있으나 문서 끝·완전성 확인이 필요합니다':'아직 열 수 있는 완성 HTML이 없습니다'):`현재 열람 보고서 · 저장 이력 ${saved.revision}${reports.state==='previous'?' · 새 생성 실패/미완료로 기존 보고서 유지':''}`;
 const storedRevision=reports?.stored_revisions?.[0];$('stored-review').hidden=!storedRevision;
 if(storedRevision)$('stored-review').href=base+`/stored-review.zip?revision=${storedRevision}`;else $('stored-review').removeAttribute('href');
 $('html-failure').textContent=[reports?.current_failure?`현재 생성 실패: ${reports.current_failure.reason}`:'',...(reports?.invalid||[]).map(x=>`리비전 ${x.revision}: ${x.reason}`)].filter(Boolean).join(' · ');
 if(!ready)$('report-preview').removeAttribute('src');
 $('final-html').removeAttribute('href');$('raw-html').removeAttribute('href');
 $('view-html').onclick=null;
 if(ready){
  const view=base+`/report.html?revision=${saved.revision}`;
  if(reports.state==='previous'&&$('report-preview').getAttribute('src')!==view)$('report-preview').removeAttribute('src');
  const show=()=>{$('html-result').hidden=false;if($('report-preview').getAttribute('src')!==view)$('report-preview').src=view;};
  $('view-html').onclick=show;
  show();
  $('final-html').href=view;$('raw-html').hidden=!saved.raw_available;
  if(saved.raw_available)$('raw-html').href=base+`/report.raw.html?revision=${saved.revision}`;
  const meta=saved.metadata||{};
  const bindings=reports.state==='current'?detail['image-bindings']:null;
  $('image-summary').textContent=`${reports.state==='previous'?'이전 보고서':'현재 보고서'} · 리비전 ${saved.revision} · 생성 설정: ${meta.model||'미기록'} / ${meta.reasoning_effort||'기본 또는 미기록 effort'} / ${meta.max_output_tokens?meta.max_output_tokens+' 토큰':'출력 한도 미기록'} · ${saved.integrity==='verified'?'원본/최종본 무결성 확인':'복구 파일 · 무결성 메타데이터 미기록'}`;
  $('missing-images').replaceChildren();for(const slot of bindings?.unresolved||[])$('missing-images').append(element('li',`미연결: ${slot.uri} · HTML 위치 ${slot.offset}`));
 }
 for(const [stage,buttonId,noteId,endpoint] of [['verify','view-verification','verification-result-note','review-verification.html'],['analyze','view-analysis','analysis-result-note','review-analysis.html']]){
  const info=currentReview?.reviews[stage];const button=$(buttonId);button.disabled=!info?.available;button.onclick=null;
  $(noteId).textContent=info?.available?`${info.previous?'이전 결과 · 최신 결과가 아닙니다':info.older_attempt?'같은 리비전의 이전 실행 결과 · 최근 실행 실패/진행 중':info.superseded?'보존된 기술분석 결과 · 최신 실행 조건은 충족하지 않음':'현재 결과'} · 보고서 리비전 ${current?.revision} · 화면의 최종 HTML 검토 결과 · 새 탭에서 읽기`:'저장된 결과가 없습니다. 실행 조건과 실패 이유를 확인하세요.';
  if(info?.available){button.onclick=()=>window.open(base+`/target-result.html?target=${currentReview.id}&stage=${stage}&attempt=${info.attempt}`,'_blank','noopener');}
 }
 $('analysis-panel').hidden=true;
 $('approve-document').disabled=state.approved||state.stages.filter(s=>s.id!=='approval').some(s=>!s.passed);
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
$('close-review').onclick=()=>{$('review').hidden=true;activeDoc=null;$('report-preview').removeAttribute('src');};
$('approve-document').onclick=()=>busy($('approve-document'),async()=>{if(!$('reviewed-html').checked)throw new Error('최종 HTML 검토를 확인해 주세요.');await api(`/api/documents/${activeDoc.id}/approve`,{revision:detail.status.revision,note:$('approval-note').value,reviewed_outputs:['report.html']});await refreshReview();});
(async()=>{try{await signedIn();}catch(e){signedOut();if(!e.message.includes('로그인'))message(e.message);}})();

function renderReportTimeout(config){$('report-timeout').value=config.timeout_seconds;$('timeout-summary').textContent=`보고서 API 대기시간 ${config.timeout_seconds}초 · ${config.source==='web'?'웹 저장값':'서버 기본값'}`;}
$('save-report-timeout').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{renderReportTimeout(await api('/api/settings/report-timeout',{timeout_seconds:Number($('report-timeout').value)}));message('대기시간을 저장했습니다. 출력 토큰 설정은 변경하지 않았습니다.');});};


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
  if(state.blocked_reason)notes.push(label+': '+state.blocked_reason);if(state.failure)notes.push(label+' 실패/미확인: '+state.failure);
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

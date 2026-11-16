'use strict';
let csrf = '', selected = null;
const $ = id => document.getElementById(id);
const stageNames = {source:'원본 보관',extract:'추출',translate:'번역',verify:'독립 검증',analyze:'기술 분석',report:'보고서',approval:'직원 승인'};
function message(text) { $('message').textContent = text; }
async function api(path, data) {
  const response = await fetch(path, {method:data === undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data === undefined?undefined:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== '/api/login') signedOut(); throw new Error(result.error || '요청에 실패했습니다.'); }
  return result;
}
function signedOut() { csrf='';selected=null;$('workspace').hidden=true;$('identity').hidden=true;$('login-panel').hidden=false;$('documents').replaceChildren();$('review').hidden=true;$('project-list').replaceChildren();$('project-body').hidden=true;$('username').textContent='';for(const id of ['metric-projects','metric-documents','metric-approved'])$(id).textContent='—';document.querySelector('.selection-hint').hidden=false;for(const id of ['source-note','source-correction','approval-note'])$(id).value='';$('page-preview').removeAttribute('src');$('record-html').removeAttribute('href');$('record-json').removeAttribute('href');$('review-title').textContent='문서 검토';for(const id of ['translation-blocks','analysis-content','chat-result','check-results','export-links','checklist-steps'])$(id).replaceChildren();if(typeof activeDoc!=='undefined'){activeDoc=null;detail=null;proposal=null;} }
function element(tag,text,cls) { const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node; }
async function signedIn() { const me=await api('/api/me');csrf=me.csrf;$('username').textContent=me.username;$('login-panel').hidden=true;$('workspace').hidden=false;$('identity').hidden=false;await projects(); }
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
    row.append(stages,element('p',status.approved?'현재 리비전의 직원 승인이 완료됐습니다.':'미검증 항목을 확인하고 원문·번역 검토에서 다음 작업을 진행하세요.','muted small'));
    const link=element('a','원본 다운로드','download');link.href=`/api/documents/${doc.id}/original`;link.download=doc.name;row.append(link);const review=element('button','원문·번역 검토');review.type='button';review.onclick=()=>openReview(doc).catch(e=>message(e.message));row.append(review);$('documents').append(row);
  }
}
async function submit(form, fn) { const button=form.querySelector('button');button.disabled=true;message('');try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;} }
$('login').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const data=new FormData(e.target);await api('/api/login',{username:data.get('username'),password:data.get('password')});e.target.reset();await signedIn();});};
$('new-project').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const title=new FormData(e.target).get('title');const project=await api('/api/projects',{title});e.target.reset();await choose({id:project.id,title});});};
$('upload').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const file=new FormData(e.target).get('pdf');if(!selected)throw new Error('프로젝트를 선택해 주세요.');if(!file||!file.size||file.size>20*1024*1024)throw new Error('최대 20MB의 PDF를 선택해 주세요.');const project=selected.id;const bytes=new Uint8Array(await file.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));await api(`/api/projects/${project}/documents`,{name:file.name,content:btoa(text)});e.target.reset();await documents();message('원본 등록 및 무결성 확인을 완료했습니다.');});};
$('logout').onclick=()=>submit($('identity'),async()=>{await api('/api/logout',{});signedOut();message('로그아웃했습니다.');});
(async()=>{try{await signedIn();}catch(e){signedOut();if(!e.message.includes('로그인'))message(e.message);}})();
let activeDoc=null, detail=null, currentPage=1, corrections={}, sourceChanges={}, translationChanges={}, proposal=null;
const outputs=['translation.pdf','translation.docx','analysis.pdf','analysis.docx'];
function stateFor(stage){return detail.status.stages.find(s=>s.id===stage);}
async function refreshReview(){if(!activeDoc)return;detail=await api(`/api/documents/${activeDoc.id}/detail`);renderReview();await documents();}
async function openReview(doc){activeDoc=doc;currentPage=1;corrections={};sourceChanges={};translationChanges={};proposal=null;await refreshReview();$('review').hidden=false;$('review').scrollIntoView({behavior:'smooth',block:'start'});}
function busy(button,fn){button.disabled=true;message('작업 중입니다. AI 요청은 시간이 걸릴 수 있습니다.');Promise.resolve().then(fn).then(()=>message('작업 결과를 확인해 주세요.')).catch(e=>message(e.message)).finally(()=>button.disabled=false);}
function highlight(block){const page=detail.extraction.pages.find(p=>p.number===block.page);const rect=$('highlight-rect');$('source-highlight').setAttribute('viewBox',`0 0 ${page.width} ${page.height}`);const[x0,y0,x1,y1]=block.bbox;for(const[k,v]of Object.entries({x:x0,y:y0,width:x1-x0,height:y1-y0}))rect.setAttribute(k,String(v));}

function sourceLinks(ids){
 const links=element('div','','source-links');
 for(const id of ids){const block=detail.extraction?.pages.flatMap(p=>p.blocks).find(b=>b.id===id);if(!block)continue;
  const button=element('button',`원문 ${block.page}페이지 · ${id}`);button.type='button';button.dataset.sourceId=id;
  button.onclick=()=>{corrections[String(currentPage)]=$('source-correction').value;currentPage=block.page;$('page-select').value=String(currentPage);renderPage();highlight(block);const card=[...$('translation-blocks').children].find(c=>c.dataset.sourceId===id);if(card){card.scrollIntoView({block:'nearest'});const input=card.querySelector('textarea[data-block-id]');if(input)input.focus({preventScroll:true});}};
  links.append(button);
 }return links;
}
function renderVerificationHistory(){
 const history=detail.verification?.history||[];
 for(const [index,attempt] of history.entries())for(const issue of attempt.issues||[]){
  const box=document.createElement('details');box.className='issue-detail';
  box.append(element('summary',`검증 ${index+1}회 · ${issue.id||'문서 전체'} · ${issue.reason||issue.type}`));
  const block=detail.extraction?.pages.flatMap(p=>p.blocks).find(b=>b.id===issue.id);
  if(block)box.append(element('p','원문: '+block.text));
  if(attempt.translations?.[issue.id])box.append(element('p','당시 번역: '+attempt.translations[issue.id]));
  box.append(element('p','오류 이유: '+issue.reason));
  const later=history[index+1];
  if(later){if(later.translations?.[issue.id])box.append(element('p','수정 후 번역: '+later.translations[issue.id]));box.append(element('p',(later.issues||[]).some(x=>x.id===issue.id)?'후속 검사: 해당 항목 미해결':'후속 검사: 해당 오류 미검출. 문서 전체 통과 여부는 단계 상태를 확인하세요.'));}
  else box.append(element('p','후속 검사: 이 기록 이후 재검증 기록 없음'));
  box.append(sourceLinks(issue.id?[issue.id]:[]));$('check-results').append(box);
 }
}

function renderPage(){if(!detail.extraction)return;const page=detail.extraction.pages.find(p=>p.number===currentPage);$('page-preview').src=`/api/documents/${activeDoc.id}/page-${currentPage}`;$('source-highlight').setAttribute('viewBox',`0 0 ${page.width} ${page.height}`);$('highlight-rect').setAttribute('width','0');$('source-correction').value=corrections[String(currentPage)]||'';$('translation-blocks').replaceChildren();if(!page.blocks.length)$('translation-blocks').append(element('p',page.intentionally_blank?'원본 대조로 확인한 빈 페이지입니다. 원본 이미지는 그대로 보관합니다.':'추출된 문자가 없습니다. 원본을 대조하고 누락 원문 보완 또는 실제 빈 페이지 확인이 필요합니다.','muted'));for(const block of page.blocks){const card=element('div','','block');card.dataset.sourceId=block.id;card.append(element('p',block.id,'eyebrow'),element('p',block.text,'source-quote'));const sourceEdit=document.createElement('details');const summary=element('summary','원문 추출 문자 수정');const originalInput=document.createElement('textarea');originalInput.value=sourceChanges[block.id]??block.text;originalInput.rows=2;originalInput.oninput=()=>{sourceChanges[block.id]=originalInput.value;};sourceEdit.append(summary,originalInput);card.append(sourceEdit);const translated=detail.translation?.[block.id];if(translated!==undefined){const label=element('label','한국어 번역');const input=document.createElement('textarea');input.rows=3;input.value=translationChanges[block.id]??translated;input.dataset.blockId=block.id;input.oninput=()=>{translationChanges[block.id]=input.value;};label.append(input);card.append(label);}else card.append(element('p','번역 전 · 원문 대조를 완료한 뒤 번역을 실행하세요.','muted small'));card.onmouseenter=()=>highlight(block);card.addEventListener('focusin',()=>highlight(block));$('translation-blocks').append(card);}}
const statusLabels={PASS:'완료',FAIL:'오류 확인',NEEDS_REVIEW:'검토 필요',UNVERIFIED:'확인 전',BLOCKED:'진행 불가',NOT_IMPLEMENTED:'기능 준비 중'};
const checklistDescriptions={source:'원본 파일의 보존 상태와 무결성을 확인합니다.',extract:'모든 페이지·표·그림을 대조하고 누락 문자를 보완합니다.',translate:'모든 원문 항목의 한국어 번역을 생성합니다. 문장 의미는 다음 단계에서 검증합니다.',verify:'문장 전체 의미·부정·조건·수치·단위를 원문과 독립 대조합니다.',analyze:'설비·공정·사양 충돌·고객 질의를 출처와 함께 검토합니다.',report:'한국어 번역본과 분석 보고서의 Word/PDF를 생성하고 검사합니다.',approval:'전문가 평가 조건과 출력물 4개를 확인한 뒤 직원이 승인합니다.'};
function renderDocumentChecklist(){
 const state=detail.status;const done=state.stages.filter(s=>s.passed).length;
 $('checklist-summary').textContent=`필수 확인 완료 ${done} / ${state.stages.length}단계 · ${state.approved?'현재 리비전 승인 완료':'최종 승인 전'}`;
 $('checklist-steps').replaceChildren();
 let current=false;
 for(const [index,stage] of state.stages.entries()){
   const result=state.results.find(r=>r.stage===stage.id);const code=stage.passed?'PASS':result?.status||'UNVERIFIED';
   const waiting=code==='UNVERIFIED'&&state.stages.slice(0,index).some(s=>!s.passed);
   const label=waiting?'이전 단계 대기':code==='UNVERIFIED'&&stage.id==='approval'?'승인 대기':statusLabels[code]||'확인 필요';
   const row=element('li','','checklist-step '+(code==='PASS'?'complete':code==='FAIL'?'error':code==='NEEDS_REVIEW'||code==='BLOCKED'?'attention':'waiting'));
   row.dataset.stage=stage.id;row.dataset.status=code;
   if(!stage.passed&&!current){row.setAttribute('aria-current','step');current=true;}
   const top=element('div','','checklist-row');top.append(element('strong',`${index+1}. ${stage.id==='translate'?'번역 생성':stageNames[stage.id]}`),element('span',label,'checklist-status'));row.append(top,element('p',checklistDescriptions[stage.id],'muted small'));
   if(waiting)row.append(element('p','앞 단계의 필수 확인을 먼저 완료하세요.','small'));
   $('checklist-steps').append(row);
 }
}
function renderReview(){
 renderDocumentChecklist();
 $('record-html').href=`/api/documents/${activeDoc.id}/verification.html`;$('record-json').href=`/api/documents/${activeDoc.id}/verification.json`;
 const rev=detail.status.revision;$('review-title').textContent=`${activeDoc.name} · 리비전 ${rev}`;$('process-buttons').replaceChildren();
 for(const stage of detail.status.stages.filter(s=>s.id!=='approval')){const button=element('button',stageNames[stage.id]+(stage.passed?' 다시 검사':' 실행'));button.type='button';const index=detail.status.stages.indexOf(stage);button.disabled=detail.status.stages.slice(0,index).some(s=>!s.passed);button.onclick=()=>busy(button,async()=>{await api(`/api/documents/${activeDoc.id}/run`,{stage:stage.id});await refreshReview();});$('process-buttons').append(button);}
 $('check-results').replaceChildren();for(const result of detail.status.results){const evidence=JSON.parse(result.evidence);const box=element('div',`${stageNames[result.stage]} · ${result.status}${evidence.reason?' — '+evidence.reason:''}`,'result'+(result.status==='PASS'?'':' fail'));for(const issue of evidence.issues||[])box.append(element('p',`${issue.id||''} ${issue.reason||issue}`));$('check-results').append(box);}
 renderVerificationHistory();if(detail.verification){const last=detail.verification.history?.at(-1);if(last)$('check-results').append(element('p',`독립 검증 실행 ${detail.verification.history.length}회 · 마지막 검토 원문 ${last.reviewed_ids.length}개. 이 수치는 문서의 의미 정확도 점수가 아닙니다.`,'muted small'));}const qualification=detail.status.qualification;if(qualification)$('check-results').append(element('p',qualification.blocked?'최종 승인 차단: '+qualification.blocked:`전문가 평가집 ${qualification.total}개 중 ${qualification.correct}개 통과 · 중대 안전 오역 ${qualification.critical}개. 이 문서만의 정확도 점수는 아닙니다.`,'muted small'));
 $('source-review').hidden=!detail.extraction;$('save-translations').hidden=!detail.translation;$('page-select').replaceChildren();$('page-checks').replaceChildren();
 if(detail.extraction){const pages=detail.extraction.pages;if(!pages.some(p=>p.number===currentPage))currentPage=pages[0].number;for(const page of pages){const option=element('option',`${page.number}페이지`);option.value=String(page.number);$('page-select').append(option);const label=element('label',`${page.number}페이지 본문·표·그림 문자·주석 대조 완료`,'check');const check=document.createElement('input');check.type='checkbox';check.value=String(page.number);check.dataset.reviewedPage=String(page.number);check.checked=!!detail.extraction.review?.accepted;label.prepend(check);$('page-checks').append(label);if(page.blank_candidate){const blankLabel=element('label',`${page.number}페이지는 문자·그림·도형이 없는 실제 빈 페이지임을 확인`,'check');const blank=document.createElement('input');blank.type='checkbox';blank.value=String(page.number);blank.dataset.blankPage=String(page.number);blank.checked=page.intentionally_blank===true;blankLabel.prepend(blank);$('page-checks').append(blankLabel);}}$('page-select').value=String(currentPage);$('source-note').value=detail.extraction.review?.note||'';renderPage();}
 $('analysis-panel').hidden=!detail.analysis;$('analysis-content').replaceChildren();if(detail.analysis){for(const section of detail.analysis.sections){const box=element('div','','analysis-item');box.append(element('h4',section.title),element('p',`${{customer:'고객 원문 요구',explanation:'AI 기술 해설',capacity:'생산능력 분석',risk:'기술 검토사항'}[section.kind]} · 근거: ${section.coverage==='not_stated'?'원문 미명시 · 고객 확인 필요':section.source_ids.join(', ')}`,'muted small'));const input=document.createElement('textarea');input.value=section.text;input.rows=4;input.oninput=()=>section.text=input.value;box.append(input,sourceLinks(section.source_ids));$('analysis-content').append(box);}for(const conflict of detail.analysis.conflicts){const box=element('div','','conflict-item');box.append(element('p',`[${conflict.status}] ${conflict.title}: ${conflict.description}`),element('p',`관련 대상: ${conflict.subject} · 판단 근거: ${conflict.reason}`),element('p',`기술적 중요성: ${conflict.technical_impact} · 고객 확인: ${conflict.customer_confirmation?'필요':'직원 검토 필요'}`),sourceLinks(conflict.source_ids));$('analysis-content').append(box);}for(const q of [...detail.analysis.questions]){const box=element('div','','analysis-item');for(const [key,label]of [['question_ko','고객 질의 (한국어)'],['question_en','고객 질의 (영어)'],['reason','필요 이유']]){const l=element('label',label);const input=document.createElement('textarea');input.value=q[key];input.oninput=()=>q[key]=input.value;l.append(input);box.append(l);}const remove=element('button','이 질의 삭제');remove.onclick=()=>{detail.analysis.questions=detail.analysis.questions.filter(x=>x!==q);box.remove();};box.append(sourceLinks(q.source_ids),remove);$('analysis-content').append(box);}}
 const reportReady=stateFor('report').passed;$('exports').hidden=!reportReady;$('export-links').replaceChildren();$('output-checks').replaceChildren();if(reportReady){for(const kind of outputs){const link=element('a',(kind.startsWith('translation')?'번역본 ':'분석 보고서 ')+kind.split('.')[1].toUpperCase()+(detail.status.approved?' · 승인본':' · 검토본'),'download');link.href=`/api/documents/${activeDoc.id}/${detail.status.approved?'final':'draft'}-${kind}`;link.download=true;$('export-links').append(link);const label=element('label',kind+' 실제 파일의 본문·표·그림·서식·개요 링크 확인','check');const check=document.createElement('input');check.type='checkbox';check.value=kind;label.prepend(check);$('output-checks').append(label);}}$('approve-document').disabled=detail.status.approved;
}
$('page-select').onchange=()=>{corrections[String(currentPage)]=$('source-correction').value;currentPage=Number($('page-select').value);renderPage();};
$('source-correction').oninput=()=>{corrections[String(currentPage)]=$('source-correction').value;};
$('close-review').onclick=()=>{$('review').hidden=true;activeDoc=null;};
$('accept-source').onclick=()=>busy($('accept-source'),async()=>{const extra=Object.fromEntries(Object.entries(corrections).filter(([,v])=>v.trim()));const pages=[...$('page-checks').querySelectorAll('input[data-reviewed-page]:checked')].map(c=>Number(c.value));await api(`/api/documents/${activeDoc.id}/review-extraction`,{revision:detail.status.revision,pages,note:$('source-note').value,corrections:extra,block_corrections:sourceChanges,blank_pages:[...$('page-checks').querySelectorAll('input[data-blank-page]:checked')].map(c=>Number(c.value))});corrections={};sourceChanges={};await refreshReview();});
$('save-translations').onclick=()=>busy($('save-translations'),async()=>{const changes=Object.fromEntries(Object.entries(translationChanges).filter(([id,value])=>value!==detail.translation[id]));if(!Object.keys(changes).length)throw new Error('변경된 번역이 없습니다.');await api(`/api/documents/${activeDoc.id}/edit-translation`,{revision:detail.status.revision,changes});translationChanges={};await refreshReview();});
$('save-analysis').onclick=()=>busy($('save-analysis'),async()=>{await api(`/api/documents/${activeDoc.id}/edit-analysis`,{revision:detail.status.revision,analysis:detail.analysis});await refreshReview();});
$('chat').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{const messageText=new FormData(e.target).get('message');proposal=await api(`/api/documents/${activeDoc.id}/chat`,{revision:detail.status.revision,message:messageText});$('chat-result').replaceChildren(element('p',proposal.reply),element('p','원문 근거: '+proposal.source_ids.join(', '),'muted small'));for(const change of proposal.changes)$('chat-result').append(element('p',`[${change.id}] 수정안: ${change.text}`));if(proposal.changes.length){const button=element('button','이 수정안 적용 · 기존 검증 무효화');button.onclick=()=>busy(button,async()=>{await api(`/api/documents/${activeDoc.id}/edit-translation`,{revision:proposal.revision,changes:Object.fromEntries(proposal.changes.map(c=>[c.id,c.text]))});$('chat-result').replaceChildren();await refreshReview();});$('chat-result').append(button);}if(proposal.analysis_proposal){$('chat-result').append(element('p','보고서 수정안: '+proposal.analysis_proposal.sections.map(s=>s.title+': '+s.text).join('\n')));const button=element('button','보고서 수정안 적용 · 독립 재검증 대기');button.onclick=()=>busy(button,async()=>{await api(`/api/documents/${activeDoc.id}/edit-analysis`,{revision:proposal.revision,analysis:proposal.analysis_proposal});$('chat-result').replaceChildren();await refreshReview();});$('chat-result').append(button);}});};
$('approve-document').onclick=()=>busy($('approve-document'),async()=>{await api(`/api/documents/${activeDoc.id}/approve`,{revision:detail.status.revision,note:$('approval-note').value,reviewed_outputs:[...$('output-checks').querySelectorAll('input:checked')].map(c=>c.value)});await refreshReview();});

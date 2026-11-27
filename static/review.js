(() => {
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 async function api(url,body){let csrf='';if(body!==undefined){const me=await fetch('/api/me').then(r=>r.json());csrf=me.csrf;}const r=await fetch(url,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw new Error(value.error||'요청을 완료하지 못했습니다.');return value;}
 function consent(q,revision){
  return new Promise(resolve=>{const d=el('dialog');d.className='review-confirm';d.append(el('h2','이 보고서로 검증을 시작할까요?'),el('p','보고서 버전 '+revision+' · 이번 1회 예상 상한 $'+q.estimated_max_usd.toFixed(6)+' / 실행 한도 $'+q.cap_usd.toFixed(2)),el('p','실제 비용은 사용량에 따라 달라집니다.'));
   const start=el('button',q.blocked?'1회 실행 한도 초과':'이 보고서로 실행 시작');start.type='button';start.id='confirm-review-run';start.disabled=q.blocked;const cancel=el('button','취소');cancel.type='button';const done=value=>{d.close();d.remove();resolve(value);};start.onclick=()=>done(true);cancel.onclick=()=>done(false);d.addEventListener('cancel',e=>{e.preventDefault();done(false);});d.append(start,cancel);document.body.append(d);d.showModal();
  });
 }
 async function run({base,stage,revision,sha256,knownQuote,onProgress,onComplete}){
  onProgress?.('예상 비용 확인 중…');
  const q=await api(base+'/review-prepare',{stage,expected_revision:revision,expected_sha256:sha256});
  if(!knownQuote||knownQuote.status!=='READY'||knownQuote.fingerprint!==q.fingerprint||q.blocked){if(!await consent(q,q.revision)){onProgress?.('취소했습니다.');return;}}
  const accepted=await api(base+'/current-review-run',{stage,expected_revision:q.revision,expected_sha256:q.stored_html_sha256});
  onProgress?.('실행 중…');
  let state;do{await new Promise(r=>setTimeout(r,1000));state=await api(base+'/target-status?target='+encodeURIComponent(accepted.target));}while(state.reviews[stage].running);
  const result=state.reviews[stage];if(result.failure||result.older_attempt)throw new Error((result.failure||'최근 실행 결과를 저장하지 못했습니다.')+' 이전 결과는 보존했습니다.');if(!result.available)throw new Error(result.failure||'저장된 결과가 없습니다. 실패 기록을 확인하세요.');
  onComplete?.({url:base+'/target-result.html?target='+encodeURIComponent(accepted.target)+'&stage='+stage+'&attempt='+result.attempt,state,stage});
 }
 window.URSReview={run};
 const encoded=document.getElementById('review-data');if(!encoded)return;
 let data=JSON.parse(encoded.textContent);const base='/api/documents/'+data.document;const $=id=>document.getElementById(id);
 const message=text=>{$('correction-status').textContent=text;};
 const itemPlans=new Map();
 function itemChange(n){return {issue_id:n.dataset.issue,before:n.querySelector('[data-before]').value,after:n.querySelector('[data-after]').value,delete:n.querySelector('[data-delete]').checked,page:Number(n.querySelector('[data-page]')?.value)||undefined,confirmed:n.querySelector('[data-confirm]')?.checked===true,basis:n.querySelector('[data-basis]')?.value||'',occurrence:n.querySelector('[data-occurrence]')?.value?Number(n.querySelector('[data-occurrence]').value):undefined};}
 function clearItemPlans(){itemPlans.clear();for(const box of document.querySelectorAll('[data-item-preview],[data-apply-item]'))box.hidden=true;}

 function update(){
  if(data.editable_revision===undefined)message('실행 중인 서버는 이전 수정 기능입니다. GitHub 업데이트 후 서버를 재시작해야 항목별 수정과 다음 단계 버튼이 적용됩니다.');
  const current=data.execution_report;const verify=current?.reviews.verify,analyze=current?.reviews.analyze;
  if($('report-version-context'))$('report-version-context').textContent='보고서 버전 '+data.revision+(current&&current.revision!==data.revision?' · 현재 버전 '+current.revision:'');
  const applied=new Set(data.applied_issue_ids||[]);
  for(const finding of document.querySelectorAll('.finding')){
   const done=applied.has(finding.dataset.issue),readOnly=!data.can_edit||done;
   for(const input of finding.querySelectorAll('input,select,button'))input.disabled=readOnly;
   for(const input of finding.querySelectorAll('textarea'))input.readOnly=readOnly;
   if(done&&finding.querySelector('.proposal'))finding.querySelector('.proposal').open=false;
   if(finding.querySelector('.current-translation h4'))finding.querySelector('.current-translation h4').textContent=done?'수정 전 번역':'현재 번역';
   if(done&&finding.querySelector('.finding-top'))finding.querySelector('.finding-top').textContent=finding.querySelector('.finding-top').textContent.replace(/번역 오류|번역 확인 필요|프로그램 문제/,'처리 완료');
   if(done&&!finding.querySelector('.applied-note')){const note=el('p','저장 완료 · 현재 보고서에 반영했습니다.');note.className='applied-note';finding.querySelector('h3').after(note);}
  }
  if($('add-manual-correction'))$('add-manual-correction').disabled=!data.can_edit;
  if($('remaining-errors'))$('remaining-errors').textContent='번역 오류 '+data.error_count+'건';
  if($('remaining-reviews'))$('remaining-reviews').textContent='번역 확인 필요 '+(data.review_count-data.customer_count)+'건';
  if($('remaining-programs'))$('remaining-programs').textContent='프로그램 점검 '+data.program_count+'건';
  if($('applied-count'))$('applied-count').textContent='적용 '+(data.applied_count||0)+'건';
  $('reverify').disabled=!verify?.can_run;$('analyze-current').disabled=!analyze?.can_run||!data.flow?.steps[4].can_enter;
  $('analysis-wait').textContent=!data.flow?.steps[4].can_enter?'CSS와 최종 검증 후 실행할 수 있습니다.':analyze?.can_run?'기술분석을 실행할 수 있습니다.':analyze?.blocked_reason||'최종 검증 후 실행할 수 있습니다.';
  if(current){$('corrected-report').hidden=false;$('corrected-report').href=base+'/report.html?revision='+current.revision;$('corrected-report').textContent=current.revision!==data.revision?'수정된 보고서 보기':'보고서 보기';}
  if(!data.current_matches&&!$('historical-note')){const note=el('p','이전 검증 결과입니다.');note.id='historical-note';note.className='notice';document.querySelector('header').after(note);}
  if(!data.current_matches&&$('verified-report'))$('verified-report').textContent='이전 보고서 보기 · 버전 '+data.revision;
  const steps=data.flow?.steps||[];let next=steps[2]?.passed?(steps[3]?.passed?4:3):2;const titles={2:'CSS로 이동 →',3:'최종 검증으로 이동 →',4:'기술분석으로 이동 →'};
  const pending=data.issues.filter(i=>!i.applied&&!applied.has(i.id)&&!i.customer_confirmation&&(i.kind==='error'||i.kind==='review'||i.text_integrity));
  const visuals=data.issues.filter(i=>!i.applied&&i.kind==='program'&&!i.text_integrity);if(visuals.length&&steps[2]?.passed&&!steps[3]?.passed)next=2;
  const historical=!data.can_edit;
  const eligible=historical||!!steps[next]?.can_enter&&!pending.length;const reason=pending.length?'남은 필수 항목 '+pending.length+'개를 고쳐 저장하세요.':eligible?'이 단계의 문구 수정이 끝났습니다. 다음 단계로 이동하세요.':steps.find((s,i)=>i<next&&!s.passed)?.reason||'남은 수정 항목과 실행 상태를 확인하세요.';
  if($('work-title'))$('work-title').textContent=historical?'이전 검증 결과':pending.length?'남은 필수 수정 '+pending.length+'개':eligible?'모두 고쳤습니다':'확인이 필요합니다';
  if($('work-instruction'))$('work-instruction').textContent=!historical&&!pending.length&&!eligible?reason:'';
  for(const id of ['next-stage','next-stage-bottom'])if($(id)){const button=$(id);button.textContent=historical?'현재 보고서 작업으로 돌아가기 →':eligible?titles[next]:pending.length?'남은 '+pending.length+'개 처리 후 다음 →':'먼저 실행 상태를 확인하세요';button.disabled=!eligible;button.onclick=()=>{location.href='/?document='+encodeURIComponent(data.document)+'&step='+(historical?((data.flow?.frontier??0)+1):next+1);};}
  for(const id of ['next-stage-reason','next-stage-reason-bottom'])if($(id))$(id).textContent=historical||eligible||pending.length?'':reason;
  if($('next-action-summary'))$('next-action-summary').textContent='다음에 할 일 · '+(eligible?titles[next].replace(' →','')+' 버튼을 누르세요.':reason);
  if(!data.current_matches&&$('verification-verdict'))$('verification-verdict').textContent='수정 전 보고서 버전 '+data.revision+'의 판정: '+data.status+'. 현재 수정본의 새 판정이 아닙니다. CSS 후 최종 독립검증이 필요합니다.';
 }
 async function refresh(){clearItemPlans();data=await api(base+'/review-result-data?target='+encodeURIComponent(data.target)+'&attempt='+data.attempt);update();}
 if(location.protocol==='file:'){for(const b of document.querySelectorAll('button'))b.disabled=true;message('내려받은 HTML은 읽기 전용입니다. 수정·재검증은 로그인한 URS 웹 화면에서 진행하세요.');return;}
 function fitFields(){for(const field of document.querySelectorAll('textarea')){field.style.height='auto';field.style.height=Math.max(field.hasAttribute('data-basis')?70:128,field.scrollHeight+2)+'px';const copy=field.parentElement.querySelector('.print-value');if(copy)copy.textContent=field.value;}for(const d of document.querySelectorAll('.proposal'))d.dataset.printValues=[...d.querySelectorAll('textarea')].some(f=>f.value.trim())?'yes':'no';}
 $('findings').addEventListener('input',()=>{clearItemPlans();fitFields();});
 for(const details of document.querySelectorAll('.proposal'))details.addEventListener('toggle',fitFields);fitFields();
 window.addEventListener('beforeprint',()=>{for(const d of document.querySelectorAll('.source,.proposal,.finding-explanation'))if(!d.open&&(!d.classList.contains('proposal')||d.dataset.printValues==='yes')){d.dataset.printOpen='yes';d.open=true;}});
 window.addEventListener('afterprint',()=>{for(const d of document.querySelectorAll('[data-print-open]')){d.open=false;delete d.dataset.printOpen;}});
 const manualTemplate=document.querySelector('.finding.manual')?.cloneNode(true);let manualIndex=Number(manualTemplate?.dataset.issue.split(':')[1]||0)+1;
 if($('add-manual-correction'))$('add-manual-correction').onclick=()=>{
  if(!manualTemplate||!data.can_edit)return;const node=manualTemplate.cloneNode(true);node.dataset.issue='manual:'+manualIndex++;
  for(const field of node.querySelectorAll('textarea,input,button')){if(field.type==='checkbox')field.checked=false;else field.value='';field.disabled=false;field.readOnly=false;}
  node.classList.add('advanced-mode');node.querySelector('.proposal').open=true;$('add-manual-correction').before(node);fitFields();node.scrollIntoView({block:'center'});
 };
 $('findings').addEventListener('click',async event=>{
  const button=event.target.closest('[data-edit-item],[data-preview-item],[data-apply-item],[data-use-recommendation]');if(!button||button.disabled)return;
  const finding=button.closest('.finding'),quick=button.hasAttribute('data-use-recommendation'),status=finding.querySelector(quick?'[data-recommendation-status]':'[data-item-status]');
  if(button.hasAttribute('data-edit-item')){finding.classList.add('advanced-mode');finding.querySelector('.proposal').open=true;fitFields();finding.querySelector('[data-after]').focus();status.textContent='';return;}
  button.disabled=true;
  try{
   if(quick){
    const issue=data.issues.find(x=>x.id===finding.dataset.issue);if(!issue?.can_propose||issue.can_manual)throw new Error('이 항목은 직접 확인이 필요합니다.');
    status.textContent='추천 수정문을 저장하고 있습니다…';
    const preview=await api(base+'/correction-preview',{target:data.target,attempt:data.attempt,changes:[{issue_id:issue.id,page:issue.page,before:finding.querySelector('[data-recommendation-before]').textContent,after:finding.querySelector('[data-recommendation-after]').textContent}]});
    const saved=await api(base+'/correction-apply',{plan_id:preview.plan_id});await refresh();status.textContent='고쳤습니다 · 보고서 버전 '+saved.revision;message('저장 완료 · 버전 '+saved.revision);
    if('BroadcastChannel' in window){const c=new BroadcastChannel('urs-report-updates');c.postMessage({document:data.document});c.close();}
   }else if(button.hasAttribute('data-preview-item')){
    const change=itemChange(finding),signature=JSON.stringify(change);clearItemPlans();
    const preview=await api(base+'/correction-preview',{target:data.target,attempt:data.attempt,changes:[change]});
    if(JSON.stringify(itemChange(finding))!==signature)throw new Error('입력이 바뀌었습니다. 변경 내용을 다시 확인해 주세요.');
    itemPlans.set(finding.dataset.issue,{id:preview.plan_id,signature});const area=finding.querySelector('[data-item-preview]');area.replaceChildren(el('h4','수정 내용'));
    for(const p of preview.changes)area.append(el('p','현재: '+p.before),el('p','수정 후: '+(p.after||'(이 문구만 삭제)')));
    area.hidden=false;finding.querySelector('[data-apply-item]').hidden=false;status.textContent='';
   }else{
    const selected=itemPlans.get(finding.dataset.issue);if(!selected||selected.signature!==JSON.stringify(itemChange(finding)))throw new Error('변경 내용 확인을 먼저 눌러 주세요.');
    const saved=await api(base+'/correction-apply',{plan_id:selected.id});await refresh();
    message('저장 완료 · 버전 '+saved.revision);
    status.textContent='저장 완료 · 보고서 버전 '+saved.revision;finding.querySelector('.applied-note')?.scrollIntoView({block:'center'});
    if('BroadcastChannel' in window){const channel=new BroadcastChannel('urs-report-updates');channel.postMessage({document:data.document});channel.close();}
   }
  }catch(error){status.textContent=error.message;}finally{button.disabled=!data.can_edit||(data.applied_issue_ids||[]).includes(finding.dataset.issue);}
 });
 $('findings').addEventListener('click',event=>{if(!event.target.matches('[data-clean-invisible]'))return;const node=event.target.closest('.finding');const before=node.querySelector('[data-before]');const after=node.querySelector('[data-after]');after.value=before.value.replace(/[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]/g,'');after.dispatchEvent(new Event('input',{bubbles:true}));});
 for(const [id,stage] of [['reverify','verify'],['analyze-current','analyze']])$(id).onclick=async()=>{
  const button=$(id),current=data.execution_report;if(!current)return;button.disabled=true;
  try{await run({base,stage,revision:current.revision,sha256:current.sha256,onProgress:t=>$('run-status').textContent=t,onComplete:r=>{const link=$('new-result');link.href=r.url;link.textContent=stage==='verify'?'새 독립검증 결과 보기':'새 기술분석 결과 보기';link.hidden=false;$('run-status').textContent='결과가 저장되었습니다. 새 결과 보기를 눌러 확인하세요.';}});await refresh();}
  catch(e){$('run-status').textContent=e.message;}finally{update();}
 };
 update();
})();

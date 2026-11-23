(() => {
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 async function api(url,body){let csrf='';if(body!==undefined){const me=await fetch('/api/me').then(r=>r.json());csrf=me.csrf;}const r=await fetch(url,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw new Error(value.error||'요청을 완료하지 못했습니다.');return value;}
 function consent(q,revision){
  return new Promise(resolve=>{const d=el('dialog');d.className='review-confirm';d.append(el('h2','이 보고서로 검증을 시작할까요?'),el('p','보고서 버전 '+revision+' · 이번 1회 예상 상한 $'+q.estimated_max_usd.toFixed(6)+' / 실행 한도 $'+q.cap_usd.toFixed(2)),el('p','입력 비용과 최대 출력 비용을 합친 설정 단가 기준 예상입니다. 실제 사용량으로 정산하며 OpenAI 계정 잔액은 별도입니다.'));
   const start=el('button',q.blocked?'1회 실행 한도 초과':'이 보고서로 실행 시작');start.type='button';start.id='confirm-review-run';start.disabled=q.blocked;const cancel=el('button','취소');cancel.type='button';const done=value=>{d.close();d.remove();resolve(value);};start.onclick=()=>done(true);cancel.onclick=()=>done(false);d.addEventListener('cancel',e=>{e.preventDefault();done(false);});d.append(start,cancel);document.body.append(d);d.showModal();
  });
 }
 async function run({base,stage,revision,sha256,knownQuote,onProgress,onComplete}){
  onProgress?.('실행 자료와 예상 비용을 확인하고 있습니다. 아직 유료 검증을 시작하지 않았습니다.');
  const q=await api(base+'/review-prepare',{stage,expected_revision:revision,expected_sha256:sha256});
  if(!knownQuote||knownQuote.status!=='READY'||knownQuote.fingerprint!==q.fingerprint||q.blocked){if(!await consent(q,q.revision)){onProgress?.('실행을 취소했습니다. 유료 호출하지 않았습니다.');return;}}
  const accepted=await api(base+'/current-review-run',{stage,expected_revision:q.revision,expected_sha256:q.stored_html_sha256});
  onProgress?.('실행 중입니다. 결과가 저장될 때까지 기다립니다. 응답 대기시간 제한과 자동 유료 재시도는 없습니다.');
  let state;do{await new Promise(r=>setTimeout(r,1000));state=await api(base+'/target-status?target='+encodeURIComponent(accepted.target));}while(state.reviews[stage].running);
  const result=state.reviews[stage];if(result.failure||result.older_attempt)throw new Error((result.failure||'최근 실행 결과를 저장하지 못했습니다.')+' 이전 결과는 보존했습니다.');if(!result.available)throw new Error(result.failure||'저장된 결과가 없습니다. 실패 기록을 확인하세요.');
  onComplete?.({url:base+'/target-result.html?target='+encodeURIComponent(accepted.target)+'&stage='+stage+'&attempt='+result.attempt,state,stage});
 }
 window.URSReview={run};
 const encoded=document.getElementById('review-data');if(!encoded)return;
 let data=JSON.parse(encoded.textContent),plan=null;const base='/api/documents/'+data.document;const $=id=>document.getElementById(id);
 const message=text=>{$('correction-status').textContent=text;};
 function updateButtons(){
  const selected=[...document.querySelectorAll('[data-select]')].filter(n=>n.checked&&!n.disabled);
  $('preview-corrections').disabled=!data.can_edit||!selected.length;
  $('preview-corrections').textContent=selected.length?'선택한 '+selected.length+'개 수정 전후 확인':'수정할 항목을 선택하세요';
 }
 function update(){
  if(data.editable_revision===undefined)message('실행 중인 서버는 이전 수정 기능입니다. GitHub 업데이트 후 서버를 재시작해야 항목별 수정과 다음 단계 버튼이 적용됩니다.');
  const current=data.execution_report;const verify=current?.reviews.verify,analyze=current?.reviews.analyze;
  if($('report-version-context'))$('report-version-context').textContent='검증 대상: 보고서 버전 '+data.revision+' · 현재 직원용: '+(current?'보고서 버전 '+current.revision:'열람 가능한 보고서 없음');
  const applied=new Set(data.applied_issue_ids||[]);
  for(const finding of document.querySelectorAll('.finding')){
   const done=applied.has(finding.dataset.issue),readOnly=!data.can_edit||done;
   for(const input of finding.querySelectorAll('input,select,button'))input.disabled=readOnly;
   for(const input of finding.querySelectorAll('textarea'))input.readOnly=readOnly;
   if(done&&finding.querySelector('.proposal'))finding.querySelector('.proposal').open=false;
   if(done&&!finding.querySelector('.applied-note')){const note=el('p','이미 현재 보고서에 적용한 항목입니다. 나머지 항목은 계속 수정할 수 있습니다.');note.className='applied-note';finding.querySelector('h3').after(note);}
  }
  if($('add-manual-correction'))$('add-manual-correction').disabled=!data.can_edit;
  updateButtons();
  if($('remaining-errors'))$('remaining-errors').textContent='번역 오류 '+data.error_count+'건';
  if($('remaining-reviews'))$('remaining-reviews').textContent='번역 확인 필요 '+(data.review_count-data.customer_count)+'건';
  if($('remaining-programs'))$('remaining-programs').textContent='프로그램 점검 '+data.program_count+'건';
  if($('applied-count'))$('applied-count').textContent='적용 '+(data.applied_count||0)+'건';
  if($('edit-report-link')&&current){$('edit-report-link').href=base+'/report.html?revision='+current.revision;$('edit-report-link').textContent='현재 수정할 보고서 보기 · 버전 '+current.revision;}
  $('reverify').disabled=!verify?.can_run;$('analyze-current').disabled=!analyze?.can_run||!data.flow?.steps[4].can_enter;
  $('analysis-wait').textContent=!data.flow?.steps[4].can_enter?'단계별 작업 화면에서 CSS 배치와 최종 독립검증을 먼저 완료하세요.':analyze?.can_run?'현재 보고서의 독립검증이 통과했습니다. 기술분석을 실행할 수 있습니다.':analyze?.blocked_reason||'현재 보고서의 독립검증 PASS 후 기술분석을 실행할 수 있습니다.';
  if(current){$('corrected-report').hidden=current.revision===data.revision;$('corrected-report').href=base+'/report.html?revision='+current.revision;$('corrected-report').textContent=current.revision!==data.revision?'수정된 보고서 보기':'현재 보고서 보기';}
  if(!data.current_matches){if($('verified-report'))$('verified-report').textContent='수정 전 검증대상 보고서 보기 · 버전 '+data.revision;$('verification-state').textContent='현재 보고서는 버전 '+(current?.revision||'미확인')+'입니다. 이 결과는 수정 전 버전 '+data.revision+'의 결과입니다. '+(data.can_edit?'적용한 항목만 잠그며, 남은 항목은 현재 보고서에 이어서 반영합니다.':'현재 보고서의 결과를 확인하세요.');}
  const steps=data.flow?.steps||[];const next=steps[2]?.passed?(steps[3]?.passed?4:3):2;const titles={2:'CSS 단계로 이동 →',3:'최종 독립검증으로 이동 →',4:'기술분석으로 이동 →'};
  const eligible=!!steps[next]?.can_enter;const reason=eligible?'현재 보고서를 다음 단계에서 사용합니다.':steps.find((s,i)=>i<next&&!s.passed)?.reason||'남은 수정 항목과 실행 상태를 확인하세요.';
  for(const id of ['next-stage','next-stage-bottom'])if($(id)){const button=$(id);button.textContent=titles[next];button.disabled=!eligible;button.onclick=()=>{location.href='/?document='+encodeURIComponent(data.document)+'&step='+(next+1);};}
  for(const id of ['next-stage-reason','next-stage-reason-bottom'])if($(id))$(id).textContent=reason;
  if($('next-action-summary'))$('next-action-summary').textContent='다음에 할 일 · '+(eligible?titles[next].replace(' →','')+' 버튼을 누르세요.':reason);
  if(!data.current_matches&&$('verification-verdict'))$('verification-verdict').textContent='수정 전 보고서 버전 '+data.revision+'의 판정: '+data.status+'. 현재 수정본의 새 판정이 아닙니다. CSS 후 최종 독립검증이 필요합니다.';
 }
 async function refresh(){data=await api(base+'/review-result-data?target='+encodeURIComponent(data.target)+'&attempt='+data.attempt);update();}
 if(location.protocol==='file:'){for(const b of document.querySelectorAll('button'))b.disabled=true;message('내려받은 HTML은 읽기 전용입니다. 수정·재검증은 로그인한 URS 웹 화면에서 진행하세요.');return;}
 function fitFields(){for(const field of document.querySelectorAll('textarea')){field.style.height='auto';field.style.height=Math.max(field.hasAttribute('data-basis')?70:128,field.scrollHeight+2)+'px';const copy=field.parentElement.querySelector('.print-value');if(copy)copy.textContent=field.value;}for(const d of document.querySelectorAll('.proposal'))d.dataset.printValues=[...d.querySelectorAll('textarea')].some(f=>f.value.trim())?'yes':'no';}
 $('findings').addEventListener('input',event=>{plan=null;$('apply-corrections').hidden=true;$('correction-preview').hidden=true;if(event.target.matches('[data-select]')&&event.target.checked){const details=event.target.closest('.finding').querySelector('.proposal');if(details)details.open=true;}fitFields();updateButtons();});
 for(const details of document.querySelectorAll('.proposal'))details.addEventListener('toggle',fitFields);fitFields();
 window.addEventListener('beforeprint',()=>{for(const d of document.querySelectorAll('.source,.proposal'))if(!d.open&&(!d.classList.contains('proposal')||d.dataset.printValues==='yes')){d.dataset.printOpen='yes';d.open=true;}});
 window.addEventListener('afterprint',()=>{for(const d of document.querySelectorAll('[data-print-open]')){d.open=false;delete d.dataset.printOpen;}});
 $('preview-corrections').onclick=async()=>{
  try{const changes=[...document.querySelectorAll('.finding')].filter(n=>{const box=n.querySelector('[data-select]');return box?.checked&&!box.disabled;}).map(n=>({issue_id:n.dataset.issue,before:n.querySelector('[data-before]').value,after:n.querySelector('[data-after]').value,delete:n.querySelector('[data-delete]').checked,page:Number(n.querySelector('[data-page]')?.value)||undefined,confirmed:n.querySelector('[data-confirm]')?.checked===true,basis:n.querySelector('[data-basis]')?.value||'',occurrence:n.querySelector('[data-occurrence]')?.value?Number(n.querySelector('[data-occurrence]').value):undefined}));
   plan=await api(base+'/correction-preview',{target:data.target,attempt:data.attempt,changes});const area=$('correction-preview');area.replaceChildren();for(const p of plan.changes){const box=el('section');box.append(el('h3','원문 '+p.page+'쪽 · '+(p.occurrence||1)+'번째 문구 수정안'),el('p','현재 보고서에서 바꿀 문구: '+p.before),el('p','바꿀 문구: '+(p.after||'(이 문구만 삭제)')));area.append(box);}area.hidden=false;$('apply-corrections').hidden=false;message(plan.note);
  }catch(e){message(e.message);}
 };
 $('apply-corrections').onclick=async()=>{
  if(!plan)return;const button=$('apply-corrections');button.disabled=true;
  try{const applied=await api(base+'/correction-apply',{plan_id:plan.plan_id});button.hidden=true;plan=null;await refresh();if('BroadcastChannel' in window){const c=new BroadcastChannel('urs-report-updates');c.postMessage({document:data.document});c.close();}let note=$('historical-note');if(!note){note=el('p');note.id='historical-note';note.className='notice';document.querySelector('header').after(note);}note.textContent='이 화면은 수정 전 보고서 버전 '+data.revision+'의 검증 결과입니다. 수정본 버전 '+applied.revision+'은 최종 재검증 전이며, 남은 항목은 이 화면에서 계속 수정할 수 있습니다.';message('선택한 수정만 보고서 버전 '+applied.revision+'에 저장했습니다. 수정 전 보고서와 검증 기록은 보존했습니다.');
  }catch(e){message(e.message);}finally{button.disabled=false;}
 };
 const manualTemplate=document.querySelector('.finding.manual')?.cloneNode(true);let manualIndex=Number(manualTemplate?.dataset.issue.split(':')[1]||0)+1;
 if($('add-manual-correction'))$('add-manual-correction').onclick=()=>{
  if(!manualTemplate||!data.can_edit)return;const node=manualTemplate.cloneNode(true);node.dataset.issue='manual:'+manualIndex++;
  for(const field of node.querySelectorAll('textarea,input,button')){if(field.type==='checkbox')field.checked=false;else field.value='';field.disabled=false;field.readOnly=false;}
  node.querySelector('.proposal').open=true;node.querySelector('[data-select]').checked=true;$('findings').insertBefore(node,$('add-manual-correction'));fitFields();updateButtons();node.scrollIntoView({block:'center'});
 };
 $('findings').addEventListener('click',event=>{if(!event.target.matches('[data-clean-invisible]'))return;const node=event.target.closest('.finding');const before=node.querySelector('[data-before]');const after=node.querySelector('[data-after]');after.value=before.value.replace(/[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]/g,'');after.dispatchEvent(new Event('input',{bubbles:true}));});
 for(const [id,stage] of [['reverify','verify'],['analyze-current','analyze']])$(id).onclick=async()=>{
  const button=$(id),current=data.execution_report;if(!current)return;button.disabled=true;
  try{await run({base,stage,revision:current.revision,sha256:current.sha256,onProgress:t=>$('run-status').textContent=t,onComplete:r=>{const link=$('new-result');link.href=r.url;link.textContent=stage==='verify'?'새 독립검증 결과 보기':'새 기술분석 결과 보기';link.hidden=false;$('run-status').textContent='결과가 저장되었습니다. 새 결과 보기를 눌러 확인하세요.';}});await refresh();}
  catch(e){$('run-status').textContent=e.message;}finally{update();}
 };
 update();
})();

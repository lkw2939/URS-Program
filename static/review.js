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
 function update(){
  const current=data.execution_report;const verify=current?.reviews.verify,analyze=current?.reviews.analyze;
  if($('report-version-context'))$('report-version-context').textContent='검증 대상: 보고서 버전 '+data.revision+' · 현재 직원용: '+(current?'보고서 버전 '+current.revision:'열람 가능한 보고서 없음');
  $('preview-corrections').disabled=!data.can_edit||!data.current_matches||!data.error_count;
  $('reverify').disabled=!verify?.can_run;$('analyze-current').disabled=!analyze?.can_run||!data.flow?.steps[4].can_enter;
  $('analysis-wait').textContent=!data.flow?.steps[4].can_enter?'단계별 작업 화면에서 CSS 배치와 최종 독립검증을 먼저 완료하세요.':analyze?.can_run?'현재 보고서의 독립검증이 통과했습니다. 기술분석을 실행할 수 있습니다.':analyze?.blocked_reason||'현재 보고서의 독립검증 PASS 후 기술분석을 실행할 수 있습니다.';
  if(current){$('corrected-report').hidden=current.revision===data.revision;$('corrected-report').href=base+'/report.html?revision='+current.revision;$('corrected-report').textContent=current.revision!==data.revision?'수정된 보고서 보기':'현재 보고서 보기';}
  if(!data.current_matches){if($('verified-report'))$('verified-report').textContent='수정 전 검증대상 보고서 보기 · 버전 '+data.revision;$('verification-state').textContent='현재 보고서는 버전 '+(current?.revision||'미확인')+'입니다. 이 화면은 수정 전 버전 '+data.revision+'의 검증 결과입니다. 수정본의 독립 재검증이 필요합니다.';$('preview-corrections').disabled=true;for(const input of document.querySelectorAll('[data-select],[data-delete]'))input.disabled=true;for(const input of document.querySelectorAll('[data-before],[data-after]'))input.readOnly=true;}
 }
 async function refresh(){data=await api(base+'/review-result-data?target='+encodeURIComponent(data.target)+'&attempt='+data.attempt);update();}
 if(location.protocol==='file:'){for(const b of document.querySelectorAll('button'))b.disabled=true;message('내려받은 HTML은 읽기 전용입니다. 수정·재검증은 로그인한 URS 웹 화면에서 진행하세요.');return;}
 function fitFields(){for(const field of document.querySelectorAll('textarea')){field.style.height='auto';field.style.height=Math.max(58,field.scrollHeight+2)+'px';const copy=field.parentElement.querySelector('.print-value');if(copy)copy.textContent=field.value;}for(const d of document.querySelectorAll('.proposal'))d.dataset.printValues=[...d.querySelectorAll('textarea')].some(f=>f.value.trim())?'yes':'no';}
 $('findings').addEventListener('input',()=>{plan=null;$('apply-corrections').hidden=true;$('correction-preview').hidden=true;fitFields();});
 for(const details of document.querySelectorAll('.proposal'))details.addEventListener('toggle',fitFields);fitFields();
 window.addEventListener('beforeprint',()=>{for(const d of document.querySelectorAll('.source,.proposal'))if(!d.open&&(!d.classList.contains('proposal')||d.dataset.printValues==='yes')){d.dataset.printOpen='yes';d.open=true;}});
 window.addEventListener('afterprint',()=>{for(const d of document.querySelectorAll('[data-print-open]')){d.open=false;delete d.dataset.printOpen;}});
 $('preview-corrections').onclick=async()=>{
  try{const changes=[...document.querySelectorAll('.finding')].filter(n=>n.querySelector('[data-select]')?.checked).map(n=>({issue_id:n.dataset.issue,before:n.querySelector('[data-before]').value,after:n.querySelector('[data-after]').value,delete:n.querySelector('[data-delete]').checked}));
   plan=await api(base+'/correction-preview',{target:data.target,attempt:data.attempt,changes});const area=$('correction-preview');area.replaceChildren();for(const p of plan.changes){const box=el('section');box.append(el('h3','원문 '+p.page+'쪽 수정안'),el('p','현재 보고서에서 바꿀 문구: '+p.before),el('p','바꿀 문구: '+(p.after||'(이 문구만 삭제)')));area.append(box);}area.hidden=false;$('apply-corrections').hidden=false;message(plan.note);
  }catch(e){message(e.message);}
 };
 $('apply-corrections').onclick=async()=>{
  if(!plan)return;const button=$('apply-corrections');button.disabled=true;
  try{const applied=await api(base+'/correction-apply',{plan_id:plan.plan_id});message('선택한 수정만 보고서 버전 '+applied.revision+'에 저장했습니다. 수정 전 보고서와 검증 기록은 보존했습니다.');button.hidden=true;plan=null;await refresh();if('BroadcastChannel' in window){const c=new BroadcastChannel('urs-report-updates');c.postMessage({document:data.document});c.close();}let note=$('historical-note');if(!note){note=el('p');note.id='historical-note';note.className='notice';document.querySelector('header').after(note);}note.textContent='이 화면은 수정 전 보고서 버전 '+data.revision+'의 검증 결과입니다. 수정본 버전 '+applied.revision+'은 독립 재검증 전입니다.';
  }catch(e){message(e.message);}finally{button.disabled=false;}
 };
 for(const [id,stage] of [['reverify','verify'],['analyze-current','analyze']])$(id).onclick=async()=>{
  const button=$(id),current=data.execution_report;if(!current)return;button.disabled=true;
  try{await run({base,stage,revision:current.revision,sha256:current.sha256,onProgress:t=>$('run-status').textContent=t,onComplete:r=>{const link=$('new-result');link.href=r.url;link.textContent=stage==='verify'?'새 독립검증 결과 보기':'새 기술분석 결과 보기';link.hidden=false;$('run-status').textContent='결과가 저장되었습니다. 새 결과 보기를 눌러 확인하세요.';}});await refresh();}
  catch(e){$('run-status').textContent=e.message;}finally{update();}
 };
 update();
})();

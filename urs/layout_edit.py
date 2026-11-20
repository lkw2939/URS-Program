"""Explicit model CSS/layout edit of a saved report; append-only versions and attempts."""
import json,threading
from datetime import datetime,timezone
from urs.workflow import Blocked
from urs.gates import Status
from urs.images import ImageSlots
from urs.layout_refinement import preserved,captures,evaluate,sha,VERSION
from urs.ai_settings import effective,signature

def schema(workspace):
 with workspace.workflow.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS layout_edit_attempts(id INTEGER PRIMARY KEY,document TEXT,parent INTEGER,state TEXT,result_revision INTEGER,reason TEXT,created TEXT)')
def recover(workspace):
 schema(workspace)
 with workspace.workflow.connect() as db:db.execute("UPDATE layout_edit_attempts SET state='failed',reason='서버 재시작으로 작업이 중단됐습니다. 자동 유료 재시도하지 않았습니다.' WHERE state IN ('queued','running')")
def latest(workspace,owner,document):
 workspace.original(owner,document);schema(workspace)
 with workspace.workflow.connect() as db:
  history=[dict(r) for r in db.execute('SELECT * FROM layout_edit_attempts WHERE document=? ORDER BY id DESC LIMIT 20',(document,))]
 return {**(history[0] if history else {'state':'none'}),'history':history}
def run(workspace,owner,document,parent,notes,ident=None):
 original=workspace.original(owner,document);schema(workspace)
 if sha(original['original'])!=original['sha256']:raise Blocked('원본 PDF 무결성 검사 실패')
 with workspace._locks_guard:lock=workspace._run_locks.setdefault(document,threading.Lock())
 if not lock.acquire(False):raise Blocked('다른 문서 작업이 실행 중입니다.')
 try:
  with workspace.workflow.connect() as db:
   from urs.saved_reports import read_final
   final,info=read_final(db,document,parent)
   current=workspace.workflow._job(db,document)['revision']
   newest=db.execute("SELECT MAX(revision) FROM artifacts WHERE document=? AND kind='report.html'",(document,)).fetchone()[0]
   if parent!=newest:raise Blocked('보고서가 변경됐습니다. 화면을 새로고침하세요.')
   assets=json.loads(db.execute("SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind='report-images'",(document,parent)).fetchone()[0])
   if ident is None:ident=db.execute('INSERT INTO layout_edit_attempts(document,parent,state,reason,created) VALUES(?,?,?,?,?)',(document,parent,'running','CSS·배치 다듬기',datetime.now(timezone.utc).isoformat())).lastrowid
   else:db.execute("UPDATE layout_edit_attempts SET state='running' WHERE id=?",(ident,))
  from urs.layout_audit import inspect
  from urs.css_only import layout_policy
  audit=layout_policy(inspect(final.decode(),original['pages']))
  if audit['status']=='UNVERIFIED':raise Blocked('브라우저 검사를 실행할 수 없어 유료 호출을 시작하지 않았습니다. 서버의 Playwright·Chromium 설치/실행 상태를 확인하세요.')
  raw=final.decode();mapping={a['data_url']:a['uri'] for a in assets};by_uri={a['uri']:a['data_url'] for a in assets}
  with workspace.workflow.connect() as db:
   kind='report.refinement-response.html' if info['metadata'].get('layout_refinement_accepted') else 'report.raw.html'
   source=db.execute('SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind=?',(document,parent,kind)).fetchone()
  original_slots=ImageSlots(bytes(source[0]).decode()).slots if source else []
  embedded_slots=ImageSlots(raw,prefix='data:image/').slots
  recovered=[s[2] for s in original_slots] if len(original_slots)==len(embedded_slots) and all(by_uri.get(s[2])==i[2] for s,i in zip(original_slots,embedded_slots)) else None
  if recovered:
   for (start,end,url),uri in reversed(list(zip(embedded_slots,recovered))):raw=raw[:start]+uri+raw[end:]
  else:
   for start,end,url in reversed(embedded_slots):
    if url not in mapping:raise Blocked('원본 그림 연결 자료가 일치하지 않습니다.')
    raw=raw[:start]+mapping[url]+raw[end:]
  if any(uri not in by_uri for _,_,uri in ImageSlots(raw).slots):raise Blocked('연결되지 않은 원본 그림 주소가 있어 CSS 호출 전에 중단했습니다.')
  screens=captures(final.decode(),{**audit,'pages':[{**p,'issues':['직원이 요청한 배치 개선']} for p in audit['pages']]})
  config=effective(workspace.workflow,document=document);provider=workspace.processing.provider_for(document,config);prompt=info['metadata'].get('prompt') or workspace.report_settings(owner)['prompt'];from urs.costing import image_guide
  requested={**audit,'css_only':True,'employee_layout_request':notes or '번역 내용을 바꾸지 말고 사진·표 크기와 여백, 제목·본문 배치를 전문적인 기술 보고서로 다듬으세요.'}
  response=provider.refine_report_html(original['original'],original['name'],prompt,image_guide(assets),raw,requested,screens)
  from urs.css_only import unchanged_outside_styles
  if not unchanged_outside_styles(raw,response):raise Blocked('CSS 수정 거절: <style> 밖의 HTML이 달라졌습니다. 기존 보고서를 유지했습니다.')
  if not preserved(raw,response):raise Blocked('CSS 수정 응답에서 본문·수치·표·캡션·그림 연결이 달라져 저장하지 않았습니다.')
  result,binding,quality=evaluate(response,assets,original['pages'])
  quality=layout_policy(quality)
  if quality['status']!='PASS':raise Blocked('다듬기 후 화면 검사 미통과: '+' · '.join(quality.get('issues',[]))+'. 기존 보고서를 유지했습니다.')
  receipt={'version':VERSION,'accepted':True,'attempted':True,'max_refinements':1,'initial_raw_sha256':sha(raw),'chosen_raw_sha256':sha(response),'final_sha256':sha(result),'parent_revision':parent,'parent_sha256':sha(final),'program_pagination':False,'screenshots':[{'page':s['page'],'sha256':s['sha256']} for s in screens]}
  meta={**info['metadata'],'generation_kind':'model_layout_edit','raw_input_kind':'saved_report_with_source_image_slots','parent_revision':parent,'model':config['model'],'reasoning_effort':config['effort'],'max_output_tokens':config['max_output_tokens'],'ai_settings_signature':signature(config),'raw_sha256':sha(raw),'final_sha256':sha(result),'binding_raw_sha256':sha(response),'layout_refinement_version':VERSION,'layout_refinement_accepted':True,'layout_refinement_sha256':sha(json.dumps(receipt,ensure_ascii=False)),'layout_status':'PASS'}
  meta.pop('image_presentation_version',None);meta.pop('a4_pagination_version',None)
  items={'report.raw.html':raw.encode(),'report.refinement-response.html':response.encode(),'report.html':result.encode(),'report-images':assets,'image-bindings':binding,'layout-refinement':receipt,'layout-audit':quality,'report-metadata':meta}
  with workspace.workflow.connect() as db:
   job=workspace.workflow._job(db,document)
   if job['revision']!=current:raise Blocked('작업 중 보고서가 변경됐습니다. 결과를 덮어쓰지 않았습니다.')
   revision=current+1;content=json.loads(job['content']);content['revision']=revision
   for kind,value in items.items():db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(document,revision,kind,value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()))
   db.execute('UPDATE jobs SET revision=?,content=? WHERE id=?',(revision,json.dumps(content),document))
   workspace.workflow._record(db,document,'source',revision,'integrity',Status.PASS,{'source_sha256':original['sha256']},'original-preserved','1')
   workspace.workflow._record(db,document,'report',revision,'html-v1',Status.PASS,{'reason':'직원이 요청한 CSS·배치 다듬기 완료 · 독립 재검증 필요','parent_revision':parent},'model-layout-edit','1')
   workspace.workflow._event(db,document,revision,'layout_edit_saved',{'parent_revision':parent,'attempt':ident})
   db.execute("UPDATE layout_edit_attempts SET state='finished',result_revision=?,reason=? WHERE id=?",(revision,'CSS·배치 다듬기 완료',ident))
  return {'revision':revision,'report_url':f'/api/documents/{document}/report.html?revision={revision}'}
 except Exception as error:
  if ident:
   from urs.ai import AIError,AIBlocked
   reason=str(error) if isinstance(error,(Blocked,AIError,AIBlocked,ValueError)) else 'CSS·배치 작업 처리 실패. 기존 보고서는 유지됩니다.'
   with workspace.workflow.connect() as db:db.execute("UPDATE layout_edit_attempts SET state='failed',reason=? WHERE id=?",(reason,ident))
  raise
 finally:lock.release()
def start(workspace,owner,document,parent,notes):
 workspace.original(owner,document)
 if type(parent) is not int or not isinstance(notes,str) or len(notes)>4000:raise ValueError('다듬기 요청을 확인하세요.')
 schema(workspace)
 with workspace.workflow.connect() as db:
  running=db.execute("SELECT 1 FROM layout_edit_attempts WHERE document=? AND state IN ('queued','running')",(document,)).fetchone()
  if running:raise Blocked('CSS·배치 다듬기가 이미 실행 중입니다.')
  ident=db.execute('INSERT INTO layout_edit_attempts(document,parent,state,reason,created) VALUES(?,?,?,?,?)',(document,parent,'queued','CSS·배치 다듬기 접수',datetime.now(timezone.utc).isoformat())).lastrowid
 def work():
  try:run(workspace,owner,document,parent,notes,ident)
  except Exception as error:
   from urs.ai import AIError,AIBlocked
   reason=str(error) if isinstance(error,(Blocked,AIError,AIBlocked,ValueError)) else 'CSS·배치 작업 실패. 기존 보고서는 유지됩니다.'
   with workspace.workflow.connect() as db:db.execute("UPDATE layout_edit_attempts SET state='failed',reason=? WHERE id=? AND state IN ('queued','running')",(reason,ident))
 threading.Thread(target=work,daemon=True).start()
 return {'state':'accepted'}

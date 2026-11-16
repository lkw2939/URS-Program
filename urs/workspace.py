"""Employee access and append-only original document storage."""
import hashlib
import hmac
import io
import json
import secrets
import time
import os
import threading
from pathlib import Path

from pypdf import PdfReader

from urs.gates import Status
from urs.workflow import Workflow, Blocked

MAX_PDF = 20 * 1024 * 1024
PIPELINE = [
    {'id': 'source', 'checks': [{'id': 'integrity', 'kind': 'automatic'}]},
    *[{'id': stage, 'checks': [{'id': 'complete', 'kind': 'automatic'}]}
      for stage in ('extract', 'translate', 'verify', 'analyze', 'report')],
    {'id': 'approval', 'checks': [{'id': 'employee-review', 'kind': 'human'}]},
]


class Unauthorized(ValueError):
    pass


class AccessDenied(ValueError):
    pass


class Workspace:
    def __init__(self, path):
        self._run_locks = {}
        self._locks_guard = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.workflow = Workflow(path)
        self.workflow.define(PIPELINE)
        with self.workflow.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS qualifications(fingerprint TEXT,model TEXT,total INTEGER,correct INTEGER,critical INTEGER,reviewer TEXT,evidence TEXT,digest TEXT);
            CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, salt BLOB, digest BLOB);
            CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, name TEXT, csrf TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS attempts(name TEXT PRIMARY KEY, failures INTEGER, since REAL);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, owner TEXT, title TEXT);
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, project TEXT, name TEXT, original BLOB, sha256 TEXT, pages INTEGER);
            CREATE TRIGGER IF NOT EXISTS preserve_original_update BEFORE UPDATE ON documents BEGIN SELECT RAISE(ABORT, 'original is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS preserve_original_delete BEFORE DELETE ON documents BEGIN SELECT RAISE(ABORT, 'original is immutable'); END;
            ''')
        from urs.processing import Processing
        self.processing = Processing(self)

    @staticmethod
    def _password(password, salt):
        return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)

    def add_user(self, name, password):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('직원 ID를 확인해 주세요.')
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError('비밀번호는 12~256자여야 합니다.')
        salt = secrets.token_bytes(16)
        digest = self._password(password, salt)
        with self.workflow.connect() as db:
            db.execute('INSERT INTO users VALUES(?,?,?)', (name.strip(), salt, digest))

    def reset_password(self, name, password):
        """Local database operator only; deliberately not exposed over HTTP."""
        if not isinstance(password,str) or not 12<=len(password)<=256:
            raise ValueError('비밀번호는 12~256자여야 합니다.')
        if not isinstance(name,str) or not name.strip():raise ValueError('직원 ID를 확인해 주세요.')
        salt=secrets.token_bytes(16);digest=self._password(password,salt)
        with self.workflow.connect() as db:
            if db.execute('SELECT 1 FROM users WHERE name=?',(name,)).fetchone() is None:
                raise ValueError('등록된 직원 계정이 없습니다.')
            db.execute('UPDATE users SET salt=?,digest=? WHERE name=?',(salt,digest,name))
            db.execute('DELETE FROM sessions WHERE name=?',(name,))
            db.execute('DELETE FROM attempts WHERE name=?',(name,))

    def login(self, name, password):
        if not isinstance(name, str) or not isinstance(password, str) or len(name) > 80 or len(password) > 256:
            raise Unauthorized('로그인 정보를 확인해 주세요.')
        now = time.time()
        with self.workflow.connect() as db:
            attempt = db.execute('SELECT * FROM attempts WHERE name=?', (name,)).fetchone()
            if attempt and attempt['failures'] >= 5 and now - attempt['since'] < 60:
                raise Unauthorized('잠시 후 다시 로그인해 주세요.')
            row = db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
            salt = row['salt'] if row else b'unknown-user-salt'
            digest = self._password(password, salt)
            valid = hmac.compare_digest(digest, row['digest'] if row else bytes(64))
            if not valid:
                failures = attempt['failures'] + 1 if attempt and now - attempt['since'] < 60 else 1
                since = attempt['since'] if failures > 1 else now
                db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (name, failures, since))
            else:
                db.execute('DELETE FROM attempts WHERE name=?', (name,))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires<?', (now,))
                db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                           (hashlib.sha256(token.encode()).hexdigest(), name, csrf, now + 8 * 3600))
        if not valid:
            raise Unauthorized('로그인 정보를 확인해 주세요.')
        return token, csrf

    def session(self, token):
        with self.workflow.connect() as db:
            row = db.execute('SELECT * FROM sessions WHERE digest=? AND expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            if row is None:
                raise Unauthorized('로그인이 필요합니다.')
            return row['name'], row['csrf']

    def logout(self, token):
        with self.workflow.connect() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def _project(self, db, owner, project):
        row = db.execute('SELECT * FROM projects WHERE id=? AND owner=?', (project, owner)).fetchone()
        if row is None:
            raise AccessDenied('프로젝트에 접근할 수 없습니다.')
        return row

    def create_project(self, owner, title):
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError('프로젝트 이름은 1~200자여야 합니다.')
        project = secrets.token_hex(16)
        with self.workflow.connect() as db:
            if not db.execute('SELECT 1 FROM users WHERE name=?', (owner,)).fetchone():
                raise AccessDenied('등록되지 않은 직원입니다.')
            db.execute('INSERT INTO projects VALUES(?,?,?)', (project, owner, title.strip()))
        return project

    def projects(self, owner):
        with self.workflow.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,title FROM projects WHERE owner=? ORDER BY rowid DESC', (owner,))]

    def documents(self, owner, project):
        with self.workflow.connect() as db:
            self._project(db, owner, project)
            return [dict(r) for r in db.execute('SELECT id,name,sha256,pages FROM documents WHERE project=? ORDER BY rowid', (project,))]

    def upload(self, owner, project, name, payload):
        with self.workflow.connect() as db:
            self._project(db, owner, project)
        if not isinstance(name, str) or not name.lower().endswith('.pdf') or len(name) > 240:
            raise ValueError('PDF 파일만 등록할 수 있습니다.')
        # Client filename is display metadata only; never used as a storage path.
        name = name.replace('\\', '/').split('/')[-1]
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_PDF:
            raise ValueError('PDF 크기는 최대 20MB입니다.')
        if not payload.startswith(b'%PDF-'):
            raise ValueError('PDF 형식이 아닙니다.')
        try:
            reader = PdfReader(io.BytesIO(payload), strict=True)
            if reader.is_encrypted:
                raise ValueError('암호화 PDF는 해제 후 등록해 주세요.')
            pages = len(reader.pages)
            if pages < 1:
                raise ValueError('페이지가 없는 PDF입니다.')
        except Exception as exc:
            raise ValueError('손상·암호화 또는 지원하지 않는 PDF입니다.') from exc
        document = secrets.token_hex(16)
        digest = hashlib.sha256(payload).hexdigest()
        content = json.dumps({'document': document, 'sha256': digest, 'revision': 1})
        with self.workflow.connect() as db:
            self._project(db, owner, project)
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)', (document, project, name, payload, digest, pages))
            db.execute('INSERT INTO jobs VALUES(?,1,?)', (document, content))
            self.workflow._event(db, document, 1, 'original_uploaded', {'sha256': digest, 'pages': pages, 'actor': owner})
        self.workflow.run(document, 'source', self.validators())
        return document

    def original(self, owner, document):
        with self.workflow.connect() as db:
            row = db.execute('SELECT d.* FROM documents d JOIN projects p ON p.id=d.project WHERE d.id=? AND p.owner=?',
                             (document, owner)).fetchone()
            if row is None:
                raise AccessDenied('문서에 접근할 수 없습니다.')
            if hashlib.sha256(row['original']).hexdigest() != row['sha256']:
                raise ValueError('원본 무결성 검사에 실패했습니다.')
            return dict(row)

    def validators(self):
        def integrity(content):
            ref = json.loads(content)
            with self.workflow.connect() as db:
                row = db.execute('SELECT original,sha256 FROM documents WHERE id=?', (ref['document'],)).fetchone()
            actual = hashlib.sha256(row['original']).hexdigest() if row else None
            valid = row is not None and actual == row['sha256'] == ref['sha256']
            return (Status.PASS if valid else Status.FAIL, {'expected': ref['sha256'], 'actual': actual})
        return {('source', 'integrity'): ('original-sha256', '1', integrity), **self.processing.validators()}

    def status(self, owner, document):
        self.original(owner, document)
        state=self.workflow.snapshot(document)
        from urs.evaluation import require
        try:
            state['qualification']=require(self.workflow,os.environ.get('URS_OPENAI_MODEL',''))
        except Blocked as exc:
            state['qualification']={'blocked':str(exc)}
        return state

    def run(self, owner, document, stage):
        self.original(owner, document)
        with self._locks_guard:
            lock = self._run_locks.setdefault(document, threading.Lock())
        if not lock.acquire(blocking=False):
            raise Blocked('이 문서의 다른 처리가 진행 중입니다.')
        try:
            self.workflow.run(document, stage, self.validators())
        finally:
            lock.release()
        return self.status(owner, document)

    def artifact(self, owner, document, kind):
        self.original(owner,document)
        return self.processing.get(document,kind)

    def page_image(self, owner, document, page):
        self.original(owner,document)
        with self.workflow.connect() as db:
            row=db.execute('SELECT payload FROM page_assets WHERE document=? AND page=?',(document,page)).fetchone()
        if row is None:raise ValueError('페이지 미리보기가 없습니다.')
        extracted=self.processing.get(document,'extraction')
        metadata=next((p for p in extracted['pages'] if p['number']==page),None)
        if metadata is None or hashlib.sha256(row['payload']).hexdigest()!=metadata['preview_sha256']:
            raise ValueError('원본 페이지 미리보기 무결성 검사 실패')
        return row['payload']

    def review_extraction(self, owner, document, revision, pages, note, corrections, block_corrections=None, blank_pages=None):
        self.original(owner,document)
        if revision != self.processing._revision(document):raise Blocked('이전 리비전의 검토입니다.')
        extracted=self.processing.get(document,'extraction',revision)
        blank_pages = [] if blank_pages is None else blank_pages
        if not isinstance(blank_pages,list) or any(type(n) is not int for n in blank_pages) or len(blank_pages)!=len(set(blank_pages)):
            raise ValueError('빈 페이지 확인 목록이 올바르지 않습니다.')
        if any(n not in {p['number'] for p in extracted['pages']} for n in blank_pages):
            raise ValueError('존재하지 않는 빈 페이지입니다.')
        block_corrections = block_corrections or {}
        indexed = {block['id']: block for page in extracted['pages'] for block in page['blocks']}
        if not isinstance(block_corrections,dict) or any(key not in indexed or not isinstance(value,str) or not value.strip() or len(value)>100000 for key,value in block_corrections.items()):
            raise ValueError('수정할 원문 ID와 문자를 확인해 주세요.')
        for key,value in block_corrections.items():
            indexed[key]['text']=value
            indexed[key]['origin']='employee-corrected-extraction'
        expected=[page['number'] for page in extracted['pages']]
        if not isinstance(pages,list) or len(pages)!=len(set(pages)) or sorted(pages)!=expected:
            raise ValueError('모든 원본 페이지를 대조해야 합니다.')
        if not isinstance(note,str) or not note.strip() or not isinstance(corrections,dict):raise ValueError('검토 근거가 필요합니다.')
        if any(str(key) not in {str(n) for n in expected} for key in corrections):raise ValueError('잘못된 페이지입니다.')
        for page in extracted['pages']:
            text=corrections.get(str(page['number']))
            if text is not None:
                if not isinstance(text,str) or not text.strip() or len(text)>100000:raise ValueError('추가 원문을 확인해 주세요.')
                page['blocks'].append({'id':f'p{page["number"]}-manual{revision}', 'page':page['number'],
                                       'text':text,'bbox':[0,0,page['width'],page['height']], 'origin':'employee-transcription'})
            page['intentionally_blank'] = page['number'] in blank_pages
            if page['intentionally_blank'] and (not page.get('blank_candidate') or page['blocks']):
                raise ValueError('문자·이미지·도형이 있는 페이지를 빈 페이지로 처리할 수 없습니다.')
            if not page['blocks'] and not page['intentionally_blank']:
                raise ValueError('문자 없는 페이지는 원문을 보완하거나 실제 빈 페이지임을 명시 확인해야 합니다.')
        extracted['review']={'accepted':True,'reviewer':owner,'pages':pages,'note':note}
        return self._revise(owner,document,revision,{'extraction':extracted},'source_review')

    def _revise(self, owner, document, revision, changes, action):
        self.original(owner,document)
        with self.workflow.connect() as db:
            row=self.workflow._job(db,document)
            if row['revision']!=revision:raise Blocked('이전 리비전의 수정입니다.')
            ref=json.loads(row['content'])
        try:extracted=self.processing.get(document,'extraction',revision)
        except Blocked:extracted=None
        if 'translations' in changes:
            current=self.processing.get(document,'translation',revision)
            edits=changes['translations']
            if not isinstance(edits,dict) or not edits or any(key not in current or not isinstance(value,str) or not value.strip() or len(value)>20000 for key,value in edits.items()):
                raise ValueError('수정할 번역 ID와 내용을 확인해 주세요.')
            current.update(edits);ref['seed_translation']=current
            ref.pop('seed_analysis',None)
        elif 'analysis' in changes:
            ref['seed_translation']=self.processing.get(document,'translation',revision)
            ref['seed_analysis']=changes['analysis']
        else:
            ref.pop('seed_translation',None);ref.pop('seed_analysis',None)
        ref['revision']=revision+1
        new_revision=self.workflow.edit(document,revision,json.dumps(ref,ensure_ascii=False))
        if extracted is not None or 'extraction' in changes:
            self.processing.put(document,new_revision,'extraction',changes.get('extraction',extracted))
        with self.workflow.connect() as db:
            self.workflow._event(db,document,new_revision,action,{'actor':owner,'previous_revision':revision,'changes':changes})
        self.workflow.run(document,'source',self.validators())
        self.workflow.run(document,'extract',self.validators())
        return self.status(owner,document)

    def edit_translation(self, owner, document, revision, changes):
        return self._revise(owner,document,revision,{'translations':changes},'translation_edited')

    def edit_analysis(self, owner, document, revision, analysis):
        if not isinstance(analysis,dict):raise ValueError('분석 결과 형식이 올바르지 않습니다.')
        return self._revise(owner,document,revision,{'analysis':analysis},'analysis_edited')

    def chat(self, owner, document, revision, message):
        self.original(owner,document)
        if revision!=self.processing._revision(document):raise Blocked('이전 리비전입니다.')
        if not isinstance(message,str) or not message.strip() or len(message)>5000:raise ValueError('질문은 1~5000자여야 합니다.')
        from urs.processing import blocks_of
        extracted=self.processing.get(document,'extraction',revision)
        translated=self.processing.get(document,'translation',revision)
        try: analysis=self.processing.get(document,'analysis',revision)
        except Blocked: analysis=None
        result=self.processing.call(document,'dialogue',{'instruction':'Answer the employee question using ONLY cited source blocks. Return reply:string, changes:[{id,text}] for proposed Korean translation edits (or empty), source_ids:[ids], and optionally analysis_proposal (the complete revised analysis object using the same sections/conflicts/questions schema) for requested report edits. Explain uncertainties. Preserve source_ids and customer requirements. Never mix translation edits and report edits in one proposal. Do not claim the proposal is verified or approved.',
                                  'message':message,'source':blocks_of(extracted),'translation':translated,'analysis':analysis})
        changes=result.get('changes');refs=result.get('source_ids')
        if not isinstance(result.get('reply'),str) or not isinstance(changes,list) or not isinstance(refs,list) or any(x not in translated for x in refs):raise ValueError('대화 응답 형식이 올바르지 않습니다.')
        if any(not isinstance(change,dict) or change.get('id') not in translated or not isinstance(change.get('text'),str) for change in changes):raise ValueError('대화 수정안에 잘못된 원문 ID가 있습니다.')
        proposed=result.get('analysis_proposal')
        if proposed is not None and (analysis is None or not isinstance(proposed,dict) or changes or any(not isinstance(proposed.get(k),list) for k in ('sections','conflicts','questions'))):
            raise ValueError('보고서 수정안 형식이 올바르지 않습니다.')
        if revision!=self.processing._revision(document):raise Blocked('대화 중 문서가 수정되었습니다.')
        with self.workflow.connect() as db:
            self.workflow._event(db,document,revision,'ai_dialogue',{'actor':owner,'message':message,'response':result})
        return {**result,'revision':revision}

    def approve_document(self, owner, document, revision, note, reviewed_outputs):
        self.original(owner,document)
        if not isinstance(note,str) or not note.strip():raise ValueError('최종 검토 근거를 입력해 주세요.')
        expected={'translation.pdf','translation.docx','analysis.pdf','analysis.docx'}
        if not isinstance(reviewed_outputs,list) or set(reviewed_outputs)!=expected or len(reviewed_outputs)!=4:raise ValueError('번역본/분석 보고서 Word·PDF 모두 검토해야 합니다.')
        from urs.evaluation import require
        qualification=require(self.workflow,os.environ.get('URS_OPENAI_MODEL',''))
        self._check_verification_version(document)
        state=self.workflow.snapshot(document)
        if state['revision']!=revision or state['approved']:raise Blocked('현재 미승인 리비전만 승인할 수 있습니다.')
        # Validate reviewed bytes before preparing an approval appendix.
        outputs={kind:self.export(owner,document,kind) for kind in sorted(expected)}
        from datetime import datetime,timedelta,timezone
        from urs.reports import attach_approval
        source=self.original(owner,document)
        record={'document':document,'revision':revision,'reviewer':owner,'note':note,
                'source_sha256':source['sha256'],
                'approved_at_kst':datetime.now(timezone(timedelta(hours=9))).isoformat()}
        final=attach_approval(outputs,record)
        digests={kind:hashlib.sha256(data).hexdigest() for kind,data in final.items()}
        # Commit approval and all four verified final files together. Concurrent
        # edits or revalidation invalidate the prepared snapshot and save nothing.
        with self.workflow.connect() as db:
            current=self.workflow._snapshot(db,document)
            if current['revision']!=revision or current['results']!=state['results'] or current['approved']:
                raise Blocked('승인본 생성 중 문서 또는 검증 상태가 변경되었습니다.')
            self.workflow._entry(db,document,revision,'approval')
            for kind,data in outputs.items():
                row=db.execute('SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind=?',(document,revision,kind)).fetchone()
                if row is None or bytes(row['payload'])!=data:raise Blocked('승인본 생성 중 검토한 출력 파일이 변경되었습니다.')
            for kind,data in final.items():db.execute('INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?)',(document,revision,kind,data))
            self.workflow._record(db,document,'approval',revision,'employee-review',Status.PASS,
                {**record,'qualification':qualification,'outputs':digests},'human','2')
            if not all(self.workflow._passed(db,document,revision,s) for s in self.workflow._definitions(db)):
                raise Blocked('모든 필수 검사 완료 후 승인할 수 있습니다.')
            db.execute('INSERT INTO approvals VALUES(?,?,?)',(document,revision,owner))
            self.workflow._event(db,document,revision,'approved',{**record,'outputs':digests})
        return self.status(owner,document)

    def export(self, owner, document, kind, final=False):
        self.original(owner,document)
        if kind not in {'translation.pdf','translation.docx','analysis.pdf','analysis.docx'}:raise ValueError('지원하지 않는 출력 형식입니다.')
        state=self.workflow.snapshot(document)
        if not next(s['passed'] for s in state['stages'] if s['id']=='report') or (final and not state['approved']):
            raise Blocked('현재 리비전의 보고서 검증/직원 승인이 완료되지 않았습니다.')
        if final:
            from urs.evaluation import require
            require(self.workflow,os.environ.get('URS_OPENAI_MODEL',''))
            self._check_verification_version(document)
        data=self.processing.get(document,kind,state['revision'])
        result=next(r for r in state['results'] if r['stage']=='report' and r['check_id']=='complete')
        if hashlib.sha256(data).hexdigest()!=json.loads(result['evidence'])['outputs'][kind]:raise Blocked('출력 파일의 검증 해시가 일치하지 않습니다.')
        if final:
            approval=next(r for r in state['results'] if r['stage']=='approval' and r['check_id']=='employee-review')
            final_kind='final-'+kind
            expected=json.loads(approval['evidence']).get('outputs',{}).get(final_kind)
            if not expected:raise Blocked('승인 기록이 포함된 최종 파일을 다시 생성해야 합니다.')
            data=self.processing.get(document,final_kind,state['revision'])
            if hashlib.sha256(data).hexdigest()!=expected:raise Blocked('승인본 파일의 검증 해시가 일치하지 않습니다.')
        return data


    def _check_verification_version(self, document):
        from urs.evaluation import fingerprint
        state=self.workflow.snapshot(document)
        result=next((r for r in state['results'] if r['stage']=='verify' and r['status']=='PASS'),None)
        if result is None:raise Blocked('현재 리비전의 의미 검증을 완료해야 합니다.')
        evidence=json.loads(result['evidence'])
        if evidence.get('pipeline_fingerprint')!=fingerprint() or evidence.get('model')!=os.environ.get('URS_OPENAI_MODEL',''):
            raise Blocked('코드 또는 모델 변경 후 의미 검증을 다시 실행해야 합니다.')

    def verification_record(self, owner, document):
        from datetime import datetime,timezone,timedelta
        from urs.audit import envelope
        with self.workflow.connect() as db:
            row=db.execute('SELECT d.* FROM documents d JOIN projects p ON p.id=d.project WHERE d.id=? AND p.owner=?',(document,owner)).fetchone()
            if row is None:raise AccessDenied('문서에 접근할 수 없습니다.')
            if hashlib.sha256(row['original']).hexdigest()!=row['sha256']:raise ValueError('원본 무결성 검사에 실패했습니다.')
            snapshot=self.workflow._snapshot(db,document)
            results=[dict(r) for r in db.execute('SELECT * FROM results WHERE job=? ORDER BY revision,stage,check_id',(document,))]
            verification_history=[{'revision':r['revision'],'verification':json.loads(r['payload'])} for r in db.execute("SELECT revision,payload FROM artifacts WHERE document=? AND kind='verification' ORDER BY revision",(document,))]
            artifacts=[{'revision':r['revision'],'kind':r['kind'],'sha256':hashlib.sha256(r['payload']).hexdigest()} for r in db.execute('SELECT revision,kind,payload FROM artifacts WHERE document=? ORDER BY revision,kind',(document,))]
            bundle=envelope({'schema_version':1,'document_id':document,
                'original':{'name':row['name'],'sha256':row['sha256'],'pages':row['pages']},
                'snapshot':snapshot,'all_results':results,'verification_history':verification_history,'artifact_hashes':artifacts,
                'scope':'Document evidence only. No process environment, application authentication credential tables, raw original binary or app payment configuration is included. No inferred accuracy score.'})
            bundle['exported_at_kst']=datetime.now(timezone(timedelta(hours=9))).isoformat()
            return bundle

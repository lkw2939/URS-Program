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
from urs.ai_settings import SettingsError

MAX_PDF = 20 * 1024 * 1024
PIPELINE = [
    {'id':'source','checks':[{'id':'integrity','kind':'automatic'}]},
    {'id':'report','checks':[{'id':'html-v1','kind':'automatic'}]},
    *[{'id':s,'checks':[{'id':'pdf-html-v1','kind':'automatic'}]} for s in ('verify','analyze')],
    {'id':'approval','checks':[{'id':'employee-review-v2','kind':'human'}]},
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
        # Keep every historical definition/result/artifact intact. Active v2 checks
        # have distinct IDs, so old successful report checks cannot qualify v2.
        with self.workflow.connect() as db:
            empty=not db.execute('SELECT 1 FROM definitions').fetchone()
        if empty:self.workflow.define(PIPELINE)
        self.workflow.active_stages=PIPELINE
        with self.workflow.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS qualifications(fingerprint TEXT,model TEXT,total INTEGER,correct INTEGER,critical INTEGER,reviewer TEXT,evidence TEXT,digest TEXT);
            CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, salt BLOB, digest BLOB);
            CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, name TEXT, csrf TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS attempts(name TEXT PRIMARY KEY, failures INTEGER, since REAL);
            CREATE TABLE IF NOT EXISTS ai_settings(owner TEXT,version INTEGER,payload TEXT,PRIMARY KEY(owner,version));
            CREATE TABLE IF NOT EXISTS report_settings(owner TEXT,version INTEGER,prompt TEXT,PRIMARY KEY(owner,version));
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
            from urs.ai_settings import effective
            state['qualification']=require(self.workflow,effective(self.workflow,document=document)['model'])
        except (Blocked,SettingsError) as exc:
            state['qualification']={'blocked':str(exc)}
        return state

    def run(self, owner, document, stage):
        self.original(owner, document)
        if stage not in ('source','report','verify','analyze'):raise ValueError('지원하지 않는 단계입니다.')
        with self._locks_guard:
            lock = self._run_locks.setdefault(document, threading.Lock())
        if not lock.acquire(blocking=False):
            raise Blocked('이 문서의 다른 처리가 진행 중입니다.')
        try:
            if stage=='report':
                if not self.report_settings(owner)['prompt'].strip():raise Blocked('웹 설정에서 보고서 프롬프트를 저장해 주세요.')
                with self.workflow.connect() as db:
                    job=self.workflow._job(db,document)
                    has_artifacts=db.execute('SELECT 1 FROM artifacts WHERE document=? AND revision=?',(document,job['revision'])).fetchone()
                    if has_artifacts:
                        ref=json.loads(job['content']);ref.pop('seed_translation',None);ref.pop('seed_analysis',None)
                        ref['revision']=job['revision']+1
                        # User explicitly requested a new report. Preserve old artifacts,
                        # results and approval rows; never regenerate on application load.
                        db.execute('UPDATE jobs SET revision=?,content=? WHERE id=?',(ref['revision'],json.dumps(ref),document))
                        self.workflow._event(db,document,ref['revision'],'report_generation_requested',{'actor':owner,'previous_revision':job['revision']})
                if has_artifacts:self.workflow.run(document,'source',self.validators())
            self.workflow.run(document, stage, self.validators())
        finally:
            lock.release()
        return self.status(owner, document)

    def artifact(self, owner, document, kind):
        self.original(owner,document)
        return self.processing.get(document,kind)

    def ai_settings(self, owner):
        from urs.ai_settings import effective
        try:return effective(self.workflow,owner=owner)
        except SettingsError as exc:
            return {'model':os.environ.get('URS_OPENAI_MODEL','').strip(),'effort':None,'max_output_tokens':5000,'version':0,'source':'invalid','configuration_error':str(exc)}

    def save_ai_settings(self, owner, value):
        from urs.ai_settings import validate
        config=validate(value)
        with self.workflow.connect() as db:
            if not db.execute('SELECT 1 FROM users WHERE name=?',(owner,)).fetchone():raise AccessDenied('등록된 직원이 아닙니다.')
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM ai_settings WHERE owner=?',(owner,)).fetchone()[0]
            db.execute('INSERT INTO ai_settings VALUES(?,?,?)',(owner,version,json.dumps(config)))
        return {**config,'version':version,'source':'web'}

    def report_settings(self, owner):
        with self.workflow.connect() as db:
            row=db.execute('SELECT version,prompt FROM report_settings WHERE owner=? ORDER BY version DESC LIMIT 1',(owner,)).fetchone()
        return dict(row) if row else {'version':0,'prompt':''}

    def save_report_settings(self, owner, prompt):
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt.encode())>180000:
            raise ValueError('보고서 프롬프트를 입력해 주세요. 최대 180KB입니다.')
        with self.workflow.connect() as db:
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM report_settings WHERE owner=?',(owner,)).fetchone()[0]
            db.execute('INSERT INTO report_settings VALUES(?,?,?)',(owner,version,prompt))
        return {'version':version,'prompt':prompt}

    def report_availability(self, owner, document):
        self.original(owner,document)
        from urs.saved_reports import inspect_document
        with self.workflow.connect() as db:
            current=self.workflow._job(db,document)['revision']
            return inspect_document(db,document,current)

    def report_html(self, owner, document, raw=False, revision=None):
        self.original(owner,document)
        if revision is not None and (type(revision) is not int or revision<1):raise ValueError('리비전 오류')
        if raw:return self.processing.get(document,'report.raw.html',revision)
        from urs.saved_reports import read_final
        with self.workflow.connect() as db:
            current=self.workflow._job(db,document)['revision']
            if revision is not None and revision>current:raise Blocked('존재하지 않는 리비전입니다.')
            return read_final(db,document,revision or current)[0]

    def approve_document(self, owner, document, revision, note, reviewed_outputs):
        self.original(owner,document)
        if not isinstance(note,str) or not note.strip() or reviewed_outputs!=['report.html']:
            raise ValueError('최종 HTML과 검토 근거를 확인해 주세요.')
        from urs.evaluation import require
        from urs.ai_settings import effective
        require(self.workflow,effective(self.workflow,document=document)['model'])
        self._check_verification_version(document)
        self.processing.checked_html(document,revision)
        bindings=self.processing.get(document,'image-bindings',revision)
        if bindings['unresolved']:raise Blocked('미연결 그림 자리를 검토해야 합니다.')
        self.workflow.review(document,'approval','employee-review-v2',revision,owner,note)
        self.workflow.approve(document,revision,owner)
        return self.status(owner,document)

    def export(self, owner, document, kind, final=False):
        # Existing Word/PDF artifacts remain downloadable, without running their
        # retired builders or changing historical bytes.
        self.original(owner,document)
        if kind not in {'translation.pdf','translation.docx','analysis.pdf','analysis.docx'}:
            raise ValueError('지원하지 않는 출력 형식입니다.')
        return self.processing.get(document,('final-' if final else '')+kind)


    def _check_verification_version(self, document):
        from urs.evaluation import fingerprint
        state=self.workflow.snapshot(document)
        result=next((r for r in state['results'] if r['stage']=='verify' and r['status']=='PASS'),None)
        if result is None:raise Blocked('현재 리비전의 의미 검증을 완료해야 합니다.')
        evidence=json.loads(result['evidence'])
        from urs.ai_settings import effective,signature
        config=effective(self.workflow,document=document)
        if evidence.get('pipeline_fingerprint')!=fingerprint() or evidence.get('ai_settings_signature')!=signature(config):
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

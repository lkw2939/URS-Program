"""Original-PDF report authoring, image URL binding, and separate reviews."""
import hashlib
import json
import os
from urs.ai import OpenAI, requested_effort
from urs.images import crop_images, bind_images
from urs.gates import Status
from urs.workflow import Blocked
from urs.evaluation import fingerprint


class Processing:
    def __init__(self, workspace, provider=None):
        self.workspace,self.workflow,self.provider=workspace,workspace.workflow,provider
        with self.workflow.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS artifacts(document TEXT,revision INTEGER,kind TEXT,payload BLOB,PRIMARY KEY(document,revision,kind));
            CREATE TABLE IF NOT EXISTS page_assets(document TEXT,page INTEGER,payload BLOB,PRIMARY KEY(document,page));
            CREATE TABLE IF NOT EXISTS ai_usage(id INTEGER PRIMARY KEY,document TEXT,task TEXT,model TEXT,reserved REAL,state TEXT,usage TEXT);
            ''')

    def _revision(self, document):
        with self.workflow.connect() as db:return self.workflow._job(db,document)['revision']

    def get(self, document, kind, revision=None):
        revision=revision or self._revision(document)
        with self.workflow.connect() as db:
            row=db.execute('SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind=?',(document,revision,kind)).fetchone()
        if row is None:raise Blocked('필요한 결과물이 아직 생성되지 않았습니다.')
        return bytes(row['payload']) if kind.endswith(('.pdf','.docx','.html')) else json.loads(row['payload'])

    def put(self, document, revision, kind, value):
        payload=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        with self.workflow.connect() as db:
            if self.workflow._job(db,document)['revision']!=revision:raise Blocked('문서가 변경되었습니다.')
            db.execute('INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?)',(document,revision,kind,payload))

    def _input(self, content):
        ref=json.loads(content);document=ref['document'];revision=ref.get('revision',1)
        if revision!=self._revision(document):raise Blocked('문서가 변경되었습니다.')
        with self.workflow.connect() as db:row=db.execute('SELECT original,name,sha256 FROM documents WHERE id=?',(document,)).fetchone()
        if not row or hashlib.sha256(row['original']).hexdigest()!=row['sha256']:raise Blocked('원본 무결성 검사 실패')
        return document,revision,bytes(row['original']),row['name']

    def provider_for(self, document):
        return self.provider or OpenAI(self.workflow,document)

    def report(self, content):
        document,revision,pdf,name=self._input(content)
        # Read no legacy text/translation artifact. Prompt content is not stripped.
        with self.workflow.connect() as db:
            owner=db.execute('SELECT p.owner FROM documents d JOIN projects p ON p.id=d.project WHERE d.id=?',(document,)).fetchone()[0]
        settings=self.workspace.report_settings(owner)
        prompt=settings['prompt']
        if not prompt.strip():raise Blocked('웹 설정에서 보고서 프롬프트를 먼저 저장해 주세요.')
        assets=crop_images(pdf)
        inventory=[{k:a[k] for k in ('uri','page','index','bbox')} for a in assets]
        guide='Image address mapping only: use <img src="urs-image:PAGE:INDEX"> for a source picture/diagram at the corresponding original PDF page and region. Available image addresses and bounding boxes (PDF points from top-left):\n'+json.dumps(inventory,ensure_ascii=False)
        raw=self.provider_for(document).report_html(pdf,name,prompt,guide)
        if not isinstance(raw,str) or not raw:raise ValueError('HTML 응답이 없습니다.')
        final,comparison=bind_images(raw,assets)
        data={'report.raw.html':raw.encode(),'report.html':final.encode(),
              'report-images':assets,'image-bindings':comparison,
              'report-metadata':{'prompt':prompt,'settings_version':settings['version'],
                  'source_sha256':hashlib.sha256(pdf).hexdigest(),'model':os.environ.get('URS_OPENAI_MODEL',''),'reasoning_effort':requested_effort(),
                  'image_guide':guide,'raw_sha256':comparison['raw_sha256'],'final_sha256':comparison['final_sha256']}}
        # Append-only report artifacts. Retries/regeneration must use a new revision.
        with self.workflow.connect() as db:
            if self.workflow._job(db,document)['revision']!=revision:raise Blocked('보고서 생성 중 문서가 변경되었습니다.')
            for kind,value in data.items():
                payload=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
                db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(document,revision,kind,payload))
        return Status.PASS, {'raw_sha256':comparison['raw_sha256'],'final_sha256':comparison['final_sha256'],
            'only_image_addresses_changed':True,'unresolved':comparison['unresolved'],
            'outputs':{k:hashlib.sha256(v if isinstance(v,bytes) else json.dumps(v,ensure_ascii=False).encode()).hexdigest() for k,v in data.items()},
            'reason':f"HTML 저장 완료 · 이미지 주소 {len(comparison['replacements'])}개 연결 · 미연결 {len(comparison['unresolved'])}개"}

    def checked_html(self, document, revision=None):
        raw=self.get(document,'report.raw.html',revision)
        final=self.get(document,'report.html',revision)
        assets=self.get(document,'report-images',revision)
        expected,comparison=bind_images(raw.decode(),assets)
        metadata=self.get(document,'report-metadata',revision)
        if final!=expected.encode() or metadata['raw_sha256']!=comparison['raw_sha256'] or metadata['final_sha256']!=comparison['final_sha256']:
            raise Blocked('HTML 원본/최종본 무결성 검사 실패')
        return final

    def _review(self, content, task, kind):
        document,revision,pdf,name=self._input(content)
        self.checked_html(document,revision)
        raw=self.get(document,'report.raw.html',revision).decode()
        result=self.provider_for(document).review_pdf(task,pdf,name,raw)
        if not isinstance(result,dict) or result.get('status') not in ('PASS','FAIL','NEEDS_REVIEW') or not isinstance(result.get('issues'),list):
            raise ValueError('검토 응답 형식이 올바르지 않습니다.')
        if result['status']=='PASS' and result['issues']:raise ValueError('검토 상태와 오류 목록이 모순됩니다.')
        if kind=='analysis' and any(not isinstance(result.get(k),list) for k in ('sections','conflicts','questions')):
            raise ValueError('기술 분석 형식이 올바르지 않습니다.')
        self.put(document,revision,kind,result)
        bindings=self.get(document,'image-bindings',revision)
        status=Status.NEEDS_REVIEW if bindings['unresolved'] else Status(result['status'])
        return status, {'issues':result['issues'],'unresolved':bindings['unresolved'],'artifact':kind,
            'model':os.environ.get('URS_OPENAI_MODEL',''),'reasoning_effort':requested_effort(),'pipeline_fingerprint':fingerprint(),
            'accuracy_99_measured':False,'reason':'원본 PDF와 HTML의 별도 검토. HTML은 변경하지 않음.'}

    def verify(self, content):return self._review(content,'independent_verify','verification')
    def analyze(self, content):return self._review(content,'technical_analysis','analysis')

    def validators(self):
        return {(stage,check):('pdf-html-'+stage,'1',function) for stage,check,function in
            [('report','html-v1',self.report),('verify','pdf-html-v1',self.verify),('analyze','pdf-html-v1',self.analyze)]}

"""Original-PDF report authoring, image URL binding, and separate reviews."""
import hashlib
import json
import os
from urs.ai import OpenAI,AIError
from urs.ai_settings import effective,signature
from urs.images import crop_images, bind_images
from urs.gates import Status
from urs.workflow import Blocked
from urs.evaluation import fingerprint


class Processing:
    def __init__(self, workspace, provider=None):
        self.workspace,self.workflow,self.provider=workspace,workspace.workflow,provider
        self.authorized_quotes={}
        with self.workflow.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS report_timeouts(owner TEXT,version INTEGER,seconds INTEGER,PRIMARY KEY(owner,version));
            CREATE TABLE IF NOT EXISTS report_diagnostics(call_id INTEGER PRIMARY KEY,document TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS review_attempts(id INTEGER PRIMARY KEY,document TEXT,revision INTEGER,stage TEXT,state TEXT,status TEXT,payload TEXT,evidence TEXT,created TEXT,digest TEXT);
            CREATE TABLE IF NOT EXISTS review_targets(id TEXT PRIMARY KEY,document TEXT,parent_revision INTEGER,name TEXT,payload BLOB,sha256 TEXT,source_sha256 TEXT,owner TEXT,created TEXT);
            CREATE TRIGGER IF NOT EXISTS immutable_review_targets_update BEFORE UPDATE ON review_targets BEGIN SELECT RAISE(ABORT,'immutable review target'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_review_targets_delete BEFORE DELETE ON review_targets BEGIN SELECT RAISE(ABORT,'immutable review target'); END;
            CREATE TABLE IF NOT EXISTS target_reviews(id INTEGER PRIMARY KEY,target TEXT,stage TEXT,state TEXT,status TEXT,payload TEXT,evidence TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS artifacts(document TEXT,revision INTEGER,kind TEXT,payload BLOB,PRIMARY KEY(document,revision,kind));
            CREATE TABLE IF NOT EXISTS page_assets(document TEXT,page INTEGER,payload BLOB,PRIMARY KEY(document,page));
            CREATE TABLE IF NOT EXISTS ai_usage(id INTEGER PRIMARY KEY,document TEXT,task TEXT,model TEXT,reserved REAL,state TEXT,usage TEXT);
            ''')
            from urs.costing import schema
            schema(db)
            from urs.corrections import schema as correction_schema
            correction_schema(db)

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

    def provider_for(self, document, config=None):
        return self.provider or OpenAI(self.workflow,document,settings=config,authorized_quotes=self.authorized_quotes)

    def report(self, content):
        document,revision,pdf,name=self._input(content)
        # Read no legacy text/translation artifact. Prompt content is not stripped.
        with self.workflow.connect() as db:
            owner=db.execute('SELECT p.owner FROM documents d JOIN projects p ON p.id=d.project WHERE d.id=?',(document,)).fetchone()[0]
        config=effective(self.workflow,document=document)
        settings=self.workspace.report_settings(owner)
        prompt=settings['prompt']
        if not prompt.strip():raise Blocked('웹 설정에서 보고서 프롬프트를 먼저 저장해 주세요.')
        assets=crop_images(pdf)
        from urs.costing import image_guide
        guide=image_guide(assets)
        raw=self.provider_for(document,config).report_html(pdf,name,prompt,guide)
        if not isinstance(raw,str) or not raw:raise ValueError('HTML 응답이 없습니다.')
        try:final,comparison=bind_images(raw,assets)
        except Exception as error:
            from urs.report_transport import diagnostics
            records=diagnostics(self.workflow,document)
            exc=AIError('OpenAI 응답 후 이미지 연결 처리 실패.')
            if records and records[-1]['revision']==revision:
                info={**records[-1],'outcome':'html_processing_error','processing_phase':'image_binding','error_type':type(error).__name__}
                with self.workflow.connect() as db:db.execute('UPDATE report_diagnostics SET payload=? WHERE call_id=?',(json.dumps(info),info['call_id']))
                exc.diagnostics=info
            raise exc from None
        from urs.layout_audit import inspect
        from urs.report_contract import VERSION,check
        from pypdf import PdfReader
        import io
        layout=inspect(final,len(PdfReader(io.BytesIO(pdf)).pages))
        contract_issues=check(raw)
        if contract_issues:
            layout['status']='NEEDS_REVIEW';layout.setdefault('issues',[]).extend(contract_issues)
        layout['contract_issues']=contract_issues
        layout['source_image_candidates']=len(assets);layout['bound_image_slots']=len(comparison['replacements'])
        if assets and not comparison['replacements']:
            layout['status']='NEEDS_REVIEW';layout.setdefault('issues',[]).append('원본 그림 후보가 있으나 최종 HTML에 연결된 그림이 없습니다.')
        data={'layout-audit':layout,'report.raw.html':raw.encode(),'report.html':final.encode(),
              'report-images':assets,'image-bindings':comparison,
              'report-metadata':{'prompt':prompt,'settings_version':settings['version'],
                  'source_sha256':hashlib.sha256(pdf).hexdigest(),'model':config['model'],'reasoning_effort':config['effort'],'max_output_tokens':config['max_output_tokens'],'ai_settings_version':config['version'],'ai_settings_signature':signature(config),
                  'api_timeout_seconds':None,'api_wait_policy':'unlimited','layout_contract':VERSION,'layout_status':layout['status'],'image_guide':guide,'raw_sha256':comparison['raw_sha256'],'final_sha256':comparison['final_sha256']}}
        # Append-only report artifacts. Retries/regeneration must use a new revision.
        with self.workflow.connect() as db:
            if self.workflow._job(db,document)['revision']!=revision:raise Blocked('보고서 생성 중 문서가 변경되었습니다.')
            for kind,value in data.items():
                payload=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
                db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(document,revision,kind,payload))
        complete=layout['status']=='PASS'
        return (Status.PASS if complete else Status.UNVERIFIED if layout['status']=='UNVERIFIED' else Status.NEEDS_REVIEW), {'layout_status':layout['status'],'layout_issues':layout.get('issues',[]),'visible_image_count':layout.get('visible_image_count'),'raw_sha256':comparison['raw_sha256'],'final_sha256':comparison['final_sha256'],
            'only_image_addresses_changed':True,'unresolved':comparison['unresolved'],
            'outputs':{k:hashlib.sha256(v if isinstance(v,bytes) else json.dumps(v,ensure_ascii=False).encode()).hexdigest() for k,v in data.items()},
            'reason':('최종 HTML 저장·사진 표시 확인 완료' if complete else 'HTML은 보존했으나 사진 표시/배치 확인이 필요합니다.')+f" · 이미지 주소 {len(comparison['replacements'])}개 연결 · 미연결 {len(comparison['unresolved'])}개"+((' · '+' · '.join(layout.get('issues',[]))) if not complete else '')}

    def checked_html(self, document, revision=None):
        revision=revision or self._revision(document)
        with self.workflow.connect() as db:
            corrected=db.execute("SELECT 1 FROM artifacts WHERE document=? AND revision=? AND kind='correction-patch'",(document,revision)).fetchone()
            if corrected:
                from urs.saved_reports import read_final
                return read_final(db,document,revision)[0]
        raw=self.get(document,'report.raw.html',revision)
        final=self.get(document,'report.html',revision)
        assets=self.get(document,'report-images',revision)
        expected,comparison=bind_images(raw.decode(),assets)
        metadata=self.get(document,'report-metadata',revision)
        if final!=expected.encode() or metadata['raw_sha256']!=comparison['raw_sha256'] or metadata['final_sha256']!=comparison['final_sha256']:
            raise Blocked('HTML 원본/최종본 무결성 검사 실패')
        return final

    def _review(self, content, task, kind, persist=True):
        document,revision,pdf,name=self._input(content)
        config=effective(self.workflow,document=document)
        self.checked_html(document,revision)
        input_kind='report.html' if self.get(document,'report-metadata',revision).get('generation_kind')=='employee_selected_correction' else 'report.raw.html'
        raw=self.get(document,input_kind,revision).decode()
        result=self.provider_for(document,config).review_pdf(task,pdf,name,raw)
        if not isinstance(result,dict) or result.get('status') not in ('PASS','FAIL','NEEDS_REVIEW') or not isinstance(result.get('issues'),list):
            raise ValueError('검토 응답 형식이 올바르지 않습니다.')
        if result['status']=='PASS' and result['issues']:raise ValueError('검토 상태와 오류 목록이 모순됩니다.')
        if kind=='analysis' and any(not isinstance(result.get(k),list) for k in ('sections','conflicts','questions')):
            raise ValueError('기술 분석 형식이 올바르지 않습니다.')
        if persist:self.put(document,revision,kind,result)
        bindings=self.get(document,'image-bindings',revision)
        status=Status.NEEDS_REVIEW if bindings['unresolved'] else Status(result['status'])
        return status, {**({'review_result':result} if not persist else {}),'input_html_kind':input_kind,'input_html_sha256':hashlib.sha256(raw.encode()).hexdigest(),'input_pdf_sha256':hashlib.sha256(pdf).hexdigest(),'issues':result['issues'],'unresolved':bindings['unresolved'],'artifact':kind,
            'model':config['model'],'reasoning_effort':config['effort'],'max_output_tokens':config['max_output_tokens'],'ai_settings_version':config['version'],'ai_settings_signature':signature(config),'pipeline_fingerprint':fingerprint(),
            'api_timeout_seconds':None,'api_wait_policy':'unlimited','accuracy_99_measured':False,'reason':'원본 PDF와 HTML의 별도 검토. HTML은 변경하지 않음.'}

    def verify(self, content):return self._review(content,'independent_verify','verification')
    def analyze(self, content):return self._review(content,'technical_analysis','analysis')

    def validators(self):
        return {(stage,check):('pdf-html-'+stage,'1',function) for stage,check,function in
            [('report','html-v1',self.report),('verify','pdf-html-v1',self.verify),('analyze','pdf-html-v1',self.analyze)]}

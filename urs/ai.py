"""OpenAI Responses adapter. No calls without explicit model/pricing/budget settings."""
import base64
import json
import math
import os
import urllib.error
import urllib.request

from urs.ai_settings import EFFORTS, SettingsError, normalize_effort, effective, validate


class AIBlocked(RuntimeError):
    pass


class AIError(RuntimeError):
    pass


REASONING_EFFORTS=EFFORTS

def requested_effort():
    try:return normalize_effort(os.environ.get('URS_OPENAI_REASONING_EFFORT',''))
    except SettingsError as exc:raise AIBlocked(str(exc)) from None


class OpenAI:
    def __init__(self, workflow, document, settings=None):
        self.workflow, self.document = workflow, document
        self.settings=dict(settings) if settings is not None else None

    def report_html(self, pdf, filename, prompt, image_guide):
        """Report authoring: the saved prompt is the sole authoring instruction."""
        return self._pdf_request('report_html', pdf, filename,
            [{'type':'input_text','text':prompt}, {'type':'input_text','text':image_guide}], False)

    def review_pdf(self, task, pdf, filename, html):
        instructions = {
            'independent_verify': 'Independently compare the original PDF with the supplied HTML. Check full technical meaning, omissions, additions, negation, conditions, obligations, quantities, units, codes and table associations. Return JSON {status:PASS|FAIL|NEEDS_REVIEW,issues:[{page,reason}]}. Do not edit or rewrite the HTML.',
            'technical_analysis': 'Analyze equipment, processes, specification conflicts and customer questions using the original PDF and supplied report. Cite original page numbers. Return JSON {status:PASS|FAIL|NEEDS_REVIEW,sections:[],conflicts:[],questions:[],issues:[]}. Do not edit or rewrite the HTML.'}
        return self._pdf_request(task,pdf,filename,[{'type':'input_text','text':instructions[task]},
            {'type':'input_text','text':html}],True)

    def _pdf_request(self, task, pdf, filename, texts, json_response):
        key=os.environ.get('URS_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
        try:
            config=validate({k:self.settings[k] for k in ('model','effort','max_output_tokens')}) if self.settings is not None else effective(self.workflow,document=self.document)
        except SettingsError as exc:raise AIBlocked(str(exc)) from None
        report_timeout=None
        if task=='report_html':
            from urs.report_transport import settings
            try:report_timeout=settings(self.workflow,document=self.document)['timeout_seconds']
            except (ValueError,TypeError):raise AIBlocked('보고서 API 대기시간 설정을 확인해 주세요.') from None
        model=config['model'];effort=config['effort'];output_limit=config['max_output_tokens']
        try:
            budget=float(os.environ.get('URS_AI_BUDGET_USD','0'))
            ir=float(os.environ.get('URS_AI_INPUT_USD_PER_MILLION','0'))
            outr=float(os.environ.get('URS_AI_OUTPUT_USD_PER_MILLION','0'))
        except ValueError:
            raise AIBlocked('AI 비용 설정을 확인해 주세요.') from None
        if not key or not model or not all(math.isfinite(n) and n>0 for n in (budget,ir,outr)):
            raise AIBlocked('회사 승인 API 키·모델·문서별 비용 한도·입출력 단가 설정이 필요합니다.')
        # Reserve against this call's immutable settings snapshot, including its output limit.
        reserve=((len(pdf)+sum(len(t['text'].encode()) for t in texts))*ir+output_limit*outr)/1_000_000
        with self.workflow.connect() as db:
            total,calls=db.execute('SELECT COALESCE(SUM(reserved),0),COUNT(*) FROM ai_usage WHERE document=?',(self.document,)).fetchone()
            if calls>=120 or total+reserve>budget:raise AIBlocked('문서의 AI 요청/비용 상한에 도달했습니다.')
            call_id=db.execute('INSERT INTO ai_usage(document,task,model,reserved,state) VALUES(?,?,?,?,?)',
                (self.document,task,model,reserve,'reserved')).lastrowid
        content=[{'type':'input_file','filename':filename,'file_data':'data:application/pdf;base64,'+base64.b64encode(pdf).decode()},*texts]
        payload={'model':model,'input':[{'role':'user','content':content}],'max_output_tokens':output_limit,'store':False}
        if effort is not None:payload['reasoning']={'effort':effort}
        if json_response:payload['text']={'format':{'type':'json_object'}}
        req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        if task=='report_html':
            from urs.report_transport import request
            return request(self,req,call_id,output_limit,report_timeout)
        try:
            with urllib.request.urlopen(req,timeout=90) as response:result=json.load(response)
            if result.get('status')!='completed':
                if (result.get('incomplete_details') or {}).get('reason')=='max_output_tokens':
                    raise AIError(f'출력 토큰 한도({output_limit:,})에 도달했습니다. 웹의 AI 호출 설정에서 출력 한도를 조정한 뒤 다시 실행하세요.')
                raise AIError('모델 응답이 완료되지 않았습니다.')
            raw=''.join(c['text'] for item in result.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
            value=json.loads(raw) if json_response else raw
            if json_response and not isinstance(value,dict):raise ValueError('JSON object required')
            if not json_response and (not raw or not any(t in raw.lower() for t in ('<html','<!doctype','<body'))):
                raise ValueError('Expected HTML; response is never unwrapped or rewritten')
        except AIError:
            with self.workflow.connect() as db:db.execute('UPDATE ai_usage SET state=?,usage=? WHERE id=?',('failed',json.dumps(result.get('usage',{})),call_id))
            raise
        except Exception:
            with self.workflow.connect() as db:db.execute('UPDATE ai_usage SET state=? WHERE id=?',('failed',call_id))
            raise AIError('OpenAI 호출 실패: 네트워크·모델 접근·응답 형식을 확인해 주세요.') from None
        with self.workflow.connect() as db:
            db.execute('UPDATE ai_usage SET state=?,usage=? WHERE id=?',('completed',json.dumps(result.get('usage',{})),call_id))
        return value

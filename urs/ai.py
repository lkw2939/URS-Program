"""OpenAI Responses adapter. No calls without explicit model/pricing/budget settings."""
import base64
import json
import math
import os
import time
import socket
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
    def __init__(self, workflow, document, settings=None, authorized_quotes=None):
        self.request_manifest=None
        self.report_execution_call_ids=[]
        self.workflow, self.document = workflow, document
        self.authorized_quotes=authorized_quotes if authorized_quotes is not None else {}
        self.settings=dict(settings) if settings is not None else None

    def report_html(self, pdf, filename, prompt, image_guide):
        """Report authoring: saved prompt plus the user-authorized A4 output contract."""
        self.report_execution_call_ids=[]
        return self._pdf_request('report_html', pdf, filename,
            [{'type':'input_text','text':prompt}, {'type':'input_text','text':image_guide}, {'type':'input_text','text':__import__('urs.report_contract',fromlist=['TEXT']).TEXT}], False)

    def refine_report_html(self,pdf,filename,prompt,image_guide,raw,audit,screenshots):
        from urs.layout_refinement import INSTRUCTION
        if audit.get('css_only'):
            from urs.css_only import INSTRUCTION
        parts=[{'type':'input_text','text':prompt},{'type':'input_text','text':image_guide},
               {'type':'input_text','text':__import__('urs.report_contract',fromlist=['TEXT']).TEXT},
               {'type':'input_text','text':INSTRUCTION},{'type':'input_text','text':raw},
               {'type':'input_text','text':'실제 사진 삽입 후 브라우저 검사: '+json.dumps(audit,ensure_ascii=False)}]
        if audit.get('css_only'):
            parts=[{'type':'input_text','text':INSTRUCTION},{'type':'input_text','text':image_guide},{'type':'input_text','text':raw},{'type':'input_text','text':'현재 화면 측정 (글자 크기·축소 측정은 참고이며 배치 강제 지시가 아닙니다): '+json.dumps(audit,ensure_ascii=False)}]
        for image in screenshots:
            parts.extend([{'type':'input_text','text':'실제 렌더링 · 원문 '+image['page']+'쪽'},
                          {'type':'input_image','image_url':image['image_url'],'detail':'auto'}])
        return self._pdf_request('report_layout_refine',pdf,filename,parts,False)

    def review_pdf(self, task, pdf, filename, html, customer_findings=None):
        from urs.costing import review_parts
        return self._pdf_request(task,pdf,filename,review_parts(task,html,customer_findings),True)

    def _pdf_request(self, task, pdf, filename, texts, json_response):
        key=os.environ.get('URS_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
        try:
            config=validate({k:self.settings[k] for k in ('model','effort','max_output_tokens')}) if self.settings is not None else effective(self.workflow,document=self.document)
        except SettingsError as exc:raise AIBlocked(str(exc)) from None
        from urs.report_transport import settings
        api_timeout=settings(self.workflow,document=self.document)['timeout_seconds']
        model=config['model'];effort=config['effort'];output_limit=config['max_output_tokens']
        from urs import costing
        if not key:raise AIBlocked('API 연결 설정을 확인하세요. 유료 호출하지 않았습니다.')
        try:
            payload=costing.payload(config,pdf,filename,texts,json_response)
            authorized=self.authorized_quotes.get((self.document,task))
            if authorized is not None:
                q=costing.quote(self.workflow,payload)
                if q['status']!='READY' or q['fingerprint']!=authorized:raise costing.CostError('화면에서 확인한 비용과 실행 자료/설정이 달라졌습니다. 무료 비용 계산을 다시 확인하세요. 유료 호출하지 않았습니다.')
            if task=='report_layout_refine':
                q=costing.quote(self.workflow,payload,True)
                from decimal import Decimal
                spent=Decimal(0)
                with self.workflow.connect() as db:
                    for ident in self.report_execution_call_ids:
                        record=json.loads(db.execute('SELECT payload FROM ai_call_costs WHERE call_id=?',(ident,)).fetchone()[0])
                        spent+=Decimal(str(record['actual_cost_usd'] if record['actual_cost_usd'] is not None else record['quote']['estimated_max_usd']))
                if spent+Decimal(str(q['estimated_max_usd']))>Decimal(str(q['cap_usd'])):
                    raise costing.CostError(f"이번 보고서 실행의 기존 사용/미정산 예약액 ${spent:.6f} + 다듬기 예상 상한 ${q['estimated_max_usd']:.6f}가 실행 한도 ${q['cap_usd']:.6f}를 넘습니다. 다듬기 유료 호출하지 않았습니다.")
            call_id=costing.reserve(self.workflow,self.document,task,payload)
            if task in ('report_html','report_layout_refine'):self.report_execution_call_ids.append(call_id)
        except costing.CostError as exc:raise AIBlocked(str(exc)) from None
        req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        if task in ('report_html','report_layout_refine'):
            from urs.report_transport import request
            return request(self,req,call_id,output_limit,api_timeout,task=task)
        from urs.request_evidence import manifest
        self.request_manifest=manifest(task,req);self.request_manifest['request_attempted']=True
        started=time.monotonic();http_status=None;result=None
        try:
            with urllib.request.urlopen(req,timeout=api_timeout) as response:
                value=getattr(response,'status',None);http_status=value if type(value) is int else None
                self.request_manifest['http_status']=http_status
                result=json.load(response)
            if result.get('status')!='completed':
                if (result.get('incomplete_details') or {}).get('reason')=='max_output_tokens':
                    raise AIError(f'출력 토큰 한도({output_limit:,})에 도달했습니다. 웹의 AI 호출 설정에서 출력 한도를 조정한 뒤 다시 실행하세요.')
                raise AIError('모델 응답이 완료되지 않았습니다.')
            raw=''.join(c['text'] for item in result.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
            value=json.loads(raw) if json_response else raw
            if json_response and not isinstance(value,dict):raise ValueError('JSON object required')
            if not json_response and (not raw or not any(t in raw.lower() for t in ('<html','<!doctype','<body'))):
                raise ValueError('Expected HTML; response is never unwrapped or rewritten')
        except AIError as exc:
            exc.diagnostics={'max_output_tokens':output_limit,'timeout_seconds':api_timeout,'timeout_policy':'unlimited','elapsed_seconds':round(time.monotonic()-started,3),'http_status':http_status,'response_status':result.get('status') if isinstance(result,dict) else None,'incomplete_reason':(result.get('incomplete_details') or {}).get('reason') if isinstance(result,dict) else None}
            costing.finish(self.workflow,call_id,'failed',result)
            raise
        except Exception as exc:
            costing.finish(self.workflow,call_id,'failed',result)
            timed=isinstance(exc,(TimeoutError,socket.timeout)) or isinstance(exc,urllib.error.URLError) and isinstance(exc.reason,(TimeoutError,socket.timeout))
            if isinstance(exc,urllib.error.HTTPError):reason=f'OpenAI HTTP 오류 ({exc.code}). API 권한·사용 한도를 확인하세요.';http_status=exc.code
            elif timed:reason='연결/제공자 측 시간 초과 또는 연결 종료입니다. 앱의 검토 응답 대기 제한은 없습니다. 자동 재시도하지 않습니다.'
            elif http_status is not None:reason='OpenAI 응답 후 검토 JSON 해석 실패. 결과 형식을 확인하세요.'
            else:reason='OpenAI 연결/검토 응답 처리 실패. HTTP 응답 상태는 미확인입니다.'
            error=AIError(reason);error.diagnostics={'max_output_tokens':output_limit,'timeout_seconds':api_timeout,'timeout_policy':'unlimited','elapsed_seconds':round(time.monotonic()-started,3),'http_status':http_status,'response_status':result.get('status') if isinstance(result,dict) else None,'error_type':type(exc).__name__}
            raise error from None
        costing.finish(self.workflow,call_id,'completed',result)
        return value

def review_text(task):
    instructions = {
        'independent_verify': 'Independently compare the original PDF with the supplied report HTML and image inputs. Check technical meaning, omissions, additions, negation, conditions, obligations, quantities, units, model codes and table associations. Return JSON {status:PASS|FAIL|NEEDS_REVIEW,issues:[{page,pages,severity,category,issue_type,title_ko,problem_ko,why_ko,fix_ko,question_ko,before,after,source_en,evidence:[{page,source_en}],needs_confirmation}]}. issue_type must distinguish translation, customer, and program. Use short natural Korean: state the actual difference and its practical consequence once, without repeating the title. Provide a specific customer question when the original itself is ambiguous or inconsistent; do not invent a corrected requirement. Leave unknown evidence or impact fields empty rather than inventing reasons. For cross-page comparisons, cite each original page and its exact supporting quotation in evidence. Image references named urs-review-image are transport labels for separately supplied images, not missing staff-report images. Image addresses, CSS visibility and rendering defects are program issues, never translation corrections. For customer/program issues leave before/after empty. Do not edit or rewrite the report. before must quote the exact existing text within one HTML text node, after is the proposed Korean replacement. If a unique exact location cannot be established, mark needs_confirmation true. Missing original content needs a clearly quoted existing anchor for a proposed insertion. Do not guess uncertain source characters or values. Treat pagination or line wrapping alone as layout observations, not translation errors. Distinguish proven semantic errors from matters requiring customer or employee confirmation.',
        'technical_analysis': 'Analyze equipment, processes, specification conflicts and customer questions using the original PDF and supplied report. Cite original page numbers. Return JSON {status:PASS|FAIL|NEEDS_REVIEW,sections:[],conflicts:[],questions:[],issues:[]}. Do not edit or rewrite the HTML.'}
    if task=='independent_verify':
        instructions[task]+=' 원문과 번역의 일치 여부를 판정하세요. 원문 자체의 모호성·상충으로 고객에게 물어볼 사항은 issue_type:customer로 분리하고 이것만 남으면 status:PASS로 반환하세요. 원문과 다른 번역·누락·번역 근거 부족 및 실제 프로그램 표시 문제는 계속 독립검증 대상으로 남기세요. 고객 확인 필요를 이유로 번역 오류를 customer로 재분류하지 마세요.'
    return instructions[task]+' 설명과 판단 이유는 한국어로 먼저 작성하세요. 필요한 영어 원문 근거는 source_en에 분리하세요. issues 항목에는 page, severity(오류 또는 확인 필요), reason을, questions 항목에는 question_ko, reason_ko를 포함하세요. 기존 HTML은 수정하지 말고 before/after는 제안일 때만 표시하세요.'

"""Non-secret, employee-scoped API request settings with environment fallback."""
import hashlib
import json
import os
import re

EFFORTS=frozenset({'none','minimal','low','medium','high','xhigh'})
MAX_OUTPUT_TOKENS=1_000_000

class SettingsError(ValueError):
    pass

def normalize_effort(value):
    if value is None or value=='':return None
    if not isinstance(value,str):raise SettingsError('effort 값을 선택해 주세요.')
    value=value.strip().lower()
    if not value:return None
    if value not in EFFORTS:raise SettingsError('effort는 API 기본값, none, minimal, low, medium, high, xhigh 중에서 선택하세요.')
    return value

def validate(value,allow_empty_model=False):
    if not isinstance(value,dict) or set(value)!={'model','effort','max_output_tokens'}:
        raise SettingsError('모델·effort·출력 토큰 한도 3개 설정이 필요합니다.')
    model=value['model']
    if not isinstance(model,str):raise SettingsError('API 모델 ID를 입력해 주세요.')
    model=model.strip()
    if (not model and not allow_empty_model) or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}',model)):
        raise SettingsError('API 모델 ID는 1~200자의 영문·숫자·점·하이픈·밑줄·콜론·슬래시로 입력하세요.')
    tokens=value['max_output_tokens']
    if type(tokens) is not int or not 1<=tokens<=MAX_OUTPUT_TOKENS:
        raise SettingsError('출력 토큰 한도는 1~1,000,000 사이의 정수로 입력하세요. 실제 최대값은 모델에 따라 다릅니다.')
    return {'model':model,'effort':normalize_effort(value['effort']),'max_output_tokens':tokens}

def environment():
    try:tokens=int(os.environ.get('URS_OPENAI_MAX_OUTPUT_TOKENS','').strip() or '5000')
    except ValueError:raise SettingsError('URS_OPENAI_MAX_OUTPUT_TOKENS는 정수여야 합니다.') from None
    return validate({'model':os.environ.get('URS_OPENAI_MODEL',''),'effort':os.environ.get('URS_OPENAI_REASONING_EFFORT',''),
                     'max_output_tokens':tokens},allow_empty_model=True)

def effective(workflow,document=None,owner=None):
    with workflow.connect() as db:
        if owner is None and document is not None:
            row=db.execute('SELECT p.owner FROM documents d JOIN projects p ON p.id=d.project WHERE d.id=?',(document,)).fetchone()
            owner=row['owner'] if row else None
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_settings'").fetchone()
        row=db.execute('SELECT version,payload FROM ai_settings WHERE owner=? ORDER BY version DESC LIMIT 1',(owner,)).fetchone() if exists and owner is not None else None
    if row:
        return {**validate(json.loads(row['payload'])),'version':row['version'],'source':'web'}
    return {**environment(),'version':0,'source':'server'}

def signature(config):
    return hashlib.sha256(json.dumps({k:config[k] for k in ('model','effort','max_output_tokens')},sort_keys=True).encode()).hexdigest()

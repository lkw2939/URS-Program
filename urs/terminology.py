"""Reviewed technical references supplied as context, never treated as instructions."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

PATH = Path(__file__).resolve().parents[1] / '.runtime/terminology.json'


def load(path=None):
    path=Path(path) if path is not None else PATH
    if not path.exists():
        return {'status':'UNVERIFIED','reason':'승인된 공식 용어 자료가 아직 등록되지 않았습니다.','entries':[]}
    with path.open('rb') as source:raw=source.read(100001)
    if len(raw)>100000:
        raise ValueError('용어집이 너무 큽니다. 분야별 선별이 필요합니다.')
    data=json.loads(raw)
    entries=data.get('entries') if isinstance(data,dict) else None
    if not isinstance(entries,list) or not entries:
        raise ValueError('검토한 용어 항목이 필요합니다.')
    for entry in entries:
        required=('english','korean','context','organization','document','edition','location','url','reviewer','scope')
        if not isinstance(entry,dict) or any(not isinstance(entry.get(k),str) or not entry[k].strip() for k in required):
            raise ValueError('공식 용어의 원문·번역·문맥·출처·판본·위치·검토자·적용 범위가 필요합니다.')
        if entry.get('approved') is not True or entry['scope'] not in ('standard','manufacturer','company'):
            raise ValueError('검토 승인과 표준/제조사/사내 용어 구분이 필요합니다.')
        url=urlparse(entry['url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password:
            raise ValueError('출처의 안전한 HTTPS 주소가 필요합니다.')
    return {'status':'REVIEWED_REFERENCE','sha256':hashlib.sha256(raw).hexdigest(),'entries':entries}


def import_reviewed(source):
    """Register an already reviewed corpus; never approve or fetch references."""
    source=Path(source)
    with source.open('rb') as stream:raw=stream.read(100001)
    if len(raw)>100000:raise ValueError('용어집이 너무 큽니다.')
    PATH.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Validate exactly the bytes to be installed, then publish without overwrite.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=PATH.parent,prefix='.terms-',delete=False) as staged:
            temporary=Path(staged.name);staged.write(raw);staged.flush();os.fsync(staged.fileno())
        checked=load(temporary)
        if checked['status']!='REVIEWED_REFERENCE':raise ValueError('검토된 용어집이 필요합니다.')
        os.link(temporary,PATH)
        return {'status':checked['status'],'entries':len(checked['entries']),'sha256':checked['sha256'],
                'qualification_reevaluation_required':True}
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def digest():
    return hashlib.sha256(PATH.read_bytes()).hexdigest() if PATH.exists() else 'no-reviewed-terminology'

"""Human-reviewed benchmark qualification; never inferred from AI self-scores."""
import hashlib
import json
from pathlib import Path

from urs.workflow import Blocked


def fingerprint():
    root=Path(__file__).resolve().parent
    digest=hashlib.sha256()
    for name in ('ai.py','processing.py','quality.py','extraction.py','reports.py'):
        digest.update(name.encode());digest.update((root/name).read_bytes())
    from urs.terminology import digest as terminology_digest
    digest.update(terminology_digest().encode())
    digest.update((root/'terminology.py').read_bytes())
    return digest.hexdigest()


def record(workflow, model, report):
    if not isinstance(model,str) or not model.strip():raise ValueError('평가한 모델 ID가 필요합니다.')
    if not isinstance(report,dict) or not isinstance(report.get('reviewer'),str) or not report['reviewer'].strip():raise ValueError('전문가 검토자 기록이 필요합니다.')
    samples=report.get('samples')
    if not isinstance(samples,list) or len(samples)<100:raise ValueError('최소 100개 전문가 대조 항목이 필요합니다.')
    ids=set();sources=set();languages=set()
    for sample in samples:
        if not isinstance(sample,dict):raise ValueError('평가 항목 형식 오류')
        for key in ('id','source','expected_meaning','observed_translation','evidence'):
            if not isinstance(sample.get(key),str) or not sample[key].strip():raise ValueError('평가 근거 누락')
        if sample['id'] in ids or sample['source'] in sources:raise ValueError('중복 평가 항목')
        ids.add(sample['id']);sources.add(sample['source'])
        if sample.get('language') not in ('en','id') or sample.get('verdict') not in ('PASS','FAIL') or type(sample.get('critical_error')) is not bool:raise ValueError('평가 판정 형식 오류')
        languages.add(sample['language'])
    if languages!={'en','id'}:raise ValueError('영어·인도네시아어 평가가 모두 필요합니다.')
    total=len(samples);correct=sum(s['verdict']=='PASS' for s in samples);critical=sum(s['critical_error'] for s in samples)
    raw=json.dumps(report,ensure_ascii=False,sort_keys=True)
    with workflow.connect() as db:
        db.execute('INSERT INTO qualifications VALUES(?,?,?,?,?,?,?,?)',
                   (fingerprint(),model,total,correct,critical,report['reviewer'],raw,hashlib.sha256(raw.encode()).hexdigest()))
    return {'total':total,'correct':correct,'critical_errors':critical,'accuracy':correct/total,
            'passed':correct/total>=.99 and critical==0}


def require(workflow,model):
    with workflow.connect() as db:
        row=db.execute('SELECT * FROM qualifications WHERE fingerprint=? AND model=? ORDER BY rowid DESC LIMIT 1',
                       (fingerprint(),model)).fetchone()
    if row is None:raise Blocked('현재 코드·모델의 전문가 평가집 검증 근거가 없습니다. 99% 목표를 미측정 상태로 승인할 수 없습니다.')
    if hashlib.sha256(row['evidence'].encode()).hexdigest()!=row['digest'] or row['correct']/row['total']<.99 or row['critical']!=0:
        raise Blocked('전문가 평가의 의미 정확도 99% 이상·중대 안전 오역 0건 기준을 통과하지 못했습니다.')
    return {'model':model,'total':row['total'],'correct':row['correct'],'critical':row['critical'],'reviewer':row['reviewer'],'digest':row['digest']}

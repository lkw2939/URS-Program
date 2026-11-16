"""Readable, script-free exports of document validation evidence."""
import hashlib
import json
from html import escape

STAGES={'source':'원본 보관','extract':'추출·원문 대조','translate':'번역 생성','verify':'독립 의미 검증','analyze':'기술 분석','report':'보고서','approval':'직원 승인'}
STATUS={'PASS':'완료','FAIL':'오류 확인','NEEDS_REVIEW':'검토 필요','UNVERIFIED':'확인 전','BLOCKED':'진행 불가','NOT_IMPLEMENTED':'기능 준비 중'}


def envelope(record):
    canonical=json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    return {'record':record,'record_sha256':hashlib.sha256(canonical).hexdigest(),
            'hash_scope':'SHA-256 detects accidental content changes; this is not a digital signature or proof of translation accuracy.'}


def html_report(bundle):
    record=bundle['record'];state=record['snapshot']
    def esc(value):return escape(str(value),quote=True)
    def table(headers,rows):
        return '<table><thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
    statuses=[]
    for stage in state['stages']:
        result=next((r for r in state['results'] if r['stage']==stage['id']),None)
        code='PASS' if stage['passed'] else result['status'] if result else 'UNVERIFIED'
        statuses.append((STAGES.get(stage['id'],stage['id']),STATUS.get(code,code),code))
    rows=[]
    for result in record['all_results']:
        evidence=json.loads(result['evidence'])
        rows.append((result['revision'],STAGES.get(result['stage'],result['stage']),result['check_id'],STATUS.get(result['status'],result['status']),evidence.get('reason','검사별 근거는 원본 JSON 참조'),result['validator'],result['version'],result['created']))
    corrections=''.join('<details><summary>'+esc(f"리비전 {item['revision']} · 오류 수정 및 독립 재검증")+'</summary><pre>'+esc(json.dumps(item['verification'],ensure_ascii=False,indent=2))+'</pre></details>' for item in record['verification_history'])
    events=''.join('<details><summary>'+esc(f"리비전 {event['revision']} · {event['action']} · {event['created']}")+'</summary><pre>'+esc(json.dumps(json.loads(event['detail']),ensure_ascii=False,indent=2))+'</pre></details>' for event in state['events'])
    return ('''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>URS 문서 검증 기록</title><style>body{font:15px/1.7 sans-serif;max-width:1100px;margin:35px auto;padding:0 20px;color:#18343e}table{border-collapse:collapse;width:100%;margin:20px 0;display:block;overflow-x:auto}th,td{border:1px solid #cbd9df;padding:9px;text-align:left;vertical-align:top}th{background:#e8f3f2}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f9;padding:16px}.notice{padding:15px;background:#fff1dc}details{border-bottom:1px solid #d5e1e6;padding:12px 0}code{overflow-wrap:anywhere}</style></head><body><h1>문서 검증·수정 기록</h1>'''
        +'<p class="notice">이 파일은 검증 기록입니다. 내려받았다는 사실만으로 문서의 정확도나 최종 승인이 보장되지 않습니다.</p>'
        +'<p>원본: '+esc(record['original']['name'])+' · '+esc(record['original']['pages'])+'페이지</p>'
        +'<p>현재 리비전: '+esc(state['revision'])+' · 승인 상태: '+('승인 완료' if state['approved'] else '승인 전')+'</p>'
        +'<p>내보낸 시각(한국): '+esc(bundle['exported_at_kst'])+'</p>'
        +'<p>원본 SHA-256: <code>'+esc(record['original']['sha256'])+'</code></p>'
        +'<h2>단계별 체크리스트</h2>'+table(('단계','상태','기록 코드'),statuses)
        +'<h2>현재·이전 리비전의 검사 결과</h2>'+table(('리비전','단계','검사','결과','근거 요약','검사기','버전','검사 시각(UTC)'),rows)
        +'<h2>오류 수정 전후·독립 재검증</h2>'+corrections+'<h2>수정·검증 이력</h2>'+events
        +'<h2>기록 무결성</h2><p>기록 SHA-256: <code>'+esc(bundle['record_sha256'])+'</code></p>'
        +'<p>같이 제공되는 JSON의 record를 정렬·UTF-8 직렬화해 계산한 값입니다. 전자서명이나 실제 번역 정확도 인증은 아닙니다.</p></body></html>').encode()

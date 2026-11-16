"""Deterministic guards complement, and never replace, semantic verification."""
import re
import unicodedata
from collections import Counter

# Digits adjacent to units (120mm) must still be checked. Product-code digits
# participate too; code strings have their own separate preservation check.
NUMBERS = re.compile(r'(?<![\d.,])[+-]?\d+(?:[.,]\d+)*(?!\d|[.,]\d)')
CODES = re.compile(r'\b(?:[A-Z][A-Z0-9]*[-_][A-Z0-9-]+|[A-Z]{1,6}\d+[A-Z0-9-]*)\b')
UNIT_PATTERNS = [
    ('packs/min',r'(?:packs?\s*/\s*min(?:ute)?s?|팩\s*/\s*분|팩\s*퍼\s*분|kemasan\s*/\s*menit)'),
    ('sachets/min',r'(?:sachets?\s*/\s*min(?:ute)?s?|사셰\s*/\s*분|saset\s*/\s*menit)'),
    ('pieces/min',r'(?:pieces?\s*/\s*min(?:ute)?s?|pcs\s*/\s*min|개\s*/\s*분)'),
    ('m/min',r'(?:m\s*/\s*min|m\s*/\s*분|미터\s*/\s*분)'),
    ('mm',r'(?:mm|밀리미터)'),('cm',r'(?:cm|센티미터)'),
    ('kg',r'(?:kg|킬로그램)'),('g',r'(?:g|그램)'),
    ('bar',r'(?:bar|바)'),('MPa',r'(?:MPa|메가파스칼)'),('kPa',r'(?:kPa|킬로파스칼)'),
    ('V',r'(?:V|볼트)'),('W',r'(?:W|와트)'),('kW',r'(?:kW|킬로와트)'),
    ('Hz',r'(?:Hz|헤르츠)'),('rpm',r'(?:rpm|분당\s*회전)'),
    ('m',r'(?:m|미터)'),
]
# Deliberately bounded: unknown/composite units are left for semantic review.
QUANTITIES = [(canonical,re.compile(r'(?<![\d.,])([+-]?\d+(?:[.,]\d+)*)\s*('+pattern+r')(?![A-Za-z0-9/²³])',re.I if canonical in ('packs/min','sachets/min','pieces/min','rpm') else 0))
              for canonical,pattern in UNIT_PATTERNS]


def quantities(text):
    text=unicodedata.normalize('NFKC',text)
    found=[]
    occupied=[]
    for canonical,pattern in QUANTITIES:
        for match in pattern.finditer(text):
            if any(match.start()<end and match.end()>start for start,end in occupied):continue
            occupied.append(match.span())
            found.append((match.group(1),canonical))
    return Counter(found)


def translation_issues(blocks, translated):
    issues = []
    expected = {b['id'] for b in blocks}
    if set(translated) != expected:
        issues.append({'id':None,'type':'coverage','reason':'원문 ID와 번역 ID 집합 불일치'})
    for block in blocks:
        source, target = block['text'], translated.get(block['id'], '')
        if not isinstance(target, str) or not target.strip():
            issues.append({'id':block['id'],'type':'missing','reason':'번역 누락'})
            continue
        if Counter(NUMBERS.findall(unicodedata.normalize('NFKC',source))) != Counter(NUMBERS.findall(unicodedata.normalize('NFKC',target))):
            issues.append({'id':block['id'],'type':'numbers','reason':'수치 누락·변경·추가','source':source,'target':target})
        if quantities(source)!=quantities(target):
            issues.append({'id':block['id'],'type':'quantity_unit','reason':'수치와 단위의 연결 누락·변경·추가. 단위별 수치 관계를 원문과 대조해야 합니다.','source':source,'target':target})
        if any(code not in target for code in CODES.findall(source)):
            issues.append({'id':block['id'],'type':'product_code','reason':'제품/요구사항 코드 변경','source':source,'target':target})
        if re.search(r'\b(?:shall not|must not|do not|tidak boleh|dilarang)\b',source,re.I) and not re.search(r'않|금지|불가|안\s',target):
            issues.append({'id':block['id'],'type':'safety_negation','reason':'부정 안전 요구의 한국어 표현 확인 필요','source':source,'target':target})
    return issues


def parse_translations(result, blocks):
    pairs = result.get('translations')
    if not isinstance(pairs,list) or any(not isinstance(p,dict) or not isinstance(p.get('id'),str) or not isinstance(p.get('text'),str) for p in pairs):
        raise ValueError('번역 응답 형식 불일치')
    ids = [p['id'] for p in pairs]
    if len(ids) != len(set(ids)) or set(ids) != {b['id'] for b in blocks}:
        raise ValueError('번역 누락·중복 또는 알 수 없는 ID')
    return {p['id']:p['text'] for p in pairs}

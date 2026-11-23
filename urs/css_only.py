"""Byte-preserving guard: only the text inside existing style elements may change."""
import re
STYLE=re.compile(r'(<style\b[^>]*>)(.*?)(</style\s*>)',re.I|re.S)
DEFAULT_REQUEST='페이지별 내용량·현재 글자 크기·남는 공간을 먼저 분석하고 각 쪽에 맞춰 배치하세요. 모든 쪽에 같은 글자 크기와 간격을 일괄 적용하지 마세요. 내용이 적은 쪽은 본문 글자 크기·줄 간격·문단 간격을 적절히 늘려 가독성을 높이고, 내용이 많은 쪽은 별도로 조정해 잘림·겹침을 막으세요. 제목과 본문, 서로 다른 주제의 구역 사이를 명확히 구분하고 그림·표 크기도 쪽별로 조정하세요. 하단 여백을 어느 정도 남겨도 되며 공간을 100% 채우는 것이 목표가 아닙니다. 전체 페이지가 자연스럽고 읽기 편해야 합니다. 특정 문서의 글자 크기값·좌표·쪽수를 다른 문서에 복사하지 마세요.'
INSTRUCTION='''CSS 수정 전용입니다. 번역은 이미 끝났습니다. 영어 원본 PDF는 그림·구성의 참고 자료일 뿐이며 기존 번역을 재작성하지 마세요. 기존 HTML 전체를 반환하고 변경은 기존 <style> 내부의 CSS에만 한정하세요. style 태그 밖의 모든 바이트, 본문·제목·수치·모델 코드·목록·표의 행열·셀·캡션·주석·링크·쪽번호 문구·요소 순서·그림 src와 순서를 그대로 보존하세요. inline style도 변경하지 마세요.
종이 크기는 브라우저와 인쇄에서 A4 세로 210×297mm로 유지하세요. 그 외 여백, 글꼴, 글자 크기, 줄 간격, 구역 간격, 그림 표시 크기, 정렬, 쪽번호 위치, 카드/테두리/색상은 자유롭게 설계하세요. 기존 CSS는 제약이 아니라 수정 대상입니다. 빈 공간을 최대한 유용하게 쓰되 모든 공간을 억지로 채우지는 마세요. 원본 PDF의 위치·Letter 크기나 기존 고정 여백·최소 글자 크기를 그대로 따를 필요는 없습니다. 쪽별 내용량에 맞춰 개별 선택자로 조정하세요. 직원이 이번에 입력한 수정 요청이 있으면 반영하세요.
읽기 좋은 배치를 목표로 하며 내용을 삭제·숨김·자르거나 그림을 왜곡하지 마세요. 원본 이미지를 다시 만들거나 자르지 말고 기존 그림이 PDF 재선택 없이 보이게 하세요. 장 순서·내용 소속·HTML 구조는 보존하고 CSS만으로 불가능하면 그 내용을 그대로 보존하세요. 프로그램은 임의 분할이나 재배치를 하지 않습니다. 마크다운 없이 전체 HTML만 반환하세요.'''+'\n'+DEFAULT_REQUEST
def unchanged_outside_styles(before,after):
 a=list(STYLE.finditer(before));b=list(STYLE.finditer(after))
 if not a or len(a)!=len(b):return False
 def outside(value,matches):
  end=0;parts=[]
  for m in matches:parts.extend([value[end:m.start(2)],'<CSS-CONTENT>']);end=m.end(2)
  parts.append(value[end:]);return parts
 return outside(before,a)==outside(after,b)

def layout_policy(audit):
    """CSS design measurements are advisory; content visibility and A4 remain mandatory."""
    import copy
    result=copy.deepcopy(audit);warnings=[]
    for key in ('pages','narrow_pages'):
        for page in result.get(key,[]):
            kept=[]
            for issue in page['issues']:
                if issue in ('작은 글자','강제 축소 배치') or issue.startswith('모델 확인 필요:'):warnings.append({'page':page['page'],'reason':issue})
                else:kept.append(issue)
            page['issues']=kept
    if audit.get('status')!='UNVERIFIED':
        issues=[x for x in result.get('issues',[]) if x not in ('좁은 화면에서도 A4 크기/내용 유지 필요','A4 크기/넘침/읽기 크기/이미지 확인 필요')]
        if any(p['issues'] for k in ('pages','narrow_pages') for p in result.get(k,[])):issues.append('A4 크기/내용 표시 확인 필요')
        result['issues']=issues;result['status']='NEEDS_REVIEW' if issues else 'PASS'
    result['design_warnings']=warnings;result['layout_policy']='css-freedom-v1'
    return result

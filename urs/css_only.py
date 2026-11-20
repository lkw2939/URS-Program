"""Byte-preserving guard: only the text inside existing style elements may change."""
import re
STYLE=re.compile(r'(<style\b[^>]*>)(.*?)(</style\s*>)',re.I|re.S)
INSTRUCTION='''이번 작업은 CSS 수정 전용입니다. 원본 영문 PDF는 배치 참고만 하세요. 기존 HTML 전체를 반환하되 변경은 기존 <style> 요소 내부의 CSS 텍스트로만 제한하세요. <style> 태그 자체와 그 밖의 모든 바이트, 본문·제목·수치·모델 코드·목록·표 행열·셀·캡션·번역자 주·링크·쪽번호 문구·요소 순서·img src/순서를 그대로 보존하세요. 마크다운을 붙이지 마세요. 재번역, 문장 고침, 요소 추가/삭제/이동, inline style 변경은 금지합니다. 숨겨진 기존 이미지는 CSS로 표시하세요. A4 세로 210×297mm와 해당 보고서의 원문 쪽 순서·장수 유지를 목표로 하되 내용을 자르거나 숨기지 마세요. 쪽번호 문구는 보존하고 CSS로 아래 가운데에 배치하세요. 직원이 요청한 쪽별 배치와 그림 크기·여백을 CSS 선택자로 조정하세요. 원본과 같은 덩어리를 비슷한 위치에서 찾도록 하되 CSS만으로 불가능하면 원래 내용을 보존하세요.'''
def unchanged_outside_styles(before,after):
 a=list(STYLE.finditer(before));b=list(STYLE.finditer(after))
 if not a or len(a)!=len(b):return False
 def outside(value,matches):
  end=0;parts=[]
  for m in matches:parts.extend([value[end:m.start(2)],'<CSS-CONTENT>']);end=m.end(2)
  parts.append(value[end:]);return parts
 return outside(before,a)==outside(after,b)

"""User-authorized report output contract; Terra owns all translation and design."""
VERSION='a4-browser-v1'
TEXT='''현재 URS 보고서의 출력 요구사항(저장 프롬프트의 PDF 재선택 방식 대신 이 조건 적용):
번역·문서 구성·HTML/CSS 디자인과 각 쪽 내부 재배치는 모델이 직접 작성한다. 원문 내용을 삭제·요약·잘라내지 않는다.
브라우저에서도 원본 1쪽당 section[data-urs-page="원문쪽번호"] 한 장을 만들고 각 장의 border-box를 210mm × 297mm A4 세로로 지정한다. @page 인쇄 설정만으로 대신하지 않는다. 좁은 화면에서도 A4 CSS 크기를 유지하고 수평 스크롤을 허용하며 미디어쿼리로 페이지를 축소하지 않는다.
문단·표·사진·도면·여백을 해당 장 안에서 재배치한다. 글자가 많다는 이유로 자동 다음 장으로 넘기거나 overflow:hidden, 잘라내기, transform/zoom 축소로 숨기지 않는다. 본문은 읽기 가능한 크기(최소13 CSS px), 표·캡션은 최소12px로 쓴다.
한 장에 읽기 좋게 담기 어려우면 data-urs-unfit="구체적인 이유"를 그 장에 표시하고, 내용을 숨기지 말고 보존한다. 어려운 쪽은 사용자에게 명시한다.
이미지 src에는 제공한 urs-image:PAGE:INDEX만 사용한다. 프로그램이 그 자리의 src만 원본 PNG data URL로 치환한다. 치환 후 사진이 즉시 표시되어야 하며 ready 클래스·PDF 선택·PDF.js 렌더링을 기다려 숨기지 않는다. src 접두어를 찾는 스크립트에 표시를 의존하지 않는다. 사진·도면 비율을 유지하고 object-fit:cover나 잘림을 사용하지 않는다.
원본 PDF 재선택/업로드 UI와 외부 PDF.js를 넣지 않는다. 파일 내부 이미지·CSS로 오프라인 열람 가능하게 한다. 디자인·배치 선택은 모델이 담당한다.
실제 완성 HTML만 <!DOCTYPE html>부터 </html>까지 출력하고 마크다운 코드펜스를 붙이지 않는다.'''

"""User-authorized output mechanics; Terra owns translation and page design."""
import re
from html.parser import HTMLParser
VERSION='a4-readable-layout-v5'
TEXT='''현재 URS 보고서의 출력 요구사항(저장 프롬프트에 원본 PDF 재선택·PDF.js 방식이 있어도 아래 방식이 우선):
번역·문서 구성·HTML/CSS 디자인과 각 쪽 내부 재배치는 모델이 직접 작성한다. 처음부터 첨부 원본 PDF의 사진·도면과 이미지 목록의 실제 width_px·height_px·aspect_ratio를 확인하고, A4 안에 본문과 함께 들어갈 표시 크기를 직접 지정한다. 픽셀 수를 CSS 표시 크기로 그대로 쓰지 말고 원본 비율을 유지한다. 원문 내용을 삭제·요약·잘라내지 않는다.
브라우저에서도 원본 1쪽당 section[data-urs-page="원문쪽번호"] 구역을 만들고 각 장의 border-box를 210mm × 297mm A4 세로로 지정한다. @page 인쇄 설정만으로 대신하지 않는다. 좁은 화면에서도 A4 CSS 크기를 유지하고 수평 스크롤을 허용하며 미디어쿼리로 페이지를 축소하지 않는다.
문단·표·사진·도면·여백을 읽기 좋게 배치한다. 원문 1쪽의 내용은 가능한 한 해당 A4 한 장 안에 배치한다. overflow:hidden, 잘라내기, transform/zoom 축소로 숨기지 않는다. 본문은 읽기 가능한 크기(최소13 CSS px), 표·캡션은 최소12px로 쓴다.
프로그램은 HTML의 CSS·문단·표·그림 크기를 바꾸거나 장을 나누지 않는다. 사진 삽입 후 실제 브라우저 화면에서 배치 문제가 발견되면 같은 모델에 화면과 HTML을 보내 최대 1회 다듬기를 요청한다. 한 장에 읽기 좋게 담을 수 없으면 내용을 숨기지 말고 data-urs-unfit="구체적인 이유"로 표시한다.
사진·도면 자리는 일반 <img> 태그로만 만든다. 예: <img src="urs-image:1:2" alt="원본 1쪽 두 번째 도면">. 제공한 목록의 urs-image:쪽:번호를 img의 src에 직접 넣는다. canvas, picture/source, data-src, CSS 배경 그림, JavaScript 그림 삽입으로 대신하지 않는다.
프로그램이 처음 업로드된 PDF에서 원본 사진·도면을 잘라 지정 img src만 원본 PNG data URL로 치환해 최종 HTML로 저장한다. 사용자가 PDF를 다시 고르거나 첨부할 필요가 없다.
사진을 숨기는 CSS(display:none, visibility:hidden, opacity:0, content-visibility:hidden 등)를 만들지 않는다. ready 클래스, 파일 선택, PDF.js, onload/onerror, src 접두어를 찾는 스크립트, 클릭·스크롤 이벤트에 사진 표시를 의존하지 않는다. 치환된 img는 JavaScript와 인터넷 연결 없이도 즉시 보여야 한다.
원본 PDF 재선택/업로드 input, PDF.js 및 PDF worker 로딩, 원본 PDF 뷰어/렌더링 코드를 넣지 않는다. 사진·도면 비율을 유지하고 object-fit:cover나 잘림을 사용하지 않는다. 디자인·배치 선택은 모델이 담당한다.
실제 완성 HTML만 <!DOCTYPE html>부터 </html>까지 출력하고 마크다운 코드펜스를 붙이지 않는다.'''

from urs.css_only import DEFAULT_REQUEST
TEXT+='\n'+DEFAULT_REQUEST

class _Contract(HTMLParser):
    def __init__(self,raw):
        super().__init__();self.issues=[];self.in_script=False;self.script=[];self.feed(raw);self.close()
    def add(self,message):
        if message not in self.issues:self.issues.append(message)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and (attrs.get('type') or '').lower()=='file':self.add('원본 PDF 재선택/파일 업로드 UI가 있습니다.')
        if tag in ('canvas','picture','source'):self.add('사진·도면은 canvas/picture/source 대신 일반 img 태그로 표시해야 합니다.')
        if tag=='script':
            self.in_script=True;self.script=[attrs.get('src') or '']
        if tag in ('object','embed','iframe') and ('application/pdf' in (attrs.get('type') or '').lower() or re.search(r'\.pdf(?:[?#]|$)',attrs.get('src') or attrs.get('data') or '',re.I)):
            self.add('원본 PDF 뷰어에 의존하는 구성이 있습니다.')
        uri=attrs.get('src') or attrs.get('href') or attrs.get('xlink:href') or ''
        if uri.startswith('urs-image:') and tag!='img':self.add('그림 자리는 일반 img 태그의 src만 사용해야 합니다.')
        if tag=='img':
            if not re.fullmatch(r'urs-image:[1-9]\d*:[1-9]\d*',attrs.get('src') or ''):self.add('img src에 원본 사진·도면 식별 주소가 없습니다.')
            if any(k.lower().startswith('on') for k in attrs):self.add('사진 표시가 JavaScript 이벤트에 의존할 수 있습니다.')
    handle_startendtag=handle_starttag
    def handle_data(self,data):
        if self.in_script:self.script.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.in_script:
            if re.search(r'pdfjs|pdf\.worker|\bpdf(?:\.min)?\.(?:m?js)\b', '\n'.join(self.script),re.I):self.add('PDF.js 또는 PDF worker 로딩/렌더링 코드가 있습니다.')
            self.in_script=False;self.script=[]

def check(raw):
    parser=_Contract(raw)
    if parser.in_script:parser.handle_endtag('script')
    return parser.issues

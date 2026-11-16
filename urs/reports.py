"""Word/PDF artifacts with embedded Korean font and original page appendices."""
import hashlib
import io
import threading
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak

_LOCK = threading.Lock()
FONT = Path(__file__).resolve().parents[1] / 'static/fonts/NanumGothic-Regular.ttf'
FONT_SHA = '76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31'
ANALYSIS_TOPICS = {
    'overview':'프로젝트 개요', 'products':'제품 정보', 'process':'공정 흐름',
    'specifications':'설비별 사양', 'explanation':'기술 설명',
    'requirements':'주요 요구사항', 'capacity':'생산능력 분석', 'review':'기술 검토사항',
}
NOT_STATED = '원문에 명시되지 않음 — 고객 확인 필요.'
ANALYSIS_HEADINGS = (*ANALYSIS_TOPICS.values(), '사양 모순', '고객 기술질의',
                     '원본 시각자료 및 출처', '검증 및 승인')


def ordered_page_content(page):
    items=[('block',b) for b in page['blocks'] if not b.get('table')]
    items.extend(('table',t) for t in page['tables'])
    return sorted(items,key=lambda item:(item[1]['bbox'][1],item[1]['bbox'][0]))


def validate_analysis_sections(analysis, source_ids):
    sections=analysis.get('sections')
    if not isinstance(sections,list) or not sections:raise ValueError('분석 본문 누락')
    covered=set()
    for item in sections:
        if not isinstance(item,dict) or item.get('topic') not in ANALYSIS_TOPICS:
            raise ValueError('분석 필수 구성 분류 누락')
        covered.add(item['topic'])
        if any(not isinstance(item.get(k),str) or not item[k].strip() for k in ('title','kind','text')):
            raise ValueError('분석 필수 정보 누락')
        if item['kind'] not in ('customer','explanation','risk','capacity'):raise ValueError('원문/해설 구분 누락')
        refs=item.get('source_ids')
        if not isinstance(refs,list):raise ValueError('분석 출처 불일치')
        if item.get('coverage')=='not_stated':
            if refs or item['text']!=NOT_STATED:raise ValueError('원문 미명시 항목의 임의 내용 또는 출처')
        elif item.get('coverage')=='supported':
            if not refs or any(not isinstance(x,str) or x not in source_ids for x in refs):
                raise ValueError('분석 출처 불일치')
        else:raise ValueError('분석 원문 확인 상태 누락')
    if covered!=set(ANALYSIS_TOPICS):raise ValueError('분석 보고서 필수 구성 누락')


def _bookmark(paragraph, name, number):
    start = OxmlElement('w:bookmarkStart')
    start.set(qn('w:id'),str(number)); start.set(qn('w:name'),name)
    end = OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),str(number))
    paragraph._p.insert(0,start);paragraph._p.append(end)


def _link(document, text, anchor):
    paragraph = document.add_paragraph()
    link = OxmlElement('w:hyperlink');link.set(qn('w:anchor'),anchor)
    run = OxmlElement('w:r');t = OxmlElement('w:t');t.text=text;run.append(t);link.append(run);paragraph._p.append(link)


def build_reports(extraction, translated, analysis, previews, revision, verification=None):
    validate_analysis_sections(analysis,{b['id'] for p in extraction['pages'] for b in p['blocks']})
    if len(previews)!=len(extraction['pages']) or any(hashlib.sha256(image).hexdigest()!=page['preview_sha256'] for page,image in zip(extraction['pages'],previews)):
        raise ValueError('보고서 원본 시각자료의 개수 또는 해시 불일치')
    if hashlib.sha256(FONT.read_bytes()).hexdigest() != FONT_SHA:
        raise ValueError('한국어 글꼴 무결성 검사 실패')
    output = {}
    with _LOCK:
        if 'URS-Korean' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('URS-Korean', str(FONT)))
        styles = getSampleStyleSheet()
        for style in styles.byName.values():
            style.fontName='URS-Korean';style.wordWrap='CJK'
        styles.add(ParagraphStyle('ImportantKR',fontName='URS-Korean',fontSize=10,leading=16,wordWrap='CJK',backColor=colors.HexColor('#e8f3f2'),borderPadding=5,spaceAfter=7))
        styles.add(ParagraphStyle('CellKR',fontName='URS-Korean',fontSize=8,leading=12,wordWrap='CJK'))
        for kind,title in [('translation','한국어 URS 번역본'),('analysis','URS 기술 분석 보고서')]:
            word = Document()
            normal = word.styles['Normal'];normal.font.name='NanumGothic'
            normal._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'NanumGothic')
            word.add_heading(title,0)
            word.add_paragraph(f'문서 리비전 {revision} · 원본 SHA-256 {extraction["sha256"]}')
            word.add_paragraph('승인 상태와 검증 이력은 시스템의 해당 리비전 기록을 기준으로 확인하세요.')
            flow=[Paragraph(escape(title),styles['Title']),Paragraph(f'문서 리비전 {revision}',styles['Normal']),Spacer(1,12)]
            sections=[]
            if kind=='translation':
                for page in extraction['pages']:
                    sections.append((f'원문 {page["number"]}페이지',page))
            else:
                sections=[(heading,{'special':'topic','items':[s for s in analysis['sections'] if s['topic']==topic]}) for topic,heading in ANALYSIS_TOPICS.items()]
                sections.extend([('사양 모순',{'special':'conflicts'}),('고객 기술질의',{'special':'questions'})])
            for i,(heading,_) in enumerate(sections):
                anchor=f's{i}'
                _link(word,heading,anchor)
                flow.append(Paragraph(f'<link href="#{anchor}" color="#087778">{escape(heading)}</link>',styles['Normal']))
            _link(word,'원본 시각자료 및 출처','sourceappendix')
            flow.append(Paragraph('<link href="#sourceappendix" color="#087778">원본 시각자료 및 출처</link>',styles['Normal']))
            if kind=='analysis':
                _link(word,'검증 및 승인','verification')
                flow.append(Paragraph('<link href="#verification" color="#087778">검증 및 승인</link>',styles['Normal']))
            flow.append(Spacer(1,18))
            def text(value, important=False):
                paragraph=word.add_paragraph()
                paragraph.add_run(value).bold=important
                flow.append(Paragraph(escape(value).replace('\n','<br/>'),styles['ImportantKR'] if important else styles['Normal']))
                flow.append(Spacer(1,6))
            for i,(heading,data) in enumerate(sections):
                _bookmark(word.add_heading(heading,1),f's{i}',i+1)
                flow.append(Paragraph(f'<a name="s{i}"/>'+escape(heading),styles['Heading1']))
                if kind=='translation':
                    if data.get('intentionally_blank'):
                        text('원본 대조에서 확인한 빈 페이지입니다. 원본 페이지는 시각자료 부록에 보존했습니다.')
                    for item_kind,item in ordered_page_content(data):
                        if item_kind=='block':
                            text(f'[{item["id"]}] '+translated[item['id']])
                            continue
                        table=item
                        text('표 원본 출처: '+table['id'])
                        grid=table['grid']
                        if not grid or not grid[0]:
                            continue
                        cols=len(grid[0]);doc_table=word.add_table(rows=len(grid),cols=cols)
                        doc_table.style='Table Grid'
                        pdf_rows=[];seen={};spans=[]
                        for ri,row in enumerate(grid):
                            values=[]
                            for ci,cell in enumerate(row):
                                value=translated.get(cell,'') if cell not in seen else ''
                                if cell is not None and cell not in seen:seen[cell]=(ri,ci)
                                doc_table.cell(ri,ci).text=value
                                values.append(Paragraph(escape(value),styles['CellKR']))
                            pdf_rows.append(values)
                        for cell,(r0,c0) in seen.items():
                            positions=[(r,c) for r,row in enumerate(grid) for c,v in enumerate(row) if v==cell]
                            r1=max(p[0] for p in positions);c1=max(p[1] for p in positions)
                            if (r0,c0)!=(r1,c1):
                                doc_table.cell(r0,c0).merge(doc_table.cell(r1,c1));spans.append(('SPAN',(c0,r0),(c1,r1)))
                        pdf_table=Table(pdf_rows,colWidths=[480/cols]*cols)
                        pdf_table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),*spans]))
                        flow.extend([pdf_table,Spacer(1,10)])
                elif data.get('special')=='conflicts':
                    for conflict in analysis['conflicts']:
                        text(f"[{conflict['status']}] {conflict['title']}: {conflict['description']} (근거: {', '.join(conflict['source_ids'])})")
                        text('관련 대상: '+conflict['subject']);text('차이 판단 근거: '+conflict['reason'])
                        text('기술적 중요성: '+conflict['technical_impact']);text('고객 확인: '+('필요' if conflict['customer_confirmation'] else '불필요로 판단 — 직원 검토 필요'))
                    if not analysis['conflicts']:text('검토 결과에 등록된 사양 충돌 후보가 없습니다. 무모순 보장을 의미하지 않습니다.')
                elif data.get('special')=='questions':
                    for question in analysis['questions']:
                        text(question['question_ko']);text(question['question_en']);text('필요 이유: '+question['reason']+' / 근거: '+', '.join(question['source_ids']))
                    if not analysis['questions']:text('현재 등록된 고객 기술질의가 없습니다. 추가 확인이 필요 없다는 보장은 아닙니다.')
                elif data.get('special')=='topic':
                    labels={'customer':'고객 원문 요구사항','explanation':'AI 기술 해설','risk':'기술 검토사항','capacity':'생산능력 분석'}
                    for item in data['items']:
                        text(item['title']);text('구분: '+labels[item['kind']])
                        text(item['text'],item['kind'] in ('customer','risk'))
                        if item['source_ids']:text('근거: '+', '.join(item['source_ids']))
                else:
                    labels={'customer':'고객 원문 요구사항','explanation':'AI 기술 해설','risk':'기술 검토사항','capacity':'생산능력 분석'}
                    text('구분: '+labels[data['kind']]);text(data['text'],data['kind'] in ('customer','risk'));text('근거: '+', '.join(data['source_ids']))
            _bookmark(word.add_heading('원본 시각자료 및 출처',1),'sourceappendix',9999)
            flow.extend([PageBreak(),Paragraph('<a name="sourceappendix"/>원본 시각자료 및 출처',styles['Heading1'])])
            for page,image in zip(extraction['pages'],previews):
                word.add_paragraph(f'원본 {page["number"]}페이지 · 표·그림·사진·도면 전체')
                word.add_picture(io.BytesIO(image),width=Inches(6))
                ratio=page['height']/page['width'];w=min(480,660/ratio)
                flow.extend([Paragraph(f'원본 {page["number"]}페이지',styles['Heading2']),Image(io.BytesIO(image),width=w,height=w*ratio),PageBreak()])
            if kind=='analysis':
                _bookmark(word.add_heading('검증 및 승인',1),'verification',10000)
                flow.append(Paragraph('<a name="verification"/>검증 및 승인',styles['Heading1']))
                text('아래는 파일 생성 시점의 기록입니다. 이 파일 자체가 최종 승인 증명서는 아닙니다.')
                text(f'문서 리비전 {revision} / 원본 SHA-256 {extraction["sha256"]}')
                text('최종 승인: 파일 생성 시점 미완료. 최신 승인·수정 이력은 문서별 검증 기록에서 확인하세요.')
                names={'source':'원본 보관','extract':'원문 추출·검토','translate':'번역 생성','verify':'번역 독립 검증','analyze':'기술 분석','report':'보고서 출력','approval':'직원 승인'}
                for stage in (verification or {}).get('stages',[]):
                    text(names.get(stage['id'],stage['id'])+': '+('필수 검사 통과' if stage['passed'] else '미완료'))
                text('문장 의미 정확도 99% 달성 여부는 이 출력 검사만으로 입증되지 않습니다.')
                for item in analysis['sections']:
                    if item['coverage']=='not_stated':text('확인 필요: '+ANALYSIS_TOPICS[item['topic']]+' — '+NOT_STATED)
            stream=io.BytesIO();word.save(stream);output[kind+'.docx']=stream.getvalue()
            pdf=io.BytesIO();SimpleDocTemplate(pdf,title=title,rightMargin=45,leftMargin=45,topMargin=40,bottomMargin=40).build(flow)
            output[kind+'.pdf']=pdf.getvalue()
    # Reopen each output and inspect content, links and images. Visual inspection
    # is still required before employee final approval.
    for kind in ('translation','analysis'):
        docx=Document(io.BytesIO(output[kind+'.docx']))
        if len(docx.inline_shapes)!=len(extraction['pages']):raise ValueError('Word 원본 페이지 이미지 누락')
        with zipfile.ZipFile(io.BytesIO(output[kind+'.docx'])) as z:
            xml=z.read('word/document.xml')
            if b'w:hyperlink' not in xml or b'w:bookmarkStart' not in xml:raise ValueError('Word 내부 링크 누락')
        pdf=PdfReader(io.BytesIO(output[kind+'.pdf']))
        pdf_text=''.join(page.extract_text() or '' for page in pdf.pages)
        if '원본 시각자료 및 출처' not in pdf_text:raise ValueError('PDF 한국어 본문 검증 실패')
        if not any(page.get('/Annots') for page in pdf.pages):raise ValueError('PDF 개요 링크 누락')
        doc_text=''.join(p.text for p in docx.paragraphs)+''.join(cell.text for table in docx.tables for row in table.rows for cell in row.cells)
        if kind=='translation':
            for text in translated.values():
                if ''.join(text.split()) not in ''.join(doc_text.split()):raise ValueError('Word 번역 본문 누락')
                if ''.join(text.split()) not in ''.join(pdf_text.split()):raise ValueError('PDF 번역 본문 누락')
        else:
            doc_text=''.join(p.text for p in docx.paragraphs)
            for heading in ANALYSIS_HEADINGS:
                if heading not in pdf_text or heading not in doc_text:raise ValueError('분석 보고서 필수 구성 출력 누락')
            for item in analysis['sections']:
                if ''.join(item['text'].split()) not in ''.join(pdf_text.split()) or ''.join(item['text'].split()) not in ''.join(doc_text.split()):raise ValueError('Word/PDF 분석 본문 누락')
    return output


def attach_approval(outputs, record):
    """Append an approval page to reviewed bytes; never rewrite their content."""
    lines=['직원 최종 승인 기록',f'문서 {record["document"]} · 리비전 {record["revision"]}',
           '승인자: '+record['reviewer'],'승인 시각(KST): '+record['approved_at_kst'],
           '검토 근거: '+record['note'],'원본 SHA-256: '+record['source_sha256'],
           '이 기록은 앞선 본문 생성 시점의 미승인 표시 이후에 부여된 최종 승인입니다.',
           '전자서명이 아니며, 이후 수정 시 해당 리비전의 승인본 제공은 차단됩니다.']
    final={}
    with _LOCK:
        if hashlib.sha256(FONT.read_bytes()).hexdigest()!=FONT_SHA:raise ValueError('한국어 글꼴 무결성 검사 실패')
        if 'URS-Korean' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('URS-Korean',str(FONT)))
        style=ParagraphStyle('ApprovalKR',fontName='URS-Korean',fontSize=10,leading=16,wordWrap='CJK')
        for kind,payload in outputs.items():
            content=[*lines,'직원이 검토한 본문 파일 SHA-256: '+hashlib.sha256(payload).hexdigest()]
            if kind.endswith('.docx'):
                doc=Document(io.BytesIO(payload));doc.add_page_break()
                doc.add_heading(content[0],1)
                for value in content[1:]:doc.add_paragraph(value)
                stream=io.BytesIO();doc.save(stream);data=stream.getvalue()
                reopened=Document(io.BytesIO(data))
                if len(reopened.inline_shapes)!=len(Document(io.BytesIO(payload)).inline_shapes):raise ValueError('승인본 Word 이미지 누락')
                text=''.join(p.text for p in reopened.paragraphs)
            else:
                stream=io.BytesIO()
                SimpleDocTemplate(stream,rightMargin=45,leftMargin=45).build([Paragraph(escape(value).replace('\n','<br/>'),style) for value in content])
                original_reader=PdfReader(io.BytesIO(payload))
                appendix_reader=PdfReader(io.BytesIO(stream.getvalue()))
                writer=PdfWriter(clone_from=original_reader);writer.append(appendix_reader)
                result=io.BytesIO();writer.write(result);data=result.getvalue()
                reopened=PdfReader(io.BytesIO(data));original=PdfReader(io.BytesIO(payload))
                if len(reopened.pages)<=len(original.pages):raise ValueError('승인 기록 페이지 누락')
                for a,b in zip(original.pages,reopened.pages):
                    if a.extract_text()!=b.extract_text() or len(a.images)!=len(b.images):raise ValueError('승인본 원래 본문 불일치')
                    if len(a.get('/Annots',[]))!=len(b.get('/Annots',[])):raise ValueError('승인본 원래 개요 링크 누락')
                text=''.join(p.extract_text() or '' for p in reopened.pages)
            if any(''.join(value.split()) not in ''.join(text.split()) for value in content):raise ValueError('승인 기록 출력 누락')
            final['final-'+kind]=data
    return final

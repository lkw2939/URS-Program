"""Library-based PDF extraction with page renders and explicit uncertainty."""
import hashlib
import io
import threading

import pdfplumber
import pypdfium2 as pdfium

_RENDER_LOCK = threading.Lock()  # PDFium is not safe for concurrent rendering.
MAX_PAGES = 100
MAX_PIXELS = 12_000_000


def extract_pdf(payload):
    pages, previews, warnings = [], [], []
    with _RENDER_LOCK:
        rendered = pdfium.PdfDocument(payload)
        try:
            with pdfplumber.open(io.BytesIO(payload)) as document:
                if len(document.pages) > MAX_PAGES:
                    raise ValueError('100페이지를 초과한 PDF는 현재 처리 범위를 벗어납니다.')
                for index, page in enumerate(document.pages):
                    width, height = float(page.width), float(page.height)
                    if width <= 0 or height <= 0 or width * height * 4 > MAX_PIXELS:
                        raise ValueError('페이지 렌더링 크기 제한을 초과했습니다.')
                    blocks = []
                    for n, line in enumerate(page.extract_text_lines(layout=False, strip=True, return_chars=False)):
                        blocks.append({'id': f'p{index+1}-b{n+1}', 'page': index + 1,
                                       'text': line['text'], 'bbox': [float(line[k]) for k in ('x0','top','x1','bottom')]})
                    if not blocks:
                        warnings.append({'page': index + 1, 'reason': '문자층 없음: 스캔·빈 페이지의 사람 확인/OCR 필요'})
                    tables = []
                    for ti, table in enumerate(page.find_tables()):
                        cells = []
                        for ci, bbox in enumerate(table.cells):
                            if bbox is not None:
                                cells.append({'id': f'p{index+1}-t{ti+1}-c{ci+1}', 'bbox': list(map(float,bbox)),
                                              'text': page.crop(bbox).extract_text() or ''})
                        xs = sorted({c['bbox'][n] for c in cells for n in (0,2)})
                        ys = sorted({c['bbox'][n] for c in cells for n in (1,3)})
                        grid = []
                        for y0, y1 in zip(ys, ys[1:]):
                            row = []
                            for x0, x1 in zip(xs, xs[1:]):
                                midx, midy = (x0+x1)/2, (y0+y1)/2
                                hits = [c['id'] for c in cells if c['bbox'][0] <= midx <= c['bbox'][2] and c['bbox'][1] <= midy <= c['bbox'][3]]
                                row.append(hits[0] if len(hits) == 1 else None)
                            grid.append(row)
                        tables.append({'id': f'p{index+1}-t{ti+1}', 'bbox': list(map(float,table.bbox)),
                                       'cells': cells, 'grid': grid, 'text_grid': table.extract()})
                        if any(cell is None for row in grid for cell in row):
                            warnings.append({'page': index+1, 'reason': '표의 셀 연결 불확실'})
                    images = [{'bbox': [float(image[k]) for k in ('x0','top','x1','bottom')],
                               'name': str(image.get('name',''))} for image in page.images]
                    if images:
                        warnings.append({'page': index+1, 'reason': '그림 내부 문자·설명 확인 필요'})
                    source_lines = list(blocks)
                    if tables:
                        def in_table(block):
                            x0,y0,x1,y1 = block['bbox']
                            return any(t['bbox'][0] <= (x0+x1)/2 <= t['bbox'][2] and
                                       t['bbox'][1] <= (y0+y1)/2 <= t['bbox'][3] for t in tables)
                        blocks = [b for b in blocks if not in_table(b)]
                        for table in tables:
                            for cell in table['cells']:
                                if cell['text'].strip():
                                    blocks.append({'id':cell['id'], 'page':index+1, 'text':cell['text'], 'bbox':cell['bbox'], 'table':table['id']})
                    pdf_page = rendered[index]
                    bitmap = pdf_page.render(scale=1.5)
                    try:
                        out = io.BytesIO()
                        bitmap.to_pil().save(out, format='PNG')
                        preview = out.getvalue()
                    finally:
                        bitmap.close()
                        pdf_page.close()
                    previews.append(preview)
                    if sum(map(len,previews)) > 64*1024*1024:
                        raise ValueError('페이지 미리보기 저장 한도를 초과했습니다.')
                    pages.append({'number': index+1, 'width': width, 'height': height, 'blocks': blocks,
                                  'source_lines': source_lines, 'tables': tables, 'images': images,
                                  'blank_candidate': not page.chars and not page.images and not page.lines and not page.rects and not page.curves,
                                  'preview_sha256': hashlib.sha256(preview).hexdigest()})
        finally:
            rendered.close()
    return {'pages': pages, 'warnings': warnings, 'sha256': hashlib.sha256(payload).hexdigest(),
            'coverage': 'NEEDS_REVIEW' if warnings else 'UNVERIFIED'}, previews

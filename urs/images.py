"""Crop only PDF visual regions; never read, OCR, or persist source text."""
import base64
import hashlib
import io
import threading
from html.parser import HTMLParser
import re
import pdfplumber
import pypdfium2 as pdfium

_LOCK = threading.Lock()


def crop_images(payload):
    assets = []
    with _LOCK, pdfplumber.open(io.BytesIO(payload)) as pdf:
        if len(pdf.pages) > 100:
            raise ValueError('PDF는 최대 100페이지입니다.')
        rendered = pdfium.PdfDocument(payload)
        try:
            for number, page in enumerate(pdf.pages, 1):
                w, h = float(page.width), float(page.height)
                if w <= 0 or h <= 0 or w*h*4 > 12_000_000:
                    raise ValueError('페이지 렌더링 크기 제한을 초과했습니다.')
                def box(item):
                    return [max(0.,float(item['x0'])), max(0.,float(item['top'])),
                            min(w,float(item['x1'])), min(h,float(item['bottom']))]
                boxes = [box(item) for item in page.images]
                # Group connected vector paths into diagram regions, without text.
                vectors = [box(item) for item in [*page.curves,*page.lines,*page.rects]]
                groups = []
                for b in vectors:
                    if any(a[0]<=b[0] and a[1]<=b[1] and a[2]>=b[2] and a[3]>=b[3] for a in boxes):
                        continue
                    group = b
                    while True:
                        hits = [a for a in groups if a[0]<=group[2]+4 and a[2]>=group[0]-4 and a[1]<=group[3]+4 and a[3]>=group[1]-4]
                        if not hits: break
                        for a in hits:
                            groups.remove(a)
                            group = [min(a[0],group[0]),min(a[1],group[1]),max(a[2],group[2]),max(a[3],group[3])]
                    groups.append(group)
                boxes += [b for b in groups if b[2]-b[0]>=8 and b[3]-b[1]>=8]
                boxes = sorted({tuple(b) for b in boxes if b[2]>b[0] and b[3]>b[1]},key=lambda b:(b[1],b[0],b[3],b[2]))
                if not boxes: continue
                pdfpage = rendered[number-1]
                bitmap = pdfpage.render(scale=1.5)
                try:
                    image = bitmap.to_pil()
                    sx,sy = image.width/w,image.height/h
                    for index,b in enumerate(boxes,1):
                        crop=image.crop((int(b[0]*sx),int(b[1]*sy),min(image.width,int(b[2]*sx+0.999)),min(image.height,int(b[3]*sy+0.999))))
                        out=io.BytesIO();crop.save(out,format='PNG');crop.close()
                        data=out.getvalue()
                        assets.append({'uri':f'urs-image:{number}:{index}','page':number,'index':index,'bbox':list(b),
                                       'sha256':hashlib.sha256(data).hexdigest(), 'data_url':'data:image/png;base64,'+base64.b64encode(data).decode()})
                        if sum(len(a['data_url']) for a in assets)>90*1024*1024:
                            raise ValueError('원본 그림 저장 한도를 초과했습니다.')
                finally:
                    bitmap.close();pdfpage.close()
        finally:
            rendered.close()
    return assets


class ImageSlots(HTMLParser):
    def __init__(self, html, prefix="urs-image:"):
        super().__init__(convert_charrefs=False)
        self.html=html;self.slots=[];self.prefix=prefix
        self.lines=[0]
        self.lines.extend(m.end() for m in re.finditer('\n',html))
        self.feed(html);self.close()

    def handle_starttag(self, tag, attrs):
        if tag not in ('img','image','source'): return
        raw=self.get_starttag_text()
        line,col=self.getpos();offset=self.lines[line-1]+col
        # Lex attributes only inside the exact original start tag. Do not serialize HTML.
        token=re.compile(r'''([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?''')
        for match in token.finditer(raw, len(tag)+1):
            if match.group(1).lower() not in ('src','href','xlink:href'):continue
            group=next((g for g in (2,3,4) if match.group(g) is not None),None)
            if group is None:continue
            uri=match.group(group)
            if uri.startswith(self.prefix):
                self.slots.append((offset+match.start(group),offset+match.end(group),uri))

    handle_startendtag=handle_starttag


def bind_images(raw, assets):
    mapping={a['uri']:a['data_url'] for a in assets}
    changes=[];missing=[];final=raw
    slots=ImageSlots(raw).slots
    for start,end,uri in reversed(slots):
        if uri not in mapping:
            missing.append({'uri':uri,'offset':start});continue
        final=final[:start]+mapping[uri]+final[end:]
        changes.append({'uri':uri,'start':start,'end':end,'replacement_sha256':hashlib.sha256(mapping[uri].encode()).hexdigest()})
    return final, {'replacements':list(reversed(changes)),'unresolved':list(reversed(missing)),
                   'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'final_sha256':hashlib.sha256(final.encode()).hexdigest(),
                   'only_image_addresses_changed':True}

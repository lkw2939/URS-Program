"""Reopen generated Word files in LibreOffice, then inspect the exported PDFs."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from pypdf import PdfReader
import pypdfium2 as pdfium
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urs.reports import ANALYSIS_HEADINGS

ROOT=Path(__file__).resolve().parents[1]


def main():
    evidence=ROOT/'docs/evidence';out=evidence/'word-rendered';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        config=base/'fonts.conf'
        config.write_text(f'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir>{ROOT}/static/fonts</dir><cachedir>{base}/fontcache</cachedir></fontconfig>')
        env={**os.environ,'FONTCONFIG_FILE':str(config),'XDG_CACHE_HOME':str(base/'cache')}
        variants=[(status,kind) for status in ('draft','final') for kind in ('translation','analysis')]
        files=[evidence/f'synthetic-{status}-{kind}.docx' for status,kind in variants]
        for status,kind in variants:
            (out/f'synthetic-{status}-{kind}.pdf').unlink(missing_ok=True)
        subprocess.run(['soffice',f'-env:UserInstallation={base.as_uri()}/lo','--headless','--convert-to','pdf','--outdir',str(out),*[str(p) for p in files]],env=env,check=True,timeout=90,capture_output=True)
    for status,kind in variants:
        path=out/f'synthetic-{status}-{kind}.pdf';pdf=PdfReader(path)
        text=''.join(page.extract_text() or '' for page in pdf.pages)
        assert '원본 시각자료 및 출처' in text
        if kind=='translation':assert all(value in text for value in ('120','165','160','600','60','AB-12'))
        else:
            compact=''.join(text.split())
            for heading in ANALYSIS_HEADINGS:assert ''.join(heading.split()) in compact,heading
            assert '최종승인:파일생성시점미완료' in compact
        if status=='final':
            assert '직원최종승인기록' in ''.join(text.split())
            assert '승인자:pipeline-test' in ''.join(text.split())
        assert sum(len(page.images) for page in pdf.pages)>=2
        links=[ref.get_object() for page in pdf.pages for ref in page.get('/Annots',[]) if ref.get_object().get('/Subtype')=='/Link']
        assert links
        for link in links:
            assert link.get('/Dest') or link.get('/A',{}).get('/D'), 'internal link target missing'
        rendered=pdfium.PdfDocument(str(path))
        for i in range(len(rendered)):
            page=rendered[i];bitmap=page.render(scale=1.2)
            bitmap.to_pil().save(out/f'{kind if status=="draft" else "final-"+kind}-page-{i+1}.png');bitmap.close();page.close()
        rendered.close()
        print(f'PASS: LibreOffice reopened {status}-{kind}.docx; {len(pdf.pages)} PDF pages, Korean text, original images and internal links present.')
    print('Scope: synthetic documents; these artifacts do not establish real customer/AI accuracy.')


if __name__=='__main__':main()

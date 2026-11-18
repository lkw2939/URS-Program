"""Versioned cleanup of the obsolete PDF-picker image loader, never report prose/layout."""
import hashlib,re
VERSION='embedded-image-presentation-v1'
def digest(text):return hashlib.sha256(text.encode()).hexdigest()
def prepare(raw):
    text=raw;changes=[]
    # Only the recognized legacy loader is eligible. Unknown designs remain audit-blocked.
    legacy=bool(re.search(r'\bid\s*=\s*[\"\']pdf-file[\"\']',raw,re.I) and re.search(r'pdfjsLib|pdf\.min\.js',raw,re.I))
    if legacy:
        def aside(m):
            value=m.group()
            if not re.search(r'<input\b[^>]*\bid\s*=\s*[\"\']pdf-file[\"\']',value,re.I) or re.search(r'<(?:img|table|section|figure)\b',value,re.I):return value
            changes.append('remove_pdf_picker');return ''
        text=re.sub(r'<aside\b[^>]*\bclass=[\"\']toolbar[\"\'][^>]*>.*?</aside>',aside,text,flags=re.S|re.I)
        def script(m):
            value=m.group()
            if not re.search(r'pdfjsLib|pdf\.min\.js|pdf\.worker',value,re.I):return value
            changes.append('remove_pdf_loader_script');return ''
        text=re.sub(r'<script\b[^>]*>.*?</script\s*>',script,text,flags=re.S|re.I)
        def status(m):changes.append('remove_image_picker_placeholder');return ''
        text=re.sub(r'<(?:span|div)\b[^>]*\bclass=[\"\']figure-status[\"\'][^>]*>[^<]*</(?:span|div)>',status,text,flags=re.I)
        # Change visibility declarations of img selectors only. Do not touch sizes/positions.
        def style(m):
            def rule(r):
                selector,body=r.group(1),r.group(2)
                if not all(re.fullmatch(r'\.figure\s+img(?:\.ready)?',part.strip()) for part in selector.split(',')):return r.group()
                fixed=re.sub(r'(?<![-\w])display\s*:\s*none\b','display: block',body,flags=re.I)
                fixed=re.sub(r'(?<![-\w])visibility\s*:\s*(?:hidden|collapse)\b','visibility: visible',fixed,flags=re.I)
                fixed=re.sub(r'(?<![-\w])opacity\s*:\s*0(?:\.0+)?(?=\s*(?:!important)?\s*[;}])','opacity: 1',fixed+'}',flags=re.I)[:-1]
                if fixed!=body:changes.append('enable_embedded_img_visibility')
                return selector+'{'+fixed+'}'
            return m.group(1)+re.sub(r'([^{}]+)\{([^{}]*)\}',rule,m.group(2))+m.group(3)
        text=re.sub(r'(<style\b[^>]*>)(.*?)(</style\s*>)',style,text,flags=re.S|re.I)
        # Remove outer Markdown wrappers only; never manufacture a closing HTML tag.
        if re.match(r'\A\s*```html\s*\n\s*<!doctype html>',text,re.I) and re.search(r'</html>\s*```\s*\Z',text,re.I):
            text=re.sub(r'\A\s*```html\s*\n','',text,flags=re.I);text=re.sub(r'\n?```\s*\Z','',text);changes.append('remove_outer_markdown_fences')
    receipt={'version':VERSION,'changed':text!=raw,'raw_sha256':digest(raw),'prepared_sha256':digest(text),'changes':changes,'body_tables_captions_and_image_addresses_preserved':True}
    return text,receipt

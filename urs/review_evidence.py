"""Reproduce the HTML transport copy against its recorded request hash; no API calls."""
import hashlib,re
from urs.images import ImageSlots

def sha(text):return hashlib.sha256(text.encode()).hexdigest()
def hidden_css(text):
    # Presence of a declaration is not proof that a matching image was hidden at runtime.
    return len(re.findall(r'display\s*:\s*none\b|visibility\s*:\s*hidden\b|opacity\s*:\s*0(?:\.0+)?\s*[;}!]',text,re.I))
def mask(text,prefix):
    cursor=0;parts=[]
    for start,end,_ in ImageSlots(text,prefix).slots:parts.extend([text[cursor:start],'<IMAGE_ADDRESS>']);cursor=end
    return ''.join(parts)+text[cursor:]
def compare(staff,manifest):
    result={'staff_html_sha256':sha(staff),'staff_embedded_images':len(ImageSlots(staff,'data:image/').slots),'staff_unresolved_slots':len(ImageSlots(staff).slots),'staff_hidden_declarations':hidden_css(staff),'request_copy_verified':False,'only_image_addresses_changed':None,'css_unchanged':None,'reason':'이 결과에는 실제 검증 사본의 해시 기록이 없어 전송 당시 상태는 미확인입니다.'}
    if not manifest or not manifest.get('html_text'):return result
    try:
        from urs.costing import review_parts
        copy=review_parts('independent_verify',staff)[1]['text']
        result['recorded_review_html_sha256']=manifest['html_text']['sha256']
        if sha(copy)!=manifest['html_text']['sha256']:
            result['reason']='저장 HTML로 재현한 사본과 실제 전송 해시가 다릅니다. 전송 당시 사본을 확정할 수 없습니다.';return result
        addresses_only=mask(staff,'data:image/')==mask(copy,'urs-review-image:')
        result.update(request_copy_verified=True,only_image_addresses_changed=addresses_only,css_unchanged=addresses_only,review_hidden_declarations=hidden_css(copy),review_image_references=len(ImageSlots(copy,'urs-review-image:').slots),reason='실제 요청의 HTML 해시와 재현한 검증 사본이 일치합니다.')
    except Exception:result['reason']='저장된 이미지 또는 전송 자료를 대조하지 못했습니다. 발생 위치는 미확인입니다.'
    return result

def explanation(item,comparison):
    lines=[]
    if comparison['staff_unresolved_slots']:lines.append('직원용 HTML에 연결되지 않은 원본 그림 주소가 '+str(comparison['staff_unresolved_slots'])+'개 남아 있습니다. 보고서의 이미지 연결 문제이며 번역문 수정 대상이 아닙니다.')
    if comparison['staff_hidden_declarations']:lines.append('숨김 CSS 선언은 직원용 HTML에도 있습니다. 실제 사진에 적용되는지는 화면 표시 검사로 확인해야 합니다.')
    if comparison['request_copy_verified'] and comparison['only_image_addresses_changed']:
        lines.append('직원용 HTML과 실제 검증 사본은 그림 주소만 다르고 본문·CSS는 같습니다. urs-review-image:는 검증용 식별자이며 직원용 이미지의 누락을 뜻하지 않습니다.')
        if not comparison['staff_hidden_declarations'] and re.search(r'display\s*:\s*none|숨김',item['problem']+' '+item['title'],re.I):lines.append('지적한 숨김 선언은 이 저장 HTML에서 확인되지 않았습니다. AI의 지적을 확정 오류로 처리하지 않습니다.')
    else:lines.append(comparison['reason'])
    return lines

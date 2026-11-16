"""Known synthetic URS content; not a customer accuracy evaluation corpus."""
import io
import copy
from reportlab.pdfgen import canvas

TRANSLATIONS = {
 'RQ-01 The conveyor shall not operate when the safety guard is open.':'RQ-01 안전 가드가 열려 있을 때 컨베이어는 작동해서는 안 됩니다.',
 'RQ-02 Minimum speed 120 packs/min.':'RQ-02 최소 속도는 120 packs/min입니다.',
 'Product':'제품', 'Length (mm)':'길이 (mm)', 'AB-12':'AB-12','165':'165',
 'RQ-03 Produk harus dihentikan jika pelindung terbuka.':'RQ-03 가드가 열리면 제품을 정지해야 합니다.',
 'RQ-04 AB-12 length is 160 mm.':'RQ-04 AB-12 길이는 160 mm입니다.',
 'RQ-05 Sorting speed 600 sachets/min; wrapping 60 packs/min.':'RQ-05 정렬 속도는 600 sachets/min이며 포장 속도는 60 packs/min입니다.',
}


def urs_pdf():
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=(612,792))
    c.setFont('Helvetica',10)
    c.drawString(40,750,list(TRANSLATIONS)[0]);c.drawString(40,730,list(TRANSLATIONS)[1])
    for x in (40,200,360):c.line(x,600,x,680)
    for y in (600,640,680):c.line(40,y,360,y)
    c.drawString(48,655,'Product');c.drawString(208,655,'Length (mm)')
    c.drawString(48,615,'AB-12');c.drawString(208,615,'165')
    c.showPage();c.setFont('Helvetica',10)
    c.drawString(40,750,'RQ-03 Produk harus dihentikan jika pelindung terbuka.')
    c.drawString(40,730,'RQ-04 AB-12 length is 160 mm.')
    c.drawString(40,710,'RQ-05 Sorting speed 600 sachets/min; wrapping 60 packs/min.')
    c.save();return out.getvalue()


class FixtureAI:
    """Test transport with known responses; never registered in app startup."""
    def __init__(self, wrong_number=False, persistent_failure=False):
        self.calls=[];self.wrong_number=wrong_number;self.persistent_failure=persistent_failure

    def call(self, task, data, images=()):
        self.calls.append(task)
        if task in ('translate','correct_translation'):
            pairs=[]
            for block in data['blocks']:
                text=TRANSLATIONS[block['text']]
                if self.wrong_number and '120' in text and (task=='translate' or self.persistent_failure):text=text.replace('120','102')
                pairs.append({'id':block['id'],'text':text})
            return {'translations':pairs}
        if task=='independent_verify':
            return {'checks':[{'id':p['id'],'status':'FAIL' if ('120' in p['source'] and '102' in p['translation']) else 'PASS','reason':'수치 불일치' if '102' in p['translation'] else '합성 정답 대조'} for p in data['pairs']]}
        if task=='analyze':
            blocks=data['source'];first=next(b['id'] for b in blocks if b['text']=='165');second=next(b['id'] for b in blocks if '160 mm' in b['text'])
            speed=next(b['id'] for b in blocks if '600 sachets' in b['text'])
            sections=[
                {'topic':'overview','title':'고객사·공장 확인','kind':'customer','coverage':'not_stated','text':'원문에 명시되지 않음 — 고객 확인 필요.','source_ids':[]},
                {'topic':'products','title':'제품 AB-12','kind':'customer','coverage':'supported','text':'제품 AB-12의 길이는 표에서 165 mm로 제시됩니다.','source_ids':[first]},
                {'topic':'process','title':'정렬 및 포장','kind':'customer','coverage':'supported','text':'정렬과 포장 공정의 속도가 제시됩니다. 연결 순서는 원문 추가 확인이 필요합니다.','source_ids':[speed]},
                {'topic':'specifications','title':'AB-12 사양','kind':'customer','coverage':'supported','text':'AB-12 길이 160 mm와 표의 165 mm는 같은 기준인지 확인이 필요합니다.','source_ids':[first,second]},
                {'topic':'explanation','title':'안전 가드 해설','kind':'explanation','coverage':'supported','text':'안전 가드 개방 시 컨베이어 작동 금지 요구는 가드 상태와 작동 허용을 연결합니다.','source_ids':[blocks[0]['id']]},
                {'topic':'requirements','title':'안전 요구사항','kind':'customer','coverage':'supported','text':TRANSLATIONS[blocks[0]['text']],'source_ids':[blocks[0]['id']]},
                {'topic':'capacity','title':'생산능력 확인','kind':'capacity','coverage':'supported','text':'600 sachets/min과 60 packs/min은 처리 단위가 다릅니다. 팩당 수량이 없어 직접 비교할 수 없습니다.','source_ids':[speed]},
                {'topic':'review','title':'치수 기준 검토','kind':'risk','coverage':'supported','text':'길이의 기준 차이를 확인한 후 설계에 적용해야 합니다.','source_ids':[first,second]},
            ]
            sections.insert(0,sections.pop(5))
            return {'sections':sections,
                    'conflicts':[{'title':'AB-12 길이 확인','status':'potential','description':'원문 표의 165 mm와 다른 페이지의 160 mm가 같은 치수 기준인지 확인이 필요합니다.','subject':'제품 AB-12','reason':'같은 제품 길이에 서로 다른 값이 있습니다. 내외측 치수 등 기준 차이는 불명확합니다.','technical_impact':'제품 길이 기준이 달라지면 이송·포장 설계의 기준 치수에 영향을 줍니다.','customer_confirmation':True,'source_ids':[first,second]}],
                    'questions':[{'question_ko':'AB-12의 최종 길이 기준을 확인해 주세요.','question_en':'Please confirm the final AB-12 length specification.','reason':'165 mm와 160 mm의 기준이 다를 수 있습니다.','source_ids':[first,second]}]}
        if task=='independent_document_verify':return {'status':'PASS','issues':[]}
        if task=='independent_analysis_verify':return {'status':'PASS','issues':[]}
        if task=='dialogue':
            if '보고서' in data['message'] and data.get('analysis'):
                proposal=copy.deepcopy(data['analysis'])
                proposal['sections'][0]['text']='안전 가드가 열리면 컨베이어가 작동하지 않도록 해야 한다는 고객 요구입니다.'
                return {'reply':'보고서 설명 수정안입니다. 적용 후 독립 재검증이 필요합니다.','changes':[],'source_ids':proposal['sections'][0]['source_ids'],'analysis_proposal':proposal}
            first=next(p for p in data['source'] if '120 packs' in p['text'])
            return {'reply':'원문 RQ-02의 최소 속도는 120 packs/min입니다.','changes':[{'id':first['id'],'text':TRANSLATIONS[first['text']]}],'source_ids':[first['id']]}
        raise AssertionError('unexpected task '+task)

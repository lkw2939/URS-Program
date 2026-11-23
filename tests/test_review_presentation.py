"""Categorization and request-copy provenance without inference or customer data."""
import hashlib,unittest
from html_fixtures import RAW,visual_pdf
from urs.images import crop_images,bind_images
from urs.review_results import issues,plan_changes
from urs.review_evidence import compare,explanation
from urs.costing import review_parts
class ReviewPresentationTests(unittest.TestCase):
 def test_translation_ambiguity_and_program_are_distinct(self):
  rows=issues({'issues':[{'page':7,'severity':'오류','category':'source_ambiguity','reason':'원문은 4시간과 2시간의 관계가 불명확합니다.','before':'4시간','after':'2시간'}, {'page':1,'severity':'오류','category':'quantity','issue_type':'translation','reason':'원문은 무엇이 5개인지 밝히지 않았지만 번역은 완제품 5개로 확정했습니다.','before':'완제품 5개','after':'5개(대상 확인 필요)'}, {'page':1,'severity':'오류','reason':'urs-review-image: 주소와 display:none 문제','before':'본문','after':'변경'}]})
  by={r['id']:r for r in rows};self.assertEqual([by[str(i)]['kind'] for i in range(3)],['review','error','program']);self.assertIn('4시간',by['0']['question']);self.assertIn('2시간',by['0']['question']);self.assertFalse(by['0']['can_propose']);self.assertFalse(by['2']['can_propose']);self.assertTrue(by['1']['can_propose'])
 def test_missing_fields_are_empty_not_invented(self):
  r=issues({'issues':[{'page':1,'severity':'오류','title_ko':'같은 설명','problem_ko':'같은 설명','source_en':'  \n ','before':'','after':''}]})[0]
  self.assertEqual(r['problem'],'');self.assertEqual(r['why'],'');self.assertEqual(r['source_en'],'');self.assertEqual(r['how'],'');self.assertEqual(issues({'issues':[{'before':'없음','after':'있음','source_en':'[]'}]})[0]['before'],'없음');self.assertEqual(issues({'issues':[{'source_en':'[]'}]})[0]['source_en'],'')
 def test_both_pages_need_quotes(self):
  r=issues({'issues':[{'page':12,'pages':[12,16,17],'evidence':[{'page':12,'source_en':'Existing unit.'},{'page':16,'source_en':'New unit.'},{'page':17,'source_en':' '}]}]},25)[0]
  self.assertEqual(r['pages'],[12,16]);self.assertEqual(r['pending_pages'],[17]);self.assertEqual(len(r['references']),2)
 def test_out_of_range_pages_not_promoted(self):
  r=issues({'issues':[{'page':12,'evidence':[{'page':16,'source_en':'quote'}]}]},7)[0];self.assertEqual(r['pages'],[]);self.assertFalse(r['can_propose'])
 def test_actual_copy_hash_distinguishes_transport_labels(self):
  staff=bind_images(RAW,crop_images(visual_pdf()))[0];copy=review_parts('independent_verify',staff)[1]['text'];m={'html_text':{'sha256':hashlib.sha256(copy.encode()).hexdigest()}}
  d=compare(staff,m);self.assertTrue(d['request_copy_verified']);self.assertTrue(d['only_image_addresses_changed']);self.assertTrue(d['css_unchanged']);self.assertEqual(d['staff_embedded_images'],2);self.assertEqual(d['staff_unresolved_slots'],1)
 def test_old_or_different_request_not_falsely_verified(self):
  self.assertFalse(compare(RAW,None)['request_copy_verified']);self.assertFalse(compare(RAW,{'html_text':{'sha256':'wrong'}})['request_copy_verified'])
 def test_hidden_css_located_in_staff_and_transport_copy(self):
  staff=bind_images(RAW.replace('</style>','img{display:none}</style>'),crop_images(visual_pdf()))[0];copy=review_parts('independent_verify',staff)[1]['text'];d=compare(staff,{'html_text':{'sha256':hashlib.sha256(copy.encode()).hexdigest()}})
  self.assertEqual(d['staff_hidden_declarations'],1);self.assertEqual(d['review_hidden_declarations'],1);self.assertIn('직원용 HTML에도', ' '.join(explanation({'problem':'숨김 CSS','title':'점검'},d)))
 def test_delete_with_replacement_is_rejected(self):
  with self.assertRaises(ValueError):plan_changes('<html><body><p>원래 문장</p></body></html>',[{'id':'0','page':1,'can_propose':True}],[{'issue_id':'0','before':'원래 문장','after':'수정문','delete':True}],single_page=True)

class CustomerPolicyTests(unittest.TestCase):
 def test_customer_only_passes_but_translation_unknown_and_program_still_block(self):
  from urs.review_policy import decision
  customer={'page':7,'issue_type':'customer','severity':'오류','reason':'원문에 4시간과 2시간이 함께 있어 적용 기준 확인 필요'}
  for status in ('FAIL','NEEDS_REVIEW','PASS'):
   body={'status':status,'issues':[customer]};self.assertEqual(decision(body)['status'],'PASS');self.assertEqual(body['status'],status)
  for blocking in ({'severity':'오류','issue_type':'translation','reason':'수치 오역'}, {'severity':'확인 필요','reason':'번역 근거 부족'}, {'issue_type':'program','reason':'사진이 숨겨짐'}, {'category':'source_ambiguity','issue_type':'translation','reason':'원문은 모호하지만 번역은 단정'}):
   self.assertNotEqual(decision({'status':'NEEDS_REVIEW','issues':[customer,blocking]})['status'],'PASS')
  self.assertEqual(decision({'status':'FAIL','issues':[]})['status'],'FAIL')
 def test_customer_question_is_not_lost_or_duplicated_in_analysis(self):
  from urs.review_policy import decision,analysis_body
  body={'status':'NEEDS_REVIEW','issues':[{'page':1,'category':'source_conflict','question_ko':'어떤 시험 기준을 적용하나요?','reason':'원문에 두 기준이 있습니다.'}]}
  findings=decision(body)['customer_findings'];analysis={'status':'PASS','issues':[],'questions':[{'question_ko':'어떤 시험 기준을 적용하나요?'}]}
  self.assertEqual(len(analysis_body(analysis,findings)['questions']),1)
  analysis['questions']=[];self.assertEqual(len(analysis_body(analysis,findings)['questions']),1);self.assertEqual(analysis['questions'],[])


class BroaderTextEditTests(unittest.TestCase):
 def test_inline_formatting_is_preserved_and_only_selected_text_changes(self):
  from urs.review_results import replay,TextRanges,decoded_map
  source='<html><head><style>b{color:blue}</style></head><body><section data-urs-page="1"><p>고객은 <strong>반드시</strong> 시험합니다.</p><a href="mailto:a@example.com">메일</a><img src="data:image/png;base64,AAAA"></section></body></html>'
  patch=plan_changes(source,[{'id':'0','page':1,'can_propose':True}],[{'issue_id':'0','before':'고객은 반드시 시험합니다.','after':'고객의 시험을 권장합니다.'}])
  final=replay(source,patch);visible=''.join(decoded_map(final[a:b])[0] for a,b,_ in TextRanges(final).ranges)
  self.assertIn('고객의 시험을 권장합니다.',visible);self.assertIn('<strong>',final);self.assertIn('</strong>',final);self.assertIn('href="mailto:a@example.com"',final);self.assertIn('<style>b{color:blue}</style>',final);self.assertIn('src="data:image/png;base64,AAAA"',final)
 def test_repeated_phrase_requires_an_explicit_occurrence(self):
  from urs.review_results import replay
  source='<html><body><section data-urs-page="1"><p>반복</p><p>반복</p></section></body></html>';entries=[{'id':'0','page':1,'can_propose':True}]
  patch=plan_changes(source,entries,[{'issue_id':'0','page':1,'before':'반복','after':'수정','occurrence':2}]);self.assertIn('<p>반복</p><p>수정</p>',replay(source,patch))
 def test_email_character_issue_allows_confirmed_text_edit_but_css_does_not(self):
  rows=issues({'issues':[{'page':3,'issue_type':'program','reason':'이메일 표시 문자열에 폭이 없는 문자가 있습니다.'},{'page':3,'issue_type':'program','reason':'그림이 숨김 CSS로 보이지 않습니다.'}]})
  by={r['id']:r for r in rows};self.assertTrue(by['0']['can_manual']);self.assertFalse(by['1']['can_manual']);self.assertFalse(by['0']['can_propose'])

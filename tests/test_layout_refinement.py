"""Model-owned layout: preserve text/URIs, one refinement, cost/response failure safety."""
import io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.workspace import Workspace
from urs.images import bind_images,crop_images
from urs.layout_refinement import preserved
GOOD=RAW.replace('src=urs-image:9:8','src=urs-image:1:1')
BAD=GOOD.replace('width:210mm','width:260mm').replace('</style>','img{display:none}</style>')
class Refiner(ReportAI):
 def __init__(self,raw=BAD,reply=GOOD):super().__init__(raw);self.reply=reply;self.refinements=[]
 def refine_report_html(self,*args):self.refinements.append(args);return self.reply
class RefinementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'fixture.sqlite');self.w.add_user('a','fixture-password-123');project=self.w.create_project('a','fixture');self.doc=self.w.upload('a',project,'source.pdf',visual_pdf());self.w.save_report_settings('a',PROMPT)
 def run_report(self,provider):self.w.processing.provider=provider;return self.w.run('a',self.doc,'report')
 def test_refined_model_html_is_saved_with_only_image_addresses_changed(self):
  provider=Refiner();self.run_report(provider);self.assertEqual(len(provider.refinements),1);args=provider.refinements[0];self.assertEqual(args[0],self.w.original('a',self.doc)['original']);self.assertEqual(args[2],PROMPT);self.assertEqual(args[4],BAD);inventory=json.loads(args[3].split('\n',1)[1]);self.assertTrue(all(i['width_px']>0 and i['height_px']>0 and i['aspect_ratio']==i['width_px']/i['height_px'] for i in inventory));self.assertTrue(args[6][0]['image_url'].startswith('data:image/png;base64,'))
  final=self.w.report_html('a',self.doc);self.assertEqual(final,bind_images(GOOD,crop_images(args[0]))[0].encode());self.assertEqual(self.w.report_html('a',self.doc,True),BAD.encode());self.assertEqual(self.w.processing.checked_html(self.doc),final)
  receipt=self.w.processing.get(self.doc,'layout-refinement');self.assertTrue(receipt['accepted']);self.assertFalse(receipt['program_pagination']);self.assertEqual(self.w.processing.get(self.doc,'layout-audit')['status'],'PASS')
  with self.w.workflow.connect() as db:db.execute("UPDATE artifacts SET payload=? WHERE document=? AND kind='report.refinement-response.html'",(b'changed',self.doc))
  from urs.workflow import Blocked
  with self.assertRaises(Blocked):self.w.report_html('a',self.doc)
 def test_text_or_image_change_is_rejected_and_previous_report_is_kept(self):
  self.run_report(ReportAI(GOOD));old=self.w.report_html('a',self.doc)
  provider=Refiner(reply=GOOD.replace('120 mm','125 mm'));self.run_report(provider);self.assertEqual(len(provider.refinements),1);self.assertEqual(self.w.report_availability('a',self.doc)['selected']['revision'],1);self.assertEqual(self.w.report_html('a',self.doc,revision=1),old);receipt=self.w.processing.get(self.doc,'layout-refinement',2);self.assertFalse(receipt['accepted']);self.assertIn('달라졌습니다',receipt['failure_reason'])
  self.assertFalse(preserved(BAD,GOOD.replace('urs-image:1:2','urs-image:1:1')))
 def test_still_bad_response_is_not_retried(self):
  provider=Refiner(reply=BAD);self.run_report(provider);self.assertEqual(len(provider.refinements),1);self.assertFalse(self.w.processing.get(self.doc,'layout-refinement')['accepted']);self.assertNotEqual(self.w.processing.get(self.doc,'layout-audit')['status'],'PASS')
 def test_incomplete_refinement_keeps_existing_report_and_diagnostics(self):
  from urs.ai import AIError
  self.run_report(ReportAI(GOOD));old=self.w.report_html('a',self.doc,revision=1);provider=Refiner()
  error=AIError('출력 토큰 한도(16,000)에 도달했습니다.');error.diagnostics={'task':'report_layout_refine','outcome':'max_output_tokens','max_output_tokens':16000,'response_status':'incomplete'}
  with patch.object(provider,'refine_report_html',side_effect=error) as call:self.run_report(provider)
  self.assertEqual(call.call_count,1);receipt=self.w.processing.get(self.doc,'layout-refinement',2);self.assertEqual(receipt['api_diagnostics']['outcome'],'max_output_tokens');self.assertFalse(receipt['accepted']);self.assertEqual(self.w.report_availability('a',self.doc)['selected']['revision'],1);self.assertEqual(self.w.report_html('a',self.doc,revision=1),old)
 def test_good_first_reply_needs_no_refinement(self):
  provider=Refiner(raw=GOOD);self.run_report(provider);self.assertEqual(provider.refinements,[]);self.assertEqual(self.w.processing.get(self.doc,'layout-audit')['status'],'PASS')
 def test_unknown_initial_usage_keeps_reservation_and_blocks_overall_execution_cap(self):self.real_transport(unknown=True)
 def test_known_usage_settles_before_refinement_and_same_model_settings_are_used(self):self.real_transport(unknown=False)
 def real_transport(self,unknown):
  calls=[]
  def network(req,**kw):
   body=json.loads(req.data)
   if req.full_url.endswith('/input_tokens'):value={'input_tokens':20000}
   else:
    calls.append(body);value={'status':'completed','usage':{} if unknown else {'input_tokens':1000,'output_tokens':1000},'output':[{'content':[{'type':'output_text','text':BAD if len(calls)==1 else GOOD}]}]}
   response=io.BytesIO(json.dumps(value).encode());response.status=200;return response
  env={'URS_OPENAI_API_KEY':'MOCK','URS_OPENAI_MODEL':'fixture-terra','URS_OPENAI_REASONING_EFFORT':'high','URS_OPENAI_MAX_OUTPUT_TOKENS':'16000','URS_AI_BUDGET_USD':'.15','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
  with patch.dict(os.environ,env,clear=True),patch('urllib.request.urlopen',side_effect=network):self.w.run('a',self.doc,'report')
  receipt=self.w.processing.get(self.doc,'layout-refinement');self.assertEqual(len(calls),1 if unknown else 2)
  if unknown:self.assertIn('실행 한도',receipt['failure_reason']);self.assertFalse(receipt['accepted'])
  else:
   self.assertTrue(receipt['accepted']);self.assertEqual(calls[0]['model'],calls[1]['model']);self.assertEqual(calls[0]['reasoning'],calls[1]['reasoning']);self.assertEqual(calls[1]['max_output_tokens'],16000)
   content=calls[1]['input'][0]['content'];self.assertTrue(any(c['type']=='input_image' for c in content));self.assertTrue(any(c.get('text')==BAD for c in content));self.assertEqual(content[1]['text'],PROMPT)
  with self.w.workflow.connect() as db:cost=json.loads(db.execute('SELECT payload FROM ai_call_costs ORDER BY call_id').fetchone()[0])
  self.assertEqual(cost['settlement_state'],'usage_unknown' if unknown else 'settled');self.assertIsNone(cost['actual_cost_usd']) if unknown else self.assertGreater(cost['actual_cost_usd'],0)

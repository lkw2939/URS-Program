"""No paid calls: exact payload preflight, image transport, per-call cap and settlement."""
import base64,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html_fixtures import RAW,PROMPT,ReportAI,visual_pdf
from urs.workspace import Workspace
from urs import costing
from urs.ai import OpenAI,AIBlocked
from urs.usage_audit import ledger
ENV={'URS_OPENAI_API_KEY':'PRIVATE-MOCK-KEY','URS_OPENAI_MODEL':'fixture-model','URS_AI_BUDGET_USD':'10','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'}
class CostTests(unittest.TestCase):
 def setUp(self):
  self.env=self.enterContext(patch.dict(os.environ,ENV,clear=True));self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workspace(Path(self.tmp.name)/'fixture.sqlite');self.w.add_user('fixture','fixture-password-123');p=self.w.create_project('fixture','Costs');self.pdf=visual_pdf();self.doc=self.w.upload('fixture',p,'source.pdf',self.pdf);self.w.save_report_settings('fixture',PROMPT);self.config={'model':'fixture-model','effort':'high','max_output_tokens':16000};self.ai=OpenAI(self.w.workflow,self.doc,self.config)
 def request(self):return costing.payload(self.config,self.pdf,'source.pdf',[{'type':'input_text','text':'fixture text'}])
 def reply(self,value):return io.BytesIO(json.dumps(value).encode())
 def reserve(self):
  with patch('urs.costing.count_input_tokens',return_value=20000):return costing.reserve(self.w.workflow,self.doc,'fixture',self.request())
 def costs(self):
  with self.w.workflow.connect() as db:return ledger(db,self.doc)
 def test_count_endpoint_uses_exact_model_input_and_format_without_inference(self):
  request=self.request()
  with patch('urllib.request.urlopen',return_value=self.reply({'input_tokens':20000})) as net:q=costing.quote(self.w.workflow,request,True)
  self.assertIsNone(net.call_args.kwargs['timeout'])
  sent=json.loads(net.call_args.args[0].data);self.assertTrue(net.call_args.args[0].full_url.endswith('/responses/input_tokens'));self.assertEqual(sent['input'],request['input']);self.assertEqual(sent['model'],request['model']);self.assertEqual(sent['reasoning'],request['reasoning']);self.assertNotIn('max_output_tokens',sent);self.assertAlmostEqual(q['input_cost_usd'],.02);self.assertAlmostEqual(q['estimated_max_usd'],.10);self.assertIsNone(q['provider_balance_usd']);self.assertEqual(self.costs()['calls'],[])
 def test_status_query_does_not_contact_network(self):
  with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):self.assertEqual(costing.quote(self.w.workflow,self.request())['status'],'UNVERIFIED')
 def test_cached_count_invalidated_by_model_effort_or_output_limit(self):
  request=self.request()
  with patch('urs.costing.count_input_tokens',return_value=123) as count:
   costing.quote(self.w.workflow,request,True);costing.quote(self.w.workflow,request,True);self.assertEqual(count.call_count,1)
   for field,value in [('model','other-model'),('max_output_tokens',32000),('reasoning',{'effort':'low'})]:
    changed={**request,field:value};self.assertEqual(costing.quote(self.w.workflow,changed)['status'],'UNVERIFIED')
 def test_expired_quote_does_not_authorize_inference(self):
  with patch('urs.costing.count_input_tokens',return_value=10):costing.quote(self.w.workflow,self.request(),True)
  with self.w.workflow.connect() as db:db.execute('UPDATE ai_cost_quotes SET created=0')
  self.assertEqual(costing.quote(self.w.workflow,self.request())['status'],'UNVERIFIED')
 def test_images_are_image_inputs_exact_bytes_and_stored_html_unchanged(self):
  from urs.images import bind_images,crop_images
  final=bind_images(RAW.replace('src=urs-image:9:8','src=urs-image:1:1'),crop_images(self.pdf))[0];original=final.encode();parts=costing.review_parts('independent_verify',final);images=[p for p in parts if p['type']=='input_image'];self.assertEqual(len(images),3)
  self.assertNotIn('data:image/',parts[1]['text']);self.assertEqual(final.encode(),original)
  restored=parts[1]['text']
  for i in range(2,len(parts),2):restored=restored.replace(parts[i]['text'].split('HTML image reference: ')[1],parts[i+1]['image_url'])
  self.assertEqual(restored,final)
  from urs.images import ImageSlots
  before=[base64.b64decode(url.split(',')[1]) for _,_,url in reversed(ImageSlots(final,prefix='data:image/').slots)]
  self.assertEqual([base64.b64decode(p['image_url'].split(',')[1]) for p in images],before);self.assertTrue(all(p['detail']=='auto' for p in images))
 def test_unknown_image_format_not_silently_counted_as_text(self):
  with self.assertRaises(costing.CostError):costing.review_parts('independent_verify','<html><img src="data:image/svg+xml;base64,AAAA"></html>')
 def test_prior_failed_estimates_do_not_reduce_per_execution_cap(self):
  with self.w.workflow.connect() as db:db.execute('INSERT INTO ai_usage(document,task,model,reserved,state) VALUES(?,?,?,?,?)',(self.doc,'old','old-model',999,'failed'))
  ident=self.reserve();self.assertGreater(ident,0);self.assertEqual(self.costs()['unresolved_count'],2);self.assertEqual(self.costs()['settled_usage_cost_usd'],0)
 def test_single_execution_over_cap_is_blocked_before_reservation(self):
  with patch('urs.costing.count_input_tokens',return_value=11000000):
   with self.assertRaises(costing.CostError):costing.reserve(self.w.workflow,self.doc,'fixture',self.request())
  self.assertEqual(self.costs()['calls'],[])
 def test_failed_call_with_usage_is_settled_at_snapshot_rates(self):
  ident=self.reserve()
  with patch.dict(os.environ,{'URS_AI_INPUT_USD_PER_MILLION':'999'}):costing.finish(self.w.workflow,ident,'failed',{'status':'incomplete','usage':{'input_tokens':20000,'output_tokens':1000}})
  c=self.costs()['calls'][0];self.assertEqual(c['state'],'failed');self.assertEqual(c['settlement_state'],'settled');self.assertAlmostEqual(c['actual_cost_usd'],.025);self.assertAlmostEqual(c['original_estimate_usd'],.10)
 def test_success_with_usage_settles_and_reasoning_not_double_counted(self):
  ident=self.reserve();costing.finish(self.w.workflow,ident,'completed',{'usage':{'input_tokens':20000,'output_tokens':1000,'output_tokens_details':{'reasoning_tokens':800}}});self.assertAlmostEqual(self.costs()['settled_usage_cost_usd'],.025)
 def test_unknown_failure_retains_evidence_but_never_becomes_zero_spend(self):
  ident=self.reserve();costing.finish(self.w.workflow,ident,'failed',None);c=self.costs()['calls'][0];self.assertIsNone(c['actual_cost_usd']);self.assertEqual(c['settlement_state'],'usage_unknown');self.assertAlmostEqual(c['original_estimate_usd'],.1);self.assertEqual(self.costs()['unresolved_count'],1)
 def test_partial_usage_is_not_settled(self):
  ident=self.reserve();costing.finish(self.w.workflow,ident,'failed',{'usage':{'input_tokens':20000}});self.assertIsNone(self.costs()['calls'][0]['actual_cost_usd'])
 def test_cached_usage_without_historical_cache_price_is_unsettled(self):
  ident=self.reserve();costing.finish(self.w.workflow,ident,'completed',{'usage':{'input_tokens':20000,'output_tokens':1000,'input_tokens_details':{'cached_tokens':10000}}});self.assertEqual(self.costs()['calls'][0]['settlement_state'],'cached_rate_unknown')
 def test_cached_usage_with_price_is_settled(self):
  with patch.dict(os.environ,{'URS_AI_CACHED_INPUT_USD_PER_MILLION':'.1'}):ident=self.reserve()
  costing.finish(self.w.workflow,ident,'completed',{'usage':{'input_tokens':20000,'output_tokens':1000,'input_tokens_details':{'cached_tokens':10000}}});self.assertAlmostEqual(self.costs()['settled_usage_cost_usd'],.016)
 def test_legacy_usage_has_no_fabricated_historical_rate(self):
  with self.w.workflow.connect() as db:db.execute('INSERT INTO ai_usage(document,task,model,reserved,state,usage) VALUES(?,?,?,?,?,?)',(self.doc,'old','old-model',3,'failed',json.dumps({'input_tokens':1,'output_tokens':2})))
  c=self.costs()['calls'][0];self.assertEqual(c['settlement_state'],'legacy_rates_unknown');self.assertIsNone(c['actual_cost_usd'])
 def test_free_counter_failure_never_sends_paid_request(self):
  with patch('urllib.request.urlopen',side_effect=TimeoutError) as net:
   with self.assertRaises(AIBlocked):self.ai.report_html(self.pdf,'source.pdf',PROMPT,'guide')
   self.assertEqual(net.call_count,1);self.assertTrue(net.call_args.args[0].full_url.endswith('/input_tokens'))
  self.assertEqual(self.costs()['calls'],[])
 def test_counter_and_inference_use_same_inputs_and_only_inference_is_reserved(self):
  wires=[]
  def network(req,**kw):
   wires.append((req.full_url,json.loads(req.data)))
   if req.full_url.endswith('/input_tokens'):return self.reply({'input_tokens':20000})
   return self.reply({'status':'completed','usage':{'input_tokens':20000,'output_tokens':1000},'output':[{'content':[{'type':'output_text','text':'<html>fixture</html>'}]}]})
  with patch('urllib.request.urlopen',side_effect=network):self.ai.report_html(self.pdf,'source.pdf',PROMPT,'guide')
  self.assertEqual(len(wires),2);self.assertEqual(wires[0][1]['input'],wires[1][1]['input']);self.assertEqual(len(self.costs()['calls']),1);self.assertEqual(self.costs()['unresolved_count'],0)
 def test_html_processing_failure_keeps_actual_usage(self):
  def network(req,**kw):return self.reply({'input_tokens':20000}) if req.full_url.endswith('/input_tokens') else self.reply({'status':'completed','usage':{'input_tokens':20000,'output_tokens':1000},'output':[{'content':[{'type':'output_text','text':'not HTML'}]}]})
  with patch('urllib.request.urlopen',side_effect=network):
   with self.assertRaises(Exception):self.ai.report_html(self.pdf,'source.pdf',PROMPT,'guide')
  self.assertEqual(self.costs()['calls'][0]['state'],'failed');self.assertAlmostEqual(self.costs()['settled_usage_cost_usd'],.025)

 def test_changed_preview_fingerprint_blocks_before_count_or_inference(self):
  self.ai.authorized_quotes[(self.doc,'report_html')]='old-preview'
  with patch('urllib.request.urlopen') as net:
   with self.assertRaises(AIBlocked):self.ai.report_html(self.pdf,'source.pdf',PROMPT,'guide')
   net.assert_not_called()

 def test_verification_export_includes_settlement_without_keys_or_body(self):
  ident=self.reserve();costing.finish(self.w.workflow,ident,'completed',{'usage':{'input_tokens':20000,'output_tokens':1000}})
  bundle=self.w.verification_record('fixture',self.doc);history=bundle['record']['ai_cost_history'];self.assertEqual(history['calls'][0]['settlement_state'],'settled');self.assertAlmostEqual(history['settled_usage_cost_usd'],.025);self.assertNotIn(ENV['URS_OPENAI_API_KEY'],json.dumps(bundle));self.assertNotIn('fixture text',json.dumps(history))

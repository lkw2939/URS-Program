"""Inspect the local app configuration; optionally make ONE recorded live report call.

Existing report artifacts and workflow stages are never regenerated/overwritten.
Only the real call's ai_usage ledger is appended. Diagnostic HTML stays in a new
private .runtime/diagnostics directory. Never prints keys, prompts, PDF or HTML text.
"""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from urs.ai import OpenAI, AIBlocked
from urs.ai_settings import environment,validate,SettingsError
from urs.workspace import Workspace
from urs.workflow import Workflow

ROOT=Path(__file__).resolve().parents[1]


def sha(value):return hashlib.sha256(value).hexdigest()


def inspect(root,document=None):
    path=Path(root)/'.runtime/workspace.sqlite'
    environment_error=None
    try:base=environment()
    except SettingsError as exc:
        environment_error=str(exc);base={'model':os.environ.get('URS_OPENAI_MODEL','').strip(),'effort':None,'max_output_tokens':5000}
    result={'scope':'configuration and existing artifacts; no API call yet',
        'api_key_present':bool(os.environ.get('URS_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')),
        'requested_model':base['model'] or None,'requested_effort':base['effort'],'requested_max_output_tokens':base['max_output_tokens'],'ai_settings_source':'server','ai_settings_version':0,
        'effort_note':'explicit configured effort' if base['effort'] is not None else 'reasoning.effort is not sent; provider default, not yet observed',
        'api_call_verified':False,'html_image_only_verified':False}
    if not path.exists():result['blocked']='workspace database missing';return result,None
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        sql='SELECT d.*,p.owner FROM documents d JOIN projects p ON p.id=d.project'
        row=db.execute(sql+(' WHERE d.id=?' if document else '')+' ORDER BY d.rowid DESC LIMIT 1',(document,) if document else ()).fetchone()
        if not row:result['blocked']='uploaded PDF missing';return result,None
        selected=dict(row)
        if sha(selected['original'])!=selected['sha256']:result['blocked']='original PDF integrity mismatch';return result,None
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        config_row=db.execute('SELECT version,payload FROM ai_settings WHERE owner=? ORDER BY version DESC LIMIT 1',(selected['owner'],)).fetchone() if 'ai_settings' in tables else None
        config=validate(json.loads(config_row['payload'])) if config_row else base
        selected['ai_config']=config
        result['effort_note']='explicit configured effort' if config['effort'] is not None else 'reasoning.effort not sent; provider default not yet observed'
        if not config_row and environment_error:result['blocked']=environment_error
        result.update({'requested_model':config['model'] or None,'requested_effort':config['effort'],'requested_max_output_tokens':config['max_output_tokens'],'ai_settings_source':'web' if config_row else 'server','ai_settings_version':config_row['version'] if config_row else 0})
        prompt=None
        if 'report_settings' in tables:
            prompt=db.execute('SELECT prompt,version FROM report_settings WHERE owner=? ORDER BY version DESC LIMIT 1',(selected['owner'],)).fetchone()
        result.update({'document_id':selected['id'],'original_pdf_sha256':selected['sha256'],'pages':selected['pages'],
            'prompt_saved':bool(prompt and prompt['prompt'].strip()),'prompt_version':prompt['version'] if prompt else None,
            'prompt_bytes':len(prompt['prompt'].encode()) if prompt else 0,'prompt_sha256':sha(prompt['prompt'].encode()) if prompt else None})
        selected['prompt']=prompt['prompt'] if prompt else ''
        selected['artifacts_before']=[tuple(r) for r in db.execute('SELECT revision,kind,payload FROM artifacts WHERE document=? ORDER BY revision,kind',(selected['id'],))]
        selected['results_before']=[tuple(r) for r in db.execute('SELECT * FROM results WHERE job=? ORDER BY revision,stage,check_id',(selected['id'],))]
        if 'ai_usage' in tables:
            result['existing_api_calls']=[dict(r) for r in db.execute('SELECT id,task,model,state FROM ai_usage WHERE document=? ORDER BY id DESC LIMIT 5',(selected['id'],))]
    return result,selected


def save_prompt_file(root, filename, document=None):
    """Explicit user action: append a settings version for the selected PDF owner."""
    root=Path(root).resolve();prompt=Path(filename).read_text(encoding='utf-8')
    if not prompt.strip() or len(prompt.encode())>180000:raise ValueError('Prompt file must contain 1..180000 UTF-8 bytes')
    path=root/'.runtime/workspace.sqlite'
    if not path.exists():raise ValueError('Upload the original PDF first')
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT p.owner FROM documents d JOIN projects p ON p.id=d.project'+(' WHERE d.id=?' if document else '')+' ORDER BY d.rowid DESC LIMIT 1',(document,) if document else ()).fetchone()
    if not row:raise ValueError('Uploaded PDF missing')
    w=Workspace(path)
    current=w.report_settings(row[0])
    if current['prompt']==prompt:return {'version':current['version'],'changed':False,'sha256':sha(prompt.encode())}
    saved=w.save_report_settings(row[0],prompt)
    return {'version':saved['version'],'changed':True,'sha256':sha(prompt.encode())}


class ResponseObserver:
    def __init__(self,response,proof):self.response,self.proof=response,proof
    def __enter__(self):
        self.proof['http_status']=self.response.status
        self.proof['request_id']=self.response.headers.get('x-request-id')
        return self
    def read(self,*args):
        raw=self.response.read(*args)
        try:
            value=json.loads(raw)
            self.proof.update({'response_id':value.get('id'),'returned_model':value.get('model'),
                'returned_effort':(value.get('reasoning') or {}).get('effort'),
                'response_status':value.get('status'),'incomplete_reason':(value.get('incomplete_details') or {}).get('reason'),'usage':value.get('usage',{})})
        except (ValueError,TypeError):pass
        return raw
    def __exit__(self,*args):self.response.close()


def run(root=ROOT,document=None,live=False):
    root=Path(root).resolve()
    result,source=inspect(root,document)
    if not live or source is None or result.get('blocked'):return result
    if not source['prompt'].strip():result['blocked']='saved report prompt missing; no report API request sent';return result
    if not result['api_key_present'] or not result['requested_model']:
        result['blocked']='API key or model setting missing; no API request sent';return result
    result['scope']='single provider call; existing report artifacts and stages preserved'
    proof={'requests':0};real_open=urllib.request.urlopen
    def observed(request,*args,**kwargs):
        if request.full_url!='https://api.openai.com/v1/responses':raise ValueError('Unexpected diagnostic destination')
        proof['requests']+=1
        if proof['requests']>1:raise ValueError('Diagnostic is limited to one live call')
        payload=json.loads(request.data);content=payload['input'][0]['content']
        proof['sent_original_pdf']=content[0]['type']=='input_file' and base64.b64decode(content[0]['file_data'].split(',')[1])==source['original']
        proof['sent_verbatim_saved_prompt']=content[1]['text']==source['prompt']
        proof['only_file_prompt_image_guide']=len(content)==3 and [c['type'] for c in content]==['input_file','input_text','input_text'] and 'instructions' not in payload and 'text' not in payload
        proof['requested_effort']=(payload.get('reasoning') or {}).get('effort')
        proof['requested_max_output_tokens']=payload.get('max_output_tokens')
        try:return ResponseObserver(real_open(request,*args,**kwargs),proof)
        except urllib.error.HTTPError as exc:
            proof['http_status']=exc.code
            try:
                error=json.loads(exc.read()).get('error',{})
                proof['provider_error_code']=error.get('code');proof['provider_error_type']=error.get('type')
            except (ValueError,AttributeError):pass
            exc.close();raise
    try:
        # Production report pipeline, isolated artifact storage; the production
        # budget and usage ledger apply to the original selected document.
        live_workflow=Workflow(root/'.runtime/workspace.sqlite')
        live_provider=OpenAI(live_workflow,source['id'],settings=source['ai_config'])
        with tempfile.TemporaryDirectory(prefix='urs-api-report-check-') as folder:
            w=Workspace(Path(folder)/'diagnostic.sqlite')
            w.add_user('diagnostic','temporary-diagnostic-account-123')
            project=w.create_project('diagnostic','Diagnostic only')
            doc=w.upload('diagnostic',project,source['name'],source['original'])
            w.save_report_settings('diagnostic',source['prompt'])
            if source['ai_config']['model']:w.save_ai_settings('diagnostic',source['ai_config'])
            w.processing.provider=live_provider
            with patch('urllib.request.urlopen',side_effect=observed):
                state=w.run('diagnostic',doc,'report')
            passed=next(s['passed'] for s in state['stages'] if s['id']=='report')
            result['api_call_verified']=proof.get('http_status')==200 and proof.get('response_status')=='completed'
            if passed:
                raw=w.report_html('diagnostic',doc,True);final=w.report_html('diagnostic',doc)
                comparison=w.artifact('diagnostic',doc,'image-bindings')
                assets=w.artifact('diagnostic',doc,'report-images');mapping={a['uri']:a['data_url'].encode() for a in assets}
                # Independently walk every unchanged text span (Unicode source offsets).
                raw_text=raw.decode();final_text=final.decode();source_pos=final_pos=0;identical=True
                for change in comparison['replacements']:
                    unchanged=raw_text[source_pos:change['start']]
                    identical &= final_text[final_pos:final_pos+len(unchanged)]==unchanged
                    final_pos+=len(unchanged)
                    replacement=mapping[change['uri']].decode()
                    identical &= raw_text[change['start']:change['end']]==change['uri'] and final_text[final_pos:final_pos+len(replacement)]==replacement
                    final_pos+=len(replacement);source_pos=change['end']
                identical &= final_text[final_pos:]==raw_text[source_pos:]
                result.update({'html_image_only_verified':bool(identical),'image_binding_exercised':bool(comparison['replacements']),'images_inserted':len(comparison['replacements']),
                    'unresolved_images':comparison['unresolved'],'raw_html_sha256':sha(raw),'final_html_sha256':sha(final)})
                directory=root/'.runtime/diagnostics'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                directory.mkdir(parents=True,mode=0o700)
                for name,value in [('report.raw.html',raw),('report.html',final)]:
                    file=directory/name;file.write_bytes(value);file.chmod(0o600)
                result['diagnostic_files']=str(directory.relative_to(root))
            else:
                result['blocked']='report pipeline did not pass'
                result['pipeline_result']=[{'stage':r['stage'],'status':r['status'],'evidence':json.loads(r['evidence'])} for r in state['results'] if r['stage']=='report']
    except Exception as exc:
        result['blocked']='diagnostic failed';result['error_type']=type(exc).__name__
    finally:
        result['live_request']=proof
        result['api_http_success']=proof.get('http_status')==200
        result['api_response_completed']=proof.get('response_status')=='completed'
        result['effort_note']=('requested effort '+str(proof.get('requested_effort'))+'; provider returned '+str(proof.get('returned_effort'))) if proof.get('requested_effort') is not None else ('reasoning.effort not sent; provider returned '+str(proof['returned_effort']) if proof.get('returned_effort') is not None else 'reasoning.effort not sent; effective provider default was not reported')
        with sqlite3.connect((root/'.runtime/workspace.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            artifacts=[tuple(r) for r in db.execute('SELECT revision,kind,payload FROM artifacts WHERE document=? ORDER BY revision,kind',(source['id'],))]
            results=[tuple(r) for r in db.execute('SELECT * FROM results WHERE job=? ORDER BY revision,stage,check_id',(source['id'],))]
        result['existing_reports_and_stages_unchanged']=artifacts==source['artifacts_before'] and results==source['results_before']
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--call',action='store_true',help='Make at most one real paid report request when PDF, saved prompt and configuration exist')
    parser.add_argument('--save-prompt',type=Path,help='Explicitly save the supplied prompt file to the selected PDF owner settings before diagnosis')
    parser.add_argument('--document',help='Document ID; defaults to latest uploaded PDF')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env',override=False,interpolate=False)
    try:
        saved=save_prompt_file(ROOT,args.save_prompt,args.document) if args.save_prompt else None
        result=run(ROOT,args.document,args.call)
        if saved:result['prompt_saved_from_file']=saved
    except (AIBlocked,SettingsError,ValueError,OSError) as exc:
        result={'blocked':'configuration or prompt-file error','error_type':type(exc).__name__,'api_call_verified':False,'html_image_only_verified':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if result.get('blocked') else 0
if __name__=='__main__':raise SystemExit(main())

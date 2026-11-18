"""Reopen fixture HTML/PNGs and retain the actual mocked OpenAI request body."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from html_fixtures import visual_pdf,RAW,PROMPT
from urs.workspace import Workspace

def main():
    root=Path(__file__).resolve().parents[1]/'docs/evidence'
    with patch('urs.costing.count_input_tokens',return_value=12000),patch.dict('os.environ',{'URS_AI_BUDGET_USD':'100','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'5'},clear=False),tempfile.TemporaryDirectory() as folder:
        w=Workspace(Path(folder)/'synthetic.sqlite')
        w.add_user('fixture','synthetic-password-123')
        project=w.create_project('fixture','Synthetic request evidence')
        doc=w.upload('fixture',project,'synthetic.pdf',visual_pdf())
        w.save_report_settings('fixture',PROMPT)
        response={'status':'completed','output':[{'content':[{'type':'output_text','text':RAW}]}]}
        settings={'URS_OPENAI_API_KEY':'synthetic-only-not-a-real-key','URS_OPENAI_MODEL':'fixture-terra',
                  'URS_AI_BUDGET_USD':'50','URS_AI_INPUT_USD_PER_MILLION':'1','URS_AI_OUTPUT_USD_PER_MILLION':'2'}
        with patch.dict(os.environ,settings,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as network:
            state=w.run('fixture',doc,'report')
        assert next(s['passed'] for s in state['stages'] if s['id']=='report')
        payload=json.loads(network.call_args.args[0].data)
        assert payload['input'][0]['content'][1]['text']==PROMPT
        assert set(payload)=={'model','input','max_output_tokens','store'}
        (root/'html-request-contract.json').write_text(json.dumps({'scope':'Synthetic PDF, fixture model, mocked transport; no authentication headers or real customer data','payload':payload},ensure_ascii=False,indent=2)+'\n')
        raw=w.report_html('fixture',doc,True);final=w.report_html('fixture',doc)
        assert raw==RAW.encode()
        for name,value in [('synthetic-model-original.html',raw),('synthetic-model-final.html',final)]:
            file=root/name;file.write_bytes(value);assert file.read_bytes()==value
        for asset in w.artifact('fixture',doc,'report-images'):
            png=base64.b64decode(asset['data_url'].split(',')[1]);assert hashlib.sha256(png).hexdigest()==asset['sha256']
            with Image.open(io.BytesIO(png)) as image:image.verify()
        comparison=w.artifact('fixture',doc,'image-bindings')
        (root/'html-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+'\n')
        assert comparison['only_image_addresses_changed'] and len(comparison['replacements'])==2 and len(comparison['unresolved'])==1
    print('PASS: exact mocked PDF/prompt/image-guide request retained; model HTML preserved byte-for-byte, self-contained HTML reopened, 2 distinct source PNG crops decoded, only image addresses replaced; 1 unresolved slot retained and recorded. No paid API calls; no Word/PDF regeneration.')
if __name__=='__main__':main()

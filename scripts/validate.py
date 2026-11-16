"""Reproduce all available local evidence, retaining each runner's exit status."""
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    python=str(ROOT/'.venv/bin/python') if (ROOT/'.venv/bin/python').exists() else sys.executable
    # The browser runner uses host Playwright; document checks reopen unchanged HTML.
    commands=[('unit-http',[python,'scripts/validate_unit_stages.py'],'final-tests.txt'),
              ('chromium',[sys.executable,'tests/browser_pipeline.py'],'final-browser.txt'),
              ('html-artifacts',[sys.executable,'tests/html_smoke.py'],'final-html.txt')]
    runs=[]
    for name,command,filename in commands:
        started=time.time()
        result=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (OUT/filename).write_bytes(result.stdout)
        entry={'name':name,'command':command,'exit_code':result.returncode,'duration_seconds':round(time.time()-started,3),'log':filename}
        if name=='unit-http':
            match=re.search(rb'Ran (\d+) tests',result.stdout)
            entry['tests']=int(match.group(1)) if match else 0
            if not entry['tests']:entry['exit_code']=1
        runs.append(entry)
        print(name,'PASS' if entry['exit_code']==0 else 'FAIL',flush=True)
        if entry['exit_code']!=0:break
    paths=[*ROOT.glob('urs/*.py'),*ROOT.glob('tests/*.py'),*ROOT.glob('scripts/*.py'),*ROOT.glob('static/*.*'),*ROOT.glob('tests/vendor/pdfjs/*'),*ROOT.glob('prompts/*.txt'),ROOT/'requirements.lock',ROOT/'service.py',ROOT/'start.py',ROOT/'.devcontainer/devcontainer.json']
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    evidence={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.parent==OUT and (p.name.startswith(('final-','html-report-','synthetic-model-')) or p.name in ('html-comparison.json','html-request-contract.json'))}
    stage_file=OUT/'stages/stage-results.json'
    unit_stages=json.loads(stage_file.read_text()) if stage_file.exists() else []
    summary={'unit_stages':unit_stages,'scope':'synthetic fixtures and mocked AI transport only','runs':runs,'source_sha256':manifest,'evidence_sha256':evidence,
             'real_openai_verified':False,'real_customer_urs_verified':False,'accuracy_99_demonstrated':False,
             'all_requirements_completed':False}
    (OUT/'validation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return 0 if len(runs)==len(commands) and all(r['exit_code']==0 for r in runs) else 1


if __name__=='__main__':raise SystemExit(main())

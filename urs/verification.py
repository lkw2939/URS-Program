"""Ordered development checks; a failed stage prevents subsequent commands."""
import json
import re
import subprocess
import time
from pathlib import Path


def run_stages(plan,root,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    results=[]
    for stage in plan:
        commands=[];total=0
        for index,command in enumerate(stage['commands'],1):
            started=time.monotonic()
            result=subprocess.run(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            filename=f"{stage['id']}-{index}.txt"
            (out/filename).write_bytes(result.stdout)
            counts=re.findall(rb'Ran (\d+) tests?',result.stdout)
            count=int(counts[-1]) if counts else 0
            exit_code=result.returncode
            # Zero tests or skipped tests do not prove stage readiness.
            if stage.get('requires_tests') and (count==0 or re.search(rb'\b(?:skipped|expected failures|unexpected successes)[= ]\d+',result.stdout)):
                exit_code=exit_code or 1
            total+=count
            commands.append({'command':command,'exit_code':exit_code,'tests':count,'log':filename,'duration_seconds':round(time.monotonic()-started,3)})
            if exit_code:break
        passed=bool(commands) and len(commands)==len(stage['commands']) and all(c['exit_code']==0 for c in commands)
        results.append({'id':stage['id'],'status':'PASS' if passed else 'FAIL','tests':total,'commands':commands})
        (out/'stage-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
        if not passed:break
    return results

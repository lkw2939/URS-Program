"""Test-only host for independent legacy controls, not the employee page router.

The unmodified stage-page flow is covered by browser_workflow.py. This host
mounts detached components explicitly; the production app has no unlock mode.
"""
def install(page):
    page.add_init_script('''(()=>{
    if(window!==window.top||!/^https?:$/.test(location.protocol))return;
    history.replaceState({},'',location.pathname);
    document.addEventListener('DOMContentLoaded',()=>{
      const open=()=>{
        const root=document.querySelector('#review');if(!root)return;
        if(typeof flowBank!=='undefined')for(const n of [...flowBank.children]){
          if(n.dataset.operation){const actions=document.querySelector('#process-buttons');if(actions)actions.append(n);}
          else root.append(n);
        }
        if(!document.querySelector('#flow-details')){const host=document.createElement('details');host.id='flow-details';host.append(document.createElement('summary'));root.append(host);}
        const host=document.querySelector('#flow-details');
        for(const id of ['technical-details','check-results']){const n=document.getElementById(id);if(n&&n.parentNode!==host)host.append(n);}
        document.querySelectorAll('.flow-panel,#process-buttons .execution-cost,#advanced-targets').forEach(n=>n.hidden=false);
        document.querySelectorAll('.flow-cost,#flow-details').forEach(d=>d.open=true);
      };
      new MutationObserver(open).observe(document.body,{subtree:true,childList:true});open();
    });})();''')

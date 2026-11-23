"""Mount legacy browser component regressions without wizard presentation.

These tests exercise existing controls/HTTP/artifacts, not step-navigation UX.
The unmodified, one-panel user flow is tested separately in browser_workflow.py.
This host exists only in tests; the application has no 'skip steps' switch.
"""
def install(page):
    page.add_init_script('''document.addEventListener('DOMContentLoaded',()=>{
      document.documentElement.dataset.componentHost='true';
      const s=document.createElement('style');s.textContent='[data-component-host] .flow-panel[hidden], [data-component-host] #process-buttons [hidden]{display:block!important}';document.head.append(s);
      const open=()=>{document.querySelectorAll('.flow-panel,#process-buttons .execution-cost,#advanced-targets').forEach(n=>n.hidden=false);document.querySelectorAll('.flow-cost,#flow-details').forEach(d=>d.open=true);};
      new MutationObserver(open).observe(document.body,{subtree:true,childList:true});open();
    });''')

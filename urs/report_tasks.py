"""Short HTTP acceptance + polling; no automatic paid retry."""
import threading
class ReportTasks:
    def __init__(self,workspace):self.workspace=workspace;self.lock=threading.Lock();self.tasks={}
    def status(self,document):
        with self.lock:return dict(self.tasks.get(document,{'state':'none'}))
    def start(self,owner,document):
        self.workspace.original(owner,document)
        with self.lock:
            if self.tasks.get(document,{}).get('state')=='running':return {'state':'running'}
            self.tasks[document]={'state':'running'}
        def work():
            try:
                self.workspace.run(owner,document,'report');state={'state':'finished'}
            except Exception:state={'state':'failed','error':'보고서 작업이 중단됐습니다. 기존 검증 기록을 확인하세요. 자동 재시도하지 않습니다.'}
            with self.lock:self.tasks[document]=state
        threading.Thread(target=work,daemon=True).start()
        return {'state':'running'}

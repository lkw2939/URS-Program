"""Short HTTP acceptance + polling; no automatic paid retry."""
import threading
class ReportTasks:
    def __init__(self,workspace):self.workspace=workspace;self.lock=threading.Lock();self.tasks={}
    def status(self,document,stage="report"):
        with self.lock:return dict(self.tasks.get((document,stage),{'state':'none'}))
    def start(self,owner,document,stage="report"):
        self.workspace.original(owner,document)
        if stage!='report':
            from urs.reviews import overview
            info=overview(self.workspace,owner,document)[stage]
            if not info['can_run']:
                from urs.workflow import Blocked
                raise Blocked(info['blocked_reason'])
        with self.lock:
            if self.tasks.get((document,stage),{}).get('state')=='running':return {'state':'running'}
            self.tasks[(document,stage)]={'state':'running'}
        def work():
            try:

                if stage=='report':self.workspace.run(owner,document,'report')
                else:
                    from urs.reviews import run
                    run(self.workspace,owner,document,stage)
                state={'state':'finished'}
            except Exception as exc:
                from urs.workflow import Blocked
                state={'state':'failed','error':str(exc) if isinstance(exc,Blocked) else '작업이 중단됐습니다. 기존 검증 기록을 확인하세요. 자동 재시도하지 않습니다.'}
            with self.lock:self.tasks[(document,stage)]=state
        threading.Thread(target=work,daemon=True).start()
        return {'state':'running'}

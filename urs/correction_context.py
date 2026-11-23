"""Verified correction ancestry; prior reports and review judgments remain immutable."""
import hashlib,json

def continuation(workspace,owner,document,current_revision,source_revision,target,attempt):
    applied={};revision=current_revision;visited=set()
    while revision!=source_revision:
        if revision in visited or len(visited)>=100:return False,{}
        visited.add(revision)
        with workspace.workflow.connect() as db:
            rows={r['kind']:bytes(r['payload']) for r in db.execute("SELECT kind,payload FROM artifacts WHERE document=? AND revision=? AND kind IN ('report-metadata','correction-patch')",(document,revision))}
        if not all(k in rows for k in ('report-metadata','correction-patch')):return False,{}
        meta=json.loads(rows['report-metadata']);receipt=json.loads(rows['correction-patch']);parent=meta.get('parent_revision')
        if meta.get('generation_kind')!='employee_selected_correction' or type(parent) is not int or parent>=revision:return False,{}
        if hashlib.sha256(rows['correction-patch']).hexdigest()!=meta.get('correction_patch_sha256'):return False,{}
        if receipt.get('parent_revision')!=parent or receipt.get('source_target')!=target or receipt.get('source_attempt')!=attempt:return False,{}
        if hashlib.sha256(workspace.report_html(owner,document,revision=parent)).hexdigest()!=receipt.get('parent_sha256'):return False,{}
        if hashlib.sha256(workspace.report_html(owner,document,revision=revision)).hexdigest()!=meta.get('final_sha256'):return False,{}
        for patch in receipt.get('patches',[]):applied.setdefault(patch['issue_id'],{**patch,'applied_revision':revision})
        revision=parent
    return True,applied

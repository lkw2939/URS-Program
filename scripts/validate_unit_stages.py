"""All unit/HTTP test modules run in prerequisite order, with no silent omissions."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urs.verification import run_stages

ROOT=Path(__file__).resolve().parents[1]
GROUPS=[
    ('foundation',['test_gates.py','test_workflow.py','test_requirements.py','test_verification.py']),
    ('employee-original',['test_workspace.py','test_backup.py','test_service.py']),
    ('pdf-source',['test_pdf_variants.py','test_blank_pages.py']),
    ('technical-meaning-guards',['test_quantity_units.py','test_terminology.py','test_ai_and_evaluation.py','test_api_diagnostic.py','test_ai_settings.py','test_ai_limits_inspector.py','test_costing.py']),
    ('document-pipeline',['test_processing.py','test_saved_reports.py','test_report_transport.py','test_reviews.py','test_targets.py','test_layout_flow.py','test_corrections.py','test_image_presentation.py','test_review_presentation.py','test_report_view.py']),
]


def main():
    stage_dir=ROOT/'docs/evidence/stages'
    stage_dir.mkdir(parents=True,exist_ok=True)
    (stage_dir/'stage-results.json').write_text('[]\n')
    planned=[name for _,names in GROUPS for name in names]
    actual={p.name for p in (ROOT/'tests').glob('test_*.py')}
    if len(planned)!=len(set(planned)) or set(planned)!=actual:
        print('FAIL: planned tests differ from discovered test files. No stages executed.')
        return 1
    plan=[{'id':name,'requires_tests':True,'commands':[[sys.executable,'-m','unittest','discover','-s','tests','-p',file,'-v'] for file in files]} for name,files in GROUPS]
    results=run_stages(plan,ROOT,ROOT/'docs/evidence/stages')
    for result in results:
        print(result['id'],result['status'],f"({result['tests']} tests)")
    total=sum(r['tests'] for r in results)
    print(f'Ran {total} tests')
    passed=len(results)==len(plan) and all(r['status']=='PASS' for r in results)
    print('OK' if passed else 'FAILED: subsequent stages were not executed')
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())

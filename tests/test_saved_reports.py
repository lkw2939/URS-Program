"""Read-only HTML discovery across revisions, isolated fixtures, no paid API."""
import json
from pathlib import Path
import tempfile
import unittest
from html_fixtures import ReportAI,RAW,PROMPT,visual_pdf
from urs.ai import AIError
from urs.workspace import Workspace,AccessDenied
from urs.workflow import Blocked

class SavedReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=Workspace(Path(self.tmp.name)/'fixture.sqlite')
        self.w.add_user('alice','fixture-password-123');self.w.add_user('bob','fixture-password-456')
        self.project=self.w.create_project('alice','Stored HTML fixture')
        self.doc=self.w.upload('alice',self.project,'fixture.pdf',visual_pdf())
        self.w.save_report_settings('alice',PROMPT);self.w.processing.provider=ReportAI()

    def generate(self):self.w.run('alice',self.doc,'report')

    def fail_new(self):
        class Failure:
            def report_html(self,*args):raise AIError('출력 토큰 한도(16,000)에 도달했습니다.')
        self.w.processing.provider=Failure();self.w.run('alice',self.doc,'report')

    def dump(self):
        with self.w.workflow.connect() as db:
            return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('documents','jobs','artifacts','results','events','approvals','report_settings','ai_usage')}

    def test_never_generated_reports_none(self):
        info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'none');self.assertIsNone(info['selected']);self.assertIsNone(info['current_failure'])

    def test_current_html_readable_without_verification_or_approval(self):
        self.generate();info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'current');self.assertEqual(info['selected']['revision'],1)
        self.assertEqual(info['selected']['integrity'],'verified')
        self.assertIn(b'<html>',self.w.report_html('alice',self.doc))
        self.assertFalse(self.w.status('alice',self.doc)['approved'])

    def test_failed_regeneration_selects_previous_bytes_and_records_failure(self):
        self.generate();raw=self.w.report_html('alice',self.doc,True,1);final=self.w.report_html('alice',self.doc,False,1)
        self.fail_new();before=self.dump()
        info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'previous');self.assertEqual(info['current_revision'],2)
        self.assertEqual(info['selected']['revision'],1)
        self.assertIn('16,000',info['current_failure']['reason'])
        self.assertEqual(self.w.report_html('alice',self.doc,False,1),final)
        self.assertEqual(self.w.report_html('alice',self.doc,True,1),raw)
        self.assertEqual(self.dump(),before,'Reading must never repair/rewrite/advance any record')

    def test_failed_first_generation_has_no_report_but_reason(self):
        self.fail_new();info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'none');self.assertIn('16,000',info['current_failure']['reason'])

    def test_new_complete_revision_preferred_over_old(self):
        self.generate();self.generate();info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'current');self.assertEqual(info['selected']['revision'],2)
        self.assertEqual([r['revision'] for r in info['available']],[2,1])

    def test_final_only_restored_file_can_be_viewed_with_unknown_metadata(self):
        self.w.processing.put(self.doc,1,'report.html',RAW.encode())
        before=self.dump();info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'current');self.assertEqual(info['selected']['metadata'],{})
        self.assertEqual(info['selected']['integrity'],'unrecorded');self.assertFalse(info['selected']['raw_available'])
        self.assertEqual(self.w.report_html('alice',self.doc),RAW.encode());self.assertEqual(self.dump(),before)

    def test_truncated_saved_final_is_not_presented_as_complete(self):
        self.w.processing.put(self.doc,1,'report.html',b'<html><body>partial')
        info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'none');self.assertIn('불완전',info['invalid'][0]['reason'])
        with self.assertRaises(Blocked):self.w.report_html('alice',self.doc)

    def test_corrupt_current_final_falls_back_to_valid_old_revision(self):
        self.generate();self.generate()
        with self.w.workflow.connect() as db:
            db.execute("UPDATE artifacts SET payload=? WHERE document=? AND revision=2 AND kind='report.html'",(b'<html><body>tampered</body></html>',self.doc))
        info=self.w.report_availability('alice',self.doc)
        self.assertEqual(info['state'],'previous');self.assertEqual(info['selected']['revision'],1)
        self.assertIn('무결성',info['invalid'][0]['reason'])

    def test_raw_only_is_not_a_final_report(self):
        self.w.processing.put(self.doc,1,'report.raw.html',RAW.encode())
        self.assertEqual(self.w.report_availability('alice',self.doc)['state'],'none')

    def test_other_owner_cannot_discover_or_download_reports(self):
        self.generate()
        with self.assertRaises(AccessDenied):self.w.report_availability('bob',self.doc)
        with self.assertRaises(AccessDenied):self.w.report_html('bob',self.doc,revision=1)

    def test_operator_inspector_reads_existing_db_without_modification_or_prompt_leak(self):
        import subprocess,sys
        self.generate();self.fail_new();before=self.dump()
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/inspect_saved_html.py'),'--data',str(Path(self.tmp.name)/'fixture.sqlite'),'--document',self.doc]
        result=subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout);self.assertTrue(output['read_only']);self.assertEqual(output['api_calls'],0)
        self.assertEqual(output['reports'][0]['selected']['revision'],1)
        self.assertNotIn(PROMPT,result.stdout);self.assertNotIn('image_guide',result.stdout)
        self.assertEqual(self.dump(),before)

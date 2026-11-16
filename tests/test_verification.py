import json
import sys
import tempfile
import unittest
from pathlib import Path
from urs.verification import run_stages


class DevelopmentGateTests(unittest.TestCase):
    def test_failed_stage_prevents_later_command_actually_running(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'must-not-exist'
            plan=[{'id':'first','commands':[[sys.executable,'-c','raise SystemExit(23)']]},
                  {'id':'later','commands':[[sys.executable,'-c',f'from pathlib import Path; Path({str(marker)!r}).write_text("bad")']]}]
            result=run_stages(plan,root,root/'logs')
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['status'],'FAIL')
            self.assertEqual(result[0]['commands'][0]['exit_code'],23)
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads((root/'logs/stage-results.json').read_text())[0]['status'],'FAIL')

    def test_zero_test_run_cannot_unlock_next_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            plan=[{'id':'zero','requires_tests':True,'commands':[[sys.executable,'-c','print("Ran 0 tests")']]},
                  {'id':'later','commands':[[sys.executable,'-c','raise SystemExit(0)']]}]
            result=run_stages(plan,root,root/'logs')
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['status'],'FAIL')

    def test_skipped_checks_do_not_unlock_next_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            result=run_stages([{'id':'skipped','requires_tests':True,'commands':[[sys.executable,'-c','print("Ran 1 test\\nOK (skipped=1)")']]}],root,root/'logs')
            self.assertEqual(result[0]['status'],'FAIL')

    def test_passing_stage_allows_next_stage_and_preserves_both_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            result=run_stages([{'id':name,'requires_tests':True,'commands':[[sys.executable,'-c','print("Ran 1 test\\nOK")']]} for name in ('one','two')],root,root/'logs')
            self.assertEqual([r['status'] for r in result],['PASS','PASS'])
            self.assertTrue((root/'logs/one-1.txt').exists())
            self.assertTrue((root/'logs/two-1.txt').exists())

    def test_expected_failure_does_not_count_as_required_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            result=run_stages([{'id':'expected-failure','requires_tests':True,'commands':[[sys.executable,'-c','print("Ran 1 test\\nOK (expected failures=1)")']]}],root,root/'logs')
            self.assertEqual(result[0]['status'],'FAIL')

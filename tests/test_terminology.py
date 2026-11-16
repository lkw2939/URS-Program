import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urs.terminology import load,digest
from urs.evaluation import fingerprint


class TerminologyTests(unittest.TestCase):
    def test_import_is_private_non_overwriting_and_invalidates_fingerprint(self):
        from urs.terminology import import_reviewed
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'reviewed.json';target=Path(tmp)/'runtime/terms.json'
            entry={k:'synthetic fixture only' for k in ('english','korean','context','organization','document','edition','location','reviewer')}
            entry.update(url='https://example.org/reference',scope='manufacturer',approved=True)
            source.write_text(json.dumps({'entries':[entry]}))
            with patch('urs.terminology.PATH',target):
                before=fingerprint();result=import_reviewed(source)
                self.assertEqual(target.read_bytes(),source.read_bytes())
                self.assertEqual(target.stat().st_mode&0o777,0o600)
                self.assertNotEqual(before,fingerprint())
                self.assertTrue(result['qualification_reevaluation_required'])
                with self.assertRaises(FileExistsError):import_reviewed(source)
                self.assertEqual(target.read_bytes(),source.read_bytes())

    def test_unapproved_or_missing_provenance_cannot_be_registered(self):
        from urs.terminology import import_reviewed
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'bad.json';target=Path(tmp)/'runtime/terms.json'
            with patch('urs.terminology.PATH',target):
                for data in ({'entries':[]},{'entries':[{'approved':False}]},{'entries':[{'approved':True}]}):
                    source.write_text(json.dumps(data))
                    with self.assertRaises(ValueError):import_reviewed(source)
                    self.assertFalse(target.exists())
                    self.assertFalse(list(target.parent.glob('.terms-*')))

    def test_check_cli_does_not_create_database_or_register_corpus(self):
        import contextlib,io
        from urs.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'missing.json';db=Path(tmp)/'unused.sqlite'
            with patch('sys.argv',['urs','--data',str(db),'check-terminology',str(source)]),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:main()
            self.assertEqual(error.exception.code,1)
            self.assertFalse(db.exists())

    def test_missing_is_unverified(self):
        with tempfile.TemporaryDirectory() as tmp,patch('urs.terminology.PATH',Path(tmp)/'absent.json'):
            self.assertEqual(load()['status'],'UNVERIFIED')

    def test_provenance_required_and_changes_invalidate_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'terms.json'
            with patch('urs.terminology.PATH',path):
                before=fingerprint()
                entry={k:'synthetic fixture only' for k in ('english','korean','context','organization','document','edition','location','reviewer')}
                entry.update(url='https://example.org/reference',scope='manufacturer',approved=True)
                path.write_text(json.dumps({'entries':[entry]}))
                self.assertEqual(load()['entries'][0]['scope'],'manufacturer')
                self.assertNotEqual(before,fingerprint())
                first=digest();entry['approved']=False
                path.write_text(json.dumps({'entries':[entry]}))
                self.assertNotEqual(first,digest())
                with self.assertRaises(ValueError):load()

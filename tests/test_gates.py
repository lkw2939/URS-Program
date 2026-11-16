import unittest

from urs.gates import Evidence, Stage, Status, can_advance


class GateTests(unittest.TestCase):
    def setUp(self):
        self.stage = Stage('source', ('hash', 'coverage'))
        self.results = [Evidence(c, 'v1', Status.PASS, f'evidence/{c}.json')
                        for c in self.stage.required_checks]

    def test_all_required_checks(self):
        self.assertTrue(can_advance(self.stage, 'v1', self.results))

    def test_missing_result_blocks(self):
        self.assertFalse(can_advance(self.stage, 'v1', self.results[:1]))

    def test_every_nonpassing_status_blocks(self):
        for status in Status:
            if status != Status.PASS:
                with self.subTest(status=status):
                    results = [self.results[0], Evidence('coverage', 'v1', status, 'log')]
                    self.assertFalse(can_advance(self.stage, 'v1', results))

    def test_edit_invalidates_previous_results(self):
        self.assertFalse(can_advance(self.stage, 'v2', self.results))

    def test_no_evidence_reference_blocks(self):
        self.assertFalse(can_advance(self.stage, 'v1', [self.results[0], Evidence('coverage', 'v1', Status.PASS, '')]))

    def test_ambiguous_results_block(self):
        self.assertFalse(can_advance(self.stage, 'v1', self.results + self.results[:1]))

    def test_empty_or_duplicate_definition_blocks(self):
        for checks in [(), ('hash', 'hash')]:
            self.assertFalse(can_advance(Stage('bad', checks), 'v1', self.results))
        self.assertFalse(can_advance(self.stage, '', self.results))

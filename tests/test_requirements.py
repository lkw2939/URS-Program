import json
import unittest
from pathlib import Path


class RequirementCoverage(unittest.TestCase):
    def test_all_33_and_five_additional_requirements_have_stages(self):
        mapping = json.loads((Path(__file__).resolve().parents[1] / 'docs/requirements-map.json').read_text())
        expected = {f'{group}{n}' for group, count in {'A':4, 'B':4, 'C':7, 'D':4, 'E':5, 'F':5, 'G':4}.items()
                    for n in range(1, count + 1)} | {f'추가{n}' for n in range(1,6)}
        self.assertEqual(set(mapping), expected)
        for requirement, stages in mapping.items():
            with self.subTest(requirement=requirement):
                self.assertTrue(stages)
                self.assertTrue(all(type(s) is int and 1 <= s <= 9 for s in stages))

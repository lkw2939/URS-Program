import unittest
from urs.quality import translation_issues,quantities


class QuantityMeaningTests(unittest.TestCase):
    def issues(self,source,target):
        return translation_issues([{'id':'requirement','text':source}],{'requirement':target})

    def test_same_numbers_and_units_wrongly_associated_fail(self):
        issues=self.issues('Length 120 mm; speed 60 packs/min.','길이 120 packs/min, 속도 60 mm.')
        self.assertIn('quantity_unit',{i['type'] for i in issues})
        self.assertNotIn('numbers',{i['type'] for i in issues})

    def test_compact_dimensions_cannot_silently_change(self):
        issues=self.issues('Length 120mm.','길이 102mm.')
        self.assertIn('numbers',{i['type'] for i in issues})
        self.assertIn('quantity_unit',{i['type'] for i in issues})

    def test_same_number_different_unit_fails(self):
        self.assertIn('quantity_unit',{i['type'] for i in self.issues('Length 120 mm.','길이 120 cm.')})

    def test_localized_korean_units_keep_pairs(self):
        self.assertEqual(self.issues('Length 120mm; speed 60 packs/min.','길이 120밀리미터, 속도 60팩/분입니다.'),[])

    def test_indonesian_pack_rate(self):
        self.assertEqual(quantities('Kecepatan 60 kemasan/menit.'),quantities('속도 60팩/분.'))

    def test_order_can_change_without_changing_quantity_relationship(self):
        self.assertEqual(self.issues('Width 60mm; length 120mm.','길이 120mm, 너비 60mm.'),[])

    def test_composite_unknown_units_not_partially_reinterpreted(self):
        self.assertEqual(quantities('Load 120 N/mm2; speed 60 mm/s.'),{})

    def test_unit_omission_requires_review(self):
        self.assertIn('quantity_unit',{i['type'] for i in self.issues('Weight 120 kg.','중량 120.')})

    def test_si_prefix_case_is_not_silently_equated(self):
        self.assertIn('quantity_unit',{i['type'] for i in self.issues('Length 120 Mm.','길이 120 mm.')})

    def test_sentence_final_punctuation_does_not_drop_numeric_value(self):
        self.assertEqual(self.issues('Count 165.','수량은 165입니다.'),[])

    def test_changed_unitless_value_at_sentence_end_is_detected(self):
        self.assertIn('numbers',{i['type'] for i in self.issues('Count 165.','수량 160.')})

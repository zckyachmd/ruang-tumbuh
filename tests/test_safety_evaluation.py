"""Synthetic language regression set; expectations are NOT clinician-validated."""
import unittest
from ruang_tumbuh.safety import route

# Explicit current signs, negation, history, educational intent and mixed clauses.
# No real family or patient data is used in this set.
CASES = [
    ('bayi tidak bernapas', 'emergency'),
    ('anak tidak bernafas', 'emergency'),
    ('bayi sulit bernapas', 'emergency'),
    ('anak sulit dibangunkan', 'emergency'),
    ('bayi kejang', 'emergency'),
    ('bibir anak kebiruan', 'emergency'),
    ('bayi tidak merespons', 'emergency'),
    ('blue lips', 'emergency'),
    ('tidak sesak', None),
    ('tidak ada kejang', None),
    ('nggak mengalami kejang', None),
    ('bibir tidak biru', None),
    ('belum ada kejang', None),
    ('bukan kejang', None),
    ('anak tidak sesak nafas', None),
    ('anak tidak lagi kejang', None),
    ('kemarin bayi kejang', 'health_boundary'),
    ('dulu bibirnya biru', 'health_boundary'),
    ('apa itu kejang?', 'health_boundary'),
    ('jelaskan tanda sesak', 'health_boundary'),
    ('catat kejang kemarin', None),
    ('ringkasan riwayat kejang', None),
    ('tidak kejang, tapi sekarang tidak bernapas', 'emergency'),
    ('kemarin kejang, sekarang sulit dibangunkan', 'emergency'),
    ('apa itu kejang? sekarang bayi tidak bernapas', 'emergency'),
    ('bibir tidak biru tapi bayi kejang', 'emergency'),
    ('tidak sesak, namun bibirnya biru', 'emergency'),
    ('catat bayi kejang sekarang', 'emergency'),
    ('bayi kejang; tadi tidak sesak', 'emergency'),
    ('nggak ada kejang. sekarang tidak merespons', 'emergency'),
    ('bibir tidak bergerak dan biru', 'emergency'),
    ('riwayat kejang sedang terjadi lagi', 'emergency'),
    ('anak pernah kejang', 'health_boundary'),
    ('bayi kejang tadi', 'health_boundary'),
    ('kemarin bayi sulit bernapas, sekarang sudah pulih', 'health_boundary'),
    ('pernah sesak, sekarang bayi tidak bernapas', 'emergency'),
    ('bayi kejang tadi masih berlangsung', 'emergency'),
    ('berapa dosis obat?', 'health_boundary'),
    ('kenapa bayi demam?', 'health_boundary'),
    ('napasnya cepat kenapa?', 'health_boundary'),
    ('apakah anak aman?', 'health_boundary'),
    ('apakah data anak aman?', None),
    ('jam 9 ASIP 60 ml', None),
    ('ringkasan hari ini', None),
    ('catat tersedak kemarin', None),
]


def evaluate(router=route):
    results = [(index + 1, expected, router(message)) for index, (message, expected) in enumerate(CASES)]
    labels = ('emergency', 'health_boundary', 'none')
    confusion = {expected: {actual: 0 for actual in labels} for expected in labels}
    for _, expected, actual in results:
        confusion[expected or 'none'][actual or 'none'] += 1
    return {
        'synthetic_cases': len(results),
        'routing_mismatches': [index for index, expected, actual in results if expected != actual],
        'confusion_counts': confusion,
        'emergency_false_negatives': sum(expected == 'emergency' and actual != 'emergency' for _, expected, actual in results),
        'emergency_false_positives': sum(expected != 'emergency' and actual == 'emergency' for _, expected, actual in results),
        'health_boundary_false_negatives': sum(expected == 'health_boundary' and actual != 'health_boundary' for _, expected, actual in results),
        'health_boundary_false_positives': sum(expected != 'health_boundary' and actual == 'health_boundary' for _, expected, actual in results),
        'clinical_validation': 'pending',
    }


class SyntheticSafetyEvaluation(unittest.TestCase):
    def test_synthetic_language_expectations(self):
        result = evaluate()
        self.assertEqual(result['synthetic_cases'], 45)
        self.assertEqual(result['routing_mismatches'], [], result)
        self.assertEqual(result['emergency_false_positives'], 0)
        self.assertEqual(result['emergency_false_negatives'], 0)
        self.assertEqual(result['health_boundary_false_positives'], 0)
        self.assertEqual(result['health_boundary_false_negatives'], 0)


if __name__ == '__main__':
    import json
    print(json.dumps(evaluate(), sort_keys=True))

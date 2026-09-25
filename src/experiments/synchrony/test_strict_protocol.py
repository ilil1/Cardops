import unittest

import pandas as pd

from .strict_benchmark import checked_training_mask, validate_protocol


class FrozenProtocolTests(unittest.TestCase):
    def test_future_validation_labels_cannot_select_earlier_model(self):
        with self.assertRaisesRegex(ValueError, 'Development outcome'):
            validate_protocol(['2026-02-28'], '2026-03-30', ['2026-03-31'], 60)
        validate_protocol(['2026-02-28'], '2026-03-30', ['2026-03-31'], 30)

    def test_test_months_stay_excluded_for_entire_frozen_evaluation(self):
        frame = pd.DataFrame({'customer_id': [1, 1, 1, 1],
            'as_of_date': pd.to_datetime(['2025-12-31', '2026-02-28', '2026-03-31', '2026-04-30']),
            'y_close_30': [0, 0, 0, 1], 'y_close_60': [0, 0, 1, 1]})
        dates = ['2026-03-31', '2026-04-30']
        self.assertEqual(checked_training_mask(frame, '2026-03-30', 30, None, dates).tolist(), [True, True, False, False])
        self.assertEqual(checked_training_mask(frame, '2026-03-30', 60, None, dates).tolist(), [True, False, False, False])
        # Using a later training cutoff must fail once test observations mature.
        with self.assertRaisesRegex(ValueError, 'entered training'):
            checked_training_mask(frame, '2026-06-30', 30, None, dates)

    def test_freeze_must_precede_first_test(self):
        with self.assertRaisesRegex(ValueError, 'before every evaluation'):
            validate_protocol(['2025-12-31'], '2026-04-01', ['2026-03-31'], 30)


if __name__ == '__main__':
    unittest.main()

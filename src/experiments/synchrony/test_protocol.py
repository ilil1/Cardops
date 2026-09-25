"""Focused checks for temporal leakage and prediction population correctness."""
import unittest

import numpy as np
import pandas as pd

from .benchmark import CONFIRMATION, DEVELOPMENT, development_dates, train_mask
from .data import snapshot
from .models import prepare_features


class TemporalProtocolTests(unittest.TestCase):
    def source(self):
        customers = pd.DataFrame({
            'Customer_ID': [1, 2, 3],
            'Credit_Card_Open_Date': pd.to_datetime(['2024-12-01', '2025-02-01', '2024-12-01']),
            'Credit_Card_Closed_Date': pd.to_datetime(['2025-02-20', None, '2025-01-20']),
        }).set_index('Customer_ID')
        tx = pd.DataFrame({
            'Customer_ID': [1, 1], 'Transaction_ID': ['past', 'future'],
            'Transaction_Date': pd.to_datetime(['2025-01-10', '2025-02-10']),
            'Transaction_Type': ['Sale', 'Sale'], 'Transaction_Amount': [20., 999.],
            'Number_of_Transactions': [2., 99.], 'Payment_Code': [3, 3], 'Category_Code': [1, 2],
        })
        tx['month'] = tx.Transaction_Date.dt.to_period('M')
        return customers, tx

    def test_future_transactions_and_outcomes_cannot_change_features(self):
        customers, tx = self.source()
        first, columns = snapshot(customers, tx, '2025-01-31', pd.Timestamp('2024-08-01'), pd.Timestamp('2025-04-30'))
        changed = customers.copy()
        changed.loc[1, 'Credit_Card_Closed_Date'] = pd.Timestamp('2025-04-20')
        tx.loc[1, 'Transaction_Amount'] = 999999.
        tx.loc[1, 'Number_of_Transactions'] = 9999.
        second, _ = snapshot(changed, tx, '2025-01-31', pd.Timestamp('2024-08-01'), pd.Timestamp('2025-04-30'))
        pd.testing.assert_frame_equal(first[columns], second[columns])
        pd.testing.assert_frame_equal(prepare_features(first, columns), prepare_features(second, columns))
        self.assertEqual(first.customer_id.tolist(), [1])
        self.assertEqual(first.y_close_30.tolist(), [1])
        self.assertEqual(second.y_close_30.tolist(), [0])
        self.assertNotEqual(first.y_next_card_amount.iloc[0], second.y_next_card_amount.iloc[0])

    def test_training_requires_full_horizon_to_have_elapsed(self):
        frame = pd.DataFrame({'as_of_date': pd.to_datetime(['2024-12-31', '2025-01-31', '2025-02-28']),
                              'y_close_30': [0, 1, 0]})
        # February has only 28 days: January's 30-day label is not yet available.
        self.assertEqual(train_mask(frame, pd.Timestamp('2025-02-28'), 30).tolist(), [True, False, False])

    def test_30_day_development_dates_are_preserved(self):
        self.assertEqual(development_dates(30), DEVELOPMENT)

    def test_development_labels_mature_before_confirmation(self):
        # February's 60-day outcome is unavailable before the first March test.
        self.assertEqual(development_dates(60), ['2025-10-31', '2025-12-31'])
        for horizon in (30, 60):
            for date in development_dates(horizon):
                with self.subTest(horizon=horizon, date=date):
                    label_end = pd.Timestamp(date) + pd.Timedelta(days=horizon)
                    self.assertLess(label_end, pd.Timestamp(CONFIRMATION[0]))

    def test_incomplete_future_is_not_labeled_negative(self):
        customers, tx = self.source()
        frame, _ = snapshot(customers, tx, '2025-01-31', pd.Timestamp('2024-08-01'), pd.Timestamp('2025-02-15'))
        self.assertTrue(np.isnan(frame.y_close_30.iloc[0]))
        self.assertTrue(np.isnan(frame.y_next_card_count.iloc[0]))


if __name__ == '__main__':
    unittest.main()

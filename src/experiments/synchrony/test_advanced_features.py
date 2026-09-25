"""Synthetic tests of additional dated features; no held-out outcomes used."""
import unittest

import numpy as np
import pandas as pd

from .advanced_features import build_advanced_features
from .data import snapshot


class AdvancedFeatureTests(unittest.TestCase):
    def source(self):
        customers = pd.DataFrame({
            'Customer_ID': [1, 2, 3, 4],
            'Credit_Card_Open_Date': pd.to_datetime(['2024-01-01', '2024-01-01', '2025-02-01', '2024-01-01']),
            'Credit_Card_Closed_Date': pd.to_datetime(['2025-02-20', None, None, '2025-01-31']),
            'Credit_Card_Limit': [1000, 2000, 3000, 4000],
        }).set_index('Customer_ID')
        rows = [
            # A future row, ignored even when its quantities are subsequently corrupted.
            (1, 'f', '2025-02-10', 'Sale', 999., 99., 3, 2),
            (1, 'a', '2025-01-31', 'Sale', 30., 3., 2, 2),
            (1, 'b', '2025-01-31', 'Sale', 20., 2., 3, 1),
            (1, 'c', '2025-01-20', 'Sale', 50., 5., 1, 2),
            (1, 'd', '2025-01-10', 'Sale', 100., 10., 3, 1),
            # January 1 is the lower boundary and excluded from the 30-day window.
            (1, 'e', '2025-01-01', 'Sale', 100., 10., 5, 3),
            (1, 'g', '2024-12-01', 'Sale', 100., 10., 2, 1),
            (1, 'h', '2024-09-01', 'Sale', 100., 10., 3, 3),
            # Returns have missing counts in the real source and do not enter Sale features.
            (1, 'r', '2025-01-30', 'Return', 300., np.nan, 3, 1),
            (4, 'closed', '2025-01-20', 'Sale', 500., 5., 3, 1),
        ]
        tx = pd.DataFrame(rows, columns=[
            'Customer_ID', 'Transaction_ID', 'Transaction_Date', 'Transaction_Type',
            'Transaction_Amount', 'Number_of_Transactions', 'Payment_Code', 'Category_Code',
        ])
        tx.Transaction_Date = pd.to_datetime(tx.Transaction_Date)
        tx['month'] = tx.Transaction_Date.dt.to_period('M')
        return customers, tx

    def test_values_windows_eligibility_and_date_aggregation(self):
        customers, tx = self.source()
        actual = build_advanced_features(customers, tx, '2025-01-31')
        self.assertEqual(actual.index.tolist(), [1, 2])
        self.assertEqual(actual.index.name, 'Customer_ID')
        self.assertEqual(actual.shape, (2, 60))
        self.assertEqual(actual.loc[1, 'adv_payment_3_count_30'], 12)
        self.assertEqual(actual.loc[1, 'adv_payment_3_amount_30'], 120)
        self.assertEqual(actual.loc[1, 'adv_payment_5_amount_30'], 0)
        self.assertAlmostEqual(actual.loc[1, 'adv_payment_2_amount_share_change_30v60'], .15 - .5, places=6)
        self.assertEqual(actual.loc[1, 'adv_other_credit_recency'], 0)
        self.assertEqual(actual.loc[1, 'adv_other_credit_more_recent'], 0)
        self.assertAlmostEqual(actual.loc[1, 'adv_last3_purchase_days_target_count_share'], .6, places=6)
        self.assertAlmostEqual(actual.loc[1, 'adv_last3_purchase_days_target_amount_share'], .6, places=6)
        self.assertAlmostEqual(actual.loc[1, 'adv_last3_purchase_days_target_day_fraction'], 2 / 3, places=6)
        # Target card category distribution switched completely since prior 90 days.
        self.assertAlmostEqual(actual.loc[1, 'adv_target_category_mix_change_90v90'], 1., places=6)
        self.assertEqual(actual.loc[1, 'adv_target_category_hhi_90'], 1.)

    def test_future_changes_cannot_change_features_or_sources(self):
        customers, tx = self.source()
        original_customers, original_tx = customers.copy(deep=True), tx.copy(deep=True)
        first = build_advanced_features(customers, tx, '2025-01-31')
        pd.testing.assert_frame_equal(customers, original_customers)
        pd.testing.assert_frame_equal(tx, original_tx)
        changed_customers = customers.copy()
        changed_customers.loc[1, 'Credit_Card_Closed_Date'] = pd.Timestamp('2025-04-20')
        changed_customers['Credit_Card_Limit'] *= 99
        changed_tx = tx.copy()
        future = changed_tx.Transaction_Date.gt(pd.Timestamp('2025-01-31'))
        changed_tx.loc[future, 'Transaction_Amount'] = np.nan
        changed_tx.loc[future, 'Number_of_Transactions'] = -100
        changed_tx.loc[future, 'Payment_Code'] = 5
        changed_tx.loc[future, 'Category_Code'] = 9
        second = build_advanced_features(changed_customers, changed_tx, '2025-01-31')
        pd.testing.assert_frame_equal(first, second)

    def test_row_order_and_arbitrary_transaction_ids_are_irrelevant(self):
        customers, tx = self.source()
        first = build_advanced_features(customers, tx, '2025-01-31')
        shuffled = tx.sample(frac=1, random_state=42).copy()
        shuffled['Transaction_ID'] = [f'new-{i}' for i in range(len(shuffled))]
        second = build_advanced_features(customers, shuffled, '2025-01-31')
        pd.testing.assert_frame_equal(first, second)

    def test_missing_history_is_finite_and_identifiers_are_not_columns(self):
        customers, tx = self.source()
        frame = build_advanced_features(customers, tx, '2025-01-31')
        empty = frame.loc[2]
        self.assertEqual(empty.adv_other_credit_recency, 999)
        self.assertEqual(empty.drop('adv_other_credit_recency').sum(), 0)
        self.assertTrue(np.isfinite(frame.to_numpy()).all())
        self.assertFalse(any('customer_id' in name.lower() for name in frame.columns))
        self.assertFalse(any(name.startswith(('y_', 'meta_')) for name in frame.columns))

    def test_empty_transactions_and_empty_eligible_population(self):
        customers, tx = self.source()
        frame = build_advanced_features(customers, tx.iloc[:0], '2025-01-31')
        self.assertEqual(frame.shape, (2, 60))
        empty = build_advanced_features(customers, tx, '2023-01-31')
        self.assertEqual(empty.shape, (0, 60))

    def test_advanced_join_preserves_existing_feature_and_label_contract(self):
        customers, tx = self.source()
        before, columns = snapshot(customers, tx, '2025-01-31', pd.Timestamp('2024-08-01'), pd.Timestamp('2025-04-30'))
        advanced = build_advanced_features(customers, tx, '2025-01-31')
        joined = before.join(advanced, on='customer_id', validate='one_to_one')
        after, after_columns = snapshot(customers, tx, '2025-01-31', pd.Timestamp('2024-08-01'), pd.Timestamp('2025-04-30'))
        self.assertEqual(columns, after_columns)
        pd.testing.assert_frame_equal(before, after)
        pd.testing.assert_frame_equal(joined[before.columns], before)
        self.assertEqual(before.y_close_30.tolist(), [1, 0])

    def test_invalid_observed_purchase_quantities_are_rejected(self):
        customers, tx = self.source()
        for bad in (np.nan, np.inf, -1):
            with self.subTest(bad=bad):
                changed = tx.copy()
                changed.loc[1, 'Number_of_Transactions'] = bad
                with self.assertRaisesRegex(ValueError, 'finite and nonnegative'):
                    build_advanced_features(customers, changed, '2025-01-31')


if __name__ == '__main__':
    unittest.main()

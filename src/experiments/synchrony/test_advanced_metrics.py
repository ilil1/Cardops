import unittest

import numpy as np
import pandas as pd

from .advanced_metrics import (_order, _ranking_inputs, _weighted_metrics, metrics,
                               paired_customer_bootstrap, score_rank, top_mask)


class AdvancedRankingTests(unittest.TestCase):
    def test_equal_scores_are_invariant_to_input_order(self):
        ids = np.array([f'customer-{i}' for i in range(31)])
        scores = np.ones(len(ids))
        permutation = np.random.default_rng(18).permutation(len(ids))
        original = set(ids[top_mask(scores, ids)])
        permuted = set(ids[permutation][top_mask(scores[permutation], ids[permutation])])
        self.assertEqual(original, permuted)
        self.assertEqual(len(original), 4)
        ranks = score_rank(scores, ids)
        reverse = np.argsort(permutation)
        np.testing.assert_array_equal(ranks, score_rank(scores[permutation], ids[permutation])[reverse])

    def test_rank_and_selection_preserve_score_order(self):
        ids = np.arange(11)
        scores = np.arange(11, dtype=float)
        self.assertEqual(set(ids[top_mask(scores, ids)]), {9, 10})
        self.assertTrue(np.all(np.diff(score_rank(scores, ids)) > 0))
        self.assertEqual(score_rank([5], ['only']).tolist(), [1.])
        self.assertEqual(top_mask(scores, ids, fraction=0).sum(), 0)
        self.assertEqual(top_mask(scores, ids, fraction=1).sum(), 11)

    def test_integer_weighting_exactly_matches_repeated_rows(self):
        rng = np.random.default_rng(2026)
        ids = np.array([f'c-{i}' for i in range(29)])
        y = np.arange(len(ids)) % 2
        scores, normalized = _ranking_inputs(rng.integers(0, 4, len(ids)), ids)
        for _ in range(12):
            weights = rng.integers(0, 5, len(ids))
            index = np.repeat(np.arange(len(ids)), weights)
            expected = metrics(y[index], scores[index], ids[index])
            actual = _weighted_metrics(y, scores, weights, _order(scores, normalized))
            for key in expected:
                self.assertAlmostEqual(actual[key], expected[key], places=12, msg=key)

    def test_invalid_inputs_fail_without_silent_coercion(self):
        for scores, ids in [([], []), ([np.nan], ['a']), ([1, 2], ['a']),
                            ([[1]], ['a']), ([1], [None]), ([1], [''])]:
            with self.assertRaises(ValueError):
                top_mask(scores, ids)
        for y in ([.5, 1], [0, np.nan], [0]):
            with self.assertRaises(ValueError):
                metrics(y, [.1, .2], ['a', 'b'])
        with self.assertRaises(ValueError):
            top_mask([1], ['a'], fraction=1.1)

    def test_single_class_metrics_are_explicit(self):
        result = metrics([0, 0], [.1, .2], ['a', 'b'])
        self.assertTrue(np.isnan(result['auc']))
        self.assertEqual(result['top10_recall'], 0.)
        self.assertEqual(result['ap'], 0.)


class PairedBootstrapTests(unittest.TestCase):
    def setUp(self):
        ids = np.arange(24)
        self.base = pd.DataFrame({'customer_id': ids, 'as_of_date': '2025-10-31',
                                  'y_close_60': ids % 2, 'score': ids % 5 / 5})
        self.new = self.base.copy()
        self.new['score'] = self.new.y_close_60 * .8 + self.new.score * .1

    def test_repeated_customer_months_are_sampled_together(self):
        one = paired_customer_bootstrap(self.base, self.new, 'y_close_60', reps=30)
        base2 = self.base.assign(as_of_date='2025-11-30')
        new2 = self.new.assign(as_of_date='2025-11-30')
        two = paired_customer_bootstrap(pd.concat([self.base, base2]),
                                        pd.concat([self.new, new2]), 'y_close_60', reps=30)
        self.assertEqual(one['observed_mean_delta'], two['observed_mean_delta'])
        self.assertEqual(one['mean_delta_95_interval'], two['mean_delta_95_interval'])

    def test_row_order_does_not_change_bootstrap(self):
        expected = paired_customer_bootstrap(self.base, self.new, 'y_close_60', reps=20)
        actual = paired_customer_bootstrap(self.base.sample(frac=1, random_state=4),
                                           self.new.sample(frac=1, random_state=9),
                                           'y_close_60', reps=20)
        self.assertEqual(actual, expected)

    def test_identical_predictions_produce_zero_intervals(self):
        result = paired_customer_bootstrap(self.base, self.base, 'y_close_60', reps=20)
        for interval in result['mean_delta_95_interval'].values():
            self.assertEqual(interval, [0., 0.])

    def test_populations_labels_and_duplicate_keys_must_match(self):
        with self.assertRaisesRegex(ValueError, 'populations differ'):
            paired_customer_bootstrap(self.base, self.new.iloc[:-1], 'y_close_60', reps=5)
        changed = self.new.copy()
        changed.loc[0, 'y_close_60'] = 1
        with self.assertRaisesRegex(ValueError, 'labels differ'):
            paired_customer_bootstrap(self.base, changed, 'y_close_60', reps=5)
        with self.assertRaisesRegex(ValueError, 'duplicate observation'):
            paired_customer_bootstrap(pd.concat([self.base, self.base.iloc[:1]]),
                                       self.new, 'y_close_60', reps=5)


if __name__ == '__main__':
    unittest.main()

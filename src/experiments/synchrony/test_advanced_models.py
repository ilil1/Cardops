import unittest
import numpy as np
import pandas as pd

from .advanced_models import CANDIDATES, CONTROLS, development_gate, predict_bundle


def results(values):
    return {'folds': [{'top10_recall': v} for v in values],
            'mean_top10_recall': float(np.mean(values))}


class AdvancedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.development = {name: results([.3] * 6) for name in CANDIDATES}

    def test_gate_requires_both_controls_and_consistency(self):
        self.development['tenure_control'] = results([.33] * 6)
        self.development['behavior_lr'] = results([.34] * 6)
        selection = development_gate(self.development)
        self.assertFalse(selection['new_candidate_passed'])
        self.assertEqual(selection['selected'], 'tenure_control')
        self.assertEqual(selection['best_new_diagnostic'], 'behavior_lr')
        self.development['behavior_lr'] = results([.37, .37, .37, .37, .37, .30])
        self.assertFalse(development_gate(self.development)['new_candidate_passed'])
        self.development['behavior_lr'] = results([.36] * 6)
        self.assertEqual(development_gate(self.development)['selected'], 'behavior_lr')

    def test_high_mean_from_few_months_does_not_pass(self):
        self.development['behavior_cat'] = results([.6, .6, .3, .3, .3, .3])
        selection = development_gate(self.development)
        self.assertFalse(selection['new_candidate_passed'])
        self.assertEqual(selection['selected'], CONTROLS[0])

    def test_blend_is_fixed_ranks_and_never_fits(self):
        class Hazard:
            def predict(self, frame):
                return np.array([.01, .04, .03, .02])

        class Classifier:
            def predict_proba(self, frame):
                values = np.array([.9, .1, .4, .8])
                return np.c_[1 - values, values]

        bundle = {'name': 'hazard_behavior_blend', 'components': [
            {'name': 'duration_hazard', 'model': Hazard()},
            {'name': 'behavior_cat', 'model': Classifier()}]}
        score = predict_bundle(bundle, pd.DataFrame(index=range(4)), [10, 20, 30, 40])
        np.testing.assert_allclose(score, [.5, .5, .5, .5])


if __name__ == '__main__':
    unittest.main()

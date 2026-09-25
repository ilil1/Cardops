"""Independent small-data oracles and future-information invariance checks."""
import unittest

import numpy as np
import pandas as pd

from .duration_model import DurationHazardModel


class DurationHazardTests(unittest.TestCase):
    def example(self):
        return pd.DataFrame({
            'Credit_Card_Open_Date': pd.to_datetime(['2025-01-01', '2025-01-02', '2024-12-31', '2025-01-04']),
            'Credit_Card_Closed_Date': pd.to_datetime(['2025-01-03', '2025-01-10', '2025-01-01', '2025-01-04']),
        })

    def test_hand_calculated_weighted_risk_days_and_closes(self):
        # cutoff Jan 4, half-life 1: Jan 2/3/4 weights are 1/4, 1/2, 1.
        # A contributes ages 1,2; B contributes 0,1,2; C closed before entry;
        # D opens and closes at age 0 on Jan 4 (included last risk day).
        model = DurationHazardModel(2, bandwidth_days=0, half_life_days=1, prior_exposure=2)
        model.fit(self.example(), '2025-01-02', '2025-01-04')
        np.testing.assert_allclose(model.exposure_by_age_[:3], [1.25, .75, 1.5])
        np.testing.assert_allclose(model.events_by_age_[:3], [1, 0, .5])
        self.assertAlmostEqual(model.global_hazard_, 3 / 7)
        self.assertEqual(model.fit_account_count_, 3)
        # Two prior risk-days at hazard 3/7 give hazards 4/7, 24/77, 19/49.
        np.testing.assert_allclose(model.hazard_by_age_[:3], [4/7, 24/77, 19/49])
        predicted = model.predict(pd.DataFrame({'tenure_days': [0, 1, 2]}))
        np.testing.assert_allclose(predicted, [1-(53/77)*(30/49), 1-(30/49)*(4/7), 1-(4/7)**2])

    def test_interval_accumulator_matches_explicit_daily_oracle(self):
        source = self.example()
        start, cutoff = pd.Timestamp('2025-01-02'), pd.Timestamp('2025-01-04')
        model = DurationHazardModel(30).fit(source, start, cutoff)
        exposure = np.zeros_like(model.exposure_by_age_)
        events = np.zeros_like(model.events_by_age_)
        for row in source.itertuples():
            opening, closing = row.Credit_Card_Open_Date, row.Credit_Card_Closed_Date
            end = min(closing, cutoff) if pd.notna(closing) else cutoff
            for day in pd.date_range(max(opening, start), end):
                weight = .5 ** ((cutoff - day).days / 180)
                age = (day - opening).days
                exposure[age] += weight
                if day == closing:
                    events[age] += weight
        np.testing.assert_allclose(model.exposure_by_age_, exposure, atol=1e-12)
        np.testing.assert_allclose(model.events_by_age_, events, atol=1e-12)

    def test_future_closes_and_future_openings_cannot_change_fit(self):
        source = self.example()
        reference = DurationHazardModel(60).fit(source, '2025-01-02', '2025-01-04')
        changed = source.copy()
        changed.loc[1, 'Credit_Card_Closed_Date'] = pd.NaT
        changed.loc[len(changed)] = [pd.Timestamp('2025-04-01'), pd.Timestamp('2025-05-01')]
        changed['Customer_ID'] = [987, 654, 321, 123, 456]
        changed['Credit_Card_Limit'] = [1, 1e9, -1, 99, 0]
        fitted = DurationHazardModel(60).fit(changed, '2025-01-02', '2025-01-04')
        np.testing.assert_array_equal(reference.exposure_by_age_, fitted.exposure_by_age_)
        np.testing.assert_array_equal(reference.events_by_age_, fitted.events_by_age_)
        np.testing.assert_array_equal(reference.hazard_by_age_, fitted.hazard_by_age_)
        frame = pd.DataFrame({'tenure_days': [0, 40, 4000, 9000]})
        np.testing.assert_array_equal(reference.predict(frame), fitted.predict(frame))
        changed.loc[1, 'Credit_Card_Closed_Date'] = pd.Timestamp('2026-07-31')
        later = DurationHazardModel(60).fit(changed, '2025-01-02', '2025-01-04')
        np.testing.assert_array_equal(reference.predict(frame), later.predict(frame))

    def test_long_tenure_and_tail_extrapolation_are_finite(self):
        source = pd.DataFrame({
            'Credit_Card_Open_Date': pd.to_datetime(['2000-01-01', '2000-01-02']),
            'Credit_Card_Closed_Date': pd.to_datetime(['2025-01-03', None]),
        })
        model = DurationHazardModel(60).fit(source, '2025-01-01', '2025-01-04')
        self.assertGreater(model.observed_age_max_, 4000)
        value = model.predict(pd.DataFrame({'tenure_days': [0, 4000, 9500, 100000]}))
        self.assertTrue(np.isfinite(value).all())
        self.assertTrue(((value >= 0) & (value <= 1)).all())
        np.testing.assert_allclose(value[-2:], 1-(1-model.global_hazard_)**60)

    def test_horizon_consistency_and_zero_events(self):
        models = [DurationHazardModel(h).fit(self.example(), '2025-01-02', '2025-01-04') for h in [30, 60]]
        frame = pd.DataFrame({'tenure_days': [0, 1, 2, 4000]})
        self.assertTrue((models[1].predict(frame) >= models[0].predict(frame)).all())
        source = self.example()
        source['Credit_Card_Closed_Date'] = pd.NaT
        no_events = DurationHazardModel(60).fit(source, '2025-01-02', '2025-01-04')
        np.testing.assert_array_equal(no_events.predict(frame), np.zeros(4))

    def test_certain_event_does_not_break_prefix_subtraction(self):
        source = pd.DataFrame({
            'Credit_Card_Open_Date': [pd.Timestamp('2025-01-01')],
            'Credit_Card_Closed_Date': [pd.Timestamp('2025-01-01')],
        })
        model = DurationHazardModel(30, bandwidth_days=0, prior_exposure=0).fit(source, '2025-01-01', '2025-01-01')
        np.testing.assert_array_equal(model.predict(pd.DataFrame({'tenure_days': [0, 4000, 9999]})), np.ones(3))

    def test_invalid_observation_and_prediction_are_rejected(self):
        model = DurationHazardModel(30)
        with self.assertRaisesRegex(ValueError, 'observation_start'):
            model.fit(self.example(), '2025-01-05', '2025-01-04')
        with self.assertRaisesRegex(ValueError, 'No observable'):
            model.fit(self.example(), '2024-01-01', '2024-01-02')
        model.fit(self.example(), '2025-01-02', '2025-01-04')
        for invalid in [-1, .5, np.nan, np.inf, float(2**63)]:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'whole days'):
                model.predict(pd.DataFrame({'tenure_days': [invalid]}))


if __name__ == '__main__':
    unittest.main()

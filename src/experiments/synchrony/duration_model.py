"""Calendar-weighted daily card-duration hazard, using dated account events only.

For account i opened on O_i, a day t is in its risk set when
max(O_i, observation_start) <= t <= min(observed_close_i, cutoff).
Both endpoints are included: an observed close is an event on its last risk day.
Missing closes and closes after the fit cutoff are censored at that cutoff.
An account's age on day t is a = (t - O_i).days, including age zero.

With w(t) = 2 ** (-(cutoff - t).days / half_life_days), E[a] sums weighted
risk days and D[a] sums weighted observed closes at age a. A normalized Gaussian
kernel K smooths both arrays. The daily hazard is

    h[a] = ((K * D)[a] + prior_exposure * global_hazard)
           / ((K * E)[a] + prior_exposure),
    global_hazard = sum(D) / sum(E).

For an open account with tenure d, predict 1 - product(1 - h[d+j], j=1..horizon).
Thus neither the opening day nor a known past day is predicted a second time.
Outside the observed age range, use the fitted global daily hazard. This is a
conservative explicit fallback, not evidence that tail risk is actually constant.

Assumptions: supplied rows are distinct accounts and include the full eligible
population, including accounts without merchant revisits. Opening/closing dates
must be available by their event dates. Continuous account-at-risk observation
between these dates is assumed; merchant transactions do not establish that
coverage. Historical membership in a final customer file may itself be selected.
The fit cutoff must be within the source's verified observation coverage.
No customer identifiers, final static attributes, or transaction data are used.
"""
from __future__ import annotations

import numbers

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d


class DurationHazardModel:
    def __init__(self, horizon, bandwidth_days=45, half_life_days=180, prior_exposure=500):
        if (not isinstance(horizon, numbers.Integral) or isinstance(horizon, bool)
                or horizon <= 0 or horizon > np.iinfo(np.int64).max // 4):
            raise ValueError('horizon must be a positive integer number of days')
        for name, value, allow_zero in (
            ('bandwidth_days', bandwidth_days, True),
            ('half_life_days', half_life_days, False),
            ('prior_exposure', prior_exposure, True),
        ):
            if not np.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
                raise ValueError(f'{name} must be finite and {"nonnegative" if allow_zero else "positive"}')
        self.horizon = int(horizon)
        self.bandwidth_days = float(bandwidth_days)
        self.half_life_days = float(half_life_days)
        self.prior_exposure = float(prior_exposure)

    @staticmethod
    def _day(value, name):
        result = pd.Timestamp(value)
        if pd.isna(result) or result.tzinfo is not None:
            raise ValueError(f'{name} must be a nonmissing timezone-naive date')
        return result.normalize()

    def fit(self, customers, observation_start, cutoff):
        start = self._day(observation_start, 'observation_start')
        cutoff = self._day(cutoff, 'cutoff')
        if start > cutoff:
            raise ValueError('observation_start must not follow cutoff')
        required = ['Credit_Card_Open_Date', 'Credit_Card_Closed_Date']
        if any(column not in customers for column in required):
            raise ValueError('Opening and closing date columns are required')
        # Only these two fields are read, and every future close becomes missing.
        opened = pd.to_datetime(customers[required[0]], errors='raise').dt.normalize()
        closed = pd.to_datetime(customers[required[1]], errors='raise').dt.normalize()
        if opened.dt.tz is not None or closed.dt.tz is not None:
            raise ValueError('Account dates must be timezone-naive')
        closed = closed.where(closed.le(cutoff))
        candidate = opened.notna() & opened.le(cutoff)
        if (candidate & closed.notna() & closed.lt(opened)).any():
            raise ValueError('Observed close precedes account opening')
        first = opened.clip(lower=start)
        last = closed.fillna(cutoff)
        eligible = candidate & first.le(last)
        if not eligible.any():
            raise ValueError('No observable account risk days before cutoff')
        opened, first, last, closed = (
            values.loc[eligible] for values in (opened, first, last, closed)
        )
        left = (first - opened).dt.days.to_numpy(dtype=np.int64)
        right = (last - opened).dt.days.to_numpy(dtype=np.int64)
        cutoff_age = (cutoff - opened).dt.days.to_numpy(dtype=np.int64)
        self.observed_age_min_ = int(left.min())
        self.observed_age_max_ = int(right.max())
        grid_max = max(4000, self.observed_age_max_)
        n = grid_max + 1
        decay = np.log(2.0) / self.half_life_days

        # Reverse age recurrence. This multiplies by exp(-decay) <= 1,
        # avoiding exp(+decay * age) overflow and customer-by-calendar expansion.
        # Entry at R_i contributes w(O_i + R_i); remove it below L_i.
        enter = np.zeros(n, dtype=float)
        leave = np.zeros(n, dtype=float)
        np.add.at(enter, right, np.exp(-decay * (cutoff_age - right)))
        nonzero_left = left > 0
        np.add.at(leave, left[nonzero_left] - 1,
                  np.exp(-decay * (cutoff_age[nonzero_left] - left[nonzero_left] + 1)))
        exposure = np.zeros(n, dtype=float)
        carry = 0.0
        q = np.exp(-decay)
        for age in range(self.observed_age_max_, -1, -1):
            carry = carry * q + enter[age] - leave[age]
            # Roundoff around interval subtraction can produce tiny negatives.
            if carry < -1e-8 * max(1, len(left)):
                raise ArithmeticError('Negative duration exposure after accumulation')
            carry = max(carry, 0.0)
            exposure[age] = carry
        event = np.zeros(n, dtype=float)
        observed_event = closed.notna().to_numpy()
        event_age = right[observed_event]
        np.add.at(event, event_age,
                  np.exp(-decay * (cutoff_age[observed_event] - event_age)))
        if exposure.sum() <= 0:
            raise ValueError('All risk-day weights underflowed; choose an observable cutoff')
        global_hazard = float(np.clip(event.sum() / exposure.sum(), 0, 1))
        if self.bandwidth_days:
            smooth_exposure = gaussian_filter1d(exposure, self.bandwidth_days, mode='constant', cval=0)
            smooth_event = gaussian_filter1d(event, self.bandwidth_days, mode='constant', cval=0)
        else:
            smooth_exposure, smooth_event = exposure, event
        denominator = smooth_exposure + self.prior_exposure
        hazard = np.full(n, global_hazard, dtype=float)
        np.divide(smooth_event + self.prior_exposure * global_hazard,
                  denominator, out=hazard, where=denominator > 0)
        hazard = np.clip(hazard, 0, 1)
        hazard[:self.observed_age_min_] = global_hazard
        hazard[self.observed_age_max_ + 1:] = global_hazard
        certain = hazard >= 1
        log_survival = np.zeros(n)
        log_survival[~certain] = np.log1p(-hazard[~certain])
        self.exposure_by_age_ = exposure
        self.events_by_age_ = event
        self.hazard_by_age_ = hazard
        self.global_hazard_ = global_hazard
        self.log_survival_prefix_ = np.r_[0.0, np.cumsum(log_survival)]
        self.certain_event_prefix_ = np.r_[0, np.cumsum(certain)]
        self.observation_start_ = start
        self.cutoff_ = cutoff
        self.fit_account_count_ = int(len(left))
        return self

    def predict(self, frame):
        if not hasattr(self, 'hazard_by_age_'):
            raise ValueError('Model must be fitted before prediction')
        if 'tenure_days' not in frame:
            raise ValueError('tenure_days is required')
        tenure = np.asarray(frame['tenure_days'], dtype=float)
        if (tenure.ndim != 1 or not np.isfinite(tenure).all() or (tenure < 0).any()
                or (tenure != np.floor(tenure)).any()
                or (tenure > np.iinfo(np.int64).max // 4).any()):
            raise ValueError('tenure_days must contain finite nonnegative whole days')
        tenure = tenure.astype(np.int64)
        grid_size = len(self.hazard_by_age_)
        first = np.minimum(tenure + 1, grid_size)
        after_last = np.minimum(tenure + self.horizon + 1, grid_size)
        log_survival = self.log_survival_prefix_[after_last] - self.log_survival_prefix_[first]
        certain = self.certain_event_prefix_[after_last] - self.certain_event_prefix_[first]
        remaining = self.horizon - (after_last - first)
        if self.global_hazard_ >= 1:
            certain += remaining
        else:
            log_survival += remaining * np.log1p(-self.global_hazard_)
        result = -np.expm1(log_survival)
        result[certain > 0] = 1.0
        return np.clip(result, 0, 1)

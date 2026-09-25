"""Model candidates fixed before the temporal comparison.

Only dated transaction history and known card opening dates are used. Scores
are ranking scores; class-balanced classifiers are not calibrated probabilities.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, SplineTransformer, StandardScaler


def signed_log(values):
    return np.sign(values) * np.log1p(np.abs(values))


def prepare_features(frame: pd.DataFrame, original: list[str]) -> pd.DataFrame:
    """Deterministic point-in-time transformations; never read outcome columns."""
    forbidden = [c for c in original if c.startswith(('y_', 'meta_')) or c in ('customer_id', 'as_of_date')]
    if forbidden:
        raise ValueError(f'Forbidden input features: {forbidden}')
    x = frame[original].astype('float32').copy()
    day = (pd.to_datetime(frame.as_of_date) - pd.Timestamp('2024-08-01')).dt.days
    extra = {'calendar_days': day, 'opening_calendar_days': day - x.tenure_days}
    observed = x.observed_card_days.clip(lower=1)
    extra['card_recency_observed'] = x.card_recency.where(x.card_ever_seen.eq(1), observed)
    extra['card_recency_fraction'] = np.minimum(extra['card_recency_observed'], observed) / observed
    extra['no_card_purchase'] = 1 - x.card_ever_seen
    extra['no_purchase'] = 1 - x.all_ever_seen
    extra['tenure_sin_year'] = np.sin(2 * np.pi * x.tenure_days / 365.25)
    extra['tenure_cos_year'] = np.cos(2 * np.pi * x.tenure_days / 365.25)
    extra['days_to_anniversary'] = 365.25 - (x.tenure_days % 365.25)
    for days in (30, 90, 180):
        exposure = observed.clip(upper=days)
        extra[f'card_exposure_{days}'] = exposure / days
        extra[f'card_count_rate_{days}'] = x[f'card_count_{days}'] / exposure * 30
        extra[f'card_amount_rate_{days}'] = x[f'card_amount_{days}'] / exposure * 30
    extra['card_log_count_decline'] = np.log1p(x.card_count_30) - np.log1p((x.card_count_90 - x.card_count_30).clip(lower=0) / 2)
    extra['card_log_amount_decline'] = np.log1p(x.card_amount_30) - np.log1p((x.card_amount_90 - x.card_amount_30).clip(lower=0) / 2)
    extra['all_log_count_decline'] = np.log1p(x.all_count_30) - np.log1p((x.all_count_90 - x.all_count_30).clip(lower=0) / 2)
    result = pd.concat([x, pd.DataFrame(extra, index=x.index)], axis=1).astype('float32')
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError('Non-finite feature value')
    return result


CORE = [
    'tenure_days', 'observed_card_days', 'inverse_tenure',
    'calendar_days', 'month_sin', 'month_cos',
    'card_recency_observed', 'card_recency_fraction', 'all_recency',
    'no_card_purchase', 'no_purchase',
    'card_count_rate_30', 'card_count_rate_90', 'card_count_rate_180',
    'card_amount_rate_90', 'card_spend_share_90',
    'card_log_count_decline', 'card_log_amount_decline', 'all_log_count_decline',
    'card_count_active_months', 'card_interval_mean', 'card_interval_std',
    'all_count_90', 'all_amount_90', 'other_history_rows',
    'card_history_count_per_row', 'card_history_amount_per_count',
    'card_return_rows_90', 'card_return_amount_90',
    'card_share_change_1v3', 'card_exposure_180',
]
SPLINE = ['tenure_days', 'observed_card_days', 'card_recency_observed', 'all_recency']

# Training windows and candidate definitions are fixed before scoring comparisons.
CANDIDATES = {
    'reference_lr210': {'kind': 'reference', 'window': None},
    'lr_core': {'kind': 'linear', 'window': None},
    'lr_core_recent6': {'kind': 'linear', 'window': 6},
    'spline_tenure': {'kind': 'spline_tenure', 'window': None},
    'spline_behavior': {'kind': 'spline', 'window': None},
    'spline_recent6': {'kind': 'spline', 'window': 6},
    'catboost_depth4': {'kind': 'cat4', 'window': None},
    'catboost_recent6': {'kind': 'cat4', 'window': 6},
    'catboost_depth6': {'kind': 'cat6', 'window': None},
    'hgb_core': {'kind': 'hgb', 'window': None},
}


def classifier(name: str, original: list[str], all_features: list[str], threads: int = 4):
    kind = CANDIDATES[name]['kind']
    if kind == 'reference':
        return make_pipeline(
            ColumnTransformer([('features', 'passthrough', original)], remainder='drop'),
            FunctionTransformer(signed_log), SelectKBest(f_classif, k=40), StandardScaler(),
            LogisticRegression(C=.1, class_weight='balanced', solver='newton-cholesky', max_iter=100),
        )
    if kind in ('linear', 'spline', 'spline_tenure'):
        if kind == 'linear':
            transform = ColumnTransformer([('linear', make_pipeline(FunctionTransformer(signed_log), StandardScaler()), CORE)])
        else:
            smooth = ['tenure_days', 'observed_card_days'] if kind == 'spline_tenure' else SPLINE
            linear = ['calendar_days', 'month_sin', 'month_cos'] if kind == 'spline_tenure' else [c for c in CORE if c not in smooth]
            transform = ColumnTransformer([
                ('spline', make_pipeline(FunctionTransformer(signed_log),
                    SplineTransformer(n_knots=6, degree=3, knots='quantile', extrapolation='linear', include_bias=False),
                    StandardScaler()), smooth),
                ('linear', make_pipeline(FunctionTransformer(signed_log), StandardScaler()), linear),
            ])
        return make_pipeline(transform,
            LogisticRegression(C=.03, class_weight='balanced', solver='newton-cholesky', max_iter=100))
    if kind.startswith('cat'):
        from catboost import CatBoostClassifier
        return make_pipeline(ColumnTransformer([('features', 'passthrough', all_features)]),
            CatBoostClassifier(iterations=300, depth=4 if kind == 'cat4' else 6,
                learning_rate=.04, l2_leaf_reg=30, loss_function='Logloss',
                random_seed=42, thread_count=threads, verbose=False,
                allow_writing_files=False, border_count=64))
    return make_pipeline(ColumnTransformer([('features', 'passthrough', CORE)]),
        HistGradientBoostingClassifier(max_iter=180, learning_rate=.04, max_leaf_nodes=7,
            min_samples_leaf=150, l2_regularization=20, max_bins=127,
            early_stopping=False, random_state=42))

"""Small fixed candidate set for frozen-model temporal reevaluation."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .models import CORE, prepare_features, signed_log

RELIABILITY = [
    'card_zero_rows', 'card_single_row', 'card_multiple_rows',
    'card_interval_available', 'all_interval_available',
    'card_active_month_fraction', 'card_count_deviation',
    'card_return_purchase_ratio', 'card_share_drop',
]
TENURE = ['tenure_days', 'observed_card_days', 'inverse_tenure', 'calendar_days', 'month_sin', 'month_cos']
CANDIDATES = {
    'original_reference': {'kind': 'original', 'window': None},
    'previous_core6': {'kind': 'core', 'window': 6},
    'tenure_control': {'kind': 'tenure', 'window': 6},
    'core9': {'kind': 'core', 'window': 9},
    'core_decay90': {'kind': 'core', 'window': None, 'half_life_days': 90},
    'reliable_core6': {'kind': 'reliable', 'window': 6},
    'reliable_decay180': {'kind': 'reliable', 'window': None, 'half_life_days': 180},
    'catboost_core4': {'kind': 'cat', 'window': 9},
}


def prepare_strict_features(frame, original):
    features = prepare_features(frame, original)
    rows = features.card_history_rows
    count_previous = features[[f'card_lag{i}_count' for i in range(1, 6)]]
    extra = {
        'card_zero_rows': rows.eq(0).astype(float),
        'card_single_row': rows.eq(1).astype(float),
        'card_multiple_rows': rows.ge(2).astype(float),
        'card_interval_available': features.card_interval_count.gt(0).astype(float),
        'all_interval_available': features.all_interval_count.gt(0).astype(float),
        'card_active_month_fraction': features.card_count_active_months /
            (features.observed_card_days.clip(lower=30, upper=180) / 30),
        'card_count_deviation': (features.card_lag0_count - count_previous.mean(axis=1)) /
            (count_previous.std(axis=1) + 1),
        'card_return_purchase_ratio': features.card_return_amount_90 / (features.card_amount_90 + 1),
        'card_share_drop': features.card_spend_share_90 - features.card_spend_share_180,
    }
    return pd.concat([features, pd.DataFrame(extra, index=features.index)], axis=1).astype('float32')


def make_model(name, horizon, original, threads=3):
    kind = CANDIDATES[name]['kind']
    if kind == 'original':
        select = ColumnTransformer([('features', 'passthrough', original)])
        if horizon == 60:
            return make_pipeline(select, HistGradientBoostingClassifier(
                max_iter=180, learning_rate=.05, max_leaf_nodes=7, min_samples_leaf=100,
                l2_regularization=10, max_bins=127, early_stopping=False, random_state=42))
        return make_pipeline(select, FunctionTransformer(signed_log), SelectKBest(f_classif, k=40),
            StandardScaler(), LogisticRegression(C=.1, class_weight='balanced',
                solver='newton-cholesky', max_iter=100))
    columns = TENURE if kind == 'tenure' else CORE + (RELIABILITY if kind in ('reliable', 'cat') else [])
    select = ColumnTransformer([('features', 'passthrough', columns)])
    if kind == 'cat':
        from catboost import CatBoostClassifier
        return make_pipeline(select, CatBoostClassifier(iterations=300, depth=4,
            learning_rate=.04, l2_leaf_reg=30, loss_function='Logloss',
            random_seed=42, thread_count=threads, verbose=False,
            allow_writing_files=False, border_count=64))
    return make_pipeline(select, FunctionTransformer(signed_log), StandardScaler(),
        LogisticRegression(C=.03, class_weight='balanced', solver='newton-cholesky', max_iter=100))


def fit_model(model, x, y, dates, cutoff, spec):
    kwargs = {}
    if 'half_life_days' in spec:
        elapsed = (pd.Timestamp(cutoff) - pd.to_datetime(dates)).dt.days.to_numpy()
        weights = .5 ** (elapsed / spec['half_life_days'])
        weights /= weights.mean()
        kwargs[f'{model.steps[-1][0]}__sample_weight'] = weights
    return model.fit(x, y, **kwargs)

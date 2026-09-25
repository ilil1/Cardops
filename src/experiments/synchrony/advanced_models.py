"""Fixed hypothesis-driven candidates; no fitting or selection on later periods."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .models import CORE, signed_log
from .strict_models import make_model as strict_model, prepare_strict_features

BEHAVIOR = [
    'adv_payment_2_count_90', 'adv_payment_2_amount_90',
    'adv_payment_2_count_share_change_30v60', 'adv_payment_2_amount_share_change_30v60',
    'adv_payment_3_count_share_change_30v60', 'adv_payment_3_amount_share_change_30v60',
    'adv_other_credit_seen', 'adv_other_credit_more_recent', 'adv_target_to_other_credit_gap_days',
    'adv_last3_purchase_days_target_count_share', 'adv_last6_purchase_days_target_count_share',
    'adv_last3_purchase_days_target_amount_share', 'adv_last3_purchase_days_target_day_fraction',
    'adv_all_category_hhi_90', 'adv_target_category_hhi_90',
    'adv_all_category_mix_change_90v90', 'adv_target_category_mix_change_90v90',
    'adv_payment_entropy_90',
]
KNOTS = [30, 90, 180, 365, 730, 1095]
DURATION_CALENDAR = ['duration_log', 'duration_calendar'] + [f'duration_hinge_{k}' for k in KNOTS]
DURATION_CALENDAR += [f'{c}_calendar' for c in DURATION_CALENDAR if c != 'duration_calendar']
CONTROLS = ['previous_core6', 'tenure_control']
CANDIDATES = CONTROLS + [
    'duration_hazard', 'tenure_calendar_lr', 'behavior_lr', 'behavior_cat',
    'hazard_behavior_blend', 'tenure_behavior_blend',
]
COMPONENTS = {
    'hazard_behavior_blend': ['duration_hazard', 'behavior_cat'],
    'tenure_behavior_blend': ['tenure_calendar_lr', 'behavior_lr'],
}


def prepare_advanced_features(frame, original, additional):
    keys = ['customer_id', 'as_of_date']
    if frame[keys].duplicated().any() or additional[keys].duplicated().any():
        raise ValueError('Duplicate feature observation keys')
    aligned = frame[keys].merge(additional[keys + BEHAVIOR], how='left', on=keys,
                                sort=False, validate='one_to_one')
    aligned.index = frame.index
    x = prepare_strict_features(frame, original)
    age_log = np.log1p(x.tenure_days / 30)
    calendar = x.calendar_days / 365.25
    duration = {'duration_log': age_log, 'duration_calendar': calendar}
    duration.update({f'duration_hinge_{k}': (age_log - np.log1p(k / 30)).clip(lower=0) for k in KNOTS})
    duration.update({f'{c}_calendar': value * calendar for c, value in list(duration.items())
                     if c != 'duration_calendar'})
    x = pd.concat([x, aligned[BEHAVIOR], pd.DataFrame(duration, index=frame.index)], axis=1).astype('float32')
    if not np.isfinite(x.to_numpy()).all():
        raise ValueError('Missing or nonfinite advanced features')
    return x


def make_model(name, horizon, original, threads=3):
    if name in CONTROLS:
        return strict_model(name, horizon, original, threads)
    columns = DURATION_CALENDAR if name == 'tenure_calendar_lr' else CORE + BEHAVIOR
    select = ColumnTransformer([('features', 'passthrough', columns)])
    if name == 'behavior_cat':
        from catboost import CatBoostClassifier
        return make_pipeline(select, CatBoostClassifier(iterations=300, depth=4,
            learning_rate=.04, l2_leaf_reg=30, loss_function='Logloss',
            random_seed=42, thread_count=threads, verbose=False,
            allow_writing_files=False, border_count=64))
    if name not in ('tenure_calendar_lr', 'behavior_lr'):
        raise ValueError(f'No standalone classifier for {name}')
    steps = [select]
    if name == 'behavior_lr':
        steps.append(FunctionTransformer(signed_log))
    return make_pipeline(*steps, StandardScaler(), LogisticRegression(
        C=.03, class_weight='balanced', solver='newton-cholesky', max_iter=100))


def predict_bundle(bundle, x, customer_ids):
    """Rank blends require the full intended customer cohort at one cutoff."""
    from .advanced_metrics import score_rank
    name = bundle['name']
    if name in COMPONENTS:
        scores = [predict_bundle(child, x, customer_ids) for child in bundle['components']]
        return np.mean([score_rank(s, customer_ids) for s in scores], axis=0)
    if name == 'duration_hazard':
        return bundle['model'].predict(x)
    return bundle['model'].predict_proba(x)[:, 1]


def development_gate(development):
    """Frozen practical gate against BOTH controls; no evaluation input."""
    diagnostics = {}
    for name in CANDIDATES[len(CONTROLS):]:
        by_control = {}
        values = np.array([f['top10_recall'] for f in development[name]['folds']])
        for reference in CONTROLS:
            baseline = np.array([f['top10_recall'] for f in development[reference]['folds']])
            delta = values - baseline
            by_control[reference] = {
                'mean_gain': float(delta.mean()), 'improved_months': int((delta > 0).sum()),
                'worst_month_gain': float(delta.min()),
                'passed': bool(delta.mean() >= .02 and (delta > 0).sum() >= 4 and delta.min() >= -.02),
            }
        diagnostics[name] = {'comparisons': by_control,
                             'passed': all(v['passed'] for v in by_control.values())}
    eligible = [name for name in diagnostics if diagnostics[name]['passed']]
    key = lambda name: development[name]['mean_top10_recall']
    best_new = max(CANDIDATES[len(CONTROLS):], key=key)
    selected = max(eligible or CONTROLS, key=key)
    return {'selected': selected, 'best_new_diagnostic': best_new,
            'new_candidate_passed': bool(eligible), 'gate': diagnostics}

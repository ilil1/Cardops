"""Predeclared six-origin development and frozen, previously exposed verification."""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .advanced_metrics import metrics, top_mask
from .advanced_models import (CANDIDATES, COMPONENTS, CONTROLS, BEHAVIOR,
                              development_gate, make_model, predict_bundle, prepare_advanced_features)
from .benchmark import aggregate, write_json
from .data import read_source
from .duration_model import DurationHazardModel
from .strict_benchmark import checked_training_mask, validate_protocol, FREEZE_DATE, EVALUATION

DEVELOPMENT = ['2025-07-31', '2025-08-31', '2025-09-30', '2025-10-31', '2025-11-30', '2025-12-31']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def early_warning(predictions, customers, outcome):
    positive = predictions.loc[predictions[outcome].eq(1)].copy()
    close = positive.customer_id.map(customers.Credit_Card_Closed_Date)
    positive['lead_days'] = (close - pd.to_datetime(positive.as_of_date)).dt.days
    alerted = positive.loc[positive.top10]
    early = alerted.loc[alerted.lead_days.ge(14)]
    first = alerted.groupby('customer_id').lead_days.max()
    return {
        'positive_customer_months': len(positive),
        'unique_closing_customers': int(positive.customer_id.nunique()),
        'true_positive_alert_customer_months': len(alerted),
        'unique_closing_customers_alerted': int(alerted.customer_id.nunique()),
        'unique_closing_customers_with_14_day_opportunity': int(positive.loc[positive.lead_days.ge(14), 'customer_id'].nunique()),
        'unique_closing_customers_alerted_at_least_14_days_before': int(early.customer_id.nunique()),
        'median_first_alert_lead_days': float(first.median()) if len(first) else None,
        'definition': 'Only alerts inside the target horizon count. Deduplicated within evaluated monthly origins; no assumed alerts before evaluation.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--additional', type=Path, required=True)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--horizon', type=int, choices=[30, 60], required=True)
    parser.add_argument('--threads', type=int, default=3)
    args = parser.parse_args()
    out = args.output / f'classification_{args.horizon}'
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'selection.json').exists():
        raise ValueError('Use a fresh output directory; do not silently overwrite completed selection')
    dates = EVALUATION[args.horizon]
    validate_protocol(DEVELOPMENT, FREEZE_DATE, dates, args.horizon)
    protocol = {
        'horizon_days': args.horizon, 'development_dates': DEVELOPMENT,
        'freeze_date': FREEZE_DATE, 'evaluation_dates': dates,
        'candidates': CANDIDATES, 'additional_model_features': BEHAVIOR,
        'selection': 'mean development Recall@10%; both-control gate +2pp mean, >=4/6 improved months, worst month >=-2pp',
        'diagnostic_evaluation': 'development-best new candidate evaluated even if gate fails; no reselection afterward',
        'same_customer_past_future_allowed': True, 'test_previously_inspected': True,
        'no_updates_during_evaluation': True,
        'score_semantics': 'ranking score, not validated individual churn probability; blends depend on entire cutoff cohort',
        'code_sha256': {p.name: sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
        'plan_sha256': sha(Path('docs/synchrony_improvement_plan.md')),
        'snapshots_sha256': sha(args.snapshots), 'source_sha256': sha(args.source_zip),
        'features_sha256': sha(args.features), 'additional_sha256': sha(args.additional),
        'hazard_settings': {'bandwidth_days': 45, 'half_life_days': 180, 'prior_exposure': 500},
        'classification_settings': {'window_months': 6, 'lr_C': .03, 'cat_depth': 4, 'cat_iterations': 300},
        'tie_break': 'label-independent deterministic hash of customer ID, shared across candidates',
    }
    write_json(out / 'protocol.json', protocol)
    frame = pd.read_pickle(args.snapshots)
    original = json.loads(args.features.read_text())
    x = prepare_advanced_features(frame, original, pd.read_pickle(args.additional))
    customers, transactions = read_source(args.source_zip)
    observation_start = transactions.Transaction_Date.min()
    del transactions
    outcome = f'y_close_{args.horizon}'
    result = {'protocol': protocol, 'development': {n: {'folds': []} for n in CANDIDATES}, 'evaluation': {}}

    def fit_at(cutoff, requested):
        fitted = {}

        def fit_one(name):
            if name in fitted:
                return fitted[name]
            if name in COMPONENTS:
                children = [fit_one(child) for child in COMPONENTS[name]]
                bundle = {'name': name, 'components': children,
                          'audit': {'component_audits': {child['name']: child['audit'] for child in children}}}
            elif name == 'duration_hazard':
                model = DurationHazardModel(horizon=args.horizon, **protocol['hazard_settings'])
                model.fit(customers, observation_start, cutoff)
                bundle = {'name': name, 'model': model, 'audit': {
                    'event_and_exposure_cutoff': str(cutoff),
                    'observation_start': str(observation_start.date()),
                    'uses_future_closure_dates': False,
                    'training_evaluation_key_overlap': 0,
                    'training_unit': 'calendar-weighted at-risk customer days, not labelled monthly snapshots',
                }}
            else:
                train = checked_training_mask(frame, cutoff, args.horizon, 6, dates)
                if not train.any():
                    raise ValueError('No matured training data')
                model = make_model(name, args.horizon, original, args.threads)
                model.fit(x.loc[train], frame.loc[train, outcome].astype(int))
                bundle = {'name': name, 'model': model, 'audit': {
                    'training_rows': int(train.sum()),
                    'training_first_as_of': str(frame.loc[train, 'as_of_date'].min().date()),
                    'training_last_as_of': str(frame.loc[train, 'as_of_date'].max().date()),
                    'training_label_end_max': str((frame.loc[train, 'as_of_date'] + pd.Timedelta(days=args.horizon)).max().date()),
                    'training_evaluation_key_overlap': 0,
                }}
            bundle.update(horizon_days=args.horizon, as_of_date=str(cutoff),
                          original_features=original, feature_preparation='advanced',
                          score_semantics=protocol['score_semantics'])
            fitted[name] = bundle
            return bundle

        return {name: fit_one(name) for name in requested}

    with threadpool_limits(limits=args.threads):
        for date in DEVELOPMENT:
            fitted = fit_at(date, CANDIDATES)
            valid = frame.as_of_date.eq(pd.Timestamp(date))
            for name in CANDIDATES:
                score = predict_bundle(fitted[name], x.loc[valid], frame.loc[valid, 'customer_id'])
                m = {'date': date, **metrics(frame.loc[valid, outcome], score, frame.loc[valid, 'customer_id'])}
                result['development'][name]['folds'].append(m)
                print('DEVELOPMENT', args.horizon, name, json.dumps(m), flush=True)
            write_json(out / 'results.json', result)
        for summary in result['development'].values():
            summary.update(aggregate(summary['folds']))
        selection = development_gate(result['development'])
        result['selection'] = selection
        write_json(out / 'selection.json', selection)
        write_json(out / 'results.json', result)
        selection_hash = sha(out / 'selection.json')
        print('SELECTED', args.horizon, json.dumps(selection), flush=True)
        compared = list(dict.fromkeys(CONTROLS + [selection['selected'], selection['best_new_diagnostic']]))
        frozen = fit_at(FREEZE_DATE, compared)
        hashes = {}
        for name, bundle in frozen.items():
            path = out / f'{name}.joblib'
            joblib.dump(bundle, path, compress=3)
            hashes[name] = sha(path)
        del frozen
        # All final models have been fitted and saved. This stage only loads and predicts.
        for name in compared:
            bundle = joblib.load(out / f'{name}.joblib')
            folds, predictions = [], []
            for date in dates:
                test = frame.as_of_date.eq(pd.Timestamp(date))
                if frame.loc[test, outcome].isna().any():
                    raise ValueError('Incomplete evaluation follow-up')
                scores = predict_bundle(bundle, x.loc[test], frame.loc[test, 'customer_id'])
                m = {'date': date, **metrics(frame.loc[test, outcome], scores, frame.loc[test, 'customer_id'])}
                folds.append(m)
                pred = frame.loc[test, ['customer_id', 'as_of_date', outcome]].copy()
                pred['score'] = scores
                pred['top10'] = top_mask(scores, pred.customer_id)
                predictions.append(pred)
                print('FROZEN_EVALUATION', args.horizon, name, json.dumps(m), flush=True)
            predictions = pd.concat(predictions)
            predictions.to_csv(out / f'predictions_{name}.csv', index=False)
            if sha(out / f'{name}.joblib') != hashes[name] or sha(out / 'selection.json') != selection_hash:
                raise ValueError('Frozen model or selection changed during evaluation')
            result['evaluation'][name] = {'audit': bundle['audit'], 'artifact_sha256': hashes[name],
                'folds': folds, **aggregate(folds), 'early_warning': early_warning(predictions, customers, outcome)}
            write_json(out / 'results.json', result)
    print('COMPLETE', out / 'results.json', flush=True)


if __name__ == '__main__':
    main()

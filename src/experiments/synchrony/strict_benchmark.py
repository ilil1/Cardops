"""Frozen-model temporal reevaluation, with no test observations in training.

The source test periods were previously inspected. Freezing the partition now
does not make these periods an untouched independent test.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .benchmark import aggregate, metrics, train_mask, write_json
from .strict_models import CANDIDATES, fit_model, make_model, prepare_strict_features

DEVELOPMENT = ['2025-08-31', '2025-10-31', '2025-12-31']
FREEZE_DATE = '2026-03-30'
EVALUATION = {30: ['2026-03-31', '2026-04-30', '2026-05-31', '2026-06-30'],
              60: ['2026-03-31', '2026-04-30', '2026-05-31']}


def validate_protocol(development, freeze, evaluation, horizon):
    freeze = pd.Timestamp(freeze)
    if not evaluation or freeze >= min(pd.to_datetime(evaluation)):
        raise ValueError('Model must be frozen before every evaluation date')
    for date in pd.to_datetime(development):
        if date + pd.Timedelta(days=horizon) > freeze:
            raise ValueError('Development outcome not available at the freeze date')


def checked_training_mask(frame, cutoff, horizon, window, evaluation_dates):
    train = train_mask(frame, pd.Timestamp(cutoff), horizon, window)
    evaluation = frame.as_of_date.isin(pd.to_datetime(evaluation_dates))
    if (train & evaluation).any():
        raise ValueError('Evaluation observations entered training')
    if frame.loc[train, ['customer_id', 'as_of_date']].duplicated().any():
        raise ValueError('Duplicate training observation keys')
    return train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--horizon', type=int, choices=[30, 60], required=True)
    args = parser.parse_args()
    out = args.output / f'classification_{args.horizon}'
    out.mkdir(parents=True, exist_ok=True)
    dates = EVALUATION[args.horizon]
    validate_protocol(DEVELOPMENT, FREEZE_DATE, dates, args.horizon)
    protocol = {
        'horizon_days': args.horizon, 'development_dates': DEVELOPMENT,
        'freeze_date': FREEZE_DATE, 'evaluation_dates': dates,
        'candidates': CANDIDATES, 'selection': 'equal-month mean development AP; declaration order breaks ties',
        'evaluation_training_updates': False, 'test_previously_inspected': True,
        'same_customer_in_past_and_future_allowed': True,
        'selection_must_finish_before_any_evaluation': True,
        'limitations': [
            'Previously inspected periods remain reused temporal evaluation, not an untouched independent test.',
            'Tests evaluate existing customers again in future periods, not only previously unseen customers.',
            'Event dates are assumed to be available dates; source lacks ingestion timestamps.',
            'Ranking scores are not calibrated churn probabilities.',
        ],
        'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [
            Path(__file__), Path(__file__).with_name('strict_models.py'), Path(__file__).with_name('models.py')]},
        'feature_definition_sha256': hashlib.sha256(args.features.read_bytes()).hexdigest(),
    }
    write_json(out / 'protocol.json', protocol)
    frame = pd.read_pickle(args.snapshots)
    if frame[['customer_id', 'as_of_date']].duplicated().any():
        raise ValueError('Duplicate source observation keys')
    original = json.loads(args.features.read_text())
    x = prepare_strict_features(frame, original)
    if not np.isfinite(x.to_numpy()).all():
        raise ValueError('Non-finite input features')
    result = {'protocol': protocol, 'development': {}, 'evaluation': {}}
    outcome = f'y_close_{args.horizon}'

    def fit(name, cutoff):
        spec = CANDIDATES[name]
        train = checked_training_mask(frame, cutoff, args.horizon, spec['window'], dates)
        model = make_model(name, args.horizon, original)
        fit_model(model, x.loc[train], frame.loc[train, outcome].astype(int),
                  frame.loc[train, 'as_of_date'], cutoff, spec)
        return model, train

    with threadpool_limits(limits=3):
        for name in CANDIDATES:
            folds = []
            for date in DEVELOPMENT:
                model, train = fit(name, date)
                valid = frame.as_of_date.eq(pd.Timestamp(date))
                if (train & valid).any():
                    raise ValueError('Training/development rows overlap')
                m = {'date': date, **metrics(frame.loc[valid, outcome], model.predict_proba(x.loc[valid])[:, 1])}
                folds.append(m)
                print('DEVELOPMENT', args.horizon, name, json.dumps(m), flush=True)
            result['development'][name] = {'folds': folds, **aggregate(folds)}
            write_json(out / 'results.json', result)
        winner = max(result['development'], key=lambda name: result['development'][name]['mean_ap'])
        result['selected'] = winner
        write_json(out / 'selection.json', {'selected': winner, 'selection_data': DEVELOPMENT,
                                           'freeze_date': FREEZE_DATE})
        print('SELECTED', args.horizon, winner, flush=True)
        # Fit all compared models ONCE before scoring any evaluation observations.
        frozen = {}
        for name in dict.fromkeys(['original_reference', 'previous_core6', 'tenure_control', winner]):
            model, train = fit(name, FREEZE_DATE)
            path = out / f'{name}.joblib'
            joblib.dump({'model': model, 'original_features': original,
                'horizon_days': args.horizon, 'model_name': name,
                'as_of_date': FREEZE_DATE, 'feature_preparation': 'strict',
                'score_semantics': 'uncalibrated ranking score'}, path, compress=3)
            # Reloading models separates training from the evaluation stage.
            frozen[name] = (joblib.load(path), train, hashlib.sha256(path.read_bytes()).hexdigest())
        evaluation_keys = frame[frame.as_of_date.isin(pd.to_datetime(dates))][['customer_id', 'as_of_date']]
        for name, (bundle, train, artifact_hash) in frozen.items():
            training_keys = frame.loc[train, ['customer_id', 'as_of_date']]
            key_overlap = len(training_keys.merge(evaluation_keys, on=['customer_id', 'as_of_date']))
            if key_overlap:
                raise ValueError('Frozen training and evaluation observation keys overlap')
            audit = {
                'training_rows': int(train.sum()),
                'training_first_as_of': str(frame.loc[train, 'as_of_date'].min().date()),
                'training_last_as_of': str(frame.loc[train, 'as_of_date'].max().date()),
                'training_label_end_max': str((frame.loc[train, 'as_of_date'] + pd.Timedelta(days=args.horizon)).max().date()),
                'training_evaluation_key_overlap': key_overlap,
                'fit_calls_during_evaluation': 0, 'artifact_sha256': artifact_hash,
            }
            folds, predictions = [], []
            for date in dates:
                test = frame.as_of_date.eq(pd.Timestamp(date))
                scores = bundle['model'].predict_proba(x.loc[test])[:, 1]
                m = {'date': date, **metrics(frame.loc[test, outcome], scores)}
                m['customers_seen_in_training'] = int(frame.loc[test, 'customer_id'].isin(training_keys.customer_id).sum())
                folds.append(m)
                pred = frame.loc[test, ['customer_id', 'as_of_date', outcome]].copy()
                pred['score'] = scores
                predictions.append(pred)
                print('FROZEN_EVALUATION', args.horizon, name, json.dumps(m), flush=True)
            if hashlib.sha256((out / f'{name}.joblib').read_bytes()).hexdigest() != artifact_hash:
                raise ValueError('Frozen model artifact changed during evaluation')
            pd.concat(predictions).to_csv(out / f'predictions_{name}.csv', index=False)
            result['evaluation'][name] = {'audit': audit, 'folds': folds, **aggregate(folds)}
            write_json(out / 'results.json', result)
    print('COMPLETE', out / 'results.json', flush=True)


if __name__ == '__main__':
    main()

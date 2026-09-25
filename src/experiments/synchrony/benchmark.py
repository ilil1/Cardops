"""Finite temporal comparison; no selection on the confirmation periods.

Example:
  python -m src.experiments.synchrony.benchmark --snapshots path.pkl \
      --features features.json --output outputs/synchrony_tuning
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

from .models import CANDIDATES, classifier, prepare_features

DEVELOPMENT = ['2025-10-31', '2025-12-31', '2026-02-28']
CONFIRMATION = ['2026-03-31', '2026-04-30', '2026-05-31', '2026-06-30']


def development_dates(horizon):
    """Only select models using labels available before confirmation begins."""
    first_confirmation = pd.Timestamp(CONFIRMATION[0])
    return [date for date in DEVELOPMENT
            if pd.Timestamp(date) + pd.Timedelta(days=horizon) < first_confirmation]


def train_mask(frame, cutoff, horizon, window=None):
    dates = pd.to_datetime(frame.as_of_date)
    mask = dates.lt(cutoff) & (dates + pd.Timedelta(days=horizon)).le(cutoff)
    mask &= frame[f'y_close_{horizon}'].notna()
    if window is not None:
        mask &= dates.ge(cutoff - pd.DateOffset(months=window))
    return mask


def metrics(y, scores):
    y, scores = np.asarray(y, dtype=int), np.asarray(scores, dtype=float)
    k = int(np.ceil(len(y) * .1))
    top = np.argsort(-scores, kind='stable')[:k]
    return {'n': len(y), 'positive': int(y.sum()), 'prevalence': float(y.mean()),
        'auc': float(roc_auc_score(y, scores)), 'ap': float(average_precision_score(y, scores)),
        'top10_recall': float(y[top].sum() / y.sum()),
        'top10_precision': float(y[top].mean()), 'top10_caught': int(y[top].sum()),
        'top10_size': k}


def aggregate(folds):
    return {f'mean_{key}': float(np.mean([v[key] for v in folds]))
            for key in ['auc', 'ap', 'top10_recall', 'top10_precision']}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--horizon', type=int, choices=[30, 60], default=30)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    out = args.output / f'classification_{args.horizon}'
    out.mkdir(parents=True, exist_ok=True)
    protocol = {
        'horizon_days': args.horizon, 'development_dates': development_dates(args.horizon),
        'confirmation_dates': CONFIRMATION if args.horizon == 30 else CONFIRMATION[:-1],
        'candidates': CANDIDATES, 'selection': 'highest equal-month mean AP on development periods',
        'reference': 'reference_lr210',
        'confirmation_reused': True,
        'limitations': [
            'Confirmation periods were inspected in prior experiments; this is a repeated temporal backtest, not an untouched independent test.',
            'Only labels completely observable at each cutoff enter training. Same customers may reappear in later periods.',
            'No final customer metadata, identifiers, future outcomes, or dataset end date enter model inputs.',
            'Scores are rankings, not calibrated individual churn probabilities.',
            'Complete transaction observation and event-time availability remain assumptions of the source data.',
        ],
        'snapshot_path': str(args.snapshots.resolve()),
        'features_sha256': hashlib.sha256(args.features.read_bytes()).hexdigest(),
        'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [Path(__file__), Path(__file__).with_name('models.py')]},
        'python': platform.python_version(), 'sklearn': sklearn.__version__,
    }
    # Write the experiment contract before reading any model evaluation outcomes.
    write_json(out / 'protocol.json', protocol)
    frame = pd.read_pickle(args.snapshots)
    original = json.loads(args.features.read_text())
    features = prepare_features(frame, original)
    result = {'protocol': protocol, 'development': {}, 'confirmation': {}}
    path = out / 'results.json'

    def fit(name, date):
        date = pd.Timestamp(date)
        train = train_mask(frame, date, args.horizon, CANDIDATES[name]['window'])
        test = frame.as_of_date.eq(date) & frame[f'y_close_{args.horizon}'].notna()
        assert (frame.loc[train, 'as_of_date'] + pd.Timedelta(days=args.horizon)).le(date).all()
        model = classifier(name, original, list(features.columns), args.threads)
        start = time.monotonic()
        model.fit(features.loc[train], frame.loc[train, f'y_close_{args.horizon}'].astype(int))
        scores = model.predict_proba(features.loc[test])[:, 1]
        measured = metrics(frame.loc[test, f'y_close_{args.horizon}'], scores)
        measured.update({'date': str(date.date()), 'train_rows': int(train.sum()),
                         'fit_seconds': round(time.monotonic() - start, 2)})
        return model, test, scores, measured

    with threadpool_limits(limits=args.threads):
        for name in CANDIDATES:
            folds = []
            for date in protocol['development_dates']:
                model, test, scores, measured = fit(name, date)
                folds.append(measured)
                print('DEVELOPMENT', name, json.dumps(measured), flush=True)
            result['development'][name] = {'folds': folds, **aggregate(folds)}
            write_json(path, result)
        best = max(result['development'], key=lambda n: result['development'][n]['mean_ap'])
        result['selected'] = best
        write_json(path, result)
        print('SELECTED', best, flush=True)
        # The selected candidate is frozen here; confirmation cannot change it.
        names = list(dict.fromkeys(['reference_lr210', best]))
        for name in names:
            folds = []
            predictions = []
            for date in protocol['confirmation_dates']:
                model, test, scores, measured = fit(name, date)
                folds.append(measured)
                pred = frame.loc[test, ['customer_id', 'as_of_date', f'y_close_{args.horizon}']].copy()
                pred['score'] = scores
                predictions.append(pred)
                print('CONFIRMATION', name, json.dumps(measured), flush=True)
            result['confirmation'][name] = {'folds': folds, **aggregate(folds)}
            pd.concat(predictions).to_csv(out / f'predictions_{name}.csv', index=False)
            artifact = out / f'{name}.joblib'
            joblib.dump({'model': model, 'original_features': original,
                'model_features': list(features.columns), 'horizon_days': args.horizon,
                'model_name': name, 'as_of_date': protocol['confirmation_dates'][-1],
                'input_contract': 'Call models.prepare_features on monthly snapshots before predict_proba.',
                'score_semantics': 'uncalibrated ranking score'}, artifact, compress=3)
            # Check the reusable model actually reproduces the saved final scores.
            loaded = joblib.load(artifact)
            np.testing.assert_allclose(loaded['model'].predict_proba(features.loc[test])[:, 1], scores)
            result['confirmation'][name]['artifact_sha256'] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            write_json(path, result)
    print('COMPLETE', path, flush=True)


if __name__ == '__main__':
    main()

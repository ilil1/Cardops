"""Score an eligible monthly snapshot using a saved experiment model."""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .models import prepare_features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle = joblib.load(args.model)
    date = pd.Timestamp(args.as_of)
    if date < pd.Timestamp(bundle['as_of_date']):
        raise ValueError('This artifact was trained with labels unavailable at the requested historical cutoff')
    data = pd.read_pickle(args.snapshots)
    data = data[data.as_of_date.eq(date)]
    if data.empty:
        raise ValueError('No eligible customer snapshots at this cutoff')
    if bundle.get('feature_preparation') == 'strict':
        from .strict_models import prepare_strict_features
        features = prepare_strict_features(data, bundle['original_features'])
    else:
        features = prepare_features(data, bundle['original_features'])
    result = data[['customer_id', 'as_of_date']].copy()
    result['horizon_days'] = bundle['horizon_days']
    result['risk_score'] = bundle['model'].predict_proba(features)[:, 1]
    result = result.sort_values('risk_score', ascending=False, kind='stable')
    result['priority_rank'] = np.arange(1, len(result) + 1)
    result['top10_review_candidate'] = result.priority_rank.le(int(np.ceil(len(result) * .1)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f'Scored {len(result)} customers; score is not a calibrated churn probability: {args.output}')


if __name__ == '__main__':
    main()

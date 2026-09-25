"""Paired customer-block bootstrap for already frozen model comparisons.

Resampling a customer's entire history together preserves repeated monthly
observations and overlapping 60-day labels. These intervals quantify customer
sampling uncertainty within the observed months, not future calendar drift.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .benchmark import metrics, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--horizon', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replicates', type=int, default=200)
    args = parser.parse_args()
    a, b = pd.read_csv(args.baseline), pd.read_csv(args.candidate)
    label = f'y_close_{args.horizon}'
    keys = ['customer_id', 'as_of_date']
    paired = a.merge(b, on=keys, validate='one_to_one', suffixes=('_base', '_new'))
    if len(paired) != len(a) or len(paired) != len(b):
        raise ValueError('Prediction populations differ')
    np.testing.assert_array_equal(paired[label + '_base'], paired[label + '_new'])
    paired['block'], customers = pd.factorize(paired.customer_id)
    groups = list(paired.groupby('as_of_date', sort=True))
    rng = np.random.default_rng(20260925)
    deltas = []
    for _ in range(args.replicates):
        weights = np.bincount(rng.integers(0, len(customers), len(customers)), minlength=len(customers))
        per_month = []
        for date, frame in groups:
            index = np.repeat(np.arange(len(frame)), weights[frame.block.to_numpy()])
            sample = frame.iloc[index]
            base = metrics(sample[label + '_base'], sample.score_base)
            new = metrics(sample[label + '_new'], sample.score_new)
            per_month.append([new[key] - base[key] for key in ('auc', 'ap', 'top10_recall')])
        deltas.append(np.mean(per_month, axis=0))
    interval = np.quantile(np.array(deltas), [.025, .975], axis=0)
    write_json(args.output, {'replicates': args.replicates, 'seed': 20260925,
        'unit': 'customer, all months sampled together; paired models',
        'limitation': 'Fixed observed months; does not cover future drift or repeated model-development choices.',
        'mean_delta_95_interval': {key: interval[:, i].tolist()
            for i, key in enumerate(('auc', 'ap', 'top10_recall'))}})
    print(args.output, flush=True)


if __name__ == '__main__':
    main()

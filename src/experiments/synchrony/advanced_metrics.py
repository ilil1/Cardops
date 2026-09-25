"""Ranking metrics with reproducible, label-independent customer tie breaking.

Customer identifiers only break exact score ties; their numeric value never
enters the model or ranking. Bootstrap weights are integer customer replication
counts. The top-k calculation is exactly equivalent to repeating those rows,
including taking an integer number of copies of the customer at the boundary.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


@lru_cache(maxsize=262144)
def _customer_hash(identifier: str) -> int:
    return int.from_bytes(hashlib.blake2b(identifier.encode('utf-8'), digest_size=8,
                                        person=b'CardOpsRank-v1').digest(), 'big')


def _ranking_inputs(scores, customer_ids):
    try:
        values = np.asarray(scores, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError('Scores must be a finite numeric vector') from exc
    identifiers = np.asarray(customer_ids, dtype=object)
    if values.ndim != 1 or identifiers.ndim != 1:
        raise ValueError('Scores and customer IDs must be one-dimensional')
    if len(values) == 0 or len(values) != len(identifiers):
        raise ValueError('Scores and customer IDs must have the same nonzero length')
    if not np.isfinite(values).all():
        raise ValueError('Scores must be finite')
    if pd.isna(identifiers).any():
        raise ValueError('Customer IDs must not be missing')
    identifiers = np.asarray([str(value) for value in identifiers], dtype=str)
    if np.any(identifiers == ''):
        raise ValueError('Customer IDs must not be empty')
    return values, identifiers


def _labels(y, length):
    try:
        values = np.asarray(y, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError('Labels must be a binary vector') from exc
    if values.ndim != 1 or len(values) != length:
        raise ValueError('Labels and scores must have the same length')
    if not np.isfinite(values).all() or not np.isin(values, [0, 1]).all():
        raise ValueError('Labels must contain only zero or one')
    return values.astype(np.int64)


def _order(scores, identifiers):
    hashed = np.fromiter((_customer_hash(value) for value in identifiers),
                         dtype=np.uint64, count=len(identifiers))
    # The string is a deterministic last resort in the unlikely hash collision.
    # Exact replicas of a customer have the same score and outcome.
    return np.lexsort((identifiers, hashed, -scores))


def top_mask(scores, customer_ids, fraction=.1):
    """Select ceil(n * fraction) rows; ties use a fixed customer hash."""
    values, identifiers = _ranking_inputs(scores, customer_ids)
    if not np.isscalar(fraction):
        raise ValueError('Fraction must lie between zero and one')
    try:
        fraction = float(fraction)
    except (TypeError, ValueError) as exc:
        raise ValueError('Fraction must lie between zero and one') from exc
    if not np.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError('Fraction must lie between zero and one')
    selected = np.zeros(len(values), dtype=bool)
    selected[_order(values, identifiers)[:int(np.ceil(len(values) * fraction))]] = True
    return selected


def score_rank(scores, customer_ids):
    """Return ordinal ranks in [0, 1], with one meaning highest priority.

Ties are resolved with the same fixed customer hash used by ``top_mask``.
A population containing only one customer receives rank one.
"""
    values, identifiers = _ranking_inputs(scores, customer_ids)
    ranks = np.empty(len(values), dtype=float)
    ranks[_order(values, identifiers)] = np.linspace(1., 0., len(values))
    return ranks


def _weighted_metrics(y, scores, weights, order):
    """Exact row-replication metrics for nonnegative integer weights."""
    weights = np.asarray(weights, dtype=np.int64)
    n = int(weights.sum())
    if n <= 0:
        raise ValueError('A metric population must contain at least one row')
    positives = int(np.dot(y, weights))
    k = int(np.ceil(n * .1))
    ordered_weights = weights[order]
    before = np.cumsum(ordered_weights) - ordered_weights
    selected_copies = np.minimum(ordered_weights, np.maximum(k - before, 0))
    caught = int(np.dot(y[order], selected_copies))
    used = weights > 0
    auc = (float(roc_auc_score(y[used], scores[used], sample_weight=weights[used]))
           if 0 < positives < n else float('nan'))
    ap = (float(average_precision_score(y[used], scores[used], sample_weight=weights[used]))
          if positives else 0.)
    return {'n': n, 'positive': positives, 'prevalence': positives / n,
            'auc': auc, 'ap': ap,
            'top10_recall': caught / positives if positives else 0.,
            'top10_precision': caught / k, 'top10_caught': caught, 'top10_size': k}


def metrics(y, scores, customer_ids):
    """Match benchmark.metrics keys, using hash-based score tie breaking.

For a single-class population AUC is NaN. With no positives, AP and recall are
zero; the bootstrap reports how many finite draws each interval uses.
"""
    values, identifiers = _ranking_inputs(scores, customer_ids)
    labels = _labels(y, len(values))
    return _weighted_metrics(labels, values, np.ones(len(values), dtype=np.int64),
                             _order(values, identifiers))


def paired_customer_bootstrap(pred_a, pred_b, outcome, reps=300):
    """Paired CI for mean-month differences (candidate B minus baseline A).

Each draw resamples customers, retaining all their monthly observations. AP and
AUC use integer sample weights, exactly matching replicated rows. Top 10% uses
ceil(10% of the replicated population) with integer boundary copies, not a
fractional-budget approximation. The observed estimate uses the original
unweighted customer populations.
"""
    if isinstance(reps, bool) or not isinstance(reps, (int, np.integer)) or reps < 2:
        raise ValueError('Bootstrap replicates must be an integer of at least two')
    keys = ['customer_id', 'as_of_date']
    required = keys + [outcome, 'score']
    tables = []
    for name, frame in [('baseline', pred_a), ('candidate', pred_b)]:
        if not isinstance(frame, pd.DataFrame) or not set(required).issubset(frame.columns):
            raise ValueError(f'{name} predictions must contain {required}')
        table = frame[required].copy()
        if table.empty or table[keys].isna().any().any():
            raise ValueError(f'{name} predictions must have nonempty, complete keys')
        table['as_of_date'] = pd.to_datetime(table.as_of_date, errors='raise')
        if table.as_of_date.isna().any():
            raise ValueError(f'{name} predictions must have complete dates')
        table['customer_id'] = _ranking_inputs(table.score, table.customer_id)[1]
        table[outcome] = _labels(table[outcome], len(table))
        if table[keys].duplicated().any():
            raise ValueError(f'{name} predictions have duplicate observation keys')
        tables.append(table)
    paired = tables[0].merge(tables[1], on=keys, how='outer', validate='one_to_one',
                             suffixes=('_base', '_new'), indicator=True)
    if not paired['_merge'].eq('both').all():
        raise ValueError('Prediction populations differ')
    if not np.array_equal(paired[f'{outcome}_base'], paired[f'{outcome}_new']):
        raise ValueError('Prediction labels differ')
    # Canonical order makes identical comparisons invariant to input row order.
    paired = paired.sort_values(keys).reset_index(drop=True)
    customers = np.sort(paired.customer_id.unique())
    block_lookup = {customer: i for i, customer in enumerate(customers)}
    paired['block'] = paired.customer_id.map(block_lookup)
    groups = []
    for date, group in paired.groupby('as_of_date', sort=True):
        y = group[f'{outcome}_base'].to_numpy(dtype=np.int64)
        base, identifiers = _ranking_inputs(group.score_base, group.customer_id)
        new, _ = _ranking_inputs(group.score_new, group.customer_id)
        groups.append((str(date.date()), y, base, new, group.block.to_numpy(),
                       _order(base, identifiers), _order(new, identifiers)))
    metric_keys = ('auc', 'ap', 'top10_recall')

    def differences(weights):
        per_month = []
        for _, y, base, new, blocks, order_a, order_b in groups:
            group_weights = weights[blocks]
            if not group_weights.sum():
                return None
            a = _weighted_metrics(y, base, group_weights, order_a)
            b = _weighted_metrics(y, new, group_weights, order_b)
            per_month.append([b[key] - a[key] for key in metric_keys])
        return np.mean(per_month, axis=0)

    observed = differences(np.ones(len(customers), dtype=np.int64))
    seed = 20260925
    rng = np.random.default_rng(seed)
    deltas = []
    empty_month_draws = 0
    for _ in range(reps):
        weights = np.bincount(rng.integers(0, len(customers), len(customers)),
                              minlength=len(customers))
        delta = differences(weights)
        if delta is None:
            empty_month_draws += 1
        else:
            deltas.append(delta)
    values = np.asarray(deltas, dtype=float).reshape(-1, len(metric_keys))
    intervals, valid = {}, {}
    for i, key in enumerate(metric_keys):
        finite = values[:, i][np.isfinite(values[:, i])]
        valid[key] = len(finite)
        intervals[key] = np.quantile(finite, [.025, .975]).tolist() if len(finite) else None
    return {'replicates': int(reps), 'seed': seed, 'customer_count': len(customers),
            'months': [group[0] for group in groups], 'empty_month_draws': empty_month_draws,
            'valid_replicates': valid,
            'observed_mean_delta': {key: (float(observed[i]) if np.isfinite(observed[i]) else None)
                                    for i, key in enumerate(metric_keys)},
            'mean_delta_95_interval': intervals,
            'direction': 'candidate minus baseline; equal weight for each observed month',
            'unit': 'customer, all monthly observations resampled together; paired models',
            'top10_definition': 'Exact integer row replication; ceil(0.1 * replicated monthly rows)',
            'limitation': ('Fixed observed months only. Intervals do not cover future temporal drift, '
                           'repeated model selection, or treatment effects.')}

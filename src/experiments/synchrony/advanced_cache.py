"""Build a keyed cache of added features, without reading outcome values.

Example::

    python -m src.experiments.synchrony.advanced_cache \\
        --source-zip /path/to/Datasets.zip \\
        --snapshots /path/to/snapshots.pkl \\
        --output /path/to/advanced_features.pkl

The snapshots pickle is a trusted, locally generated experiment artifact. Only
its customer_id/as_of_date columns are retained or inspected. The output contains
those two keys and the 60 added feature columns; existing features and labels are
not copied. The adjacent JSON records source, snapshot and feature-code hashes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from . import advanced_features, data


KEYS = ['customer_id', 'as_of_date']


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def build_cache(source_zip: Path, snapshots: Path, output: Path) -> dict:
    source_zip, snapshots, output = (Path(p).resolve() for p in (source_zip, snapshots, output))
    metadata_path = output.with_suffix('.json')
    if output.suffix != '.pkl':
        raise ValueError('Output must use a .pkl extension')
    if output in (source_zip, snapshots) or metadata_path in (source_zip, snapshots):
        raise ValueError('Output must not overwrite an input')
    inputs = {
        'source_zip': source_zip,
        'snapshots': snapshots,
        'feature_builder': Path(advanced_features.__file__).resolve(),
        'source_reader': Path(data.__file__).resolve(),
        'cache_builder': Path(__file__).resolve(),
    }
    before = {name: sha256(path) for name, path in inputs.items()}
    # No feature/label selection, statistics, fitting or evaluation is done here.
    keys = pd.read_pickle(snapshots)[KEYS].copy().reset_index(drop=True)
    keys['as_of_date'] = pd.to_datetime(keys.as_of_date, errors='raise')
    if keys.isna().to_numpy().any() or keys.duplicated(KEYS).any():
        raise ValueError('Snapshot keys must be present and unique')
    if keys.empty:
        raise ValueError('Snapshots contain no keys')

    customers, transactions = data.read_source(source_zip)
    frames, feature_names = [], None
    cutoffs = sorted(keys.as_of_date.unique())
    for cutoff in cutoffs:
        month_keys = keys.loc[keys.as_of_date.eq(cutoff)]
        features = advanced_features.build_advanced_features(customers, transactions, cutoff)
        if not features.index.is_unique or features.index.hasnans:
            raise ValueError('Advanced feature customer index must be present and unique')
        missing = ~month_keys.customer_id.isin(features.index)
        if missing.any():
            raise ValueError(f'{missing.sum()} snapshot keys missing from eligible features at {cutoff}')
        columns = list(features.columns)
        if feature_names is None:
            feature_names = columns
        elif feature_names != columns:
            raise ValueError('Feature columns changed between cutoffs')
        frame = month_keys.join(features, on='customer_id', validate='one_to_one')
        if len(columns) != 60 or not np.isfinite(frame[columns].to_numpy()).all():
            raise ValueError('Expected 60 finite additional features per snapshot key')
        frames.append(frame)
        print(f'FEATURE_CACHE {pd.Timestamp(cutoff).date()} rows={len(frame)} columns={len(columns)}', flush=True)

    cache = pd.concat(frames).sort_index().reset_index(drop=True)
    pd.testing.assert_frame_equal(cache[KEYS], keys)
    if len(cache) != len(keys) or cache.duplicated(KEYS).any():
        raise ValueError('Cache must contain exactly one row per snapshot key')
    after = {name: sha256(path) for name, path in inputs.items()}
    if before != after:
        changed = [name for name in before if before[name] != after[name]]
        raise RuntimeError(f'Inputs or feature code changed during cache generation: {changed}')

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths = []
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + '.', suffix='.tmp', delete=False) as handle:
            pickle_path = Path(handle.name)
            temporary_paths.append(pickle_path)
        cache.to_pickle(pickle_path)
        metadata = {
            'schema_version': 1,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'keys': KEYS,
            'rows': len(cache),
            'features': feature_names,
            'feature_count': len(feature_names),
            'columns': list(cache.columns),
            'cutoffs': [str(pd.Timestamp(cutoff).date()) for cutoff in cutoffs],
            'inputs': {name: {'path': str(path), 'sha256': before[name]} for name, path in inputs.items()},
            'output': {'path': str(output), 'sha256': sha256(pickle_path)},
            'alignment': 'Exactly the snapshot customer_id/as_of_date keys, in snapshot row order.',
            'labels_used': False,
            'assumptions': [
                'Only purchase events dated at or before each cutoff enter the features.',
                'Event dates are assumed available on the recorded event date.',
                'No observed merchant purchase is represented by zero amounts and counts.',
                'Customer card dates are used only for eligibility at the cutoff.',
                'Unknown histories and missing-value conventions are documented in advanced_features.py.',
            ],
        }
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=metadata_path.name + '.', suffix='.tmp', mode='w', delete=False) as handle:
            json_path = Path(handle.name)
            temporary_paths.append(json_path)
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(pickle_path, output)
        os.replace(json_path, metadata_path)
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    metadata = build_cache(args.source_zip, args.snapshots, args.output)
    print(f"SAVED {args.output.resolve()} rows={metadata['rows']} features={metadata['feature_count']}", flush=True)


if __name__ == '__main__':
    main()

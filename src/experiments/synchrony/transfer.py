"""Check the frozen 30-day winner on 60-day labels, without more tuning."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import make_pipeline
from threadpoolctl import threadpool_limits

from .benchmark import aggregate, metrics, train_mask, write_json
from .models import CANDIDATES, classifier, prepare_features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.selection.read_text())
    selected = source['selected']
    out = args.output / 'classification_60_transfer'
    out.mkdir(parents=True, exist_ok=True)
    result = {'selected_on_30_day_development': selected,
              'dates': ['2026-03-31', '2026-04-30', '2026-05-31'],
              'note': 'Previously inspected periods; frozen-method transfer check, not an independent test or 60-day retuning.',
              'comparison': {}}
    write_json(out / 'protocol.json', result)
    frame = pd.read_pickle(args.snapshots)
    original = json.loads(args.features.read_text())
    features = prepare_features(frame, original)
    with threadpool_limits(limits=4):
        for name in ['previous_hgb60', selected]:
            folds, predictions = [], []
            for date_str in result['dates']:
                date = pd.Timestamp(date_str)
                window = None if name == 'previous_hgb60' else CANDIDATES[name]['window']
                train = train_mask(frame, date, 60, window)
                test = frame.as_of_date.eq(date) & frame.y_close_60.notna()
                if name == 'previous_hgb60':
                    model = make_pipeline(ColumnTransformer([('features', 'passthrough', original)]),
                        HistGradientBoostingClassifier(max_iter=180, learning_rate=.05, max_leaf_nodes=7,
                            min_samples_leaf=100, l2_regularization=10, max_bins=127,
                            early_stopping=False, random_state=42))
                else:
                    model = classifier(name, original, list(features.columns))
                model.fit(features.loc[train], frame.loc[train, 'y_close_60'].astype(int))
                scores = model.predict_proba(features.loc[test])[:, 1]
                measured = {'date': date_str, **metrics(frame.loc[test, 'y_close_60'], scores)}
                folds.append(measured)
                pred = frame.loc[test, ['customer_id', 'as_of_date', 'y_close_60']].copy()
                pred['score'] = scores
                predictions.append(pred)
                print('TRANSFER60', name, json.dumps(measured), flush=True)
            result['comparison'][name] = {'folds': folds, **aggregate(folds)}
            pd.concat(predictions).to_csv(out / f'predictions_{name}.csv', index=False)
            path = out / f'{name}.joblib'
            joblib.dump({'model': model, 'original_features': original, 'horizon_days': 60,
                'model_name': name, 'as_of_date': result['dates'][-1],
                'score_semantics': 'uncalibrated ranking score'}, path, compress=3)
            restored = joblib.load(path)
            np.testing.assert_allclose(restored['model'].predict_proba(features.loc[test])[:, 1], scores)
            write_json(out / 'results.json', result)
    print('COMPLETE', out / 'results.json', flush=True)


if __name__ == '__main__':
    main()

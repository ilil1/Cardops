"""Build event-time monthly snapshots from the locally supplied source ZIP.

Raw data is never downloaded or added to the repository by this module. The
caller must separately obtain permission to use the source dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


def read_source(path):
    with zipfile.ZipFile(path) as archive:
        customers = pd.read_csv(archive.open('Datasets/Customer Data.csv')).set_index('Customer_ID')
        transactions = pd.read_csv(archive.open('Datasets/Transaction Data.csv'))
    for col in ['Credit_Card_Open_Date', 'Credit_Card_Closed_Date']:
        customers[col] = pd.to_datetime(customers[col], format='%m/%d/%Y')
    transactions.Transaction_Date = pd.to_datetime(transactions.Transaction_Date, format='%m/%d/%Y')
    if not customers.index.is_unique or not transactions.Transaction_ID.is_unique:
        raise ValueError('Duplicate source identifiers')
    if not transactions.Customer_ID.isin(customers.index).all():
        raise ValueError('Transaction references unknown customer')
    transactions['month'] = transactions.Transaction_Date.dt.to_period('M')
    return customers, transactions


def snapshot(customers, tx, cutoff, observation_start, observation_end):
    cutoff = pd.Timestamp(cutoff)
    eligible = customers.Credit_Card_Open_Date.le(cutoff) & (
        customers.Credit_Card_Closed_Date.isna() | customers.Credit_Card_Closed_Date.gt(cutoff))
    index = customers.index[eligible]
    values = {}

    def assign(name, value):
        values[name] = value.reindex(index).fillna(0) if isinstance(value, pd.Series) else value

    tenure = (cutoff - customers.loc[index, 'Credit_Card_Open_Date']).dt.days
    assign('tenure_days', tenure)
    assign('observed_card_days', np.minimum(tenure, (cutoff - observation_start).days + 1))
    past = tx[tx.Transaction_Date.le(cutoff)]
    all_sales = past[past.Transaction_Type.eq('Sale')]
    card_sales = all_sales[all_sales.Payment_Code.eq(3)]
    for channel, sales in [('all', all_sales), ('card', card_sales)]:
        last = sales.groupby('Customer_ID').Transaction_Date.max().reindex(index)
        assign(f'{channel}_recency', (cutoff - last).dt.days.fillna(999))
        assign(f'{channel}_ever_seen', last.notna().astype(int))
        for days in (30, 90, 180):
            window = sales[sales.Transaction_Date.gt(cutoff - pd.Timedelta(days=days))]
            grouped = window.groupby('Customer_ID').agg(rows=('Transaction_ID', 'size'),
                count=('Number_of_Transactions', 'sum'), amount=('Transaction_Amount', 'sum'))
            for col in grouped:
                assign(f'{channel}_{col}_{days}', grouped[col])
        window = sales[sales.Transaction_Date.gt(cutoff - pd.Timedelta(days=180))]
        categories = window.groupby(['Customer_ID', 'Category_Code']).Transaction_Amount.sum().unstack(fill_value=0)
        for category in range(1, 11):
            value = categories.get(category, pd.Series(dtype=float)).reindex(index).fillna(0)
            assign(f'{channel}_category_{category}_share', value / values[f'{channel}_amount_180'].clip(lower=1))
    for days in (30, 90, 180):
        assign(f'card_spend_share_{days}', values[f'card_amount_{days}'] / values[f'all_amount_{days}'].clip(lower=1))
    assign('card_count_trend', values['card_count_30'] - values['card_count_90'] / 3)
    assign('all_count_trend', values['all_count_30'] - values['all_count_90'] / 3)

    for channel, subset in [('all', past), ('card', past[past.Payment_Code.eq(3)]), ('other', past[past.Payment_Code.ne(3)])]:
        sales = subset[subset.Transaction_Type.eq('Sale')]
        returns = subset[subset.Transaction_Type.eq('Return')]
        monthly = sales.groupby(['Customer_ID', 'month']).agg(count=('Number_of_Transactions', 'sum'),
            amount=('Transaction_Amount', 'sum'), rows=('Transaction_ID', 'size'))
        for lag in range(6):
            period = cutoff.to_period('M') - lag
            at_month = monthly.xs(period, level='month') if period in monthly.index.get_level_values('month') else pd.DataFrame(columns=['count', 'amount', 'rows'], dtype=float)
            for variable in ['count', 'amount', 'rows']:
                assign(f'{channel}_lag{lag}_{variable}', at_month[variable])
        for variable in ['count', 'amount', 'rows']:
            month_values = pd.DataFrame({lag: values[f'{channel}_lag{lag}_{variable}'] for lag in range(6)})
            recent, previous = month_values.iloc[:, :3].sum(axis=1), month_values.iloc[:, 3:].sum(axis=1)
            assign(f'{channel}_{variable}_change_3v3', recent - previous)
            assign(f'{channel}_{variable}_ratio_3v3', (recent + 1) / (previous + 1))
            assign(f'{channel}_{variable}_monthly_std', month_values.std(axis=1))
            assign(f'{channel}_{variable}_monthly_max', month_values.max(axis=1))
            assign(f'{channel}_{variable}_active_months', month_values.gt(0).sum(axis=1))
        dates = sales[['Customer_ID', 'Transaction_Date']].drop_duplicates().sort_values(['Customer_ID', 'Transaction_Date'])
        dates['interval'] = dates.groupby('Customer_ID').Transaction_Date.diff().dt.days
        intervals = dates.groupby('Customer_ID').interval.agg(['median', 'mean', 'std', 'count'])
        for stat in intervals:
            assign(f'{channel}_interval_{stat}', intervals[stat])
        last = dates.groupby('Customer_ID').Transaction_Date.max().reindex(index)
        recency = (cutoff - last).dt.days.fillna(999)
        assign(f'{channel}_recency_over_interval', recency / (values[f'{channel}_interval_median'] + 1))
        history = sales.groupby('Customer_ID').agg(count=('Number_of_Transactions', 'sum'),
            amount=('Transaction_Amount', 'sum'), rows=('Transaction_ID', 'size'))
        for variable in history:
            assign(f'{channel}_history_{variable}', history[variable])
        assign(f'{channel}_history_count_per_row', values[f'{channel}_history_count'] / values[f'{channel}_history_rows'].clip(lower=1))
        assign(f'{channel}_history_amount_per_count', values[f'{channel}_history_amount'] / values[f'{channel}_history_count'].clip(lower=1))
        for days in (30, 90, 180):
            grouped = returns[returns.Transaction_Date.gt(cutoff - pd.Timedelta(days=days))].groupby('Customer_ID').Transaction_Amount.agg(['sum', 'size'])
            assign(f'{channel}_return_amount_{days}', grouped['sum'])
            assign(f'{channel}_return_rows_{days}', grouped['size'])
    for lag in range(6):
        assign(f'card_purchase_share_lag{lag}', values[f'card_lag{lag}_amount'] / values[f'all_lag{lag}_amount'].clip(lower=1))
    assign('card_share_change_1v3', values['card_purchase_share_lag0'] - sum(values[f'card_purchase_share_lag{i}'] for i in (1, 2, 3)) / 3)
    assign('card_relative_count_change', values['card_count_change_3v3'] - values['other_count_change_3v3'])
    assign('card_net_90', values['card_amount_90'] - values['card_return_amount_90'])
    assign('all_net_90', values['all_amount_90'] - values['all_return_amount_90'])
    assign('observed_tenure_monthly_rate', values['card_history_rows'] / (values['observed_card_days'].clip(lower=30) / 30))
    assign('month_sin', np.sin(2 * np.pi * cutoff.month / 12))
    assign('month_cos', np.cos(2 * np.pi * cutoff.month / 12))
    assign('inverse_tenure', 1 / (values['tenure_days'] + 30))
    features = list(values)
    frame = pd.DataFrame(values, index=index)
    frame['customer_id'] = index
    frame['as_of_date'] = cutoff
    close = customers.loc[index, 'Credit_Card_Closed_Date']
    for horizon in (30, 60):
        end = cutoff + pd.Timedelta(days=horizon)
        frame[f'y_close_{horizon}'] = ((close > cutoff) & (close <= end)).astype(int) if end <= observation_end else np.nan
    end = cutoff + pd.offsets.MonthEnd(1)
    future = tx[tx.Payment_Code.eq(3) & tx.Transaction_Type.eq('Sale') & tx.Transaction_Date.gt(cutoff) & tx.Transaction_Date.le(end)]
    grouped = future.groupby('Customer_ID').agg(count=('Number_of_Transactions', 'sum'), amount=('Transaction_Amount', 'sum'))
    for target in ('count', 'amount'):
        frame[f'y_next_card_{target}'] = grouped[target].reindex(index).fillna(0) if end <= observation_end else np.nan
    return frame.reset_index(drop=True), features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', default='2025-01-31')
    parser.add_argument('--end', default='2026-06-30')
    args = parser.parse_args()
    customers, tx = read_source(args.zip)
    frames = []
    for cutoff in pd.date_range(args.start, args.end, freq='ME'):
        frame, features = snapshot(customers, tx, cutoff, tx.Transaction_Date.min(), tx.Transaction_Date.max())
        frames.append(frame)
        print('SNAPSHOT', str(cutoff.date()), len(frame), flush=True)
    if not frames:
        raise ValueError('No month-end cutoffs in requested interval')
    args.output.mkdir(parents=True, exist_ok=True)
    data = pd.concat(frames, ignore_index=True)
    if not np.isfinite(data[features].to_numpy()).all():
        raise ValueError('Non-finite feature value')
    data.to_pickle(args.output / 'snapshots.pkl')
    (args.output / 'features.json').write_text(json.dumps(features, indent=2) + '\n')
    (args.output / 'data_manifest.json').write_text(json.dumps({
        'source_sha256': hashlib.sha256(args.zip.read_bytes()).hexdigest(),
        'source_path': str(args.zip.resolve()), 'rows': len(data), 'features': len(features),
        'observation_start': str(tx.Transaction_Date.min().date()),
        'observation_end': str(tx.Transaction_Date.max().date()),
        'assumptions': ['Absent customer-month purchases mean zero at the observed merchant.',
                        'Event dates are assumed available on that date.',
                        'Purchase counts belong to the date of the source row.'],
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()

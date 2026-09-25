"""Additional, dated merchant-behaviour features, without labels or fitting.

The input is ``data.read_source`` output. Every feature uses Sale rows at or
before ``cutoff``; windows are (cutoff - days, cutoff]. Card dates only determine
the eligible population (opened and not yet closed). No final customer metadata
is read. Customer_ID remains the join index and is never a model column.

Missing-history rules: sums, shares, concentrations and entropy are zero when
there are no qualifying purchases. A share change can therefore describe entry
into or exit from an observed payment method. Distribution change is zero when
either comparison window has no purchases, because the mix is then unobserved.
Unobserved other-credit recency is 999 with a separate seen flag; the recency gap
is zero unless both card methods were observed. Recent-N features use the last N
distinct purchase dates, including every row on each date, and divide by the
number of available dates. They never infer a transaction order from row IDs.

Absent merchant history is an observation assumption, not evidence of inactivity
at other merchants. Event dates are assumed available as of their event date.
Observed Sale amounts/counts must be finite and nonnegative; missing quantities
raise an error instead of silently manufacturing purchase values. Return rows
are excluded. Unspecified category/payment codes form an unknown group for mix
statistics and remain in all-payment denominators. The function does not mutate
either input. The feature set is fixed at 60 numeric columns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


PAYMENT_CODES = (1, 2, 3, 4, 5)
WINDOWS = (30, 90, 180)


def build_advanced_features(
    customers: pd.DataFrame,
    transactions: pd.DataFrame,
    cutoff,
) -> pd.DataFrame:
    """Return point-in-time features indexed by eligible Customer_ID."""
    cutoff = pd.Timestamp(cutoff)
    if customers.index.name != 'Customer_ID' or not customers.index.is_unique:
        raise ValueError('customers must have a unique Customer_ID index')
    eligible = customers.Credit_Card_Open_Date.le(cutoff) & (
        customers.Credit_Card_Closed_Date.isna()
        | customers.Credit_Card_Closed_Date.gt(cutoff)
    )
    index = customers.index[eligible]
    sales = transactions.loc[
        transactions.Customer_ID.isin(index)
        & transactions.Transaction_Date.le(cutoff)
        & transactions.Transaction_Type.eq('Sale'),
        ['Customer_ID', 'Transaction_Date', 'Payment_Code', 'Category_Code',
         'Number_of_Transactions', 'Transaction_Amount'],
    ].copy()
    for column in ('Number_of_Transactions', 'Transaction_Amount'):
        sales[column] = pd.to_numeric(sales[column], errors='raise')
        values = sales[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f'Observed Sale {column} must be finite and nonnegative')

    result = {}

    def aligned(value):
        return value.reindex(index).fillna(0).astype(float)

    def ratio(numerator, denominator):
        numerator, denominator = aligned(numerator), aligned(denominator)
        return numerator.div(denominator.where(denominator.gt(0))).fillna(0)

    def grouped_values(frame):
        return frame.groupby('Customer_ID').agg(
            count=('Number_of_Transactions', 'sum'),
            amount=('Transaction_Amount', 'sum'),
        ).reindex(index).fillna(0)

    totals, by_payment = {}, {}
    for days in WINDOWS:
        window = sales.loc[sales.Transaction_Date.gt(cutoff - pd.Timedelta(days=days))]
        totals[days] = grouped_values(window)
        for code in PAYMENT_CODES:
            values = grouped_values(window.loc[window.Payment_Code.eq(code)])
            by_payment[code, days] = values
            for variable in ('count', 'amount'):
                result[f'adv_payment_{code}_{variable}_{days}'] = values[variable]

    for code in PAYMENT_CODES:
        for variable in ('count', 'amount'):
            recent = ratio(by_payment[code, 30][variable], totals[30][variable])
            previous = ratio(
                by_payment[code, 90][variable] - by_payment[code, 30][variable],
                totals[90][variable] - totals[30][variable],
            )
            result[f'adv_payment_{code}_{variable}_share_change_30v60'] = recent - previous

    last_other = sales.loc[sales.Payment_Code.eq(2)].groupby('Customer_ID').Transaction_Date.max().reindex(index)
    last_target = sales.loc[sales.Payment_Code.eq(3)].groupby('Customer_ID').Transaction_Date.max().reindex(index)
    both_seen = last_other.notna() & last_target.notna()
    result['adv_other_credit_recency'] = (cutoff - last_other).dt.days.fillna(999)
    result['adv_other_credit_seen'] = last_other.notna().astype(float)
    result['adv_other_credit_more_recent'] = (
        last_other.notna() & (last_target.isna() | last_other.gt(last_target))
    ).astype(float)
    result['adv_target_to_other_credit_gap_days'] = (
        (last_other - last_target).dt.days.where(both_seen, 0)
    )

    daily_source = sales.assign(
        target_count=sales.Number_of_Transactions.where(sales.Payment_Code.eq(3), 0),
        target_amount=sales.Transaction_Amount.where(sales.Payment_Code.eq(3), 0),
        target_day=sales.Payment_Code.eq(3).astype(float),
    )
    daily = daily_source.groupby(['Customer_ID', 'Transaction_Date']).agg(
        count=('Number_of_Transactions', 'sum'), amount=('Transaction_Amount', 'sum'),
        target_count=('target_count', 'sum'), target_amount=('target_amount', 'sum'),
        target_day=('target_day', 'max'),
    ).reset_index().sort_values(['Customer_ID', 'Transaction_Date'], ascending=[True, False])
    daily['date_rank'] = daily.groupby('Customer_ID').cumcount()
    for count in (3, 6):
        recent = daily.loc[daily.date_rank.lt(count)].groupby('Customer_ID').agg(
            count=('count', 'sum'), amount=('amount', 'sum'),
            target_count=('target_count', 'sum'), target_amount=('target_amount', 'sum'),
            target_day=('target_day', 'sum'), days=('Transaction_Date', 'size'),
        )
        result[f'adv_last{count}_purchase_days_target_count_share'] = ratio(recent.target_count, recent['count'])
        result[f'adv_last{count}_purchase_days_target_amount_share'] = ratio(recent.target_amount, recent.amount)
        result[f'adv_last{count}_purchase_days_target_day_fraction'] = ratio(recent.target_day, recent.days)

    def distribution(frame, column):
        amounts = frame.groupby(['Customer_ID', column], dropna=False).Transaction_Amount.sum().unstack(fill_value=0)
        # Empty frames retain the customer index and produce zero mix statistics.
        amounts = amounts.reindex(index).fillna(0)
        total = amounts.sum(axis=1)
        return amounts.div(total.where(total.gt(0)), axis=0).fillna(0), total

    for channel, subset in [('all', sales), ('target', sales.loc[sales.Payment_Code.eq(3)])]:
        recent = subset.loc[subset.Transaction_Date.gt(cutoff - pd.Timedelta(days=90))]
        past180 = subset.loc[subset.Transaction_Date.gt(cutoff - pd.Timedelta(days=180))]
        previous = past180.loc[past180.Transaction_Date.le(cutoff - pd.Timedelta(days=90))]
        recent_mix, recent_amount = distribution(recent, 'Category_Code')
        old_mix, old_amount = distribution(previous, 'Category_Code')
        all_mix, _ = distribution(past180, 'Category_Code')
        result[f'adv_{channel}_category_hhi_90'] = recent_mix.pow(2).sum(axis=1)
        result[f'adv_{channel}_category_hhi_180'] = all_mix.pow(2).sum(axis=1)
        # Total variation is bounded [0, 1] when both windows are observed.
        left, right = recent_mix.align(old_mix, join='outer', axis=1, fill_value=0)
        result[f'adv_{channel}_category_mix_change_90v90'] = (
            left.sub(right).abs().sum(axis=1).mul(.5)
            .where(recent_amount.gt(0) & old_amount.gt(0), 0)
        )

    for days in (90, 180):
        window = sales.loc[sales.Transaction_Date.gt(cutoff - pd.Timedelta(days=days))]
        mix, _ = distribution(window, 'Payment_Code')
        result[f'adv_payment_hhi_{days}'] = mix.pow(2).sum(axis=1)
        result[f'adv_payment_entropy_{days}'] = -(mix * np.log(mix.where(mix.gt(0), 1))).sum(axis=1)

    frame = pd.DataFrame(result, index=index).astype('float32')
    if len(frame.columns) != 60 or not frame.columns.is_unique:
        raise AssertionError('Expected exactly 60 unique advanced features')
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError('Non-finite advanced feature value')
    return frame

# ============================================================
# SECTION 1: IMPORT LIBRARIES
# ============================================================
# pathlib provides tools for working with file paths.
# io allows Excel files to be created in memory.
# pandas handles tables of stocks and portfolio holdings.
# numpy supplies missing-value and numerical operations.
#
# This module contains the calculations and Excel file handling
# used by the separate Streamlit portfolio dashboard.

from __future__ import annotations

import io

import pandas as pd
import numpy as np


# ============================================================
# SECTION 2: READ AND PREPARE WLS STOCK RANKINGS
# ============================================================
# Read the 'Full Rankings' worksheet and standardise tickers.
# Remove rows without a ticker and keep each ticker only once.
#
# Where available, use the 'Top 30 Candidates' worksheet to
# fill missing company names and classifications.
# Existing information is preserved rather than overwritten.
#
# Missing descriptive fields become 'Unknown', while missing
# numerical screening metrics become NaN (not a number).
# The resulting DataFrame is the stock universe used by the app.


def read_rankings(source):
    full = pd.read_excel(source, sheet_name='Full Rankings', engine='openpyxl')
    full.columns = full.columns.astype(str).str.strip()

    if 'Ticker' not in full:
        raise ValueError('Full Rankings must contain Ticker.')

    full['Ticker'] = full['Ticker'].astype('string').str.strip().str.upper()
    full = full.dropna(subset=['Ticker']).drop_duplicates('Ticker').copy()

    for c in ['Name', 'Sector', 'Industry']:
        if c not in full:
            full[c] = pd.NA

    if 'Country' not in full:
        full['Country'] = pd.NA

    try:
        top = pd.read_excel(source, sheet_name='Top 30 Candidates', engine='openpyxl')
        top['Ticker'] = top['Ticker'].astype('string').str.strip().str.upper()

        if 'Country' in top:
            by_ticker = (
                top.dropna(subset=['Ticker'])
                .drop_duplicates('Ticker')
                .set_index('Ticker')['Country']
            )
            full['Country'] = full['Country'].fillna(full['Ticker'].map(by_ticker))

        for c in ['Name', 'Sector', 'Industry']:
            if c in top:
                by_ticker = (
                    top.dropna(subset=['Ticker'])
                    .drop_duplicates('Ticker')
                    .set_index('Ticker')[c]
                )
                full[c] = full[c].fillna(full['Ticker'].map(by_ticker))

    except ValueError:
        pass

    full['Name'] = full['Name'].fillna(full['Ticker'])

    for c in ['Sector', 'Industry', 'Country']:
        full[c] = full[c].fillna('Unknown').replace('', 'Unknown')

    for c in [
        'Score', 'Rank', 'Beta_6M', 'Momentum_12_1',
        'Volatility_6M', 'Max_Drawdown', 'Recent_Return_2M'
    ]:
        if c not in full:
            full[c] = np.nan
        full[c] = pd.to_numeric(full[c], errors='coerce')

    return full


# ============================================================
# SECTION 3: IMPORT A STARTING PORTFOLIO FROM EXCEL
# ============================================================
# This function accepts either the original portfolio layout
# or a workbook previously exported from the dashboard.
#
# It finds the header row by searching the first 12 rows for
# column headings containing 'ticker' and 'name'. This is useful
# because the original workbook has introductory rows above
# the main holdings table.
#
# The portfolio capital is read from the workbook when possible.
# If it cannot be read, $1,000,000 is used as the default number
# (the currency itself is determined by the workbook).
#
# Original workbooks may have blank column headings for Country,
# Weight and Value. Their locations are then inferred from the
# Name column. A standard dashboard export uses named columns.
# In both cases, the holdings are passed to _clean_portfolio().


def read_starting_portfolio(source):
    raw = pd.read_excel(source, sheet_name=0, header=None, engine='openpyxl')

    if raw.empty:
        raise ValueError('Portfolio sheet is empty')

    capital = pd.to_numeric(
        pd.Series([raw.iat[0, 1] if raw.shape[1] > 1 else None]),
        errors='coerce'
    ).iloc[0]

    if not np.isfinite(capital):
        capital = 1_000_000.

    hdr = None
    for i in range(min(12, len(raw))):
        vals = [str(x).strip().lower() for x in raw.iloc[i] if pd.notna(x)]
        if any('ticker' in v for v in vals) and any('name' in v for v in vals):
            hdr = i
            break

    if hdr is None:
        raise ValueError('Could not find a ticker/name header row')

    header = [str(v).strip() if pd.notna(v) else '' for v in raw.iloc[hdr]]
    body = raw.iloc[hdr + 1:].copy()
    body.columns = header

    ticker_col = next(
        (c for c in body if c.lower() in ('yahoo finance ticker', 'ticker', 'yahoo ticker')),
        None
    )

    if ticker_col is None:
        raise ValueError('Expected Yahoo Finance Ticker or Ticker column')

    if 'Weight' in body.columns:
        wc = 'Weight'
        cc = 'Country' if 'Country' in body else None
    else:
        name_pos = header.index('Name') if 'Name' in header else 3
        cc = header[name_pos + 1] if name_pos + 1 < len(header) else None
        wc = header[name_pos + 2] if name_pos + 2 < len(header) else None

        work = pd.DataFrame({
            'Ticker': body[ticker_col],
            'Name': body['Name'] if 'Name' in body else None,
            'Country': raw.iloc[hdr + 1:, name_pos + 1].to_numpy()
            if name_pos + 1 < raw.shape[1] else None,
            'Weight': raw.iloc[hdr + 1:, name_pos + 2].to_numpy()
            if name_pos + 2 < raw.shape[1] else None,
            'Value': raw.iloc[hdr + 1:, name_pos + 3].to_numpy()
            if name_pos + 3 < raw.shape[1] else None
        })

        work['Bloomberg Ticker'] = (
            body['Bloomberg Ticker'].to_numpy()
            if 'Bloomberg Ticker' in body else ''
        )
        return _clean_portfolio(work), float(capital)

    work = pd.DataFrame({
        'Ticker': body[ticker_col],
        'Name': body['Name'] if 'Name' in body else None,
        'Country': body[cc] if cc else None,
        'Weight': body[wc],
        'Value': body['Value'] if 'Value' in body else None,
        'Bloomberg Ticker': body['Bloomberg Ticker']
        if 'Bloomberg Ticker' in body else ''
    })

    if 'Portfolio Capital' in body:
        detected = pd.to_numeric(body['Portfolio Capital'], errors='coerce').dropna()
        if len(detected):
            capital = float(detected.iloc[0])

    return _clean_portfolio(work), float(capital)


# ============================================================
# SECTION 4: CLEAN IMPORTED HOLDINGS AND WEIGHTS
# ============================================================
# Standardise tickers and remove empty or total-summary rows.
# Convert Weight and Value columns into numbers.
#
# If only position values are available, calculate each weight
# by dividing its value by the sum of all position values.
# If weights appear as whole percentages (such as 8 for 8%),
# convert them to decimals (0.08).
#
# When the same ticker appears more than once, combine its
# weights and values into a single holding.
# The final DataFrame contains one row per ticker.


def _clean_portfolio(df):
    df = df.copy()
    df['Ticker'] = df['Ticker'].astype('string').str.strip().str.upper()
    df = df.dropna(subset=['Ticker'])
    df = df[~df['Ticker'].isin(['', 'NAN', 'NONE', 'TOTAL'])]

    for c in ['Weight', 'Value']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    if df['Weight'].isna().all() and df['Value'].notna().any():
        df['Weight'] = df['Value'] / df['Value'].sum()

    if df['Weight'].dropna().gt(1).any():
        if df['Weight'].dropna().between(0, 100).all():
            df['Weight'] /= 100

    df['Weight'] = df['Weight'].fillna(0)

    if df['Ticker'].duplicated().any():
        df = df.groupby('Ticker', as_index=False).agg({
            'Name': 'first',
            'Country': 'first',
            'Weight': 'sum',
            'Value': 'sum',
            'Bloomberg Ticker': 'first'
        })

    return df.reset_index(drop=True)


# ============================================================
# SECTION 5: ADD COMPANY AND SCREENING INFORMATION
# ============================================================
# Match each portfolio holding to the WLS rankings using its
# ticker as a lookup key.
#
# Bring in company classifications and available screening
# metrics, including rank, score, beta and momentum.
# Imported Name and Country values are retained when present;
# missing values are filled from the rankings.
# Missing descriptive fields are labelled 'Unknown'.


def enrich_holdings(holdings, universe):
    lookup = universe.set_index('Ticker')
    out = holdings.copy()

    for c in [
        'Name', 'Sector', 'Industry', 'Country', 'Score',
        'Rank', 'Beta_6M', 'Momentum_12_1',
        'Volatility_6M', 'Max_Drawdown'
    ]:
        mapped = (
            out['Ticker'].map(lookup[c])
            if c in lookup
            else pd.Series(np.nan, index=out.index)
        )

        if c in ('Name', 'Country') and c in out:
            out[c] = out[c].replace('', np.nan).fillna(mapped)
        else:
            out[c] = mapped

    for c in ['Name', 'Sector', 'Industry', 'Country']:
        out[c] = out[c].fillna('Unknown')

    return out


# ============================================================
# SECTION 6: CHANGE ONE HOLDING'S PORTFOLIO WEIGHT
# ============================================================
# Set the chosen ticker to a target allocation between 0% and
# 100%. All other holdings share the remaining allocation.
#
# For example, if one stock is set to 30%, the other stocks
# collectively receive the remaining 70%.
# Their relative weights are preserved where possible.
# If the other stocks all have zero weight, their portion is
# split equally instead.
# The function returns a new dictionary of updated weights.


def set_weight(weights: dict[str, float], ticker: str, target: float) -> dict[str, float]:
    target = max(0., min(1., float(target)))
    w = {k: max(0., float(v)) for k, v in weights.items()}

    if ticker not in w:
        w[ticker] = 0.

    others = [k for k in w if k != ticker]
    old_sum = sum(w[k] for k in others)

    if not others:
        w[ticker] = 1.
        return w

    if old_sum > 0:
        for k in others:
            w[k] = w[k] / old_sum * (1 - target)
    else:
        for k in others:
            w[k] = (1 - target) / len(others)

    w[ticker] = target
    return w


# ============================================================
# SECTION 7: REMOVE HOLDINGS AND REDISTRIBUTE CAPITAL
# ============================================================
# Remove the selected tickers from the portfolio.
# Then increase the remaining allocations proportionally so
# that they sum to 100%.
#
# For example, removing a 20% holding leaves the other 80%
# to be rescaled to a full 100% allocation.
# The function prevents deleting every holding.
# If the remaining holdings have no positive weight, they
# receive equal weights instead.


def remove_holdings(weights: dict[str, float], tickers) -> dict[str, float]:
    remove = set(tickers)
    kept = {
        ticker: float(weight)
        for ticker, weight in weights.items()
        if ticker not in remove
    }

    if not kept:
        raise ValueError('At least one holding must remain in the portfolio.')

    result = normalize_weights(kept)

    if sum(result.values()) <= 0:
        equal = 1 / len(result)
        result = {ticker: equal for ticker in result}

    return result


# ============================================================
# SECTION 8: NORMALISE PORTFOLIO WEIGHTS
# ============================================================
# Normalisation adjusts weights so they add up to 1 (100%).
# Each nonnegative weight is divided by the total weight.
#
# Example: weights 30 and 70 become 0.30 and 0.70.
# Negative weights are treated as zero in this calculation.
# If all weights are zero, the original dictionary is returned.


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    denom = sum(max(0., float(v)) for v in weights.values())

    if denom <= 0:
        return weights.copy()

    return {
        k: max(0., float(v)) / denom
        for k, v in weights.items()
    }


# ============================================================
# SECTION 9: CALCULATE ALLOCATION BREAKDOWNS
# ============================================================
# Group holdings by a chosen column such as Sector, Country,
# Industry or Ticker, then add their portfolio weights.
#
# Sorting the result from largest to smallest makes it easy
# to identify the portfolio's largest concentrations.
# The Streamlit dashboard uses these results for its charts.


def breakdown(holdings, category):
    return (
        holdings.groupby(category, dropna=False)['Weight']
        .sum()
        .sort_values(ascending=False)
        .rename('Weight')
        .reset_index()
    )


# ============================================================
# SECTION 10: CALCULATE WEIGHTED SCREENING METRICS
# ============================================================
# Calculate a portfolio-weighted average of a stock metric,
# such as beta, momentum, screening score or volatility.
#
# Each stock's metric is multiplied by its portfolio weight.
# Stocks missing that metric are excluded from the average.
#
# The function returns two numbers:
# 1. The weighted average among stocks with available data.
# 2. The sum of portfolio weights covered by that metric.
#
# A weighted average of stock volatilities is NOT actual
# portfolio volatility, which also depends on correlations.


def weighted_metric(holdings, col):
    vals = pd.to_numeric(holdings[col], errors='coerce')
    w = holdings['Weight'].where(vals.notna(), 0)

    if w.sum() > 0:
        return (
            float((vals.fillna(0) * w).sum() / w.sum()),
            float(w.sum())
        )

    return np.nan, 0.


# ============================================================
# SECTION 11: RUN A SIMPLE HYPOTHETICAL STRESS TEST
# ============================================================
# Select holdings belonging to a particular ticker, sector,
# country or industry, and apply the specified price shock.
#
# Portfolio impact = affected portfolio weight × price shock.
# For example, a 30% decline in a sector worth 20% of the
# portfolio produces a 6% loss across the entire portfolio.
#
# Unaffected stocks are assumed to have unchanged prices.
# This is a static scenario, not a forecast or a VaR model.


def stress(holdings, column, name, shock):
    mask = holdings[column].eq(name)
    return float(holdings.loc[mask, 'Weight'].sum() * shock)


# ============================================================
# SECTION 12: EXPORT PORTFOLIO AND EXPOSURES TO EXCEL
# ============================================================
# Create an Excel workbook containing the current holdings
# and their allocation breakdowns.
#
# Recalculate each position's monetary value using:
# position value = portfolio weight × portfolio capital.
#
# The output workbook contains four worksheets:
# - Portfolio: Individual holdings and screening metrics.
# - Sector Exposure: Total weight by sector.
# - Country Exposure: Total weight by country.
# - Industry Exposure: Total weight by industry.
#
# Basic formatting makes the workbook easier to use:
# bold coloured headers, frozen top rows, column filters
# and automatically sized columns.
#
# The workbook is built in memory using BytesIO and returned
# as bytes, allowing Streamlit to offer it as a download.


def export_portfolio(holdings, capital):
    df = holdings.copy()
    df['Value'] = df['Weight'] * capital
    df['Portfolio Capital'] = capital
    buf = io.BytesIO()

    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        cols = [
            'Ticker', 'Name', 'Bloomberg Ticker', 'Country',
            'Sector', 'Industry', 'Weight', 'Value',
            'Portfolio Capital', 'Score', 'Rank', 'Beta_6M',
            'Momentum_12_1', 'Volatility_6M', 'Max_Drawdown'
        ]

        df[[c for c in cols if c in df]].to_excel(
            writer, index=False, sheet_name='Portfolio'
        )

        for field in ['Sector', 'Country', 'Industry']:
            breakdown(df, field).to_excel(
                writer, index=False, sheet_name=field + ' Exposure'
            )

        from openpyxl.styles import Font, PatternFill

        for ws in writer.book.worksheets:
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions

            for cell in ws[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='16324A')

            for col in ws.columns:
                letter = col[0].column_letter
                ws.column_dimensions[letter].width = min(
                    40,
                    max(13, max(len(str(c.value or '')) for c in list(col)[:200]) + 2)
                )

    return buf.getvalue()

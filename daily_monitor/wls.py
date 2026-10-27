"""Join a dated WLS snapshot to existing Yahoo classifications without guessing countries."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from trading_dashboard.portfolio import read_rankings

DEFAULT_SOURCE = 'WLS Stock Screening – Code & Data/WLS Data.xlsx'


def map_symbol(ticker, mic, rules):
    ticker = str(ticker).strip().replace('/', '-')
    suffix = rules['mic_to_suffix'].get(mic)
    override = rules['ticker_overrides'].get(ticker)
    # Historical overrides are exchange scoped; a common short symbol elsewhere must not inherit one.
    if override and suffix and (override.endswith(suffix) or (mic in ('XNSE', 'XBOM') and override.endswith(('.NS', '.BO')))):
        return override
    if suffix is None:
        return None
    if mic == 'XSTO' and ticker in rules['swedish_share_class_tickers']:
        ticker = ticker[:-1] + '-' + ticker[-1]
    elif mic == 'XCSE' and ticker in rules['danish_share_class_tickers']:
        ticker = ticker[:-1] + '-' + ticker[-1]
    elif mic == 'XHKG':
        ticker = ticker.zfill(4)
    elif mic == 'XLON' and ticker.endswith('-'):
        ticker = ticker[:-1]
    elif mic == 'XMEX' and ticker.endswith('*'):
        ticker = ticker[:-1]
    return ticker + suffix


def load_snapshot(source, rankings, overrides='daily_monitor/data/wls_classifications.csv'):
    raw = pd.read_excel(source, sheet_name='Worksheet Raw', dtype={'Ticker': str})
    raw = raw.rename(columns={'Ticker': 'Bloomberg Ticker', 'Weight': 'Source Weight Percent'})
    if raw['Bloomberg Ticker'].duplicated().any():
        raise ValueError('Duplicate Bloomberg identifiers in WLS snapshot')
    weight = pd.to_numeric(raw['Source Weight Percent'], errors='coerce') / 100
    if not np.isfinite(weight).all() or (weight < 0).any() or not np.isclose(weight.sum(), 1, atol=1e-6, rtol=0):
        raise ValueError('WLS source weights must sum to 100 percent')
    raw['Weight'] = weight
    final = pd.read_excel(source, sheet_name='Worksheet Final', dtype=str, keep_default_na=False)
    # Workbook variants label the first identifier column differently; positions are verified by matching raw keys.
    final = final.rename(columns={final.columns[0]: 'Bloomberg Ticker', final.columns[1]: 'Local Ticker'})
    final = final[['Bloomberg Ticker', 'Local Ticker', 'MIC']]
    frame = raw.merge(final, on='Bloomberg Ticker', how='left', validate='one_to_one')
    rules = json.loads(Path('daily_monitor/data/ticker_rules.json').read_text())
    frame['Ticker'] = [map_symbol(t, mic, rules) for t, mic in zip(frame['Local Ticker'], frame.MIC)]
    override = pd.read_csv(overrides, dtype=str, keep_default_na=False)
    if override['Bloomberg Ticker'].duplicated().any() or not override['Bloomberg Ticker'].isin(frame['Bloomberg Ticker']).all():
        raise ValueError('Classification overrides require unique snapshot Bloomberg identifiers')
    frame = frame.set_index('Bloomberg Ticker')
    for _, row in override.iterrows():
        if row.Ticker.strip():
            frame.loc[row['Bloomberg Ticker'], 'Ticker'] = row.Ticker.strip().upper()
    ambiguous = frame.Ticker.notna() & frame.Ticker.duplicated(keep=False)
    frame['Mapping Status'] = np.where(frame.Ticker.isna(), 'UNMAPPED', np.where(ambiguous, 'AMBIGUOUS', 'MAPPED'))
    # A Yahoo collision must not attribute classification or grant eligibility to another security.
    usable = frame.Ticker.where(frame['Mapping Status'].eq('MAPPED'))
    lookup = rankings.drop_duplicates('Ticker').set_index('Ticker')
    for column in ['Country', 'Sector', 'Industry', 'Rank']:
        frame[column] = usable.map(lookup[column])
    for _, row in override.iterrows():
        for column in ['Country', 'Sector', 'Industry']:
            if row[column].strip():
                frame.loc[row['Bloomberg Ticker'], column] = row[column].strip()
    for column in ['Country', 'Sector', 'Industry']:
        frame[column] = frame[column].fillna('Unknown').replace('', 'Unknown')
    return frame.reset_index()


def build(source, metadata, output):
    frame = load_snapshot(source, read_rankings(metadata))
    output.mkdir(parents=True, exist_ok=True)
    exposure_rows, coverage = [], {}
    for column in ['Country', 'Sector', 'Industry']:
        grouped = frame.groupby(column, dropna=False).Weight.sum()
        coverage[column.lower()] = {'classified_weight': float(frame.loc[frame[column].ne('Unknown'), 'Weight'].sum()),
                                    'unknown_weight': float(frame.loc[frame[column].eq('Unknown'), 'Weight'].sum()),
                                    'unknown_records': int(frame[column].eq('Unknown').sum())}
        for category, weight in grouped.items():
            exposure_rows.append({'dimension': column.lower(), 'category': category, 'weight': weight,
                                  'major_country': False if column == 'Country' else ''})
    # Countries default to the stricter minor-country limit until the owner marks major countries explicitly.
    path = output / 'benchmark_exposures.csv'
    if path.exists():
        previous = pd.read_csv(path, dtype=str, keep_default_na=False)
        flags = {r.category: r.major_country for r in previous.itertuples() if r.dimension == 'country'}
        for row in exposure_rows:
            if row['dimension'] == 'country' and row['category'] in flags:
                row['major_country'] = flags[row['category']]
    pd.DataFrame(exposure_rows).to_csv(path, index=False)
    incomplete = frame[['Country', 'Sector', 'Industry']].eq('Unknown').any(axis=1) | frame['Mapping Status'].ne('MAPPED')
    frame.loc[incomplete, ['Bloomberg Ticker', 'Ticker', 'Name', 'Weight', 'Country', 'Sector', 'Industry', 'Mapping Status']].to_csv(output / 'wls_missing_classifications.csv', index=False)
    summary = {'source': str(source), 'classification_source': str(metadata), 'snapshot_records': len(frame),
               'mapped_records': int(frame['Mapping Status'].eq('MAPPED').sum()),
               'ambiguous_records': int(frame['Mapping Status'].eq('AMBIGUOUS').sum()),
               'source_weight_sum': float(frame.Weight.sum()), 'dimensions': coverage,
               'method': 'No reweighting of classified subset; Unknown retains actual uncovered index weight. Exchange jurisdiction is not company country.'}
    (output / 'wls_classification_coverage.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', default=DEFAULT_SOURCE)
    p.add_argument('--metadata', default='yahoo_enrichment/output/stock_metadata.xlsx')
    p.add_argument('--output', type=Path, default=Path('daily_monitor/data'))
    args = p.parse_args()
    print(json.dumps(build(args.source, args.metadata, args.output), indent=2))


if __name__ == '__main__':
    main()

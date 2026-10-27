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


def read_listing_countries(path):
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = ['Ticker', 'Listing Market Country']
    if not set(required).issubset(frame.columns):
        raise ValueError('Listing-country input requires Ticker and Listing Market Country columns')
    frame = frame[required].copy()
    frame['Ticker'] = frame.Ticker.str.strip().str.upper()
    frame['Listing Market Country'] = frame['Listing Market Country'].str.strip()
    if frame.Ticker.eq('').any() or frame.Ticker.duplicated().any():
        raise ValueError('Listing-country input requires unique nonempty tickers')
    if frame['Listing Market Country'].str.lower().isin(['', 'unknown', 'none', 'nan']).any():
        raise ValueError('Listing-country input has missing labels')
    return frame


def read_company_domiciles(path):
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    columns = ['Ticker', 'Company Domicile', 'Verification Source', 'Verification Status']
    if not set(columns).issubset(frame.columns):
        raise ValueError('Company-domicile input requires ticker, domicile, verification source and status')
    frame = frame[columns].copy()
    for column in columns:
        frame[column] = frame[column].str.strip()
    frame['Ticker'] = frame.Ticker.str.upper()
    if frame.Ticker.eq('').any() or frame.Ticker.duplicated().any():
        raise ValueError('Company-domicile input requires unique nonempty tickers')
    if frame['Company Domicile'].str.lower().isin(['', 'unknown', 'none', 'nan']).any():
        raise ValueError('Unverified/blank domiciles must not be supplied as classified records')
    if not frame['Verification Status'].str.casefold().str.startswith('verified:').all() or not frame['Verification Source'].str.startswith('https://').all():
        raise ValueError('Domicile records require explicit verified status and HTTPS evidence')
    return frame


def load_snapshot(source, rankings, overrides='daily_monitor/data/wls_classifications.csv', listing_countries='daily_monitor/data/listing_market_countries.csv', domiciles='daily_monitor/data/company_domiciles.csv'):
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
        if column != 'Rank':
            frame[column + ' Source'] = np.where(frame[column].notna() & frame[column].ne('Unknown'), 'Enriched metadata', 'Missing')
    for _, row in override.iterrows():
        for column in ['Country', 'Sector', 'Industry']:
            if row[column].strip():
                frame.loc[row['Bloomberg Ticker'], column] = row[column].strip()
                frame.loc[row['Bloomberg Ticker'], column + ' Source'] = 'Owner override'
    for column in ['Country', 'Sector', 'Industry']:
        frame[column] = frame[column].fillna('Unknown').replace('', 'Unknown')
    # Listing market is a distinct supplied field, never an issuer-country substitute.
    listing = read_listing_countries(listing_countries).set_index('Ticker')
    frame['Listing Market Country'] = usable.map(listing['Listing Market Country']).fillna('Unknown')
    frame['Listing Market Country Source'] = np.where(frame['Listing Market Country'].ne('Unknown'), 'Supplied listing-market workbook', 'Missing')
    domicile = read_company_domiciles(domiciles).set_index('Ticker')
    frame['Company Domicile'] = usable.map(domicile['Company Domicile']).fillna('Unknown')
    frame['Domicile Verification Source'] = usable.map(domicile['Verification Source']).fillna('')
    frame['Domicile Verification Status'] = usable.map(domicile['Verification Status']).fillna('Unverified')
    return frame.reset_index()


def classifications(symbol, info, snapshot=None):
    """Use approved labels consistently for holdings and benchmark comparisons."""
    result = {}
    match = snapshot.loc[snapshot.Ticker.eq(symbol) & snapshot['Mapping Status'].eq('MAPPED')] if snapshot is not None else pd.DataFrame()
    record = match.iloc[0] if len(match) == 1 else None
    for column in ['Country', 'Sector', 'Industry']:
        key = column.lower()
        value = info.get(key)
        source = 'Yahoo current metadata' if value else 'Missing'
        if record is not None:
            approved = record.get(column + ' Source') == 'Owner override'
            if approved or (not value and record[column] != 'Unknown'):
                value, source = record[column], record[column + ' Source']
        result[key] = value or 'Unknown'
        result[key + '_source'] = source
    result['listing_market_country'] = record['Listing Market Country'] if record is not None else 'Unknown'
    result['listing_market_country_source'] = record['Listing Market Country Source'] if record is not None else 'Missing'
    # Yahoo profile country/headquarters and owner labels are not incorporation evidence.
    result['company_domicile'] = record['Company Domicile'] if record is not None and 'Company Domicile' in record else 'Unknown'
    result['domicile_verification_source'] = record['Domicile Verification Source'] if record is not None and 'Domicile Verification Source' in record else ''
    result['domicile_verification_status'] = record['Domicile Verification Status'] if record is not None and 'Domicile Verification Status' in record else 'Unverified'
    return result


def build(source, metadata, output, as_of=None):
    cfg_path = Path('daily_monitor/config.json')
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    domicile_path = cfg.get('company_domicile_source', 'daily_monitor/data/company_domiciles.csv')
    frame = load_snapshot(source, read_rankings(metadata), domiciles=domicile_path)
    country_basis = cfg.get('geographic_limit_basis', 'country_labels')
    if country_basis not in ('country_labels', 'company_domicile', 'listing_market'):
        raise ValueError('Geographic limit basis must be country_labels, company_domicile or listing_market')
    country_column = {'company_domicile': 'Company Domicile', 'listing_market': 'Listing Market Country', 'country_labels': 'Country'}[country_basis]
    output.mkdir(parents=True, exist_ok=True)
    exposure_rows, coverage = [], {}
    for column in ['Country', 'Sector', 'Industry']:
        effective_column = country_column if column == 'Country' else column
        grouped = frame.groupby(effective_column, dropna=False).Weight.sum()
        coverage[column.lower()] = {'classified_weight': float(frame.loc[frame[effective_column].ne('Unknown'), 'Weight'].sum()),
                                    'unknown_weight': float(frame.loc[frame[effective_column].eq('Unknown'), 'Weight'].sum()),
                                    'unknown_records': int(frame[effective_column].eq('Unknown').sum())}
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
    for column, dimension, filename in [('Country', 'country_labels', 'benchmark_country_labels_exposures.csv'),
                                        ('Company Domicile', 'company_domicile', 'benchmark_company_domicile_exposures.csv')]:
        separate = frame.groupby(column, dropna=False).Weight.sum().rename_axis('category').reset_index(name='weight')
        separate.insert(0, 'dimension', dimension)
        separate.to_csv(output / filename, index=False)
    missing_domicile = frame['Company Domicile'].eq('Unknown')
    frame.loc[missing_domicile, ['Bloomberg Ticker', 'Ticker', 'Name', 'Weight', 'Mapping Status']].to_csv(output / 'wls_missing_company_domiciles.csv', index=False)
    coverage['company_domicile'] = {
        'classified_weight': float(frame.loc[~missing_domicile, 'Weight'].sum()),
        'unknown_weight': float(frame.loc[missing_domicile, 'Weight'].sum()),
        'unknown_records': int(missing_domicile.sum())}
    coverage['country_labels'] = {
        'classified_weight': float(frame.loc[frame.Country.ne('Unknown'), 'Weight'].sum()),
        'unknown_weight': float(frame.loc[frame.Country.eq('Unknown'), 'Weight'].sum()),
        'unknown_records': int(frame.Country.eq('Unknown').sum())}
    listing_exposures = frame.groupby('Listing Market Country', dropna=False).Weight.sum().rename_axis('category').reset_index(name='weight')
    listing_exposures.insert(0, 'dimension', 'listing_market')
    listing_exposures.to_csv(output / 'benchmark_listing_market_exposures.csv', index=False)
    coverage['listing_market'] = {
        'classified_weight': float(frame.loc[frame['Listing Market Country'].ne('Unknown'), 'Weight'].sum()),
        'unknown_weight': float(frame.loc[frame['Listing Market Country'].eq('Unknown'), 'Weight'].sum()),
        'unknown_records': int(frame['Listing Market Country'].eq('Unknown').sum())}
    missing_listing = frame['Listing Market Country'].eq('Unknown')
    frame.loc[missing_listing, ['Bloomberg Ticker', 'Ticker', 'Name', 'Weight', 'Mapping Status']].to_csv(output / 'wls_missing_listing_countries.csv', index=False)
    incomplete = frame[[country_column, 'Sector', 'Industry']].eq('Unknown').any(axis=1) | frame['Mapping Status'].ne('MAPPED')
    frame.loc[incomplete, ['Bloomberg Ticker', 'Ticker', 'Name', 'Weight', 'Country', 'Company Domicile', 'Listing Market Country', 'Sector', 'Industry', 'Mapping Status']].to_csv(output / 'wls_missing_classifications.csv', index=False)
    listing_input = read_listing_countries('daily_monitor/data/listing_market_countries.csv')
    eligible_symbols = set(frame.loc[frame['Mapping Status'].eq('MAPPED'), 'Ticker'])
    unmatched_input = listing_input.loc[~listing_input.Ticker.isin(eligible_symbols)]
    unmatched_input.to_csv(output / 'listing_country_unmatched_input.csv', index=False)
    if as_of is None and str(source) == cfg.get('universe_source'):
        as_of = cfg.get('universe_verified_as_of')
    if as_of is not None:
        as_of = str(pd.Timestamp(as_of).date())
    summary = {'effective_date': as_of, 'date_source': cfg.get('universe_date_confirmation_source') if as_of == cfg.get('universe_verified_as_of') else 'Explicit build argument', 'source': str(source), 'classification_source': str(metadata), 'listing_country_source': 'daily_monitor/data/listing_market_countries.csv', 'snapshot_records': len(frame),
               'mapped_records': int(frame['Mapping Status'].eq('MAPPED').sum()),
               'ambiguous_records': int(frame['Mapping Status'].eq('AMBIGUOUS').sum()),
               'listing_country_input_rows': len(listing_input),
               'listing_country_input_tickers_without_snapshot_match': len(unmatched_input),
               'geographic_limit_basis': country_basis, 'domicile_input_records': len(read_company_domiciles(domicile_path)),
               'source_weight_sum': float(frame.Weight.sum()), 'dimensions': coverage,
               'method': 'No reweighting of classified subset; Unknown retains actual uncovered index weight. Exchange jurisdiction is not company country.'}
    (output / 'wls_classification_coverage.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', default=DEFAULT_SOURCE)
    p.add_argument('--metadata', default='yahoo_enrichment/output/stock_metadata.xlsx')
    p.add_argument('--output', type=Path, default=Path('daily_monitor/data'))
    p.add_argument('--as-of', help='Explicit snapshot date when building a different source')
    args = p.parse_args()
    print(json.dumps(build(args.source, args.metadata, args.output, args.as_of), indent=2))


if __name__ == '__main__':
    main()

"""Enrich Full Rankings from Yahoo Finance company profiles.

Run inside BTC/.venv after: python -m pip install -r requirements.txt
The input file must contain a 'Full Rankings' sheet with Name/Ticker/Sector/Industry.
The program uses Yahoo Finance via yfinance, not price-history downloads.
"""
from __future__ import annotations

import argparse
import csv
import random
import time
from pathlib import Path

from openpyxl import load_workbook
import yfinance as yf

FIELDS = ('Name', 'Sector', 'Industry')
CACHE_FIELDS = ('Ticker', 'Name', 'Sector', 'Industry', 'Status', 'Error')


def clean(value):
    return str(value).strip() if value is not None else ''


def read_cache(path):
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8-sig') as f:
        return {r['Ticker']: r for r in csv.DictReader(f) if r.get('Ticker')}


def write_cache(path, cache):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_FIELDS)
        writer.writeheader()
        for ticker in sorted(cache):
            writer.writerow({col: cache[ticker].get(col, '') for col in CACHE_FIELDS})
    temp.replace(path)


def query_yahoo(ticker):
    try:
        info = yf.Ticker(ticker).get_info()
        if not isinstance(info, dict):
            return dict(Ticker=ticker, Name='', Sector='', Industry='', Status='unresolved', Error='No profile')
        company = clean(info.get('longName') or info.get('shortName'))
        sector = clean(info.get('sector'))
        industry = clean(info.get('industry'))
        return dict(Ticker=ticker, Name=company, Sector=sector, Industry=industry,
                    Status='complete' if all((company, sector, industry)) else 'partial', Error='')
    except Exception as exc:
        return dict(Ticker=ticker, Name='', Sector='', Industry='', Status='error',
                    Error=f'{type(exc).__name__}: {str(exc)[:160]}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, type=Path, help='Source workbook (never modified)')
    p.add_argument('--output', type=Path, help='Final workbook (default: output/stock_metadata.xlsx next to script)')
    p.add_argument('--cache', type=Path, help='Progress CSV (default: output/lookup_cache.csv next to script)')
    p.add_argument('--limit', type=int, default=0, help='Max NEW Yahoo lookups this run; 0 means all')
    p.add_argument('--delay', type=float, default=2.0, help='Seconds between requests (default 2)')
    p.add_argument('--batch-size', type=int, default=50, help='Number of requests between longer pauses (default 50)')
    p.add_argument('--batch-pause', type=float, default=120, help='Seconds to pause between batches (default 120)')
    p.add_argument('--rate-limit-pause', type=float, default=900, help='Seconds to wait after HTTP 429 (default 900)')
    p.add_argument('--max-rate-limit-retries', type=int, default=3, help='Retries per ticker after 429 before stopping safely')
    p.add_argument('--retry-failed', action='store_true', help='Retry earlier partial/error/unresolved results')
    args = p.parse_args()
    output_dir = Path(__file__).resolve().parent / 'output'
    args.output = args.output or output_dir / 'stock_metadata.xlsx'
    args.cache = args.cache or output_dir / 'lookup_cache.csv'
    # Protect the existing progress cache from accidental resets on upgrade.
    previous_cache = Path(__file__).resolve().parent / 'yahoo_lookup_progress.csv'
    if not args.cache.exists() and previous_cache.exists():
        import shutil
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(previous_cache, args.cache)
        print(f'Migrated existing lookup cache to {args.cache}', flush=True)
    if args.output.resolve() == args.input.resolve():
        p.error('Output must differ from input to protect the source workbook')

    print('Loading workbook...')
    workbook = load_workbook(args.input)
    if 'Full Rankings' not in workbook.sheetnames:
        raise ValueError('Workbook must contain a Full Rankings sheet')
    sheet = workbook['Full Rankings']
    header = [clean(cell.value) for cell in sheet[1]]
    cols = {h: i for i, h in enumerate(header)}
    if not all(h in cols for h in ('Ticker', *FIELDS)):
        raise ValueError(f'Missing expected columns: {header}')
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    tickers = list(dict.fromkeys(clean(row[cols['Ticker']]) for row in rows if clean(row[cols['Ticker']])))
    cache = read_cache(args.cache)
    if args.batch_size < 1 or args.delay < 0 or args.batch_pause < 0 or args.rate_limit_pause < 0 or args.max_rate_limit_retries < 0 or args.limit < 0:
        p.error('Batch size must be positive; delays, retry count, and limit must be nonnegative')

    new_count = 0
    batch_count = 0
    try:
        for index, ticker in enumerate(tickers, 1):
            existing = cache.get(ticker)
            if existing and (not args.retry_failed or existing.get('Status') == 'complete'):
                continue
            if args.limit and new_count >= args.limit:
                break

            # Pauses are between completed batches; a single invocation continues automatically.
            if batch_count >= args.batch_size:
                write_cache(args.cache, cache)
                print(f'Batch complete. Sleeping {args.batch_pause:.0f}s before continuing...', flush=True)
                time.sleep(args.batch_pause)
                batch_count = 0

            retries = 0
            while True:
                result = query_yahoo(ticker)
                error = result.get('Error', '').lower()
                rate_limited = result['Status'] == 'error' and (
                    '429' in error or 'ratelimit' in error or 'rate limit' in error or 'too many requests' in error
                )
                if not rate_limited:
                    break
                if retries >= args.max_rate_limit_retries:
                    print(f'Yahoo Finance continues to rate-limit after {retries} retries. '
                          'Stopping safely; run again later.', flush=True)
                    # Do not add the rate-limited result to the cache: rerun will retry this ticker.
                    break
                retries += 1
                write_cache(args.cache, cache)
                pause = args.rate_limit_pause * (2 ** (retries - 1))
                print(f'Rate limited on {ticker}. Waiting {pause:.0f}s '
                      f'(retry {retries}/{args.max_rate_limit_retries})...', flush=True)
                time.sleep(pause)

            if rate_limited:
                break
            cache[ticker] = result
            new_count += 1
            batch_count += 1
            print(f'{index}/{len(tickers)} {ticker}: {result["Status"]} | {result["Name"][:60]}', flush=True)
            if new_count % 20 == 0:
                write_cache(args.cache, cache)
                print(f'Checkpoint saved: {len(cache)} symbols', flush=True)
            time.sleep(args.delay + random.uniform(0, 0.3))
    except KeyboardInterrupt:
        print('Interrupted. Saving current progress.', flush=True)
    finally:
        write_cache(args.cache, cache)

    changed = 0
    # Fill blanks only; preserve existing classifications and all ranking data.
    for row_number, row in enumerate(sheet.iter_rows(min_row=2), start=2):
        ticker = clean(row[cols['Ticker']].value)
        record = cache.get(ticker, {})
        for field in FIELDS:
            cell = row[cols[field]]
            addition = clean(record.get(field, ''))
            if not clean(cell.value) and addition:
                cell.value = addition
                changed += 1
    print('Exporting edited workbook...')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(args.output)

    failed_path = args.output.parent / 'unresolved.csv'
    with failed_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_FIELDS)
        writer.writeheader()
        for ticker in tickers:
            row = cache.get(ticker, {})
            if row.get('Status') != 'complete':
                writer.writerow({col: row.get(col, '') if col != 'Ticker' else ticker for col in CACHE_FIELDS})
    print(f'Added {changed} missing cells; output: {args.output}')
    print(f'Progress cache: {args.cache}; unresolved report: {failed_path}')
    print('If rate-limited or interrupted, re-run the same command to resume.')


if __name__ == '__main__':
    main()

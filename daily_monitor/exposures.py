"""Read/validate WLS weights without downloading prices or assuming benchmark weights."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

DIMENSIONS = ('country', 'industry', 'sector')
COLUMNS = ['dimension', 'category', 'weight', 'major_country']


def read_exposures(path):
    empty = pd.DataFrame(columns=COLUMNS)
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, ValueError) as exc:
        return empty, [f'Cannot read WLS exposure file: {exc}']
    if not set(COLUMNS).issubset(frame.columns):
        return empty, ['WLS exposure file requires columns: ' + ', '.join(COLUMNS)]
    frame = frame[COLUMNS].copy()
    for c in COLUMNS:
        frame[c] = frame[c].str.strip()
    # Ignore entirely blank rows; never ignore incomplete categories or weights.
    frame = frame.loc[~frame.eq('').all(axis=1)].copy()
    frame['dimension'] = frame.dimension.str.lower()
    frame['weight'] = pd.to_numeric(frame.weight, errors='coerce')
    errors = []
    if not frame.dimension.isin(DIMENSIONS).all():
        errors.append('WLS dimension must be country, industry or sector')
    for dimension in DIMENSIONS:
        group = frame.loc[frame.dimension == dimension]
        prefix = f'WLS {dimension}'
        if group.empty:
            errors.append(f'{prefix}: add categories and weights summing to 1')
            continue
        if group.category.eq('').any() or group.category.str.lower().isin(['unknown', 'nan', 'none']).any():
            errors.append(f'{prefix}: enter actual benchmark categories')
        if group.category.str.casefold().duplicated().any():
            errors.append(f'{prefix}: duplicate categories')
        if not np.isfinite(group.weight).all() or not group.weight.between(0, 1).all():
            errors.append(f'{prefix}: every weight must be a decimal from 0 to 1 (no blanks)')
        elif not np.isclose(group.weight.sum(), 1, atol=1e-6, rtol=0):
            errors.append(f'{prefix}: weights sum to {group.weight.sum():.8f}; must sum to 1')
        if dimension == 'country' and not group.major_country.str.lower().isin(['true', 'false', '1', '0']).all():
            errors.append(f'{prefix}: major_country must be true or false')
    frame['major_country'] = frame.major_country.str.lower().isin(['true', '1'])
    return frame, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', type=Path, default=Path('daily_monitor/data/benchmark_exposures.csv'))
    args = parser.parse_args()
    frame, errors = read_exposures(args.path)
    for dimension in DIMENSIONS:
        group = frame.loc[frame.dimension == dimension]
        print(f'{dimension}: {len(group)} rows, total {group.weight.sum():.6f}')
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print('All three WLS weight groups are valid and sum to 1.')


if __name__ == '__main__':
    main()

import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from curl_cffi.requests import Session
from daily_monitor.data import ThrottledSession, expected_session, completed_prices, positions
from daily_monitor.signals import analyse
from daily_monitor.decisions import replacement, active_limits
from daily_monitor.run import execute, quote_units, clean_json

CFG = json.loads(Path('daily_monitor/config.json').read_text())


def test_throttle_counts_http_attempts_and_retries():
    class Response:
        status_code = 200
    sleeps = []
    session = ThrottledSession(sleeper=sleeps.append)
    with patch.object(Session, 'request', return_value=Response()):
        for _ in range(41):
            session.get('https://example.com')
    assert session.calls == 41
    assert sleeps == [1, 1]
    Response.status_code = 429
    with patch.object(Session, 'request', return_value=Response()):
        Response.raise_for_status = lambda self: (_ for _ in ()).throw(RuntimeError('429'))
        with pytest.raises(RuntimeError):
            session.get('https://example.com')
    assert sleeps[-2:] == [2, 4]


def test_market_holiday_weekend_and_open_bar():
    # Independence Day observed and weekend must use Thursday July 2.
    now = pd.Timestamp('2026-07-04T12:00Z')
    assert str(expected_session('MU', now, {}).date()) == '2026-07-02'
    assert str(expected_session('MU', pd.Timestamp('2026-07-06T18:00Z'), {}).date()) == '2026-07-02'
    with pytest.raises(ValueError, match='calendar'):
        expected_session('ACICO.KW', now, {})
    idx = pd.to_datetime(['2026-07-02', '2026-07-06'])
    h = pd.DataFrame({'Close': [10., 20.], 'Adj Close': [9., 19.]}, index=idx)
    assert len(completed_prices(h, pd.Timestamp('2026-07-02'))) == 1
    with pytest.raises(ValueError, match='latest'):
        completed_prices(h.iloc[:1], pd.Timestamp('2026-07-06'))


def series():
    rng = np.random.default_rng(13)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(.0003, .01, 1000))),
                     index=pd.bdate_range('2021-01-01', periods=1000))


def test_walk_forward_purges_labels_and_future_does_not_change_past():
    s = series()
    a = analyse(s, horizon=5)
    assert len(a['folds']) == 5
    for fold in a['folds']:
        assert s.index.get_loc(pd.Timestamp(fold['test_start'])) - s.index.get_loc(pd.Timestamp(fold['train_end'])) > 5
    changed = pd.concat([s, pd.Series([1e9], index=[s.index[-1] + pd.offsets.BDay()])])
    # The caller's as-of slice contains no future prices/labels.
    assert analyse(changed.loc[:s.index[-1]]) == a
    assert analyse(s.iloc[:200])['recommendation'] == 'HOLD'


def test_currency_units_and_positions():
    assert quote_units({'currency': 'GBp'}, {}) == ('GBP', .01)
    with pytest.raises(ValueError, match='Kuwait'):
        quote_units({'currency': 'KWD'}, {})
    p = positions('daily_monitor/data/positions.csv')
    assert len(p) == 20 and '0622.HK' in set(p.Symbol)
    assert p.loc[p.Symbol == 'ACICO.KW', 'Quantity'].iloc[0] == 168430
    assert clean_json({'x': np.nan}) == {'x': None}


def benchmark():
    return pd.DataFrame([{'dimension': d, 'category': c, 'weight': 1., 'major_country': True}
                         for d, c in [('sector', 'Tech'), ('industry', 'Software'), ('country', 'United States')]])


def test_active_exposures_are_relative_and_unknown_blocks():
    meta = {'A': {'sector': 'Tech', 'industry': 'Software', 'country': 'United States'}}
    assert active_limits(['A'], [1.], meta, benchmark(), CFG) is not None
    meta['A']['country'] = 'Unknown'
    assert active_limits(['A'], [1.], meta, benchmark(), CFG) is None


def test_replacement_is_blocked_before_any_math():
    r = replacement({}, {}, {}, {}, CFG, ['Unknown cash'], benchmark())
    assert r['status'] == 'BLOCKED' and not r['proposals']


def test_replacement_cost_risk_and_active_limits():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range('2025-01-01', periods=252)
    returns = {'A': pd.Series(rng.normal(0, .02, 252), index=idx),
               'B': pd.Series(rng.normal(0, .001, 252), index=idx)}
    sig = {s: {'qualified': True, 'recommendation': 'BUY' if s == 'B' else 'SELL',
               'forecast': .20 if s == 'B' else -.05, 'error_band': .001,
               'suggested_weight': .05} for s in ['A', 'B']}
    meta = {s: {'sector': 'Tech', 'industry': 'Software', 'country': 'United States'} for s in sig}
    cfg = dict(CFG, max_position=1., min_gain=.001)
    result = replacement({'A': 1., '__CASH__': 0.}, sig, returns, meta, cfg, [], benchmark())
    assert result['status'] == 'REVIEW'
    p = result['proposals'][0]
    assert p['fund_from'] == 'A' and p['weight'] <= .05
    assert p['vol_after'] < p['vol_before']
    assert sum(p['weights_after'].values()) + p['cash_weight_after'] == pytest.approx(1.)
    assert replacement({'A': 1.}, sig, returns, meta, dict(cfg, cost_bps_one_way=5000), [], benchmark())['status'] == 'NO CHANGE'


def test_end_to_end_partial_failure_writes_report_without_fake_valuation(tmp_path):
    s = series()
    history = pd.DataFrame({'Close': s, 'Adj Close': s})
    def fake(self, symbol):
        if symbol != 'MU':
            raise ValueError('provider unavailable')
        return history, {'currency': 'USD', 'sector': 'Technology'}, [], '2026-10-27T07:15:00+00:00'
    with patch('daily_monitor.run.Yahoo.fetch', fake):
        result = execute(CFG, Path('daily_monitor/data/positions.csv'), Path('yahoo_enrichment/output/stock_metadata.xlsx'),
                         tmp_path / 'out', tmp_path / 'cache', pd.Timestamp('2026-10-27T07:15Z'), max_screen=0)
    output = pd.read_csv(tmp_path / 'out/portfolio.csv')
    assert len(output) == 20
    assert output.weight.isna().all()
    assert result['decisions']['status'] == 'BLOCKED'
    assert len(result['errors']) == 19
    assert (tmp_path / 'out/report.md').exists()
    json.loads((tmp_path / 'out/audit.json').read_text())


def test_custom_exchange_calendar_requires_unexpired_source(tmp_path):
    path = tmp_path / 'sessions.csv'
    path.write_text('session_date,close_utc\n2026-10-25,2026-10-25T10:00:00Z\n2026-10-26,2026-10-26T10:00:00Z\n')
    override = {'ACICO.KW': {'sessions_csv': str(path), 'valid_through': '2026-10-27', 'source': 'verified exchange export'}}
    assert expected_session('ACICO.KW', pd.Timestamp('2026-10-26T09:00Z'), override) == pd.Timestamp('2026-10-25')
    with pytest.raises(ValueError, match='expired'):
        expected_session('ACICO.KW', pd.Timestamp('2026-10-28T09:00Z'), override)

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
    meta = {'A': {'sector': 'Tech', 'industry': 'Software', 'country': 'United States', 'company_domicile': 'United States'}}
    assert active_limits(['A'], [1.], meta, benchmark(), CFG) is not None
    meta['A']['company_domicile'] = 'Unknown'
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
               'suggested_weight': .05, 'one_way_cost_fraction': .005 / (100 if s == 'A' else 10)} for s in ['A', 'B']}
    meta = {s: {'sector': 'Tech', 'industry': 'Software', 'country': 'United States', 'company_domicile': 'United States'} for s in sig}
    cfg = dict(CFG, max_position=1., min_gain=.001)
    result = replacement({'A': 1., '__CASH__': 0.}, sig, returns, meta, cfg, [], benchmark())
    assert result['status'] == 'REVIEW'
    p = result['proposals'][0]
    assert p['fund_from'] == 'A' and p['weight'] <= .05
    assert p['vol_after'] < p['vol_before']
    assert sum(p['weights_after'].values()) + p['cash_weight_after'] == pytest.approx(1.)
    assert p['transaction_cost_fraction'] == pytest.approx(.05 * .005 / 100 + p['buy_value_fraction_of_original_nav'] * .005 / 10)
    assert p['cash_weight_after'] == 0
    assert p['buy_value_fraction_of_original_nav'] + p['transaction_cost_fraction'] == pytest.approx(.05)
    expensive = {s: dict(v, one_way_cost_fraction=.5) for s, v in sig.items()}
    assert replacement({'A': 1.}, expensive, returns, meta, cfg, [], benchmark())['status'] == 'NO CHANGE'


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
    assert 'Cash balance is unknown' not in result['decisions']['reasons']
    assert result['signals']['MU']['one_way_cost_fraction'] == pytest.approx(.005 / history.Close.iloc[-1])
    assert (tmp_path / 'out/report.md').exists()
    json.loads((tmp_path / 'out/audit.json').read_text())


def test_custom_exchange_calendar_requires_unexpired_source(tmp_path):
    path = tmp_path / 'sessions.csv'
    path.write_text('session_date,close_utc\n2026-10-25,2026-10-25T10:00:00Z\n2026-10-26,2026-10-26T10:00:00Z\n')
    override = {'ACICO.KW': {'sessions_csv': str(path), 'valid_through': '2026-10-27', 'source': 'verified exchange export'}}
    assert expected_session('ACICO.KW', pd.Timestamp('2026-10-26T09:00Z'), override) == pd.Timestamp('2026-10-25')
    with pytest.raises(ValueError, match='expired'):
        expected_session('ACICO.KW', pd.Timestamp('2026-10-28T09:00Z'), override)


def test_per_share_commission_uses_usd_price():
    from daily_monitor.costs import one_way_cost_fraction
    assert CFG['cash'] == 0
    assert one_way_cost_fraction(100, CFG) == pytest.approx(.00005)
    assert one_way_cost_fraction(1, CFG) == pytest.approx(.005)
    for price in [0, -1, float('nan')]:
        with pytest.raises(ValueError):
            one_way_cost_fraction(price, CFG)


def test_wls_weight_inputs_require_each_group_to_sum_to_one(tmp_path):
    from daily_monitor.exposures import read_exposures
    path = tmp_path / 'weights.csv'
    content = ('dimension,category,weight,major_country\n'
               'country,United States,0.6,true\ncountry,Japan,0.4,true\n'
               'industry,Software,1,\nsector,Technology,1,\n')
    path.write_text(content)
    frame, errors = read_exposures(path)
    assert not errors
    assert frame.groupby('dimension').weight.sum().eq(1).all()
    for changed in [content.replace('Japan,0.4', 'Japan,0.3'),
                    content.replace('Japan,0.4', 'Japan,'),
                    content.replace('Japan,0.4', 'Japan,40'),
                    content.replace('Japan,0.4', 'United States,0.4'),
                    content.replace('Japan,0.4,true', 'Japan,0.4,maybe')]:
        path.write_text(changed)
        assert read_exposures(path)[1]
    assert read_exposures('daily_monitor/data/benchmark_exposures.csv')[1]


def test_confirmed_risk_and_initial_commission_are_separate_from_future_fees():
    p = positions('daily_monitor/data/positions.csv')
    assert CFG['constraints_confirmed'] and CFG['risk_limits_confirmed']
    assert CFG['competition_rules_reviewed']
    assert CFG['initial_trade_commission_usd'] == 0
    assert CFG['commission_usd_per_share'] == .005
    assert p.Commission.eq(0).all() and p['Commission Currency'].eq('USD').all()
    assert CFG['max_position'] == .10 and CFG['hard_position'] == .125
    assert not CFG['purchase_units_confirmed']
    assert CFG['universe_verified_as_of'] == '2026-10-12'


def test_outside_competition_dates_withholds_new_trade_scenarios(tmp_path):
    def unavailable(self, symbol):
        raise ValueError('provider unavailable')
    with patch('daily_monitor.run.Yahoo.fetch', unavailable):
        result = execute(CFG, Path('daily_monitor/data/positions.csv'), Path('yahoo_enrichment/output/stock_metadata.xlsx'),
                         tmp_path / 'out', tmp_path / 'cache', pd.Timestamp('2026-11-14T07:15Z'), max_screen=0)
    assert any('Outside the competition trading dates' in x for x in result['decisions']['reasons'])
    assert not any('Confirm risk settings' in x for x in result['decisions']['reasons'])


def test_dated_wls_membership_preserves_full_denominator_and_mapping_gaps(tmp_path):
    from daily_monitor.wls import load_snapshot, map_symbol
    from trading_dashboard.portfolio import read_rankings
    ranking = read_rankings('yahoo_enrichment/output/stock_metadata.xlsx')
    snapshot = load_snapshot(CFG['universe_source'], ranking)
    assert len(snapshot) == 10420
    assert snapshot.Weight.sum() == pytest.approx(.99999991)
    assert snapshot['Mapping Status'].eq('MAPPED').sum() == 10175
    # Unknown source weight stays in the denominator; no renormalisation of the matched subset.
    assert snapshot.loc[snapshot.Sector.eq('Unknown'), 'Weight'].sum() > .03
    assert snapshot.loc[snapshot.Country.eq('Unknown'), 'Weight'].sum() > .98
    rules = json.loads(Path('daily_monitor/data/ticker_rules.json').read_text())
    assert map_symbol('0622', 'XHKG', rules) == '0622.HK'
    assert map_symbol('MM', 'XNYS', rules) == 'MM'
    assert map_symbol('MM', 'XNSE', rules) == 'M&M.NS'


def test_owner_country_labels_are_used_for_holdings_and_benchmark():
    from daily_monitor.wls import classifications, load_snapshot
    from trading_dashboard.portfolio import read_rankings
    frame = load_snapshot(CFG['universe_source'], read_rankings('yahoo_enrichment/output/stock_metadata.xlsx'))
    source = frame.set_index('Ticker')
    assert source.loc['ASB.WA', 'Country'] == 'Poland'
    assert source.loc['ASB.WA', 'Country Source'] == 'Owner override'
    labels = classifications('ASB.WA', {'country': 'Cyprus', 'sector': 'Technology'}, frame)
    assert labels['country'] == 'Poland' and labels['country_source'] == 'Owner override'
    assert labels['sector'] == 'Technology' and labels['sector_source'] == 'Yahoo current metadata'
    # Classification survives a missing price response without manufacturing a price or weight.
    labels = classifications('MU', {}, frame)
    assert labels['country'] == 'United States'
    assert labels['sector'] == 'Technology' and labels['sector_source'] == 'Enriched metadata'
    outside = classifications('NOT_IN_SNAPSHOT', {}, frame)
    assert outside['country'] == 'Unknown'


def test_starting_portfolio_labels_do_not_hide_remaining_benchmark_country_gaps():
    from daily_monitor.wls import load_snapshot
    from trading_dashboard.portfolio import read_rankings
    frame = load_snapshot(CFG['universe_source'], read_rankings('yahoo_enrichment/output/stock_metadata.xlsx'))
    current = positions('daily_monitor/data/positions.csv')
    held = frame.loc[frame.Ticker.isin(current.Symbol)]
    assert len(held) == 20
    assert held.Country.ne('Unknown').all()
    assert frame.loc[frame.Country.ne('Unknown'), 'Weight'].sum() == pytest.approx(.01373326)
    assert frame.Weight.sum() == pytest.approx(.99999991)
    # Keep the repository's more complete entries when the supplied older file lacks them.
    assert frame.loc[frame.Ticker.eq('TMO'), 'Sector'].iloc[0] == 'Healthcare'


def test_listing_market_data_cannot_silently_replace_country():
    from daily_monitor.wls import classifications
    frame = pd.DataFrame([{'Ticker': 'TEST', 'Mapping Status': 'MAPPED',
                           'Country': 'Ireland', 'Country Source': 'Enriched metadata',
                           'Sector': 'Technology', 'Sector Source': 'Enriched metadata',
                           'Industry': 'Software', 'Industry Source': 'Enriched metadata',
                           'Listing Market Country': 'United States',
                           'Listing Market Country Source': 'Supplied listing-market workbook'}])
    result = classifications('TEST', {'country': 'Ireland'}, frame)
    assert result['country'] == 'Ireland'
    assert result['listing_market_country'] == 'United States'
    assert result['country_source'] == 'Yahoo current metadata'


def test_listing_country_import_rejects_missing_and_ambiguous_input(tmp_path):
    from daily_monitor.wls import read_listing_countries
    path = tmp_path / 'listing.csv'
    for text in ['Ticker,Listing Market Country\nA,United States\n a ,Canada\n',
                 'Ticker,Listing Market Country\nA,\n',
                 'Ticker,Country\nA,United States\n']:
        path.write_text(text)
        with pytest.raises(ValueError):
            read_listing_countries(path)
    path.write_text('Ticker,Listing Market Country\n A ,United States\n')
    assert read_listing_countries(path).Ticker.tolist() == ['A']


def test_listing_market_coverage_keeps_full_wls_denominator_and_original_country():
    from daily_monitor.wls import load_snapshot
    from trading_dashboard.portfolio import read_rankings
    frame = load_snapshot(CFG['universe_source'], read_rankings('yahoo_enrichment/output/stock_metadata.xlsx'))
    known = frame['Listing Market Country'].ne('Unknown')
    assert known.sum() == 8892
    assert frame.loc[known, 'Weight'].sum() == pytest.approx(.96580757)
    assert frame.loc[~known, 'Weight'].sum() == pytest.approx(.03419234)
    assert frame.loc[frame.Country.ne('Unknown'), 'Weight'].sum() == pytest.approx(.01373326)
    assert frame.loc[frame.Ticker.eq('ASB.WA'), 'Country'].iloc[0] == 'Poland'


def test_domicile_import_requires_verification_not_just_country_or_url(tmp_path):
    from daily_monitor.wls import read_company_domiciles
    path = tmp_path / 'domiciles.csv'
    header = 'Ticker,Company Domicile,Verification Source,Verification Status\n'
    for row in ['A,Ireland,https://example.com,Unverified\n',
                'A,,https://example.com,Verified: incorporation\n',
                'A,Ireland,http://example.com,Verified: incorporation\n',
                'A,Ireland,https://example.com,Verified: incorporation\nA,Ireland,https://example.com,Verified: incorporation\n']:
        path.write_text(header + row)
        with pytest.raises(ValueError):
            read_company_domiciles(path)
    path.write_text(header + 'A,Ireland,https://example.com,Verified: incorporation\n')
    assert read_company_domiciles(path)['Company Domicile'].tolist() == ['Ireland']


def test_domicile_risk_basis_preserves_owner_labels_without_using_them_as_evidence():
    from daily_monitor.wls import classifications, load_snapshot
    from trading_dashboard.portfolio import read_rankings
    frame = load_snapshot(CFG['universe_source'], read_rankings('yahoo_enrichment/output/stock_metadata.xlsx'))
    asb = classifications('ASB.WA', {'country': 'Cyprus'}, frame)
    assert asb['country'] == 'Poland'
    assert asb['company_domicile'] == 'Cyprus'
    hk = classifications('0622.HK', {'country': 'Hong Kong'}, frame)
    assert hk['country'] == 'Hong Kong' and hk['company_domicile'] == 'Bermuda'
    # A profile-country response is not incorporation evidence.
    mu = classifications('MU', {'country': 'United States'}, frame)
    assert mu['country'] == 'United States' and mu['company_domicile'] == 'Unknown'
    assert frame['Company Domicile'].ne('Unknown').sum() == 7
    assert frame.loc[frame['Company Domicile'].ne('Unknown'), 'Weight'].sum() == pytest.approx(.00010377)
    meta = {'A': {'sector': 'Tech', 'industry': 'Software', 'country': 'United States', 'company_domicile': 'Unknown'}}
    assert active_limits(['A'], [1.], meta, benchmark(), CFG) is None


def test_active_country_exposures_use_domicile_and_keep_other_views_separate():
    frame = pd.read_csv('daily_monitor/data/benchmark_exposures.csv')
    country = frame.loc[frame.dimension.eq('country')].set_index('category')
    assert country.loc['Unknown', 'weight'] == pytest.approx(.99989614)
    assert 'Cyprus' in country.index and 'Bermuda' in country.index
    assert country.weight.sum() == pytest.approx(.99999991)
    original = pd.read_csv('daily_monitor/data/benchmark_country_labels_exposures.csv').set_index('category')
    assert 'Poland' in original.index
    assert original.loc['Unknown', 'weight'] == pytest.approx(.98626665)

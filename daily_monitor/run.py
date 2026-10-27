"""Run with python -m daily_monitor.run. All paths relative to repository root."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import html
import numpy as np
import pandas as pd
import yfinance as yf
from trading_dashboard.portfolio import read_rankings
from .data import Yahoo, positions
from .signals import analyse
from .decisions import replacement
from .costs import one_way_cost_fraction
from .exposures import read_exposures
from .wls import load_snapshot, classifications

DEFAULT_UNIVERSE = 'yahoo_enrichment/output/stock_metadata.xlsx'


def fx_history(provider, currency, base, now):
    if currency == base:
        return None
    # FX is separate from equity calendars; use only dates strictly before UTC today.
    ticker = yf.Ticker(f'{currency}{base}=X', session=provider.session)
    h = ticker.history(period='5y', auto_adjust=False, raise_errors=True)
    s = h.Close.copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    cutoff = now.tz_convert('UTC').normalize().tz_localize(None)
    s = s[s.index < cutoff]
    if s.empty or (cutoff - s.index[-1]).days > 4 or not np.isfinite(s).all() or (s <= 0).any():
        raise ValueError(f'Invalid/stale FX {currency}/{base}')
    return s


def quote_units(info, override):
    code = override.get('currency', info.get('currency'))
    special = {'GBp': ('GBP', .01), 'GBX': ('GBP', .01), 'ZAc': ('ZAR', .01), 'ILA': ('ILS', .01)}
    currency, factor = special.get(code, (code, 1.0))
    if code in ('KWF', 'KWD') and not override:
        raise ValueError('Kuwait quote scale requires explicit quote_overrides confirmation')
    factor = override.get('scale', factor)
    if not currency or not isinstance(currency, str) or len(currency) != 3 or factor <= 0:
        raise ValueError('Unknown quote currency/unit')
    return currency, factor


def safe_text(value):
    return html.escape(str(value)).replace('\n', ' ').replace('|', '&#124;')


def execute(cfg, input_path, universe_path, output, cache, now, max_screen=None):
    output.mkdir(parents=True, exist_ok=True)
    p = positions(input_path)
    rankings = read_rankings(universe_path)
    membership_records = None
    snapshot = None
    if cfg.get('universe_source'):
        snapshot = load_snapshot(cfg['universe_source'], rankings, domiciles=cfg.get('company_domicile_source', 'daily_monitor/data/company_domiciles.csv'))
        membership_records = len(snapshot)
        universe = snapshot.loc[snapshot['Mapping Status'].eq('MAPPED')].copy()
    else:
        universe = rankings
    universe = universe.sort_values('Rank', na_position='last')
    n = max_screen if max_screen is not None else cfg['max_screen']
    # Fixed bounded daily rotation, not an undocumented claim of a full-universe screen.
    pool = universe[~universe.Ticker.isin(p.Symbol)]
    offset = (now.date().toordinal() * n) % max(1, len(pool))
    subset = pd.concat([pool.iloc[offset:], pool.iloc[:offset]]).head(n)
    symbols = list(dict.fromkeys(p.Symbol.tolist() + subset.Ticker.tolist()))
    provider = Yahoo(cache, now, cfg['calendar_overrides'])
    signals, histories, infos, headlines, errors, retrieved = {}, {}, {}, {}, {}, {}
    fx_cache = {cfg['base_currency']: None}
    base_returns, values, metadata = {}, {}, {}
    rows = []
    for symbol in symbols:
        metadata[symbol] = classifications(symbol, {}, snapshot)
        try:
            h, info, news, stamp = provider.fetch(symbol)
            histories[symbol], infos[symbol], headlines[symbol], retrieved[symbol] = h, info, news, stamp
            metadata[symbol] = classifications(symbol, info, snapshot)
            currency, scale = quote_units(info, cfg['quote_overrides'].get(symbol, {}))
            if currency not in fx_cache:
                fx_cache[currency] = fx_history(provider, currency, cfg['base_currency'], now)
            fx = fx_cache[currency]
            if fx is None:
                rate = pd.Series(1., index=h.index)
            else:
                # Backward-only alignment, maximum four calendar days; never backfill.
                rate = fx.reindex(h.index, method='ffill', tolerance=pd.Timedelta(days=4))
            converted = h['Adj Close'] * scale * rate
            # Returns use only consecutive valid observations; no implicit fill.
            base_returns[symbol] = converted.pct_change(fill_method=None)
            last_rate = float(rate.iloc[-1])
            if not np.isfinite(last_rate):
                raise ValueError('FX unavailable at equity session date')
            price_usd = float(h.Close.iloc[-1]) * scale * last_rate
            fee_fraction = one_way_cost_fraction(price_usd, cfg)
            signals[symbol] = analyse(h['Adj Close'], cfg['horizon'], fee_fraction * 10000)
            signals[symbol].update(one_way_cost_fraction=fee_fraction, price_usd=price_usd,
                                   fundamental_context=fundamental_context(info))
            holding = p[p.Symbol == symbol]
            if not holding.empty:
                row = holding.iloc[0].to_dict()
                value = float(h.Close.iloc[-1]) * scale * last_rate * row['Quantity']
                values[symbol] = value
                row.update(latest_close=float(h.Close.iloc[-1]), price_session=str(h.index[-1].date()),
                           quote_currency=currency, quote_scale=scale, fx_to_base=last_rate,
                           base_value=value, recommendation=signals[symbol]['recommendation'],
                           data_status='CURRENT', retrieved_at=stamp, **metadata[symbol])
                rows.append(row)
        except Exception as exc:
            errors[symbol] = f'{type(exc).__name__}: {str(exc)[:220]}'
            # A price-only model cannot override an unresolved currency/calendar/data failure.
            signals[symbol] = {'recommendation': 'HOLD', 'qualified': False, 'reason': errors[symbol]}
            if symbol in set(p.Symbol):
                row = p[p.Symbol == symbol].iloc[0].to_dict()
                row.update(data_status='UNAVAILABLE', recommendation='HOLD', error=errors[symbol], **metadata[symbol])
                rows.append(row)
    blockers = []
    if len(values) != len(p):
        blockers.append('Incomplete current portfolio valuations; aggregate weights suppressed')
    if not cfg['constraints_confirmed']:
        blockers.append('Confirm risk settings and review competition rules in config')
    if cfg.get('competition_rules_reviewed'):
        rules = cfg['competition_rules']
        local_day = now.tz_convert(cfg['timezone']).date()
        if not pd.Timestamp(rules['start_date']).date() <= local_day <= pd.Timestamp(rules['end_date']).date():
            blockers.append('Outside the competition trading dates; new-trade scenarios withheld')
    if cfg['cash'] is None:
        blockers.append('Cash balance is unknown')
    if not cfg['purchase_units_confirmed']:
        blockers.append('Purchase-price units/corporate actions unconfirmed; cost/P&L suppressed')
    if not cfg['universe_verified_as_of']:
        blockers.append('WLS membership/as-of date not verified; workbook is a historical candidate snapshot')
    if any(not item.get('reconciled', False) for item in cfg['cost_basis_overrides'].values()):
        blockers.append('Stated ACICO total purchase cost is unreconciled with shares × price × currency')
    if cfg['cash'] is not None and cfg['cash'] < 0:
        raise ValueError('Cash cannot be negative')
    total = sum(values.values()) + (cfg['cash'] or 0)
    weights = {s: v / total for s, v in values.items()} if len(values) == len(p) and total > 0 else {}
    if weights:
        weights['__CASH__'] = (cfg['cash'] or 0) / total
    exposures, exposure_errors = read_exposures(cfg['benchmark_exposures'])
    blockers.extend(exposure_errors)
    if cfg.get('geographic_limit_basis') == 'company_domicile' and snapshot is not None and snapshot['Company Domicile'].eq('Unknown').any():
        known_weight = float(snapshot.loc[snapshot['Company Domicile'].ne('Unknown'), 'Weight'].sum())
        blockers.append(f'Company-domicile coverage is {known_weight:.4%} of WLS weight; unverified domiciles remain missing')
    team = pd.read_csv(cfg['team_scores']).set_index('symbol')
    risk = {'effective_holdings': float(1 / sum(v ** 2 for k, v in weights.items() if k != '__CASH__')) if weights else None,
            'target_holdings': cfg['target_holdings'], 'current_holdings': len(p),
            'portfolio_minus_30pct_impact': -.30 * sum(v for k, v in weights.items() if k != '__CASH__') if weights else None}
    held = p.Symbol.tolist()
    if weights and all(s in base_returns for s in held):
        joint = pd.concat({s: base_returns[s] for s in held}, axis=1).dropna().tail(252)
        if len(joint) >= 126:
            portfolio_returns = joint.dot(pd.Series(weights).reindex(held))
            risk['annual_vol'] = float(portfolio_returns.std() * np.sqrt(252))
            risk['common_sessions'] = len(joint)
            risk['effective_holdings_ex_cash'] = float(sum(weights[s] for s in held) ** 2 / sum(weights[s] ** 2 for s in held))
        else:
            blockers.append('Fewer than 126 common portfolio return sessions')
    for symbol, signal in signals.items():
        if not signal.get('qualified'):
            continue
        vol = signal['annual_vol']
        correlation = None
        if symbol in base_returns and weights:
            paired = pd.concat({s: base_returns[s] for s in held + ([symbol] if symbol not in held else [])}, axis=1).dropna().tail(252)
            if len(paired) >= 126:
                portfolio = paired[held].dot(pd.Series(weights).reindex(held))
                correlation = float(paired[symbol].corr(portfolio))
        vol_points = 1 if vol < .20 else (-1 if vol > .40 else 0)
        corr_points = 1 if correlation is not None and correlation < .30 else (-1 if correlation is not None and correlation > .70 else 0)
        fundamental_points = int(team.loc[symbol, 'fundamental_score']) if symbol in team.index else signal.get('fundamental_context', {}).get('score', 0)
        event_points = int(team.loc[symbol, 'event_risk_score']) if symbol in team.index else 0
        if fundamental_points not in (-1, 0, 1) or event_points not in (-1, 0, 1):
            raise ValueError('Team scores must be -1, 0 or 1')
        points = fundamental_points + event_points + vol_points + corr_points
        tier_cap = .05 if points <= 0 else (.08 if points <= 2 else .10)
        # Transparent heuristic: equal-weight anchor, signal/error strength and inverse vol.
        strength = min(2., max(.5, abs(signal['forecast']) / max(signal['error_band'], .001)))
        target = min(tier_cap, cfg['max_position'], (1 / 15) * strength * .20 / max(vol, .10))
        signal.update(team_approved=symbol in team.index and str(team.loc[symbol, 'approved']).lower() in ('true', '1', '1.0'), conviction_points=points, suggested_weight=target, correlation=correlation,
                      volatility_points=vol_points, correlation_points=corr_points,
                      fundamental_points=fundamental_points, event_risk_points=event_points)
        if symbol not in held and (symbol not in team.index or str(team.loc[symbol, 'approved']).lower() not in ('true', '1', '1.0')):
            signal['recommendation'] = 'HOLD'
            signal['reason'] = 'Quantitative candidate pending team fundamental/event-risk approval'
    if any(v > cfg['hard_position'] for k, v in weights.items() if k != '__CASH__'):
        blockers.append('Existing position exceeds 12.5% hard barrier; review concentration first')
    result = replacement(weights, signals, base_returns, metadata, cfg, blockers, exposures)
    frame = pd.DataFrame(rows)
    frame['base_currency'] = cfg['base_currency']
    frame['weight'] = frame.Symbol.map(weights)
    frame['run_at'] = now.isoformat()
    frame['confirmed_total_cost_usd'] = frame.Symbol.map({k: v['total_usd'] for k, v in cfg['cost_basis_overrides'].items()})
    frame['cost_basis_reconciled'] = frame.Symbol.map({k: v['reconciled'] for k, v in cfg['cost_basis_overrides'].items()})
    if cfg['purchase_units_confirmed']:
        # Historical purchase FX is unavailable: report only quote-currency price return.
        frame['local_price_return'] = frame.latest_close * frame.quote_scale / frame['Purchase Price'] - 1
    benchmark = {'status': 'UNAVAILABLE', 'reason': 'Supply an authorised WLS benchmark ticker; no proxy silently substituted'}
    if cfg.get('benchmark_ticker'):
        try:
            b, bi, _, _ = provider.fetch(cfg['benchmark_ticker'])
            currency, scale = quote_units(bi, cfg['quote_overrides'].get(cfg['benchmark_ticker'], {}))
            if currency not in fx_cache:
                fx_cache[currency] = fx_history(provider, currency, cfg['base_currency'], now)
            fx = fx_cache[currency]
            bs = b['Adj Close'] * scale
            if fx is not None:
                bs = bs * fx.reindex(bs.index, method='ffill', tolerance=pd.Timedelta(days=4))
            if not weights or len(base_returns) < len(p):
                raise ValueError('Incomplete portfolio for benchmark comparison')
            joint = pd.concat({s: base_returns[s] for s in p.Symbol}, axis=1).join(bs.pct_change(fill_method=None).rename('__BENCH__')).dropna().tail(60)
            if len(joint) < 40:
                raise ValueError('Insufficient common sessions')
            pr = joint[p.Symbol.tolist()].dot(pd.Series(weights).reindex(p.Symbol))
            benchmark = {'status': 'AVAILABLE', 'ticker': cfg['benchmark_ticker'], 'sessions': len(joint),
                         'portfolio_constant_current_weight_return': float((1 + pr).prod() - 1),
                         'benchmark_return': float((1 + joint['__BENCH__']).prod() - 1)}
        except Exception as exc:
            benchmark = {'status': 'UNAVAILABLE', 'reason': str(exc)}
    geographic_column = {'company_domicile': 'Company Domicile', 'listing_market': 'Listing Market Country', 'country_labels': 'Country'}[cfg.get('geographic_limit_basis', 'country_labels')]
    geographic_label = {'company_domicile': 'company domicile', 'listing_market': 'listing-exchange country', 'country_labels': 'owner country labels'}[cfg.get('geographic_limit_basis', 'country_labels')]
    payload = {'run_at': now.isoformat(), 'coverage': {'snapshot_universe': len(universe), 'source_membership_records': membership_records,
               'attempted': len(symbols), 'priced': len(histories), 'screen_limit': n,
               'rotation_offset': offset, 'universe_path': str(universe_path),
               'membership_verified_as_of': cfg['universe_verified_as_of'],
               'geographic_limit_basis': cfg.get('geographic_limit_basis', 'country_labels'),
               'geographic_classified_weight': float(snapshot.loc[snapshot[geographic_column].ne('Unknown'), 'Weight'].sum()) if snapshot is not None else None,
               'company_domicile_classified_weight': float(snapshot.loc[snapshot['Company Domicile'].ne('Unknown'), 'Weight'].sum()) if snapshot is not None else None,
               'listing_market_classified_weight': float(snapshot.loc[snapshot['Listing Market Country'].ne('Unknown'), 'Weight'].sum()) if snapshot is not None else None,
               'listing_market_unknown_records': int(snapshot['Listing Market Country'].eq('Unknown').sum()) if snapshot is not None else None},
               'signals': signals, 'classifications': metadata, 'risk': risk, 'errors': errors, 'decisions': result, 'benchmark': benchmark,
               'fundamentals': {s: {k: i.get(k) for k in ['sector', 'trailingPE', 'forwardPE', 'revenueGrowth',
                   'profitMargins', 'debtToEquity', 'freeCashflow', 'marketCap', '_warnings', '_news_status']}
                   for s, i in infos.items()}, 'news': headlines, 'retrieved_at': retrieved,
               'http_attempts': provider.session.calls, 'config': cfg}
    frame.to_csv(output / 'portfolio.csv', index=False)
    pd.DataFrame([{'symbol': s, **{k: v for k, v in sig.items() if k != 'folds'}} for s, sig in signals.items()]).to_csv(output / 'screen.csv', index=False)
    (output / 'audit.json').write_text(json.dumps(clean_json(payload), indent=2, default=str, allow_nan=False))
    lines = [f'# Morning portfolio report — {now.date()}', '', f'Generated {now.isoformat()}. Completed exchange sessions only.',
             f"Coverage: {len(histories)}/{len(symbols)} priced; {n} rotating candidates from {len(universe)} mapped WLS listings ({membership_records or len(universe)} source records). Snapshot as of {cfg['universe_verified_as_of'] or 'unverified'}.",
             f'Portfolio decision: **{result["status"]}**.',
             f"Geographic-limit basis: {geographic_label}; benchmark coverage {payload['coverage']['geographic_classified_weight']:.2%}." if snapshot is not None else 'Geographic exposure unavailable.',
             'Initial portfolio trades: USD 0 commission (owner confirmed).' if cfg.get('initial_trade_commission_confirmed') else 'Initial-trade commission is unconfirmed.',
             f"Cash: USD {cfg['cash']:,.2f}. Commission: USD {cfg['commission_usd_per_share']:.3f} per share per trade leg." if cfg['cash'] is not None else 'Cash is unknown.', '']
    lines += [f'- {safe_text(x)}' for x in result['reasons']]
    lines += ['', '| Holding | Signal | Session | Status |', '|---|---|---|---|']
    for row in rows:
        lines.append(f'| {row["Symbol"]} | {row["recommendation"]} | {row.get("price_session", "—")} | {row["data_status"]} |')
    buys = [s for s in subset.Ticker if signals.get(s, {}).get('recommendation') == 'BUY']
    lines += ['', 'Portfolio risk: ' + (f"effective holdings {risk['effective_holdings']:.1f}; " if risk['effective_holdings'] is not None else 'Aggregate risk unavailable until all holdings are valued; ') + f"{len(p)} current holdings versus target 12–15.", '', 'New validated BUY screen: ' + (', '.join(buys[:10]) or 'None cleared the evidence threshold.'),
              '', 'Replacement/cash-funded scenarios: ' + ('See alternatives below and audit.json.' if result['proposals'] else 'None approved by constraints.'),
              '', 'WLS benchmark: ' + (f"portfolio constant-weight return {benchmark['portfolio_constant_current_weight_return']:.2%} versus WLS {benchmark['benchmark_return']:.2%} over {benchmark['sessions']} common sessions." if benchmark['status'] == 'AVAILABLE' else safe_text(benchmark['reason'])), '', '### Current fundamental context and recent headlines',
              'Up to five holdings/candidates shown; all fundamentals and headlines are in audit.json. Snapshot ratios are descriptive, not point-in-time backtest inputs. Headlines require manual relevance and full-text checks; no sentiment score is inferred.']
    for s in list(dict.fromkeys(buys[:3] + [s for s in p.Symbol if signals[s]['recommendation'] != 'HOLD'] + list(p.Symbol)))[:5]:
        i = payload['fundamentals'].get(s, {})
        lines += ['', f'**{s}** — {safe_text(signals.get(s, {}).get("fundamental_context", {}).get("assessment", "Unavailable"))}. P/E {i.get("trailingPE")}; revenue growth {i.get("revenueGrowth")}; margin {i.get("profitMargins")}; debt/equity {i.get("debtToEquity")}; FCF {i.get("freeCashflow")}.']
        news = headlines.get(s, [])
        if not news:
            lines.append('No recent accessible headlines returned (not evidence of no news).')
        for item in news[:2]:
            # Escape markdown link delimiters in untrusted publisher content.
            title = safe_text(item['title']).replace('[', '&#91;').replace(']', '&#93;')
            url = item['url'].replace(')', '%29').replace('(', '%28').replace(' ', '%20')
            lines.append(f'- [{title}]({url}) — {safe_text(item["provider"])}; {item["published"]}')
    lines += ['', f'Data failures: {len(errors)} (see audit.json).',
              'Research only. HOLD includes abstention. Models may fail under regime changes; costs/FX/taxes/liquidity can erase gains. No trades are executed.',
              'Returns use adjusted prices; valuation uses raw closes. Error bands are heuristics, not calibrated confidence intervals.']
    for proposal in result['proposals']:
        lines.append(f"Review alternative: buy {proposal['buy']} at {proposal['weight']:.1%}, funded from {proposal['fund_from']}; net utility gain {proposal['net_utility_gain']:.2%}, uncertainty penalty {proposal['uncertainty_penalty']:.2%}, five-session volatility {proposal['vol_before']:.2%} → {proposal['vol_after']:.2%}.")
    report = '\n'.join(lines) + '\n'
    (output / 'report.md').write_text(report)
    (output / f'report-{now.date()}.md').write_text(report)
    return payload


def fundamental_context(info):
    # Coarse, sector-dependent context only, explicitly separated from OOS models.
    margin, growth, debt = (info.get(k) for k in ['profitMargins', 'revenueGrowth', 'debtToEquity'])
    flags = []
    if margin is not None and margin < 0:
        flags.append('Loss-making on reported margin')
    if growth is not None and growth < 0:
        flags.append('Reported revenue contraction')
    if debt is not None and debt > 200:
        flags.append('Debt/equity above 200%; sector context required')
    positive = margin is not None and growth is not None and margin > 0 and growth > 0
    return {'score': -1 if flags else (1 if positive else 0),
            'assessment': '; '.join(flags) if flags else ('Profitable with positive reported revenue growth' if positive else 'Insufficient/neutral fundamental context'),
            'limit': 'Current vendor snapshot, not a valuation model; banks and other sectors require manual interpretation'}


def clean_json(value):
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, default=Path('daily_monitor/config.json'))
    ap.add_argument('--positions', type=Path, default=Path('daily_monitor/data/positions.csv'))
    ap.add_argument('--universe', type=Path, default=Path(DEFAULT_UNIVERSE))
    ap.add_argument('--output', type=Path, default=Path('daily_monitor/output'))
    ap.add_argument('--cache', type=Path, default=Path('.monitor-cache'))
    ap.add_argument('--max-screen', type=int)
    ap.add_argument('--scheduled', action='store_true')
    args = ap.parse_args()
    cfg = json.loads(args.config.read_text())
    now = pd.Timestamp.now(tz='UTC')
    local = now.tz_convert(cfg['timezone'])
    if args.scheduled and (local.hour != cfg['hour']):
        print('Outside configured local morning hour; skipping duplicate DST schedule')
        return
    if args.max_screen is not None and args.max_screen < 0:
        ap.error('--max-screen must be nonnegative')
    execute(cfg, args.positions, args.universe, args.output, args.cache, now, args.max_screen)


if __name__ == '__main__':
    main()

"""Constrained, same-budget scenarios. No order-routing or execution code."""
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf


def active_limits(names, after, metadata, benchmark, cfg):
    exposures = {}
    for dimension, limit in [('sector', cfg['max_sector_active']), ('industry', cfg['max_industry_active']), ('country', None)]:
        grouped = {}
        for s, w in zip(names, after):
            if w <= 1e-10:
                continue
            category = metadata.get(s, {}).get(dimension, 'Unknown')
            if not category or category == 'Unknown':
                return None
            grouped[category] = grouped.get(category, 0) + w
        b = benchmark[benchmark.dimension == dimension].set_index('category')
        if b.empty:
            return None
        active = {}
        for category in set(grouped) | set(b.index):
            bw = float(b.loc[category, 'weight']) if category in b.index else 0.
            delta = grouped.get(category, 0) - bw
            cap = limit
            if dimension == 'country':
                major = category in b.index and str(b.loc[category, 'major_country']).lower() in ('true', '1', '1.0')
                cap = cfg['major_country_active'] if major else cfg['minor_country_active']
            if abs(delta) > cap + 1e-9:
                return None
            active[category] = delta
        exposures[dimension] = active
    return exposures


def replacement(weights, signals, returns, metadata, cfg, blockers, benchmark=None):
    if blockers:
        return {'status': 'BLOCKED', 'reasons': sorted(set(blockers)), 'proposals': []}
    held = list(weights)
    candidates = [s for s, v in signals.items() if s not in weights and v.get('recommendation') == 'BUY']
    if not candidates:
        return {'status': 'NO CHANGE', 'reasons': ['No validated new BUY candidates'], 'proposals': []}
    proposals = []
    cash_weight = weights.get('__CASH__', 0)
    held = [s for s in held if s != '__CASH__']
    for candidate in candidates:
        for funding in ['__CASH__'] + held:
            allocation = min(signals[candidate].get('suggested_weight', cfg['new_buy_weight']), weights.get(funding, 0), cfg['max_turnover'] / (1 if funding == '__CASH__' else 2))
            if allocation <= 0:
                continue
            names = held + [candidate]
            if any(s not in returns or s not in signals or not signals[s].get('qualified') for s in names):
                continue
            joint = pd.concat({s: returns[s] for s in names}, axis=1).dropna().tail(252)
            if len(joint) < 126:
                continue
            cov = LedoitWolf().fit(joint.to_numpy()).covariance_ * cfg['horizon']
            before = np.array([weights.get(s, 0) for s in names])
            after = before.copy()
            after[-1] += allocation
            if funding != '__CASH__':
                after[names.index(funding)] -= allocation
            if after.max() > cfg['max_position'] + 1e-9:
                continue
            exposure = active_limits(names, after, metadata, benchmark, cfg)
            if exposure is None:
                continue
            mu = np.array([signals[s]['forecast'] for s in names])
            v0, v1 = float(before @ cov @ before), float(after @ cov @ after)
            cost = allocation * cfg['cost_bps_one_way'] / 10000 * (1 if funding == '__CASH__' else 2)
            gain = float((after - before) @ mu) - cost - cfg['risk_aversion'] * (v1 - v0) / 2
            # Penalise candidate forecast error as well as model-estimated risk.
            margin = allocation * (signals[candidate]['error_band'] + (signals[funding]['error_band'] if funding != '__CASH__' else 0))
            if np.sqrt(v1) > np.sqrt(v0) + cfg['max_vol_increase'] or gain - margin < cfg['min_gain']:
                continue
            proposals.append({'buy': candidate, 'fund_from': funding, 'weight': allocation,
                              'net_utility_gain': gain, 'uncertainty_penalty': margin,
                              'transaction_cost_fraction': cost, 'common_sessions': len(joint),
                              'vol_before': np.sqrt(v0), 'vol_after': np.sqrt(v1),
                              'active_exposures_after': exposure,
                              'effective_holdings_after': float(1 / np.sum(after ** 2)),
                              'candidate_minus_30pct_impact': float(-.30 * allocation),
                              'weights_after': dict(zip(names, after)),
                              'cash_weight_after': cash_weight - (allocation if funding == '__CASH__' else 0)})
    proposals.sort(key=lambda p: p['net_utility_gain'] - p['uncertainty_penalty'], reverse=True)
    return {'status': 'REVIEW' if proposals else 'NO CHANGE', 'reasons': ['Scenarios are alternatives; do not combine'],
            'proposals': proposals[:3]}

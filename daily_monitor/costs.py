"""Trading commission expressed as a fraction of USD trade value."""
import math


def one_way_cost_fraction(price_usd, cfg):
    if cfg['base_currency'] != 'USD':
        raise ValueError('USD per-share commission currently requires USD base currency')
    commission = float(cfg['commission_usd_per_share'])
    extra_bps = float(cfg.get('other_cost_bps_one_way', 0))
    if not all(math.isfinite(v) for v in [price_usd, commission, extra_bps]) or price_usd <= 0 or commission < 0 or extra_bps < 0:
        raise ValueError('Price must be positive; commission and extra costs must be finite and nonnegative')
    return commission / price_usd + extra_bps / 10000

"""Yahoo transport, completed-session filtering, and auditable snapshots."""
from __future__ import annotations
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import exchange_calendars as xc
from curl_cffi.requests import Session
import yfinance as yf


class ThrottledSession(Session):
    """Count actual HTTP attempts, including yfinance metadata/auth requests."""
    def __init__(self, sleeper=time.sleep):
        super().__init__(impersonate='chrome')
        self.calls = 0
        self.sleeper = sleeper

    def request(self, *args, **kwargs):
        for attempt in range(3):
            if self.calls and self.calls % 20 == 0:
                self.sleeper(1)
            self.calls += 1
            response = super().request(*args, **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504):
                return response
            if attempt < 2:
                self.sleeper(2 ** (attempt + 1))
        response.raise_for_status()
        return response


def calendar_for(symbol, overrides):
    if symbol in overrides:
        return overrides[symbol]
    mapping = {'.SS': 'XSHG', '.SZ': 'XSHG', '.HK': 'XHKG', '.T': 'XTKS',
               '.NS': 'XBOM', '.BO': 'XBOM', '.L': 'XLON', '.IS': 'XIST',
               '.WA': 'XWAR', '.KW': None,
               '.SW': 'XSWX', '.DE': 'XETR', '.F': 'XFRA', '.PA': 'XPAR',
               '.MI': 'XMIL', '.AS': 'XAMS', '.BR': 'XBRU', '.TO': 'XTSE',
               '.V': 'XTSX', '.AX': 'XASX', '.NZ': 'XNZE', '.KS': 'XKRX',
               '.KQ': 'XKRX', '.SA': 'BVMF', '.MX': 'XMEX', '.TA': 'XTAE',
               '.ST': 'XSTO', '.OL': 'XOSL', '.CO': 'XCSE', '.HE': 'XHEL',
               '.SI': 'XSES', '.JO': 'XJSE', '.JK': 'XIDX', '.KL': 'XKLS',
               '.BK': 'XBKK', '.TW': 'XTAI', '.AT': 'ASEX', '.PR': 'XPRA',
               '.LS': 'XLIS', '.VI': 'XWBO', '.IR': 'XDUB', '.IC': 'XICE'}
    for suffix, name in mapping.items():
        if symbol.endswith(suffix):
            return name
    return 'XNYS' if '.' not in symbol else None


def expected_session(symbol, now, overrides):
    name = calendar_for(symbol, overrides)
    if name is None:
        raise ValueError('Unverified exchange calendar; configure calendar_overrides')
    if isinstance(name, dict):
        # Explicit schedule input supports exchanges absent from exchange-calendars.
        if not name.get('source') or pd.Timestamp(name['valid_through']).date() < now.date():
            raise ValueError('Custom calendar source/coverage expired or unverified')
        schedule = pd.read_csv(name['sessions_csv'])
        dates = pd.to_datetime(schedule.session_date, errors='raise')
        closes = pd.to_datetime(schedule.close_utc, utc=True, errors='raise')
        if dates.duplicated().any() or not dates.is_monotonic_increasing or closes.isna().any():
            raise ValueError('Invalid custom session schedule')
        complete = dates[closes + pd.Timedelta(minutes=30) <= now]
        if complete.empty or (now.date() - complete.iloc[-1].date()).days > 20:
            raise ValueError('Custom calendar has no recent completed session')
        return pd.Timestamp(complete.iloc[-1]).normalize()
    cal = xc.get_calendar(name)
    day = now.tz_convert('UTC').normalize().tz_localize(None)
    sessions = cal.sessions_in_range(day - pd.Timedelta(days=20), day)
    closed = [s for s in sessions if cal.session_close(s) + pd.Timedelta(minutes=30) <= now]
    if not closed:
        raise ValueError('No completed exchange session')
    return pd.Timestamp(closed[-1]).tz_localize(None).normalize()


def completed_prices(history, expected):
    frame = history.copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    frame = frame[~frame.index.duplicated(keep='last')].sort_index()
    frame = frame.loc[frame.index <= expected]
    if frame.empty or frame.index[-1] != expected:
        raise ValueError('Missing latest completed session')
    for col in ['Close', 'Adj Close']:
        if col not in frame or not np.isfinite(frame[col]).all() or (frame[col] <= 0).any():
            raise ValueError('Invalid or missing raw/adjusted prices')
    return frame


class Yahoo:
    def __init__(self, cache, now, overrides):
        self.session = ThrottledSession()
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.now = now
        self.overrides = overrides

    def fetch(self, symbol):
        expected = expected_session(symbol, self.now, self.overrides)
        # A daily cache is reusable only for this exact completed-session cutoff.
        path = self.cache / (symbol.replace('/', '_') + '.json')
        if path.exists():
            saved = json.loads(path.read_text())
            if saved['cutoff'] == str(expected.date()) and saved['retrieved_at'][:10] == self.now.isoformat()[:10]:
                h = pd.DataFrame(saved['history']).set_index('Date')
                h.index = pd.to_datetime(h.index)
                return completed_prices(h, expected), saved['info'], saved['news'], saved['retrieved_at']
        ticker = yf.Ticker(symbol, session=self.session)
        h = ticker.history(period='5y', auto_adjust=False, actions=True, raise_errors=True)
        h = completed_prices(h, expected)
        warnings = []
        try:
            info = ticker.get_info()
        except Exception as exc:
            info = {}
            warnings.append(f'fundamentals unavailable: {type(exc).__name__}')
        try:
            raw_news = ticker.get_news(count=8)
        except Exception as exc:
            raw_news = []
            warnings.append(f'news unavailable: {type(exc).__name__}')
        news = []
        for item in raw_news:
            c = item.get('content', item)
            published = c.get('pubDate')
            when = pd.to_datetime(published, utc=True, errors='coerce')
            if pd.isna(when) or not self.now - pd.Timedelta(days=3) <= when <= self.now:
                continue
            link = c.get('canonicalUrl') or c.get('clickThroughUrl') or {}
            url = link.get('url', '') if isinstance(link, dict) else str(link)
            if not url.startswith('https://'):
                continue
            # Headlines/links only; never scrape linked articles or bypass paywalls.
            news.append({'title': str(c.get('title', ''))[:250], 'url': url,
                         'published': str(when), 'provider': c.get('provider', {}).get('displayName', '')})
        info['_warnings'] = warnings
        info['_news_status'] = 'available' if news else 'no recent accessible headlines'
        serial = h.reset_index(names='Date').copy()
        serial['Date'] = serial['Date'].astype(str)
        saved = {'cutoff': str(expected.date()), 'retrieved_at': self.now.isoformat(),
                 'history': serial.to_dict('records'), 'info': info, 'news': news}
        path.write_text(json.dumps(saved, default=str))
        return h, info, news, saved['retrieved_at']


def positions(path):
    p = pd.read_csv(path, dtype={'Symbol': str})
    p['Symbol'] = p.Symbol.str.strip().str.upper()
    for c in ['Quantity', 'Purchase Price']:
        p[c] = pd.to_numeric(p[c], errors='raise')
        if not np.isfinite(p[c]).all() or (p[c] <= 0).any():
            raise ValueError(f'{c} must be finite and positive')
    if p.Symbol.isna().any() or p.Symbol.eq('').any() or p.Symbol.duplicated().any():
        raise ValueError('Positions require unique, nonempty symbols; consolidate lots explicitly')
    if not p['Transaction Type'].eq('BUY').all():
        raise ValueError('Input is a positions snapshot, not a transaction ledger')
    return p

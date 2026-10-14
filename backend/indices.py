"""Display-only index candles; never mixed into stock snapshots or backtests."""
import json
import math
import threading
import time
from datetime import date, datetime, timezone
from .sources import Feed, cutoff_date
from . import store

INDICES = {
    'sh000001': '上证指数', 'sz399001': '深证成指',
    'sz399006': '创业板指', 'sh000688': '科创50',
    'sh000300': '沪深300', 'sh000905': '中证500',
}
REFRESH_SECONDS = 300
_LOCKS = {symbol: threading.Lock() for symbol in INDICES}
_ATTEMPTS = {}


def index_bars(symbol):
    # Serialize each symbol, including concurrent browser tabs. Keep a separately
    # validated archive so malformed upstream responses cannot replace good data.
    with _LOCKS[symbol]:
        cutoff = cutoff_date()
        key = 'validated-index:' + symbol
        cached = store.cached(key)
        prior = json.loads(cached[0]) if cached else None
        if prior and prior.get('cutoff') == cutoff:
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(cached[1]['fetched'])).total_seconds()
            if age < REFRESH_SECONDS:
                return prior
        attempt = _ATTEMPTS.get(symbol)
        if attempt and attempt[1] == cutoff and time.monotonic()-attempt[0] < REFRESH_SECONDS:
            if prior:
                return dict(prior, cutoff=cutoff, refresh_error=attempt[2])
            raise ValueError(attempt[2] or '指数行情正在等待下一次更新')
        feed = Feed(force=True, budget_seconds=20)
        try:
            rows = sorted((r for r in feed.sina_bars(symbol) if r['date'] <= cutoff), key=lambda r: r['date'])
            seen = set()
            for r in rows:
                date.fromisoformat(r['date'])
                if r['date'] in seen or not all(math.isfinite(r[k]) and r[k] > 0 for k in ('open','high','low','close')) or not r['low'] <= min(r['open'],r['close']) <= max(r['open'],r['close']) <= r['high']:
                    raise ValueError('指数行情包含重复日期或无效 OHLC')
                seen.add(r['date'])
            if not rows:
                raise ValueError('指数行情为空')
            if prior and rows[-1]['date'] < prior['latest']:
                raise ValueError('上游指数行情日期倒退，保留已校验数据')
            url = f'https://finance.sina.com.cn/realstock/company/{symbol}/hisdata/klc_kl.js'
            raw = store.cached(url)
            result = dict(symbol=symbol,name=INDICES[symbol],bars=rows,source='新浪财经',source_url=url,
                          fetched=raw[1]['fetched'] if raw else None,latest=rows[-1]['date'],cutoff=cutoff)
            store.archive(key, store.dumps(result).encode())
            _ATTEMPTS[symbol] = (time.monotonic(), cutoff, None)
            return result
        except Exception as exc:
            message = str(exc)
            _ATTEMPTS[symbol] = (time.monotonic(), cutoff, message)
            if prior:
                return dict(prior, cutoff=cutoff, refresh_error=message)
            raise
        finally:
            feed.close()

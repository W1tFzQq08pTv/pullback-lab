"""Display-only index candles; never mixed into stock snapshots or backtests."""
import math
from datetime import date
from .sources import Feed, cutoff_date
from . import store

INDICES = {
    'sh000001': '上证指数', 'sz399001': '深证成指',
    'sz399006': '创业板指', 'sh000688': '科创50',
    'sh000300': '沪深300', 'sh000905': '中证500',
}

def index_bars(symbol):
    feed = Feed()
    try:
        cutoff = cutoff_date()
        rows = sorted((r for r in feed.sina_bars(symbol) if r['date'] <= cutoff), key=lambda r: r['date'])
        seen = set()
        for r in rows:
            date.fromisoformat(r['date'])
            if r['date'] in seen or not all(math.isfinite(r[k]) and r[k] > 0 for k in ('open','high','low','close')) or not r['low'] <= min(r['open'],r['close']) <= max(r['open'],r['close']) <= r['high']:
                raise ValueError('指数行情包含重复日期或无效 OHLC，暂不展示')
            seen.add(r['date'])
        if not rows:
            raise ValueError('指数行情为空')
        url = f'https://finance.sina.com.cn/realstock/company/{symbol}/hisdata/klc_kl.js'
        cached = store.cached(url)
        return dict(symbol=symbol,name=INDICES[symbol],bars=rows,source='新浪财经',source_url=url,
                    fetched=cached[1]['fetched'] if cached else None,latest=rows[-1]['date'],cutoff=cutoff)
    finally:
        feed.close()

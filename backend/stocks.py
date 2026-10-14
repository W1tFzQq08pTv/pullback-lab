"""Public A-share directory, persisted for offline symbol/name/pinyin search."""
import json
from . import store
from .sources import Feed

DEFAULT='002028.SZ'

def normalize(value):
    value=value.strip().upper()
    if len(value)==6 and value.isdigit():
        value += '.SH' if value.startswith(('5','6')) else '.BJ' if value.startswith(('4','8','9')) else '.SZ'
    return value

def directory(include_etf=True):
    feed=Feed()
    try:
        raw=json.loads(feed.get('https://www.cninfo.com.cn/new/data/szse_stock.json',ttl=604800,offline=True))
        rows=[]
        for r in raw['stockList']:
            code=r['code']
            if r['category']!='A股' or not code.isdigit() or len(code)!=6:continue
            symbol=normalize(code)
            if symbol.endswith('.SZ') and not code.startswith(('00','30')):continue
            rows.append(dict(symbol=symbol,code=code,name=r['zwjc'],pinyin=r.get('pinyin',''),org_id=r['orgId']))
        # CNInfo retains legacy BJ codes: identify issuers, not code suffixes.
        groups={}
        for row in rows:
            row['asset_type']='stock'
            key=row['org_id'] if row['symbol'].endswith('.BJ') else row['symbol']
            if key not in groups or row['code'].startswith('920'):groups[key]=row
        rows=list(groups.values())
        from .instruments import bse_mapping,etf_directory
        try:
            mapping={r['code']:r for r in bse_mapping()}
            for row in rows:
                if row['symbol'].endswith('.BJ') and row['code'] in mapping:
                    m=mapping[row['code']];row.update(listed=m['listed'],aliases=[m['old_code']+'.BJ'],listing_source=m['source'])
        except Exception:
            # Missing official metadata stays explicit during per-symbol validation.
            pass
        if include_etf:
            try:rows.extend(etf_directory())
            except Exception as exc:
                from .logging_setup import log
                log.warning('ETF directory unavailable; stock search remains available: %s',exc)
        return rows
    finally:feed.close()

def get_stock(symbol):
    symbol=normalize(symbol)
    stock=next((r for r in directory() if r['symbol']==symbol or symbol in r.get('aliases',[])),None)
    if stock is None:raise ValueError('未找到该股票或ETF代码，请从搜索结果中选择')
    return stock

def search(query):
    q=query.strip().lower();rows=directory()
    with store.connect() as db:
        cached={r[0] for r in db.execute("SELECT DISTINCT coalesce(json_extract(payload,'$.symbol'),'002028.SZ') FROM snapshots")}
    matches=[r for r in rows if not q or q in r['symbol'].lower() or q in r['name'].lower() or q in r['pinyin'].lower()]
    matches.sort(key=lambda r:(not(q in (r['code'],r['symbol'].lower(),r['name'].lower())),r['symbol'] not in cached,r['symbol']))
    return [{**r,'cached':r['symbol'] in cached} for r in matches[:30]]

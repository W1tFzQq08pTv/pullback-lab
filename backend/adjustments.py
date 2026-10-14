"""Separate quote adjustment from real-price executions and corporate-action cash."""
import json
import math
from bisect import bisect_right
from datetime import date
from . import store
REVISION=1
FIELDS=('open','high','low','close')

def adjusted_bars(rows, factors, basis):
    dates=[r['date'] for r in factors]
    def factor(day):
        i=bisect_right(dates,day)-1
        if i<0:raise ValueError('复权因子未覆盖行情起点')
        return factors[i]['factor']
    base=factor(basis)
    return [{**r,**{k:r[k]*base/factor(r['date']) for k in FIELDS},'adjustment_ratio':base/factor(r['date']),'price_basis':'qfq'} for r in rows if r['date']<=basis]

def collect(feed,payload):
    symbol=payload['symbol'][-2:].lower()+payload['symbol'][:6]
    url=f'https://finance.sina.com.cn/realstock/company/{symbol}/qfq.js'
    raw=feed.get(url,ttl=0 if feed.fresh_market else 21600).decode()
    data=json.JSONDecoder().raw_decode(raw.split('=',1)[1].lstrip())[0]['data']
    factors=[]
    for r in data:
        d=date.fromisoformat(r['d']).isoformat();f=float(r['f'])
        if not math.isfinite(f) or f<=0:raise ValueError('复权因子非法')
        if d<=payload['end']:factors.append(dict(date=d,factor=f))
    factors.sort(key=lambda r:r['date'])
    if not factors or len({r['date'] for r in factors})!=len(factors):raise ValueError('复权因子为空或重复')
    quote=adjusted_bars(payload['bars'],factors,payload['end'])
    # The series is normalized at the snapshot end, never spliced across refreshes.
    return dict(revision=REVISION,status='available',basis=payload['end'],fetched=store.now(),source='sina-qfq-factor',source_url=url,algorithm='raw * factor(basis) / factor(day)',factors=factors,bars=quote)

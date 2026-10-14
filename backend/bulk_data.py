"""Read versioned, original-price TDX daily archives without unpacking the market."""
import hashlib
import json
import re
import struct
import zipfile
from datetime import date
from . import store

FOLDER=store.DATA/'bulk'
URL='https://www.tdx.com.cn/products/data/data/vipdoc/'

def publish(market, temporary):
    # Validate the complete archive before atomically replacing the manifest.
    with zipfile.ZipFile(temporary) as z:
        bad=z.testzip()
        if bad:raise ValueError('ZIP校验失败：'+bad)
        if not any(re.fullmatch(market+r'\d{6}\.day',n) for n in z.namelist()):
            raise ValueError('整包没有对应市场日线')
    with temporary.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    target=FOLDER/(market+'-'+digest+'.zip')
    temporary.replace(target)
    meta=dict(file=target.name,sha256=digest,url=URL+market+'lday.zip',imported=store.now())
    temp=FOLDER/(market+'.json.tmp');temp.write_text(store.dumps(meta));temp.replace(FOLDER/(market+'.json'))
    return meta

def bars(symbol, start, end, *, etf=False):
    market=symbol[:2]
    manifest=FOLDER/(market+'.json')
    if not manifest.exists():return [],None
    meta=json.loads(manifest.read_text())
    with zipfile.ZipFile(FOLDER/meta['file']) as z:
        name=symbol+'.day'
        if name not in z.namelist():return [],meta
        raw=z.read(name)
    if len(raw)%32:raise ValueError('通达信日线记录长度异常')
    scale=1000 if etf else 100
    rows=[];last=''
    for d,o,h,l,c,amount,volume,_ in struct.iter_unpack('<IIIIIfII',raw):
        text=str(d)
        day=date.fromisoformat(text[:4]+'-'+text[4:6]+'-'+text[6:]).isoformat()
        if day<=last:raise ValueError('整包日线重复或日期乱序')
        last=day
        if not start<=day<=end:continue
        values=[v/scale for v in (o,h,l,c)]
        if not 0<values[2]<=min(values[0],values[3])<=max(values[0],values[3])<=values[1]:
            raise ValueError('整包OHLC关系非法：'+day)
        rows.append(dict(date=day,open=values[0],high=values[1],low=values[2],close=values[3],volume=volume,source='tdx-bulk'))
    return rows,meta

def cache_current(payload):
    """A newly imported archive invalidates only the snapshot reuse shortcut."""
    symbol=payload.get('symbol','002028.SZ')
    for code in (symbol[-2:].lower()+symbol[:6],'sh000300'):
        path=FOLDER/(code[:2]+'.json')
        if path.exists():
            try:meta=json.loads(path.read_text())
            except (OSError,ValueError):return False
            if payload.get('bulk_sources',{}).get(code,{}).get('sha256')!=meta['sha256']:return False
    return True

def crosscheck(feed, symbol, rows, manifest, *, etf=False):
    """Once per archive/symbol/window, retain independent historical conflicts."""
    key=f"tdx-check://v1/{manifest['sha256']}/{symbol}/{rows[0]['date']}/{rows[-1]['date']}"
    cached=store.cached(key)
    if cached:
        report=json.loads(cached[0]);feed.evidence[key]=cached[1]['digest']
        return report
    secondary={r['date']:r for r in feed.sina_bars(symbol)}
    overlap=[r for r in rows if r['date'] in secondary]
    if len(overlap)<min(10,len(rows)):raise ValueError('整包与独立行情源重叠不足，无法核验历史价格口径')
    tolerance=.001001 if etf else .010001
    conflicts=[r['date'] for r in overlap if any(abs(r[k]-secondary[r['date']][k])>tolerance for k in ('open','high','low','close'))]
    report=dict(overlap=len(overlap),rows=len(rows),conflicts=conflicts)
    feed.evidence[key]=store.archive(key,store.dumps(report).encode())
    return report

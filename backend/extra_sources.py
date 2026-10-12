"""Unadjusted fallback daily bars. Credentials never enter cache keys or archives."""
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import date,timedelta
from urllib.parse import urlencode
from . import store
from .quality import issue

BAO_SCRIPT = '''
import contextlib,io,json,sys
import baostock as bs
with contextlib.redirect_stdout(io.StringIO()):
 login=bs.login()
 if login.error_code!='0': raise RuntimeError('BaoStock 登录失败')
 try:
  rs=bs.query_history_k_data_plus(sys.argv[1],'date,open,high,low,close,volume',start_date=sys.argv[2],end_date=sys.argv[3],frequency='d',adjustflag='3')
  rows=[]
  while rs.error_code=='0' and rs.next(): rows.append(rs.get_row_data())
  if rs.error_code!='0': raise RuntimeError('BaoStock 查询失败')
 finally: bs.logout()
print(json.dumps(rows))
'''

def fetch(feed, source, symbol, start, end):
    if source in getattr(feed,'unavailable_sources',set()):
        raise RuntimeError(f'{source} 本次任务已连续三次失败，跳过重复连接')
    if source=='eastmoney':
        params=dict(secid=('1' if symbol.startswith('sh') else '0')+'.'+symbol[2:],klt=101,fqt=0,beg=start.replace('-',''),end=end.replace('-',''),fields1='f1,f2,f3,f4,f5,f6',fields2='f51,f52,f53,f54,f55,f56')
        raw=json.loads(feed.get('https://push2his.eastmoney.com/api/qt/stock/kline/get?'+urlencode(params),ttl=0,offline=True))
        if raw.get('rc',0)!=0: raise ValueError('东方财富返回错误状态')
        rows=(raw.get('data') or {}).get('klines',[])
        return [dict(date=r[0],open=float(r[1]),close=float(r[2]),high=float(r[3]),low=float(r[4]),volume=float(r[5])*100,source=source) for r in (x.split(',') for x in rows)]
    key=f'{source}://daily/{symbol}/{start}/{end}/unadjusted'
    # Only unresolved gaps reach this adapter; stale empty responses must not suppress retries.
    blob=None
    for attempt in range(3):
        try:
            if source=='baostock':
                proc=subprocess.run([sys.executable,'-c',BAO_SCRIPT,symbol[:2]+'.'+symbol[2:],start,end],capture_output=True,timeout=20,check=True)
                blob=proc.stdout
                json.loads(blob)
            else:
                token=os.environ.get('TUSHARE_TOKEN','').strip()
                if not token: raise ValueError('未配置 TUSHARE_TOKEN')
                api='index_daily' if symbol=='sh000300' else 'daily'
                response=feed.client.post('https://api.tushare.pro',json=dict(api_name=api,token=token,params=dict(ts_code=symbol[2:]+'.'+symbol[:2].upper(),start_date=start.replace('-',''),end_date=end.replace('-','')),fields='trade_date,open,high,low,close,vol'))
                response.raise_for_status()
                raw=response.json()
                if raw.get('code')!=0: raise ValueError('Tushare 权限不足或接口拒绝请求')
                # Archive only data, never upstream error messages or the token-bearing request.
                blob=store.dumps(raw['data']).encode()
            store.archive(key,blob)
            break
        except Exception:
            if attempt==2:
                feed.unavailable_sources=getattr(feed,'unavailable_sources',set())|{source}
                raise RuntimeError(f'{source} 获取失败（连接、超时或权限问题）') from None
            time.sleep(2**attempt)
    feed.evidence[key]=store.archive(key,blob)
    raw=json.loads(blob)
    if source=='baostock':
        return [dict(date=r[0],**{k:float(v) for k,v in zip(('open','high','low','close','volume'),r[1:])},source=source) for r in raw if all(r)]
    rows=[dict(zip(raw['fields'],r)) for r in raw['items']]
    return [dict(date=r['trade_date'][:4]+'-'+r['trade_date'][4:6]+'-'+r['trade_date'][6:],**{k:float(r[k]) for k in ('open','high','low','close')},volume=float(r['vol'])*100,source=source) for r in rows]

def supplement(feed, symbol, rows, dates):
    """Fetch only years containing gaps, cross-check overlaps, never overwrite conflicts."""
    from .repair import valid
    dates=set(dates)
    if not dates:return rows,[],[]
    code=symbol[2:]+'.'+symbol[:2].upper()
    candidates={};problems=[];reports=[]
    sources=['eastmoney','baostock']+(['tushare'] if os.environ.get('TUSHARE_TOKEN','').strip() else [])
    existing={r['date']:r for r in rows}
    for source in sources:
        collected=[];failures=[]
        for year in sorted({d[:4] for d in dates}):
            window=sorted(d for d in dates if d.startswith(year))
            try:
                lower=max((d for d in existing if d<window[0]),default=(date.fromisoformat(window[0])-timedelta(days=7)).isoformat())
                collected.extend(fetch(feed,source,symbol,lower,window[-1]))
            except Exception as exc:failures.append(str(exc))
        counts=Counter(r['date'] for r in collected)
        for r in collected:
            d=r['date']
            if d not in dates and d not in existing:continue
            if counts[d]!=1 or not valid(r):
                problems.append(issue('backup_invalid',d,f'{source} 日线重复或价格/成交量非法，未采用',code,'warning'));continue
            candidates.setdefault(d,[]).append(r)
        report=dict(source=source,symbol=code,latest=max((r['date'] for r in collected),default=None),rows=len(collected),failures=failures)
        report['cached']=source=='eastmoney' and bool(getattr(feed,'cached_fallbacks',set()))
        reports.append(report)
        if report['cached']:problems.append(issue('backup_cached',max(dates),'东方财富连接失败，复用同一请求已归档的真实响应，按返回日期校验',code,'warning'))
        if failures:problems.append(issue('backup_source',None,f'{source} 补数失败：'+ '; '.join(failures),code,'warning'))
        elif not collected:problems.append(issue('backup_empty',max(dates),f'{source} 尚未返回请求区间日线',code,'warning'))
    for d,options in candidates.items():
        old=existing.get(d)
        comparable=([old] if old and valid(old) else [])+options
        if any(abs(r[k]-comparable[0][k])>.010001 for r in comparable[1:] for k in ('open','high','low','close')):
            problems.append(issue('source_conflict',d,'补数来源原始 OHLC 差异超过0.01元，未采用：'+','.join(r['source'] for r in comparable),code));continue
        if d in dates and (old is None or (not valid(old) and old.get('volume')==0)):
            existing[d]=options[0]
    # Retain duplicate original rows so quality validation still blocks them.
    counts=Counter(r['date'] for r in rows)
    merged=[r for r in rows if counts[r['date']]>1]+[r for d,r in existing.items() if counts[d]<=1]
    return sorted(merged,key=lambda r:r['date']),problems,reports

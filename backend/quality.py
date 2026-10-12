import math
from collections import Counter

def issue(code, date, message, symbol='002028.SZ', severity='error'):
    return dict(code=code, date=date, message=message, symbol=symbol, severity=severity)

def validate(payload):
    problems = list(payload.get('source_issues', []))
    cal = set(payload['calendar'])
    events = {e['date']: e for e in payload['actions']}
    for key, symbol in [('bars',payload.get('symbol','002028.SZ')), ('index','000300.SH')]:
        rows = payload[key]
        counts = Counter(r['date'] for r in rows)
        for d,n in counts.items():
            if n > 1: problems.append(issue('duplicate',d,f'重复日线 {n} 条',symbol))
        mapping = {r['date']:r for r in rows}
        for d in sorted(cal):
            if key=='bars' and d<payload.get('listed',payload['start']):continue
            if d not in mapping and not (key=='bars' and d in payload.get('suspensions', [])):
                problems.append(issue('missing',d,'交易日缺少行情，尚无停牌证据',symbol))
        prev = None
        for r in sorted(rows,key=lambda r:r['date']):
            d=r['date']
            values=[r.get(k) for k in ('open','high','low','close','volume')]
            if any(v is None or not math.isfinite(v) for v in values):
                problems.append(issue('null',d,'行情包含空值或非有限数',symbol)); continue
            if min(values[:4]) <= 0 or r['volume'] < 0 or not r['low'] <= min(r['open'],r['close']) <= max(r['open'],r['close']) <= r['high']:
                problems.append(issue('ohlc',d,'价格、成交量或 OHLC 关系非法',symbol))
            if key=='bars' and r['volume']==0 and d not in payload.get('suspensions', []):
                problems.append(issue('zero_volume',d,'零成交量日线需核实停牌，不能认定为有效交易日',symbol))
            if d not in cal:
                problems.append(issue('calendar',d,'行情日期不在交易日历内',symbol))
            if prev and key=='bars':
                e=events.get(d,{})
                reference=(prev['close']-e.get('reference_cash',e.get('cash',0)))/(1+e.get('bonus',0)+e.get('transfer',0))
                if abs(r['close']/reference-1) > .105:
                    problems.append(issue('price_jump',d,'超过主板通常涨跌幅，需核实公司行动或行情',symbol))
            prev=r
    for e in payload['actions']:
        if not e.get('verified'):
            problems.append(issue('action_unverified',e['date'],e.get('review_reason','公司行动未完成实施公告核验')))
        elif not (e.get('announcement',e['record']) <= e['record'] < e['date'] <= e['pay']):
            problems.append(issue('action_dates',e['date'],'公司行动日期顺序异常'))
        elif (e.get('bonus',0) or e.get('transfer',0)) and not (e.get('credit_date') and e.get('share_date') and e['date'] <= e['credit_date'] <= e['share_date']):
            problems.append(issue('share_dates',e['date'],'送转到账或可交易日期不完整'))
    for problem in problems:
        if problem['symbol']=='002028.SZ':problem['symbol']=payload.get('symbol','002028.SZ')
    return problems

def eligible(payload, p):
    start,end=str(p.start),str(p.end)
    symbol=payload.get('symbol','002028.SZ')
    if p.symbol!=symbol:return [issue('symbol',None,'标的与快照不一致，请重新选择数据',p.symbol)]
    required=max(250,p.slow+p.slope,p.middle+p.slope+p.pullback)
    before=[r for r in payload['bars'] if r['date']<start and r['volume']>0]
    lower=before[-required]['date'] if len(before)>=required else payload['start']
    problems=[i for i in payload['quality'] if i['severity']=='error' and (i['date'] is None or lower<=i['date']<=end) and (p.market_filter or i['symbol']!='000300.SH')]
    if symbol != '002028.SZ':
        stock=payload.get('stock',{})
        if not symbol.startswith(('000','001','002','003','600','601','603','605')) or 'ST' in stock.get('name','').upper() or '退' in stock.get('name',''):
            problems.append(issue('trading_rules',None,'该标的的板块或风险警示交易规则尚未支持；行情可缓存查看，正式回测已阻止',symbol))
    if len(before)<required:
        problems.append(issue('warmup',start,f'预热需要{required}根有效日线，实际{len(before)}根'))
    if start<payload['start'] or end>payload['end']:
        problems.append(issue('range',end,'请求日期超出已保存且收盘的覆盖区间'))
    if not any(start<=r['date']<=end for r in payload['bars']):
        problems.append(issue('empty',start,'区间内没有行情'))
    for problem in problems:
        if problem['symbol']=='002028.SZ':problem['symbol']=payload.get('symbol','002028.SZ')
    return problems

from .logging_setup import log
"""Finite exhaustive grids, cached equivalent signals, exact existing-account evaluation.
Run: python -m backend.optimize --workers 4
Outputs are local research artifacts; this command does not apply defaults.
"""
import argparse
import hashlib
import itertools
import json
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
import numpy as np
from . import store
from .models import Parameters
from .quality import validate,eligible
from .fallback import prepare,slice_payload
from .engine import Book,indicators,VERSION,money
from .strategies import MartinBook,martin_indicators,multi_backtest

SMA_GRID=dict(fast=[5,10,15,20,30,40,60],middle=[20,30,40,50,60,90,120],slow=[80,100,150,200],slope=[1,5,10,20],pullback=[1,3,5,10,20],market_filter=[False,True])
MARTIN_GRID=dict(martin_risk=[.001,.0025,.005,.01,.02,.05],martin_max_stop=[.01,.015,.02,.025,.03,.05,.1],martin_min_return=[0,.1,.2,.3,.5,1],martin_min_turnover=[0,5000000,10000000,20000000,50000000],martin_support_tolerance=[0,.005,.01,.015,.025,.05],martin_anchor_window=[21,42,63,84,126])

def product(grid):
    return (dict(zip(grid,values)) for values in itertools.product(*grid.values()))

def sma_features(payload):
    periods=sorted(set(SMA_GRID['fast']+SMA_GRID['middle']+SMA_GRID['slow']))
    mas={n:[] for n in periods};slopes={(m,s):[] for m in SMA_GRID['middle'] for s in SMA_GRID['slope']}
    close=[];low=[];prev=[];dates=[];history=[]
    actions={a['date']:a for a in payload['actions'] if a.get('verified')}
    for row in payload['bars']:
        a=actions.get(row['date'])
        if a:
            cash=a.get('reference_cash',a.get('cash',0));factor=a.get('reference_factor',1+a.get('bonus',0)+a.get('transfer',0))
            for h in history:
                for k in ('close','low','high'):h[k]=(h[k]-cash)/factor
        if row['volume']<=0:continue
        previous=history[-1]['high'] if history else np.nan
        history.append(dict(row));n=len(history)
        # Prefix accumulation matches original arithmetic to floating-point precision;
        # each cached average uses the original sum order for boundary parity.
        for period in periods:mas[period].append(sum(h['close'] for h in history[-period:])/period if n>=period else np.nan)
        for (period,offset),values in slopes.items():
            end=n-offset;values.append(sum(h['close'] for h in history[end-period:end])/period if end>=period else np.nan)
        dates.append(row['date']);close.append(row['close']);low.append(row['low']);prev.append(previous)
    market={}
    index={r['date']:r['close'] for r in payload['index']};ih=[]
    for d in payload['calendar']:
        if d in index:
            ih.append(index[d]);market[d]={n:len(ih)>=n and ih[-1]>sum(ih[-n:])/n for n in SMA_GRID['slow']}
    return dates,np.array(close),np.array(low),np.array(prev),{k:np.array(v) for k,v in mas.items()},{k:np.array(v) for k,v in slopes.items()},market

class SearchValuation:
    """Only search metrics need daily equity/shares; retain full final valuation.

    Trading, corporate actions, tax settlement and rounding use the real Book.
    Potential liquidation tax is informational, not deducted from equity.
    """
    def valuation(self,d,price):
        if d==self.valuation_end:return super().valuation(d,price)
        shares=self.shares
        receivable=sum(e['gross'] for e in self.entitlements if e['recognized'] and not e['paid'])
        pending=sum(e['new_shares'] for e in self.entitlements if e['recognized'] and not e.get('credited'))
        return dict(date=d,equity=money(self.cash+(shares+pending)*price+receivable),shares=shares)

class SearchBook(SearchValuation,Book):pass
class SearchMartinBook(SearchValuation,MartinBook):pass

_CONTEXT=None

def init_worker(data,params):
    global _CONTEXT
    p=Parameters(**params);dates=[d for d in data['calendar'] if str(p.start)<=d<=str(p.end)]
    bars={r['date']:r for r in data['bars']};actions={a['date']:a for a in data['actions'] if a.get('verified')}
    recorded={}
    for a in actions.values():recorded.setdefault(a['record'],[]).append(a)
    price=next(r['close'] for r in reversed(data['bars']) if r['date']<dates[0]);steps=[]
    signal_indices={r['date']:i for i,r in enumerate(r for r in data['bars'] if r['volume']>0)}
    for d in dates:
        r=bars.get(d);a=actions.get(d,{})
        reference=(price-a.get('reference_cash',a.get('cash',0)))/(a.get('reference_factor',1+a.get('bonus',0)+a.get('transfer',0)))
        price=r['close'] if r else reference
        steps.append((d,r,a,reference,price,recorded.get(d,[]),signal_indices.get(d)))
    _CONTEXT=(p,steps,len(signal_indices))

def evaluate(job):
    ident,strategy,fields,buybits,sellbits=job
    p,steps,n=_CONTEXT;p=p.model_copy(update=fields)
    buy=np.unpackbits(np.frombuffer(buybits,dtype=np.uint8),count=n);sell=np.unpackbits(np.frombuffer(sellbits,dtype=np.uint8),count=n)
    martin=strategy=='martin_daily';b=SearchMartinBook(p) if martin else SearchBook(p)
    b.valuation_end=steps[-1][0]
    for d,r,a,reference,price,record,i in steps:
        if martin:b.adjust(a)
        b.process_actions(d);b.execute(d,r,reference)
        if record:b.register(d,record)
        b.curve.append(b.valuation(d,price))
        if i is not None:
            if martin:b.schedule(dict(close=price,stop=r['low'],buy=bool(buy[i]),sell=bool(sell[i])))
            elif b.shares and sell[i]:b.pending='sell'
            elif not b.shares and buy[i]:b.pending='buy'
    return ident,b.metrics()

def search_gate(p):
    # Common warmup covers both exhaustive grids, independent of saved winners.
    return p.model_copy(update={'strategies':['trend_pullback','martin_daily'],
        'fast':20,'middle':max(SMA_GRID['middle']),'slow':max(SMA_GRID['slow']),
        'slope':max(SMA_GRID['slope']),'pullback':max(SMA_GRID['pullback']),
        'martin_anchor_window':max(MARTIN_GRID['martin_anchor_window']),'market_filter':True})

def run(symbol,workers,output,params=None,progress=lambda n,m:None):
    started=time.perf_counter();s=store.latest(params.snapshot_id if params else None,symbol=symbol)
    if not s:raise ValueError('股票没有本地快照')
    p=params or Parameters(symbol=symbol,time_range='all',snapshot_id=s['id'],strategies=['trend_pullback','martin_daily'])
    if p.martin_pool_id:raise ValueError('个股寻优仅支持单股条件，请先取消股票池横向排名')
    p=p.model_copy(update={'snapshot_id':s['id'],'strategies':['trend_pullback','martin_daily'],'fast':20,'middle':50,'slow':200,'slope':10,'pullback':5,'market_filter':True})
    progress(2,'校验数据并缓存指标')
    data,gate,fallback,problems=prepare({**s['payload'],'quality':validate(s['payload'])},search_gate(p))
    p=p.model_copy(update={'start':gate.start,'end':gate.end,'data_after':gate.data_after})
    if problems:raise ValueError(str(problems))
    # Freeze a common range, data version and warmup for every candidate.
    p=p.model_copy(update={'time_range':'custom'})
    for q in (p.model_copy(update={'slow':200,'slope':20,'middle':120,'pullback':20}),):
        if eligible(data,q):raise ValueError('搜索网格预热不足，不能改变候选区间')
    output.mkdir(parents=True,exist_ok=True)
    dates,close,low,prev,mas,slopes,market=sma_features(data)
    candidates=[];groups={};jobs=[]
    def add(strategy,fields,buy,sell):
        buybits=np.packbits(buy).tobytes();sellbits=np.packbits(sell).tobytes()
        key=(strategy,buybits,sellbits,fields.get('martin_risk'),fields.get('martin_max_stop'))
        if key not in groups:
            ident=len(jobs);groups[key]=ident;jobs.append((ident,strategy,fields,buybits,sellbits))
        candidates.append(dict(strategy=strategy,params=fields,group=groups[key]))
    pull_cache={}
    for fields in product(SMA_GRID):
        f,m,l,sl,pb=(fields[k] for k in ('fast','middle','slow','slope','pullback'))
        if not f<m<l:continue
        key=(f,m,pb)
        if key not in pull_cache:
            touches=(low<=mas[f])&(close>mas[m]);pull=np.zeros(len(close),dtype=bool)
            for j in range(pb):
                if j:pull[j:]|=touches[:-j]
                else:pull|=touches
            pull_cache[key]=pull
        buy=(close>mas[l])&(mas[m]>slopes[m,sl])&pull_cache[key]&(close>prev)&(close>mas[f])
        if fields['market_filter']:buy&=np.array([market.get(d,{}).get(l,False) for d in dates])
        add('trend_pullback',fields,buy,close<mas[m])
    martin_cache={}
    for window in MARTIN_GRID['martin_anchor_window']:
        sig=martin_indicators(data,p.model_copy(update={'martin_anchor_window':window}),explain=True,features=True)
        rows=[sig[d] for d in dates]
        martin_cache[window]=dict(base=np.array([r['conditions']['warmup'] and r['conditions']['trend'] and r['conditions']['rebound'] for r in rows]),
            strength=np.array([max(r['returns'].values(),default=-np.inf) for r in rows]),
            turnover=np.array([r['features']['turnover'] for r in rows]),
            support=np.array([r['features']['support'] if r['features']['support'] is not None else np.inf for r in rows]),
            risk=np.array([(r['close']-r['stop'])/r['close'] for r in rows]),sell=np.array([r['sell'] for r in rows]))
    for fields in product(MARTIN_GRID):
        a=martin_cache[fields['martin_anchor_window']]
        buy=a['base']&(a['strength']>=fields['martin_min_return'])&(a['turnover']>=fields['martin_min_turnover'])&(a['support']<=fields['martin_support_tolerance'])&(a['risk']>0)&(a['risk']<=fields['martin_max_stop'])
        add('martin_daily',fields,buy,a['sell'])
    log.info('optimization prepared symbol=%s candidates=%s accounts=%s workers=%s',symbol,len(candidates),len(jobs),workers)
    # Validate cached masks against the real indicator path before spending search time.
    sample=[jobs[i] for i in sorted(set([0,len(jobs)//4,len(jobs)//2,len(jobs)-1]))]
    sample += [next(j for j in jobs if j[1]=='martin_daily')]
    for _,strategy,fields,buybits,sellbits in sample:
        q=p.model_copy(update=fields)
        sig=(indicators if strategy=='trend_pullback' else martin_indicators)(data,q)
        assert np.array_equal(np.unpackbits(np.frombuffer(buybits,dtype=np.uint8),count=len(dates)),[sig[d]['buy'] for d in dates]),('buy-mask',fields)
        assert np.array_equal(np.unpackbits(np.frombuffer(sellbits,dtype=np.uint8),count=len(dates)),[sig[d]['sell'] for d in dates]),('sell-mask',fields)
    scores={}
    with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,initargs=(data,p.model_dump(mode='json'))) as executor:
        for completed,(ident,metrics) in enumerate(executor.map(evaluate,jobs,chunksize=32),1):
            scores[ident]=metrics
            if completed%250==0 or completed==len(jobs):progress(10+int(80*completed/len(jobs)),f'参数回测 {completed:,} / {len(jobs):,}（{len(candidates):,} 组参数已合并重复方案）')
    leaders={}
    with (output/'candidates.jsonl').open('w') as f:
        for row in candidates:
            row['metrics']=scores[row['group']];f.write(store.dumps(row)+'\n')
    for strategy in ('trend_pullback','martin_daily'):
        ranked=sorted((r for r in candidates if r['strategy']==strategy),key=lambda r:(-r['metrics']['total_return'],-r['metrics']['max_drawdown'],r['metrics']['trade_count'],store.dumps(r['params'])))
        leaders[strategy]=ranked[:20]
    progress(93,'使用原回测引擎复核优胜参数')
    baseline=multi_backtest(s['payload'],p)
    verification={}
    for strategy,rows in leaders.items():
        winner=rows[0];q=p.model_copy(update={**winner['params'],'strategies':[strategy]})
        real=multi_backtest(s['payload'],q)['variants'][strategy]['book']
        assert real['metrics']==winner['metrics'],('winner-parity',strategy)
        verification[strategy]=dict(params=q.model_dump(mode='json'),metrics=real['metrics'])
        (output/(strategy+'-winner.json')).write_text(store.dumps(real))
    report=dict(symbol=symbol,snapshot_id=s['id'],engine=VERSION,objective='total_return',range=dict(start=str(p.start),end=str(p.end)),fallback=fallback,
        base_params=p.model_dump(mode='json'),grids=dict(trend_pullback=SMA_GRID,martin_daily=MARTIN_GRID),candidates=len(candidates),unique_accounts=len(jobs),
        counts={s:sum(r['strategy']==s for r in candidates) for s in leaders},leaders=leaders,verified=verification,
        baseline={k:v['book']['metrics'] for k,v in baseline['variants'].items()},seconds=round(time.perf_counter()-started,2),
        note='有限离散网格全覆盖；单股、固定快照、固定区间样本内累计收益排序，同收益按较小回撤、较少成交数排序。不是所有连续参数的全局最优，也不是样本外验证。资金、仓位上限、费用和交易约束固定，Martin的EMA与3R/5R规则固定。')
    report['checksum']=hashlib.sha256(store.dumps(report).encode()).hexdigest()
    (output/'report.json').write_text(store.dumps(report));log.info('optimization verified symbol=%s seconds=%s',symbol,report['seconds'])

    return report

if __name__=='__main__':
    from .logging_setup import configure
    configure()
    parser=argparse.ArgumentParser();parser.add_argument('--symbol',default='601138.SH');parser.add_argument('--workers',type=int,default=4);parser.add_argument('--output',default='data/optimizations/601138-grid-v1');a=parser.parse_args()
    run(a.symbol,max(1,min(a.workers,4)),Path(a.output))

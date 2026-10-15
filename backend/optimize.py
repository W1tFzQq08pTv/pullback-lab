from .logging_setup import log
"""Finite exhaustive grids, cached equivalent signals, exact existing-account evaluation.
Run: python -m backend.optimize --workers 4
Outputs are local research artifacts; this command does not apply defaults.
"""
import argparse
import bisect
from functools import lru_cache
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
from .quality import eligible
from .search_plan import plan_search
from .engine import Book,indicators,VERSION,money
from .strategies import MartinBook,martin_indicators,multi_backtest
from .position import PositionBook,POSITION_GRID,saved_fields

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
class SearchPositionBook(SearchValuation,PositionBook):pass
class SearchMartinBook(SearchValuation,MartinBook):pass

_CONTEXT=None
_EVENT_CONTEXT=None

def init_worker(data,params):
    global _CONTEXT,_EVENT_CONTEXT
    event_signals.cache_clear()
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
    deadlines=set()
    for a in actions.values():
        for key in ('record','date','pay','credit_date','share_date'):
            if a.get(key):
                ix=bisect.bisect_left(dates,a[key])
                if ix<len(dates):deadlines.add(ix)
    _EVENT_CONTEXT=(sorted(deadlines),np.array([x[4] for x in steps]),np.array([x[6] is not None for x in steps]))

def evaluate_reference(job,audit=False):
    ident,strategy,fields,buybits,sellbits=job
    p,steps,n=_CONTEXT;p=p.model_copy(update=fields)
    buy=np.unpackbits(np.frombuffer(buybits,dtype=np.uint8),count=n);sell=np.unpackbits(np.frombuffer(sellbits,dtype=np.uint8),count=n)
    martin=strategy=='martin_daily';b=SearchMartinBook(p) if martin else SearchPositionBook(p) if strategy=='trend_pullback_v2' else SearchBook(p)
    b.valuation_end=steps[-1][0]
    for d,r,a,reference,price,record,i in steps:
        if martin or strategy=='trend_pullback_v2':b.adjust(a)
        b.process_actions(d);b.execute(d,r,reference)
        if record:b.register(d,record)
        b.curve.append(b.valuation(d,price))
        if i is not None:
            if martin or strategy=='trend_pullback_v2':b.schedule(dict(close=price,stop=r['low'],buy=bool(buy[i]),sell=bool(sell[i])))
            elif b.shares and sell[i]:b.pending='sell'
            elif not b.shares and buy[i]:b.pending='buy'
    return b.result() if audit else (ident,fields,b.metrics())

@lru_cache(maxsize=128)
def event_signals(buybits,sellbits):
    _,steps,n=_CONTEXT
    buy=np.unpackbits(np.frombuffer(buybits,dtype=np.uint8),count=n)
    sell=np.unpackbits(np.frombuffer(sellbits,dtype=np.uint8),count=n)
    return (buy,sell,
            [j for j,x in enumerate(steps) if x[6] is not None and buy[x[6]]],
            [j for j,x in enumerate(steps) if x[6] is not None and sell[x[6]]])


def evaluate(job,audit=False):
    """Event-driven execution; daily valuation still uses the exact money rule.

    Nothing is skipped across a buy/sell signal, pending order, corporate-action
    deadline or v2 add-on threshold. Martin keeps its reference daily scheduler.
    """
    ident,strategy,fields,buybits,sellbits=job
    if strategy=='martin_daily':return evaluate_reference(job,audit)
    p,steps,n=_CONTEXT;p=p.model_copy(update=fields)
    deadlines,prices,valid=_EVENT_CONTEXT
    buy,sell,buy_days,sell_days=event_signals(buybits,sellbits)
    v2=strategy=='trend_pullback_v2'
    b=SearchPositionBook(p) if v2 else SearchBook(p)
    end=len(steps);b.valuation_end=steps[-1][0]
    def following(days,day):
        at=bisect.bisect_right(days,day)
        return days[at] if at<len(days) else end
    day=0;equities=[];exposure=0
    while day<end:
        d,r,a,reference,price,record,i=steps[day]
        if v2:b.adjust(a)
        b.process_actions(d)
        if b.pending:b.execute(d,r,reference)
        if record:b.register(d,record)
        shares=b.shares
        if i is not None:
            if v2:b.schedule(dict(close=price,buy=bool(buy[i]),sell=bool(sell[i])))
            elif shares and sell[i]:b.pending='sell'
            elif not shares and buy[i]:b.pending='buy'
        until=following(deadlines,day)
        if b.pending:until=min(until,day+1)
        elif shares:
            until=min(until,following(sell_days,day))
            if v2 and p.v2_mode!='fixed' and b.batch<p.v2_batches:
                threshold=b.first_price*(1+(1 if p.v2_mode=='up' else -1)*b.batch*p.v2_step)
                part=prices[day+1:until]
                crossed=(part>=threshold) if p.v2_mode=='up' else (part<=threshold)
                hits=np.flatnonzero(crossed & valid[day+1:until])
                if len(hits):until=day+1+int(hits[0])
        else:until=min(until,following(buy_days,day))
        receivable=sum(e['gross'] for e in b.entitlements if e['recognized'] and not e['paid'])
        pending=sum(e['new_shares'] for e in b.entitlements if e['recognized'] and not e.get('credited'))
        cash=b.cash;marked=shares+pending
        # Preserve Python's operation order and Decimal(str(...)) HALF_UP, even
        # for suspended days whose reference price has fractional cents.
        values=([money(cash+marked*x[4]+receivable) for x in steps[day:until]] if marked else [money(cash+receivable)]*(until-day))
        equities.extend(values)
        if shares:exposure+=until-day
        if audit:b.curve.extend(dict(date=x[0],equity=value,shares=shares) for x,value in zip(steps[day:until],values))
        day=until
    ending=b.valuation(steps[-1][0],steps[-1][4])
    if audit:
        b.curve[-1]=ending
        return b.result()
    peaks=np.maximum.accumulate(np.array([p.capital,*equities]))[1:]
    drawdowns=np.array(equities)/peaks-1
    ending['drawdown']=float(drawdowns[-1])
    years=max((p.end-p.start).days/365.25,1/365.25)
    metrics=dict(total_return=equities[-1]/p.capital-1,annual_return=(equities[-1]/p.capital)**(1/years)-1,
                 max_drawdown=float(np.min(drawdowns)),trade_count=len(b.trades),closed_trades=len(b.cycles),
                 win_rate=sum(x>0 for x in b.cycles)/len(b.cycles) if b.cycles else None,
                 exposure=exposure/end,fees=money(b.total_fees),dividend_tax=money(b.tax),ending=ending)
    return ident,fields,metrics


def search_plan(payload,p):
    return plan_search(payload,p,SMA_GRID,MARTIN_GRID,product)


def checkpoint_contract(p,snapshot_id):
    names=('optimize.py','position.py','engine.py','models.py','strategies.py','quality.py','fallback.py','search_plan.py','trading_rules.py')
    return dict(schema=1,snapshot_id=snapshot_id,params=p.model_dump(mode='json'),
                grids=dict(sma=SMA_GRID,martin=MARTIN_GRID,positions=POSITION_GRID),
                sources={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names})


def find_checkpoint(output,contract):
    matches=[]
    for folder in output.parent.iterdir():
        if folder==output or not folder.is_dir():continue
        manifest=folder/'checkpoint.json';rows=folder/'candidates.jsonl'
        if not manifest.exists() or not rows.exists():continue
        try:
            if json.loads(manifest.read_text()).get('contract')==contract:matches.append(rows)
        except (OSError,ValueError):continue
    return max(matches,key=lambda f:f.stat().st_size,default=None)


def run(symbol,workers,output,params=None,progress=lambda n,m:None):
    started=time.perf_counter();s=store.latest(params.snapshot_id if params else None,symbol=symbol)
    if not s:raise ValueError('股票没有本地快照')
    p=params or Parameters(symbol=symbol,time_range='all',snapshot_id=s['id'],strategies=['trend_pullback','martin_daily'])
    if p.martin_pool_id:raise ValueError('个股寻优仅支持单股条件，请先取消股票池横向排名')
    p=p.model_copy(update={'snapshot_id':s['id']})
    progress(2,'校验数据并缓存指标')
    data,gate,fallback,problems,search_candidates,adaptation=search_plan(s['payload'],p)
    p=gate
    if problems:raise ValueError(str(problems))
    # Freeze a common range, data version and warmup for every candidate.
    p=p.model_copy(update={'time_range':'custom'})
    if eligible(data,p):raise ValueError('搜索网格预热不足，不能改变候选区间')
    progress(4,adaptation['note'])
    output.mkdir(parents=True,exist_ok=True)
    contract=checkpoint_contract(p,s['id'])
    resume=find_checkpoint(output,contract)
    (output/'checkpoint.json').write_text(store.dumps(dict(contract=contract)))
    dates,close,low,prev,mas,slopes,market=sma_features(data)
    candidates=[];groups={};jobs=[]
    def add(strategy,fields,buy,sell):
        buybits=np.packbits(buy).tobytes();sellbits=np.packbits(sell).tobytes()
        key=(strategy,buybits,sellbits,fields.get('martin_risk'),fields.get('martin_max_stop'))
        if key not in groups:
            ident=len(jobs);groups[key]=ident;jobs.append((ident,strategy,fields,buybits,sellbits))
        candidates.append(dict(strategy=strategy,params=fields,group=groups[key]))
    pull_cache={}
    for fields in search_candidates.get('trend_pullback',search_candidates.get('trend_pullback_v2',[])):
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
        for strategy in ('trend_pullback','trend_pullback_v2'):
            if strategy in search_candidates:add(strategy,fields,buy,close<mas[m])
    martin_cache={}
    for window in sorted({fields['martin_anchor_window'] for fields in search_candidates.get('martin_daily',[])}):
        sig=martin_indicators(data,p.model_copy(update={'martin_anchor_window':window}),explain=True,features=True)
        rows=[sig[d] for d in dates]
        martin_cache[window]=dict(base=np.array([r['conditions']['warmup'] and r['conditions']['trend'] and r['conditions']['rebound'] for r in rows]),
            strength=np.array([max(r['returns'].values(),default=-np.inf) for r in rows]),
            turnover=np.array([r['features']['turnover'] for r in rows]),
            support=np.array([r['features']['support'] if r['features']['support'] is not None else np.inf for r in rows]),
            risk=np.array([(r['close']-r['stop'])/r['close'] for r in rows]),sell=np.array([r['sell'] for r in rows]))
    for fields in search_candidates.get('martin_daily',[]):
        a=martin_cache[fields['martin_anchor_window']]
        buy=a['base']&(a['strength']>=fields['martin_min_return'])&(a['turnover']>=fields['martin_min_turnover'])&(a['support']<=fields['martin_support_tolerance'])&(a['risk']>0)&(a['risk']<=fields['martin_max_stop'])
        add('martin_daily',fields,buy,a['sell'])
    log.info('optimization prepared symbol=%s candidates=%s accounts=%s workers=%s',symbol,len(candidates),len(jobs),workers)
    # Validate cached masks against the real indicator path before spending search time.
    sample=[jobs[i] for i in sorted(set([0,len(jobs)//4,len(jobs)//2,len(jobs)-1]))]
    sample += [next(j for j in jobs if j[1]==strategy) for strategy in search_candidates]
    for _,strategy,fields,buybits,sellbits in sample:
        q=p.model_copy(update=fields)
        sig=(martin_indicators if strategy=='martin_daily' else indicators)(data,q)
        assert np.array_equal(np.unpackbits(np.frombuffer(buybits,dtype=np.uint8),count=len(dates)),[sig[d]['buy'] for d in dates]),('buy-mask',fields)
        assert np.array_equal(np.unpackbits(np.frombuffer(sellbits,dtype=np.uint8),count=len(dates)),[sig[d]['sell'] for d in dates]),('sell-mask',fields)
    # Keep only signal equivalence groups in memory. Position combinations and
    # candidate rows are generated in bounded batches, never materialized globally.
    grouped={j[0]:[] for j in jobs}
    for row in candidates:grouped[row['group']].append(row['params'])
    total=sum(len(POSITION_GRID) if j[1]=='trend_pullback_v2' else 1 for j in jobs)
    counts={k:len(v)*(len(POSITION_GRID) if k=='trend_pullback_v2' else 1) for k,v in search_candidates.items()}
    count=sum(counts.values())
    progress(5,f'完整网格 {count:,} 组；等价合并后 {total:,} 个账户，开始小规模计时')
    def expanded():
        for ident,strategy,fields,buybits,sellbits in jobs:
            for position in (POSITION_GRID if strategy=='trend_pullback_v2' else [{}]):
                yield ident,strategy,{**fields,**position},buybits,sellbits
    def rank(row):
        m=row['metrics']
        return (-m['total_return'],-m['max_drawdown'],m['trade_count'],store.dumps(row['params']))
    leaders={k:[] for k in search_candidates};mode_leaders={k:[] for k in ('fixed','up','down')} if 'trend_pullback_v2' in search_candidates else {}
    def retain(rows,row):
        if len(rows)==20 and rank(row)>=rank(rows[-1]):return
        bisect.insort_right(rows,row,key=rank);del rows[20:]
    stream=expanded();completed=0;reused=0;benchmark_seconds=None
    with (output/'candidates.jsonl').open('w') as f:
        def consume(ident,fields,metrics):
            nonlocal completed
            strategy=jobs[ident][1]
            position={k:v for k,v in fields.items() if k.startswith('v2_')}
            for base in grouped[ident]:
                row=dict(strategy=strategy,params={**base,**position},group=ident,metrics=metrics)
                f.write(store.dumps(row)+'\n')
                retain(leaders[strategy],row)
                if strategy=='trend_pullback_v2':retain(mode_leaders[fields['v2_mode']],row)
            completed+=1
        if resume:
            progress(6,'发现同快照、同网格与同版本检查点，复用已完成账户')
            with resume.open() as previous:
                def read_row():
                    line=previous.readline()
                    if not line:return None
                    try:return json.loads(line)
                    except ValueError:
                        if previous.readline():raise ValueError('检查点中段损坏，拒绝复用')
                        return None  # A process can stop midway through its final line.
                for job in stream:
                    ident,strategy,fields,_,_=job
                    position={k:v for k,v in fields.items() if k.startswith('v2_')}
                    metrics=None
                    for base in grouped[ident]:
                        row=read_row()
                        if row is None:break
                        if row['group']!=ident or row['strategy']!=strategy or row['params']!={**base,**position}:
                            raise ValueError('检查点参数序列不匹配，拒绝复用')
                        if metrics is not None and row['metrics']!=metrics:
                            raise ValueError('检查点等价账户结果不一致')
                        metrics=row['metrics']
                    if metrics is None:
                        stream=itertools.chain([job],stream);break
                    consume(ident,fields,metrics);reused+=1
                    if reused%2048==0:progress(6,f'已复用 {reused:,} / {total:,} 个账户')
                else:stream=iter(())
            f.flush()
        with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,initargs=(data,p.model_dump(mode='json'))) as executor:
            while batch:=list(itertools.islice(stream,128)):
                tick=time.perf_counter()
                for ident,fields,metrics in executor.map(evaluate,batch,chunksize=8):consume(ident,fields,metrics)
                f.flush()
                elapsed=time.perf_counter()-tick
                if any(j[1]=='trend_pullback_v2' for j in batch) and benchmark_seconds is None:
                    benchmark_seconds=elapsed/len(batch)*(total-reused)
                    progress(10+int(80*completed/total),f'已测 {len(batch)} 个账户；新增计算预计 {benchmark_seconds/60:.1f} 分钟，复用 {reused:,} 个账户')
                else:
                    progress(10+int(80*completed/total),f'参数回测 {completed:,} / {total:,} 个账户（完整 {count:,} 组；复用 {reused:,}）')
    progress(93,'使用原回测引擎复核优胜参数')
    baseline=multi_backtest(s['payload'],p)
    verification={}
    init_worker(data,p.model_dump(mode='json'))
    def verify_trace(winner,real):
        job=jobs[winner['group']]
        audited=evaluate((job[0],job[1],winner['params'],job[3],job[4]),audit=True)
        for field in ('metrics','trades','ledger','rejected'):
            assert audited[field]==real[field],('winner-trace-parity',job[1],field)
        assert [(x['date'],x['equity'],x['shares']) for x in audited['curve']]==[(x['date'],x['equity'],x['shares']) for x in real['curve']],('winner-curve-parity',job[1])
    for strategy,rows in leaders.items():
        winner=rows[0];q=p.model_copy(update={**saved_fields(strategy,winner['params']),'strategies':[strategy]})
        real=multi_backtest(s['payload'],q)['variants'][strategy]['book']
        assert real['metrics']==winner['metrics'],('winner-parity',strategy)
        verify_trace(winner,real)
        verification[strategy]=dict(params=q.model_dump(mode='json'),metrics=real['metrics'])
        (output/(strategy+'-winner.json')).write_text(store.dumps(real))
    mode_verification={}
    for mode,rows in mode_leaders.items():
        winner=rows[0];q=p.model_copy(update={**saved_fields('trend_pullback_v2',winner['params']),'strategies':['trend_pullback_v2']})
        real=multi_backtest(s['payload'],q)['variants']['trend_pullback_v2']['book']
        assert real['metrics']==winner['metrics'],('mode-winner-parity',mode)
        verify_trace(winner,real)
        mode_verification[mode]=dict(params=q.model_dump(mode='json'),metrics=real['metrics'])
        (output/('v2-'+mode+'-winner.json')).write_text(store.dumps(real))
    report=dict(reused_accounts=reused,computed_accounts=total-reused,resumed_from=str(resume) if resume else None,mode_leaders=mode_leaders,mode_verified=mode_verification,estimated_seconds=benchmark_seconds,symbol=symbol,snapshot_id=s['id'],engine=VERSION,objective='total_return',range=dict(start=str(p.start),end=str(p.end)),fallback=fallback,
        adaptation=adaptation,base_params=p.model_dump(mode='json'),grids=dict(trend_pullback=SMA_GRID,martin_daily=MARTIN_GRID,trend_pullback_v2=dict(sma=SMA_GRID,positions=POSITION_GRID)),candidates=count,unique_accounts=total,
        counts=counts,leaders=leaders,verified=verification,
        baseline={k:v['book']['metrics'] for k,v in baseline['variants'].items()},seconds=round(time.perf_counter()-started,2),
        note='满足历史约束的有限离散网格全覆盖；单股、固定快照、固定区间样本内累计收益排序，同收益按较小回撤、较少成交数排序。不是所有连续参数的全局最优，也不是样本外验证。资金、费用和交易约束固定；v2完整联合搜索124组仓位配置，Martin的EMA与3R/5R规则固定。')
    report['checksum']=hashlib.sha256(store.dumps(report).encode()).hexdigest()
    (output/'report.json').write_text(store.dumps(report));log.info('optimization verified symbol=%s seconds=%s',symbol,report['seconds'])

    return report

if __name__=='__main__':
    from .logging_setup import configure
    configure()
    parser=argparse.ArgumentParser();parser.add_argument('--symbol',default='601138.SH');parser.add_argument('--workers',type=int,default=4);parser.add_argument('--output',default='data/optimizations/601138-grid-v1');a=parser.parse_args()
    run(a.symbol,max(1,min(a.workers,4)),Path(a.output))

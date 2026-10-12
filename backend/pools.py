"""Local watchlists with dated, auditable membership and reproducible experiments."""
import hashlib
from datetime import date,datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel,Field,model_validator
from . import store
from .models import Parameters
from .quality import eligible,validate
from .fallback import prepare
from .research_engine import research_backtest

def today():return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
def init():
    with store.connect() as db:db.executescript('''
    CREATE TABLE IF NOT EXISTS pools(id TEXT PRIMARY KEY,name TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS pool_members(id TEXT PRIMARY KEY,pool_id TEXT,symbol TEXT,name TEXT,added TEXT,removed TEXT,recorded TEXT,retrospective INTEGER);
    CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY,pool_id TEXT,created TEXT,request TEXT,result TEXT);
    ''')
class PoolCreate(BaseModel):
    name:str=Field(min_length=1,max_length=60)
class MemberCreate(BaseModel):
    symbol:str=Field(pattern=r'^\d{6}\.(SZ|SH|BJ)$')
    effective:date
    retrospective:bool=False
    @model_validator(mode='after')
    def check(self):
        if str(self.effective)<today() and not self.retrospective:raise ValueError('过去的加入日期必须明确标记为回顾性研究')
        return self
class MemberRemove(BaseModel):
    effective:date
class ExperimentRequest(BaseModel):
    params:Parameters
    risk:float=Field(.005,gt=0,le=.05)
    stop_lookback:int=Field(10,ge=2,le=60)
    strength_lookback:int=Field(63,ge=20,le=250)
    top_n:int=Field(3,ge=1,le=100)
    as_of:date

def pools():
    with store.connect() as db:
        result=[]
        for r in db.execute('SELECT * FROM pools ORDER BY created'):
            members=[dict(m) for m in db.execute('SELECT * FROM pool_members WHERE pool_id=? ORDER BY added,symbol',(r['id'],))]
            for m in members:m['cached']=store.latest(symbol=m['symbol']) is not None
            result.append({**dict(r),'members':members})
        return result

def active(m,d):return m['added']<=d and (not m['removed'] or d<m['removed'])

def strength(payload,p,lookback):
    """Return vs CSI300 over matching market dates, adjusted only for effective actions."""
    actions={a['date']:a for a in payload['actions'] if a.get('verified')}
    index={r['date']:r for r in payload['index']};history=[];out={}
    quality=validate(payload)
    data={**payload,'quality':quality}
    for row in payload['bars']:
        d=row['date'];e=actions.get(d)
        if e:
            for h in history:h['close']=(h['close']-e.get('reference_cash',e.get('cash',0)))/(1+e.get('bonus',0)+e.get('transfer',0))
        if row['volume']<=0:continue
        history.append(dict(row));history=history[-lookback-1:]
        if len(history)<lookback+1 or d not in index or history[0]['date'] not in index:continue
        # Use strategy warmup validation as well: invalid candidates remain visible,
        # and must not silently improve the ranking by disappearing.
        q=p.model_copy(update={'symbol':payload.get('symbol','002028.SZ'),'start':date.fromisoformat(d),'end':date.fromisoformat(d),'data_after':None,'market_filter':True})
        problems=eligible(data,q)
        if problems:out[d]=dict(issues=problems);continue
        start=history[0];stock_return=row['close']/start['close']-1
        benchmark_return=index[d]['close']/index[start['date']]['close']-1
        out[d]=dict(stock_return=stock_return,benchmark_return=benchmark_return,excess_return=(1+stock_return)/(1+benchmark_return)-1,from_date=start['date'])
    return out

def experiment(pool,request,progress=lambda n,m:None):
    members=pool['members'];symbols=sorted({m['symbol'] for m in members});snapshots={};scores={};missing=[]
    for i,symbol in enumerate(symbols):
        progress(5+int(25*i/max(1,len(symbols))),f'检查缓存与历史强度：{symbol}')
        s=store.latest(symbol=symbol)
        if not s:missing.append(dict(symbol=symbol,reason='未缓存，请先同步'));continue
        snapshots[symbol]=s;scores[symbol]=strength(s['payload'],request.params,request.strength_lookback)
    all_dates=sorted({d for values in scores.values() for d in values}|{str(request.as_of)})
    rankings={};allowed={s:set() for s in symbols}
    for d in all_dates:
        if d>max(str(request.as_of),str(request.params.end)):continue
        eligible_symbols=sorted({m['symbol'] for m in members if active(m,d)})
        rows=[];unavailable=[]
        for symbol in eligible_symbols:
            score=scores.get(symbol,{}).get(d)
            if not score or score.get('issues'):
                unavailable.append(dict(symbol=symbol,reason='该日行情、预热或公司行动核验不完整'));continue
            rows.append(dict(symbol=symbol,**score))
        rows.sort(key=lambda r:(-r['excess_return'],r['symbol']))
        for rank,row in enumerate(rows,1):
            row.update(rank=rank,selected=not unavailable and rank<=request.top_n and row['excess_return']>0)
            if row['selected']:allowed[row['symbol']].add(d)
        rankings[d]=dict(date=d,rows=rows,unavailable=unavailable,complete=not unavailable,member_count=len(eligible_symbols))
    results=[]
    for i,symbol in enumerate(symbols):
        progress(35+int(60*i/max(1,len(symbols))),f'对照回测：{symbol}')
        if symbol not in snapshots:continue
        s=snapshots[symbol];p=request.params.model_copy(update={'symbol':symbol,'snapshot_id':s['id'],'data_after':None})
        _,p,fallback,problems=prepare({**s['payload'],'quality':validate(s['payload'])},p)
        if problems:
            results.append(dict(symbol=symbol,status='blocked',issues=problems));continue
        try:outcome=research_backtest(s['payload'],p,request.risk,request.stop_lookback,allowed[symbol])
        except Exception as exc:
            results.append(dict(symbol=symbol,status='blocked',issues=[dict(code='execution',date=None,message=str(exc),symbol=symbol,severity='error')]))
            continue
        # Year slices are descriptive attribution, not reset-capital independent tests.
        for variant in outcome['variants'].values():
            annual=[];previous=p.capital
            for year in sorted({r['date'][:4] for r in variant['curve']}):
                points=[r for r in variant['curve'] if r['date'].startswith(year)]
                end=points[-1]['equity'];annual.append(dict(year=year,start=points[0]['date'],end=points[-1]['date'],return_value=end/previous-1));previous=end
            variant['years']=annual
        results.append(dict(symbol=symbol,status='completed',params=p.model_dump(mode='json'),snapshot_id=s['id'],fallback=fallback,**outcome))
    result=dict(pool=pool,request=request.model_dump(mode='json'),snapshots={k:v['id'] for k,v in snapshots.items()},missing=missing,results=results,ranking=rankings.get(str(request.as_of)),rankings=rankings,retrospective=any(m['retrospective'] for m in members),note='每只股票独立账户对照，不是共享资金的组合收益；相对强度策略只在成员有效日期且全池当日数据完整时允许开仓。年度收益为连续账户分段。')

    result['checksum']=hashlib.sha256(store.dumps(result).encode()).hexdigest()
    return result

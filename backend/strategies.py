from .trading_rules import order_lot
from .logging_setup import log
"""Versioned daily approximation of the public Martin Luk thread, not intraday replication."""
import hashlib
import math
from .engine import Book, backtest, money, fees, VERSION, execution_price
from . import store
from .position import PositionBook,v2_parameters,RULES as POSITION_RULES
from .engine import indicators

NAMES={'trend_pullback_v2':'趋势回调 v2（仓位管理）','trend_pullback':'趋势回调（SMA）','martin_daily':'Martin Luk 回调（日线量化版）'}
SOURCE='https://x.com/OtherSideBJ/status/2109475443929972794'
RULES='日线收盘确认、次日开盘尝试；EMA9/21/50；近21/63/126日任一涨幅达到门槛；20日均成交额用收盘价×成交股数估算；AVWAP用典型价×成交量近似，锚点为此前窗口最高点；回踩后突破前日高点；信号日低点止损；3R/5R各减初始仓位约1/3，余仓收盘跌破EMA9退出。缺口支撑、主观形态及分钟信号未复现。'

def martin_indicators(payload,p,explain=False,features=False):
    actions={e['date']:e for e in payload['actions'] if e.get('verified')}
    history=[]; ema={};out={}
    for row in payload['bars']:
        d=row['date'];e=actions.get(d)
        if e:
            factor=e.get('reference_factor',1+e.get('bonus',0)+e.get('transfer',0));cash=e.get('reference_cash',e.get('cash',0))
            for h in history:
                for k in ('open','high','low','close'):h[k]=(h[k]-cash)/factor
                h['volume']*=factor
            ema={k:(v-cash)/factor for k,v in ema.items()}
        if row['volume']<=0:continue
        previous_ema50=ema.get(50)
        for n in (9,21,50):ema[n]=row['close'] if n not in ema else ema[n]+2/(n+1)*(row['close']-ema[n])
        history.append(dict(row)); n=len(history)
        returns={str(w):row['close']/history[-w-1]['close']-1 for w in (21,63,126) if n>w and history[-w-1]['close']>0}
        prior=history[max(0,n-1-p.martin_anchor_window):n-1]
        anchor=max(range(len(prior)),key=lambda i:(prior[i]['high'],i)) if prior else 0
        segment=prior[anchor:]+[history[-1]]
        volume=sum(h['volume'] for h in segment)
        avwap=sum((h['high']+h['low']+h['close'])/3*h['volume'] for h in segment)/volume
        previous_high=prior[anchor]['high'] if prior else row['high']
        supports=[ema[21],avwap,previous_high]
        tolerance=p.martin_support_tolerance
        support=any(abs(row['low']/v-1)<=tolerance and row['close']>v for v in supports if v>0)
        turnover=sum(h['close']*h['volume'] for h in history[-20:])/min(n,20)
        conditions=dict(warmup=n>=127,strength=len(returns)==3 and max(returns.values())>=p.martin_min_return,
            liquidity=turnover>=p.martin_min_turnover,trend=row['close']>ema[50] and previous_ema50 is not None and ema[50]>previous_ema50,
            pullback=support,rebound=n>1 and row['close']>history[-2]['high'] and row['close']>ema[9],
            risk=0<(row['close']-row['low'])/row['close']<=p.martin_max_stop)
        out[d]=dict(date=d,open=row['open'],high=row['high'],low=row['low'],close=row['close'],fast=ema[9],middle=ema[21],slow=ema[50],avwap=avwap,anchor_date=segment[0]['date'],stop=row['low'],buy=all(conditions.values()),sell=row['close']<ema[9],returns=returns)
        if explain:out[d]['conditions']=conditions
        if features:out[d]['features']=dict(turnover=turnover,support=min((abs(row['low']/v-1) for v in supports if v>0 and row['close']>v),default=None))
    return out

class MartinBook(Book):
    def __init__(self,p):
        super().__init__(p);self.stop=None;self.entry=None;self.unit_risk=None;self.initial_shares=0;self.stage=0;self.pending_stage=None;self.reason=''

    def execute(self,d,r,reference):
        original=self.p
        if self.pending=='buy' and r and r['volume']>0:
            price,_,blocked=execution_price(self.p,'buy',r,reference,d)
            if blocked:
                super().execute(d,r,reference);return
            distance=price-(self.stop or price)
            if distance<=0 or distance/price>self.p.martin_max_stop:
                self.rejected.append(dict(date=d,side='buy',reason='开盘跌破止损或止损距离超过上限'));self.pending=None;return
            budget=self.cash*self.p.martin_risk
            minimum,step=order_lot(self.p.symbol)
            qty=min(int(budget/distance/step)*step,int(self.cash*self.p.allocation/price/step)*step)
            while qty>=minimum:
                costs=sum(fees(qty*price,d,False,self.p).values())+sum(fees(qty*self.stop,d,True,self.p).values())
                if qty*distance+costs<=budget:break
                qty-=step
            if qty<minimum:
                self.rejected.append(dict(date=d,side='buy',reason=f'风险预算不足{minimum}股及双边预估费用'));self.pending=None;return
            spend=qty*price+sum(fees(qty*price,d,False,self.p).values())
            self.p=self.p.model_copy(update={'allocation':min(original.allocation,spend/self.cash+1e-10)})
        before=len(self.trades)
        try:super().execute(d,r,reference)
        finally:self.p=original
        if len(self.trades)==before:return
        t=self.trades[-1]
        if t['side']=='buy':
            self.entry=t['price'];self.unit_risk=self.entry-self.stop;self.initial_shares=t['shares'];self.stage=0
        elif self.pending_stage is not None:self.stage=self.pending_stage
        t.update(reason=self.reason,initial_stop=self.stop,risk_per_share=self.unit_risk,exit_stage=self.stage)
        self.pending_stage=None

    def adjust(self,e):
        if not e or self.entry is None:return
        factor=e.get('reference_factor',1+e.get('bonus',0)+e.get('transfer',0));cash=e.get('reference_cash',e.get('cash',0))
        self.entry=(self.entry-cash)/factor;self.stop=(self.stop-cash)/factor;self.unit_risk/=factor;self.initial_shares*=1+e.get('bonus',0)+e.get('transfer',0)
        if self.sell_quantity is not None:
            minimum,step=order_lot(self.p.symbol)
            self.sell_quantity=max(minimum,int(self.sell_quantity*(1+e.get('bonus',0)+e.get('transfer',0))/step)*step)

    def schedule(self,s):
        if self.shares:
            reason='结构止损' if s['close']<=self.stop else 'EMA9跟踪退出' if s['sell'] else None
            if reason:
                self.pending='sell';self.sell_quantity=None;self.pending_stage=None;self.reason=reason
            elif self.pending!='sell':
                reached=2 if s['close']>=self.entry+5*self.unit_risk else 1 if s['close']>=self.entry+3*self.unit_risk else 0
                if reached>self.stage:
                    # Below 300 shares, sell a minimum lot; never create an untradeable partial order.
                    minimum,step=order_lot(self.p.symbol)
                    one=max(minimum,int(self.initial_shares/3/step)*step)
                    self.sell_quantity=min(self.shares,one*(reached-self.stage));self.pending_stage=reached
                    self.pending='sell';self.reason='5R分批止盈' if reached==2 else '3R分批止盈'
        elif s['buy']:
            self.stop=s['stop'];self.pending='buy';self.pending_stage=None;self.reason='支撑回踩后反弹'

def pool_filter(p,progress=lambda *_:None):
    """Optional point-in-time local-pool rank. Missing candidates fail closed."""
    if not p.martin_pool_id:return None,dict(mode='single_stock',note='单股模式：只检查绝对涨幅与流动性，未进行池内或全市场排名。')
    from .pools import pools,active
    from .quality import eligible,validate
    from .fallback import slice_payload
    pool=next((x for x in pools() if x['id']==p.martin_pool_id),None)
    if not pool:raise ValueError('所选股票池不存在')
    if not any(m['symbol']==p.symbol for m in pool['members']):raise ValueError('当前股票不在所选股票池中')
    symbols=sorted({m['symbol'] for m in pool['members'] if m['added']<=str(p.end) and (not m['removed'] or m['removed']>str(p.start))})
    scores={};snapshots={}
    for symbol in symbols:
        s=store.latest(p.snapshot_id,symbol=symbol) if symbol==p.symbol and p.snapshot_id else store.latest(symbol=symbol)
        if not s:raise ValueError(f'股票池成员 {symbol} 未缓存，请先同步')
        data=slice_payload(s['payload'],p.data_after) if p.data_after else s['payload']
        q=p.model_copy(update={'symbol':symbol,'market_filter':False})
        problems=eligible({**data,'quality':validate(data)},q)
        if problems:raise ValueError(f'股票池成员 {symbol} 数据不完整：'+problems[0]['message'])
        scores[symbol]=martin_indicators(data,p);snapshots[symbol]=s['id']
    allowed=set();rankings={}
    for d in scores.get(p.symbol,{}):
        if not str(p.start)<=d<=str(p.end):continue
        members=sorted({m['symbol'] for m in pool['members'] if active(m,d)})
        if p.symbol not in members:continue
        if any(d not in scores.get(s,{}) or len(scores[s][d]['returns'])!=3 for s in members):continue
        ranks={}
        for window in ('21','63','126'):
            own=scores[p.symbol][d]['returns'][window]
            rank=1+sum(scores[s][d]['returns'][window]>own for s in members)
            ranks[window]=rank
            if rank<=max(1,math.ceil(len(members)*.3)) and own>=p.martin_min_return:allowed.add(d)
        rankings[d]=dict(ranks=ranks,members=len(members),selected=d in allowed)
    return allowed,dict(mode='pool',pool=pool,snapshots=snapshots,rankings=rankings,note='按历史有效成员，21/63/126日任一涨幅达到门槛且排名前30%；回顾性成员存在事后选股偏差；不是全市场选股。')

def multi_backtest(payload,p):
    log.info('backtest begin parameters=%s bars=%s',store.dumps(p.model_dump(mode='json')),len(payload['bars']))
    from .fallback import slice_payload
    # The baseline runner supplies the same buy-and-hold account, even when not selected.
    baseline=backtest(payload,p)
    variants={}
    if 'trend_pullback' in p.strategies:
        variants['trend_pullback']=dict(name=NAMES['trend_pullback'],book=baseline['strategy'],chart=baseline['chart'],rules='SMA趋势过滤、回踩与反弹确认；跌破中期均线退出。')
    for strategy in [s for s in p.strategies if s in ('martin_daily','trend_pullback_v2')]:
        is_v2=strategy=='trend_pullback_v2'
        q=v2_parameters(p) if is_v2 else p
        data=slice_payload(payload,p.data_after) if p.data_after else payload
        signals=indicators(data,q) if is_v2 else martin_indicators(data,p)
        allowed,selection=(None,None) if is_v2 else pool_filter(p)
        b=PositionBook(q) if is_v2 else MartinBook(p);bars={r['date']:r for r in data['bars']};actions={e['date']:e for e in data['actions'] if e.get('verified')}
        dates=[d for d in data['calendar'] if str(p.start)<=d<=str(p.end)]
        price=next(r['close'] for r in reversed(data['bars']) if r['date']<dates[0])
        for d in dates:
            r=bars.get(d);e=actions.get(d,{})
            reference=(price-e.get('reference_cash',e.get('cash',0)))/(e.get('reference_factor',1+e.get('bonus',0)+e.get('transfer',0)))
            b.adjust(e);b.process_actions(d);b.execute(d,r,reference);b.register(d,actions.values())
            price=r['close'] if r else reference;b.curve.append(b.valuation(d,price))
            if d in signals:
                signals[d]['buy']=signals[d]['buy'] and (allowed is None or d in allowed)
                b.schedule(signals[d])
        variants[strategy]=dict(name=NAMES[strategy],book=b.result(),chart=[signals[d] for d in dates if d in signals],rules=POSITION_RULES if is_v2 else RULES,selection=selection,**({} if is_v2 else {'source':SOURCE}))
    first=variants[p.strategies[0]]
    result=dict(engine=VERSION,strategy_id=p.strategies[0],strategy_name=first['name'],strategy=first['book'],chart=first['chart'],benchmark=baseline['benchmark'],variants=variants)
    result['checksum']=hashlib.sha256(store.dumps(result).encode()).hexdigest()
    log.info('backtest completed symbol=%s checksum=%s summaries=%s',p.symbol,result['checksum'],store.dumps({key:dict(metrics=v['book']['metrics'],trades=len(v['book']['trades']),rejected=len(v['book'].get('rejected',[]))) for key,v in variants.items()}))
    return result

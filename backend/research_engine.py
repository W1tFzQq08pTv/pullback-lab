"""Close-confirmed structural stop research; execution remains in the A-share Book."""
from .engine import Book, indicators, money, fees, VERSION
from .fallback import slice_payload

class RiskBook(Book):
    def __init__(self,p,risk):
        super().__init__(p);self.risk=risk;self.stop=None
    def execute(self,d,r,reference):
        original=self.p
        if self.pending=='buy' and r and r['volume']>0:
            price=money(r['open']*(1+self.p.slippage_bps/10000))
            if self.stop is None or price<=self.stop:
                self.rejected.append(dict(date=d,side='buy',reason='开盘已跌破结构止损或止损无效'));self.pending=None;return
            budget=self.cash*self.risk
            qty=int(budget/(price-self.stop)/100)*100
            qty=min(qty,int(self.cash*self.p.allocation/price/100)*100)
            # Reserve round-trip fees in the planned risk (gap loss is not capped).
            while qty>0:
                costs=sum(fees(qty*price,d,False,self.p).values())+sum(fees(qty*self.stop,d,True,self.p).values())
                if qty*(price-self.stop)+costs<=budget:break
                qty-=100
            if qty<=0:
                self.rejected.append(dict(date=d,side='buy',reason='风险预算不足100股及预估双边费用'));self.pending=None;return
            spend=qty*price+sum(fees(qty*price,d,False,self.p).values())
            self.p=self.p.model_copy(update={'allocation':min(original.allocation,spend/self.cash+1e-10)})
        try:super().execute(d,r,reference)
        finally:self.p=original

def research_backtest(payload,p,risk=.005,lookback=10,allowed=None):
    if p.data_after:payload=slice_payload(payload,p.data_after)
    signals=indicators(payload,p,explain=True)
    bars={r['date']:r for r in payload['bars']};actions={e['date']:e for e in payload['actions'] if e.get('verified')}
    dates=[d for d in payload['calendar'] if str(p.start)<=d<=str(p.end)]
    books=[Book(p),RiskBook(p,risk),RiskBook(p,risk)] if allowed is not None else [Book(p),RiskBook(p,risk)]
    names=['baseline','risk','relative_strength'];journals=[[] for _ in books];opened=[None for _ in books];pending_meta=[None for _ in books];last_exit=[None for _ in books]
    prior=[dict(r) for r in payload['bars'] if r['date']<dates[0] and r['volume']>0];price=prior[-1]['close']
    # Only the structural lookback is needed; earlier company actions are already
    # reflected in current prices after they leave this rolling window.
    adjusted=[];stops={}
    for row in payload['bars']:
        e=actions.get(row['date'])
        if e:
            for h in adjusted:h['low']=(h['low']-e.get('reference_cash',e.get('cash',0)))/(1+e.get('bonus',0)+e.get('transfer',0))
        if row['volume']>0:adjusted.append(dict(row))
        adjusted=adjusted[-lookback:]
        if adjusted:stops[row['date']]=min(h['low'] for h in adjusted)
    for day_index,d in enumerate(dates):
        r=bars.get(d);event=actions.get(d,{})
        factor=1+event.get('bonus',0)+event.get('transfer',0)
        reference=(price-event.get('reference_cash',event.get('cash',0)))/factor;price=reference
        for i,b in enumerate(books):
            if isinstance(b,RiskBook) and b.stop is not None and event:b.stop=(b.stop-event.get('reference_cash',event.get('cash',0)))/factor
            active=opened[i]
            if last_exit[i] and event:last_exit[i]['price']=(last_exit[i]['price']-event.get('reference_cash',event.get('cash',0)))/factor
            if active and event:
                active['basis']=(active['basis']-event.get('reference_cash',event.get('cash',0)))/factor
            b.process_actions(d);before=len(b.trades);b.execute(d,r,reference)
            if len(b.trades)>before:
                t=b.trades[-1]
                if t['side']=='buy':
                    meta=pending_meta[i] or {};previous=last_exit[i]
                    opened[i]=dict(entry_date=d,exit_date=None,entry_price=t['price'],basis=t['price'],shares=t['shares'],signal_date=meta.get('date'),entry_conditions=meta.get('conditions',{}),initial_stop=b.stop if isinstance(b,RiskBook) else None,planned_risk=money(t['shares']*(t['price']-b.stop)) if isinstance(b,RiskBook) else None,mae=0.,mfe=0.,exit_reason=None,pnl=None,reentry_days=day_index-previous['index'] if previous else None,higher_reentry=bool(previous and t['price']>previous['price']),status='持仓中')
                elif active:
                    ret=t['price']/active['basis']-1
                    active['mae']=min(active['mae'],ret);active['mfe']=max(active['mfe'],ret)
                    active.update(exit_date=d,exit_price=t['price'],exit_reason=(pending_meta[i] or {}).get('reason','均线退出'),pnl=b.cycles[-1],status='已平仓')
                    journals[i].append({k:v for k,v in active.items() if k!='basis'});opened[i]=None
                    last_exit[i]=dict(index=day_index,price=t['price'])
            b.register(d,actions.values())
            if r:price=r['close']
            b.curve.append(b.valuation(d,price))
            active=opened[i]
            if active and r and r['volume']>0:
                active['mae']=min(active['mae'],r['low']/active['basis']-1);active['mfe']=max(active['mfe'],r['high']/active['basis']-1)
            signal=signals.get(d)
            if not signal:continue
            if b.shares:
                stop_hit=isinstance(b,RiskBook) and b.stop is not None and r['close']<b.stop
                if b.pending!='sell' and (signal['sell'] or stop_hit):
                    b.pending='sell';pending_meta[i]=dict(reason='结构止损（收盘确认，次日尝试）' if stop_hit else '跌破中期均线（次日尝试）')
            elif signal['buy'] and (i!=2 or d in allowed):
                b.pending='buy';pending_meta[i]=signal
                if isinstance(b,RiskBook):b.stop=stops[d]
    result=dict(engine=VERSION+'-research-1',variants={})
    for i,b in enumerate(books):
        if opened[i]:journals[i].append({k:v for k,v in opened[i].items() if k!='basis'})
        result['variants'][names[i]]={**b.result(),'diagnostics':journals[i]}
    return result

from .trading_rules import limit_ratio
"""Deterministic daily event engine: signals at close, execution next session."""
import hashlib
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from . import store

VERSION='1.1.0'

def money(x):
    return float(Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def dividend_rate(acquired, sold):
    a,b=date.fromisoformat(acquired),date.fromisoformat(sold)
    # The transfer day is excluded; selling on the anniversary is still within the month/year.
    if b <= a+relativedelta(months=1): return .2
    if b <= a+relativedelta(years=1): return .1
    return 0.

def fees(amount, day, sell, p):
    commission=money(max(p.min_commission,amount*p.commission))
    transfer=money(amount*(.00002 if day<'2022-04-29' else .00001))
    stamp=money(amount*(.001 if day<'2023-08-28' else .0005)) if sell else 0.
    return dict(commission=commission,transfer=transfer,stamp=stamp)

def indicators(payload,p,explain=False):
    index={r['date']:r for r in payload['index']}
    ih=[]; market={}
    for d in payload['calendar']:
        if d in index:
            ih.append(index[d]['close'])
            market[d]=len(ih)>=p.slow and ih[-1]>sum(ih[-p.slow:])/p.slow
    actions={e['date']:e for e in payload['actions'] if e.get('verified')}
    history=[]; output={}
    for r in payload['bars']:
        d=r['date']
        e=actions.get(d)
        if e:
            # Re-express only past observations in today's price basis. No future adjustment.
            factor=e.get('reference_factor',1+e.get('bonus',0)+e.get('transfer',0))
            for h in history:
                for k in ('open','high','low','close'):
                    h[k]=(h[k]-e.get('reference_cash',e['cash']))/factor
        if r['volume']<=0: continue
        history.append(dict(r))
        n=len(history)
        def ma(period, offset=0):
            end=n-offset
            return sum(h['close'] for h in history[end-period:end])/period if end>=period else None
        fast,mid,slow=ma(p.fast),ma(p.middle),ma(p.slow)
        slope=ma(p.middle,p.slope)
        pull=False
        for j in range(min(p.pullback,n)):
            f,m=ma(p.fast,j),ma(p.middle,j)
            if f is not None and m is not None and history[-1-j]['low']<=f and history[-1-j]['close']>m:
                pull=True
        conditions=dict(trend=bool(slow is not None and r['close']>slow),slope=bool(mid is not None and slope is not None and mid>slope),pullback=pull,rebound=bool(n>1 and fast is not None and r['close']>history[-2]['high'] and r['close']>fast),market=bool(not p.market_filter or market.get(d,False)))
        buy=all(conditions.values())
        output[d]=dict(date=d,open=r['open'],high=r['high'],low=r['low'],close=r['close'],fast=fast,middle=mid,slow=slow,buy=buy,sell=bool(mid is not None and r['close']<mid))
        if explain:output[d]['conditions']=conditions

    return output

class Book:
    def __init__(self,p):
        self.p=p; self.cash=p.capital; self.lots=[]; self.entitlements=[]; self.ledger=[]; self.trades=[]; self.rejected=[]; self.curve=[]
        self.sell_quantity=None; self.pending=None; self.total_fees=0.; self.tax=0.; self.cycles=[]; self.entry_equity=None

    @property
    def shares(self): return sum(l['shares'] for l in self.lots)

    def log(self,d,kind,amount=0,shares=0,detail=''):
        self.ledger.append(dict(date=d,type=kind,amount=money(amount),shares=shares,cash=money(self.cash),detail=detail))

    def process_actions(self,d):
        for e in self.entitlements:
            if not e['recognized'] and e['date']<=d:
                e['recognized']=True
                self.log(d,'应收分红',e['gross'],detail=e['date'])
            if not e.get('credited') and e['new_shares'] and e.get('credit_date', e['date']) <= d:
                e['credited']=True
                self.lots.append(dict(shares=e['new_shares'],acquired=e['acquired'],available=e['share_date'],dividends=[]))
                self.log(d,'送转股份',shares=e['new_shares'])
            if not e['paid'] and e['pay']<=d:
                e['paid']=True; self.cash=money(self.cash+e['gross'])
                self.log(d,'分红到账',e['gross'],detail=e['date'])

    def register(self,d,actions):
        for a in actions:
            if a.get('record')!=d: continue
            for lot in self.lots[:]:
                raw_shares=lot['shares']*(a.get('bonus',0)+a.get('transfer',0))
                if abs(raw_shares-round(raw_shares))>1e-8:
                    raise ValueError('送转产生零碎股，公开日线无法确定登记结算分配结果；本次回测停止')
                gross=money(lot['shares']*a['cash'])
                entitlement=dict(date=a['date'],pay=a['pay'],gross=gross,recognized=False,paid=False,acquired=lot['acquired'],new_shares=int(lot['shares']*(a.get('bonus',0)+a.get('transfer',0))),share_date=a.get('share_date') or a['date'],credit_date=a.get('credit_date') or a['date'],credited=False)
                self.entitlements.append(entitlement)
                lot['dividends'].append(dict(base=gross+lot['shares']*a.get('bonus',0),date=a['date']))
                self.log(d,'权益登记',gross,detail=a['date'])

    def valuation(self,d,price):
        receivable=sum(e['gross'] for e in self.entitlements if e['recognized'] and not e['paid'])
        latent=sum(v['base']*dividend_rate(l['acquired'],d) for l in self.lots for v in l['dividends'])
        pending_shares=sum(e['new_shares'] for e in self.entitlements if e['recognized'] and not e.get('credited'))
        value=(self.shares+pending_shares)*price
        equity=self.cash+value+receivable
        return dict(date=d,equity=money(equity),cash=money(self.cash),shares=self.shares,pending_shares=pending_shares,market_value=money(value),receivable=money(receivable),potential_tax=money(latent),fees=money(self.total_fees),dividend_tax=money(self.tax))

    def execute(self,d,r,reference):
        side=self.pending
        if not side:return
        why=None
        if not r or r['volume']<=0: why='停牌或无可交易行情'
        if side=='sell' and (any(l['available']>d for l in self.lots) or any(e['recognized'] and e['new_shares'] and not e.get('credited') for e in self.entitlements)):why='T+1或送转股份尚未上市'
        if r and reference:
            limit=limit_ratio(self.p.symbol,d)
            upper,lower=money(reference*(1+limit)),money(reference*(1-limit))
            if side=='buy' and r['open']>=upper:why='开盘涨停，保守模型不买入'
            if side=='sell' and r['open']<=lower:why='开盘跌停，卖单保留'
            price=money(Decimal(str(r['open']))*(Decimal(1)+Decimal(str(self.p.slippage_bps))/Decimal(10000)*(1 if side=='buy' else -1)))
            if not max(r['low'],lower)<=price<=min(r['high'],upper):why='滑点后价格超出当日可成交范围'
        else:price=0.
        if not why and side=='buy':
            budget=min(self.cash,self.cash*self.p.allocation)
            qty=int(budget/price/100)*100
            while qty>0:
                fs=fees(qty*price,d,False,self.p)
                if qty*price+sum(fs.values())<=budget:break
                qty-=100
            if qty==0:why='资金不足100股及费用'
        if why:
            self.rejected.append(dict(date=d,side=side,reason=why))
            if side=='buy':self.pending=None
            return
        if side=='buy':
            self.entry_equity=self.cash+sum(e['gross'] for e in self.entitlements if not e['paid'])
            cost=money(qty*price); charge=money(sum(fs.values()))
            self.cash=money(self.cash-cost-charge)
            self.lots.append(dict(shares=qty,acquired=d,available=(date.fromisoformat(d)+timedelta(days=1)).isoformat(),dividends=[]))
            tax=0.
        else:
            qty=min(self.shares,self.sell_quantity) if self.sell_quantity is not None else self.shares
            if qty<=0:
                self.pending=None;self.sell_quantity=None;return
            cost=money(qty*price);fs=fees(cost,d,True,self.p)
            remaining=qty; tax_base=0.; kept=[]
            for lot in self.lots:
                take=min(remaining,lot['shares']); fraction=take/lot['shares']
                tax_base+=sum(v['base']*fraction*dividend_rate(lot['acquired'],d) for v in lot['dividends'])
                remaining-=take
                if take<lot['shares']:
                    kept.append({**lot,'shares':lot['shares']-take,'dividends':[{**v,'base':v['base']*(1-fraction)} for v in lot['dividends']]})
            tax=money(tax_base)
            charge=money(sum(fs.values()))
            self.cash=money(self.cash+cost-charge-tax);self.lots=kept;self.tax+=tax
            unsettled=sum(e['gross'] for e in self.entitlements if not e['paid'])
            if not self.shares:
                self.cycles.append(money(self.cash+unsettled-self.entry_equity))
                self.entry_equity=None
        self.total_fees+=charge
        self.trades.append(dict(date=d,side=side,price=price,shares=qty,amount=cost,**fs,dividend_tax=tax,cash=self.cash))
        self.log(d,'买入' if side=='buy' else '卖出',-cost-charge if side=='buy' else cost-charge-tax,qty)
        self.pending=None;self.sell_quantity=None

    def metrics(self):
        equity=[x['equity'] for x in self.curve]
        peak=self.p.capital;draw=[]
        for row in self.curve:
            peak=max(peak,row['equity']);dd=row['equity']/peak-1
            row['drawdown']=dd;draw.append(dd)
        years=max((self.p.end-self.p.start).days/365.25,1/365.25)
        return dict(total_return=equity[-1]/self.p.capital-1,annual_return=(equity[-1]/self.p.capital)**(1/years)-1,max_drawdown=min(draw),trade_count=len(self.trades),closed_trades=len(self.cycles),win_rate=sum(x>0 for x in self.cycles)/len(self.cycles) if self.cycles else None,exposure=sum(x['shares']>0 for x in self.curve)/len(self.curve),fees=money(self.total_fees),dividend_tax=money(self.tax),ending=self.curve[-1])

    def result(self):
        return dict(metrics=self.metrics(),curve=self.curve,trades=self.trades,ledger=self.ledger,rejected=self.rejected)

def backtest(payload,p):
    if p.data_after:
        from .fallback import slice_payload
        payload=slice_payload(payload,p.data_after)
    signals=indicators(payload,p)
    bars={r['date']:r for r in payload['bars']}
    actions={e['date']:e for e in payload['actions'] if e.get('verified')}
    books=[Book(p),Book(p)]
    dates=[d for d in payload['calendar'] if str(p.start)<=d<=str(p.end)]
    previous=[r for r in payload['bars'] if r['date']<dates[0]]
    price=previous[-1]['close']
    for d in dates:
        r=bars.get(d)
        e=actions.get(d,{})
        reference=(price-e.get('reference_cash',e.get('cash',0)))/(e.get('reference_factor',1+e.get('bonus',0)+e.get('transfer',0)))
        price=reference
        for ix,b in enumerate(books):
            b.process_actions(d)
            if ix==1 and not b.trades:b.pending='buy'
            b.execute(d,r,reference)
            b.register(d,actions.values())
            if r:price=r['close']
            b.curve.append(b.valuation(d,price))
            if ix==0 and d in signals:
                if b.shares and signals[d]['sell']:b.pending='sell'
                elif not b.shares and signals[d]['buy']:b.pending='buy'
    result=dict(engine=VERSION,strategy=books[0].result(),benchmark=books[1].result(),chart=[signals[d] for d in dates if d in signals])
    result['checksum']=hashlib.sha256(store.dumps(result).encode()).hexdigest()
    return result

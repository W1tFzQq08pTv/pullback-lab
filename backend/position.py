"""SMA v2: fixed cycle budget and close-confirmed, equal-budget entries."""
from .engine import Book, money

V2_FIELDS = ('fast','middle','slow','slope','pullback','market_filter')
POSITION_GRID = [dict(v2_mode='fixed',v2_allocation=a,v2_batches=1,v2_step=.02) for a in (.25,.5,.75,1.)]
POSITION_GRID += [dict(v2_mode=mode,v2_allocation=a,v2_batches=n,v2_step=step)
                 for mode in ('up','down') for a in (.25,.5,.75,1.)
                 for n in (2,3,4) for step in (.02,.04,.06,.08,.1)]
RULES='沿用SMA入场与中期均线退出；固定周期资金预算，固定比例一次买入，或按首次成交价的等距涨跌阈值分批买入；每日最多一批，退出优先，收盘确认、次日尝试。批次预算含费用，不借款，不自动再平衡。'

def v2_parameters(p):
    return p.model_copy(update={k:getattr(p,'v2_'+k) for k in V2_FIELDS})

def saved_fields(strategy, fields):
    return {('v2_'+k if strategy=='trend_pullback_v2' and k in V2_FIELDS else k):v for k,v in fields.items()}

class PositionBook(Book):
    def __init__(self,p):
        super().__init__(p)
        self.first_price=None;self.cycle_budget=None;self.batch=0;self.reason=''

    def buy_budget(self):
        batches=1 if self.p.v2_mode=='fixed' else self.p.v2_batches
        return min(self.cash,self.cycle_budget/batches)

    def adjust(self,e):
        if e and self.first_price is not None:
            self.first_price=(self.first_price-e.get('reference_cash',e.get('cash',0)))/e.get('reference_factor',1+e.get('bonus',0)+e.get('transfer',0))

    def execute(self,d,r,reference):
        side=self.pending
        if not side:return
        fresh=side=='buy' and self.first_price is None
        if fresh:
            # Mark equity immediately before the first attempt. Freeze only on fill.
            self.cycle_budget=self.valuation(d,reference)['equity']*self.p.v2_allocation
        budget=self.buy_budget() if side=='buy' else None
        before=len(self.trades)
        super().execute(d,r,reference)
        if len(self.trades)==before:
            if fresh:self.cycle_budget=None
            return
        t=self.trades[-1]
        if side=='buy':
            self.batch+=1
            if fresh:self.first_price=t['price']
        t.update(reason=self.reason,batch=self.batch,batch_budget=money(budget) if budget is not None else None,
                 cycle_budget=money(self.cycle_budget),first_price=self.first_price)
        if side=='sell' and not self.shares:
            self.first_price=None;self.cycle_budget=None;self.batch=0

    def schedule(self,s):
        if self.pending=='sell':return
        self.pending=None
        if not self.shares:
            if s['buy']:self.pending='buy';self.reason='回调反弹首仓'
            return
        if s['sell']:
            self.pending='sell';self.reason='跌破中期均线清仓';return
        if self.p.v2_mode=='fixed' or self.batch>=self.p.v2_batches:return
        direction=1 if self.p.v2_mode=='up' else -1
        threshold=self.first_price*(1+direction*self.batch*self.p.v2_step)
        if (s['close']-threshold)*direction>=0:
            self.pending='buy';self.reason=('上涨确认加仓' if direction==1 else '回调加深加仓')+f' · 第{self.batch+1}批'

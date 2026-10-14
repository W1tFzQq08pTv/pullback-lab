"""Conditional next-session signal using the same close-time rules as backtests."""
from datetime import date
from .engine import indicators, VERSION
from .quality import eligible, validate, issue
from .sources import cutoff_date

def latest_signal(snapshot, p):
    from .strategies import martin_indicators,pool_filter,NAMES
    strategy=p.strategies[0]
    if strategy=='martin_daily':p=p.model_copy(update={'market_filter':False})
    payload=snapshot['payload']
    end=payload['end']
    params=p.model_copy(update={'start':date.fromisoformat(end),'end':date.fromisoformat(end),'snapshot_id':snapshot['id'],'data_after':None})
    # Ignore backtest date selection, but validate all data used by the indicators.
    checked={**payload,'quality':validate(payload)}
    problems=eligible(checked,params)
    rows=[r for r in payload['bars'] if r['date']<=end and r['volume']>0]
    if not rows or rows[-1]['date']!=end:
        problems.append(issue('latest_bar',end,'最新市场交易日无有效个股行情，不能沿用旧信号',p.symbol))
    result=dict(symbol=p.symbol,snapshot_id=snapshot['id'],engine=VERSION,as_of=end,next_session=None,
                target='下一市场交易日（日期尚未核验）',stale=end<cutoff_date(),
                strategy_name=NAMES[strategy],strategy_id=strategy,status='blocked' if problems else 'ready',issues=problems,params=params.model_dump(mode='json'))
    if problems:return result
    signal=(martin_indicators if strategy=='martin_daily' else indicators)(payload,params,explain=True)[end]
    if strategy=='martin_daily' and params.martin_pool_id:
        try:
            allowed,_=pool_filter(params)
            signal['conditions']['pool_rank']=end in allowed
            signal['buy']=signal['buy'] and end in allowed
        except ValueError as exc:
            result.update(status='blocked',issues=[issue('pool',end,str(exc),p.symbol)])
            return result
    result.update(signal=signal,flat='买入' if signal['buy'] else '观望',holding=('EMA9退出' if signal['sell'] else '需核对持仓止损与止盈') if strategy=='martin_daily' else ('卖出' if signal['sell'] else '继续持有'))
    return result

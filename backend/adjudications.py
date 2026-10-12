"""Narrow, evidence-bounded corrections. Never general 'secondary wins'."""
def resolve(symbol, primary, secondary):
    if symbol != 'sh000300':return None
    d=primary['date']
    reason=None; evidence=None
    if d=='2015-03-27' and primary['low']==3993.032 and primary['high']==3993.032 and secondary['low']==3932.87 and primary['close']==secondary['close']==3971.697:
        reason='已更正：腾讯最低价3993.032高于开盘与收盘；采用OHLC关系合法的新浪原始日线，双方收盘3971.697一致'
        evidence='https://finance.sina.com.cn/realstock/company/sh000300/hisdata/klc_kl.js'
    if d=='2016-01-04' and primary['close']==3470.41 and secondary['close']==3469.066 and secondary['low']==3468.949:
        reason='已核验：2016-01-04熔断日采用新浪日线；新浪3469.066与当日全景网收盘报道3469.07一致，保留腾讯差异'
        evidence='https://www.p5w.net/stock/news/mszd/201601/t20160105_1316225.htm'
    return dict(date=d,symbol=symbol,primary=primary,selected=secondary,reason=reason,evidence=evidence) if reason else None

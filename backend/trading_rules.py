"""Ordinary A-share daily execution rules; unsupported boards fail closed.

ChiNext switches to 20% on 2020-08-24 (SZSE t20200821_580925).
STAR: SSE investor education https://edu.sse.com.cn/tib/qa/c/4761956.shtml
IPO unrestricted sessions are excluded from execution by 250-bar warmup.
"""
def board(symbol):
    if symbol.endswith('.BJ') and symbol.startswith('920'):return 'beijing'
    if symbol.endswith('.SH') and symbol.startswith('688'):return 'star'
    if symbol.endswith('.SZ') and symbol.startswith(('300','301')):return 'chinext'
    if (symbol.endswith('.SH') and symbol.startswith(('600','601','603','605'))) or (symbol.endswith('.SZ') and symbol.startswith(('000','001','002','003'))):return 'main'
    return None

def limit_ratio(symbol,day):
    kind=board(symbol)
    if kind is None:raise ValueError('未支持的股票板块交易规则：'+symbol)
    if kind=='beijing':return .30
    return .20 if kind=='star' or (kind=='chinext' and day>='2020-08-24') else .10

def order_lot(symbol):
    if board(symbol)=='beijing':return (100,1)
    return (200,1) if board(symbol)=='star' else (100,100)

def supported(symbol,name=''):
    return board(symbol) is not None and 'ST' not in name.upper() and '退' not in name

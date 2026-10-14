"""Daily auction limits for supported ordinary A shares.

SZSE 2020-08-21 press conference: existing ChiNext stocks move from 10%
to 20% on 2020-08-24. IPO no-limit sessions are outside the 250-bar warmup.
https://www.szse.cn/aboutus/trends/conference/t20200821_580925.html
"""
def limit_ratio(symbol,day):
    return .20 if symbol.startswith(('300','301')) and day>='2020-08-24' else .10

def supported(symbol,name=''):
    return symbol.startswith(('000','001','002','003','600','601','603','605','300','301')) and 'ST' not in name.upper() and '退' not in name

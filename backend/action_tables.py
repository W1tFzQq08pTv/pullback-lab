"""Strict Shanghai cash-distribution table parser; no date or payment inference."""
import re
from datetime import date

def cash_table(text,code,title):
    if not title.endswith('权益分派实施公告') or not re.search(r'证券代码[:：]'+re.escape(code),text):return None
    header=r'股份类别股权登记日最后交易日除权[（(]息[）)]日现金红利发放日[AＡ]股'
    d=r'(20\d{2})/(\d{1,2})/(\d{1,2})'
    # Keep the date table delimiters: adjacent dates are disambiguated by the 20xx year.
    matches=re.findall(header+d+r'[－—-]?'+d+d,text)
    dates=set()
    for m in matches:
        try:dates.add(tuple(date(int(m[i]),int(m[i+1]),int(m[i+2])).isoformat() for i in (0,3,6)))
        except ValueError:return None
    if len(dates)!=1:return None
    record,ex,pay=dates.pop()
    if not record<ex<=pay:return None
    cash=re.search(r'[AＡ]股每股现金红利([\d.]+)元',text)
    if not cash:return None
    cash=float(cash[1]);reference=cash
    if '差异化分红送转：是' in text:
        values={float(v) for v in re.findall(r'[=＝]前收盘价格[-－]([\d.]+)元/股',text)}
        if len(values)!=1:return None
        reference=values.pop()
    if not 0<reference<=cash:return None
    return dict(record=record,date=ex,pay=pay,cash=cash,reference_cash=reference)

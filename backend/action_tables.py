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


def transfer_terms(text,event):
    """Require explicit actual distribution and cash-only tax evidence."""
    if event.get('bonus') or not event.get('transfer'):return None
    ratios={float(v)/10 for v in re.findall(r'每10股转增([\d.]+)股',text)}
    taxes={float(v)/10 for v in re.findall(r'每10股补缴税款([\d.]+)元',text)}
    if not any(abs(v-event['transfer'])<1e-8 for v in ratios):return None
    if not all(any(abs(v-event['cash']*rate)<1e-7 for v in taxes) for rate in (.1,.2)):return None
    terms={}
    # Repurchased shares may be excluded: the exchange reference is not the
    # actual cash or shares received by a participating shareholder.
    if '回购' in text or '差异化' in text:
        pairs=re.findall(r'股权登记日收盘价[-－]([\d.]+)元[）)]/[（(]1[+＋]([\d.]+)[）)]',text)
        if len(set(pairs))!=1:return None
        cash,transfer=map(float,pairs[0])
        if not 0<cash<=event['cash'] or not 0<transfer<=event['transfer']:return None
        terms.update(reference_cash=cash,reference_factor=1+transfer)
    return terms or {'reference_factor':1+event['transfer']}

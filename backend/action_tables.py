"""Strict Shanghai cash-distribution table parser; no date or payment inference."""
import re
from datetime import date

def cash_table(text,code,title):
    if not re.search(r'(权益分派|分红派息|利润分配).*实施(?:方案)?公告$',title) or not re.search(r'证券代码[:：]'+re.escape(code),text):return None
    header=r'(?:股份类别)?股权登记日(?:最后交易日)?除权[（(]息[）)]日现金红利发放日(?:[AＡ]股)?'
    d=r'(20\d{2})/(\d{1,2})/(\d{1,2})'
    # Keep the date table delimiters: adjacent dates are disambiguated by the 20xx year.
    matches=re.findall(header+d+r'[－—-]?'+d+d,text)
    dates=set()
    for m in matches:
        try:dates.add(tuple(date(int(m[i]),int(m[i+1]),int(m[i+2])).isoformat() for i in (0,3,6)))
        except ValueError:continue
    if not dates:
        # Older implementation notices spell out each date instead of a table.
        def labelled(label):
            found=re.findall(label+r'[为是：:]*(20\d{2})年(\d{1,2})月(\d{1,2})日',text)
            values=set()
            for y,m,d in found:
                try:values.add(date(int(y),int(m),int(d)).isoformat())
                except ValueError:continue
            return next(iter(values)) if len(values)==1 else None
        record=labelled('股权登记日');ex=labelled(r'(?:除权除息日|除权[（(]除?息[）)]日|除息日)');pay=labelled(r'现金(?:股利|股息|红利)发放日')
        if record and ex and pay:dates.add((record,ex,pay))
    if len(dates)!=1:return None
    record,ex,pay=dates.pop()
    if not record<ex<=pay:return None
    cash=re.search(r'(?:[AＡ]股)?每股现金红利(?:人民币)?([\d.]+)元',text)
    if not cash:cash=re.search(r'每股派发(?:20\d{2}年(?:年度|半年度|末期|中期)?)?现金股息(?:人民币)?([\d.]+)元[（(]含税[）)]',text)
    if not cash:cash=re.search(r'每股派发现金红利(?:人民币)?([\d.]+)元[（(]含税[）)]|每股派发现金红利[（(]含税[）)][:：]([\d.]+)元',text)
    if not cash:return None
    cash=float(next(v for v in cash.groups() if v is not None));reference=cash
    if '差异化分红送转：是' in text:
        values={float(v) for v in re.findall(r'[=＝][（(]?前收盘价格[-－]([\d.]+)[）)]?元/股',text)}
        values.update(float(v) for v in re.findall(r'除权[（(]息[）)]参考价格[=＝][（(]前收盘价格[-－]([\d.]+)[）)][÷/][（(]1[+＋]0[）)]',text))
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

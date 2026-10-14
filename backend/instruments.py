"""Cache-only ETF/BSE metadata. Never infer market rules from a fund name."""
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from .sources import Feed

ETF_URL="https://vip.stock.finance.sina.com.cn/quotes_service/api/jsonp.php/IO.XSRV2.CallbackList%5B%27da_yPT46_Ll7K6WD%27%5D/Market_Center.getHQNodeDataSimple?page=1&num=5000&sort=symbol&asc=0&node=etf_hq_fund"
BSE_URL='https://www.bse.cn/service/code_mapping.html'

def etf_directory():
    f=Feed()
    try:
        text=f.get(ETF_URL,ttl=86400,offline=True).decode()
        rows=json.loads(text[text.index('([{')+1:text.rfind(')')])
        if len(rows)>=5000:raise ValueError('ETF目录达到单页上限，需补充分页')
        return [dict(symbol=r['symbol'][2:]+'.'+r['symbol'][:2].upper(),code=r['symbol'][2:],name=r['name'],pinyin='',org_id='',asset_type='etf',directory_source=ETF_URL) for r in rows if re.fullmatch(r'(sh|sz)\d{6}',r['symbol'])]
    finally:f.close()

def bse_mapping():
    f=Feed()
    try:
        soup=BeautifulSoup(f.get(BSE_URL,ttl=86400,offline=True),'html.parser');rows=[]
        for tr in soup.select('tr'):
            cells=[c.get_text(strip=True) for c in tr.select('td')]
            if len(cells)!=5 or not re.fullmatch(r'920\d{3}',cells[4]):continue
            rows.append(dict(name=cells[1],listed=datetime.strptime(cells[2],'%Y/%m/%d').date().isoformat(),old_code=cells[3],code=cells[4],source=BSE_URL))
        if not rows:raise ValueError('北交所官方代码表为空')
        return rows
    finally:f.close()

def fund_events(feed):
    url=f"https://fundf10.eastmoney.com/fhsp_{feed.stock['code']}.html"
    soup=BeautifulSoup(feed.get(url),'html.parser');events=[]
    for tr in soup.select('tr'):
        c=[td.get_text(strip=True) for td in tr.select('td')]
        if len(c)>=5 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',c[1]) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',c[2]):
            cash=re.search(r'每10份派现金([\d.]+)元',c[3])
            if cash:events.append(dict(date=c[2],record=c[1],pay=c[4],cash=float(cash[1])/10,bonus=0,transfer=0,verified=False,source=url,review_reason='ETF分红已缓存，待管理人公告核验'))
    # Keep the whole page as evidence, including split/conversion tables. Missing
    # records are not evidence that a fund has never distributed or split shares.
    return events,url

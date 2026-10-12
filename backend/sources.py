"""Public feeds, archived before parsing; no silent fill or forward-fill."""
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from . import store

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'}

class Feed:
    def __init__(self, stock=None, force=False):
        self.stock=stock or dict(symbol="002028.SZ",code="002028",name="思源电气",org_id="gssz0002028")
        self.force=force
        self.cached_fallbacks = set()
        self.fresh_market = False
        self.evidence = {}
        self.client = httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)

    def get(self, url, *, immutable=False, form=None, ttl=21600, offline=False):
        key = url + ('#' + store.dumps(form) if form else '')
        prior = store.cached(key)
        if prior and not self.force and (datetime.now(timezone.utc)-datetime.fromisoformat(prior[1]['fetched'])).total_seconds() < (315360000 if immutable else ttl):
            self.evidence[key] = prior[1]['digest']
            return prior[0]
        error = None
        for attempt in range(3):
            try:
                time.sleep(.15)
                r = self.client.post(url, data=form, headers={'Referer':'https://www.cninfo.com.cn/'}) if form else self.client.get(url)
                r.raise_for_status()
                if not r.content:
                    raise ValueError('上游返回空响应')
                digest = store.archive(key, r.content)
                self.evidence[key] = digest
                return r.content
            except Exception as exc:
                error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if offline and prior:
            self.cached_fallbacks.add(url)
            self.evidence[key]=prior[1]['digest']
            return prior[0]
        raise RuntimeError(f'公开接口获取失败 {url}: {error}')

    def sina_decoded(self, url):
        import py_mini_racer
        from akshare.stock.cons import hk_js_decode
        body = self.get(url, ttl=0 if self.fresh_market else 21600).decode()
        encoded = body.split('=', 1)[1].split(';')[0].strip().strip('"')
        with py_mini_racer.MiniRacer() as ctx:
            ctx.eval(hk_js_decode)
            return ctx.call('d', encoded)

    def calendar(self):
        rows = self.sina_decoded('https://finance.sina.com.cn/realstock/company/klc_td_sh.txt')
        return sorted(set(str(d)[:10] for d in rows))

    def sina_bars(self, symbol):
        rows = self.sina_decoded(f'https://finance.sina.com.cn/realstock/company/{symbol}/hisdata/klc_kl.js')
        return [dict(date=str(r['date'])[:10], **{k: float(r[k]) for k in ('open','high','low','close','volume')}, source='sina') for r in rows]

    def tencent_bars(self, symbol, year, cutoff):
        url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{year}-01-01,{year}-12-31,640,'
        raw = json.loads(self.get(url, ttl=2592000 if year < int(cutoff[:4]) else (0 if self.fresh_market else 21600)))
        if raw.get('code') != 0:
            raise ValueError('腾讯返回错误状态')
        rows = raw.get('data', {}).get(symbol, {}).get('day')
        if rows is None:
            raise ValueError(f'腾讯缺少 {symbol} {year} 日线字段')
        return [dict(date=r[0], open=float(r[1]), close=float(r[2]), high=float(r[3]), low=float(r[4]), volume=float(r[5])*100, source='tencent') for r in rows if r[0].startswith(str(year))]

    def listing_date(self):
        url=f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{self.stock['code']}.phtml"
        text=BeautifulSoup(self.get(url,ttl=2592000).decode('gb18030',errors='replace'),'html.parser').get_text(' ',strip=True)
        match=re.search(r'上市日期[：:]\s*(\d{4}-\d{2}-\d{2})',text)
        if not match:raise ValueError('未能核验上市日期')
        return match[1]

    def risk_notices(self):
        form=dict(pageNum='1',pageSize='30',column='sse' if self.stock['symbol'].endswith('.SH') else 'szse',tabName='fulltext',stock=self.stock['code']+','+self.stock['org_id'],searchkey='风险警示',seDate='2015-01-01~'+cutoff_date())
        result=json.loads(self.get('https://www.cninfo.com.cn/new/hisAnnouncement/query',form=form))
        if result.get('totalAnnouncement',0)>30:raise ValueError('风险警示公告超过单页，需核实历史交易规则')
        return [a for a in result.get('announcements') or [] if re.search(r'(实施|撤销|摘帽|继续|叠加).*风险警示',a.get('announcementTitle',''))]

    def dividends(self):
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{self.stock['code']}.phtml"
        soup = BeautifulSoup(self.get(url).decode('gb18030', errors='replace'), 'html.parser')
        table = soup.find(id='sharebonus_1')
        if not table:
            raise ValueError('新浪分红表结构变化')
        events = []
        for row in table.select('tbody tr'):
            c = [x.get_text(strip=True) for x in row.find_all('td')]
            if len(c) < 9 or c[4] != '实施' or c[5] < '2015-01-01':
                continue
            events.append(dict(announcement=c[0], date=c[5], record=c[6], share_date=c[7] if c[7] != '--' else None, bonus=float(c[1])/10, transfer=float(c[2])/10, cash=float(c[3])/10, pay=None, verified=False, source=url))
        rights = soup.find(id='sharebonus_2')
        if not rights:
            raise ValueError('新浪配股表缺失，不能确认公司行动完整性')
        for row in rights.select('tbody tr'):
            c = [x.get_text(strip=True) for x in row.find_all('td')]
            if len(c) > 5 and c[4] >= '2015-01-01':
                events.append(dict(date=c[4], type='rights', verified=False, source=url))
        return events

    def announcements(self):
        form = dict(pageNum='1', pageSize='30', column='sse' if self.stock['symbol'].endswith('.SH') else 'szse', tabName='fulltext', stock=self.stock['code']+','+self.stock['org_id'], searchkey='权益分派实施', seDate='2015-01-01~'+datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
        result = json.loads(self.get('https://www.cninfo.com.cn/new/hisAnnouncement/query', form=form))
        if result.get('totalAnnouncement', 0) > 30:
            raise ValueError('实施公告超过单页，需要补齐分页后才能核验')
        return result.get('announcements') or []

    def verify_actions(self, events):
        announcements = self.announcements()
        for a in announcements:
            url = 'https://static.cninfo.com.cn/' + a['adjunctUrl']
            blob = self.get(url, immutable=True)
            text = ''.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(blob)).pages)
            text = re.sub(r'\s+', '', text)
            from .action_tables import cash_table
            table=cash_table(text,self.stock['code'],a.get('announcementTitle',''))
            if table:
                matched=[e for e in events if e['date']==table['date']]
                for e in matched:
                    if e['record']==table['record'] and abs(e['cash']-table['cash'])<.00001 and not e.get('bonus') and not e.get('transfer'):
                        e.update(table,verified=True,evidence=url,evidence_digest=store.archive(url,blob))
                        e.pop('review_reason',None)
                if matched:continue
            date_pattern = r'(20\d{2})年(\d{1,2})月(\d{1,2})日'
            def date_after(pattern):
                match = re.search(pattern + date_pattern, text)
                return '%s-%02d-%02d' % (match[1], int(match[2]), int(match[3])) if match else None
            ex = date_after(r'除权除息日[为是：:]*')
            record = date_after(r'股权登记日[为是：:]*')
            pay = date_after(r'现金红利将于')
            candidates = [e for e in events if e['date'] == ex]
            if not candidates:
                if ex:
                    events.append(dict(date=ex, type='unmatched_announcement', source=url, verified=False))
                continue
            e = candidates[0]
            # The final distribution paragraph explicitly states per-ten-share cash.
            values = re.findall(r'每10股派(?:发现金(?:红利|股利)?)?([\d.]+)元', text)
            cash_values = [float(v)/10 for v in values]
            matches = [v for v in cash_values if abs(v-e['cash']) < .00001]
            if matches and record == e['record'] and pay:
                e.update(cash=round(matches[0], 8), pay=pay, verified=True, evidence=url, evidence_digest=store.archive(url, blob))
                # A special shareholder-specific distribution or nonzero share action needs explicit verification.
                if e['bonus'] or e['transfer']:
                    e['verified'] = False
                    e['review_reason'] = '送转事件需确认股份到账日、上市日与税务属性'
                    credited = date_after(r'所送（转）股于')
                    available = date_after(r'无限售流通股的起始交易日为')
                    # This exact issuer announcement explicitly taxes only cash (0.4/0.2 per ten).
                    if self.stock['symbol']=='002028.SZ' and ex == '2016-04-25' and e['bonus'] == 0 and e['transfer'] == .2 and credited and available and '每10股补缴税款0.400000元' in text:
                        e.update(verified=True, share_date=available, credit_date=credited, transfer_taxable=False)
                        e.pop('review_reason', None)
        return sorted(events, key=lambda e:e['date'])

    def close(self):
        self.client.close()

def cutoff_date(now=None):
    local = (now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai'))
    # Admit today's daily bar only after the 15:00 close; providers are still validated.
    return (local.date() if local.hour >= 15 else local.date()-timedelta(days=1)).isoformat()

def explicit_suspension_dates(text):
    """Accept one explicit initial suspension and one distinct resumption; ignore continuations."""
    text=re.sub(r'\s+','',text)
    date_pattern=r'(20\d{2})年(\d{1,2})月(\d{1,2})日'
    suffix=r'(?:[（(](?:星期|周)[一二三四五六日天][）)])?(?:开市|开盘)?(?:时)?(?:起|开始)?'
    def find(action):
        matches=re.finditer(r'(?:自|于)'+date_pattern+suffix+action,text)
        values=set()
        for match in matches:
            # Expected/conditional dates are not implementation evidence.
            if re.search(r'预计|拟于|争取|可能',text[max(0,match.start()-12):match.start()+1]):continue
            values.add('%s-%02d-%02d'%(match[1],int(match[2]),int(match[3])))
        return sorted(values)
    return find(r'(?:临时)?停牌'),find('复牌')

def explicit_suspension_interval(text):
    starts,ends=explicit_suspension_dates(text)
    if len(starts)==len(ends)==1 and starts[0]<ends[0]:return starts[0],ends[0]
    return None

def verify_suspensions(feed, missing, bars=None):
    if not missing:return [],[]
    dates=sorted(set(missing));clusters=[]
    for day in dates:
        if not clusters or (datetime.fromisoformat(day)-datetime.fromisoformat(clusters[-1][-1])).days>45:clusters.append([])
        clusters[-1].append(day)
    confirmed=set();evidence=[];documents={}
    for cluster in clusters:
        begin=(datetime.fromisoformat(cluster[0])-timedelta(days=180)).date().isoformat()
        end=min(cutoff_date(),(datetime.fromisoformat(cluster[-1])+timedelta(days=365)).date().isoformat())
        cluster_docs=[]
        for keyword in ('复牌','停牌'):
            page=1
            while True:
                form=dict(pageNum=str(page),pageSize='30',column='sse' if feed.stock['symbol'].endswith('.SH') else 'szse',tabName='fulltext',stock=feed.stock['code']+','+feed.stock['org_id'],searchkey=keyword,seDate=begin+'~'+end)
                result=json.loads(feed.get('https://www.cninfo.com.cn/new/hisAnnouncement/query',form=form))
                announcements=result.get('announcements') or []
                for a in announcements:
                    if a.get('secCode')!=feed.stock['code']:continue
                    url='https://static.cninfo.com.cn/'+a['adjunctUrl']
                    if url not in documents:
                        blob=feed.get(url,immutable=True)
                        text=''.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(blob)).pages)
                        compact=re.sub(r'\s+','',text)
                        if not re.search(r'证券代码[：:]?'+re.escape(feed.stock['code']),compact):continue
                        starts,resumes=explicit_suspension_dates(text)
                        documents[url]=dict(starts=starts,resumes=resumes,source=url,title=a.get('announcementTitle'),digest=feed.evidence.get(url))
                    cluster_docs.append(documents[url])
                total=result.get('totalAnnouncement',0)
                if page*30>=total:break
                if page>=10 or not announcements:raise ValueError('停复牌公告分页不完整，保留未知缺口')
                page+=1
        # A pair can come from one announcement or separate stop/resume announcements.
        starts={d for a in cluster_docs for d in a['starts'] if d<=cluster[0]}
        resumes={d for a in cluster_docs for d in a['resumes'] if d>cluster[-1]}
        if len(starts)!=1 or len(resumes)!=1:continue
        start,resume=next(iter(starts)),next(iter(resumes))
        if bars is not None:
            traded={r['date'] for r in bars if r.get('volume',0)>0}
            if resume not in traded or any(start<=d<resume for d in traded):continue
        stop_doc=next(a for a in cluster_docs if start in a['starts'])
        resume_doc=next(a for a in cluster_docs if resume in a['resumes'])
        matched=[d for d in dates if start<=d<resume]
        if matched:
            confirmed.update(matched)
            evidence.append(dict(start=start,resume=resume,dates=matched,source=resume_doc['source'],start_source=stop_doc['source'],title=resume_doc['title'],digest=resume_doc['digest'],start_digest=stop_doc['digest']))
    return sorted(confirmed),evidence

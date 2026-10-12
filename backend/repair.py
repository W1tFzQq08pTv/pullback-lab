"""Bounded, evidence-backed gap repair. Never insert synthetic suspension candles."""
import copy
import json
import math
from datetime import datetime,timezone
from . import store
from .sources import Feed,verify_suspensions
from .quality import validate,issue

GAPS={'missing','zero_volume'}
REPAIRABLE=GAPS|{'action_unverified','action_dates','share_dates'}

def recent_attempt(snapshot_id,max_age=21600):
    with store.connect() as db:row=db.execute('SELECT * FROM repair_attempts WHERE snapshot_id=?',(snapshot_id,)).fetchone()
    if row and (max_age is None or (datetime.now(timezone.utc)-datetime.fromisoformat(row['attempted'])).total_seconds()<max_age):
        return json.loads(row['result'])
    return None

def valid(row):
    try:
        o,h,l,c,v=(row[k] for k in ('open','high','low','close','volume'))
        return all(isinstance(n,(int,float)) and math.isfinite(n) for n in (o,h,l,c,v)) and min(o,h,l,c)>0 and v>0 and l<=min(o,c)<=max(o,c)<=h
    except (KeyError,TypeError):return False

def repair_snapshot(snapshot,progress=lambda n,m:None,force=False):
    prior=recent_attempt(snapshot['id'])
    if prior and not force:
        return store.latest(prior['snapshot_id']) or snapshot,{**prior,'cached':True}
    payload=copy.deepcopy(snapshot['payload']);symbol=payload.get('symbol','002028.SZ')
    stock=payload.get('stock')
    if stock is None:
        from .stocks import get_stock
        stock=get_stock(symbol)
    original=validate(payload)
    targets=[i for i in original if i['code'] in GAPS and i['severity']=='error']
    report=dict(original_snapshot=snapshot['id'],snapshot_id=snapshot['id'],symbol=symbol,attempted=store.now(),requested=len(targets),filled=[],suspensions=[],failures=[],remaining=0,cached=False)
    feed=Feed(stock,force=True)
    try:
        for key,code in [('bars',symbol),('index','000300.SH')]:
            dates={i['date'] for i in targets if i['symbol']==code}
            if not dates:continue
            feed_symbol=code[-2:].lower()+code[:6]
            progress(15,f'自动修复 {code}：重新检查 {len(dates)} 个缺失交易日')
            candidates={}
            for source in ('tencent','sina'):
                try:
                    rows=[]
                    if source=='tencent':
                        for year in sorted({int(d[:4]) for d in dates}):rows.extend(feed.tencent_bars(feed_symbol,year,payload['end']))
                    else:rows=feed.sina_bars(feed_symbol)
                    for r in rows:
                        if r['date'] in dates and valid(r):candidates.setdefault(r['date'],{}).setdefault(source,[]).append(r)
                except Exception as exc:report['failures'].append(dict(stage=source,symbol=code,message=str(exc)))
            for day,by_source in candidates.items():
                if any(len(rows)>1 for rows in by_source.values()):
                    report['failures'].append(dict(stage='duplicate',symbol=code,date=day,message='补数来源包含重复日期，未采用'));continue
                rows=[rs[0] for rs in by_source.values()]
                if len(rows)>1 and any(abs(rows[0][k]-rows[1][k])>.010001 for k in ('open','high','low','close')):
                    report['failures'].append(dict(stage='conflict',symbol=code,date=day,message='补数来源价格冲突，未采用'));continue
                existing=[r for r in payload[key] if r['date']==day]
                if len(existing)>1 or any(r.get('volume',0)>0 for r in existing):continue
                selected=by_source.get('tencent',by_source.get('sina'))[0]
                payload[key]=[r for r in payload[key] if r['date']!=day]+[selected]
                report['filled'].append(dict(symbol=code,date=day,source=selected['source']))
            from .extra_sources import supplement
            remaining_dates=dates-{r['date'] for r in payload[key] if valid(r)}
            before={r['date'] for r in payload[key] if valid(r)}
            payload[key],extra_issues,reports=supplement(feed,feed_symbol,payload[key],remaining_dates)
            payload.setdefault('source_issues',[]).extend(extra_issues)
            payload.setdefault('source_reports',[]).extend(reports)
            report['failures'].extend(dict(stage=i['code'],symbol=code,date=i['date'],message=i['message']) for i in extra_issues)
            report['filled'].extend(dict(symbol=code,date=r['date'],source=r['source']) for r in payload[key] if r['date'] in remaining_dates-before and valid(r))
            payload[key].sort(key=lambda r:r['date'])
        remaining=[i['date'] for i in validate(payload) if i['symbol']==symbol and i['code'] in GAPS]
        if remaining:
            progress(65,f'正在核验 {len(remaining)} 个缺失日期的停复牌公告')
            try:
                confirmed,evidence=verify_suspensions(feed,remaining,bars=payload['bars'])
                payload['suspensions']=sorted(set(payload.get('suspensions',[]))|set(confirmed))
                known={e['source'] for e in payload.get('suspension_evidence',[])}
                payload.setdefault('suspension_evidence',[]).extend(e for e in evidence if e['source'] not in known)
                report['suspensions']=confirmed
                report['evidence']=evidence
            except Exception as exc:report['failures'].append(dict(stage='announcements',symbol=symbol,message=str(exc)))
        if any(i['code'] in REPAIRABLE-GAPS for i in original):
            progress(80,'重新查询分红送转实施公告；证据不足的事件保留阻断')
            try:payload['actions']=feed.verify_actions(payload['actions'])
            except Exception as exc:report['failures'].append(dict(stage='actions',message=str(exc)))
        report['actions_verified']=sum(e.get('verified',False) for e in payload['actions'])-sum(e.get('verified',False) for e in snapshot['payload']['actions'])
        payload.setdefault('evidence',{}).update(feed.evidence)
        payload['quality']=validate(payload)
        report['remaining']=sum(i['code'] in GAPS and i['severity']=='error' for i in payload['quality'])
        report['other_errors']=sum(i['code'] not in GAPS and i['severity']=='error' for i in payload['quality'])
        if report['filled'] or report['suspensions'] or payload['actions']!=snapshot['payload']['actions'] or payload.get('source_issues')!=snapshot['payload'].get('source_issues'):
            report['snapshot_id']=store.snapshot(payload)
        with store.connect() as db:
            for ident in {snapshot['id'],report['snapshot_id']}:
                db.execute('INSERT OR REPLACE INTO repair_attempts VALUES(?,?,?)',(ident,store.now(),store.dumps(report)))
        progress(90,f'补回 {len(report["filled"])} 根行情，确认 {len(report["suspensions"])} 个停牌日，剩余 {report["remaining"]} 个缺口')
        return store.latest(report['snapshot_id']),report
    finally:feed.close()

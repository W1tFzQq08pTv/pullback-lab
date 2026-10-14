from .logging_setup import log
from datetime import date
from .sources import Feed, cutoff_date, verify_suspensions
from .quality import validate, issue
from . import store

def synchronize(task_id, stock=None, force=False):
    stock=stock or dict(symbol="002028.SZ",code="002028",name="思源电气",org_id="gssz0002028")
    log.info('sync begin task=%s symbol=%s force=%s',task_id,stock['symbol'],force)
    feed=Feed(stock,force)
    def update(n,msg):
        log.info('sync stage task=%s symbol=%s progress=%s message=%s',task_id,stock['symbol'],n,msg)
        store.task_update(task_id,progress=n,message=msg)
    try:
        cutoff=cutoff_date()
        previous=store.latest(symbol=stock['symbol'])
        if previous and previous['payload'].get('cutoff')==cutoff and not force and not any(i['severity']=='error' for i in previous['payload'].get('quality', [])):
            log.info('sync cache hit task=%s symbol=%s snapshot=%s cutoff=%s bars=%s',task_id,stock['symbol'],previous['id'],cutoff,len(previous['payload']['bars']))
            store.task_update(task_id,'completed',100,'当前已收盘区间已缓存，无需重复下载',dict(snapshot_id=previous['id'],cached=True,symbol=stock['symbol']))
            return
        # Refresh current market feeds, including a pre-close cached response.
        # Historical years and announcement archives keep their existing cache policy.
        feed.fresh_market=True
        start=f'{int(cutoff[:4])-11}-01-01'
        update(2,'获取交易日历')
        calendar=[d for d in feed.calendar() if start<=d<=cutoff]
        if not calendar or calendar[-1]<str(date.fromisoformat(cutoff).replace(day=1)):
            raise ValueError('交易日历未覆盖当前月份，不能推断交易日')
        end=calendar[-1]
        result=dict(symbol=stock['symbol'],stock=stock,cutoff=cutoff,start=start,end=end,calendar=calendar,bars=[],index=[],actions=[],suspensions=[],source_issues=[])
        try:
            result['listed']=feed.listing_date()
        except Exception as exc:
            result['source_issues'].append(issue('listing',None,str(exc),stock['symbol']))
        if stock['symbol']!='002028.SZ':
            try:
                if feed.risk_notices():result['source_issues'].append(issue('risk_history',None,'存在历史风险警示变更，需核验逐日交易规则后回测',stock['symbol']))
            except Exception as exc:
                result['source_issues'].append(issue('risk_history',None,f'历史风险警示核验失败：{exc}',stock['symbol']))
        for key,symbol in [('bars',stock['symbol'][-2:].lower()+stock['code']),('index','sh000300')]:
            update(8 if key=='bars' else 40,f'下载并交叉核验 {symbol}')
            secondary=[]
            try:
                secondary=[r for r in feed.sina_bars(symbol) if start<=r['date']<=end]
            except Exception as exc:
                result['source_issues'].append(issue('secondary',None,str(exc), stock['symbol'] if key=='bars' else '000300.SH'))
            all_rows=[]
            for year in range(int(start[:4]),int(end[:4])+1):
                update((10 if key=='bars' else 42)+(year-int(start[:4]))*2, f'{symbol} · {year} 年行情')
                try:
                    rows=feed.tencent_bars(symbol,year,end)
                except Exception as exc:
                    rows=[r for r in secondary if r['date'].startswith(str(year))]
                    result['source_issues'].append(issue('fallback',f'{year}-01-01',f'腾讯失败，采用新浪：{exc}', stock['symbol'] if key=='bars' else '000300.SH','warning'))
                all_rows.extend(r for r in rows if start<=r['date']<=end)
            primary={r['date']:r for r in all_rows}
            for r in secondary:
                old=primary.get(r['date'])
                if old is None:
                    primary[r['date']]=r
                elif any(abs(old[k]-r[k])>.010001 for k in ('open','high','low','close')):
                    from .adjudications import resolve
                    correction = resolve(symbol, old, r)
                    if correction:
                        primary[r['date']] = {**r, 'source':'sina-reviewed'}
                        result.setdefault('corrections', []).append(correction)
                        result['source_issues'].append(issue('resolved_conflict',r['date'],correction['reason'], stock['symbol'] if key=='bars' else '000300.SH','warning'))
                    else:
                        result['source_issues'].append(issue('conflict',r['date'],'腾讯与新浪原始 OHLC 差异超过0.01元', stock['symbol'] if key=='bars' else '000300.SH'))
            # Keep duplicates visible to validation instead of silently discarding provider errors.
            duplicates=[r for j,r in enumerate(all_rows) if r['date'] in {x['date'] for x in all_rows[:j]}]
            result[key]=sorted(list(primary.values())+duplicates,key=lambda r:r['date'])
            from .extra_sources import supplement
            # Preserve previously cached bars if an upstream request failed.
            cached_rows=(previous or {}).get('payload',{}).get(key,[])
            present={r['date'] for r in result[key]}
            result[key].extend(r for r in cached_rows if start<=r['date']<=end and r['date'] not in present)
            needed={d for d in calendar if key=='index' or d>=result.get('listed',start)}-{r['date'] for r in result[key] if r['volume']>0}
            if key=='bars' and needed:
                update(68,'优先核验停复牌公告，减少无效行情补数')
                try:
                    result['suspensions'],result['suspension_evidence']=verify_suspensions(feed,sorted(needed),bars=result['bars'])
                    needed-=set(result['suspensions'])
                except Exception as exc:
                    result['source_issues'].append(issue('suspension_source',None,str(exc),stock['symbol'],'warning'))
            if needed:update(70,f'{symbol}：尝试东方财富 / BaoStock 补齐 {len(needed)} 个缺口')
            result[key],extra_issues,reports=supplement(feed,symbol,result[key],needed)
            result['source_issues'].extend(extra_issues)
            result.setdefault('source_reports',[]).extend(reports)
        missing=sorted({d for d in calendar if d>=result.get('listed',start)}-{r['date'] for r in result['bars'] if r['volume']>0})
        missing=sorted(set(missing)-set(result['suspensions']))
        if missing:
            update(73,'查询缺失日期的停复牌公告证据')
            try:
                confirmed,evidence=verify_suspensions(feed,missing,bars=result['bars'])
                result['suspensions']=sorted(set(result['suspensions'])|set(confirmed))
                result.setdefault('suspension_evidence',[]).extend(evidence)
            except Exception as exc:
                result['source_issues'].append(issue('suspension_source',None,f'停复牌证据获取失败，缺口保持未确认：{exc}',severity='warning'))
        update(76,'核验分红及巨潮资讯实施公告')
        try:
            result['actions']=feed.verify_actions(feed.dividends())
        except Exception as exc:
            result['source_issues'].append(issue('actions_source',None,f'公司行动核验失败：{exc}',stock['symbol']))
        result['actions']=[e for e in result['actions'] if e['date']>=start and e.get('announcement',e['date'])<=end]
        result['evidence']=feed.evidence
        update(94,'检查数据完整性并保存快照')
        result['quality']=validate(result)
        ident=store.snapshot(result)
        log.info('sync saved task=%s symbol=%s snapshot=%s bars=%s index=%s actions=%s source_issues=%s',task_id,stock['symbol'],ident,len(result['bars']),len(result['index']),len(result['actions']),store.dumps(result['source_issues']))
        errors=sum(i['severity']=='error' for i in result['quality'])
        latest=min((max((r['date'] for r in result[key]),default='') for key in ('bars','index')))
        suffix=f'；行情源尚未补齐 {end}，请稍后重试' if latest<end else ''
        store.task_update(task_id,'completed',100,f'已保存 {len(result["bars"])} 根日线；{errors} 项待核验{suffix}',dict(snapshot_id=ident,errors=errors,symbol=stock['symbol']))
    except Exception as exc:
        log.exception('sync failed task=%s symbol=%s',task_id,stock['symbol'])
        store.task_update(task_id,'failed',message=str(exc))
    finally:
        feed.close()

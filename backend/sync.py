from .logging_setup import log
from datetime import date
from .sources import Feed, cutoff_date, verify_suspensions
from .quality import validate, issue
from . import store

def synchronize(task_id, stock=None, force=False, cache_only=False):
    stock=stock or dict(symbol="002028.SZ",code="002028",name="思源电气",org_id="gssz0002028")
    log.info('sync begin task=%s symbol=%s force=%s',task_id,stock['symbol'],force)
    feed=Feed(stock,force,budget_seconds=120 if cache_only else None)
    is_etf=stock.get('asset_type')=='etf'
    is_bj=stock['symbol'].endswith('.BJ')
    def update(n,msg):
        log.info('sync stage task=%s symbol=%s progress=%s message=%s',task_id,stock['symbol'],n,msg)
        store.task_update(task_id,progress=n,message=msg)
    try:
        cutoff=stock.get('cache_cutoff') or cutoff_date()
        previous=store.latest(symbol=stock['symbol'])
        from .bulk_data import cache_current
        if previous and previous['payload'].get('adjustments',{}).get('revision')==1 and cache_current(previous['payload']) and previous['payload'].get('cutoff')==cutoff and not force and not any(i['severity']=='error' for i in previous['payload'].get('quality', [])):
            log.info('sync cache hit task=%s symbol=%s snapshot=%s cutoff=%s bars=%s',task_id,stock['symbol'],previous['id'],cutoff,len(previous['payload']['bars']))
            store.task_update(task_id,'completed',100,'当前已收盘区间已缓存，无需重复下载',dict(snapshot_id=previous['id'],cached=True,symbol=stock['symbol']))
            return
        # Refresh current market feeds, including a pre-close cached response.
        # Historical years and announcement archives keep their existing cache policy.
        feed.fresh_market=not cache_only
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
        if stock['symbol']!='002028.SZ' and not is_etf:
            try:
                if feed.risk_notices():result['source_issues'].append(issue('risk_history',None,'存在历史风险警示变更，需核验逐日交易规则后回测',stock['symbol']))
            except Exception as exc:
                result['source_issues'].append(issue('risk_history',None,f'历史风险警示核验失败：{exc}',stock['symbol']))
        for key,symbol in [('bars',stock['symbol'][-2:].lower()+stock['code']),('index','sh000300')]:
            update(8 if key=='bars' else 40,f'下载并交叉核验 {symbol}')
            from .bulk_data import bars as bulk_bars
            bulk=[];manifest=None
            try:
                bulk,manifest=bulk_bars(symbol,start,end,etf=is_etf and key=='bars')
            except Exception as exc:
                result['source_issues'].append(issue('bulk_source',None,f'整包读取失败，回退接口：{exc}',stock['symbol'] if key=='bars' else '000300.SH','warning'))
            if bulk:
                update(10 if key=='bars' else 42,f'{symbol} · 复用整包 {len(bulk)} 条，补增量与缺口')
                result.setdefault('bulk_sources',{})[symbol]=manifest
                log.info('sync bulk hit task=%s symbol=%s rows=%s sha256=%s',task_id,symbol,len(bulk),manifest['sha256'])
                reviewed={r['date']:r for r in (previous or {}).get('payload',{}).get(key,[]) if r.get('source')=='sina-reviewed'}
                all_rows=[reviewed.get(r['date'],r) for r in bulk]
                try:
                    from .bulk_data import crosscheck
                    check=crosscheck(feed,symbol,bulk,manifest,etf=is_etf and key=='bars')
                    result.setdefault('bulk_checks',{})[symbol]=check
                    for day in check['conflicts']:
                        if day not in reviewed:
                            result['source_issues'].append(issue('conflict',day,'通达信整包与新浪历史OHLC不一致，保留待核验',stock['symbol'] if key=='bars' else '000300.SH'))
                except Exception as exc:
                    result['source_issues'].append(issue('bulk_unverified',None,f'整包历史交叉核验未完成：{exc}',stock['symbol'] if key=='bars' else '000300.SH'))

                present={r['date'] for r in all_rows}
                all_rows.extend(r for r in (previous or {}).get('payload',{}).get(key,[]) if start<=r['date']<=end and r['date'] not in present)
                lower=max(start,result.get('listed',start)) if key=='bars' else start
                if key=='bars' and is_etf:
                    lower=max(lower,bulk[0]['date']);result['listed']=lower;result['observed_start']=lower
                present={r['date'] for r in all_rows if r['volume']>0}
                gaps={d for d in calendar if lower<=d<=end and d not in present}
                gaps-=set((previous or {}).get('payload',{}).get('suspensions',[])) if key=='bars' else set()
                # Recent overlap verifies scale and raw-price agreement even with no gaps.
                wanted=gaps|{r['date'] for r in bulk[-10:]}
                wanted|={i['date'] for i in (previous or {}).get('payload',{}).get('quality',[]) if i.get('code') in ('conflict','price_jump') and i.get('date') and lower<=i['date']<=end and i.get('symbol')==(stock['symbol'] if key=='bars' else '000300.SH')}
                secondary=[]
                for year in sorted({d[:4] for d in wanted}):
                    window=sorted(d for d in wanted if d.startswith(year))
                    try:secondary.extend(feed.tencent_range(symbol,window[0],window[-1]))
                    except Exception as exc:
                        result['source_issues'].append(issue('bulk_increment',window[-1],f'整包已保留，接口补数失败：{exc}',stock['symbol'] if key=='bars' else '000300.SH','warning'))
                if not secondary:
                    try:secondary=[r for r in feed.sina_bars(symbol) if r['date'] in wanted]
                    except Exception as exc:
                        log.warning('bulk overlap fallback failed symbol=%s error=%s',symbol,exc)
                if not any(r['date'] in present for r in secondary):
                    result['source_issues'].append(issue('bulk_unverified',None,'整包行情尚未完成接口重叠核验',stock['symbol'] if key=='bars' else '000300.SH'))
            else:
                secondary=[]
                try:
                    secondary=[r for r in feed.sina_bars(symbol) if start<=r['date']<=end]
                except Exception as exc:
                    result['source_issues'].append(issue('secondary',None,str(exc), stock['symbol'] if key=='bars' else '000300.SH'))
                all_rows=[]
                lower=max(start,result.get('listed',start)) if key=='bars' else start
                if key=='bars' and is_etf and secondary:
                    lower=max(lower,secondary[0]['date'])
                    result['listed']=lower
                    result['observed_start']=lower
                for year in range(int(lower[:4]),int(end[:4])+1):
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
                elif any(abs(old[k]-r[k])>(.001001 if is_etf and key=='bars' else .010001) for k in ('open','high','low','close')):
                    from .adjudications import resolve
                    correction = resolve(symbol, old, r) if not bulk else None
                    if correction:
                        primary[r['date']] = {**r, 'source':'sina-reviewed'}
                        result.setdefault('corrections', []).append(correction)
                        result['source_issues'].append(issue('resolved_conflict',r['date'],correction['reason'], stock['symbol'] if key=='bars' else '000300.SH','warning'))
                    else:
                        precision='0.001' if is_etf and key=='bars' else '0.01'
                        result['source_issues'].append(issue('conflict',r['date'],f'{"整包与腾讯" if bulk else "腾讯与新浪"}原始 OHLC 差异超过{precision}元', stock['symbol'] if key=='bars' else '000300.SH'))
            # Keep duplicates visible to validation instead of silently discarding provider errors.
            seen=set();duplicates=[]
            for r in all_rows:
                if r['date'] in seen:duplicates.append(r)
                seen.add(r['date'])
            result[key]=sorted(list(primary.values())+duplicates,key=lambda r:r['date'])
            from .extra_sources import supplement
            # Preserve previously cached bars if an upstream request failed.
            cached_rows=(previous or {}).get('payload',{}).get(key,[])
            present={r['date'] for r in result[key]}
            result[key].extend(r for r in cached_rows if start<=r['date']<=end and r['date'] not in present)
            result[key].sort(key=lambda r:r['date'])
            if key=='bars' and result.get('listed'):
                result[key]=[r for r in result[key] if r['date']>=result['listed']]
            needed={d for d in calendar if key=='index' or d>=result.get('listed',start)}-{r['date'] for r in result[key] if r['volume']>0}
            if key=='bars' and needed and not is_etf:
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
        if missing and not is_etf:
            update(73,'查询缺失日期的停复牌公告证据')
            try:
                confirmed,evidence=verify_suspensions(feed,missing,bars=result['bars'])
                result['suspensions']=sorted(set(result['suspensions'])|set(confirmed))
                result.setdefault('suspension_evidence',[]).extend(evidence)
            except Exception as exc:
                result['source_issues'].append(issue('suspension_source',None,f'停复牌证据获取失败，缺口保持未确认：{exc}',severity='warning'))
        update(76,'核验分红及巨潮资讯实施公告')
        try:
            if is_etf:
                from .instruments import fund_events
                result['actions'],result['fund_events_source']=fund_events(feed)
                result['source_issues'].append(issue('fund_metadata',None,'ETF分红、折算及逐品种交易规则待核验；当前仅支持数据缓存',stock['symbol']))
            else:result['actions']=feed.verify_actions(feed.dividends())
        except Exception as exc:
            result['source_issues'].append(issue('actions_source',None,f'公司行动核验失败：{exc}',stock['symbol']))
        result['actions']=[e for e in result['actions'] if e['date']>=start and e.get('announcement',e['date'])<=end]
        if is_bj:
            result['source_issues'].append(issue('bse_history',None,'北交所上市前市场规则、历史公司行动及费用模型待核验；当前仅支持数据缓存',stock['symbol']))
        update(88,'获取复权因子与前复权行情；成交记账保留真实价格')
        try:
            from .adjustments import collect
            result['adjustments']=collect(feed,result)
            log.info('adjustments saved symbol=%s factors=%s bars=%s basis=%s',stock['symbol'],len(result['adjustments']['factors']),len(result['adjustments']['bars']),end)
        except Exception as exc:
            result['adjustments']=dict(revision=1,status='unavailable',message=str(exc),basis=end)
            log.warning('adjusted quote unavailable symbol=%s error=%s; raw accounting retained',stock['symbol'],exc)
        result['evidence']=feed.evidence
        update(94,'检查数据完整性并保存快照')
        result['quality']=validate(result)
        ident=store.snapshot(result)
        log.info('sync saved task=%s symbol=%s snapshot=%s bars=%s index=%s actions=%s source_issues=%s',task_id,stock['symbol'],ident,len(result['bars']),len(result['index']),len(result['actions']),store.dumps(result['source_issues']))
        errors=sum(i['severity']=='error' for i in result['quality'])
        latest=min((max((r['date'] for r in result[key]),default='') for key in ('bars','index')))
        suffix=f'；行情截至 {latest}，最新交易日 {end} 待补齐' if latest<end else ''
        bulk_count=sum(r.get('source')=='tdx-bulk' for r in result['bars'])
        bulk_note=f'；整包复用 {bulk_count} 条' if result.get('bulk_sources') else ''
        store.task_update(task_id,'completed',100,f'已保存 {len(result["bars"])} 条日线；{errors} 项待核验{bulk_note}{suffix}',dict(snapshot_id=ident,errors=errors,symbol=stock['symbol']))
    except Exception as exc:
        log.exception('sync failed task=%s symbol=%s',task_id,stock['symbol'])
        store.task_update(task_id,'failed',message=str(exc))
    finally:
        feed.close()

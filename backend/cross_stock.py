"""Frozen-parameter cross-stock evaluation, with checkpointed public-data acquisition."""
import argparse
import hashlib
import html
import json
import statistics
import time
import uuid
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import date
from pathlib import Path
from . import store
from .stocks import directory
from .sync import synchronize
from .quality import validate
from .fallback import prepare
from .models import Parameters
from .strategies import multi_backtest

# Fixed before outcomes: a broad, discretionary main-board sector sample; not a historical index universe.
SYMBOLS='601138.SH 002028.SZ 002475.SZ 000001.SZ 600036.SH 601398.SH 601318.SH 600030.SH 600519.SH 000858.SZ 600600.SH 600887.SH 000333.SZ 000651.SZ 600690.SH 002415.SZ 000725.SZ 600104.SH 002594.SZ 601633.SH 600276.SH 000538.SZ 600436.SH 601088.SH 600900.SH 600028.SH 601857.SH 600019.SH 600309.SH 601899.SH 600585.SH 000002.SZ 600048.SH 601668.SH 600050.SH 600941.SH 601012.SH 600438.SH 002460.SZ 002714.SZ'.split()

def acquire(symbol,stock):
    prior=store.latest(symbol=symbol)
    if prior and prior['payload']['end']>='2026-10-12':return dict(symbol=symbol,source='cache',snapshot_id=prior['id'])
    if stock is None:return dict(symbol=symbol,error='目录中不存在')
    ident=uuid.uuid4().hex
    with store.connect() as db:db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(ident,'cross_stock_sync','queued',0,symbol,store.now(),None))
    synchronize(ident,stock)
    with store.connect() as db:r=dict(db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())
    return dict(symbol=symbol,source='sync',task_id=ident,status=r['status'],message=r['message'])

def evaluate(symbol,profile,end):
    s=store.latest(symbol=symbol)
    if not s:return dict(symbol=symbol,status='blocked',issues=[dict(message='未取得快照')])
    payload=s['payload']; payload={**payload,'quality':validate(payload)}
    p=Parameters(symbol=symbol,strategies=['trend_pullback','martin_daily'],snapshot_id=s['id'],start=date(2019,6,20),end=date.fromisoformat(end),time_range='custom',**profile['params'])
    _,p,fallback,issues=prepare(payload,p)
    base=dict(symbol=symbol,name=payload.get('stock',{}).get('name',symbol),snapshot_id=s['id'])
    if issues:return dict(**base,status='blocked',issues=issues)
    result=multi_backtest(payload,p)
    return dict(**base,status='completed',start=str(p.start),end=str(p.end),aligned=str(p.start)=='2019-06-20',fallback=fallback,params=p.model_dump(mode='json'),metrics={k:v['book']['metrics'] for k,v in result['variants'].items()},benchmark=result['benchmark']['metrics'])

def summarize(rows):
    output={}
    for strategy in ('trend_pullback','martin_daily'):
        metrics=[r['metrics'][strategy] for r in rows]
        returns=[r['total_return'] for r in metrics]
        output[strategy]=dict(n=len(rows),positive=sum(x>0 for x in returns),outperform=sum(r['metrics'][strategy]['total_return']>r['benchmark']['total_return'] for r in rows),no_trades=sum(m['trade_count']==0 for m in metrics),median_return=statistics.median(returns) if returns else None,mean_return=statistics.mean(returns) if returns else None,median_drawdown=statistics.median(m['max_drawdown'] for m in metrics) if metrics else None,worst_drawdown=min((m['max_drawdown'] for m in metrics),default=None))
    return output

def common_window(report):
    # Eligibility depends only on data coverage, never on returns.
    rows=[r for r in report['rows'] if r['status']=='completed' and r['symbol']!='601138.SH' and (date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days>=365]
    if not rows:return None
    start=max(r['start'] for r in rows);end=min(r['end'] for r in rows);results=[]
    for r in rows:
        snapshot=store.latest(ident=r['snapshot_id']);payload=snapshot['payload']
        p=Parameters(**{**r['params'],'start':start,'end':end,'time_range':'custom','allow_suffix':False})
        _,p,_,issues=prepare({**payload,'quality':validate(payload)},p)
        if issues:raise ValueError('共同区间校验失败：'+store.dumps(issues))
        out=multi_backtest(payload,p)
        results.append(dict(symbol=r['symbol'],name=r['name'],snapshot_id=r['snapshot_id'],status='completed',start=start,end=end,aligned=True,params=p.model_dump(mode='json'),metrics={k:v['book']['metrics'] for k,v in out['variants'].items()},benchmark=out['benchmark']['metrics']))
    return dict(start=start,end=end,rows=results,summary=summarize(results),note='仅纳入至少一年有效数据的非调参股票；按数据可用性取交集起点，所有账户重置为10万元，参数仍冻结，不按结果选区间。')

def render(report,output):
    def pct(v):return '—' if v is None else f'{v*100:.2f}%'
    rows=[]
    for r in report['rows']:
        if r['status']!='completed':continue
        cells=[r.get('name',r['symbol']),r['symbol'],r['start']+' → '+r['end'],'调参原股' if r['symbol']=='601138.SH' else '同区间' if r['aligned'] else ('缩短·不足一年' if (date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days<365 else '缩短区间'),pct(r['benchmark']['total_return'])]
        for strategy in ('trend_pullback','martin_daily'):
            m=r['metrics'][strategy];cells.extend([pct(m['total_return']),pct(m['max_drawdown']),str(m['trade_count']), '是' if m['total_return']>r['benchmark']['total_return'] else '否'])
        rows.append('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in cells)+'</tr>')
    headers=['名称','代码','回测区间','分组','买入持有','SMA收益','SMA回撤','SMA成交','SMA跑赢','Martin收益','Martin回撤','Martin成交','Martin跑赢']
    blocked=['<li>'+html.escape(r.get('name',r['symbol'])+' '+r['symbol']+'：'+'；'.join(sorted({i.get('code','')+' '+i['message'] for i in r['issues']})))+'</li>' for r in report['rows'] if r['status']=='blocked']
    summaries=[]
    for group,label in [('aligned','同区间迁移样本'),('shortened','缩短区间样本')]:
        for strategy,m in report['summary'][group].items():
            summaries.append(f'<p>{label} · {strategy}：{m["n"]} 只，盈利 {m["positive"]}，跑赢买入持有 {m["outperform"]}，零成交 {m["no_trades"]}；收益中位数 {pct(m["median_return"])}，回撤中位数 {pct(m["median_drawdown"])}，最差回撤 {pct(m["worst_drawdown"])}。</p>')
    page='<!doctype html><meta charset="utf-8"><title>固定参数跨股票验证</title><style>body{font:15px/1.65 system-ui;margin:40px;color:#17212b}h1{font-size:28px}table{border-collapse:collapse;white-space:nowrap;font-variant-numeric:tabular-nums}td,th{padding:9px 12px;border-bottom:1px solid #ddd;text-align:right}th{background:#f1f5f8}td:first-child{text-align:left}.table{overflow:auto}pre{white-space:pre-wrap;background:#f4f6f8;padding:16px}li{margin:12px 0}</style><h1>工业富联最优参数：跨股票固定验证</h1><p>'+html.escape(report['note'])+'</p><p>目标区间：'+report['start']+' 至 '+report['end']+'。资金 10 万元，费用和成交约束不变。未通过质量校验的标的不计算收益，不用示例数据替代。所有参数在结果产生前固定；这属于跨股票迁移检查，不是未来时间上的样本外验证。</p>'+''.join(summaries)+'<h2>逐股结果</h2><div class="table"><table><tr>'+''.join('<th>'+x+'</th>' for x in headers)+'</tr>'+''.join(rows)+'</table></div><h2>未通过校验（'+str(report['blocked'])+' 只）</h2><ul>'+''.join(blocked)+'</ul><h2>冻结参数</h2><pre>'+html.escape(json.dumps(report['profile'],ensure_ascii=False,indent=2))+'</pre><p>原始记录：report.json；数据快照、失败原因、下载状态和参数均保留供复核。</p>'
    if report.get('common_window'):
        common=report['common_window'];folder=output/'common';folder.mkdir(exist_ok=True)
        render({**report,'common_window':None,'start':common['start'],'end':common['end'],'rows':common['rows'],'blocked':0,'note':report['note']+' '+common['note'],'summary':dict(aligned=common['summary'],shortened=summarize([]))},folder)
        page=page.replace('<h2>逐股结果</h2>','<p><a href="common/report.html">查看至少一年有效数据股票的共同区间复测（全部重置资金）</a></p><h2>逐股结果</h2>')
    (output/'report.html').write_text(page)

def main(workers,output):
    output.mkdir(parents=True,exist_ok=True);t=time.perf_counter()
    profile=json.loads(Path(__file__).with_name('strategy_defaults.json').read_text())['601138.SH']
    manifest=dict(created=store.now(),symbols=SYMBOLS,profile=profile,end='2026-10-12',start='2019-06-20',note='固定工业富联最优参数，未再调参；40只主板跨行业便利样本，含当前存续和人工选择偏差，不代表全A。工业富联单列，不纳入迁移汇总。独立账户，不是组合收益。缩短区间单列。')
    (output/'manifest.json').write_text(store.dumps(manifest))
    stocks={s['symbol']:s for s in directory()};rows=[];acquisitions=[]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures={executor.submit(acquire,s,stocks.get(s)):s for s in SYMBOLS}
        for future in as_completed(futures):
            symbol=futures[future]
            try:
                acquisition=future.result();row=evaluate(symbol,profile,manifest['end'])
            except Exception as exc:
                acquisition=dict(symbol=symbol,error=str(exc));row=dict(symbol=symbol,status='blocked',issues=[dict(message=str(exc))])
            acquisitions.append(acquisition);rows.append(row)
            (output/'checkpoint.json').write_text(store.dumps(dict(rows=rows,acquisitions=acquisitions)))
            print(store.dumps(dict(done=len(rows),total=len(SYMBOLS),symbol=symbol,status=row['status'],start=row.get('start'),seconds=round(time.perf_counter()-t,1))),flush=True)
    transfer=[r for r in rows if r['status']=='completed' and r['symbol']!='601138.SH']
    report=dict(**manifest,rows=sorted(rows,key=lambda r:r['symbol']),acquisitions=acquisitions,seconds=round(time.perf_counter()-t,2),summary=dict(aligned=summarize([r for r in transfer if r['aligned']]),shortened=summarize([r for r in transfer if not r['aligned']]),all_valid=summarize(transfer)),blocked=sum(r['status']=='blocked' for r in rows))
    report['common_window']=common_window(report)
    report['checksum']=hashlib.sha256(store.dumps(report).encode()).hexdigest();(output/'report.json').write_text(store.dumps(report));render(report,output);print(store.dumps(report['summary']),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=3);parser.add_argument('--output',default='data/cross-stock/industrial-defaults-v1');a=parser.parse_args();main(max(1,min(a.workers,3)),Path(a.output))

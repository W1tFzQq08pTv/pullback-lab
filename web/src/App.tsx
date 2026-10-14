import {FormulaInfo,FormulaLabel} from './FormulaInfo';
import {StrategyInfo} from './StrategyInfo';
import {notify,useFeedback} from './Toast';
import {WorkflowProgress} from './WorkflowProgress';
import {Icon} from './Icon';
import {OptimizationPanel} from './OptimizationPanel';
import {StrategyComparison} from './StrategyComparison';
import {strategyNames,type StrategyId} from './types';
import {PoolResearch} from './PoolResearch';
import {LatestSignal} from './LatestSignal';
import {Info} from './Info';
import {useEffect,useMemo,useRef,useState} from 'react';
import {api,num,pct,valueTone,type Overview,type Params,type Task,type Run,type RunHead,type Row,type Issue,type Stock,type RepairReport,type SourceReport} from './types';
import {Parameters} from './Parameters';
import {Charts,type ChartReturn} from './Charts';
import {Metrics,Results} from './Results';
import {Modal} from './Modal';
import {StockPicker} from './StockPicker';
export default function App(){
 const [symbol,setSymbol]=useState(()=>localStorage.getItem('pullback.symbol')||'');
 const current=useRef(symbol),sequence=useRef(0);
 const [overview,setOverview]=useState<Overview|null>(null),[params,setParams]=useState<Params|null>(null),[bars,setBars]=useState<Row[]>([]),[issues,setIssues]=useState<Issue[]>([]),[actions,setActions]=useState<Row[]>([]),[history,setHistory]=useState<RunHead[]>([]),[savedRun,setRun]=useState<Run|null>(null),[taskId,setTaskId]=useState<string|null>(null),[task,setTask]=useState<Task|null>(null),[error,setError]=useFeedback(),[sending,setSending]=useState(false),[loading,setLoading]=useState(true);
 // A result can be reopened or reused without changing its id.
 const [intervalReturn,setIntervalReturn]=useState<ChartReturn|null>(null);
 const [rangeRevision,setRangeRevision]=useState(0);
 const [chartParams,setChartParams]=useState<Params|null>(null);
 function showRun(value:Run|null,configured?:Params){setRun(value);setChartParams(configured|| (value?{...value.params,start:value.result.fallback?.requested_start||value.params.start,end:value.result.fallback?.requested_end||value.result.data_coverage?.requested_end||value.params.end}:null));setRangeRevision(n=>n+1);}
 const [workflowOpen,setWorkflowOpen]=useState(false);
 useEffect(()=>{if(task?.kind==='workflow')setWorkflowOpen(true);},[task?.id]);
 const [sourceReports,setSourceReports]=useState<SourceReport[]>([]);
 const [repair,setRepair]=useState<RepairReport|null>(null);
 const [modal,setModal]=useState<'stock'|'settings'|'sync'|'research'|null>(null),[draft,setDraft]=useState<Params|null>(null),[force,setForce]=useState(false);
 async function refresh(initial=false,applyProfile=false){
  const target=current.current,version=++sequence.current,query='?symbol='+encodeURIComponent(target);
  const o=await api<Overview>('/overview'+query);
  const snapshot=o.snapshot?'&snapshot_id='+o.snapshot.id:'';
  const [b,q,h]=await Promise.all([api<Row[]>('/bars'+query+snapshot),api<{issues:Issue[];actions:Row[];repair?:RepairReport;source_reports?:SourceReport[]}>('/quality'+query+snapshot),api<RunHead[]>('/backtests'+query)]);
  const r=initial&&h.length?await api<Run>('/backtests/'+h[0].id):null;
  if(version!==sequence.current||target!==current.current)return;
  setSourceReports(q.source_reports||[]);setOverview(o);setRepair(q.repair||null);setBars(b);setIssues(q.issues);setActions(q.actions);setHistory(h);
  if(initial){let saved:Params|null=null;try{const raw=localStorage.getItem('pullback.params.'+target);saved=raw?JSON.parse(raw):null;}catch{}let next:Params=saved?.symbol===target?{...o.defaults,...saved,time_range:saved.time_range||'all'}:r?{...o.defaults,...r.params,time_range:'all',symbol:target,snapshot_id:o.snapshot?.id||null}:o.defaults;if(!saved?.strategies)next={...next,strategies:['trend_pullback','martin_daily']};const profile=o.defaults_profile;if(profile&&(applyProfile||next.defaults_revision!==profile.revision)){next={...next,...profile.params,defaults_revision:profile.revision};localStorage.setItem('pullback.params.'+target,JSON.stringify(next));}setParams(next);showRun(r,next);if(o.active_task)setTaskId(o.active_task);}
  else setParams(p=>{let next=p?{...p,symbol:target,snapshot_id:o.snapshot?.id||null}:o.defaults;const profile=o.defaults_profile;if(profile&&(applyProfile||next.defaults_revision!==profile.revision)){next={...next,...profile.params,defaults_revision:profile.revision};localStorage.setItem('pullback.params.'+target,JSON.stringify(next));}return next;});
  setLoading(false);
 }
 useEffect(()=>{current.current=symbol;if(!symbol){setLoading(false);return;}localStorage.setItem('pullback.symbol',symbol);setLoading(true);setSourceReports([]);setOverview(null);setRepair(null);setRun(null);setParams(null);setBars([]);setIssues([]);setActions([]);setHistory([]);setError('');setTask(null);refresh(true).catch(e=>{if(current.current===symbol){setError(e.message);setLoading(false);}});},[symbol]);
 useEffect(()=>{if(!taskId)return;let alive=true;let timer:ReturnType<typeof setTimeout>;
  async function poll(){try{
   const t=await api<Task>('/tasks/'+taskId);if(!alive)return;setTask(t);
   if(['completed','failed','cancelled'].includes(t.status)){
    if(t.status==='failed'&&t.kind!=='workflow')setError(t.message);
    await refresh(false,t.status==='completed'&&['optimization','workflow'].includes(t.kind)&&t.result?.symbol===current.current);
    if(!alive)return;
    if(t.result?.run_id){const r=await api<Run>('/backtests/'+t.result.run_id);if(!alive)return;if((r.params.symbol||'002028.SZ')===current.current){showRun(r,t.result.request_params||t.result.params||params||undefined);if(t.kind==='workflow'&&t.result.params){const next={...t.result.params,defaults_revision:t.result.optimization_id};setParams(next);localStorage.setItem('pullback.params.'+current.current,JSON.stringify(next));}}}
    notify(t.message,t.status==='completed'?'success':t.status==='failed'&&t.result?.reason!=='insufficient_history'?'error':'info');setTaskId(null);
   }else timer=setTimeout(poll,1000);
  }catch(e){if(alive){setError((e as Error).message);timer=setTimeout(poll,3000);}}}
  poll();return()=>{alive=false;clearTimeout(timer);};},[taskId]);
 async function start(path:string,body:unknown){setPanel(null);setSending(true);setError('');try{const r=await api<{task_id:string;reused?:boolean;status?:string}>(path,body);setTask(path==='/workflows'?{id:r.task_id,kind:'workflow',status:'queued',progress:0,message:r.reused?'已连接已有任务':'已排队，等待执行',result:{request_params:body as Params,symbol,step:0,steps:[{id:'sync',label:'更新行情',status:'pending'},{id:'repair',label:'补齐校验',status:'pending'},{id:'optimize',label:'参数寻优',status:'pending'},{id:'backtest',label:'自动回测',status:'pending'}]}}:null);setTaskId(r.task_id);if(r.reused)notify('已连接已有任务，无需重复启动');setModal(null);}catch(e){setError((e as Error).message);setModal(null);}finally{setSending(false);}}
 async function select(id:string){try{const target=current.current,r=await api<Run>('/backtests/'+id);if(target!==current.current)return;const next={...r.params,start:r.result.fallback?.requested_start||r.params.start,end:r.result.fallback?.requested_end||r.result.data_coverage?.requested_end||r.params.end,time_range:r.params.time_range||'custom',symbol:target,snapshot_id:r.snapshot_id};showRun(r,next);setParams(next);setError('');}catch(e){setError((e as Error).message);}}
 function choose(stock:Stock){if(stock.symbol!==symbol){setTaskId(null);setTask(null);setWorkflowOpen(false);}current.current=stock.symbol;setSymbol(stock.symbol);setModal(null);}
 useEffect(()=>{document.title=`9744EAA7 · ${overview?.stock.symbol===symbol?overview.stock.name:symbol}`; },[symbol,overview?.stock.name,overview?.stock.symbol]);
 const [viewStrategy,setViewStrategy]=useState<StrategyId>('trend_pullback');
 const activeStrategy=savedRun?.result.variants?.[viewStrategy]?viewStrategy:(savedRun?.result.strategy_id||params?.strategies?.[0]||'trend_pullback');
 const signalParams=useMemo(()=>params?{...params,strategies:[activeStrategy]}:null,[params,activeStrategy]);
 const variant=savedRun?.result.variants?.[activeStrategy];
 const run= savedRun&&variant?{...savedRun,result:{...savedRun.result,strategy_id:activeStrategy,strategy_name:variant.name,strategy:variant.book,chart:variant.chart}}:savedRun;
 const [panel,setPanel]=useState<'signal'|'optimize'|'data'|'compare'|'metrics'|'tools'|'records'|null>(null);
 const busy=!!taskId||sending;
 const closePanel=()=>setPanel(null);
 const resultProps={sourceReports,run,issues,actions,history,onSelect:select};
 const panelTitles={signal:'下一交易日信号',optimize:'个股寻优',data:'数据检查与同步',compare:'策略对比',metrics:'完整回测指标',tools:'研究工具',records:'交易明细与历史'};

 if(!symbol)return <><header className="app-header"><div className="brand"><h1>9744EAA7</h1></div></header><main className="stock-welcome"><h2>从一只股票开始</h2><p>选择股票后，查看行情、研究策略与回测结果。</p><button className="primary" onClick={()=>setModal('stock')}>选择股票</button></main>{modal==='stock'?<StockPicker onClose={()=>setModal(null)} onSelect={choose}/>:null}</>;
 return <><header className="app-header"><div className="brand"><h1>9744EAA7</h1><button className="stock-switch" onClick={()=>setModal('stock')} aria-label="选择股票">{overview?.stock.name||symbol}<span>{overview?.stock.symbol||''}</span></button></div><div className="header-actions"><button onClick={()=>setPanel('tools')}>研究工具{issues.some(i=>i.severity==='error')?<span className="count">{issues.filter(i=>i.severity==='error').length}</span>:null} <Icon name="grid"/></button></div></header>
 <main className="research-workspace">{task?.kind==='workflow'?null:taskId?<div role="status" className="notice"><span>{task?.message||'任务启动中…'}</span><progress max="100" value={task?.progress||1}/></div>:null}
 <div className="result-title"><div><div className="heading-info"><h2>策略回测</h2><Info label="回测说明">{`个人投资者税后口径。历史回测绑定原股票与快照。一键研究自动更新数据、补齐校验、寻找累计收益最高的网格参数并回测；相同条件复用结果，可随时终止。${run?` 当前快照：${run.snapshot_id}。`:''}`}</Info></div><p className="muted">{run?`${run.params.start} — ${run.params.end}`:loading?'正在读取本地数据…':overview?.snapshot?'一键更新行情、寻优并回测':'点击一键研究，自动下载行情并回测'}</p></div><div className="strategy-selector"><div className="segmented" role="group" aria-label="查看策略">{(savedRun?.result.variants?(savedRun.params.strategies||Object.keys(savedRun.result.variants)) as StrategyId[]:[activeStrategy]).map(id=><span className="strategy-choice" key={id}><button aria-pressed={id===activeStrategy} onClick={()=>setViewStrategy(id)}>{id==='trend_pullback'?'趋势回调（SMA）':'Martin 日线版'}</button><StrategyInfo id={id}/></span>)}</div><button className="text-action" disabled={!savedRun} onClick={()=>setPanel('compare')}>策略对比 ›</button>{run?.result.adaptation?.adapted?<span className="history-adaptation">短历史适配<Info label="短历史适配说明">{run.result.adaptation.note}</Info></span>:null}</div><div className="toolbar"><button disabled={!params||busy} onClick={()=>{setDraft({...params!});setModal('settings');}}><Icon name="sliders"/>参数设置</button><button className="primary" disabled={loading||!params||(busy&&task?.kind!=='workflow')} onClick={()=>busy?setWorkflowOpen(true):start('/workflows',params)}>{busy?<><span className="loading-spinner" aria-hidden="true"/>查看进度</>:<><Icon name="play"/>一键研究</>}</button></div></div>



 <div className="metric-overview"><Metrics run={run} compact loading={loading} intervalReturn={intervalReturn}/><LatestSignal params={signalParams} snapshot={overview?.snapshot?.id} loading={loading} compact onDetails={()=>setPanel('signal')}/><button className="text-action" onClick={()=>setPanel('metrics')}>更多指标 ›</button></div>
 <Charts onIntervalReturn={setIntervalReturn} configuredParams={chartParams} rangeRevision={rangeRevision} zoneGuide={run?.result.fallback?<div className="research-zone-guide" aria-label="行情区间释义"><span><i className="zone-swatch zone-history"/>历史行情 · 仅供查看</span><span><i className="zone-swatch zone-warmup"/>预热区间 · 不计收益</span><span><i className="zone-swatch zone-backtest"/>回测区间 · 统计收益与成交</span><Info label="区间详情">{`行情图保留全部缓存。${run.result.fallback.reason==='warmup'?'起点已按策略预热需求调整。':`因早期数据缺口，从 ${run.result.fallback.data_start} 重新预热。`}实际回测：${run.params.start} — ${run.params.end}。区间外行情不计入本次收益与成交。`}</Info></div>:null} run={run} bars={bars} snapshotId={overview?.snapshot?.id} loading={loading}/>
 <footer className="workspace-footer"><button className="text-action" onClick={()=>setPanel('records')}>交易明细与历史 <span className="record-count">{run?`${run.result.strategy.metrics.trade_count} 笔成交`:''}</span> ›</button><Info label="使用说明">{(run?.result.data_coverage?run.result.data_coverage.message+'。当前为历史回测，不代表已覆盖最新行情。':'')+'保守日线成交模拟；无法证明实际排队成交或精确券商清算。公司行动、行情缺口或板块规则未核实时，正式回测会被阻止。单股样本内最优不代表未来收益。'}</Info><span>{loading?'正在读取本地行情…':run?.result.data_coverage?`行情截至 ${run.result.data_coverage.latest} · 最新待补齐`:`个股行情截至 ${overview?.snapshot?.end||'尚未同步'}`}</span></footer></main>
 {workflowOpen&&task?.kind==='workflow'?<Modal title="一键研究" className="workflow-modal" onClose={()=>setWorkflowOpen(false)}><WorkflowProgress key={task.id} task={task} retryDisabled={busy||!params} onRetry={()=>start('/workflows',task.result?.request_params||params)} resultLoading={task.status==='completed'&&busy} onUpdate={setTask} onDismiss={()=>setWorkflowOpen(false)}/></Modal>:null}
 {panel?<Modal title={panelTitles[panel]} className="detail-modal" onClose={closePanel}>
 {panel==='tools'?<nav className="research-tool-menu" aria-label="研究工具">{task?.kind==='workflow'?<button onClick={()=>{closePanel();setWorkflowOpen(true);}}>最近研究进度</button>:null}<button disabled={busy||loading||!overview?.snapshot||!params} onClick={()=>start('/backtests',params)}>仅按当前参数回测</button><button onClick={()=>setPanel('metrics')}>完整回测指标</button><button onClick={()=>setPanel('signal')}>下一交易日信号</button><button onClick={()=>setPanel('optimize')}>个股寻优{overview?.defaults_profile?<span className="saved-dot" aria-label="已有保存参数"/>:null}</button><button onClick={()=>setPanel('data')}>数据检查{issues.some(i=>i.severity==='error')?<span className="count">{issues.filter(i=>i.severity==='error').length}</span>:null}</button><span className="workspace-context">{params?.time_range==='custom'?`${params.start} — ${params.end}`:'全部可回测数据'} · {(params?.strategies||['trend_pullback']).length} 种策略</span><button disabled={!params||busy} onClick={()=>{closePanel();setModal('research');}}>股票池与研究</button></nav>:null}
 {panel==='records'?<Results {...resultProps} onSelect={id=>{select(id);closePanel();}}/>:null}
 {panel==='signal'?<LatestSignal params={signalParams} snapshot={overview?.snapshot?.id}/>:null}
 {panel==='optimize'?<OptimizationPanel overview={overview} params={params} busy={busy} loading={loading} symbol={symbol} setParams={setParams} start={(path,body)=>{closePanel();start(path,body);}}/>:null}
 {panel==='compare'?<StrategyComparison run={savedRun} active={activeStrategy} onSelect={id=>{setViewStrategy(id);closePanel();}}/>:null}
 {panel==='metrics'?<><p className="muted">{run?.result.strategy_name||'尚无回测'} · {run?.params.start} — {run?.params.end}</p><Metrics run={run}/>
 {run?<div className="comparison"><span>买入持有收益 <FormulaInfo name="累计收益率"/><strong className={valueTone(run.result.benchmark.metrics.total_return)}>{pct(run.result.benchmark.metrics.total_return)}</strong></span><span><FormulaLabel name="期末资产"/> <strong className={valueTone(Number(run.result.strategy.metrics.ending.equity)-run.params.capital)}>¥ {num(run.result.strategy.metrics.ending.equity)}</strong></span><span>费用 / 红利税 <FormulaInfo name="累计费用"/><FormulaInfo name="红利税"/><strong>¥ {num(run.result.strategy.metrics.fees)} / {num(run.result.strategy.metrics.dividend_tax)}</strong></span></div>:null}</>:null}
 {panel==='data'?<><div className="data-summary"><p>行情截至 <strong>{overview?.snapshot?.end||'尚未同步'}</strong> · {overview?.snapshot?.bars.toLocaleString()||0} 条日线</p><button disabled={busy||loading} onClick={()=>{closePanel();setForce(false);setModal('sync');}}>同步数据</button><Info label="数据说明">行情按股票保存在本机，切换标的直接读取缓存。同步复用历史请求，强制重查可在同步设置中开启。</Info></div>
 {overview?.snapshot&&(repair||issues.some(i=>['missing','zero_volume'].includes(i.code)))?<section className="repair-status"><div className="repair-heading"><strong>{repair?'数据修复记录':'检测到行情缺口'}</strong><button disabled={busy||!params} onClick={()=>start('/repair'+(repair?'?force=true':''),{...params!,snapshot_id:overview.snapshot!.id})}>{repair?'重新尝试修复':'尝试自动修复'}</button></div><p>{repair?`本次补回 ${repair.filled.length} 条行情 · 累计确认 ${repair.confirmed_total??repair.suspensions.length} 个停牌日 · 剩余 ${repair.remaining} 个缺口 · ${repair.other_errors} 项其他待核验`:'运行回测时会自动尝试补数和核验停复牌公告，校验通过后继续回测。'}</p>{repair?<details><summary>修复详情 · {new Date(repair.attempted).toLocaleString('zh-CN')}</summary><p>同一快照6小时内复用尝试结果，手动重试可重新请求。无法确认的数据继续阻止回测。</p>{repair.filled.map(r=><p key={r.symbol+r.date}>{r.date} {r.symbol} · 补数来源 {r.source}</p>)}{repair.evidence?.map(e=><p key={e.source}>{e.start} 至 {e.resume}（复牌日） · <a href={e.source} target="_blank" rel="noreferrer">{e.title||'复牌公告'} ↗</a>{e.start_source&&e.start_source!==e.source?<> · <a href={e.start_source} target="_blank" rel="noreferrer">停牌公告 ↗</a></>:null}</p>)}{repair.failures.map((f,i)=><p key={i}>{f.date||''} {f.message}</p>)}</details>:null}</section>:null}<Results {...resultProps} initialTab="数据质量" onlyData/></>:null}
 </Modal>:null}
 {modal==='research'&&params?<PoolResearch params={params} onClose={()=>setModal(null)}/>:null}
 {modal==='stock'?<StockPicker onClose={()=>setModal(null)} onSelect={choose}/>:null}
 {modal==='settings'&&draft?<Modal title="回测设置" onClose={()=>setModal(null)}><Parameters value={draft} availableEnd={overview?.snapshot?.end} onChange={setDraft} onCancel={()=>setModal(null)} onSave={()=>{setParams({...draft,data_after:null});localStorage.setItem('pullback.params.'+symbol,JSON.stringify({...draft,data_after:null}));setModal(null);}}/></Modal>:null}
 {modal==='sync'?<Modal title="同步数据" onClose={()=>setModal(null)}><p>{overview?.stock.name} · {symbol}</p><p className="muted">保留本地行情与历史回测，复用历史行情和公告缓存。新增数据完成校验后保存为独立快照。</p><label className="check"><input type="checkbox" checked={force} onChange={e=>setForce(e.target.checked)}/>强制重查全部来源 <Info label="强制同步说明">跳过请求缓存重新核验，适合处理数据修订或核验失败，耗时较长；不会删除已有快照。</Info></label><div className="modal-actions"><button onClick={()=>setModal(null)}>取消</button><button className="primary" disabled={busy} onClick={()=>start('/sync',{symbol,force})}>{force?'重新核验':'开始同步'}</button></div></Modal>:null}</>;
}

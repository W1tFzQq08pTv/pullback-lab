export type SearchAdaptation={adapted:boolean;min_sessions:number;available:number;sessions:number;warmup?:number;strategies:StrategyId[];skipped:Record<string,string>;note:string};
export type StrategyId='trend_pullback'|'trend_pullback_v2'|'martin_daily';
export const strategyNames:Record<StrategyId,string>={trend_pullback:'趋势回调（SMA）',trend_pullback_v2:'趋势回调 v2（仓位管理）',martin_daily:'Martin Luk 回调（日线量化版）'};
export type Stock={symbol:string;code:string;name:string;pinyin:string;org_id:string;cached?:boolean};
export type Params={v2_mode?:'fixed'|'up'|'down';v2_allocation?:number;v2_batches?:number;v2_step?:number;v2_fast?:number;v2_middle?:number;v2_slow?:number;v2_slope?:number;v2_pullback?:number;v2_market_filter?:boolean;defaults_revision?:string;time_range?:'all'|'custom';strategies?:StrategyId[];martin_risk?:number;martin_max_stop?:number;martin_min_return?:number;martin_min_turnover?:number;martin_support_tolerance?:number;martin_anchor_window?:number;martin_pool_id?:string|null;allow_suffix?:boolean;data_after?:string|null;symbol:string;start:string;end:string;fast:number;middle:number;slow:number;slope:number;pullback:number;market_filter:boolean;capital:number;allocation:number;commission:number;min_commission:number;slippage_bps:number;snapshot_id:string|null};
export type Row=Record<string,string|number|boolean|null>;
export type Issue={code:string;date:string|null;message:string;symbol:string;severity:string};
export type Snapshot={id:string;created:string;start:string;end:string;bars:number;events:number;errors:number};
export type Overview={stock:Stock;snapshot:Snapshot|null;defaults:Params;defaults_profile?:{mode_verified?:Record<string,{params:Params;metrics:Metrics}>;adaptation?:SearchAdaptation;revision:string;params:Partial<Params>;note:string;created?:string;snapshot_id?:string;range?:{start:string;end:string};metrics?:Record<StrategyId,Metrics>;conditions?:Params}|null;active_task:string|null};
export type RepairReport={attempted:string;requested:number;confirmed_total?:number;filled:{date:string;symbol:string;source:string}[];suspensions:string[];remaining:number;other_errors:number;cached:boolean;failures:{stage:string;message:string;date?:string}[];evidence?:{source:string;start_source?:string;title:string;start:string;resume:string}[]};
export type Task={id:string;kind:string;status:string;progress:number;message:string;result:{adaptation?:SearchAdaptation;run_id?:string;symbol?:string;optimization_id?:string;cached?:boolean;params?:Params;request_params?:Params;reason?:string;step?:number;step_progress?:number;steps?:{id:string;label:string;status:string;message?:string}[]}|null};
export type Metrics={total_return:number;annual_return:number;max_drawdown:number;trade_count:number;closed_trades:number;win_rate:number|null;exposure:number;fees:number;dividend_tax:number;ending:Row};
export type Book={metrics:Metrics;curve:Row[];trades:Row[];ledger:Row[];rejected:Row[]};
export type Run={id:string;created:string;snapshot_id:string;params:Params;result:{adaptation?:SearchAdaptation;data_coverage?:{latest:string;requested_end:string;backtest_end:string;message:string};strategy_id?:StrategyId;strategy_name?:string;variants?:Partial<Record<StrategyId,{name:string;book:Book;chart:Row[];rules:string;source?:string;selection?:{note:string}}>>;fallback?:{issues?:Issue[];reason?:string;requested_start:string;requested_end?:string;actual_start:string;excluded_through:string;data_start:string;warmup:number};engine:string;checksum:string;strategy:Book;benchmark:Book;chart:Row[]}};
export type RunHead=Omit<Run,'result'>;
export async function api<T>(path:string,body?:unknown):Promise<T>{
 const r=await fetch('/api'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const text=await r.text();
 let data;
 try{data=JSON.parse(text);}catch{throw new Error(r.ok?'服务返回了无效的 JSON 响应':text.trim()||`请求失败（HTTP ${r.status}）`);}
 if(!r.ok){const d=data?.detail??`请求失败（HTTP ${r.status}）`;throw new Error(typeof d==='string'?d:d?.message?d.message+'：'+(d.issues||[]).slice(0,4).map((i:Issue)=>`${i.date||''} ${i.message}`).join('；'):JSON.stringify(d));}
 return data;
}
export const exactFixed=(n:unknown,digits=2)=>typeof n==='number'&&Number.isFinite(n)?(Math.abs(n)<.5*10**(-digits)?0:n).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—';
export const fixed=(n:unknown,digits=2)=>{
 if(typeof n!=='number'||!Number.isFinite(n)||Math.abs(n)<1000)return exactFixed(n,digits);
 const units=['k','M','B','T','P','E'];
 const precision=Math.max(2,digits);
 let unit=0,scaled=n/1000;
 // Promote after rounding as well, so a boundary never displays as 1000k.
 while(Math.abs(Number(scaled.toFixed(precision)))>=1000){
  if(unit===units.length-1)return n.toExponential(precision);
  scaled/=1000;unit++;
 }
 return `${Number(scaled.toFixed(precision))}${units[unit]}`;
};
// Percentages always use full numbers on every viewport; never pass them through fixed/num.
export const percentPoints=(n:number|null,digits=2)=>n===null||!Number.isFinite(n)?'—':`${exactFixed(n,digits)}%`;
export const pct=(n:number|null)=>percentPoints(n===null?null:n*100);
export const num=(n:unknown)=>typeof n==='number'?fixed(n):String(n??'—');
export const cell=(key:string,n:unknown)=>['price','initial_stop','risk_per_share'].includes(key)?exactFixed(n):key==='drawdown'?pct(typeof n==='number'?n:null):['shares','pending_shares'].includes(key)?fixed(n,0):num(n);

export const valueTone=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?n>0?'value-up':n<0?'value-down':'':'';

export type SourceReport={source:string;symbol:string;latest:string|null;rows:number;cached?:boolean;failures:string[]};

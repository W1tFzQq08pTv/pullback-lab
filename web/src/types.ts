export type Stock={symbol:string;code:string;name:string;pinyin:string;org_id:string;cached?:boolean};
export type Params={allow_suffix?:boolean;data_after?:string|null;symbol:string;start:string;end:string;fast:number;middle:number;slow:number;slope:number;pullback:number;market_filter:boolean;capital:number;allocation:number;commission:number;min_commission:number;slippage_bps:number;snapshot_id:string|null};
export type Row=Record<string,string|number|boolean|null>;
export type Issue={code:string;date:string|null;message:string;symbol:string;severity:string};
export type Snapshot={id:string;created:string;start:string;end:string;bars:number;events:number;errors:number};
export type Overview={stock:Stock;snapshot:Snapshot|null;defaults:Params;active_task:string|null};
export type RepairReport={attempted:string;requested:number;confirmed_total?:number;filled:{date:string;symbol:string;source:string}[];suspensions:string[];remaining:number;other_errors:number;cached:boolean;failures:{stage:string;message:string;date?:string}[];evidence?:{source:string;start_source?:string;title:string;start:string;resume:string}[]};
export type Task={id:string;kind:string;status:string;progress:number;message:string;result:{run_id?:string}|null};
export type Metrics={total_return:number;annual_return:number;max_drawdown:number;trade_count:number;closed_trades:number;win_rate:number|null;exposure:number;fees:number;dividend_tax:number;ending:Row};
export type Book={metrics:Metrics;curve:Row[];trades:Row[];ledger:Row[];rejected:Row[]};
export type Run={id:string;created:string;snapshot_id:string;params:Params;result:{fallback?:{requested_start:string;actual_start:string;excluded_through:string;data_start:string;warmup:number};engine:string;checksum:string;strategy:Book;benchmark:Book;chart:Row[]}};
export type RunHead=Omit<Run,'result'>;
export async function api<T>(path:string,body?:unknown):Promise<T>{
 const r=await fetch('/api'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const data=await r.json();
 if(!r.ok){const d=data.detail;throw new Error(typeof d==='string'?d:d?.message?d.message+'：'+(d.issues||[]).slice(0,4).map((i:Issue)=>`${i.date||''} ${i.message}`).join('；'):JSON.stringify(d));}
 return data;
}
export const fixed=(n:unknown,digits=2)=>typeof n==='number'&&Number.isFinite(n)?(Math.abs(n)<.5*10**(-digits)?0:n).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—';
export const pct=(n:number|null)=>n===null||!Number.isFinite(n)?'—':`${fixed(n*100)}%`;
export const num=(n:unknown)=>typeof n==='number'?fixed(n):String(n??'—');
export const cell=(key:string,n:unknown)=>key==='drawdown'?pct(typeof n==='number'?n:null):['shares','pending_shares'].includes(key)?fixed(n,0):num(n);

export const valueTone=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?n>0?'value-up':n<0?'value-down':'':'';

export type SourceReport={source:string;symbol:string;latest:string|null;rows:number;cached?:boolean;failures:string[]};

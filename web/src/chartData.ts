import type {Row} from './types';
export type Period='day'|'week'|'month';
export type Candle={date:string;first:string;last:string;open:number;close:number;low:number;high:number;volume:number|null;trades:Row[]};
export const periodNames:Record<Period,string>={day:'日K',week:'周K',month:'月K'};
export const maChoices=[5,10,20,30,60,120,200,250];
export const maColors:Record<number,string>={5:'#b88900',10:'#9455c6',20:'#d55382',30:'#3283bf',60:'#159b93',120:'#dc7b32',200:'#6574bc',250:'#687c32'};
export function bucket(date:string,period:Period):string{
 if(period!=='week')return date.slice(0,period==='day'?10:7);
 // Monday-based calendar weeks, including weeks crossing a month/year boundary.
 const day=new Date(date+'T00:00:00Z');
 day.setUTCDate(day.getUTCDate()-(day.getUTCDay()+6)%7);
 return day.toISOString().slice(0,10);
}
// Only aggregate observed sessions. No invented future close or synthetic holiday candles.
export function candles(rows:Row[],trades:Row[],period:Period):Candle[]{
 const groups=new Map<string,Candle>();
 for(const r of [...rows].sort((a,b)=>String(a.date).localeCompare(String(b.date)))){
  const day=String(r.date),date=bucket(day,period),old=groups.get(date);
  const volume=r.volume!=null&&Number.isFinite(Number(r.volume))&&Number(r.volume)>=0?Number(r.volume):null;
  if(old){old.close=Number(r.close);old.high=Math.max(old.high,Number(r.high));old.low=Math.min(old.low,Number(r.low));old.last=day;old.volume=old.volume===null||volume===null?null:old.volume+volume;}
  else groups.set(date,{date,first:day,last:day,open:Number(r.open),close:Number(r.close),low:Number(r.low),high:Number(r.high),volume,trades:[]});
 }
 for(const t of trades)groups.get(bucket(String(t.date),period))?.trades.push(t);
 return [...groups.values()].map(c=>period==='week'?{...c,date:c.last}:c);
}
export function movingAverage(rows:Candle[],period:number):(number|null)[]{
 let sum=0;return rows.map((r,i)=>{sum+=r.close;if(i>=period)sum-=rows[i-period].close;return i+1>=period?sum/period:null;});
}

// EMA starts at the first observed close; missing values reset the sequence.
export function macd(rows:Candle[]){
 let fast:number|undefined,slow:number|undefined,signal=0;
 return rows.map(row=>{
  if(!Number.isFinite(row.close)){fast=slow=undefined;signal=0;return {dif:null,dea:null,hist:null};}
  fast=fast===undefined?row.close:fast+(row.close-fast)*2/13;
  slow=slow===undefined?row.close:slow+(row.close-slow)*2/27;
  const dif=fast-slow;signal+=(dif-signal)*2/10;
  return {dif,dea:signal,hist:2*(dif-signal)};
 });
}

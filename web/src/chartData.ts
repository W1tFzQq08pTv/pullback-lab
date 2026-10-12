import type {Row} from './types';
export type Period='day'|'month'|'year';
export type Candle={date:string;first:string;last:string;open:number;close:number;low:number;high:number;trades:Row[]};
export const periodNames:Record<Period,string>={day:'日K',month:'月K',year:'年K'};
export const maChoices=[5,10,20,30,60,120,200,250];
export const maColors:Record<number,string>={5:'#b88900',10:'#9455c6',20:'#d55382',30:'#3283bf',60:'#159b93',120:'#dc7b32',200:'#6574bc',250:'#687c32'};
export const bucket=(date:string,period:Period)=>date.slice(0,period==='day'?10:period==='month'?7:4);
// Only aggregate observed sessions. No invented future close or synthetic holiday candles.
export function candles(rows:Row[],trades:Row[],period:Period):Candle[]{
 const groups=new Map<string,Candle>();
 for(const r of [...rows].sort((a,b)=>String(a.date).localeCompare(String(b.date)))){
  const day=String(r.date),date=bucket(day,period),old=groups.get(date);
  if(old){old.close=Number(r.close);old.high=Math.max(old.high,Number(r.high));old.low=Math.min(old.low,Number(r.low));old.last=day;}
  else groups.set(date,{date,first:day,last:day,open:Number(r.open),close:Number(r.close),low:Number(r.low),high:Number(r.high),trades:[]});
 }
 for(const t of trades)groups.get(bucket(String(t.date),period))?.trades.push(t);
 return [...groups.values()];
}
export function movingAverage(rows:Candle[],period:number):(number|null)[]{
 let sum=0;return rows.map((r,i)=>{sum+=r.close;if(i>=period)sum-=rows[i-period].close;return i+1>=period?sum/period:null;});
}

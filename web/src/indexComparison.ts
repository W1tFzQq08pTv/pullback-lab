import type {Row} from './types';
import type {Candle} from './chartData';
import type {Range} from './ChartViewport';
export type IndexData={symbol:string;name:string;bars:Row[];latest:string;refresh_error?:string};
export const indexColors:Record<string,string>={sh000001:'#397cbd',sz399006:'#9455c6',sz399001:'#db9224',sh000688:'#199d9b',sh000300:'#a96b45',sh000905:'#d15a9d'};
/** Exact-date closes only: comparison never invents a suspended/missing session. */
export function compareIndices(rows:Candle[],range:Range,indices:(IndexData & {closes?:Map<string,number>})[]){
 const maps=indices.map(index=>index.closes||new Map(index.bars.map(r=>[String(r.date),Number(r.close)])));
 const start=rows.find(r=>r.last>=range[0]&&r.first<=range[1]&&maps.every(m=>(m.get(r.last)||0)>0));
 if(!start||!indices.length)return null;
 return {date:start.last,base:start.close,lines:indices.map((index,i)=>({symbol:index.symbol,name:index.name,color:indexColors[index.symbol],values:rows.map(r=>{const close=maps[i].get(r.last);return close===undefined?null:close/maps[i].get(start.last)!*start.close;})}))};
}

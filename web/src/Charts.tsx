import {FormulaInfo,FormulaLabel} from './FormulaInfo';
import {FitValue} from './FitValue';
import {DatePicker} from './DatePicker';
import {notify,useFeedback} from './Toast';
import {Icon} from './Icon';
import {Loading} from './Loading';
import './candleAlignment';
import {ChartViewport as Chart,rangeIndices,type Range} from './ChartViewport';
import {Info} from './Info';
import {Modal} from './Modal';
import {TradeDetails,type TradeMarker} from './TradeMarkers';
import {compareIndices,indexColors,type IndexData} from './indexComparison';
import {candles,movingAverage,periodNames,maChoices,maColors,type Period} from './chartData';
import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import * as echarts from 'echarts/core';
import {LineChart, CandlestickChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,MarkPointComponent,MarkAreaComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
import {api,fixed,exactFixed,pct,percentPoints,type Params,type Run,type Row} from './types';
echarts.use([LineChart,CandlestickChart,GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,MarkPointComponent,MarkAreaComponent,CanvasRenderer]);
const base={animation:false,color:['#d64b4b','#397cbd','#d49b28','#9455c6'],textStyle:{fontFamily:'system-ui'},tooltip:{trigger:'axis',showContent:false,confine:true,valueFormatter:(v:unknown)=>fixed(v),axisPointer:{type:'cross',label:{precision:2},crossStyle:{color:'#888888'}},backgroundColor:'#ffffff',borderColor:'#dddddd',textStyle:{color:'#333333'}},grid:{left:58,right:24,top:46,bottom:48},legend:{type:'scroll',left:16,right:16,top:8,pageIconColor:'#555555',pageIconInactiveColor:'#cccccc',pageTextStyle:{color:'#666666'},textStyle:{color:'#707070'}},xAxis:{type:'category',boundaryGap:false,axisLine:{lineStyle:{color:'#dedede'}},axisLabel:{color:'#808080'}},yAxis:{type:'value',scale:true,splitLine:{lineStyle:{color:'#eeeeee'}},axisLabel:{color:'#808080',formatter:(v:number)=>fixed(v)}},dataZoom:[{type:'inside',zoomOnMouseWheel:'ctrl',moveOnMouseWheel:false,moveOnMouseMove:true,preventDefaultMouseMove:false},{type:'slider',show:false,height:20,bottom:4,borderColor:'transparent',backgroundColor:'#f5f5f5',fillerColor:'rgba(0,0,0,.08)',dataBackground:{lineStyle:{color:'#aaaaaa'},areaStyle:{color:'#eeeeee'}},selectedDataBackground:{lineStyle:{color:'#777777'},areaStyle:{color:'#dddddd'}},handleStyle:{color:'#ffffff',borderColor:'#999999'},moveHandleStyle:{color:'#777777'},emphasis:{handleStyle:{color:'#dddddd',borderColor:'#666666'},moveHandleStyle:{color:'#555555'}},textStyle:{color:'#777777'}}]};
const emptyRows:Row[]=[];
const rangeChoices=[[1,'近1月'],[3,'近3月'],[6,'近6月'],[-1,'今年以来'],[12,'近1年'],[36,'近3年'],[60,'近5年'],[0,'全部']] as const;
export type ChartReturn={value:number|null;start:string;end:string;basis:string;notice?:string};
export function Charts({onIntervalReturn,configuredParams,run,bars,snapshotId,zoneGuide,loading=false,rangeRevision=0}:{onIntervalReturn?:(value:ChartReturn|null)=>void;configuredParams?:Params|null;rangeRevision?:number;run:Run|null;bars:Row[];snapshotId?:string;zoneGuide?:ReactNode;loading?:boolean}){
 const [rangeInfoOpen,setRangeInfoOpen]=useState(false);
 const [mobileDetails,setMobileDetails]=useState(false);
 const [view,setView]=useState<'equity'|'price'|'draw'>('price');
 const [period,setPeriod]=useState<Period>('day');
 const [range,setRange]=useState<Range>(['0000','9999']),[cursor,setCursor]=useState<string|null>(null),[full,setFull]=useState(false),[locate,setLocate]=useState(false),[targetDate,setTargetDate]=useState(''),[,setDateError]=useFeedback();
 const [averages,setAverages]=useState<number[]>(()=>{try{const saved=JSON.parse(localStorage.getItem('pullback.chart.ma')||'null');if(Array.isArray(saved))return maChoices.filter(n=>saved.includes(n));}catch{}return [5,10,20,30,60];});
 const [compareIds,setCompareIds]=useState(['sh000001','sz399006']),[comparisonData,setComparisonData]=useState<Record<string,IndexData>>({}),[comparisonErrors,setComparisonErrors]=useState<Record<string,string>>({}),[comparisonSettings,setComparisonSettings]=useState(false);
 const [selectedTrade,setSelectedTrade]=useState<TradeMarker|null>(null);
 const [toolsOpen,setToolsOpen]=useState(false),[quoteOpen,setQuoteOpen]=useState(false);
 const [settings,setSettings]=useState(false),[draft,setDraft]=useState<number[]>(averages);
 const [indices,setIndices]=useState<{symbol:string;name:string}[]>([]),[instrument]=useState('stock');
 const [indexData,setIndexData]=useState<{symbol:string;name:string;bars:Row[];source:string;source_url:string;latest:string;cutoff:string}|null>(null),[indexError,setIndexError]=useFeedback(),[indexLoading,setIndexLoading]=useState(false),[retry,setRetry]=useState(0),[catalogError,setCatalogError]=useFeedback();
 useEffect(()=>{let alive=true;setCatalogError('');api<{symbol:string;name:string}[]>('/indices').then(v=>{if(alive)setIndices(v);}).catch(()=>{if(alive)setCatalogError('指数目录加载失败');});return()=>{alive=false;};},[retry]);
 const isIndex=view==='price'&&instrument!=='stock';
 useEffect(()=>{if(!isIndex)return;let alive=true;setIndexData(null);setIndexError('');setIndexLoading(true);
 api<NonNullable<typeof indexData>>(`/indices/${instrument}/bars`).then(v=>{if(alive)setIndexData(v);}).catch(e=>{if(alive)setIndexError(String(e.message));}).finally(()=>{if(alive)setIndexLoading(false);});return()=>{alive=false;};},[isIndex,instrument,retry]);
 const quoteSnapshot=snapshotId||run?.snapshot_id;
 useEffect(()=>{if(view!=='price')return;let alive=true,busy=false;
 async function refresh(){
  if(busy||document.visibilityState==='hidden')return;
  busy=true;
  await Promise.all(compareIds.map(async id=>{
   try{const data=await api<IndexData>(`/indices/${id}/bars`);if(alive){setComparisonData(old=>({...old,[id]:data}));setComparisonErrors(old=>{const next={...old};delete next[id];return next;});}}
   catch(e){if(alive)setComparisonErrors(old=>({...old,[id]:String((e as Error).message)}));}
  }));
  busy=false;
 }
 void refresh();
 const timer=window.setInterval(()=>void refresh(),5*60*1000);
 const resume=()=>void refresh();
 window.addEventListener('focus',resume);document.addEventListener('visibilitychange',resume);
 return()=>{alive=false;window.clearInterval(timer);window.removeEventListener('focus',resume);document.removeEventListener('visibilitychange',resume);};
 },[view,compareIds,retry,quoteSnapshot]);
 const activeIndex=isIndex&&indexData?.symbol===instrument?indexData:null;

 const [priceBasis,setPriceBasis]=useState<'qfq'|'raw'>('qfq');
 const [adjustment,setAdjustment]=useState<{id:string;status:string;basis?:string;bars?:Row[]}|null>(null);
 useEffect(()=>{let alive=true;if(!quoteSnapshot)return;api<{status:string;basis?:string;bars?:Row[]}>(`/adjustments?snapshot_id=${encodeURIComponent(quoteSnapshot)}`).then(data=>{if(alive)setAdjustment({...data,id:quoteSnapshot});}).catch(()=>{if(alive)setAdjustment({id:quoteSnapshot,status:'unavailable'});});return()=>{alive=false;};},[quoteSnapshot]);
 const rawDaily=bars.length?bars:(run?.result.chart||emptyRows);
 const adjustedMap=useMemo(()=>new Map(adjustment&&adjustment.id===quoteSnapshot&&adjustment.status==='available'?adjustment.bars?.map(r=>[String(r.date),r]):[]),[adjustment,quoteSnapshot]);
 const useAdjusted=!isIndex&&priceBasis==='qfq'&&rawDaily.length>0&&rawDaily.every(r=>adjustedMap.has(String(r.date)));
 const daily=useMemo(()=>isIndex?(activeIndex?.bars||emptyRows):useAdjusted?rawDaily.map(r=>({...r,...adjustedMap.get(String(r.date))})):rawDaily,[isIndex,activeIndex,useAdjusted,rawDaily,adjustedMap]);
 const trades=useMemo(()=>isIndex?emptyRows:(run?.result.strategy.trades||emptyRows).map(t=>({...t,chart_price:Number(t.price)*(useAdjusted?Number(adjustedMap.get(String(t.date))?.adjustment_ratio??1):1)})),[isIndex,run,useAdjusted,adjustedMap]);
 const basisLabel=isIndex?'指数点位':useAdjusted?'前复权':priceBasis==='raw'?'未复权':adjustment?.id!==quoteSnapshot?'未复权 · 复权数据加载中':'未复权 · 前复权暂不可用';
 const rows=useMemo(()=>candles(daily,trades,period),[daily,trades,period]);
 const dailySpans=useMemo(()=>daily.map(r=>({first:String(r.date),last:String(r.date)})),[daily]);
 const curveSpans=useMemo(()=>run?.result.strategy.curve.map(r=>({first:String(r.date),last:String(r.date)}))||[],[run]);
 const candleSpans=useMemo(()=>rows.map(r=>({first:r.first,last:r.last})),[rows]);
 const configuredRange:Range=configuredParams?.time_range==='all'&&dailySpans.length?[dailySpans[0].first,dailySpans[dailySpans.length-1].last]:[configuredParams?.start||run?.result.fallback?.requested_start||run?.params.start||'0000',configuredParams?.end||run?.result.fallback?.requested_end||run?.result.data_coverage?.requested_end||run?.params.end||'9999'];
 const initializedRange=useRef('');
 const rangeSource=isIndex?`index:${instrument}`:run?`run:${run.id}:${rangeRevision}`:`quotes:${quoteSnapshot||''}`;
 useEffect(()=>{
  if(loading||!dailySpans.length||!candleSpans.length||initializedRange.current===rangeSource)return;
  const requested:Range=!isIndex&&run?configuredRange:[dailySpans[isIndex?Math.max(0,dailySpans.length-250):0].first,dailySpans[dailySpans.length-1].last];
  const first=dailySpans.findIndex(s=>s.first>=requested[0]&&s.last<=requested[1]);
  if(first<0)return; // Wait for matching data instead of showing an unrelated date.
  const [,last]=rangeIndices(dailySpans,requested);
  const [a,b]=rangeIndices(candleSpans,[dailySpans[first].first,dailySpans[last].last]);
  setRange([candleSpans[a].first,candleSpans[b].last]);
  setCursor(dailySpans[last].last);
  initializedRange.current=rangeSource;
 },[rangeSource,loading,dailySpans,candleSpans,isIndex,run,configuredRange[0],configuredRange[1]]);
 function changeRange(next:Range){const [a,b]=rangeIndices(candleSpans,next);const aligned:Range=candleSpans.length?[candleSpans[a].first,candleSpans[b].last]:next;setRange(aligned);setCursor(old=>old&&aligned[0]<=old&&old<=aligned[1]?old:aligned[1]);}
 function changePeriod(next:Period){const spans=candles(daily,trades,next).map(r=>({first:r.first,last:r.last}));const [a,b]=rangeIndices(spans,range);if(spans.length)setRange([spans[a].first,spans[b].last]);setPeriod(next);}
 function quick(months:number){
  if(!daily.length)return;
  const end=String(daily[daily.length-1].date);
  if(!months){changeRange(!isIndex&&run?configuredRange:[String(daily[0].date),end]);return;}
  const d=new Date(end+'T00:00:00Z'),day=d.getUTCDate();
  if(months===-1){d.setUTCMonth(0,1);}else{
   d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()-months);
   const lastDay=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate();
   d.setUTCDate(Math.min(day,lastDay));
  }
  const begin=d.toISOString().slice(0,10),found=daily.find(r=>String(r.date)>=begin);
  changeRange([String(found?.date||daily[0].date),end]);
 }

 function move(direction:number){if(!rows.length)return;const [a,b]=rangeIndices(candleSpans,range),size=b-a+1;const start=Math.max(0,Math.min(rows.length-size,a+direction*Math.max(1,Math.floor(size*.8))));setRange([rows[start].first,rows[Math.min(rows.length-1,start+size-1)].last]);}
 function zoom(factor:number){if(!rows.length)return;const [a,b]=rangeIndices(candleSpans,range);const size=Math.min(rows.length,Math.max(5,Math.round((b-a+1)*factor)));setRange([rows[Math.max(0,b-size+1)].first,rows[b].last]);}
 const inspected=rows.find(r=>r.first<=String(cursor)&&r.last>=String(cursor))||rows[rows.length-1];
 const inspectedIndex=inspected?rows.indexOf(inspected):-1;
 const curveIndex=run?.result.strategy.curve.findIndex(r=>r.date===cursor)??-1;
 const equityPoint=run?.result.strategy.curve[curveIndex],benchmarkPoint=run?.result.benchmark.curve[curveIndex];
 const selectedMA=useMemo(()=>averages.map(n=>({n,values:movingAverage(rows,n)})),[averages,rows]);
 const intervalReturn=useMemo(()=>{
  const curve=run?.result.strategy.curve||[];
  const first=curve.findIndex(r=>String(r.date)>=range[0]&&String(r.date)<=range[1]);
  if(first<0||!run)return null;
  let last=first;while(last+1<curve.length&&String(curve[last+1].date)<=range[1])last++;
  // The opening balance is the prior session close, or initial capital at backtest start.
  const opening=Number(first?curve[first-1].equity:run.params.capital),ending=Number(curve[last].equity);
  return Number.isFinite(opening)&&opening>0&&Number.isFinite(ending)?{value:ending/opening-1,start:String(curve[first].date),end:String(curve[last].date)}:null;
 },[run,range]);
 const curve=run?.result.strategy.curve||[];
 const coverageStart=String(curve[0]?.date||''),coverageEnd=String(curve[curve.length-1]?.date||'');
 const outsideCoverage=!!coverageStart&&(range[0]<coverageStart||range[1]>coverageEnd);
 const coverageIssues=(run?.result.fallback?.issues||[]).filter(i=>i.severity==='error');
 // Explain the boundary being viewed, not an unrelated early-history error.
 const coverageIssue=range[1]>coverageEnd?
  coverageIssues.filter(i=>i.date&&i.date>coverageEnd).sort((a,b)=>a.date!.localeCompare(b.date!))[0]:
  range[0]<coverageStart?coverageIssues.filter(i=>i.date&&i.date<coverageStart).sort((a,b)=>b.date!.localeCompare(a.date!))[0]:undefined;
 const coverageReason=coverageIssue?`${coverageIssue.date||''} ${coverageIssue.message}`:undefined;
 const coverageNotice=!run?'尚无回测结果，请先运行研究。':!intervalReturn?
  `所选范围没有策略账户数据；回测覆盖 ${coverageStart||run.params.start} — ${coverageEnd||run.params.end}。${coverageReason?'原因：'+coverageReason+'。':''}`:
  outsideCoverage?`仅计算已回测部分：${intervalReturn.start} — ${intervalReturn.end}。${coverageReason?'回测截断原因：'+coverageReason+'。':''}`:'';
 useEffect(()=>{
  onIntervalReturn?.({value:loading?null:intervalReturn?.value??null,start:intervalReturn?.start||range[0],end:intervalReturn?.end||range[1],basis:run?.result.strategy_name||'所选策略',notice:loading?'':coverageNotice});
 },[onIntervalReturn,loading,intervalReturn?.value,intervalReturn?.start,intervalReturn?.end,range[0],range[1],run?.result.strategy_name,coverageNotice]);
 const shared={range,cursor,onRange:changeRange,onCursor:setCursor};
 const comparisonSources=useMemo(()=>compareIds.filter(id=>id!==instrument&&comparisonData[id]).map(id=>({...comparisonData[id],closes:new Map(comparisonData[id].bars.map(r=>[String(r.date),Number(r.close)]))})),[compareIds,instrument,comparisonData,comparisonErrors]);
 const comparison=useMemo(()=>compareIndices(rows,range,comparisonSources),[rows,range,comparisonSources]);
 const comparisonInspectIndex=rows.findIndex(r=>r.first<=String(cursor)&&r.last>=String(cursor));
 const comparisonReadIndex=comparisonInspectIndex>=0?comparisonInspectIndex:Math.max(0,rows.reduce((last,r,i)=>r.first<=range[1]?i:last,0));
 const markers=useMemo<TradeMarker[]>(()=>rows.flatMap((r,index)=>(['buy','sell'] as const).flatMap(side=>{const selected=r.trades.filter(t=>t.side===side);return selected.length?[{index,date:r.date,side,anchor:r[side==='buy'?'low':'high'],trades:selected}]:[];})),[rows]);
 const researchAreas=useMemo(()=>{
  if(!run||isIndex)return [];
  const warmupStart=run.params.data_after?String(run.params.data_after):run.result.fallback?.data_start||String(rawDaily[0]?.date||'');
  const zones=[{name:'预热区间',color:'rgba(188,160,100,0.12)',test:(d:string)=>d>=warmupStart&&d<run.params.start&&(!run.params.data_after||d>run.params.data_after)},
   {name:'实际回测',color:'rgba(89,137,174,0.09)',test:(d:string)=>d>=run.params.start&&d<=run.params.end}];
  // Aggregated candles use their last session, so monthly/yearly areas never overlap.
  return zones.flatMap(zone=>{const selected=rows.filter(r=>zone.test(r.last));return selected.length?[[{name:zone.name,xAxis:selected[0].date,itemStyle:{color:zone.color}},{xAxis:selected[selected.length-1].date}]]:[];});
 },[run,isIndex,rows,rawDaily]);
 const price=useMemo(()=>{
 const ma=new Map(averages.map(n=>[n,movingAverage(rows,n)]));
 const visible=rows.map((r,i)=>({r,i})).filter(({r})=>r.last>=range[0]&&r.first<=range[1]);
 const values=visible.flatMap(({r,i})=>[r.low,r.high,...averages.map(n=>ma.get(n)?.[i]),...(comparison?.lines.map(line=>line.values[i])||[])]).filter((n):n is number=>typeof n==='number'&&Number.isFinite(n));
 const low=values.length?values.reduce((a,b)=>Math.min(a,b),Infinity):0,high=values.length?values.reduce((a,b)=>Math.max(a,b),-Infinity):1,pad=(high-low||high*.1)*.08;
 const priceAxis={...base.yAxis,minInterval:1,axisPointer:{label:{formatter:(p:{value:number})=>exactFixed(p.value)}},axisLabel:{...base.yAxis.axisLabel,formatter:(v:number)=>exactFixed(v,0)}};
 const bounds=comparison?{min:Math.max(0,low-pad),max:high+pad}:{};

 const tooltip=(params:unknown)=>{const entries=params as {axisValue:string}[];const i=rows.findIndex(row=>row.date===entries[0]?.axisValue),r=rows[i];if(!r)return '';const previous=rows[i-1]?.close;const change=previous?r.close/previous-1:null;const lines=[`${r.date} · ${periodNames[period]}`,...(period==='day'?[]:[`数据范围 ${r.first} 至 ${r.last}`]),`开盘 ${exactFixed(r.open)}　收盘 ${exactFixed(r.close)}`,`最高 ${exactFixed(r.high)}　最低 ${exactFixed(r.low)}`,`涨跌幅 ${pct(change)}`,...averages.map(n=>`<span style="color:${maColors[n]}">MA${n} ${exactFixed(ma.get(n)?.[i])}</span>`),...r.trades.map(t=>`${t.date} ${t.side==='buy'?'B 买入':'S 卖出'} ${exactFixed(t.price)} 元 · ${fixed(t.shares,0)} 股`)];return lines.join('<br/>');};
 return {...base,grid:{...base.grid,top:24,bottom:28,right:comparison?52:24},legend:{...base.legend,show:false,data:[periodNames[period],...averages.map(n=>`MA${n}`),{name:'B 买入',icon:'none',textStyle:{color:'#d64b4b'}},{name:'S 卖出',icon:'none',textStyle:{color:'#16966b'}}]},tooltip:{...base.tooltip,showContent:true,formatter:tooltip,enterable:false,hideDelay:0,transitionDuration:0,extraCssText:'max-height:320px;max-width:280px;overflow-y:auto;border-radius:12px;padding:12px 16px;box-shadow:0 8px 28px rgba(25,30,25,.12);font-size:12px;line-height:1.7;'},yAxis:comparison?[{...priceAxis,...bounds},{...base.yAxis,position:'right',axisPointer:{label:{formatter:(p:{value:number})=>percentPoints(p.value)}},min:(Number(bounds.min)/comparison.base-1)*100,max:(Number(bounds.max)/comparison.base-1)*100,splitLine:{show:false},axisLabel:{color:'#8991a0',fontSize:10,formatter:(v:number)=>percentPoints(v,0)}}]:priceAxis,xAxis:{...base.xAxis,boundaryGap:true,data:rows.map(r=>r.date)},dataZoom:base.dataZoom.map(z=>({...z,...(z.type==='inside'?{zoomOnMouseWheel:true}:{}),startValue:Math.max(0,rows.length-(period==='day'?120:period==='month'?60:rows.length)),endValue:Math.max(0,rows.length-1)})),series:[{name:periodNames[period],type:'candlestick',markArea:{silent:true,label:{show:false},data:researchAreas},data:rows.map(r=>[r.open,r.close,r.low,r.high]),itemStyle:{color:'#e34c4c',color0:'#16966b',borderColor:'#e34c4c',borderColor0:'#16966b',borderColorDoji:'#888888'},barMaxWidth:16},...averages.map(n=>({name:`MA${n}`,type:'line',showSymbol:false,connectNulls:false,data:ma.get(n),itemStyle:{color:maColors[n]},lineStyle:{width:0.8,color:maColors[n]}})),...(comparison?.lines.map(line=>({id:'compare-'+line.symbol,name:line.name,type:'line',showSymbol:false,connectNulls:false,data:line.values,lineStyle:{color:line.color,width:1,type:'solid'},itemStyle:{color:line.color},z:3}))||[])]};},[rows,period,averages,comparison,range,researchAreas]);
 const equity=useMemo(()=>({...base,grid:{...base.grid,top:38,bottom:28},legend:{...base.legend,show:true},dataZoom:base.dataZoom.map(z=>z.type==='slider'?{...z,show:false}:z),tooltip:{...base.tooltip,valueFormatter:(v:unknown)=>fixed(v,3)},xAxis:{...base.xAxis,data:run?.result.strategy.curve.map(r=>r.date)||[]},yAxis:{...base.yAxis,splitNumber:3,axisPointer:{label:{formatter:(p:{value:number})=>fixed(p.value,3)}},axisLabel:{formatter:(v:number)=>fixed(v,3),color:'#808080'}},series:[...(run?.result.variants?(run.params.strategies||Object.keys(run.result.variants)).map(id=>run.result.variants![id as keyof typeof run.result.variants]).filter(Boolean).map(v=>({name:v!.name,type:'line',showSymbol:false,data:v!.book.curve.map(r=>Number(r.equity)/run.params.capital),itemStyle:{color:v!.name.includes('SMA')?'#d64b4b':'#9455c6'},lineStyle:{width:v!.name===run.result.strategy_name?2.5:1.3}})):[{name:run?.result.strategy_name||'趋势回调（SMA）',type:'line',showSymbol:false,data:run?.result.strategy.curve.map(r=>Number(r.equity)/run.params.capital)||[],areaStyle:{opacity:.06}}]),{name:'买入持有',type:'line',showSymbol:false,data:run?.result.benchmark.curve.map(r=>Number(r.equity)/run.params.capital)||[],itemStyle:{color:'#397cbd'},lineStyle:{type:'dashed'}}]}),[run]);
 const draw=useMemo(()=>({...base,grid:{...base.grid,top:12,bottom:28},legend:{show:false},dataZoom:base.dataZoom.map(z=>z.type==='slider'?{...z,show:false}:z),tooltip:{...base.tooltip,valueFormatter:(v:unknown)=>pct(Number(v))},xAxis:{...base.xAxis,data:run?.result.strategy.curve.map(r=>r.date)||[]},yAxis:{...base.yAxis,splitNumber:3,axisPointer:{label:{formatter:(p:{value:number})=>pct(p.value)}},axisLabel:{formatter:(v:number)=>pct(v),color:'#808080'}},series:[{name:'策略回撤',type:'line',showSymbol:false,itemStyle:{color:'#16966b'},data:run?.result.strategy.curve.map(r=>r.drawdown)||[],areaStyle:{opacity:.08}}]}),[run]);
 const quoteDetails=<>{comparison?<p className="comparison-base-note">指数对比基准：{comparison.date} 收盘 · 右轴为相对涨跌幅</p>:null}{activeIndex&&activeIndex.latest<activeIndex.cutoff?<p className="muted">仅展示已获取的完整日线；截止日期之后未补值。</p>:null}{inspected?<><div className="quote-readout" aria-label="行情读数"><strong className="quote-date"><small>交易日</small>{inspected.date}</strong><span><small>开盘</small><FitValue as="b" value={exactFixed(inspected.open)}/></span><span><small>最高</small><FitValue as="b" value={exactFixed(inspected.high)}/></span><span><small>最低</small><FitValue as="b" value={exactFixed(inspected.low)}/></span><span><small>收盘</small><FitValue as="b" tone={inspected.close>=inspected.open?'up':'down'} value={exactFixed(inspected.close)}/></span><span><small><FormulaLabel name="涨跌幅"/></small><FitValue as="b" tone={inspectedIndex>0&&inspected.close>=rows[inspectedIndex-1].close?'up':'down'} value={pct(inspectedIndex>0?inspected.close/rows[inspectedIndex-1].close-1:null)}/></span>{period!=='day'?<span>{inspected.first} 至 {inspected.last}</span>:null}</div><div className="ma-readout">{selectedMA.map(({n,values})=><span key={n} style={{color:maColors[n]}}><small>MA{n}<FormulaInfo name="MA"/></small><FitValue as="b" value={exactFixed(values[inspectedIndex])}/></span>)}</div></>:null}{inspected?.trades.length?<details className="chart-fills" key={inspected.date}><summary>{inspected.date} · {inspected.trades.length} 笔成交</summary>{inspected.trades.map((t,i)=><div key={i}>{String(t.date)} <b className={t.side==='buy'?'up':'down'}>{t.side==='buy'?'B 买入':'S 卖出'}</b>　{exactFixed(t.price)} 元 · {fixed(t.shares,0)} 股</div>)}</details>:null}</>;
 const rangeDetails=<>
 {!loading&&run&&coverageNotice?<div className="chart-coverage-note" role="status"><span>{coverageNotice}</span>{coverageStart?<button className="text-action" onClick={()=>changeRange([coverageStart,coverageEnd])}>查看已回测区间</button>:null}</div>:null}
 <div className="chart-range-summary" aria-label="行情完整区间">{run?<span>配置区间 {configuredRange[0]} — {configuredRange[1]}</span>:null}{run?<span>回测区间 {run.params.start} — {run.params.end}</span>:null}{daily.length?<span>查看区间 {range[0]} — {range[1]}</span>:null}</div></>;
 const chartTools=<><div className="terminal-toolbar"><div className="period-switch" role="group" aria-label="K线周期">{(['day','month','year'] as Period[]).map(p=><button key={p} aria-pressed={period===p} className={period===p?'active':''} onClick={()=>changePeriod(p)}>{periodNames[p]}</button>)}</div><div className="range-shortcuts extended-ranges">{rangeChoices.map(([n,label])=><button key={n} onClick={()=>quick(Number(n))}>{label}</button>)}</div><div className="terminal-tools"><button onClick={()=>{setToolsOpen(false);setTargetDate(cursor||range[1]);setDateError('');setLocate(true);}}>日期定位</button><button onClick={()=>{setToolsOpen(false);setDraft([...averages]);setSettings(true);}}>均线设置</button><button onClick={()=>{setToolsOpen(false);setFull(!full);}}>{full?'退出放大':'放大查看'}</button><Info label="图表操作说明">三图按日期联动。拖动图表平移；K线图内直接滚轮缩放，净值与回撤图按Ctrl加滚轮缩放。图表外滚轮正常滚动页面。点击任意图表后，左右方向键逐条移动光标，上下键放大缩小，Home/End定位最早/最新区间。月年K保留当前日期范围，净值与回撤始终为日频。放大状态按Escape退出。</Info></div></div>
 <div className="terminal-range"><span>查看区间 <strong>{range[0]} — {range[1]}</strong></span><div><button aria-label="前一区间" onClick={()=>move(-1)}>←</button><button aria-label="缩小时间图" onClick={()=>zoom(1.5)}>−</button><button aria-label="放大时间图" onClick={()=>zoom(.7)}>＋</button><button aria-label="后一区间" onClick={()=>move(1)}>→</button><button onClick={()=>{if(daily.length){setRange([String(daily[Math.max(0,daily.length-120)].date),String(daily[daily.length-1].date)]);setCursor(String(daily[daily.length-1].date));}}}>回到最新</button></div></div>
</>;
 const content=<div data-view={view} className={'chart-terminal'+(full?' chart-terminal-expanded':'')}>
 <div className="chart-primary-toolbar"><div className="segmented chart-views" role="group" aria-label="图表视图">{([['price','行情K线'],['equity','净值走势'],['draw','回撤']] as const).map(([id,label])=><button key={id} aria-pressed={view===id} onClick={()=>setView(id)}>{label}</button>)}</div><div className="range-shortcuts">{rangeChoices.map(([n,label])=><button key={n} onClick={()=>quick(Number(n))}>{label}</button>)}</div></div><button className="chart-tools-trigger" onClick={()=>setToolsOpen(true)}><Icon name="sliders"/>图表工具</button>
 {view==='price'?<section className="terminal-panel"><div className="mobile-chart-navigation" aria-label="移动行情浏览"><span>横滑看历史 · 双指缩放</span><button aria-label="查看更早行情" onClick={()=>move(-1)}>←</button><button aria-label="缩小K线" onClick={()=>zoom(1.5)}>−</button><button aria-label="放大K线" onClick={()=>zoom(.7)}>＋</button><button aria-label="查看更晚行情" onClick={()=>move(1)}>→</button></div><div className="index-selector"><div className="index-comparison-controls"><button className="text-action" onClick={()=>setComparisonSettings(true)}>对比指数{compareIds.length?`（${compareIds.length}）`:''}</button>{compareIds.filter(id=>id!==instrument).map(id=>{const line=comparison?.lines.find(l=>l.symbol===id),value=line?.values[comparisonReadIndex];return <span key={id} style={{color:indexColors[id]}}>{indices.find(i=>i.symbol===id)?.name||id} {loading||isIndex&&indexLoading?'加载中…':comparisonErrors[id]&&!comparisonData[id]?'加载失败':value!=null&&comparison?pct(value/comparison.base-1):comparisonData[id]?(line?`${rows[comparisonReadIndex]?.last.slice(5)||'当前日期'} 暂无数据`:'无共同日期'):'加载中…'}{comparisonData[id]&&(comparisonErrors[id]||comparisonData[id].refresh_error)?` · 更新失败，保留至 ${comparisonData[id].latest}`:null}</span>;})}<Info label="指数对比说明">个股K线按所选复权口径展示。指数折线按可见区间首个共同收盘日归一化到个股价格，折线价格 = 指数当日收盘 ÷ 指数基准日收盘 × 个股基准日收盘；右轴涨跌幅 = 当前价格 ÷ 个股基准日收盘 − 1；缩放后起点随区间变化。指数折线不是实际点位，缺少的日期不补值。所选日期缺少指数行情时显示该日期暂无数据，不代表整个区间没有共同日期。页面可见时每5分钟自动检查，返回页面及更新个股行情后也会检查；失败时保留已校验数据，不补齐缺失日期。</Info></div>{catalogError?<span><button onClick={()=>setRetry(n=>n+1)}>重试</button></span>:null}{activeIndex?<span className="muted">{activeIndex.source} · 截至 {activeIndex.latest} · 指数点位</span>:null}<button className="text-action range-details-trigger" onClick={()=>setRangeInfoOpen(true)}>区间详情{!loading&&run&&coverageNotice?<span className="range-coverage-badge">{intervalReturn?'部分覆盖':'未覆盖'}</span>:null}</button><button className="mobile-quote-toggle text-action" aria-expanded={mobileDetails} onClick={()=>setMobileDetails(v=>!v)}>行情信息{mobileDetails?' −':' ＋'}</button><div className={"quote-actions"+(mobileDetails?" mobile-expanded":"")}>{zoneGuide}{run?<span className="research-range-legend">{!zoneGuide?<><span className="warmup-key">预热</span><span className="backtest-key">回测</span></>:null}<span>{run.params.start} — {run.params.end}</span></span>:null}{!isIndex?<button className="text-action" onClick={()=>setPriceBasis(v=>v==='qfq'?'raw':'qfq')}>{priceBasis==='qfq'?'切换未复权':'切换前复权'}</button>:null}<span>{periodNames[period]} · {basisLabel}</span><button className="text-action" onClick={()=>setQuoteOpen(true)}>行情详情</button><Info label="行情说明">浅米色背景为预热区，不计入收益；浅蓝色为实际回测区，收益与成交仅统计此区间；无底色行情仅供查看。月K、年K按该周期最后交易日归属着色，精确边界以日K和标注日期为准。载入回测结果后默认展示参数配置范围内的完整行情（包括白色历史区、预热区与实际回测区），可缩放查看全部缓存行情；B/S仅来自所选回测，区间外没有回测成交。查看旧回测时行情可能已更新，成交详情仍保留当时记录。滚轮缩放；按住图表向右拖动看更早日期，向左拖动看更晚日期。也可在“图表工具”中使用日期定位、前后区间或回到最新。指数显示实际点位，个股默认显示前复权K线，红涨绿跌。指数仅供行情查看，不参与个股回测，不显示个股成交标记。月年K聚合实际交易日；MA按当前K线周期、所选口径的收盘价计算，数据不足不绘制。图表MA与策略逐日复权口径不同，不改变回测。B/S为实际成交，同周期多笔合并标记，红B在下、绿S在上；连接线随复权比例定位，详情保留真实成交价；复权仅用于展示，不重复计入分红。悬停预览，点击标记查看成交详情；月年K按方向合并并显示笔数。</Info></div></div>
 {isIndex&&indexError?<div className="index-error"><button onClick={()=>setRetry(n=>n+1)}>重试</button></div>:null}{Object.keys(comparisonErrors).length?<p className="comparison-load-error"><button onClick={()=>setRetry(n=>n+1)}>重试</button></p>:null}
{loading||isIndex&&indexLoading?<Loading chart label={isIndex?'正在加载指数行情':'正在读取行情与回测'}/>:rows.length?<Chart option={price} wheelZoom markers={markers} onTradeSelect={m=>{setCursor(String(m.trades[0].date));setSelectedTrade(m);}} spans={candleSpans} {...shared} title="行情图" height="100%"/>:<div className="empty" role="status">{isIndex&&indexLoading?'正在加载指数行情…':indexError&&isIndex?'请重试加载行情':'暂无行情'}</div>}
 </section>:null}
 {view==='equity'?<section className="terminal-panel"><div className="section-title"><h2>累计净值</h2><span>{cursor||'—'} · 日频</span></div><div className="quote-readout"><span>{run?.result.strategy_name||'趋势回调（SMA）'} <b className="strategy-color">{equityPoint&&run?fixed(Number(equityPoint.equity)/run.params.capital,3):'—'}</b></span><span>买入持有 <b className="benchmark-color">{benchmarkPoint&&run?fixed(Number(benchmarkPoint.equity)/run.params.capital,3):'—'}</b></span><Info label="净值说明">总资产除以初始资金，初始净值1.000；与行情图共享查看日期区间，曲线保持日频。</Info></div>{loading?<Loading chart label="正在读取回测"/>:run?<Chart option={equity} spans={curveSpans} {...shared} title="净值图" height="100%"/>:<div className="empty compact">暂无回测</div>}</section>:null}
 {view==='draw'?(loading?<Loading chart label="正在读取回测"/>:run?<section className="terminal-panel"><div className="section-title"><h2>回撤曲线<FormulaInfo name="回撤"/></h2><span>{cursor||'—'} · <b className="down">{equityPoint?pct(Number(equityPoint.drawdown)):'—'}</b></span></div><Chart option={draw} spans={curveSpans} {...shared} title="回撤图" height="100%"/></section>:<div className="empty">运行回测后查看回撤</div>):null}</div>;
 return <>{rangeInfoOpen?<Modal title="区间详情" onClose={()=>setRangeInfoOpen(false)}>{rangeDetails}{run?.result.adaptation?.adapted?<p className="muted">{run.result.adaptation.note}</p>:null}</Modal>:null}{full?<Modal title="图表工作区" className="chart-workspace-modal" onClose={()=>setFull(false)}>{content}</Modal>:content}{comparisonSettings?<Modal title="对比指数" onClose={()=>setComparisonSettings(false)}><p className="muted">勾选后与当前K线叠加对比，默认显示上证指数和创业板指。各曲线以同一日期收盘归一化，比较涨跌幅。</p><div className="comparison-index-options">{indices.map(i=><label className="check" key={i.symbol}><input type="checkbox" checked={compareIds.includes(i.symbol)} onChange={e=>setCompareIds(old=>e.target.checked?[...old,i.symbol]:old.filter(id=>id!==i.symbol))}/><span style={{color:indexColors[i.symbol]}}>{i.name}</span></label>)}</div><div className="modal-actions"><button className="primary" onClick={()=>setComparisonSettings(false)}>完成</button></div></Modal>:null}{selectedTrade?<Modal title="成交详情" className="trade-detail-modal" onClose={()=>setSelectedTrade(null)}><p className="muted">{run?.params.symbol} · {run?.result.strategy_name} · {selectedTrade.date} · {selectedTrade.trades.length} 笔回测成交</p><TradeDetails trades={selectedTrade.trades}/></Modal>:null}{toolsOpen?<Modal title="图表工具" className="chart-tools-modal" onClose={()=>setToolsOpen(false)}>{chartTools}</Modal>:null}{quoteOpen?<Modal title="行情详情" onClose={()=>setQuoteOpen(false)}><p className="muted">{useAdjusted?`新浪复权因子 · 基准日 ${adjustment?.basis} · `:''}{isIndex?activeIndex?.name:'当前个股'} · {periodNames[period]} · {basisLabel}</p>{quoteDetails}</Modal>:null}{settings?<Modal title="均线设置" onClose={()=>setSettings(false)}><p className="muted">MA周期以当前K线为单位，例如月K的MA5代表5个月。设置仅影响图表。</p><div className="ma-options">{maChoices.map(n=><label className="check" key={n}><input type="checkbox" checked={draft.includes(n)} onChange={e=>setDraft(old=>e.target.checked?[...old,n].sort((a,b)=>a-b):old.filter(x=>x!==n))}/><span style={{color:maColors[n]}}>MA{n}</span></label>)}</div><p className="muted">不足周期的均线不显示。</p><div className="modal-actions"><button onClick={()=>setSettings(false)}>取消</button><button className="primary" onClick={()=>{setAverages(draft);localStorage.setItem('pullback.chart.ma',JSON.stringify(draft));setSettings(false);}}>保存设置</button></div></Modal>:null}
 {locate?<Modal title="日期定位" onClose={()=>setLocate(false)}><label>选择日期<DatePicker label="选择日期" value={targetDate} min={dailySpans[0]?.first} max={dailySpans[dailySpans.length-1]?.last} onChange={setTargetDate}/></label><p className="muted">非交易日定位到其后第一个已有交易日。</p><div className="modal-actions"><button onClick={()=>setLocate(false)}>取消</button><button className="primary" onClick={()=>{const i=dailySpans.findIndex(s=>s.first>=targetDate);if(!targetDate||i<0||targetDate<dailySpans[0].first){setDateError('请选择已下载区间内的日期');return;}setRange([dailySpans[Math.max(0,i-30)].first,dailySpans[Math.min(dailySpans.length-1,i+30)].last]);setCursor(dailySpans[i].last);setLocate(false);}}>定位</button></div></Modal>:null}</>;
}

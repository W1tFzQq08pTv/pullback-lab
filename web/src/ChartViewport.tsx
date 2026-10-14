import {useEffect,useMemo,useRef,useState,type KeyboardEvent} from 'react';
import * as echarts from 'echarts/core';
import {TradeMarkers,type TradeMarker} from './TradeMarkers';
export type Span={first:string;last:string};
export type Range=[string,string];
export function rangeIndices(spans:Span[],range:Range):[number,number]{
 if(!spans.length)return [0,0];
 let first=spans.findIndex(s=>s.last>=range[0]);if(first<0)first=spans.length-1;
 let last=spans.length-1;while(last>first&&spans[last].first>range[1])last--;
 return [first,last];
}
export function ChartViewport({option,spans,range,cursor,onRange,onCursor,title,height=300,markers,onTradeSelect,wheelZoom=false}:{option:object;spans:Span[];range:Range;cursor:string|null;onRange:(r:Range)=>void;onCursor:(d:string)=>void;title:string;height?:number|string;wheelZoom?:boolean;markers?:TradeMarker[];onTradeSelect?:(marker:TradeMarker)=>void}){
 const outer=useRef<HTMLDivElement>(null);
 const [width,setWidth]=useState(0);
 const displayOption=useMemo(()=>{
  if(!width||width>600)return option;
  type Axis={axisLabel?:{formatter?:((v:number)=>string)|string;[key:string]:unknown};[key:string]:unknown};
  const source=option as {grid?:object;xAxis?:Axis;yAxis?:Axis|Axis[];tooltip?:object;legend?:object};
  const axes=Array.isArray(source.yAxis)?source.yAxis:[source.yAxis||{}];
  const compact=(axis:Axis)=>({...axis,splitNumber:3,axisLabel:{...axis.axisLabel,fontSize:10,inside:true,margin:4,verticalAlign:'bottom',padding:[0,2,3,2],backgroundColor:'rgba(255,255,255,.78)',hideOverlap:true,showMinLabel:false,showMaxLabel:false,formatter:(value:number)=>{
   const original=axis.axisLabel?.formatter;
   const text=typeof original==='function'?original(value):String(value);
   const percent=text.includes('%');
   const n=percent?Number(text.replace(/[,％%k]/g,''))*(text.includes('k')?1000:1):value;
   return (Math.abs(n)>=1000?`${Number((n/1000).toFixed(1))}k`:String(Number(n.toFixed(Math.abs(n)>=100?0:2))))+(percent?'%':'');
  }}});
  return {...option,grid:{...source.grid,left:8,right:8,bottom:26},xAxis:{...source.xAxis,splitNumber:3,axisLabel:{...source.xAxis?.axisLabel,fontSize:9,hideOverlap:true,showMinLabel:false,showMaxLabel:false,margin:9,formatter:(date:string)=>date.slice(2)}},yAxis:Array.isArray(source.yAxis)?axes.map(compact):compact(axes[0]),legend:{...source.legend,textStyle:{fontSize:10},itemWidth:14,itemHeight:8,itemGap:10},tooltip:{...source.tooltip,extraCssText:`max-width:${Math.max(160,width-48)}px;max-height:240px;overflow:auto;white-space:normal;border-radius:10px;padding:8px 10px;font-size:11px;line-height:1.6;`}};
 },[option,width]);
 const [mountedChart,setMountedChart]=useState<ReturnType<typeof echarts.init>|null>(null);
 const ref=useRef<HTMLDivElement>(null),instance=useRef<ReturnType<typeof echarts.init>|null>(null);
 const live=useRef({spans,range,cursor,onRange,onCursor,wheelZoom});live.current={spans,range,cursor,onRange,onCursor,wheelZoom};
 const applying=useRef(false);
 useEffect(()=>{const chart=echarts.init(ref.current!);instance.current=chart;setMountedChart(chart);
  chart.on('datazoom',()=>{if(applying.current)return;const z=(chart.getOption().dataZoom as {start:number;end:number;startValue?:number;endValue?:number}[])[0];const {spans,onRange}=live.current;if(!spans.length)return;const a=Math.max(0,Math.min(spans.length-1,Math.round(z.startValue??z.start*(spans.length-1)/100))),b=Math.max(a,Math.min(spans.length-1,Math.round(z.endValue??z.end*(spans.length-1)/100)));onRange([spans[a].first,spans[b].last]);});
  chart.on('updateAxisPointer',(event:unknown)=>{if(applying.current)return;const axis=(event as {axesInfo?:{axisDim:string;value:number}[]}).axesInfo?.find(a=>a.axisDim==='x');const row=axis?live.current.spans[Number(axis.value)]:null;if(row)live.current.onCursor(row.last);});
  const element=ref.current!;
  let touchStart:{x:number;y:number}|null=null;
  const beginTouch=(event:TouchEvent)=>{touchStart=event.touches.length===1?{x:event.touches[0].clientX,y:event.touches[0].clientY}:null;};
  const moveTouch=(event:TouchEvent)=>{
   if(!touchStart||event.touches.length!==1)return;
   const dx=Math.abs(event.touches[0].clientX-touchStart.x),dy=Math.abs(event.touches[0].clientY-touchStart.y);
   // Let the browser own vertical page scroll; retain horizontal drag and pinch.
   if(dy>dx&&dy>6)event.stopPropagation();
  };
  element.addEventListener('touchstart',beginTouch,{capture:true,passive:true});
  element.addEventListener('touchmove',moveTouch,{capture:true,passive:true});
  const pageWheel=(event:WheelEvent)=>{if(live.current.wheelZoom)event.preventDefault();else if(!event.ctrlKey)event.stopPropagation();};
  element.addEventListener('wheel',pageWheel,{capture:true,passive:false});
  const observer=new ResizeObserver(()=>{chart.resize();setWidth(element.clientWidth);});observer.observe(element);
  return()=>{element.removeEventListener('touchstart',beginTouch,true);element.removeEventListener('touchmove',moveTouch,true);element.removeEventListener('wheel',pageWheel,true);observer.disconnect();chart.dispose();instance.current=null;};
 },[]);
 // Keep the grid/dataZoom controllers alive while range-dependent series update during a drag.
 useEffect(()=>{const chart=instance.current;if(!chart)return;applying.current=true;chart.setOption(displayOption as Parameters<typeof chart.setOption>[0],{replaceMerge:['series','yAxis','xAxis']});const [startValue,endValue]=rangeIndices(spans,live.current.range);chart.dispatchAction({type:'dataZoom',startValue,endValue},{silent:true});applying.current=false;},[displayOption,spans]);
 useEffect(()=>{const chart=instance.current;if(!chart||!spans.length)return;const [startValue,endValue]=rangeIndices(spans,range);applying.current=true;chart.dispatchAction({type:'dataZoom',startValue,endValue},{silent:true});applying.current=false;},[range,spans]);
 useEffect(()=>{if(!cursor||!instance.current||!outer.current?.matches(':hover, :focus-visible'))return;const index=spans.findIndex(s=>s.first<=cursor&&s.last>=cursor);if(index<0)return;applying.current=true;instance.current.dispatchAction({type:'showTip',seriesIndex:0,dataIndex:index},{silent:true});applying.current=false;},[cursor,spans,option]);
 function key(e:KeyboardEvent){outer.current?.removeAttribute('data-pointer-focus');if((e.target as HTMLElement).closest('button')||!spans.length)return;const [a,b]=rangeIndices(spans,range),size=b-a+1;let start=a,end=b;
  if(e.key==='Enter'&&onTradeSelect){const i=spans.findIndex(s=>s.first<=String(cursor)&&s.last>=String(cursor));const marker=markers?.find(m=>m.index===i);if(marker){e.preventDefault();onTradeSelect(marker);}return;}
  if(e.key==='ArrowLeft'||e.key==='ArrowRight'){const found=cursor?spans.findIndex(s=>s.first<=cursor&&s.last>=cursor):-1;const index=Math.max(0,Math.min(spans.length-1,(found<0?b:found)+(e.key==='ArrowLeft'?-1:1)));onCursor(spans[index].last);if(index<a){start=index;end=Math.min(spans.length-1,start+size-1);}else if(index>b){end=index;start=Math.max(0,end-size+1);}}
  else if(['ArrowUp','+','='].includes(e.key)){start=Math.max(a,b-Math.max(5,Math.floor(size*.7))+1);}
  else if(['ArrowDown','-'].includes(e.key)){start=Math.max(0,b-Math.ceil(size*1.4)+1);}
  else if(e.key==='Home'){start=0;end=Math.min(spans.length-1,size-1);}
  else if(e.key==='End'){end=spans.length-1;start=Math.max(0,end-size+1);}
  else return;
  e.preventDefault();if(start!==a||end!==b)onRange([spans[start].first,spans[end].last]);
 }
 return <div ref={outer} tabIndex={0} role="group" aria-label={title+'，按住向右拖动查看更早日期，向左拖动查看更晚日期，方向键浏览，Enter查看当前交易'} onMouseDown={e=>{if(!(e.target as HTMLElement).closest('button')){outer.current?.setAttribute('data-pointer-focus','true');outer.current?.focus({preventScroll:true});}}} onBlur={()=>outer.current?.removeAttribute('data-pointer-focus')} onKeyDown={key} style={{height,width:'100%',overflow:'hidden',position:'relative'}} className="interactive-chart"><div ref={ref} style={{height:'100%',width:'100%'}}/>{mountedChart&&markers&&onTradeSelect?<TradeMarkers chart={mountedChart} markers={markers} onSelect={onTradeSelect}/>:null}</div>;
}

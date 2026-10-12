import {useEffect,useRef,type KeyboardEvent} from 'react';
import * as echarts from 'echarts/core';
export type Span={first:string;last:string};
export type Range=[string,string];
export function rangeIndices(spans:Span[],range:Range):[number,number]{
 if(!spans.length)return [0,0];
 let first=spans.findIndex(s=>s.last>=range[0]);if(first<0)first=spans.length-1;
 let last=spans.length-1;while(last>first&&spans[last].first>range[1])last--;
 return [first,last];
}
export function ChartViewport({option,spans,range,cursor,onRange,onCursor,title,height=300}:{option:object;spans:Span[];range:Range;cursor:string|null;onRange:(r:Range)=>void;onCursor:(d:string)=>void;title:string;height?:number|string}){
 const ref=useRef<HTMLDivElement>(null),instance=useRef<ReturnType<typeof echarts.init>|null>(null);
 const live=useRef({spans,range,cursor,onRange,onCursor});live.current={spans,range,cursor,onRange,onCursor};
 const applying=useRef(false);
 useEffect(()=>{const chart=echarts.init(ref.current!);instance.current=chart;
  chart.on('datazoom',()=>{if(applying.current)return;const z=(chart.getOption().dataZoom as {start:number;end:number;startValue?:number;endValue?:number}[])[0];const {spans,onRange}=live.current;if(!spans.length)return;const a=Math.max(0,Math.min(spans.length-1,Math.round(z.startValue??z.start*(spans.length-1)/100))),b=Math.max(a,Math.min(spans.length-1,Math.round(z.endValue??z.end*(spans.length-1)/100)));onRange([spans[a].first,spans[b].last]);});
  chart.on('updateAxisPointer',(event:unknown)=>{if(applying.current)return;const axis=(event as {axesInfo?:{axisDim:string;value:number}[]}).axesInfo?.find(a=>a.axisDim==='x');const row=axis?live.current.spans[Number(axis.value)]:null;if(row)live.current.onCursor(row.last);});
  const element=ref.current!;
  const pageWheel=(event:WheelEvent)=>{if(!event.ctrlKey)event.stopPropagation();};
  element.addEventListener('wheel',pageWheel,{capture:true,passive:true});
  const observer=new ResizeObserver(()=>chart.resize());observer.observe(element);
  return()=>{element.removeEventListener('wheel',pageWheel,true);observer.disconnect();chart.dispose();instance.current=null;};
 },[]);
 useEffect(()=>{const chart=instance.current;if(!chart)return;applying.current=true;chart.setOption(option as Parameters<typeof chart.setOption>[0],{notMerge:true});const [startValue,endValue]=rangeIndices(spans,live.current.range);chart.dispatchAction({type:'dataZoom',startValue,endValue},{silent:true});applying.current=false;},[option,spans]);
 useEffect(()=>{const chart=instance.current;if(!chart||!spans.length)return;const [startValue,endValue]=rangeIndices(spans,range);applying.current=true;chart.dispatchAction({type:'dataZoom',startValue,endValue},{silent:true});applying.current=false;},[range,spans]);
 useEffect(()=>{if(!cursor||!instance.current)return;const index=spans.findIndex(s=>s.first<=cursor&&s.last>=cursor);if(index<0)return;applying.current=true;instance.current.dispatchAction({type:'showTip',seriesIndex:0,dataIndex:index},{silent:true});applying.current=false;},[cursor,spans,option]);
 function key(e:KeyboardEvent){if(!spans.length)return;const [a,b]=rangeIndices(spans,range),size=b-a+1;let start=a,end=b;
  if(e.key==='ArrowLeft'||e.key==='ArrowRight'){const found=cursor?spans.findIndex(s=>s.first<=cursor&&s.last>=cursor):-1;const index=Math.max(0,Math.min(spans.length-1,(found<0?b:found)+(e.key==='ArrowLeft'?-1:1)));onCursor(spans[index].last);if(index<a){start=index;end=Math.min(spans.length-1,start+size-1);}else if(index>b){end=index;start=Math.max(0,end-size+1);}}
  else if(['ArrowUp','+','='].includes(e.key)){start=Math.max(a,b-Math.max(5,Math.floor(size*.7))+1);}
  else if(['ArrowDown','-'].includes(e.key)){start=Math.max(0,b-Math.ceil(size*1.4)+1);}
  else if(e.key==='Home'){start=0;end=Math.min(spans.length-1,size-1);}
  else if(e.key==='End'){end=spans.length-1;start=Math.max(0,end-size+1);}
  else return;
  e.preventDefault();if(start!==a||end!==b)onRange([spans[start].first,spans[end].last]);
 }
 return <div ref={ref} tabIndex={0} role="group" aria-label={title+'，点击后可用方向键浏览'} onMouseDown={()=>ref.current?.focus({preventScroll:true})} onKeyDown={key} style={{height,width:'100%',overflow:'hidden'}} className="interactive-chart"/>;
}

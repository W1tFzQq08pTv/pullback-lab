import {useEffect,useRef,useState} from 'react';
import type {EChartsType} from 'echarts/core';
import {exactFixed as fixed,type Row} from './types';

export type TradeMarker={index:number;date:string;side:'buy'|'sell';anchor:number;trades:Row[]};
type Positioned=TradeMarker & {x:number;y:number;anchorX:number;anchorY:number;width:number;placed:boolean;points:{x:number;y:number;trade:Row}[]};
export function TradeMarkers({chart,markers,onSelect}:{chart:EChartsType;markers:TradeMarker[];onSelect:(marker:TradeMarker)=>void}){
 const [positions,setPositions]=useState<Positioned[]>([]),[hovered,setHovered]=useState<{key:string;tradeIndex?:number}|null>(null);
 const frame=useRef(0);
 useEffect(()=>{
  function schedule(){if(frame.current)return;frame.current=requestAnimationFrame(()=>{
   frame.current=0;
   if(chart.isDisposed())return;
   const option=chart.getOption();
   const zoom=(option.dataZoom as {startValue:number;endValue:number}[])[0];
   const grid=(option.grid as {left:number;right:number;top:number;bottom:number}[])[0];
   const bounds={left:Number(grid.left)+3,right:chart.getWidth()-Number(grid.right)-3,top:Number(grid.top)+3,bottom:chart.getHeight()-Number(grid.bottom)-3};
   const occupied:{x:number;y:number;width:number}[]=[];
   const clamp=(v:number,min:number,max:number)=>Math.max(min,Math.min(max,v));
   const next=markers.filter(m=>m.index>=zoom.startValue&&m.index<=zoom.endValue).flatMap(m=>{
    const [x,y]=chart.convertToPixel({xAxisIndex:0,yAxisIndex:0},[m.index,m.anchor]) as number[];
    if(!Number.isFinite(x)||!Number.isFinite(y)||x<0||x>chart.getWidth())return [];
    const points=m.trades.map(trade=>{const [px,py]=chart.convertToPixel({xAxisIndex:0,yAxisIndex:0},[m.index,Number(trade.chart_price??trade.price)]) as number[];return {x:px,y:py,trade};});
    const width=m.trades.length>1?20+String(m.trades.length).length*5:18;
    const half=width/2,halfHeight=9;
    const preferred=y+(m.side==='buy'&&y+20+halfHeight<=bounds.bottom?20:-20);
    const xs=[x];
    const ys=[clamp(preferred,bounds.top+halfHeight,bounds.bottom-halfHeight)];
    for(let cy=bounds.bottom-halfHeight;cy>=bounds.top+halfHeight;cy-=23)ys.push(cy);
    const candidates=ys.flatMap(cy=>xs.map(cx=>({x:cx,y:cy,score:Math.abs(cx-x)*2+Math.abs(cy-preferred)}))).sort((a,b)=>a.score-b.score);
    const slot=candidates.find(c=>(chart.getWidth()>600||Math.abs(c.y-y)<=56)&&c.x-half>=bounds.left&&c.x+half<=bounds.right&&!occupied.some(o=>Math.abs(c.x-o.x)<(width+o.width)/2+4&&Math.abs(c.y-o.y)<22));
    if(slot)occupied.push({...slot,width});
    return [{...m,x:slot?.x??x,y:slot?.y??y,anchorX:x,anchorY:y,width,placed:!!slot,points}];
   });
   setPositions(next);
  });}
  chart.on('rendered',schedule);chart.on('datazoom',schedule);schedule();
  return()=>{cancelAnimationFrame(frame.current);frame.current=0;if(!chart.isDisposed()){chart.off('rendered',schedule);chart.off('datazoom',schedule);}};
 },[chart,markers]);
 const group=positions.find(m=>`${m.index}-${m.side}`===hovered?.key);
 const point=hovered?.tradeIndex!==undefined?group?.points[hovered.tradeIndex]:undefined;
 const nearby=group&&point?group.points.filter(p=>Math.abs(p.y-point.y)<12).map(p=>p.trade):[];
 const active=group&&point?{...group,x:point.x,y:point.y,date:nearby.length>1?group.date:String(point.trade.date),trades:nearby}:group;
 const previewCount=chart.getHeight()<220?1:3;
 const cardHeight=previewCount===1?112:152;
 const cardWidth=Math.min(280,chart.getWidth()-16);
 return <div className="trade-marker-layer" onKeyDown={e=>{if(e.key==='Escape')setHovered(null);}}>
 {positions.some(m=>!m.placed)?<span className="trade-density-hint">密集成交保留圆点，放大可展开 B/S</span>:null}
 {positions.map(m=>{const key=`${m.index}-${m.side}`,buy=m.side==='buy',label=`${m.date} ${buy?'B 买入':'S 卖出'} ${m.trades.length}笔成交`;
 return <div key={key} className={buy?'trade-buy':'trade-sell'}>
 {m.placed?<svg className="trade-connector" aria-hidden="true">{m.points.map((p,i)=><line key={i} x1={p.x} y1={m.y} x2={p.x} y2={p.y} />)}</svg>:null}
 {m.points.map((p,i)=>{const nearby=m.points.filter(q=>Math.abs(q.y-p.y)<12).map(q=>q.trade);return <button key={i} type="button" className="trade-price-dot" style={{left:p.x,top:p.y}} aria-label={`${label}，成交价 ${fixed(p.trade.price)} 元，查看详情`} onMouseEnter={()=>setHovered({key,tradeIndex:i})} onMouseLeave={()=>setHovered(null)} onFocus={()=>setHovered({key,tradeIndex:i})} onBlur={()=>setHovered(null)} onClick={()=>{setHovered(null);onSelect({...m,date:nearby.length>1?m.date:String(p.trade.date),trades:nearby});}}/>;})}
 <>{m.placed?<button type="button" className="trade-badge" style={{left:m.x,top:m.y,width:m.width}} aria-label={`${label}，查看详情`} onMouseEnter={()=>setHovered({key})} onMouseLeave={()=>setHovered(null)} onFocus={()=>setHovered({key})} onBlur={()=>setHovered(null)} onClick={()=>{setHovered(null);onSelect(m);}}><span>{buy?'B':'S'}</span>{m.trades.length>1?<small>{m.trades.length}</small>:null}</button>:null}</>
 </div>;})}
 {active?<div role="tooltip" className="trade-hover-card" style={{width:cardWidth,left:Math.max(8,Math.min(chart.getWidth()-cardWidth-8,active.x-cardWidth/2)),top:Math.max(8,Math.min(chart.getHeight()-cardHeight-8,active.y>chart.getHeight()/2?active.y-cardHeight-20:active.y+24))}}><strong className={active.side==='buy'?'value-up':'value-down'}>{active.date} · {active.side==='buy'?'B 买入':'S 卖出'} · {active.trades.length} 笔</strong>{active.trades.slice(0,previewCount).map((t,i)=><div key={i}>{String(t.date)}　{fixed(t.price)} 元 × {fixed(t.shares,0)} 股</div>)}<div>成交金额 ¥ {fixed(active.trades.reduce((sum,t)=>sum+Number(t.amount),0))}</div><small>{active.trades.length>previewCount?`另有 ${active.trades.length-previewCount} 笔 · `:''}{point&&nearby.length>1?'邻近成交点已合并，点击逐笔查看':'点击查看完整成交详情'}</small></div>:null}
 </div>;
}

const extraFields:Record<string,string>={commission:'佣金',transfer:'过户费',stamp:'印花税',dividend_tax:'红利税',cash:'成交后现金',initial_stop:'初始止损价',risk_per_share:'每股风险（R）',exit_stage:'止盈阶段'};
export function TradeDetails({trades}:{trades:Row[]}){
 return <div className="trade-detail-list">{trades.map((t,i)=><article className="trade-detail-card" key={i}><div className="trade-detail-heading"><span className={t.side==='buy'?'value-up':'value-down'}><b>{t.side==='buy'?'B 买入':'S 卖出'}</b></span><strong>{String(t.date)}</strong><span>第 {i+1} 笔</span></div><dl className="trade-detail-values"><div><dt>成交价格</dt><dd>¥ {fixed(t.price)}</dd></div><div><dt>成交数量</dt><dd>{fixed(t.shares,0)} 股</dd></div><div><dt>成交金额</dt><dd>¥ {fixed(t.amount)}</dd></div>{Object.entries(extraFields).filter(([key])=>t[key]!==undefined&&t[key]!==null).map(([key,name])=><div key={key}><dt>{name}</dt><dd>{key==='exit_stage'?fixed(t[key],0):'¥ '+fixed(t[key])}</dd></div>)}</dl>{t.reason?<p className="trade-reason">成交原因：{String(t.reason)}</p>:null}</article>)}</div>;
}

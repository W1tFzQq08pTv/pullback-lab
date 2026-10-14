import {useEffect,useId,useLayoutEffect,useRef,useState,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import {Select} from './Select';
import './datePicker.css';

const pad=(n:number)=>String(n).padStart(2,'0');
const monthOf=(year:number,month:number)=>`${String(year).padStart(4,'0')}-${pad(month)}`;
const parse=(date:string)=>new Date(`${date}T12:00:00Z`);
const format=(date:Date)=>date.toISOString().slice(0,10);
type Props={value:string;onChange:(value:string)=>void;min?:string;max?:string;disabled?:boolean;label:string};

export function DatePicker({value,onChange,min,max,disabled=false,label}:Props){
 const lower=min||'0001-01-01',upper=max||'9999-12-31';
 const clamp=(date:string)=>date<lower?lower:date>upper?upper:date;
 const id=useId(),trigger=useRef<HTMLButtonElement>(null),calendar=useRef<HTMLDivElement>(null),focusDay=useRef(false);
 const [open,setOpen]=useState(false),[month,setMonth]=useState(''),[active,setActive]=useState('');
 const [position,setPosition]=useState<{left:number;top:number;width:number;maxHeight:number}|null>(null);
 const year=Number(month.slice(0,4)),m=Number(month.slice(5,7));
 const firstYear=min?Number(lower.slice(0,4)):Math.max(1,year-100),lastYear=max?Number(upper.slice(0,4)):Math.min(9999,year+100);
 const offset=month?(parse(`${month}-01`).getUTCDay()+6)%7:0;
 const endOfMonth=month?parse(`${month}-01`):null;
 if(endOfMonth){endOfMonth.setUTCMonth(endOfMonth.getUTCMonth()+1);endOfMonth.setUTCDate(0);}
 const days=endOfMonth?.getUTCDate()||0;
 function close(restore=true){setOpen(false);if(restore)trigger.current?.focus();}
 function show(){
  const today=new Date(),localToday=monthOf(today.getFullYear(),today.getMonth()+1)+`-${pad(today.getDate())}`;
  const date=clamp(value||localToday);setMonth(date.slice(0,7));setActive(date);focusDay.current=true;setPosition(null);setOpen(true);
 }
 function choose(date:string){if(disabled||date<lower||date>upper)return;onChange(date);close();}
 function changeMonth(next:string){
  const bounded=next<lower.slice(0,7)?lower.slice(0,7):next>upper.slice(0,7)?upper.slice(0,7):next;
  setMonth(bounded);setActive(clamp(`${bounded}-01`));
 }
 function move(delta:number){const date=parse(`${month}-01`);date.setUTCMonth(date.getUTCMonth()+delta);changeMonth(format(date).slice(0,7));}
 useLayoutEffect(()=>{
  if(!open||!trigger.current||!calendar.current)return;
  const r=trigger.current.getBoundingClientRect(),width=Math.min(320,innerWidth-24),height=Math.min(calendar.current.scrollHeight,innerHeight-24);
  const top=r.bottom+6+height<=innerHeight-12?r.bottom+6:Math.max(12,r.top-height-6);
  setPosition({left:Math.max(12,Math.min(r.left,innerWidth-width-12)),top,width,maxHeight:innerHeight-top-12});
 },[open,month]);
 useLayoutEffect(()=>{
  if(open&&position&&focusDay.current){calendar.current?.querySelector<HTMLButtonElement>(`[data-date="${active}"]`)?.focus();focusDay.current=false;}
 },[open,active,position]);
 useEffect(()=>{
  if(!open)return;
  const outside=(e:PointerEvent)=>{const target=e.target as HTMLElement;if(!trigger.current?.contains(target)&&!calendar.current?.contains(target)&&!target.closest('.select-menu'))close(false);};
  const resize=()=>close(false);
  const scroll=(e:Event)=>{const target=e.target;if(target instanceof Element&&!calendar.current?.contains(target)&&!target.closest('.select-menu'))close(false);};
  document.addEventListener('pointerdown',outside);window.addEventListener('resize',resize);window.addEventListener('scroll',scroll,true);
  return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',resize);window.removeEventListener('scroll',scroll,true);};
 },[open]);
 useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
 function key(e:KeyboardEvent){
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();return;}
  if(!(e.target as HTMLElement).hasAttribute('data-date'))return;
  const delta:Record<string,number>={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};
  const date=parse(active);
  if(e.key in delta)date.setUTCDate(date.getUTCDate()+delta[e.key]);
  else if(e.key==='Home')date.setUTCDate(date.getUTCDate()-(date.getUTCDay()+6)%7);
  else if(e.key==='End')date.setUTCDate(date.getUTCDate()+6-(date.getUTCDay()+6)%7);
  else return;
  e.preventDefault();const next=clamp(date.getUTCFullYear()>9999?upper:format(date));focusDay.current=true;setActive(next);setMonth(next.slice(0,7));
 }
 return <span className="date-picker">
  <button ref={trigger} type="button" className="date-trigger" aria-label={label} aria-expanded={open} aria-haspopup="dialog" aria-controls={open?id:undefined} disabled={disabled||lower>upper} onClick={()=>open?close():show()} onKeyDown={e=>{if(e.key==='ArrowDown'){e.preventDefault();show();}}}><span>{value||'请选择日期'}</span><span aria-hidden="true">▦</span></button>
  {open?createPortal(<div ref={calendar} className="date-calendar" id={id} role="dialog" aria-label={`${label}日历`} style={position||{visibility:'hidden'}} onKeyDown={key} onBlur={e=>{if(e.relatedTarget&&!e.currentTarget.contains(e.relatedTarget as Node)&&e.relatedTarget!==trigger.current)close(false);}}>
   <div className="date-calendar-heading"><button type="button" aria-label="上个月" disabled={month<=lower.slice(0,7)} onClick={()=>move(-1)}>‹</button><Select aria-label="年份" value={String(year)} onChange={v=>changeMonth(monthOf(Number(v),m))}>{Array.from({length:Math.max(0,lastYear-firstYear+1)},(_,i)=><option key={i} value={String(firstYear+i)}>{firstYear+i}年</option>)}</Select><Select aria-label="月份" value={String(m)} onChange={v=>changeMonth(monthOf(year,Number(v)))}>{Array.from({length:12},(_,i)=><option key={i} value={String(i+1)} disabled={monthOf(year,i+1)<lower.slice(0,7)||monthOf(year,i+1)>upper.slice(0,7)}>{i+1}月</option>)}</Select><button type="button" aria-label="下个月" disabled={month>=upper.slice(0,7)} onClick={()=>move(1)}>›</button></div>
   <div className="date-calendar-grid">{['一','二','三','四','五','六','日'].map(d=><span className="date-weekday" key={d}>{d}</span>)}{Array.from({length:offset},(_,i)=><span key={`empty-${i}`}/>)}{Array.from({length:days},(_,i)=>{const date=`${month}-${pad(i+1)}`;return <button type="button" key={date} data-date={date} tabIndex={date===active?0:-1} aria-label={date} aria-pressed={value===date} disabled={date<lower||date>upper} onFocus={()=>setActive(date)} onClick={()=>choose(date)}>{i+1}</button>;})}</div>
   <div className="date-calendar-footer"><span>{min||max?`${min||'不限'} 至 ${max||'不限'}`:'方向键移动 · Enter 选择'}</span><button type="button" onClick={()=>close()}>收起</button></div>
  </div>,trigger.current?.closest('dialog')||document.body):null}
 </span>;
}

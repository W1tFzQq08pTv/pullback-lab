import {Children,isValidElement,useEffect,useId,useLayoutEffect,useRef,useState,type ReactNode,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';

type Choice={value:string;label:ReactNode;disabled?:boolean};
/** Shared, keyboard-accessible dropdown, also rendered inside the dialog top layer. */
export function Select({value,onChange,children,disabled=false,'aria-label':label}:{value:string;onChange:(value:string)=>void;children:ReactNode;disabled?:boolean;'aria-label':string}){
 const options:Choice[]=Children.toArray(children).filter(isValidElement).map(child=>{const p=child.props as {value?:string;children:ReactNode;disabled?:boolean};return {value:String(p.value??p.children),label:p.children,disabled:p.disabled};});
 const id=useId(),trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null);
 const [open,setOpen]=useState(false),[active,setActive]=useState(0),[position,setPosition]=useState<{left:number;top?:number;bottom?:number;width:number;maxHeight:number}|null>(null);
 const selected=options.findIndex(o=>o.value===value);
 function show(){if(disabled)return;setActive(Math.max(0,selected));setOpen(true);}
 function close(){setOpen(false);setPosition(null);}
 function choose(i:number){const option=options[i];if(!option||option.disabled)return;onChange(option.value);close();trigger.current?.focus();}
 useLayoutEffect(()=>{if(!open||!trigger.current)return;const r=trigger.current.getBoundingClientRect(),below=innerHeight-r.bottom-14,above=r.top-14,up=below<Math.min(220,options.length*38+12)&&above>below;const width=Math.min(Math.max(r.width,200),innerWidth-24);setPosition({left:Math.max(12,Math.min(r.left,innerWidth-width-12)),width,maxHeight:Math.max(40,Math.min(280,up?above:below)),...(up?{bottom:innerHeight-r.top+6}:{top:r.bottom+6})});},[open,options.length]);
 useEffect(()=>{if(!open||!menu.current)return;const box=menu.current,option=box.querySelector<HTMLElement>(`[data-index="${active}"]`);if(!option)return;if(option.offsetTop<box.scrollTop)box.scrollTop=option.offsetTop;else if(option.offsetTop+option.offsetHeight>box.scrollTop+box.clientHeight)box.scrollTop=option.offsetTop+option.offsetHeight-box.clientHeight;},[open,active,position]);
 useEffect(()=>{if(!open)return;const outside=(e:PointerEvent)=>{if(!trigger.current?.contains(e.target as Node)&&!menu.current?.contains(e.target as Node))close();};const scroll=(e:Event)=>{if(!menu.current?.contains(e.target as Node))close();};window.addEventListener('pointerdown',outside);window.addEventListener('resize',close);window.addEventListener('scroll',scroll,true);return()=>{window.removeEventListener('pointerdown',outside);window.removeEventListener('resize',close);window.removeEventListener('scroll',scroll,true);};},[open]);
 function key(e:KeyboardEvent){
  if(e.key==='Escape'&&open){e.preventDefault();e.stopPropagation();close();return;}
  if(e.key==='Tab'){close();return;}
  if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
   e.preventDefault();if(!open){show();return;}
   const direction=e.key==='ArrowUp'||e.key==='End'?-1:1;let index=e.key==='Home'?0:e.key==='End'?options.length-1:(active+direction+options.length)%options.length;
   for(let n=0;n<options.length&&options[index]?.disabled;n++)index=(index+direction+options.length)%options.length;
   setActive(index);return;
  }
  if(e.key==='Enter'||e.key===' '){e.preventDefault();open?choose(active):show();}
 }
 return <span className="custom-select"><button ref={trigger} type="button" role="combobox" aria-label={label} aria-expanded={open} aria-haspopup="listbox" aria-controls={open?id:undefined} aria-activedescendant={open?`${id}-${active}`:undefined} disabled={disabled} className="select-trigger" onClick={()=>open?close():show()} onKeyDown={key} onBlur={close}><span>{options[selected]?.label||'请选择'}</span><svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button>{open?createPortal(<div ref={menu} role="listbox" aria-label={label} id={id} className="select-menu" style={position||{visibility:'hidden'}}>{options.map((o,i)=><div key={o.value} id={`${id}-${i}`} role="option" aria-selected={i===selected} aria-disabled={o.disabled||undefined} data-index={i} data-active={i===active} onMouseEnter={()=>!o.disabled&&setActive(i)} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(i)}><span>{o.label}</span>{i===selected?<span aria-hidden="true">✓</span>:null}</div>)}</div>,trigger.current?.closest('dialog')||document.body):null}</span>;
}

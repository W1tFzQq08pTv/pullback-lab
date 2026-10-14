import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';

/** Hover on desktop; focus or tap on keyboard/touch. Kept outside clipping containers. */
export function Info({label,children}:{label:string;children:string}){
 const id=useId(),button=useRef<HTMLButtonElement>(null),tip=useRef<HTMLSpanElement>(null),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const [open,setOpen]=useState(false),[position,setPosition]=useState<{left:number;top:number}|null>(null);
 function show(){clearTimeout(timer.current);setOpen(true);}
 function close(){clearTimeout(timer.current);setOpen(false);setPosition(null);}
 function leave(){timer.current=setTimeout(close,120);}
 useLayoutEffect(()=>{if(!open||!button.current||!tip.current)return;const a=button.current.getBoundingClientRect(),b=tip.current.getBoundingClientRect();setPosition({left:Math.max(12,Math.min(a.left,window.innerWidth-b.width-12)),top:a.bottom+b.height+10<window.innerHeight?a.bottom+8:Math.max(12,a.top-b.height-8)});},[open,children]);
 useEffect(()=>{if(!open)return;const dismiss=(e:PointerEvent)=>{if(!button.current?.contains(e.target as Node)&&!tip.current?.contains(e.target as Node))close();};const key=(e:KeyboardEvent)=>{if(e.key==='Escape')close();};window.addEventListener('pointerdown',dismiss);window.addEventListener('keydown',key);window.addEventListener('resize',close);window.addEventListener('scroll',close,true);return()=>{window.removeEventListener('pointerdown',dismiss);window.removeEventListener('keydown',key);window.removeEventListener('resize',close);window.removeEventListener('scroll',close,true);};},[open]);
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 return <><button ref={button} type="button" className="info-button" aria-label={label} aria-describedby={open?id:undefined} onMouseEnter={show} onMouseLeave={leave} onFocus={show} onBlur={close} onClick={show}><svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><path d="M8 7v5M8 4v.2"/></svg></button>{open?createPortal(<span id={id} ref={tip} role="tooltip" className="info-tooltip" style={position||{left:0,top:0,visibility:'hidden'}} onMouseEnter={()=>clearTimeout(timer.current)} onMouseLeave={leave}>{children}</span>,button.current?.closest('dialog')||document.body):null}</>;
}

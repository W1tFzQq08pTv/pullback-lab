import {useEffect,useRef,useState} from 'react';

// Keep the chart in its existing React tree; only its layout changes.
export function useChartFocus(){
 const [full,setFull]=useState(false);
 const host=useRef<HTMLDivElement>(null),active=useRef(false),ownedFullscreen=useRef(false),locked=useRef(false);
 const previous=useRef<HTMLElement|null>(null),generation=useRef(0);
 const orientation=()=>screen.orientation as ScreenOrientation & {lock?:(value:string)=>Promise<void>};
 function release(){
  if(locked.current){orientation()?.unlock?.();locked.current=false;}
  if(ownedFullscreen.current){ownedFullscreen.current=false;if(document.fullscreenElement)void document.exitFullscreen().catch(()=>{});}
 }
 function close(){active.current=false;generation.current++;release();setFull(false);}
 async function open(){
  if(active.current)return;
  previous.current=document.activeElement as HTMLElement;active.current=true;setFull(true);
  const attempt=++generation.current;
  try{
   // Fullscreen the document so existing top-layer dialogs remain usable.
   if(!document.fullscreenElement&&document.documentElement.requestFullscreen){
    await document.documentElement.requestFullscreen();ownedFullscreen.current=true;
   }
   if(!active.current||generation.current!==attempt){release();return;}
   if(orientation()?.lock){await orientation().lock!('landscape');locked.current=true;}
   if(!active.current||generation.current!==attempt)release();
  }catch{/* A fixed viewport remains available when native fullscreen/lock is denied. */}
 }
 useEffect(()=>{
  if(!full)return;
  const overflow=document.body.style.overflow;document.body.style.overflow='hidden';
  const hidden=[...document.querySelectorAll<HTMLElement>('.app-header,.research-workspace > :not(.chart-terminal):not(dialog)')];
  const prior=hidden.map(el=>el.inert);hidden.forEach(el=>{el.inert=true;});
  host.current?.querySelector<HTMLButtonElement>('.chart-focus-exit')?.focus();
  const fullscreen=()=>{if(ownedFullscreen.current&&!document.fullscreenElement)close();};
  const key=(event:KeyboardEvent)=>{
   if(document.querySelector('dialog[open]'))return;
   if(event.key==='Escape'){event.preventDefault();close();}
   if(event.key==='Tab'){
    const items=[...host.current!.querySelectorAll<HTMLElement>('button:not(:disabled),[tabindex="0"]')].filter(el=>el.getClientRects().length);
    const first=items[0],last=items[items.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
   }
  };
  document.addEventListener('fullscreenchange',fullscreen);document.addEventListener('keydown',key);
  return()=>{document.removeEventListener('fullscreenchange',fullscreen);document.removeEventListener('keydown',key);document.body.style.overflow=overflow;hidden.forEach((el,i)=>{el.inert=prior[i];});previous.current?.focus({preventScroll:true});};
 },[full]);
 useEffect(()=>()=>{active.current=false;generation.current++;release();},[]);
 return {full,host,open,close};
}

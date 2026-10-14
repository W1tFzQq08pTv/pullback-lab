import {useEffect,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
type Tone='success'|'error'|'info';
type Toast={id:number;message:string;tone:Tone};
let items:Toast[]=[],sequence=0;
const listeners=new Set<()=>void>();
const subscribe=(fn:()=>void)=>{listeners.add(fn);return()=>{listeners.delete(fn);};};
const snapshot=()=>items;
function publish(){listeners.forEach(fn=>fn());}
function dismiss(id:number){items=items.filter(t=>t.id!==id);publish();}
export function notify(message:string,tone:Tone='info'){
 if(!message||items.some(t=>t.message===message&&t.tone===tone))return;
 items=[...items.slice(-2),{id:++sequence,message,tone}];publish();
}
/** Keep request state available for empty/retry views, but send feedback through the shared toast stack. */
export function useFeedback(tone:Tone='error'){
 const [message,setMessage]=useState('');
 return [message,(value:string)=>{setMessage(value);if(value)notify(value,tone);}] as const;
}
function Bubble({item}:{item:Toast}){
 const [paused,setPaused]=useState(false);
 useEffect(()=>{if(paused)return;const timer=setTimeout(()=>dismiss(item.id),item.tone==='error'?7000:4000);return()=>clearTimeout(timer);},[item.id,item.tone,paused]);
 return <div className="toast-bubble" data-tone={item.tone} role={item.tone==='error'?'alert':'status'} onMouseEnter={()=>setPaused(true)} onMouseLeave={()=>setPaused(false)} onFocus={()=>setPaused(true)} onBlur={()=>setPaused(false)}><span className="toast-icon" aria-hidden="true">{item.tone==='success'?'✓':item.tone==='error'?'!':'i'}</span><span>{item.message}</span><button type="button" aria-label="关闭通知" onClick={()=>dismiss(item.id)}>×</button></div>;
}
export function ToastHost(){
 const list=useSyncExternalStore(subscribe,snapshot);
 const [target,setTarget]=useState<Element>(document.body);
 useEffect(()=>{const update=()=>{const dialogs=document.querySelectorAll('dialog[open]');setTarget(dialogs[dialogs.length-1]||document.body);};update();const observer=new MutationObserver(update);observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});return()=>observer.disconnect();},[]);
 return createPortal(<div className="toast-stack" aria-label="操作通知">{list.map(item=><Bubble key={item.id} item={item}/>)}</div>,target);
}

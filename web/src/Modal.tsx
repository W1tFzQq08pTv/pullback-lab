import {useLayoutEffect,useRef,type ReactNode} from 'react';
export function Modal({title,onClose,children,className=''}:{title:string;onClose:()=>void;children:ReactNode;className?:string}){
 const ref=useRef<HTMLDialogElement>(null);
 useLayoutEffect(()=>{const dialog=ref.current!,previous=document.activeElement as HTMLElement;dialog.showModal();const before=document.body.style.overflow;document.body.style.overflow='hidden';return()=>{dialog.close();document.body.style.overflow=before;previous?.focus();};},[]);
 return <dialog ref={ref} className={"modal "+className} aria-label={title} onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===ref.current){const r=ref.current.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)onClose();}}}><div className="modal-heading"><h2>{title}</h2><button type="button" aria-label="关闭弹窗" onClick={onClose}>×</button></div>{children}</dialog>;
}

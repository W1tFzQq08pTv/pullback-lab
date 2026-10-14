import {useLayoutEffect,useRef} from 'react';
import {Skeleton} from './Loading';
// Fit the rendered text, not its character count: signs, commas and digits have different widths.
export function FitValue({value,tone='',loading=false,as:Tag='strong',fit:enabled=true}:{value:string;tone?:string;loading?:boolean;as?:'strong'|'b'|'span';fit?:boolean}){
 const box=useRef<HTMLElement>(null),text=useRef<HTMLSpanElement>(null);
 useLayoutEffect(()=>{
  const element=box.current,content=text.current;if(!element||!content||loading)return;
  const mobile=window.matchMedia('(max-width:600px)');
  const fit=()=>{
   element.style.removeProperty('font-size');element.removeAttribute('data-wrap');
   if(!mobile.matches||!enabled)return;
   const available=element.clientWidth,natural=content.getBoundingClientRect().width;
   if(!available||!natural||natural<=available)return;
   const base=parseFloat(getComputedStyle(element).fontSize);
   const size=Math.max(12,Math.floor(base*(available-1)/natural*10)/10);
   element.style.fontSize=`${size}px`;
   // Very extreme values remain readable and complete instead of shrinking below 12px.
   if(content.getBoundingClientRect().width>available)element.dataset.wrap='true';
  };
  fit();
  const observer=new ResizeObserver(fit);observer.observe(element);
  mobile.addEventListener('change',fit);window.addEventListener('resize',fit);
  let active=true;document.fonts.ready.then(()=>{if(active)fit();});
  return()=>{active=false;observer.disconnect();mobile.removeEventListener('change',fit);window.removeEventListener('resize',fit);element.style.removeProperty('font-size');element.removeAttribute('data-wrap');};
 },[value,loading,enabled]);
 return <Tag ref={box} className={`fit-value ${tone}`}>{loading?<Skeleton width="78%"/>:<span ref={text} className="fit-value-text">{value}</span>}</Tag>;
}

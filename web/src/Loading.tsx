import type {CSSProperties} from 'react';

export function Skeleton({width='100%',className=''}:{width?:string;className?:string}){
 return <span aria-hidden="true" className={`skeleton ${className}`} style={{width}}/>;
}
export function Loading({label='正在加载',chart=false}:{label?:string;chart?:boolean}){
 return <div className={chart?'loading-surface chart-skeleton':'loading-surface'} role="status" aria-label={label} aria-busy="true">
  <div className="loading-caption"><span className="loading-spinner" aria-hidden="true"/>{label}</div>
  {chart?<div className="skeleton-plot" aria-hidden="true">{[0,1,2,3].map(i=><div key={i} style={{'--row':i} as CSSProperties}><Skeleton width="32px"/><span/></div>)}<div className="skeleton-axis">{[0,1,2,3,4].map(i=><Skeleton key={i} width="42px"/>)}</div></div>:<div className="skeleton-lines"><Skeleton width="72%"/><Skeleton width="92%"/><Skeleton width="56%"/></div>}
 </div>;
}

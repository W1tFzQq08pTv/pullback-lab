import {useFeedback} from './Toast';
import {Loading} from './Loading';
import {useEffect,useState} from 'react';
import {api,type Stock} from './types';
import {Modal} from './Modal';
export function StockPicker({onClose,onSelect}:{onClose:()=>void;onSelect:(stock:Stock)=>void}){
 const [query,setQuery]=useState(''),[rows,setRows]=useState<Stock[]>([]),[loading,setLoading]=useState(true),[error,setError]=useFeedback();
 useEffect(()=>{let alive=true;setLoading(true);setError('');const timer=setTimeout(()=>{api<Stock[]>('/stocks?q='+encodeURIComponent(query)).then(r=>{if(alive)setRows(r);}).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoading(false);});},250);return()=>{alive=false;clearTimeout(timer);};},[query]);
 return <Modal title="选择股票" onClose={onClose}><input autoFocus type="search" aria-label="股票代码或名称" placeholder="代码、名称或拼音首字母" value={query} onChange={e=>setQuery(e.target.value)}/><div className="stock-results" aria-live="polite">{loading?<Loading label="正在搜索股票"/>:error?<p className="muted">加载失败，请重试</p>:rows.length?rows.map(s=><button key={s.symbol} className="stock-option" onClick={()=>onSelect(s)}><strong>{s.name}</strong><span>{s.symbol}</span><small>{s.cached?'本地已缓存':'未下载'}</small></button>):<p className="empty compact">未找到匹配的A股</p>}</div></Modal>;
}

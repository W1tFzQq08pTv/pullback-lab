import {useFeedback} from './Toast';
import {Loading} from './Loading';
import {useEffect,useState} from 'react';
import {api,type Stock} from './types';
import {Modal} from './Modal';
const historyKey='pullback.stock-search-history';
function readHistory():Stock[]{
 try{const saved=JSON.parse(localStorage.getItem(historyKey)||'[]');return Array.isArray(saved)?saved.filter((s:Stock)=>s&&typeof s.symbol==='string'&&typeof s.name==='string'&&typeof s.code==='string').slice(0,20):[];}catch{return [];}
}
export function StockPicker({onClose,onSelect}:{onClose:()=>void;onSelect:(stock:Stock)=>void}){
 const [recent,setRecent]=useState<Stock[]>(readHistory);
 function select(stock:Stock){const next=[stock,...readHistory().filter(s=>s.symbol!==stock.symbol)].slice(0,20);setRecent(next);try{localStorage.setItem(historyKey,JSON.stringify(next));}catch{}onSelect(stock);}
 const [query,setQuery]=useState(''),[rows,setRows]=useState<Stock[]>([]),[loading,setLoading]=useState(true),[error,setError]=useFeedback();
 useEffect(()=>{let alive=true;if(!query.trim()){setLoading(false);setRows([]);setError('');return;}setLoading(true);setError('');const timer=setTimeout(()=>{api<Stock[]>('/stocks?q='+encodeURIComponent(query)).then(r=>{if(alive)setRows(r);}).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoading(false);});},250);return()=>{alive=false;clearTimeout(timer);};},[query]);
 return <Modal title="选择股票" onClose={onClose}><input autoFocus type="search" aria-label="股票代码或名称" placeholder="代码、名称或拼音首字母" value={query} onChange={e=>setQuery(e.target.value)}/><div className="stock-results" aria-live="polite">{!query.trim()?<><p className="muted">最近搜索 · 仅保存在此浏览器</p>{recent.length?recent.map(s=><button key={s.symbol} className="stock-option" onClick={()=>select(s)}><strong>{s.name}</strong><span>{s.symbol}</span><small>最近选择</small></button>):<p className="empty compact">暂无搜索记录，输入代码或名称查找股票</p>}</>:loading?<Loading label="正在搜索股票"/>:error?<p className="muted">加载失败，请重试</p>:rows.length?rows.map(s=><button key={s.symbol} className="stock-option" onClick={()=>select(s)}><strong>{s.name}</strong><span>{s.symbol}</span><small>{s.cached?'本地已缓存':'未下载'}</small></button>):<p className="empty compact">未找到匹配的A股</p>}</div></Modal>;
}

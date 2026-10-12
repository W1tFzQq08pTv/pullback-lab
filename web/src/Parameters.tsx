import {Info} from './Info';
import {useState} from 'react';
import type {Params} from './types';
export function Parameters({value,onChange,onSave,onCancel}:{value:Params;onChange:(p:Params)=>void;onSave:()=>void;onCancel:()=>void}){
 const [error,setError]=useState('');
 const save=()=>{const bounds:Partial<Record<keyof Params,[number,number]>>={fast:[2,120],middle:[3,250],slow:[10,500],slope:[1,60],pullback:[1,30],capital:[1000,1e8],allocation:[0.000001,1],commission:[0,.01],min_commission:[0,100],slippage_bps:[0,100]};for(const [key,[min,max]] of Object.entries(bounds)){const n=value[key as keyof Params];if(typeof n!=='number'||!Number.isFinite(n)||n<min||n>max||(['fast','middle','slow','slope','pullback'].includes(key)&&!Number.isInteger(n))){setError('请检查参数：均线与观察期须为允许范围内的整数，资金及费用不得留空或超出范围');return;}}if(!value.start||!value.end||value.start>value.end||value.start<'2016-01-01'){setError('请设置2016年起的有效日期区间');return;}if(!(value.fast>=2&&value.fast<value.middle&&value.middle<value.slow&&value.slow<=500)){setError('均线周期必须满足 2 ≤ 短期 < 中期 < 长期 ≤ 500');return;}if(!(value.capital>=1000&&value.allocation>0&&value.allocation<=1&&value.commission>=0&&value.min_commission>=0&&value.slippage_bps>=0)){setError('请检查资金、仓位和费用设置');return;}onSave();};
 const set=(key:keyof Params,v:unknown)=>onChange({...value,[key]:v});
 const field=(key:keyof Params,label:string,step=1)=> <label key={key}>{label}<input type="number" step={step} value={String(value[key])} onChange={e=>set(key,e.target.value===''?'':Number(e.target.value))}/></label>;
 return <div className="parameter-panel"><div className="section-title"><h3>均线回调策略</h3><Info label="策略说明">均线回调：上涨趋势中回踩均线，反弹确认后买入。沪深300趋势过滤仅影响开仓。</Info></div><div className="fields">
 <label>开始日期<input type="date" value={value.start} onInput={e=>set('start',e.currentTarget.value)}/></label><label>结束日期<input type="date" value={value.end} onInput={e=>set('end',e.currentTarget.value)}/></label>
 <div className="field-pair">{field('fast','短期均线')}{field('middle','中期均线')}</div><div className="field-pair">{field('slow','长期均线')}{field('slope','斜率观察期')}</div>{field('pullback','回调观察期 / 日')}
 <label className="check"><input type="checkbox" checked={value.market_filter} onChange={e=>set('market_filter',e.target.checked)}/>沪深300趋势过滤</label>
 <label className="check"><input type="checkbox" checked={value.allow_suffix!==false} onChange={e=>set('allow_suffix',e.target.checked)}/>数据无法修复时，使用缺失之后的完整区间</label><p className="muted">保留原缓存，舍弃问题日期及之前的数据参与本次回测；重新预热后开始，实际区间会明确标注。</p><div className="divider"/><div className="field-pair">{field('capital','初始资金 / 元',1000)}{field('allocation','目标仓位 / 0–1',.1)}</div>
 <details><summary>费用设置</summary><div className="fee-help"><Info label="费用说明">佣金含经手费；印花税和过户费按历史规则计算。滑点单位为基点，1基点等于0.01%。</Info></div><div className="fields">{field('commission','佣金率',.0001)}{field('min_commission','最低佣金 / 元')}{field('slippage_bps','单边滑点 / 基点')}</div></details>
 {error?<p role="alert">{error}</p>:null}<div className="modal-actions"><button type="button" onClick={onCancel}>取消</button><button className="primary" onClick={save}>保存设置</button></div></div></div>
}

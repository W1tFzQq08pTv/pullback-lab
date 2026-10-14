import {useFeedback} from './Toast';
import {useRef,useState} from 'react';
import {api,type Task} from './types';

export function WorkflowProgress({task,onUpdate,onDismiss,resultLoading=false,onRetry,retryDisabled=false}:{onRetry:()=>Promise<void>;retryDisabled?:boolean;task:Task;resultLoading?:boolean;onUpdate:(t:Task)=>void;onDismiss:()=>void}){
 const [stopping,setStopping]=useState(false),[,setError]=useFeedback();
 const retryLock=useRef(false);
 const [retrying,setRetrying]=useState(false);
 async function retry(){if(retryLock.current||retryDisabled)return;retryLock.current=true;setRetrying(true);try{await onRetry();}finally{retryLock.current=false;setRetrying(false);}}
 const active=['queued','running','cancelling'].includes(task.status);
 const cancelling=stopping||task.status==='cancelling';
 async function stop(){
  setStopping(true);setError('');
  try{await api(`/tasks/${task.id}/cancel`,{});onUpdate(await api<Task>(`/tasks/${task.id}`));}
  catch(e){setError((e as Error).message);}
  finally{setStopping(false);}
 }
 return <section className="workflow-progress" data-active={active} aria-label="一键研究进度">
  <div className="workflow-heading"><strong>{task.result?.reason==='insufficient_history'?'等待更多行情':task.status==='completed'?'已完成全部步骤':task.status==='cancelled'?'任务已终止':task.status==='failed'?'流程未完成':'为你准备完整回测'}<small>{task.result?.symbol}</small></strong></div>
  <ol className="workflow-steps">{task.result?.steps?.map((step,i)=><li key={step.id} data-status={step.status} aria-current={i===task.result?.step?'step':undefined}><span className={step.status==='running'&&active?'loading-spinner':'step-indicator'} aria-hidden="true">{step.status==='completed'?'✓':step.status==='failed'?'!':step.status==='cancelled'?'−':step.status==='running'&&active?'':i+1}</span><span className="workflow-step-copy"><b>{step.status==='waiting_data'?'历史行情不足':step.label}</b><small>{step.status==='pending'?'等待前序步骤':step.message||(step.status==='running'?task.message:'')}</small></span></li>)}</ol>
  <div className="workflow-status" role="status"><span>{cancelling?'正在终止，已完成的数据将保留':task.message}</span>{active?<span className="workflow-percent">{task.progress}%</span>:null}</div>
  {active?<progress aria-label="一键研究总体进度" max="100" value={task.progress}/>:null}
  <div className="workflow-actions">{active?<><span>关闭窗口后仍会继续运行</span><button className="workflow-stop" disabled={cancelling} onClick={stop}>{cancelling?'正在终止…':'终止任务'}</button></>:<><span>{task.status==='completed'?'最优参数已保存，后续自动复用':'已保存的数据与参数仍可复用'}</span><div className="workflow-action-buttons"><button className={task.status==='completed'?'primary':''} disabled={resultLoading||retrying} onClick={onDismiss}>{resultLoading?'正在载入结果…':task.status==='completed'?'查看结果':'返回图表'}</button>{['failed','cancelled'].includes(task.status)?<button className="primary" disabled={retryDisabled||retrying} onClick={retry}>{retrying?<><span className="loading-spinner" aria-hidden="true"/>正在重试…</>:'重试'}</button>:null}</div></>}</div>
  
 </section>;
}

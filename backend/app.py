import csv
import io
import json
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import store
from .models import Parameters, SyncRequest
from .stocks import get_stock, search, normalize
from .quality import eligible
from .sync import synchronize
from .engine import backtest
from .signals import latest_signal
from .repair import repair_snapshot, recent_attempt, GAPS, REPAIRABLE
from .fallback import prepare

LOCK=threading.Lock()
@asynccontextmanager
async def lifespan(app):
    store.init()
    from .pools import init as init_pools
    init_pools()
    yield
app=FastAPI(title='回调研究室',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

@app.middleware('http')
async def local_origin(request:Request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in ('http://127.0.0.1:5173','http://localhost:5173','http://127.0.0.1:8765'):
        return Response('不接受外部站点的写入请求',status_code=403)
    return await call_next(request)

def spawn(kind,fn):
    if not LOCK.acquire(blocking=False):raise HTTPException(409,'已有同步或回测任务运行中')
    ident=uuid.uuid4().hex
    with store.connect() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(ident,kind,'queued',0,'等待执行',store.now(),None))
    def work():
        try:fn(ident)
        except Exception as exc:store.task_update(ident,'failed',message=str(exc))
        finally:LOCK.release()
    threading.Thread(target=work,daemon=True).start()
    return dict(task_id=ident)

@app.get('/api/overview')
def overview(symbol:str="002028.SZ"):
    symbol=normalize(symbol)
    s=store.latest(symbol=symbol)
    default=Parameters(symbol=symbol).model_dump(mode='json')
    try:stock=(s['payload'].get('stock') if s else None) or (dict(symbol='002028.SZ',code='002028',name='思源电气',pinyin='sydq',org_id='gssz0002028') if symbol=='002028.SZ' else get_stock(symbol))
    except Exception as exc:raise HTTPException(400,str(exc))
    with store.connect() as db:
        active=db.execute("SELECT id FROM tasks WHERE status IN ('queued','running') ORDER BY rowid DESC LIMIT 1").fetchone()
    if not s:return dict(stock=stock,snapshot=None,defaults=default,active_task=active['id'] if active else None)
    data=s['payload'];end=date.fromisoformat(data['end'])
    default.update(end=str(end),start=str(end.replace(year=end.year-10)),snapshot_id=s['id'])
    return dict(stock=stock,snapshot=dict(id=s['id'],created=s['created'],start=data['start'],end=max((r['date'] for r in data['bars']),default=None),target_end=data['end'],bars=len(data['bars']),events=len(data['actions']),errors=sum(i['severity']=='error' for i in data['quality'])),defaults=default,active_task=active['id'] if active else None)

@app.post('/api/sync')
def sync(p:SyncRequest):
    try:stock=get_stock(p.symbol)
    except Exception as exc:raise HTTPException(400,str(exc))
    return spawn('sync',lambda ident:synchronize(ident,stock,p.force))

@app.get('/api/stocks')
def stocks(q:str=''):
    if len(q)>50:raise HTTPException(400,'搜索内容过长')
    try:return search(q)
    except Exception as exc:raise HTTPException(503,'股票目录暂不可用：'+str(exc))

@app.get('/api/tasks/{ident}')
def task(ident:str):
    with store.connect() as db:row=db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'任务不存在')
    return {**dict(row),'result':json.loads(row['result']) if row['result'] else None}

@app.get('/api/quality')
def quality(snapshot_id:str|None=None,symbol:str="002028.SZ"):
    s=store.latest(snapshot_id,symbol=normalize(symbol))
    if not s:return dict(issues=[],actions=[],snapshot_id=None)
    report=recent_attempt(s['id'],max_age=None)
    if report:report={**report,'confirmed_total':len(s['payload'].get('suspensions',[])),'evidence':s['payload'].get('suspension_evidence',[])}
    return dict(issues=s['payload']['quality'],actions=s['payload']['actions'],snapshot_id=s['id'],repair=report,source_reports=s['payload'].get('source_reports',[]))

@app.get('/api/bars')
def bars(snapshot_id:str|None=None,symbol:str="002028.SZ"):
    s=store.latest(snapshot_id,symbol=normalize(symbol))
    return s['payload']['bars'] if s else []

@app.post('/api/signals/latest')
def signal_latest(p:Parameters):
    # Always use the latest cached stock snapshot, never a historical run snapshot.
    s=store.latest(symbol=p.symbol)
    if not s:raise HTTPException(409,'请先同步数据')
    return latest_signal(s,p)

@app.post('/api/repair')
def repair(p:Parameters,force:bool=False):
    s=store.latest(p.snapshot_id,symbol=p.symbol)
    if not s:raise HTTPException(409,'请先同步数据')
    if s['payload'].get('symbol','002028.SZ')!=p.symbol:raise HTTPException(422,'股票与数据快照不一致')
    def work(ident):
        fixed,report=repair_snapshot(s,lambda n,m:store.task_update(ident,progress=n,message=m),force=force)
        message=f'修复检查完成：补回{len(report["filled"])}根行情，确认{len(report["suspensions"])}个停牌日；仍有{report["remaining"]}个缺口、{report.get("other_errors",0)}项其他数据问题'
        store.task_update(ident,'completed',100,message,dict(snapshot_id=fixed['id'],repair=report))
    return spawn('repair',work)

@app.post('/api/backtests')
def create_run(p:Parameters):
    s=store.latest(p.snapshot_id,symbol=p.symbol)
    if not s:raise HTTPException(409,dict(message='请先同步数据',issues=[]))
    problems=eligible(s['payload'],p)
    if problems and not p.allow_suffix and not any(i['code'] in REPAIRABLE for i in problems):
        raise HTTPException(422,dict(message='数据校验未通过，回测已阻止',issues=problems))
    def run(ident):
        selected=s;report=None;parameters=p
        if problems and any(i['code'] in REPAIRABLE for i in problems):
            selected,report=repair_snapshot(s,lambda n,m:store.task_update(ident,progress=min(n,80),message=m))
            parameters=p.model_copy(update={'snapshot_id':selected['id']})
        _,parameters,fallback,remaining=prepare(selected['payload'],parameters)
        if remaining:
            detail='；'.join(f'{i["date"] or ""} {i["message"]}' for i in remaining[:4])
            store.task_update(ident,'failed',100,'修复或完整区间兜底仍未通过：'+detail,dict(issues=remaining,repair=report,snapshot_id=selected['id']))
            return
        store.task_update(ident,progress=90 if report else 15,message='数据校验通过，逐日计算信号、成交和公司行动')
        result=backtest(selected['payload'],parameters)
        if fallback:result['fallback']=fallback
        with store.connect() as db:
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(ident,store.now(),selected['id'],store.dumps(parameters.model_dump(mode='json')),store.dumps(result)))
        store.task_update(ident,'completed',100,'回测完成',dict(run_id=ident,repair=report))
    return spawn('backtest',run)

@app.get('/api/backtests')
def runs(symbol:str="002028.SZ"):
    with store.connect() as db:rows=db.execute("SELECT id,created,snapshot_id,params FROM runs WHERE coalesce(json_extract(params,'$.symbol'),'002028.SZ')=? ORDER BY rowid DESC",(normalize(symbol),)).fetchall()
    return [{**dict(r),'params':json.loads(r['params'])} for r in rows]

@app.get('/api/backtests/{ident}')
def get_run(ident:str):
    with store.connect() as db:row=db.execute('SELECT * FROM runs WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'回测不存在')
    return {**dict(row),'params':json.loads(row['params']),'result':json.loads(row['result'])}

@app.get('/api/backtests/{ident}/export')
def export(ident:str,kind:str='trades',book:str='strategy'):
    if kind not in ('trades','ledger','curve','rejected') or book not in ('strategy','benchmark'):raise HTTPException(400,'不支持的导出类型')
    rows=get_run(ident)['result'][book][kind]
    stream=io.StringIO();stream.write('\ufeff')
    if rows:
        writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
    return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{ident}-{book}-{kind}.csv"'})

# Stock-pool research: no brokerage/account actions.
from . import pools as pool_service
from .pools import PoolCreate, MemberCreate, MemberRemove, ExperimentRequest

@app.get('/api/pools')
def list_pools():return pool_service.pools()

@app.post('/api/pools')
def create_pool(p:PoolCreate):
    if not p.name.strip():raise HTTPException(400,'股票池名称不能为空')
    ident=uuid.uuid4().hex
    with store.connect() as db:db.execute('INSERT INTO pools VALUES(?,?,?)',(ident,p.name.strip(),store.now()))
    return dict(id=ident)

def find_pool(ident):
    pool=next((x for x in pool_service.pools() if x['id']==ident),None)
    if not pool:raise HTTPException(404,'股票池不存在')
    return pool

@app.post('/api/pools/{ident}/members')
def add_member(ident:str,p:MemberCreate):
    pool=find_pool(ident)
    if len(pool['members'])>=100:raise HTTPException(400,'单池最多100条成员记录')
    if any(m['symbol']==p.symbol and (not m['removed'] or m['removed']>str(p.effective)) for m in pool['members']):raise HTTPException(409,'成员有效期重叠')
    s=store.latest(symbol=p.symbol)
    try:stock=(s['payload'].get('stock') if s else None) or get_stock(p.symbol)
    except Exception as exc:raise HTTPException(400,'股票目录暂不可用：'+str(exc))
    member_id=uuid.uuid4().hex
    with store.connect() as db:db.execute('INSERT INTO pool_members VALUES(?,?,?,?,?,?,?,?)',(member_id,ident,p.symbol,stock['name'],str(p.effective),None,store.now(),int(p.retrospective)))
    return dict(id=member_id)

@app.post('/api/pools/{ident}/members/{member_id}/remove')
def remove_member(ident:str,member_id:str,p:MemberRemove):
    pool=find_pool(ident);m=next((m for m in pool['members'] if m['id']==member_id),None)
    if not m:raise HTTPException(404,'成员不存在')
    if m['removed']:raise HTTPException(409,'该成员已移出，历史记录保留')
    if str(p.effective)<m['added'] or str(p.effective)<pool_service.today():raise HTTPException(400,'移出日期不可早于加入日期或今天')
    with store.connect() as db:db.execute('UPDATE pool_members SET removed=? WHERE id=?',(str(p.effective),member_id))
    return dict(ok=True)

@app.post('/api/pools/{ident}/sync')
def sync_pool(ident:str):
    pool=find_pool(ident)
    def work(task_id):
        outcomes=[]
        members={m['symbol']:m for m in pool['members'] if not m['removed'] or m['removed']>pool_service.today()}
        for symbol,m in members.items():
            child=uuid.uuid4().hex
            with store.connect() as db:db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(child,'pool-sync-item','running',0,symbol,store.now(),None))
            store.task_update(task_id,progress=int(90*len(outcomes)/max(1,len(members))),message='同步 '+m['name'])
            try:
                s=store.latest(symbol=symbol);stock=(s['payload'].get('stock') if s else None) or get_stock(symbol)
                synchronize(child,stock,False)
                with store.connect() as db:child_result=db.execute('SELECT status,message FROM tasks WHERE id=?',(child,)).fetchone()
                outcomes.append(dict(symbol=symbol,status=child_result['status'],reason=child_result['message']))
            except Exception as exc:
                store.task_update(child,'failed',message=str(exc));outcomes.append(dict(symbol=symbol,status='failed',reason=str(exc)))
        store.task_update(task_id,'failed' if any(x['status']=='failed' for x in outcomes) else 'completed',100,'股票池同步结束，请查看逐股结果',dict(items=outcomes))
    return spawn('pool-sync',work)

@app.post('/api/pools/{ident}/experiments')
def create_experiment(ident:str,p:ExperimentRequest):
    pool=find_pool(ident)
    if not pool['members']:raise HTTPException(400,'请先添加股票')
    def work(task_id):
        result=pool_service.experiment(pool,p,lambda n,m:store.task_update(task_id,progress=n,message=m))
        with store.connect() as db:db.execute('INSERT INTO experiments VALUES(?,?,?,?,?)',(task_id,ident,store.now(),store.dumps(p.model_dump(mode='json')),store.dumps(result)))
        store.task_update(task_id,'completed',100,'研究完成；受阻股票单独列出',dict(experiment_id=task_id))
    return spawn('experiment',work)

@app.get('/api/pools/{ident}/experiments')
def list_experiments(ident:str):
    find_pool(ident)
    with store.connect() as db:rows=db.execute('SELECT id,created,request FROM experiments WHERE pool_id=? ORDER BY rowid DESC',(ident,)).fetchall()
    return [{**dict(r),'request':json.loads(r['request'])} for r in rows]

@app.get('/api/experiments/{ident}')
def get_experiment(ident:str):
    with store.connect() as db:r=db.execute('SELECT * FROM experiments WHERE id=?',(ident,)).fetchone()
    if not r:raise HTTPException(404,'研究结果不存在')
    return {**dict(r),'result':json.loads(r['result']),'request':json.loads(r['request'])}

@app.get('/api/experiments/{ident}/export')
def export_experiment(ident:str):
    result=get_experiment(ident)['result'];rows=[]
    for stock in result['results']:
        for name,variant in stock.get('variants',{}).items():
            for trade in variant['diagnostics']:
                rows.append(dict(symbol=stock['symbol'],variant=name,start=stock['params']['start'],end=stock['params']['end'],snapshot_id=stock['snapshot_id'],**{k:store.dumps(v) if isinstance(v,dict) else v for k,v in trade.items()}))
    stream=io.StringIO();stream.write('\ufeff')
    if rows:
        fields=list(dict.fromkeys(k for r in rows for k in r));writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{ident}-diagnostics.csv"'})

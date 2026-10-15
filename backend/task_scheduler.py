"""Bounded queue, request deduplication and stock-resource exclusion."""
import fcntl
import hashlib
import json
import os
import threading
import time
import uuid
from fastapi import HTTPException
from . import store
from .logging_setup import log

ACTIVE=('queued','running','cancelling')
LIMIT=max(1,min(4,int(os.environ.get('PULLBACK_TASK_CONCURRENCY','2'))))
CONDITION=threading.Condition()
FUNCTIONS={}
THREADS=[]
STOP=threading.Event()
OWNER=None

def acquire_owner():
    global OWNER
    OWNER=(store.DATA/'scheduler.lock').open('a')
    try:fcntl.flock(OWNER,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        OWNER.close();OWNER=None
        raise RuntimeError('同一数据目录只能运行一个 API 调度进程；请使用单 worker，任务并发由调度器管理')

def init():
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS task_jobs(id TEXT PRIMARY KEY, fingerprint TEXT, resources TEXT, state TEXT, submitted REAL)')
        db.execute("UPDATE task_jobs SET state='done' WHERE state!='done'")
    STOP.clear()
    for i in range(LIMIT):
        thread=threading.Thread(target=worker,name=f'task-worker-{i}',daemon=True);THREADS.append(thread);thread.start()
    log.info('scheduler ready concurrency=%s queue_limit=64',LIMIT)

def submit(kind, resources, request, fn, result=None):
    resources=sorted(set(resources))
    fingerprint=hashlib.sha256(store.dumps([kind,resources,request]).encode()).hexdigest()
    with CONDITION,store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if STOP.is_set():raise HTTPException(503,'服务正在停止，请稍后重试')
        rows=db.execute("SELECT j.*,t.status FROM task_jobs j JOIN tasks t ON t.id=j.id WHERE j.state!='done' ORDER BY j.submitted").fetchall()
        for row in rows:
            if row['fingerprint']==fingerprint and row['status'] in ('queued','running'):
                log.info('task reused id=%s kind=%s resources=%s status=%s',row['id'],kind,','.join(resources),row['status'])
                return dict(task_id=row['id'],reused=True,status=row['status'])
        if sum(r['state']=='queued' for r in rows)>=64:raise HTTPException(429,'任务队列已满，请稍后重试')
        ident=uuid.uuid4().hex
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(ident,kind,'queued',0,'已排队，等待执行',store.now(),store.dumps(result) if result is not None else None))
        db.execute('INSERT INTO task_jobs VALUES(?,?,?,?,?)',(ident,fingerprint,store.dumps(resources),'queued',time.time()))
        db.commit();FUNCTIONS[ident]=fn;CONDITION.notify_all()
    log.info('task queued id=%s kind=%s resources=%s request=%s',ident,kind,','.join(resources),store.dumps(request))
    return dict(task_id=ident,reused=False,status='queued')

def claim():
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for ident in list(FUNCTIONS):
            state=db.execute('SELECT state FROM task_jobs WHERE id=?',(ident,)).fetchone()
            if state and state['state']=='done':FUNCTIONS.pop(ident,None)
        rows=db.execute("SELECT j.*,t.status,t.kind FROM task_jobs j JOIN tasks t ON t.id=j.id WHERE j.state!='done' ORDER BY j.submitted,j.rowid").fetchall()
        held=set();running=0
        for row in rows:
            if row['state']=='running':held.update(json.loads(row['resources']));running+=1
        if running>=LIMIT:return None
        waiting=set()
        for row in rows:
            if row['state']!='queued':continue
            ident=row['id'];resources=set(json.loads(row['resources']))
            if row['status'] not in ('queued','running'):
                if row['status']=='cancelling':db.execute("UPDATE tasks SET status='cancelled',message='已取消排队' WHERE id=?",(ident,))
                db.execute("UPDATE task_jobs SET state='done' WHERE id=?",(ident,));FUNCTIONS.pop(ident,None);continue
            if resources & (held|waiting):waiting.update(resources);continue
            fn=FUNCTIONS.pop(ident,None)
            if fn is None:continue
            db.execute("UPDATE task_jobs SET state='running' WHERE id=?",(ident,))
            db.execute("UPDATE tasks SET status='running',message='开始执行' WHERE id=?",(ident,))
            return ident,row['kind'],fn
    return None

def worker():
    while not STOP.is_set():
        with CONDITION:
            job=claim()
            if job is None:CONDITION.wait(timeout=.5);continue
        ident,kind,fn=job;started=time.monotonic();log.info('task started id=%s kind=%s',ident,kind)
        try:fn(ident)
        except InterruptedError:
            store.task_update(ident,'cancelled',message='参数寻优已终止，已保存参数保持不变')
        except Exception as exc:
            log.exception('task failed id=%s kind=%s',ident,kind)
            with store.connect() as db:
                old=db.execute('SELECT result FROM tasks WHERE id=?',(ident,)).fetchone()
            store.task_update(ident,'failed',message=str(exc),result=json.loads(old['result']) if old and old['result'] else None)
        finally:
            with CONDITION,store.connect() as db:
                db.execute("UPDATE task_jobs SET state='done' WHERE id=?",(ident,))
                row=db.execute('SELECT status,message FROM tasks WHERE id=?',(ident,)).fetchone()
                CONDITION.notify_all()
            (log.error if row['status']=='failed' else log.info)('task finished id=%s kind=%s status=%s seconds=%.1f message=%s',ident,kind,row['status'],time.monotonic()-started,row['message'])

def shutdown():
    STOP.set()
    with CONDITION:CONDITION.notify_all()
    for thread in THREADS:thread.join(timeout=2)
    THREADS.clear()
    # Keep ownership until process exit: a non-cancellable operation may still be finishing.
    log.info('scheduler stopping')

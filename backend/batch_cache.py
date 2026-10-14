"""Durable cache-only batches; each symbol shares the normal resource scheduler.

Pause stops new dispatch; running symbols finish their bounded downloads. Restart
pauses batches and requeues interrupted members. Resume is explicit and never
redownloads successful members. No optimization or backtest is invoked here.
"""
import hashlib
import json
import shutil
import threading
import time
import uuid
from collections import Counter
from . import store,task_scheduler
from .logging_setup import log
from .sync import synchronize

STOP=threading.Event()
THREAD=None
CONTROL=threading.RLock()
TERMINAL=('complete','review','failed')

def init():
    global THREAD
    with store.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS cache_batches(id TEXT PRIMARY KEY,created TEXT,state TEXT,concurrency INTEGER,manifest TEXT,baseline TEXT,seconds REAL DEFAULT 0,started REAL);
        CREATE TABLE IF NOT EXISTS cache_members(batch_id TEXT,symbol TEXT,stock TEXT,state TEXT,task_id TEXT,attempts INTEGER DEFAULT 0,seconds REAL DEFAULT 0,result TEXT,PRIMARY KEY(batch_id,symbol));
        ''')
        now=time.time()
        db.execute("UPDATE cache_batches SET seconds=seconds+max(0,?-coalesce(started,?)),started=NULL,state='paused' WHERE state IN ('running','pausing')",(now,now))
        db.execute("UPDATE cache_members SET state='pending',task_id=NULL WHERE state='running'")
    STOP.clear();THREAD=threading.Thread(target=dispatch,daemon=True,name='cache-batch-dispatch');THREAD.start()

def disk_bytes():
    return sum(p.stat().st_size for p in store.DATA.rglob('*') if p.is_file())

def create(stocks,concurrency=4):
    if not 1<=concurrency<=4:raise ValueError('并发范围为1至4')
    if not 1<=len(stocks)<=10000:raise ValueError('批量标的数量应为1至10000')
    if len({s['symbol'] for s in stocks})!=len(stocks):raise ValueError('批量标的不能重复')
    if shutil.disk_usage(store.DATA).free<2*1024**3:raise ValueError('可用磁盘不足2GB，暂停批量下载')
    ident=uuid.uuid4().hex
    from .sources import cutoff_date
    cutoff=cutoff_date()
    stocks=[{**s,'cache_cutoff':cutoff} for s in stocks]
    baseline=dict(bytes=disk_bytes(),free=shutil.disk_usage(store.DATA).free,cutoff=cutoff)
    with CONTROL,store.connect() as db:
        db.execute('INSERT INTO cache_batches VALUES(?,?,?,?,?,?,?,?)',(ident,store.now(),'running',concurrency,store.dumps(stocks),store.dumps(baseline),0,time.time()))
        for s in stocks:db.execute('INSERT INTO cache_members(batch_id,symbol,stock,state) VALUES(?,?,?,?)',(ident,s['symbol'],store.dumps(s),'pending'))
    log.info('cache batch created id=%s symbols=%s concurrency=%s',ident,len(stocks),concurrency)
    return ident

def control(ident,action):
    with CONTROL,store.connect() as db:
        row=db.execute('SELECT * FROM cache_batches WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('批量任务不存在')
        if action=='pause':
            if row['state']=='running':db.execute("UPDATE cache_batches SET state='pausing' WHERE id=?",(ident,))
        elif action=='resume':
            if row['state'] not in ('running','pausing'):
                db.execute("UPDATE cache_batches SET state='running',started=? WHERE id=?",(time.time(),ident))
        elif action=='retry':
            if row['state'] in ('running','pausing'):raise ValueError('请先暂停并等待在途任务结束')
            db.execute("UPDATE cache_members SET state='pending',task_id=NULL WHERE batch_id=? AND state IN ('failed','review')",(ident,))
            db.execute("UPDATE cache_batches SET state='running',started=? WHERE id=?",(time.time(),ident))
        else:raise ValueError('未知操作')
    return status(ident)

def status(ident,details=True):
    with store.connect() as db:
        row=db.execute('SELECT * FROM cache_batches WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('批量任务不存在')
        members=[dict(r) for r in db.execute('SELECT symbol,state,attempts,seconds,result FROM cache_members WHERE batch_id=? ORDER BY symbol',(ident,))]
    for m in members:m['result']=json.loads(m['result']) if m['result'] else None
    seconds=row['seconds']+(time.time()-row['started'] if row['started'] else 0)
    out=dict(id=ident,created=row['created'],state=row['state'],concurrency=row['concurrency'],seconds=round(seconds,2),counts=dict(Counter(m['state'] for m in members)),total=len(members),baseline=json.loads(row['baseline']))
    if details:out['members']=members
    return out

def run_member(ident,symbol,task,stock):
    started=time.monotonic()
    try:
        synchronize(task,stock,cache_only=True)
        with store.connect() as db:r=db.execute('SELECT status,message,result FROM tasks WHERE id=?',(task,)).fetchone()
        result=json.loads(r['result']) if r['result'] else {}
        if r['status']!='completed':raise ValueError(r['message'])
        snapshot=store.latest(result['snapshot_id']);p=snapshot['payload']
        errors=[i for i in p['quality'] if i['severity']=='error']
        state='review' if errors else 'complete'
        result.update(market_errors=dict(Counter(i['code'] for i in errors if i['code'] in ('missing','zero_volume','duplicate','null','ohlc','calendar','conflict','source_conflict','price_jump'))),bars=len(p['bars']),first=min((b['date'] for b in p['bars']),default=None),last=max((b['date'] for b in p['bars']),default=None),errors=dict(Counter(i['code'] for i in errors)),warnings=dict(Counter(i['code'] for i in p['quality'] if i['severity']=='warning')),issues=errors[:12],asset_type=stock.get('asset_type','stock'))
        if not p['bars']:state='failed';result['message']='行情源未返回有效日线'
    except Exception as exc:
        state='failed';result=dict(message=str(exc))
        store.task_update(task,'failed',message=str(exc))
        log.exception('cache member failed batch=%s symbol=%s',ident,symbol)
    elapsed=time.monotonic()-started
    with store.connect() as db:db.execute('UPDATE cache_members SET state=?,seconds=seconds+?,result=? WHERE batch_id=? AND symbol=?',(state,elapsed,store.dumps(result),ident,symbol))
    log.info('cache member finished batch=%s symbol=%s state=%s seconds=%.2f bars=%s errors=%s',ident,symbol,state,elapsed,result.get('bars',0),result.get('errors',{}))

def dispatch_once():
    with CONTROL:
        with store.connect() as db: batches=[dict(r) for r in db.execute("SELECT * FROM cache_batches WHERE state IN ('running','pausing') ORDER BY created")]
        for b in batches:
            with store.connect() as db:
                members=[dict(r) for r in db.execute('SELECT * FROM cache_members WHERE batch_id=?',(b['id'],))]
            running=[m for m in members if m['state']=='running'];pending=[m for m in members if m['state']=='pending']
            if not running and (b['state']=='pausing' or not pending):
                state='paused' if pending else 'completed'
                with store.connect() as db:db.execute('UPDATE cache_batches SET state=?,seconds=seconds+?-coalesce(started,?),started=NULL WHERE id=?',(state,time.time(),time.time(),b['id']))
                report=status(b['id']);report['disk_bytes']=disk_bytes();report['disk_growth']=report['disk_bytes']-report['baseline']['bytes']
                folder=store.DATA/'batches';folder.mkdir(exist_ok=True)
                path=folder/(b['id']+'.json');temporary=path.with_suffix('.tmp');temporary.write_text(store.dumps(report));temporary.replace(path)
                log.info('cache batch %s id=%s counts=%s seconds=%s',state,b['id'],report['counts'],report['seconds'])
                continue
            if b['state']!='running':continue
            if shutil.disk_usage(store.DATA).free<2*1024**3:
                control(b['id'],'pause');continue
            for member in pending[:max(0,b['concurrency']-len(running))]:
                stock=json.loads(member['stock']);ident=b['id'];symbol=member['symbol']
                # Mark before submit: a fast cached task may finish immediately.
                with store.connect() as db:db.execute("UPDATE cache_members SET state='running',attempts=attempts+1 WHERE batch_id=? AND symbol=?",(ident,symbol))
                try:
                    result=task_scheduler.submit('batch-cache',[symbol],dict(batch_id=ident,symbol=symbol),lambda task,i=ident,s=symbol,v=stock:run_member(i,s,task,v))
                    with store.connect() as db:db.execute('UPDATE cache_members SET task_id=? WHERE batch_id=? AND symbol=?',(result['task_id'],ident,symbol))
                except Exception:
                    with store.connect() as db:db.execute("UPDATE cache_members SET state='pending',attempts=attempts-1 WHERE batch_id=? AND symbol=?",(ident,symbol))
                    raise

def dispatch():
    while not STOP.is_set():
        try:dispatch_once()
        except Exception:log.exception('cache dispatcher failed; will retry')
        STOP.wait(1)

def shutdown():
    STOP.set()
    if THREAD:THREAD.join(timeout=3)
    with store.connect() as db:db.execute("UPDATE cache_batches SET state='paused',seconds=seconds+?-coalesce(started,?),started=NULL WHERE state IN ('running','pausing')",(time.time(),time.time()))

def sample100():
    from .stocks import directory
    from .trading_rules import board
    groups={k:[] for k in ('sh_main','sz_main','chinext','star','beijing','etf')}
    for s in directory():
        if 'ST' in s['name'].upper() or '退' in s['name']:continue
        k='etf' if s.get('asset_type')=='etf' else board(s['symbol'])
        if k=='main':k='sh_main' if s['symbol'].endswith('.SH') else 'sz_main'
        if k in groups:groups[k].append(s)
    manifest=[]
    for key,n in dict(sh_main=25,sz_main=25,chinext=20,star=10,beijing=10,etf=10).items():
        rows=sorted(groups[key],key=lambda s:hashlib.sha256(('cache-pilot-v1:'+s['symbol']).encode()).hexdigest())
        if len(rows)<n:raise ValueError('样本目录不足：'+key)
        manifest.extend({**s,'sample_group':key} for s in rows[:n])
    return manifest

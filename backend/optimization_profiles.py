from .logging_setup import log
"""Persist versioned per-stock optimization profiles; failures never replace a good profile."""
import hashlib
import json
from pathlib import Path
from . import store
from .models import Parameters
from .optimize import run,SMA_GRID,MARTIN_GRID

def init():
    with store.connect() as db:db.executescript('''
    CREATE TABLE IF NOT EXISTS optimizations(id TEXT PRIMARY KEY,symbol TEXT,cache_key TEXT,created TEXT,profile TEXT);
    CREATE INDEX IF NOT EXISTS optimization_cache ON optimizations(symbol,cache_key);
    CREATE TABLE IF NOT EXISTS active_optimization(symbol TEXT PRIMARY KEY,optimization_id TEXT);
    ''')

def latest(symbol):
    with store.connect() as db:r=db.execute('SELECT o.profile FROM active_optimization a JOIN optimizations o ON o.id=a.optimization_id WHERE a.symbol=?',(symbol,)).fetchone()
    return json.loads(r['profile']) if r else None

def key(p):
    # Search dimensions and strategy selection do not affect a search of both grids.
    fields=p.model_dump(mode='json')
    if p.time_range=='all':
        fields.pop('start',None);fields.pop('end',None)
    for k in set(SMA_GRID)|set(MARTIN_GRID)|{'strategies'}:fields.pop(k,None)
    sources={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('optimize.py','engine.py','strategies.py','quality.py','fallback.py','models.py','trading_rules.py')}
    return hashlib.sha256(store.dumps(dict(params=fields,sources=sources)).encode()).hexdigest()

def search(ident,p,force=False):
    log.info('optimization request task=%s force=%s parameters=%s',ident,force,store.dumps(p.model_dump(mode='json')))
    snapshot=store.latest(p.snapshot_id,symbol=p.symbol)
    if not snapshot or snapshot['payload'].get('symbol','002028.SZ')!=p.symbol:raise ValueError('股票与数据快照不匹配，请重新选择')
    if p.martin_pool_id:raise ValueError('请先在回测设置中选择单股条件，个股寻优不使用股票池排名')
    p=p.model_copy(update={'snapshot_id':snapshot['id'],'data_after':None})
    cache_key=key(p)
    with store.connect() as db:
        cached=db.execute('SELECT id,profile FROM optimizations WHERE symbol=? AND cache_key=? ORDER BY rowid DESC LIMIT 1',(p.symbol,cache_key)).fetchone()
    if cached and not force:
        log.info('optimization cache hit task=%s symbol=%s profile=%s',ident,p.symbol,cached['id'])
        with store.connect() as db:db.execute('INSERT OR REPLACE INTO active_optimization VALUES(?,?)',(p.symbol,cached['id']))
        store.task_update(ident,'completed',100,'已复用保存的个股最优参数',dict(optimization_id=cached['id'],symbol=p.symbol,cached=True))
        return
    folder=store.DATA/'optimizations'/p.symbol/ident
    report=run(p.symbol,max(1,min(4,int(__import__('os').environ.get('PULLBACK_OPTIMIZER_WORKERS','2')))),folder,p,lambda n,m:store.task_update(ident,progress=n,message=m))
    fields={k:v for rows in report['leaders'].values() for k,v in rows[0]['params'].items()}
    profile=dict(revision=ident,symbol=p.symbol,params=fields,created=store.now(),range=report['range'],snapshot_id=snapshot['id'],objective='total_return',candidates=report['candidates'],unique_accounts=report['unique_accounts'],seconds=report['seconds'],metrics={k:v['metrics'] for k,v in report['verified'].items()},conditions=p.model_dump(mode='json'),fallback=report['fallback'],report=str(folder/'report.json'),note='该股票、该区间的样本内网格最优，按累计收益排序；未做样本外验证。')
    with store.connect() as db:
        db.execute('INSERT INTO optimizations VALUES(?,?,?,?,?)',(ident,p.symbol,cache_key,profile['created'],store.dumps(profile)))
        db.execute('INSERT OR REPLACE INTO active_optimization VALUES(?,?)',(p.symbol,ident))
    log.info('optimization saved task=%s symbol=%s range=%s best_params=%s metrics=%s fallback=%s',ident,p.symbol,store.dumps(profile['range']),store.dumps(fields),store.dumps(profile['metrics']),store.dumps(profile['fallback']))
    store.task_update(ident,'completed',100,'个股最优参数已保存并应用，可直接运行回测',dict(optimization_id=ident,symbol=p.symbol,cached=False))

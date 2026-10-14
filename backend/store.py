"""SQLite persistence. Published snapshots and runs are immutable."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import sqlite3
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)

def now():
    return datetime.now(timezone.utc).isoformat()

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)

@contextmanager
def connect():
    db = sqlite3.connect(DATA / 'lab.sqlite', timeout=30)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        with db:
            yield db
    finally:
        db.close()

def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, created TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, kind TEXT, status TEXT, progress INTEGER, message TEXT, created TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, created TEXT, snapshot_id TEXT, params TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS repair_attempts(snapshot_id TEXT PRIMARY KEY, attempted TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS fetch_cache(key TEXT PRIMARY KEY, fetched TEXT, digest TEXT, url TEXT);
        ''')
        db.execute("UPDATE tasks SET status='failed', message='服务重启，任务中断；可重新执行，已完成下载会复用' WHERE status IN ('queued','running','cancelling')")

def archive(url, body):
    digest = hashlib.sha256(body).hexdigest()
    folder = DATA / 'raw'
    folder.mkdir(exist_ok=True)
    path = folder / (digest + '.gz')
    if not path.exists():
        fd,temporary=tempfile.mkstemp(dir=folder,prefix='.raw-')
        try:
            with os.fdopen(fd,'wb') as output:output.write(gzip.compress(body))
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO fetch_cache VALUES(?,?,?,?)', (url, now(), digest, url))
    return digest

def cached(url):
    with connect() as db:
        row = db.execute('SELECT * FROM fetch_cache WHERE key=?', (url,)).fetchone()
    if row:
        return gzip.decompress((DATA / 'raw' / (row['digest'] + '.gz')).read_bytes()), dict(row)
    return None

def snapshot(payload):
    # Identity excludes fetch timestamps so repeated identical downloads remain idempotent.
    identity = {k:v for k,v in payload.items() if k != 'evidence'}
    ident = hashlib.sha256(dumps(identity).encode()).hexdigest()[:20]
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)', (ident, now(), dumps(payload)))
    return ident

def latest(ident=None, symbol="002028.SZ"):
    with connect() as db:
        row = db.execute('SELECT * FROM snapshots WHERE id=?', (ident,)).fetchone() if ident else db.execute("SELECT * FROM snapshots WHERE coalesce(json_extract(payload,'$.symbol'),'002028.SZ')=? ORDER BY rowid DESC LIMIT 1",(symbol,)).fetchone()
    return {**dict(row), 'payload': json.loads(row['payload'])} if row else None

def task_update(ident, status='running', progress=0, message='', result=None):
    with connect() as db:
        db.execute('UPDATE tasks SET status=?,progress=?,message=?,result=? WHERE id=?', (status, progress, message, dumps(result) if result is not None else None, ident))

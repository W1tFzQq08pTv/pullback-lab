"""Own and stop the complete local workflow process tree, including search workers."""
import json
from collections import deque
from .logging_setup import log
import os
import signal
import subprocess
import sys
import threading
import uuid
from . import store
from .workflow import initial, read_task

CONTROL = threading.Lock()
PROCESSES = {}


def stop_group(process):
    # start_new_session gives every workflow a private group; no unrelated service.
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: pass


def cancel(ident):
    with CONTROL, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT kind,status FROM tasks WHERE id=?',(ident,)).fetchone()
        if not row or row['kind'] != 'workflow':
            raise ValueError('不是可终止的一键任务')
        if row['status'] not in ('queued','running','cancelling'):
            return row['status']
        if row['status']=='queued':
            db.execute("UPDATE tasks SET status='cancelled',message='已取消排队' WHERE id=?",(ident,))
            db.execute("UPDATE task_jobs SET state='done' WHERE id=? AND state='queued'",(ident,))
            log.info('task cancelled before execution id=%s',ident)
            return 'cancelled'
        db.execute("UPDATE tasks SET status='cancelling',message='正在终止，已完成的数据将保留' WHERE id=?",(ident,))
        db.commit()
        process = PROCESSES.get(ident)
        if process:
            stop_group(process)
        return 'cancelling'


def execute(ident, p):
    tail = deque(maxlen=12)
    process = None
    try:
        with CONTROL:
            task = read_task(ident)
            if task['status'] == 'cancelling':
                return
            process = subprocess.Popen([sys.executable,'-m','backend.workflow',ident],
                cwd=store.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True, text=True)
            PROCESSES[ident] = process
        process.stdin.write(store.dumps(p.model_dump(mode='json')))
        process.stdin.close()
        for line in process.stdout:
            tail.append(line.rstrip())
            # Workflow emits only stage changes and failures, never candidate-level progress.
            sys.stderr.write(line);sys.stderr.flush()
        process.wait()
    finally:
        with CONTROL:
            PROCESSES.pop(ident,None)
            row = read_task(ident)
            if process and row['status'] != 'completed':
                stop_group(process)
            if row['status'] in ('queued','running','cancelling'):
                cancelled = row['status'] == 'cancelling'
                state = row['result'] or initial(p.symbol)
                index = state.get('step',0)
                state['steps'][index]['status'] = 'cancelled' if cancelled else 'failed'
                message = '已终止，已保存的数据与参数可复用' if cancelled else '流程未完成，请重试'
                if not cancelled and tail:
                    message = tail[-1].removeprefix('ValueError: ')
                    log.error('workflow failed id=%s detail=%s',ident,' | '.join(tail))
                state['steps'][index]['message'] = message
                store.task_update(ident,'cancelled' if cancelled else 'failed',row['progress'],message,state)
                child = state.get('child_id')
                if child:
                    with store.connect() as db:
                        db.execute("UPDATE tasks SET status=?,message=? WHERE id=? AND status IN ('queued','running')",
                                   ('cancelled' if cancelled else 'failed',message,child))


def start(p):
    from fastapi import HTTPException
    from .task_scheduler import submit
    if p.martin_pool_id:
        raise HTTPException(422,'一键研究使用个股寻优，请先在参数设置中取消股票池排名')
    return submit('workflow',[p.symbol],p.model_dump(mode='json'),lambda ident:execute(ident,p),initial(p.symbol,p.model_dump(mode='json')))


def shutdown():
    with CONTROL:
        for process in PROCESSES.values():
            stop_group(process)

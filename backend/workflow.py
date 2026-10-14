"""One-click research orchestration in a cancellable process group.

Existing operations write child task progress; the public task presents four steps.
Completed snapshots/profiles remain reusable after cancellation. A run is published
atomically with completion, so cancellation cannot publish an incomplete result.
"""
import json
import sys
import uuid
from datetime import date
from .logging_setup import configure, log
from . import store, optimization_profiles
from .models import Parameters
from .stocks import get_stock
from .sync import synchronize
from .repair import repair_snapshot, REPAIRABLE
from .quality import eligible
from .fallback import prepare, resolve_range
from .strategies import multi_backtest

STEPS = [('sync', '更新行情'), ('repair', '补齐校验'), ('optimize', '参数寻优'), ('backtest', '自动回测')]
ACTIVE = ('queued', 'running', 'cancelling')


def read_task(ident):
    with store.connect() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=?', (ident,)).fetchone()
    return {**dict(row), 'result': json.loads(row['result']) if row['result'] else {}} if row else None


def present(task):
    """Expose child progress without allowing child completion to finish the flow."""
    result = task.get('result') or {}
    if task['kind'] != 'workflow' or task['status'] not in ACTIVE:
        return task
    child = read_task(result.get('child_id')) if result.get('child_id') else None
    if child:
        index = result.get('step', 0)
        progress = max(0, min(100, child['progress']))
        task = {**task, 'progress': min(99, index * 25 + progress // 4),
                'message': '正在终止，已完成的数据将保留' if task['status'] == 'cancelling' else child['message'],
                'result': {**result, 'step_progress': progress}}
    return task


def initial(symbol):
    return dict(symbol=symbol, step=0, steps=[dict(id=k, label=v, status='pending') for k, v in STEPS])


def run(ident, p):
    state = initial(p.symbol)

    def publish(message, progress=0):
        with store.connect() as db:
            changed = db.execute("UPDATE tasks SET status='running',progress=?,message=?,result=? WHERE id=? AND status IN ('queued','running')",
                                 (progress, message, store.dumps(state), ident)).rowcount
        if not changed:
            raise InterruptedError('任务已终止')

    def begin(index):
        child = uuid.uuid4().hex
        state.update(step=index, child_id=child, step_progress=0)
        state['steps'][index]['status'] = 'running'
        log.info('workflow step id=%s step=%s',ident,STEPS[index][1])
        with store.connect() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',
                       (child, 'workflow-step', 'running', 0, STEPS[index][1], store.now(), None))
        publish(STEPS[index][1], index * 25)
        return child

    def finish(child):
        row = read_task(child)
        if row['status'] != 'completed':
            raise ValueError(row['message'] or '当前步骤未完成')
        log.info('workflow step completed id=%s child=%s step=%s message=%s result=%s',ident,child,state['step'],row['message'],store.dumps(row['result']))
        state['steps'][state['step']].update(status='completed', message=row['message'])
        return row['result']

    child = begin(0)
    synchronize(child, get_stock(p.symbol))
    sync_result = finish(child)
    snapshot = store.latest(sync_result['snapshot_id'], symbol=p.symbol)
    p = p.model_copy(update={'snapshot_id': snapshot['id'], 'data_after': None})

    child = begin(1)
    # Match the optimizer's fixed warmup/market gate before searching both grids.
    gate = p.model_copy(update={'fast':20, 'middle':50, 'slow':200, 'slope':10,
                               'pullback':5, 'market_filter':True, 'strategies':['trend_pullback','martin_daily']})
    gate = resolve_range(snapshot['payload'], gate)
    problems = eligible(snapshot['payload'], gate)
    if any(i['code'] in REPAIRABLE for i in problems):
        snapshot, report = repair_snapshot(snapshot, lambda n,m: store.task_update(child, progress=n, message=m))
        state['repair'] = report
    p = p.model_copy(update={'snapshot_id':snapshot['id']})
    _, _, fallback, remaining = prepare(snapshot['payload'], gate.model_copy(update={'snapshot_id':snapshot['id']}))
    if remaining:
        raise ValueError('数据仍未通过校验：' + '；'.join(f'{i["date"] or ""} {i["message"]}' for i in remaining[:4]))
    # A latest-data workflow must not silently finish with a stale tail.
    latest = max((r['date'] for r in snapshot['payload']['bars']), default='')
    if latest < snapshot['payload']['end'] and snapshot['payload']['end'] not in snapshot['payload'].get('suspensions', []):
        raise ValueError(f'行情源尚未补齐最新交易日 {snapshot["payload"]["end"]}，请稍后重试')
    state['snapshot_id'] = snapshot['id']
    state['fallback'] = fallback
    log.info('workflow quality id=%s symbol=%s snapshot=%s initial_issues=%s remaining=%s fallback=%s',ident,p.symbol,snapshot['id'],len(problems),len(remaining),store.dumps(fallback))
    store.task_update(child, 'completed', 100, '数据校验通过' if not fallback else '已启用并记录完整区间兜底')
    finish(child)

    child = begin(2)
    optimization_profiles.search(child, p)
    optimal = finish(child)
    # Read this search's exact profile; never select another stock's latest result.
    with store.connect() as db:
        row = db.execute('SELECT profile FROM optimizations WHERE id=?', (optimal['optimization_id'],)).fetchone()
    profile = json.loads(row['profile'])
    state.update(optimization_id=optimal['optimization_id'], cached=optimal.get('cached', False))

    child = begin(3)
    # Reproduce the interval used to rank candidates, including suffix fallback.
    parameters = p.model_copy(update={**profile['params'], 'time_range':'custom',
        'start':date.fromisoformat(profile['range']['start']), 'end':date.fromisoformat(profile['range']['end']),
        'data_after':(profile.get('fallback') or {}).get('excluded_through')})
    _, parameters, run_fallback, remaining = prepare(snapshot['payload'], parameters)
    if remaining:
        raise ValueError('最优参数回测校验未通过：' + str(remaining[:4]))
    store.task_update(child, progress=20, message='使用最优参数计算成交与收益')
    result = multi_backtest(snapshot['payload'], parameters)
    if run_fallback:
        result['fallback'] = profile.get('fallback') or run_fallback
    state['steps'][3].update(status='completed', message='回测完成')
    state.update(run_id=ident, params={**parameters.model_dump(mode='json'), 'time_range':p.time_range, 'data_after':None,
                                       'start':str(p.start) if p.time_range=='custom' else str(parameters.start),
                                       'end':str(p.end) if p.time_range=='custom' else str(parameters.end)})
    # Completion and run publication share the same transaction as the cancel gate.
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        status = db.execute('SELECT status FROM tasks WHERE id=?', (ident,)).fetchone()['status']
        if status not in ('queued', 'running'):
            raise InterruptedError('任务已终止')
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (ident,store.now(),snapshot['id'],store.dumps(parameters.model_dump(mode='json')),store.dumps(result)))
        db.execute("UPDATE tasks SET status='completed',progress=100,message=?,result=? WHERE id=?",
                   ('已更新行情、应用最优参数并完成回测',store.dumps(state),ident))
        db.execute("UPDATE tasks SET status='completed',progress=100,message='回测完成' WHERE id=?",(child,))


if __name__ == '__main__':
    # The API initialized persistence; re-running store.init would interrupt tasks.
    configure()
    run(sys.argv[1], Parameters(**json.load(sys.stdin)))

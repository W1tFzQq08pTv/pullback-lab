"""Choose feasible existing search candidates without relaxing data quality checks."""
from .fallback import prepare
from .quality import warmup_required

MIN_SEARCH_SESSIONS = 20
NAMES = {'trend_pullback_v2':'趋势回调 v2（仓位管理）','trend_pullback': '趋势回调（SMA）', 'martin_daily': 'Martin 日线版'}


def plan_search(payload, p, sma_grid, martin_grid, product):
    end = payload['end'] if p.time_range == 'all' else str(p.end)
    available = sum(r['volume'] > 0 and r['date'] <= end and
                    (not p.data_after or r['date'] > p.data_after) for r in payload['bars'])
    budget = available - MIN_SEARCH_SESSIONS
    pools = {}
    for strategy in ('trend_pullback','trend_pullback_v2'):
      if strategy in p.strategies:
        pools[strategy] = [(fields, max(fields['slow'], fields['middle'] + fields['slope'],
            fields['middle'] + fields['pullback'] - 1, 2) - 1)
            for fields in product(sma_grid) if fields['fast'] < fields['middle'] < fields['slow']]
    if 'martin_daily' in p.strategies:
        pools['martin_daily'] = [(fields, max(126, fields['martin_anchor_window'])) for fields in product(martin_grid)]
    limits = sorted({need for entries in pools.values() for _, need in entries if need <= budget}, reverse=True)
    last_problems = []
    for limit in limits:
        candidates = {strategy: [fields for fields, need in entries if need <= limit]
                      for strategy, entries in pools.items()}
        candidates = {strategy: fields for strategy, fields in candidates.items() if fields}
        updates = {'strategies': list(candidates), 'market_filter': True}
        sma = candidates.get('trend_pullback', candidates.get('trend_pullback_v2'))
        if sma:
            fields = sma
            updates.update({key: max(row[key] for row in fields)
                            for key in ('middle', 'slow', 'slope', 'pullback')})
            updates['fast'] = min(row['fast'] for row in fields)
            updates['slope'] = min(updates['slope'], limit + 1 - updates['middle'])
            updates['pullback'] = min(updates['pullback'], limit + 2 - updates['middle'])
        if 'trend_pullback_v2' in candidates:
            updates.update({'v2_'+key:updates[key] for key in ('fast','middle','slow','slope','pullback','market_filter')})
        if 'martin_daily' in candidates:
            updates['martin_anchor_window'] = max(row['martin_anchor_window'] for row in candidates['martin_daily'])
        gate = p.model_copy(update=updates)
        data, gate, fallback, problems = prepare(payload, gate)
        sessions = sum(r['volume'] > 0 and str(gate.start) <= r['date'] <= str(gate.end) for r in data['bars'])
        last_problems = problems
        if problems or sessions < MIN_SEARCH_SESSIONS:
            continue
        skipped = {NAMES[strategy]: f'至少需要 {min(n for _, n in entries)} 条预热日线及 {MIN_SEARCH_SESSIONS} 个回测交易日；当前可用的连续有效区间不足'
                   for strategy, entries in pools.items() if strategy not in candidates}
        reduced = any(len(candidates.get(strategy, [])) < len(entries) for strategy, entries in pools.items())
        note = ('已按可用历史缩小参数网格。' if reduced else '现有参数网格均满足历史长度要求。')
        note += f'预热 {warmup_required(gate)} 条，实际比较 {sessions} 个有效交易日；每个候选使用相同日期区间。'
        if skipped: note += '；'.join(f'{name}跳过：{reason}' for name, reason in skipped.items()) + '。'
        note += '短历史结果仅供样本内研究，不代表已获样本外验证。'
        adaptation = dict(adapted=reduced, min_sessions=MIN_SEARCH_SESSIONS, available=available,
                          sessions=sessions, warmup=warmup_required(gate), strategies=list(candidates),
                          skipped=skipped, counts={key: len(value) for key, value in candidates.items()}, note=note)
        return data, gate, fallback, [], candidates, adaptation
    # Report quality blockers even when no candidate has enough history.
    gate = p.model_copy(update={'strategies': list(pools) or p.strategies})
    data, gate, fallback, problems = prepare(payload, gate)
    problems = last_problems or problems
    message = f'现有网格没有可用组合：共有 {available} 条有效日线，预热后还需至少 {MIN_SEARCH_SESSIONS} 个回测交易日；不会缩短策略必需的预热或跳过数据核验。'
    if not any(i['code'] == 'warmup' for i in problems):
        problems = [*problems, dict(code='warmup', date=str(gate.start), severity='error', symbol=p.symbol, message=message)]
    else:
        problems = [{**i, 'message': message} if i['code'] == 'warmup' else i for i in problems]
    adaptation = dict(adapted=True, min_sessions=MIN_SEARCH_SESSIONS, available=available, sessions=0,
                      strategies=[], skipped={}, counts={}, note=message)
    return data, gate, fallback, problems, {}, adaptation

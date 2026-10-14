"""Use the longest validated continuous interval; keep original snapshots immutable."""
import copy
from datetime import date, timedelta
from .quality import eligible, validate, warmup_required

DATED_ERRORS={'missing','zero_volume','duplicate','null','ohlc','calendar','price_jump','action_unverified','action_dates','share_dates','conflict','source_conflict'}

def slice_payload(payload,after):
    data=copy.deepcopy(payload)
    for key in ('bars','index','actions'):
        data[key]=[r for r in data[key] if r['date']>after]
    data['calendar']=[d for d in data['calendar'] if d>after]
    data['suspensions']=[d for d in data.get('suspensions',[]) if d>after]
    data['source_issues']=[i for i in data.get('source_issues',[]) if not i.get('date') or i['date']>after]
    data['start']=data['calendar'][0] if data['calendar'] else data['end']
    data['quality']=validate(data)
    return data

def resolve_range(payload,p):
    """All means all cached backtestable sessions, reserving indicator warmup."""
    required=warmup_required(p)
    end=payload['end'] if p.time_range=='all' else str(p.end)
    rows=[r for r in payload['bars'] if r['volume']>0 and r['date']<=end]
    first=rows[required]['date'] if len(rows)>required else (rows[0]['date'] if rows else payload['start'])
    start=max('2016-01-01',first,str(p.start) if p.time_range!='all' else '2016-01-01')
    return p.model_copy(update={'start':date.fromisoformat(start),
        'end':date.fromisoformat(end),'data_after':p.data_after if p.time_range!='all' else None})

def prepare(payload,p):
    requested=p
    p=resolve_range(slice_payload(payload,p.data_after) if p.data_after else payload,p)
    if p.data_after:
        data=slice_payload(payload,p.data_after)
        note=dict(requested_start=str(p.start),actual_start=str(p.start),end=str(p.end),excluded_through=p.data_after,data_start=data['start'],warmup=warmup_required(p),issues=[])
        return data,p,note,eligible(data,p)
    problems=eligible(payload,p)
    if not problems or not p.allow_suffix:
        note=dict(requested_start=str(requested.start),actual_start=str(p.start),end=str(p.end),warmup=warmup_required(p),reason='warmup',issues=[]) if requested.time_range=='custom' and p.start!=requested.start else None
        return payload,p,note,problems
    # Never hide stock/rule/range errors or failures without a known boundary.
    if any(i['code'] not in DATED_ERRORS|{'warmup'} or (i['code']!='warmup' and not i.get('date')) for i in problems):
        return payload,p,None,problems
    dates=sorted({i['date'] for i in problems if i['code'] in DATED_ERRORS})
    first=min((r['date'] for r in payload['bars'] if r['volume']>0),default=None)
    if not first:return payload,p,None,problems
    initial=(date.fromisoformat(first)-timedelta(days=1)).isoformat()
    boundaries=[initial]+[d for d in dates if d>=first]
    required=warmup_required(p)
    candidates=[]
    for index,boundary in enumerate(boundaries):
        stop=boundaries[index+1] if index+1<len(boundaries) else None
        rows=[r for r in payload['bars'] if r['volume']>0 and boundary<r['date']<=str(p.end) and (stop is None or r['date']<stop)]
        if len(rows)<=required:continue
        start=max(str(p.start),rows[required]['date'])
        end=rows[-1]['date']
        count=sum(start<=r['date']<=end for r in rows)
        if count:candidates.append((count,end,start,boundary))
    # Longest usable sample wins; ties prefer more recent data. Never join gaps.
    for _,end,start,boundary in sorted(candidates,reverse=True):
        data=slice_payload(payload,boundary)
        actual=p.model_copy(update={'start':date.fromisoformat(start),'end':date.fromisoformat(end),'data_after':boundary,'time_range':'custom'})
        if eligible(data,actual):continue
        note=dict(requested_start=str(p.start),requested_end=str(p.end),actual_start=start,end=end,excluded_through=boundary,data_start=data['start'],warmup=required,issues=problems)
        return data,actual,note,[]
    return payload,p,None,problems

"""Use only the complete suffix; keep original snapshots immutable."""
import copy
from datetime import date, timedelta
from .quality import eligible, validate

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

def prepare(payload,p):
    if p.data_after:
        data=slice_payload(payload,p.data_after)
        note=dict(requested_start=str(p.start),actual_start=str(p.start),end=str(p.end),excluded_through=p.data_after,data_start=data['start'],warmup=max(250,p.slow+p.slope,p.middle+p.slope+p.pullback),issues=[])
        return data,p,note,eligible(data,p)
    problems=eligible(payload,p)
    if not problems or not p.allow_suffix:return payload,p,None,problems
    # Never hide stock/rule/range errors or failures without a known boundary.
    if any(i['code'] not in DATED_ERRORS|{'warmup'} or (i['code']!='warmup' and not i.get('date')) for i in problems):
        return payload,p,None,problems
    dates=[i['date'] for i in problems if i['code'] in DATED_ERRORS]
    if dates:
        boundary=max(dates)
    else:
        # Newly listed stocks cannot supply ten years of history. With explicit
        # suffix mode, reserve warmup from their first real bar and disclose dates.
        first=min((r['date'] for r in payload['bars'] if r['volume']>0),default=None)
        if not first:return payload,p,None,problems
        boundary=(date.fromisoformat(first)-timedelta(days=1)).isoformat()
    data=slice_payload(payload,boundary)
    required=max(250,p.slow+p.slope,p.middle+p.slope+p.pullback)
    rows=[r for r in data['bars'] if r['volume']>0 and r['date']<=str(p.end)]
    if len(rows)<=required:return payload,p,None,problems
    start=max(str(p.start),rows[required]['date'])
    actual=p.model_copy(update={'start':date.fromisoformat(start),'data_after':boundary})
    remaining=eligible(data,actual)
    if remaining:return payload,p,None,remaining
    note=dict(requested_start=str(p.start),actual_start=start,end=str(p.end),excluded_through=boundary,data_start=data['start'],warmup=required,issues=problems)
    return data,actual,note,[]

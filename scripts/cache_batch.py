"""Manage persistent cache batches through the running local API (no optimization)."""
import argparse
import json
import time
import httpx

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('action',choices=['sample100','status','pause','resume','retry'])
p.add_argument('id',nargs='?')
p.add_argument('--wait',action='store_true')
a=p.parse_args()
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=60) as c:
    if a.action=='sample100':
        r=c.post('/api/cache-batches/sample100');r.raise_for_status();ident=r.json()['batch_id'];print('batch_id='+ident,flush=True)
    else:
        if not a.id:p.error('需要任务ID')
        ident=a.id
        if a.action!='status':
            r=c.post(f'/api/cache-batches/{ident}/{a.action}');r.raise_for_status()
    while True:
        r=c.get(f'/api/cache-batches/{ident}');r.raise_for_status();s=r.json()
        print(json.dumps({k:v for k,v in s.items() if k!='members'},ensure_ascii=False),flush=True)
        if not a.wait or s['state'] in ('completed','paused'):break
        time.sleep(10)

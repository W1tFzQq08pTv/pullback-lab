"""Download and validate official TDX archives; never runs stock optimization."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import httpx
from concurrent.futures import ThreadPoolExecutor
from backend.bulk_data import FOLDER,URL,publish
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('markets',nargs='*',default=['sh','sz','bj'],choices=['sh','sz','bj'])
a=p.parse_args();FOLDER.mkdir(exist_ok=True)
def download(market):
    import fcntl
    with (FOLDER/(market+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if (FOLDER/(market+'.json')).exists():return market+' 已导入，复用现有整包'
        path=FOLDER/(market+'lday.zip.part')
        # Existing partial downloads are restarted: never combine changed archives.
        import os,time
        url=URL+market+'lday.zip'
        with httpx.Client(timeout=60,follow_redirects=True) as c:
            probe=c.get(url,headers={'Range':'bytes=0-31'})
            probe.raise_for_status()
            if probe.status_code!=206 or not probe.content.startswith(b'PK'):
                raise ValueError('下载端点未返回可分段读取的ZIP')
            total=int(probe.headers['content-range'].split('/')[-1])
            validator=probe.headers.get('etag') or probe.headers.get('last-modified')
            if not validator:raise ValueError('下载源缺少版本标识')
            with path.open('wb') as f:
                f.truncate(total)
                def chunk(bounds):
                    lo,hi=bounds
                    for attempt in range(3):
                        try:
                            r=c.get(url,headers={'Range':f'bytes={lo}-{hi}','If-Range':validator})
                            if r.status_code!=206 or r.headers.get('content-range')!=f'bytes {lo}-{hi}/{total}' or len(r.content)!=hi-lo+1:
                                raise ValueError('分段版本或长度不一致，拒绝发布整包')
                            os.pwrite(f.fileno(),r.content,lo)
                            return
                        except Exception:
                            if attempt==2:raise
                            time.sleep(2**attempt)
                size=4*1024*1024
                with ThreadPoolExecutor(max_workers=4) as parts:
                    list(parts.map(chunk,[(lo,min(lo+size,total)-1) for lo in range(0,total,size)]))
        meta=publish(market,path)
        return market+' 导入成功 '+meta['sha256']
with ThreadPoolExecutor(max_workers=2) as pool:
    for result in pool.map(download,a.markets):print(result,flush=True)

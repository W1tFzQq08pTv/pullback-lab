"""Process-wide bounded upstream traffic and temporary circuit breaking."""
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse
from .logging_setup import log
LOCK=threading.Lock()
STATE={}

@contextmanager
def request_slot(url):
    host=urlparse(url).hostname or url
    with LOCK:
        state=STATE.setdefault(host,dict(gate=threading.BoundedSemaphore(2),next=0.,failures=0,until=0.))
    with state['gate']:
        with LOCK:
            now=time.monotonic()
            if state['until']>now:raise RuntimeError(f'{host} 暂停重试，等待故障源冷却')
            delay=max(0,state['next']-now);state['next']=max(now,state['next'])+.3
        if delay:time.sleep(delay)
        try:yield
        except Exception:
            with LOCK:
                state['failures']+=1
                if state['failures']>=3:
                    state['until']=time.monotonic()+300
                    log.warning('source circuit opened host=%s cooldown_seconds=300',host)
            raise
        else:
            with LOCK:state['failures']=0

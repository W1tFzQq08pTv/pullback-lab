"""Restart only this checkout's development services and stream concise logs."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.logging_setup import configure
log=configure()

def output(*args):
    return subprocess.run(args,text=True,capture_output=True).stdout.strip()

def listeners(port):
    return {int(p) for p in output('/usr/sbin/lsof','-nP',f'-iTCP:{port}','-sTCP:LISTEN','-t').split()}

def owned(pid,port):
    command=output('ps','-p',str(pid),'-o','command=')
    cwd=output('/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn')
    directories={line[1:] for line in cwd.splitlines() if line.startswith('n')}
    expected='uvicorn backend.app:app' if port==8765 else 'vite'
    return expected in command and bool(directories & {str(ROOT),str(ROOT/'web')})

def descendants(pid):
    pairs=[line.split() for line in output('ps','-axo','pid=,ppid=').splitlines()]
    found={pid}
    while True:
        more={int(p) for p,parent in pairs if int(parent) in found}-found
        if not more:return found
        found.update(more)

def terminate(pid):
    children=descendants(pid)
    for child in children:
        try:os.kill(child,signal.SIGTERM)
        except ProcessLookupError:pass

def stream(process,label):
    for line in process.stdout:
        line=line.strip()
        if not line:continue
        # Application log lines are already dated and persisted by the backend.
        if label=='api' and not line.startswith(('INFO:', 'WARNING:', 'ERROR:')):print(line,flush=True)
        elif 'GET /api/' not in line and 'hmr update' not in line and 'page reload' not in line:log.info('%s %s',label,line)

def main():
    lock=(ROOT/'data'/'startup.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX)
    targets={port:listeners(port) for port in (8765,5173)}
    for port,pids in targets.items():
        for pid in pids:
            if not owned(pid,port):raise RuntimeError(f'端口 {port} 被其他程序占用（PID {pid}），未停止该程序')
    for port,pids in targets.items():
        for pid in pids:
            log.info('restart stopping port=%s pid=%s',port,pid);terminate(pid)
    deadline=time.monotonic()+25
    old_pids=set().union(*targets.values())
    def old_alive():
        return any((state:=output('ps','-p',str(pid),'-o','stat=')) and not state.startswith('Z') for pid in old_pids)
    while any(listeners(port) for port in targets) or old_alive():
        if time.monotonic()>deadline:raise RuntimeError('旧服务未及时退出，未强行启动新实例，请检查正在结束的任务')
        time.sleep(.2)
    children=[]
    def cleanup(*_):
        for process in children:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for process in children:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:log.warning('service still stopping pid=%s',process.pid)
    def interrupted(*args):cleanup();raise SystemExit(0)
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        api=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','backend.app:app','--host','0.0.0.0','--port','8765','--no-access-log'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
        children.append(api);threading.Thread(target=stream,args=(api,'api'),daemon=True).start()
        deadline=time.monotonic()+25
        while True:
            if api.poll() is not None:raise RuntimeError('后端启动失败，前端未启动')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8765/openapi.json',timeout=1) as response:
                    if response.status==200:break
            except Exception:pass
            if time.monotonic()>deadline:raise RuntimeError('后端启动超时')
            time.sleep(.2)
        web=subprocess.Popen(['npm','--prefix','web','run','dev'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
        children.append(web);threading.Thread(target=stream,args=(web,'web'),daemon=True).start()
        deadline=time.monotonic()+20
        while not listeners(5173):
            if web.poll() is not None or time.monotonic()>deadline:raise RuntimeError('前端启动失败')
            time.sleep(.2)
        log.info('services ready http://127.0.0.1:5173/')
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
        while all(p.poll() is None for p in children):time.sleep(.5)
    finally:cleanup()

if __name__=='__main__':
    try:main()
    except Exception as exc:log.error('startup failed: %s',exc);sys.exit(1)

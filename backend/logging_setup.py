"""Small, date-partitioned operational log shared by the API and task workers."""
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
class DailyLog(logging.Handler):
    def __init__(self, folder):
        super().__init__(); self.folder=Path(folder); self.folder.mkdir(parents=True,exist_ok=True); self.day=None
    def emit(self, record):
        try:
            now=datetime.now(ZONE); day=now.date()
            if self.day != day:
                self.day=day
                for path in self.folder.glob('app-????-??-??.log'):
                    try: expired=datetime.strptime(path.stem[4:],'%Y-%m-%d').date() < day-timedelta(days=29)
                    except ValueError: continue
                    if expired: path.unlink(missing_ok=True)
                legacy=self.folder.parent/'workflow-logs'
                if legacy.is_dir():
                    for path in legacy.glob('*.log'):
                        try:
                            if re.fullmatch(r'[0-9a-f]{32}\.log',path.name) and datetime.fromtimestamp(path.stat().st_mtime,ZONE).date()<day-timedelta(days=29):path.unlink(missing_ok=True)
                        except FileNotFoundError:pass
            # One append syscall per record, safe for cooperating worker processes.
            line=(self.format(record)+'\n').encode('utf-8')
            fd=os.open(self.folder/f'app-{day}.log',os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
            try: os.write(fd,line)
            finally: os.close(fd)
        except Exception: self.handleError(record)
class LocalFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created,ZONE).strftime('%Y-%m-%d %H:%M:%S')
def configure(folder=None):
    logger=logging.getLogger('pullback')
    if logger.handlers:return logger
    logger.setLevel(logging.INFO); logger.propagate=False
    formatter=LocalFormatter('%(asctime)s %(levelname)s %(message)s')
    for handler in (DailyLog(folder or Path(__file__).resolve().parents[1]/'data'/'logs'),logging.StreamHandler()):
        handler.setFormatter(formatter);logger.addHandler(handler)
    for name in ('uvicorn.error','asyncio'):
        backend=logging.getLogger(name)
        backend.handlers=list(logger.handlers);backend.propagate=False;backend.setLevel(logging.INFO)
    return logger
log=logging.getLogger('pullback')

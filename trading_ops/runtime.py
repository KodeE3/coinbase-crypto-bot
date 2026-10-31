"""Process exclusion and atomic operational status for a local durable worker."""
import json
import os
import tempfile
from pathlib import Path


class SingleWorker:
    """OS-released lock. An interrupted worker cannot leave a stale PID lock."""
    def __init__(self, path): self.path, self.file = Path(path), None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0,2)
                if self.file.tell()==0: self.file.write(b'0'); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file=None
            raise RuntimeError('Another worker already holds this state directory') from None
        return self

    def __exit__(self,*args):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            self.file.close(); self.file=None


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            json.dump(value,out,sort_keys=True,allow_nan=False,indent=2)
            out.flush(); os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

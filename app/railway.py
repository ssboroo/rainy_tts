"""Railway single-service process supervisor.

Runs the FastAPI web process and the SQLite-backed background worker in the
same container so both processes share the same persistent /data volume.
"""
import signal
import subprocess
import sys
import time
import os
from pathlib import Path

children=[]

def prepare_storage():
    """Repair root-owned Railway volume, then drop privileges before either app starts."""
    if os.geteuid()!=0:
        return
    import pwd
    account=pwd.getpwnam('studio')
    data=Path(os.getenv('DATA_DIR','/data'))
    if not data.is_absolute() or data.is_symlink() or data.resolve() in {Path(p) for p in ('/','/etc','/usr','/studio','/tmp','/proc','/sys','/home','/root')}:
        raise RuntimeError('Unsafe DATA_DIR for volume initialization')
    data.mkdir(parents=True,exist_ok=True)
    for path in [data,*data.rglob('*')]:
        if path.is_symlink():
            continue
        owner=path.stat()
        if owner.st_uid!=account.pw_uid or owner.st_gid!=account.pw_gid:
            os.chown(path,account.pw_uid,account.pw_gid,follow_symlinks=False)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    if os.geteuid()!=account.pw_uid:
        raise RuntimeError('Could not drop runtime privileges')

def stop_children():
    for proc in children:
        if proc.poll() is None:
            proc.terminate()
    deadline=time.time()+8
    for proc in children:
        if proc.poll() is None:
            remaining=max(0,deadline-time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()

def handle_signal(signum, frame):
    stop_children()
    raise SystemExit(128+signum)

def main():
    prepare_storage()
    signal.signal(signal.SIGTERM,handle_signal)
    signal.signal(signal.SIGINT,handle_signal)
    commands=[
        [sys.executable,"-m","app.worker"],
        [sys.executable,"-m","app.server"],
    ]
    for command in commands:
        children.append(subprocess.Popen(command))
    try:
        while True:
            for proc in children:
                code=proc.poll()
                if code is not None:
                    stop_children()
                    return code if code else 1
            time.sleep(0.5)
    finally:
        stop_children()

if __name__=="__main__":
    raise SystemExit(main())

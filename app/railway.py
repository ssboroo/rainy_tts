"""Railway single-service process supervisor.

Runs the FastAPI web process and the SQLite-backed background worker in the
same container so both processes share the same persistent /data volume.
"""
import signal
import subprocess
import sys
import time

children=[]

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

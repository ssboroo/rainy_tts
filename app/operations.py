"""Offline maintenance and configuration readiness; never proves live provider access."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from dotenv import load_dotenv

load_dotenv(".env.local", override=False)
load_dotenv(".env", override=False)
from . import billing, core


def _flag(name):
    return os.getenv(name, '').lower() in {'true','1','yes','on'}


def inspect_readiness():
    checks={}
    checks['provider_configured']=bool(os.getenv('ELEVENLABS_API_KEY','').strip())
    checks['provider_paid_plan']=_flag('PROVIDER_PAID_PLAN_VERIFIED')
    checks['billing']=billing.billing_enabled()
    checks['wire']=bool(os.getenv('WIRE_MN_API_KEY','').startswith('sk_live_') and os.getenv('WIRE_MN_WEBHOOK_SECRET','').strip())
    checks['smtp']=all(os.getenv(k,'').strip() for k in ('SMTP_HOST','SMTP_FROM'))
    checks['persistent_storage']=_flag('PERSISTENT_STORAGE_CONFIRMED') or os.path.ismount(core.DATA)
    try:
        with tempfile.TemporaryFile(dir=core.DATA) as handle: handle.write(b'readiness')
        checks['storage']=True
    except OSError: checks['storage']=False
    try:
        with sqlite3.connect(f'file:{core.DATA / "studio.db"}?mode=ro',uri=True) as db:
            checks['database']=db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            checks['database']=checks['database'] and {'users','jobs','credit_ledger'}.issubset(tables)
    except sqlite3.Error: checks['database']=False
    try:
        age=time.time()-(core.DATA/'worker-heartbeat').stat().st_mtime
        checks['worker']=0<=age<=float(os.getenv('WORKER_HEARTBEAT_MAX_AGE_SECONDS','120'))
    except (OSError,ValueError): checks['worker']=False
    return {'ready':all(checks.values()),'checks':checks,'live_services_verified':False}


def verify_backup(source):
    source=Path(source).resolve()
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys=db.execute('PRAGMA foreign_key_check').fetchall()
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts={name:db.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
    return {'ok':integrity=='ok' and not foreign_keys and {'users','jobs','credit_ledger'}.issubset(tables),'integrity':integrity,'foreign_key_violations':len(foreign_keys),'row_counts':counts}


def backup_database(destination: Path) -> Path:
    destination=Path(destination).resolve()
    source=(core.DATA/'studio.db').resolve()
    if destination==source: raise ValueError('Backup must not replace the live database.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents overwriting any existing backup.
    with destination.open('xb'): pass
    try:
        with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as live, sqlite3.connect(destination) as backup:
            live.backup(backup)
        result=verify_backup(destination)
        if not result['ok']: raise RuntimeError('Backup verification failed.')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def cleanup_retained(now: float) -> dict:
    """Delete only expired unreferenced files, after the operator opts into policy.

    Referenced history remains available until explicit user deletion. Billing and
    all database records are untouched. A SQLite write lock excludes concurrent
    queue changes while selecting and deleting candidates.
    """
    counts={'enabled':_flag('RETENTION_POLICY_ENABLED'),'outputs':0,'artifacts':0,'tmp':0}
    if not counts['enabled']: return counts
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        references=[]
        job_ids={row[0] for row in db.execute("SELECT id FROM jobs")}
        for table in ('jobs','tool_jobs','artifacts','durable_jobs'):
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if exists:
                # Conservatively retain every DB reference, including completed history.
                references.extend(str(value) for row in db.execute('SELECT * FROM '+table) for value in row if value is not None)
        for directory,default in (('outputs',30),('artifacts',30),('tmp',7)):
            days=float(os.getenv('RETENTION_'+directory.upper()+'_DAYS',str(default)))
            if days<=0: continue
            cutoff=now-days*86400
            base=core.DATA/directory
            if not base.exists(): continue
            for path in base.rglob('*'):
                if path.is_symlink() or not path.is_file(): continue
                if directory=='outputs' and path.stem in job_ids: continue
                if directory=='tmp' and any(part in job_ids for part in path.relative_to(base).parts): continue
                # Both full paths and basenames appear in legacy JSON/payload records.
                if any(str(path) in ref or path.name in ref for ref in references): continue
                if path.stat().st_mtime<cutoff:
                    path.unlink(); counts[directory]+=1
    return counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('readiness')
    sub.add_parser('cleanup')
    for name in ('backup','verify'): sub.add_parser(name).add_argument('path',type=Path)
    args=parser.parse_args()
    if args.command=='backup': result={'backup':str(backup_database(args.path)),**verify_backup(args.path)}
    elif args.command=='verify': result=verify_backup(args.path)
    elif args.command=='cleanup': result=cleanup_retained(time.time())
    else: result=inspect_readiness()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('ok') is False: raise SystemExit(1)

if __name__=='__main__': main()

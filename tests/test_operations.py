import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from app import core
from app.engine import friendly_elevenlabs_error

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=core.DATA
        core.DATA=Path(self.tmp.name)/'data'
        core.init()
    def tearDown(self):
        core.DATA=self.old
        self.tmp.cleanup()
    def test_paid_plan_error_precedes_payment_required(self):
        msg=friendly_elevenlabs_error(Exception('paid_plan_required payment_required: library voices cannot be used on free tier'))
        self.assertIn('төлбөртэй',msg)
        self.assertNotIn('quota',msg)
    def test_backup_restores_committed_wal_and_never_overwrites(self):
        from app import operations
        with core.db() as db:
            db.execute("INSERT INTO users VALUES('u','test@example.com','hash',1)")
        target=Path(self.tmp.name)/'backup.db'
        self.assertEqual(operations.backup_database(target),target.resolve())
        self.assertTrue(operations.verify_backup(target)['ok'])
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute('SELECT email FROM users').fetchone()[0],'test@example.com')
        with self.assertRaises(FileExistsError): operations.backup_database(target)
        with self.assertRaises(ValueError): operations.backup_database(core.DATA/'studio.db')
    def test_empty_database_is_not_a_valid_restore(self):
        from app import operations
        empty=Path(self.tmp.name)/"empty.db"
        sqlite3.connect(empty).close()
        self.assertFalse(operations.verify_backup(empty)["ok"])

    def test_cleanup_requires_policy_and_preserves_references(self):
        from app import operations
        now=time.time()
        stale=core.DATA/'tmp'/'orphan'
        active=core.DATA/'tmp'/'active'
        output=core.DATA/'outputs'/'retained.wav'
        for path in (stale,active,output):
            path.write_bytes(b'x'); os.utime(path,(now-40*86400,now-40*86400))
        with core.db() as db:
            db.execute("INSERT INTO users VALUES('u','test@example.com','hash',1)")
            db.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created,result) VALUES(?,?,?,?,?,?,?,?)',('j','u','v','job',str(active),'running',1,str(output)))
        with patch.dict(os.environ,{'RETENTION_POLICY_ENABLED':'false'}):
            self.assertFalse(operations.cleanup_retained(now)['enabled'])
        self.assertTrue(stale.exists())
        with patch.dict(os.environ,{'RETENTION_POLICY_ENABLED':'true'}):
            counts=operations.cleanup_retained(now)
        self.assertEqual(counts['tmp'],1)
        self.assertTrue(active.exists()); self.assertTrue(output.exists())
    def test_cleanup_preserves_actual_tts_output_names(self):
        from app import operations
        now=time.time()
        with core.db() as db:
            db.execute("INSERT INTO users VALUES('u','test@example.com','hash',1)")
            db.execute("INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created,result) VALUES('real-job','u','v','job','{}','done',1,'{\"warnings\":[]}')")
        files=[core.DATA/'outputs'/'real-job.wav',core.DATA/'outputs'/'real-job.mp3',core.DATA/'tmp'/'real-job'/'part.wav']
        for path in files:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x');os.utime(path,(now-40*86400,now-40*86400))
        with patch.dict(os.environ,{'RETENTION_POLICY_ENABLED':'true'}):operations.cleanup_retained(now)
        self.assertTrue(all(path.exists() for path in files))

    def test_readiness_missing_worker_is_not_live_verification(self):
        from app import operations
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'','BILLING_ENABLED':'false'},clear=True):
            result=operations.inspect_readiness()
        self.assertFalse(result['ready'])
        self.assertFalse(result['checks']['worker'])
        self.assertTrue(result['checks']['database'])
        self.assertNotIn('api_key',str(result).lower())

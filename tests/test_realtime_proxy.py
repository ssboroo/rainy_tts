import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from app import core, billing


class RealtimeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=core.DATA;core.DATA=Path(self.temp.name);core.init()
        with core.db() as db:
            db.execute('INSERT INTO users VALUES(?,?,?,?)',('u','u@example.com','x',time.time()))
        self.env=patch.dict(os.environ,{'BILLING_ENABLED':'true','ELEVENLABS_API_KEY':'test-key'})
        self.env.start();billing.grant('u',1000,'test')

    def tearDown(self):
        self.env.stop();core.DATA=self.old;self.temp.cleanup()

    def test_token_private_single_use_scoped_and_bounded(self):
        from app import realtime_proxy
        result=realtime_proxy.issue('u')
        self.assertEqual(result['max_seconds'],900)
        self.assertEqual(result['websocket_path'],'/api/realtime')
        with self.assertRaises(ValueError): realtime_proxy.issue('u')
        self.assertIsNone(realtime_proxy.consume(result['token'],'other'))
        session=realtime_proxy.consume(result['token'],'u')
        self.assertIsNotNone(session)
        self.assertIsNone(realtime_proxy.consume(result['token'],'u'))
        with core.db() as db:
            row=dict(db.execute('SELECT * FROM realtime_sessions').fetchone())
        self.assertNotIn(result['token'],str(row))
        self.assertAlmostEqual(row['expires']-row['created'],900,delta=.1)
        self.assertEqual(billing.wallet('u')['wallet']['balance'],902)

    def test_expired_unused_session_refunds_once(self):
        from app import realtime_proxy
        result=realtime_proxy.issue('u')
        with core.db() as db: db.execute('UPDATE realtime_sessions SET expires=?',(time.time()-1,))
        self.assertIsNone(realtime_proxy.consume(result['token'],'u'))
        realtime_proxy.reconcile_unused();realtime_proxy.reconcile_unused()
        self.assertEqual(billing.wallet('u')['wallet']['balance'],1000)


if __name__=='__main__': unittest.main()

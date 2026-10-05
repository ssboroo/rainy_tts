import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from app import core, billing


class DurableJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = core.DATA
        core.DATA = Path(self.temp.name)
        core.init()
        with core.db() as db:
            for user in ('u', 'other'):
                db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user+'@example.com', 'x', time.time()))
        self.env = patch.dict(os.environ, {'BILLING_ENABLED':'true'})
        self.env.start()
        billing.grant('u', 1000, 'test')

    def tearDown(self):
        self.env.stop()
        core.DATA = self.old
        self.temp.cleanup()

    def queue(self):
        from app import durable_jobs
        return durable_jobs.enqueue('u', 'music', 'Хөгжим', {'method':'music','args':['Монгол аялгуу',3000,'music_v2_5',True]}, 'music.mp3', 'audio/mpeg', 10)

    def test_reservation_claim_and_output(self):
        from app import durable_jobs, server
        job_id = self.queue()
        self.assertEqual(billing.wallet('u')['wallet']['balance'], 990)
        row = durable_jobs.claim_next()
        self.assertEqual(row['id'], job_id)
        self.assertIsNone(durable_jobs.claim_next())
        with patch.object(server.tools, 'music', AsyncMock(return_value=(b'audio', {'request_id':'req'}))):
            asyncio.run(durable_jobs.execute(row))
        with core.db() as db:
            row=db.execute('SELECT * FROM tool_jobs WHERE id=?',(job_id,)).fetchone()
        self.assertEqual(row['status'], 'done')
        artifacts=core.tool_artifacts(job_id,'u')
        self.assertEqual(len(artifacts),1)
        self.assertEqual(billing.wallet('u')['wallet']['balance'],990)

    def test_cancel_owned_queued_job_refunds_once(self):
        from app import durable_jobs
        job_id=self.queue()
        with self.assertRaises(ValueError): durable_jobs.cancel(job_id,'other')
        self.assertTrue(durable_jobs.cancel(job_id,'u'))
        self.assertFalse(durable_jobs.cancel(job_id,'u'))
        self.assertEqual(billing.wallet('u')['wallet']['balance'],1000)
        self.assertIsNone(durable_jobs.claim_next())

    def test_running_cannot_be_deleted_or_replayed_on_restart(self):
        from app import durable_jobs
        job_id=self.queue()
        durable_jobs.claim_next()
        with self.assertRaises(ValueError): durable_jobs.cancel(job_id,'u')
        self.assertEqual(durable_jobs.recover_interrupted(),1)
        self.assertIsNone(durable_jobs.claim_next())
        self.assertEqual(billing.wallet('u')['wallet']['balance'],990)

    def test_failure_refunds_and_insufficient_balance_has_no_job(self):
        from app import durable_jobs, server
        with self.assertRaises(ValueError):
            durable_jobs.enqueue('other','music','Хөгжим',{'method':'music','args':[]},'x.mp3','audio/mpeg',10)
        with core.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tool_jobs WHERE user_id='other'").fetchone()[0],0)
        job_id=self.queue();row=durable_jobs.claim_next()
        from app.eleven_tools import ElevenAPIError
        with patch.object(server.tools,'music',AsyncMock(side_effect=ElevenAPIError(402,'Төлбөртэй багц шаардлагатай.'))):
            asyncio.run(durable_jobs.execute(row))
        self.assertEqual(billing.wallet('u')['wallet']['balance'],1000)
        with core.db() as db:
            self.assertEqual(db.execute('SELECT status FROM tool_jobs WHERE id=?',(job_id,)).fetchone()[0],'failed')

    def test_uncertain_provider_failure_keeps_reservation(self):
        from app import durable_jobs, server
        from app.eleven_tools import ElevenAPIError
        job_id=self.queue();row=durable_jobs.claim_next()
        with patch.object(server.tools,'music',AsyncMock(side_effect=ElevenAPIError(503,'upstream unavailable'))):
            asyncio.run(durable_jobs.execute(row))
        self.assertEqual(billing.wallet('u')['wallet']['balance'],990)

    def test_output_persistence_failure_cannot_refund_provider_success(self):
        from app import durable_jobs, server
        job_id=self.queue();row=durable_jobs.claim_next()
        with patch.object(server.tools,'music',AsyncMock(return_value=(b'audio',{'request_id':'req'}))), patch.object(core,'add_provider_usage',side_effect=RuntimeError('storage failed')):
            asyncio.run(durable_jobs.execute(row))
        self.assertEqual(billing.wallet('u')['wallet']['balance'],990)
        self.assertEqual(len(core.tool_artifacts(job_id,'u')),1)

    def test_deleted_user_cannot_enqueue(self):
        from app import durable_jobs
        with core.db() as db: db.execute("UPDATE users SET email='removed@deleted.invalid' WHERE id='u'")
        with self.assertRaises(ValueError): self.queue()
        self.assertEqual(billing.wallet('u')['wallet']['balance'],1000)

    def test_alignment_worker_exports_without_provider_method_lookup(self):
        from app import durable_jobs, audio_extensions
        upload=core.DATA/'tmp'/'alignment.wav';upload.write_bytes(b'audio')
        job_id=durable_jobs.enqueue('u','forced_alignment','Хадмал',{'method':'forced_alignment','args':['Монгол',2,10]},'alignment.json','application/json',10,upload,'alignment.wav','audio/wav')
        with patch.object(audio_extensions,'execute_alignment',AsyncMock(return_value={'artifacts':{'txt':'artifact'},'credits_used':10})) as execute:
            asyncio.run(durable_jobs.execute(durable_jobs.claim_next()))
        self.assertEqual(execute.call_args.args[3: ],('Монгол',2,10))
        with core.db() as db:self.assertEqual(db.execute('SELECT status FROM tool_jobs WHERE id=?',(job_id,)).fetchone()[0],'done')
        self.assertFalse(upload.exists())

    def test_unsafe_execution_is_rejected(self):
        from app import durable_jobs
        with self.assertRaises(ValueError):
            durable_jobs.enqueue('u','music','x',{'method':'delete_voice','args':['v']},'x.mp3','audio/mpeg',10)


if __name__ == '__main__': unittest.main()

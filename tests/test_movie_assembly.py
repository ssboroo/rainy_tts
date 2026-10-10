"""Tests for safe URL validation, durable billing, video assembly, and MCP status."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app import core, durable_jobs, movie_assembly, mcp_remote

class MovieTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.old_data=core.DATA
        core.DATA=Path(self.folder.name)
        self.env=patch.dict(os.environ,{"VOICE_MCP_ENABLED":"true",
              "RAINY_MOVIE_MEDIA_HOSTS":"media.example.com,cdn.example.com",
              "RAINY_MOVIE_ASSEMBLY_CREDITS_PER_MIN":"20",
              "BILLING_ENABLED":"true","PUBLIC_ORIGIN":"https://voice.example.com"})
        self.env.start()
        core.init()
        durable_jobs.ensure_schema()
        mcp_remote.schema()
        with core.db() as c:
            c.execute("INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)",("movie-user","movie@example.com","hash",1))
        from app import billing
        billing.ensure_wallet("movie-user",trial=False)
        with core.db() as c:
            c.execute("UPDATE credit_wallets SET balance=500 WHERE user_id='movie-user'")
    def tearDown(self):
        self.env.stop()
        core.DATA=self.old_data
        self.folder.cleanup()
    def test_urls_are_fail_closed_and_quotes_do_not_charge(self):
        with self.assertRaises(ValueError): movie_assembly.validate_video_url("http://media.example.com/movie.mp4")
        with self.assertRaises(ValueError): movie_assembly.validate_video_url("https://127.0.0.1/internal.mp4")
        with self.assertRaises(ValueError): movie_assembly.validate_video_url("https://attacker.example.com/movie.mp4")
        with self.assertRaises(ValueError): movie_assembly.validate_video_url("https://media.example.com@evil.example.com/movie.mp4")
        with self.assertRaises(ValueError): movie_assembly.validate_video_url("https://media.example.com:8443/movie.mp4")
        with self.assertRaises(ValueError): movie_assembly.validate_video_url("https://media.example.com/movie.mp4#fragment")
        video="https://media.example.com/scene01.mp4"
        estimate=movie_assembly.quote_movie([video],30,"9:16",user_id="movie-user")
        self.assertEqual(estimate["credits"],20)
        self.assertEqual(estimate["clipCount"],1)
        with core.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='usage'").fetchone()[0],0)
        with patch.dict(os.environ,{"RAINY_MOVIE_MEDIA_HOSTS":""}):
            with self.assertRaises(ValueError): movie_assembly.quote_movie([video],30,"9:16",user_id="movie-user")
    def test_movie_queue_atomic_credit_idempotency_and_recovery(self):
        video=["https://cdn.example.com/scene01.mp4"]
        args=("movie-user",video,30,"9:16",None,"movie-2026-retry-unique","sha-unique",20)
        job=movie_assembly.enqueue_movie(*args)
        self.assertEqual(job["status"],"queued")
        replay=movie_assembly.enqueue_movie(*args)
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["job_id"],job["job_id"])
        with core.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tool_jobs WHERE tool_type='video_assembly'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT balance FROM credit_wallets WHERE user_id='movie-user'").fetchone()[0],480)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='usage'").fetchone()[0],1)
            db.execute("UPDATE tool_jobs SET status='running' WHERE id=?",(job["job_id"],))
        durable_jobs.recover_interrupted()
        with core.db() as db:
            self.assertEqual(db.execute("SELECT status FROM tool_jobs WHERE id=?",(job["job_id"],)).fetchone()[0],"queued")
        with self.assertRaises(ValueError):
            movie_assembly.enqueue_movie(*args[:-2],"sha2",20)
    def test_failed_debit_does_not_poison_key(self):
        urls=["https://media.example.com/scene01.mp4"]
        with self.assertRaises(ValueError):
            movie_assembly.enqueue_movie("movie-user",urls,30,"9:16",None,"shortcredit-20261010","hsh",501)
        with core.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM vmcp_movie_requests").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tool_jobs").fetchone()[0],0)
    def test_assemble_with_local_stub_clips(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("FFmpeg is not installed")
        source=core.DATA/"tmp"/"source-demo.mp4"
        import subprocess
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=c=blue:s=128x128:r=24",
                        "-t","2","-c:v","libx264","-pix_fmt","yuv420p","-y",str(source)],check=True,timeout=15)
        async def mock_download(url,out,total):
            shutil.copyfile(source,out)
            total[0]+=out.stat().st_size
            return out
        with core.db() as db:
            db.execute("INSERT INTO tool_jobs(id,user_id,tool_type,title,payload,status,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                       ("movie-test-job","movie-user","video_assembly","Test","{}","running",1,1))
        args=["https://media.example.com/s1.mp4","https://media.example.com/s2.mp4"]
        with patch.object(movie_assembly,"download_clip",mock_download),patch.object(movie_assembly,"public_ip_resolves",return_value=True):
            result=asyncio.run(movie_assembly.assemble_movie("movie-user","movie-test-job",args,4,"1:1",None))
        self.assertEqual(result["clip_count"],2)
        artifact=core.DATA/"artifacts"
        self.assertEqual(len(list(artifact.glob("*.mp4"))),1)
        self.assertGreater(next(artifact.glob("*.mp4")).stat().st_size,4096)

if __name__=="__main__": unittest.main()

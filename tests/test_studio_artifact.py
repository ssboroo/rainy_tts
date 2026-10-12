"""The unified merchant proxy must retain artifact ownership checks."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import core, mcp_remote, server

class StudioArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.data=patch.object(core,'DATA',Path(self.tmp.name));self.data.start();core.init()
        self.env=patch.dict(os.environ,{'VOICE_MCP_ENABLED':'true'});self.env.start()
        with core.db() as c:
            for uid in ('merchant','other'):
                c.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,uid+'@example.com','x',1))
            c.execute('INSERT INTO tool_jobs(id,user_id,tool_type,title,payload,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',('job-1','merchant','video_assembly','Movie','{}','done',1,1))
            f=Path(self.tmp.name)/'movie.mp4';f.write_bytes(b'test-owned-mp4')
            c.execute('INSERT INTO artifacts(id,user_id,job_id,kind,filename,mime,path,created) VALUES(?,?,?,?,?,?,?,?)',('file-1','merchant','job-1','video','movie.mp4','video/mp4',str(f),1))
        app=FastAPI();app.get('/api/artifacts/{artifact_id}')(server.artifact)
        self.client=TestClient(app)
    def tearDown(self):
        self.env.stop();self.data.stop();self.tmp.cleanup()
    def test_bearer_download_is_owner_scoped_and_invalid_tokens_fail(self):
        with patch.object(mcp_remote,'principal',return_value={'uid':'merchant'}):
            r=self.client.get('/api/artifacts/file-1',headers={'Authorization':'Bearer valid'})
            self.assertEqual(r.status_code,200);self.assertEqual(r.content,b'test-owned-mp4')
        with patch.object(mcp_remote,'principal',return_value={'uid':'other'}):
            self.assertEqual(self.client.get('/api/artifacts/file-1',headers={'Authorization':'Bearer foreign'}).status_code,404)
        with patch.object(mcp_remote,'principal',return_value=None):
            self.assertEqual(self.client.get('/api/artifacts/file-1',headers={'Authorization':'Bearer expired'}).status_code,401)

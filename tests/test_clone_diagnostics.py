"""Instant voice cloning upstream 422 is explained without leaking raw provider text."""
import unittest
import httpx
from fastapi import UploadFile, HTTPException
from app.eleven_tools import explain_clone_rejection
from app import server

class Clone422DiagnosticsTests(unittest.TestCase):
    def test_pydantic_missing_sample_is_an_explicit_mongolian_error(self):
        data={"detail":[{"type":"missing","loc":["body","files"],"msg":"Field required"}]}
        msg=explain_clone_rejection(422,data)
        self.assertIn("аудио",msg.lower())
        self.assertNotIn("API алдаа",msg)
    def test_poor_or_invalid_audio_rejection_is_actionable(self):
        for status in ("invalid_audio","audio_too_short","poor_audio_quality"):
            msg=explain_clone_rejection(422,{"detail":{"status":status,"message":"internal English trace"}})
            self.assertTrue("аудио" in msg.lower() or "бичлэг" in msg.lower(),msg)
            self.assertNotIn("internal English trace",msg)
    def test_voice_limit_and_clone_permission_are_not_misrepresented_as_audio(self):
        limit=explain_clone_rejection(422,{"detail":{"status":"voice_limit_reached","message":"no slots"}})
        self.assertIn("хязгаар",limit)
        forbidden=explain_clone_rejection(422,{"detail":{"status":"instant_voice_cloning_not_available","message":"plan"}})
        self.assertIn("эрх",forbidden)
    def test_unknown_rejection_stays_honest_and_never_exposes_raw_data(self):
        msg=explain_clone_rejection(422,{"detail":{"status":"unexpected","message":"Secret=private-recording-123"}})
        self.assertIn("шалтгаан",msg)
        self.assertNotIn("private-recording",msg)

    def test_real_multipart_field_is_unchanged_and_upstream_array_detail_is_read(self):
        import asyncio
        from io import BytesIO
        from unittest.mock import patch
        from app.eleven_tools import ElevenAPIError, ElevenTools
        received=[]
        def fake_upstream(request):
            received.append((request.method,request.url.path,request.content))
            return httpx.Response(422,json={"detail":[{"loc":["body","files"],"type":"missing","msg":"Field required"}]})
        client=httpx.AsyncClient(transport=httpx.MockTransport(fake_upstream))
        upload=UploadFile(filename="sample.wav",file=BytesIO(b"RIFF"+b"0"*1000),size=1004)
        with patch('app.eleven_tools.httpx.AsyncClient',return_value=client):
            with self.assertRaises(ElevenAPIError) as caught:
                asyncio.run(ElevenTools(api_key="test-key").clone_voice("test",[upload]))
        self.assertEqual(caught.exception.status,422)
        self.assertIn("аудио",str(caught.exception).lower())
        self.assertEqual(received[0][0],"POST")
        self.assertEqual(received[0][1],"/v1/voices/add")
        self.assertIn(b'name="files[]"',received[0][2])
        self.assertIn(b'name="name"',received[0][2])

    def test_empty_samples_rejected_locally_before_billable_provider_request(self):
        from io import BytesIO
        file=UploadFile(filename="empty.wav",file=BytesIO(b""),size=0)
        with self.assertRaises(HTTPException) as raised:
            server.validate_upload(file,server.AUDIO_EXTS,server.MAX_AUDIO_MB)
        self.assertEqual(raised.exception.status_code,422)

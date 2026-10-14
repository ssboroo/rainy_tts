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

    def test_multipart_matches_official_elevenlabs_sdk_files_field_and_upload_bytes(self):
        """The provider expects file parts named files (without []), not files[]."""
        import asyncio
        from io import BytesIO
        from unittest.mock import patch
        from app.eleven_tools import ElevenTools
        bodies=[]
        def validate_upstream(request):
            raw=request.content
            bodies.append(raw)
            if b'name="files"; filename="voice-1.wav"' not in raw or b'name="files"; filename="voice-2.wav"' not in raw:
                return httpx.Response(422,json={"detail":[{"loc":["body","files"],"type":"missing","msg":"Field required"}]})
            if b'audio-one-data' not in raw or b'audio-two-data' not in raw:
                return httpx.Response(422,json={"detail":{"status":"invalid_audio","message":"No sample body"}})
            return httpx.Response(200,json={"voice_id":"test-id","requires_verification":False})
        client=httpx.AsyncClient(transport=httpx.MockTransport(validate_upstream))
        uploads=[
            UploadFile(filename="voice-1.wav",file=BytesIO(b"audio-one-data"),size=14),
            UploadFile(filename="voice-2.wav",file=BytesIO(b"audio-two-data"),size=14),
        ]
        with patch('app.eleven_tools.httpx.AsyncClient',return_value=client):
            result=asyncio.run(ElevenTools(api_key="test-key").clone_voice("Миний хоолой",uploads))
        self.assertEqual(result["voice_id"],"test-id")
        self.assertEqual(len(bodies),1)
        self.assertNotIn(b'name="files[]"',bodies[0])
        self.assertIn(b'name="name"',bodies[0])

    def test_provider_rejects_bad_audio_even_with_correct_field(self):
        import asyncio
        from io import BytesIO
        from unittest.mock import patch
        from app.eleven_tools import ElevenAPIError,ElevenTools
        def reject_audio(request):
            assert b'name="files";' in request.content
            return httpx.Response(422,json={"detail":{"status":"invalid_audio","message":"invalid recording"}})
        client=httpx.AsyncClient(transport=httpx.MockTransport(reject_audio))
        upload=UploadFile(filename="broken.wav",file=BytesIO(b"invalid audio bytes"),size=19)
        with patch('app.eleven_tools.httpx.AsyncClient',return_value=client):
            with self.assertRaises(ElevenAPIError) as raised:
                asyncio.run(ElevenTools(api_key="test-key").clone_voice("Миний хоолой",[upload]))
        self.assertEqual(raised.exception.status,422)
        self.assertIn("Аудио",str(raised.exception))
        self.assertNotIn("invalid recording",str(raised.exception))

    def test_empty_samples_rejected_locally_before_billable_provider_request(self):
        from io import BytesIO
        file=UploadFile(filename="empty.wav",file=BytesIO(b""),size=0)
        with self.assertRaises(HTTPException) as raised:
            server.validate_upload(file,server.AUDIO_EXTS,server.MAX_AUDIO_MB)
        self.assertEqual(raised.exception.status_code,422)

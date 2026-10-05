"""Exercise the production SDK adapter offline, without provider dependencies."""
from contextlib import contextmanager
from pathlib import Path
import struct
import tempfile
import types
import unittest
import wave

from app.engine import ElevenLabsEngine


class RawResponseTests(unittest.TestCase):
    def test_context_managed_stream_writes_pcm_and_preserves_headers(self):
        engine = object.__new__(ElevenLabsEngine)
        engine.readiness = lambda: (True, '')
        engine.language_code = 'mn'
        engine.model_id = 'eleven_v4'
        pcm = struct.pack('<h', 800) * 2400
        state = {'closed': False}

        @contextmanager
        def convert(**kwargs):
            self.assertEqual(kwargs['model_id'], 'eleven_v4')
            try:
                yield types.SimpleNamespace(data=iter([pcm]), headers={'request-id': 'request-1'})
            finally:
                state['closed'] = True

        engine.client = types.SimpleNamespace(text_to_speech=types.SimpleNamespace(
            with_raw_response=types.SimpleNamespace(convert=convert)))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'voice.wav'
            metadata = engine.synthesize('Сайн байна уу.', output, voice_id='voice', trusted_voice=True)
            with wave.open(str(output)) as audio:
                self.assertEqual(audio.readframes(2400), pcm)
                self.assertEqual(audio.getframerate(), 24000)
            self.assertEqual(metadata['request_id'], 'request-1')
            self.assertTrue(state['closed'])


if __name__ == '__main__':
    unittest.main()

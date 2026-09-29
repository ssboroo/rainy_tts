import os
import tempfile
import unittest
from unittest.mock import patch
from app.engine import OronEngine

class UsageModeTests(unittest.TestCase):
    def test_local_evaluation_still_requires_model(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'MODEL_DIR':folder,'MODEL_LICENSE_APPROVED':'false','TTS_USAGE_MODE':'local-evaluation','PUBLIC_ORIGIN':'http://localhost:8080'}):
            ok, message = OronEngine().readiness()
            self.assertFalse(ok)
            self.assertIn('суулгагдаагүй',message)
    def test_public_origin_does_not_enable_evaluation(self):
        with patch.dict(os.environ, {'MODEL_LICENSE_APPROVED':'false','TTS_USAGE_MODE':'local-evaluation','PUBLIC_ORIGIN':'https://voice.example.com'}):
            ok, message = OronEngine().readiness()
            self.assertFalse(ok)
            self.assertIn('Арилжааны',message)
    def test_commercial_default_is_preserved(self):
        with patch.dict(os.environ, {'MODEL_LICENSE_APPROVED':'false','TTS_USAGE_MODE':'commercial','PUBLIC_ORIGIN':'http://localhost:8080'}):
            self.assertIn('Арилжааны',OronEngine().readiness()[1])

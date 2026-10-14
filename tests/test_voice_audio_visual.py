"""Live robot mouth sync and voice-card preview regressions (RED)."""
import unittest
from fastapi.testclient import TestClient
from app.server import app,STATIC

class AudioVisualContract(unittest.TestCase):
 def test_library_has_real_audio_reactive_player_assets(self):
  page=(STATIC/"index.html").read_text()
  self.assertIn("voice-visual.js",page)
  self.assertIn("voice-visual.css",page)
  appjs=(STATIC/"app.js").read_text()
  self.assertIn("createVoicePreviewPlayer(",appjs)
  self.assertIn("rv-wave", (STATIC/"voice-visual.js").read_text())
  self.assertIn("createMediaElementSource", (STATIC/"voice-visual.js").read_text())
  self.assertIn("createAnalyser", (STATIC/"voice-visual.js").read_text())
  self.assertIn("decodeAudioData", (STATIC/"voice-visual.js").read_text())
  self.assertIn("URL.revokeObjectURL",appjs)
 def test_robot_mouth_tracks_output_pcm_not_fake_talking_animation(self):
  appjs=(STATIC/"app.js").read_text()
  visual=(STATIC/"reception-visual.js").read_text()
  css=(STATIC/"reception-visual.css").read_text()
  self.assertIn("rainy:agent-output-level",appjs)
  self.assertIn("requestAnimationFrame",appjs)
  self.assertIn("getChannelData",appjs)
  self.assertIn("rainy:agent-output-level",visual)
  self.assertIn("--rv-mouth-level",visual)
  self.assertIn("--rv-mouth-level",css)
  self.assertIn("rv-robot-mouth",css)
 def test_assets_are_live_http_resources(self):
  with TestClient(app) as client:
   for name in ("voice-visual.js","voice-visual.css"):
    response=client.get("/"+name)
    self.assertEqual(response.status_code,200,(name,response.status_code))

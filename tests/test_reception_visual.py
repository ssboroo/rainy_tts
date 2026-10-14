"""Regression: compact receptionist studio and honest real voice controls."""
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.server import app,STATIC
class ReceptionVisualTests(unittest.TestCase):
 def test_voice_stage_and_compact_navigation(self):
  html=(STATIC/"index.html").read_text()
  self.assertIn('id="rv-stage"',html)
  self.assertIn('id="rv-orb"',html)
  self.assertIn('id="rv-avatar"',html)
  self.assertIn('id="rv-view-orb"',html)
  self.assertIn('id="rv-view-avatar"',html)
  self.assertIn('id="rv-state-label"',html)
  self.assertIn('id="rv-transcript"',html)
  self.assertIn('data-reception-tab="voice"',html)
  self.assertIn('data-reception-tab="booking"',html)
  self.assertIn('data-reception-tab="knowledge"',html)
  self.assertIn('reception-visual.js',html)
 def test_visual_asset_and_script_runtime_contract(self):
  client=TestClient(app)
  for name in ('reception-visual.js','reception-visual.css'):
   response=client.get('/'+name)
   self.assertEqual(response.status_code,200,name)
  script=(STATIC/"reception-visual.js").read_text()
  self.assertIn('rainy:agent-state',script)
  self.assertIn('rainy:agent-transcript',script)
  self.assertIn('reception-tab-panel',script)
  self.assertIn('reception-voice-style',script)
  self.assertIn('localStorage',script)
  self.assertIn('aria-selected',script)
  self.assertIn('stopAgentPreview',script)
 def test_existing_realtime_audio_runtime_drives_visual_honestly(self):
  js=(STATIC/"app.js").read_text()
  self.assertIn("rainy:agent-state",js)
  self.assertIn("rainy:agent-transcript",js)
  self.assertIn('agent_output_audio_format',js)
  self.assertIn('user_transcription_event',js)
  self.assertIn("stopAgentPreview",js)

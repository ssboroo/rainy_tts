"""Reception's visual theme must match Voice Studio without losing its unique lab atmosphere."""
import unittest
from app.server import STATIC

class ReceptionThemeTests(unittest.TestCase):
 def test_reception_uses_voice_studio_brand_tokens_for_both_themes(self):
  css=(STATIC/"reception-visual.css").read_text(encoding="utf-8")
  for token in ("--lime","--cyan","--violet","--text","--line","--bg"):
   self.assertIn("var("+token,css,token)
  self.assertIn(':root[data-theme="light"] #reception',css)
  self.assertIn("--rv-surface:",css)
  self.assertIn("--rv-border:",css)
  self.assertIn("--rv-accent:",css)
  self.assertIn("#reception .rl-connect-card",css)
  self.assertIn("#reception .rl-price-report",css)
  self.assertIn("#reception .rl-stat",css)
 def test_voice_control_room_has_compact_status_and_ambient_art(self):
  html=(STATIC/"index.html").read_text(encoding="utf-8")
  self.assertIn('class="rv-console-frame"',html)
  self.assertIn('class="rv-signal-path"',html)
  self.assertIn('id="rv-session-meta"',html)
  self.assertIn('class="rv-hud-corner',html)
  self.assertIn('reception-visual.css?v=2',html)
  self.assertIn('reception-visual.js?v=2',html)
 def test_ai_avatar_is_a_cute_animated_robot_not_human(self):
  html=(STATIC/"index.html").read_text(encoding="utf-8")
  css=(STATIC/"reception-visual.css").read_text(encoding="utf-8")
  avatar=html.split('id="rv-avatar"',1)[1].split('</svg>',1)[0]
  self.assertIn('AI робот',avatar)
  self.assertIn('class="rv-robot-eye"',avatar)
  self.assertIn('class="rv-robot-mouth"',avatar)
  self.assertIn('class="rv-robot-antenna"',avatar)
  self.assertIn('rv-robot-head',avatar)
  self.assertNotIn('AI ресепшний хийсвэр хүний дүрс',avatar)
  self.assertIn('#reception .rv-visual[data-state="speaking"] .rv-robot-mouth',css)
  self.assertIn('@media(prefers-reduced-motion:reduce)',css)
 def test_status_refresh_never_fakes_online_call(self):
  js=(STATIC/"reception-visual.js").read_text(encoding="utf-8")
  self.assertIn("rv-session-meta",js)
  self.assertIn("agentPreview",js)
  self.assertIn("rainy:agent-state",js)
  self.assertIn("aria-selected",js)
  self.assertIn("stopAgentPreview",js)

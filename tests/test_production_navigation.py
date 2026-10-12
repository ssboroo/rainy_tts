"""Dedicated RAINY Voice production workspaces: no duplicated editor controls."""
from pathlib import Path
import re
import unittest

from app import server

static = Path(server.__file__).parent / "static"


class ProductionNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (static / "index.html").read_text(encoding="utf-8")
        cls.js = (static / "app.js").read_text(encoding="utf-8")

    def test_each_tool_has_exactly_one_navigation_item_and_one_page(self):
        nav = self.html.split('<nav class="studio-tool-nav"', 1)[1].split("</nav>", 1)[0]
        for key in ("director", "audiobook", "repair"):
            self.assertEqual(nav.count('data-page="' + key + '"'), 1, key)
            self.assertEqual(self.html.count('<section id="' + key + '"'), 1, key)
            self.assertIn(" " + key + ":[", self.js)

    def test_tts_editor_contains_no_production_accordions_or_duplicate_controls(self):
        tts = self.html.split('<section id="tts"', 1)[1].split('<section id="director"', 1)[0]
        for term in ("id=\"director-apply\"", "id=\"book-plan\"", "id=\"patch-apply\"",
                     "AI Voice Director · Уншлагын найруулга", "AI Audiobook Producer · Бүлэгчилсэн дуу",
                     "Sentence Repair · Алдаатай өгүүлбэр солих"):
            self.assertNotIn(term, tts, term)
        self.assertIn('id="text"', tts)
        self.assertIn('id="generate"', tts)

    def test_function_controls_are_singletons_and_have_event_handlers(self):
        ids = ("director-text", "director-style", "director-result", "director-apply",
               "director-to-tts", "director-from-tts", "book-model", "book-voice",
               "book-text", "book-plan", "book-create", "patch-refresh",
               "patch-create-correction", "patch-original", "patch-correction", "patch-apply")
        for key in ids:
            self.assertEqual(self.html.count('id="' + key + '"'), 1, key)
        for key in ("director-apply", "director-to-tts", "director-from-tts", "book-plan",
                    "book-create", "patch-refresh", "patch-create-correction", "patch-apply"):
            self.assertIn("$('" + key + "').onclick=", self.js, key)

    def test_free_plan_does_not_charge_audiobook_planning_and_reuses_paid_tts(self):
        self.assertIn("api('/production/audiobook/plan'", self.js)
        self.assertIn("model_id:$('book-model').value,voice_id:$('book-voice').value", self.js)
        self.assertIn("api('/jobs/quote'", self.js)
        self.assertIn("api('/jobs',{method:'POST'", self.js)
        self.assertIn("invalidateAudiobookPlan", self.js)
        self.assertIn("api('/production/audio-patch'", self.js)
        self.assertIn("if(name==='repair'&&state.user)refreshReadyPatchJobs()", self.js)

    def test_legacy_navigation_and_voice_from_video_still_work(self):
        self.assertIn("new URLSearchParams(location.search).get('tool')==='alignment'", self.js)
        self.assertIn("acceptVideoHandoff()", self.js)


if __name__ == "__main__":
    unittest.main()

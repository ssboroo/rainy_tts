"""Navigation regressions: MCP/Movie pages and the existing Voice tools remain usable."""
from pathlib import Path
import re
import unittest

from fastapi.testclient import TestClient
from app import server

STATIC=Path(server.__file__).parent / "static"

class VoiceNavigationTests(unittest.TestCase):
    def test_navigation_is_unique_and_grouped(self):
        html=(STATIC/"index.html").read_text(encoding="utf-8")
        beginning=html.index('<nav class="studio-tool-nav"')
        end=html.index("</nav>",beginning)
        menu=html[beginning:end]
        self.assertIn('href="/movie"',menu)
        self.assertIn('href="/integrations"',menu)
        self.assertIn("AI КИНО &amp; MCP",menu)
        self.assertIn('id="voice-tools-nav"',menu)
        self.assertIn('id="audio-tools-nav"',menu)
        self.assertIn('<summary>',menu)
        keys=["tts","dialogue","music","dubbing","clone","pvc","voices",
              "voice-design","voice-remix","stt","realtime","isolator",
              "changer","sfx","alignment","history","billing","analytics",
              "settings","admin","reception"]
        for key in keys:
            self.assertEqual(
                len(re.findall(r'data-page="'+re.escape(key)+r'"',menu)),1,key)
        self.assertEqual(menu.count('href="/movie"'),1)
        self.assertEqual(menu.count('href="/integrations"'),1)
        self.assertNotIn("movie-nav-link",menu)

    def test_tts_editor_is_not_filled_with_movie_promo_and_voiceover_is_under_video(self):
        html=(STATIC/"index.html").read_text(encoding="utf-8")
        tts=html.split('<section id="tts"',1)[1].split('</section>',1)[0]
        dubbing=html.split('<section id="dubbing"',1)[1].split('</section>',1)[0]
        self.assertNotIn('id="movie-beta-title"',tts)
        self.assertNotIn('id="video-voiceover-form"',tts)
        self.assertIn('id="video-voiceover-form"',dubbing)
        self.assertEqual(html.count('id="video-voiceover-form"'),1)
        self.assertEqual(html.count('id="voiceover-file"'),1)

    def test_mobile_navigation_closable_and_submenus_keyboard_accessible(self):
        script=(STATIC/"brand.js").read_text(encoding="utf-8")
        app=(STATIC/"app.js").read_text(encoding="utf-8")
        self.assertIn("querySelectorAll('a,button,summary')",script)
        self.assertIn("parentGroup.open=true",app)
        self.assertIn("page('dubbing');$('video-voiceover-form').scrollIntoView",app)
        self.assertIn('id="open-menu"',(STATIC/"index.html").read_text(encoding="utf-8"))

    def test_static_mcp_and_movie_pages_render_under_content_security_policy(self):
        with TestClient(server.app) as client:
            for route,keyword in [
                ("/integrations","ChatGPT / Claude MCP"),
                ("/movie","Нэг санаанаас"),
                ("/movie.css","text/css"),
                ("/integrations.css","text/css")
            ]:
                result=client.get(route)
                self.assertEqual(result.status_code,200,(route,result.text[:180]))
                if route.endswith(".css"):
                    self.assertIn(keyword,result.headers.get("content-type",""))
                else:
                    self.assertIn(keyword,result.text)
            self.assertEqual(client.get("/unknown.css").status_code,404)
        self.assertNotIn("<style>",(STATIC/"movie.html").read_text(encoding="utf-8"))
        self.assertIn('href="/movie.css?v=2"',(STATIC/"movie.html").read_text(encoding="utf-8"))
        self.assertIn('href="/integrations.css?v=1"',(STATIC/"integrations.html").read_text(encoding="utf-8"))

if __name__=="__main__":
    unittest.main()

"""Mastering and AI-frame-review gates must be safe even without provider keys."""
import os
import unittest
from unittest.mock import patch
from app import movie_mastering, movie_visual_qa

class MovieMasteringTests(unittest.TestCase):
    def test_1080_dimensions(self):
        master=movie_mastering.master_settings({"output_quality":"1080p","master_audio":True},60,"9:16")
        self.assertEqual(master["dimensions"],(1080,1920))
        self.assertTrue(master["master_audio"])
    def test_4k_cannot_be_false_advertised(self):
        with patch.dict(os.environ,{"RAINY_MOVIE_4K_ENABLED":"false"}):
            with self.assertRaises(ValueError):movie_mastering.master_settings({"output_quality":"4k"},60,"16:9")
        with patch.dict(os.environ,{"RAINY_MOVIE_4K_ENABLED":"true"}):
            m=movie_mastering.master_settings({"output_quality":"4k"},120,"16:9")
            self.assertEqual(m["dimensions"],(3840,2160))
            with self.assertRaises(ValueError):movie_mastering.master_settings({"output_quality":"4k"},700,"16:9")
    def test_srt_and_audio_settings(self):
        graph=movie_mastering.audio_filtergraph(1,2,True)
        self.assertIn("loudnorm",graph)
        self.assertIn("amix=inputs=3",graph)
        with self.assertRaises(ValueError):
            movie_mastering.master_settings({"subtitle_burn_in":True},30,"16:9")
        with self.assertRaises(ValueError):
            movie_mastering.master_settings({"ai_qa_consent":"maybe"},30,"16:9")
    def test_optional_visual_qa_off(self):
        with patch.dict(os.environ,{"RAINY_MOVIE_AI_QA_ENABLED":"false","OPENAI_API_KEY":""}):
            self.assertFalse(movie_visual_qa.available())

if __name__=="__main__":unittest.main()

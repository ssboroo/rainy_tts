"""Provider-free safety tests for RAINY production features."""
import unittest
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch
from app.production_suite import direct_script, plan_book, _wav_duration, _splice

class ProductionSuiteTests(unittest.TestCase):
    def test_director_uses_provider_tags_without_charging(self):
        a=direct_script("Сайн байна уу. Тавтай морил!","advertising")
        self.assertEqual(a["creditsCharged"],0)
        self.assertIn("[excited]",a["directedText"])
        self.assertEqual(a["sentences"],2)
        self.assertIn("Сайн байна уу.",a["original"])
        for invalid in ("invalid", None, "aggressive"):
            with self.assertRaises(ValueError):
                direct_script("Сайн байна уу.",invalid)
        with self.assertRaises(ValueError):
            direct_script("", "calm")
        with self.assertRaises(ValueError):
            direct_script("уу "*7000, "advertising")

    def test_mongolian_voice_directions_follow_explicit_emotion(self):
        script="Шивнэн хэлэв. Ууртайгаар хашхирав! Гунигтайгаар дурсав."
        result=direct_script(script,"advertising")
        lines=result["directedText"].splitlines()
        self.assertTrue(lines[0].startswith("[whispers] "),lines)
        self.assertTrue(lines[1].startswith("[angry] "),lines)
        self.assertTrue(lines[2].startswith("[sad] "),lines)
        self.assertEqual(result["original"],script)
        self.assertEqual(result["creditsCharged"],0)

    def test_mongolian_voice_director_preserves_existing_stage_tags(self):
        script="[whispers] Сайн уу. [happy] Баярлалаа!"
        result=direct_script(script,"cinematic")
        self.assertEqual(result["directedText"].count("[whispers]"),1)
        self.assertEqual(result["directedText"].count("[happy]"),1)
        self.assertNotIn("[curious] [whispers]",result["directedText"])

    def test_book_plan_is_bounded_and_unbilled(self):
        text=("Сайн байна уу. Урт өгүүлэмжийн эхлэл. "*180)
        plan=plan_book(text,"Миний ном","eleven_v4")
        self.assertGreater(plan["totalEstimatedCredits"],0)
        self.assertEqual(plan["creditsCharged"],0)
        self.assertGreaterEqual(plan["chapterCount"],1)
        self.assertTrue(all(ch["characters"]<=10000 for ch in plan["chapters"]))
        self.assertTrue(all(ch["estimatedCredits"]>0 for ch in plan["chapters"]))
        with self.assertRaises(ValueError):plan_book("а "*60000)
        with self.assertRaises(ValueError):plan_book("Сайн байна уу.","Ном","invalid-model")
        with self.assertRaises(ValueError):plan_book("Сайн байна уу.","Ном",multiplier=0.2)
        with self.assertRaises(ValueError):plan_book("".join(["a"*241]))

    def test_wav_boundary_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"source.wav"
            with wave.open(str(path),"wb") as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
                out.writeframes(b"\0\0"*24000)
            self.assertAlmostEqual(_wav_duration(path),1)
            other=Path(folder)/"bad.wav"
            with wave.open(str(other),"wb") as out:
                out.setnchannels(2);out.setsampwidth(2);out.setframerate(24000)
                out.writeframes(b"\0"*96000)
            with self.assertRaises(ValueError):_wav_duration(other)
            with patch("app.production_suite.subprocess.run") as run:
                run.side_effect=lambda args,**kwargs:(Path(args[-1]).write_bytes(b"x"*300),None)[1]
                _splice(path,path,0.1,0.3,Path(folder)/"out.mp3")
                command=run.call_args.args[0]
                self.assertIn("-filter_complex",command)
                self.assertEqual(command.count("-i"),2)
                self.assertIn("0.100",command[command.index("-filter_complex")+1])
                self.assertIn("0.300",command[command.index("-filter_complex")+1])

if __name__=="__main__":
    unittest.main()

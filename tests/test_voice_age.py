import unittest
from fastapi import HTTPException
from app.voice_age import normalize_age, apply_design_age, AGE_DESCRIPTORS

class VoiceAgeTests(unittest.TestCase):
    def test_normalizes_only_grounded_provider_labels(self):
        self.assertEqual(normalize_age("young"),"young")
        self.assertEqual(normalize_age("Middle-aged"),"middle_aged")
        self.assertEqual(normalize_age("elderly"),"old")
        self.assertEqual(normalize_age("adolescent"),"teen")
        self.assertIsNone(normalize_age("adult"))
        self.assertIsNone(normalize_age(None))
        self.assertIsNone(normalize_age("40"))
    def test_design_age_is_a_real_voice_description(self):
        for age in AGE_DESCRIPTORS:
            prompt = apply_design_age("Монгол өгүүлэгчтэй кино",age)
            self.assertIn("Perceived vocal age:",prompt)
            self.assertIn("Mongolian pronunciation",prompt)
            self.assertLessEqual(len(prompt),1000)
        self.assertEqual(apply_design_age("Монгол дуу",None),"Монгол дуу")
    def test_unknown_age_and_oversize_fail_before_paid_api(self):
        with self.assertRaises(HTTPException) as err:
            apply_design_age("Монгол өгүүлэгч", "25")
        self.assertEqual(err.exception.status_code,422)
        with self.assertRaises(HTTPException):
            apply_design_age("a"*980,"middle_aged")

if __name__=="__main__":
    unittest.main()

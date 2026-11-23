import unittest
from src.validation import run_validation
from src.dataset import generate, QUESTIONS
from src.rubric_engine import score_v0, score_v1, score_v2, score_v3


class TestValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results, cls.tm, cls.bypass = run_validation()

    def test_all_validation_scenarios_pass(self):
        for r in self.results:
            with self.subTest(r["id"]):
                self.assertTrue(r["passed"], r["detail"])

    def test_negation_guard(self):
        q = QUESTIONS["Q1"]
        txt = "Mutual exclusion is not needed for deadlock to occur."
        self.assertEqual(score_v0(txt, q)["mark"], 1)   # baseline wrongly credits
        self.assertEqual(score_v1(txt, q)["mark"], 1)   # initial design wrongly credits
        self.assertEqual(score_v2(txt, q)["mark"], 0)
        self.assertEqual(score_v3(txt, q)["mark"], 0)
        self.assertIn("NEGATION", score_v3(txt, q)["flags"])

    def test_dataset_is_reproducible(self):
        a, b = generate(), generate()
        self.assertEqual([r["text"] for r in a], [r["text"] for r in b])


if __name__ == "__main__":
    unittest.main(verbosity=2)

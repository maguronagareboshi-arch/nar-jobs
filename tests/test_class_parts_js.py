"""cloud/class_parts.py がサイトの js/class-parts.js raceClassParts と同じ読みをするか(本物のレース名 350 件・2026-11-04 の JS の出力)。
⛔JS を直したら fixtures/class_parts_js.json を作り直す(全件 24,494 名で違い 0 を確かめた・11/4)。
  py -3 -m unittest discover -s tests -p "test_class_parts_js.py"
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cloud"))
from class_parts import race_class_parts  # noqa: E402


class SameAsJs(unittest.TestCase):
    def test_fixture(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "class_parts_js.json"), encoding="utf-8") as f:
            rows = json.load(f)
        self.assertGreater(len(rows), 300)
        for r in rows:
            self.assertEqual(race_class_parts(r["name"], r["kind"], r["track"]), r["js"], r["track"] + " " + r["name"])


if __name__ == "__main__":
    unittest.main()

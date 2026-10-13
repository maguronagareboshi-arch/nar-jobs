"""騎手の免許番号(nar_runs.jockey_license)。⛔作り物の HTML で通さない= 本物の出馬表ページ
(keiba.go.jp DebaTable 2026-10-12 盛岡 1R・山本聡 2 人が同じレースに乗る)で照合する。⛔通信なし。"""
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))
sys.path.insert(0, str(ROOT / "pipeline"))
import nextday_card  # noqa: E402
import load_nar_official as lno  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "keiba_deba_20261012_morioka_r1.html"


class JockeyLicense(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        h = FX.read_text(encoding="utf-8")
        cls.race, cls.horses = nextday_card.parse_race(h, dt.date(2026, 10, 12), "盛岡", 1)

    def test_all_runners_have_license(self):
        self.assertEqual(len(self.horses), 12)
        for x in self.horses:
            self.assertRegex(x["jockey_license"] or "", r"^\d{5}$", x["horse_name"])

    def test_two_yamamoto_licenses(self):
        # 本物のページの略称は 31220= 山本紀・31139= 山本聡(2026-10-12 盛岡 1R の 10 番・12 番)
        got = {x["jockey_license"]: (x["runner_number"], x["jockey"]) for x in self.horses}
        self.assertEqual(got["31220"], (10, "山本紀"))
        self.assertEqual(got["31139"], (12, "山本聡"))

    def test_conv_run_sends_only_when_present(self):
        h = dict(self.horses[0])
        self.assertEqual(lno.conv_run(h)["jockey_license"], h["jockey_license"])
        h["jockey_license"] = None
        self.assertNotIn("jockey_license", lno.conv_run(h))
        h.pop("jockey_license")
        self.assertNotIn("jockey_license", lno.conv_run(h))

    def test_drop_when_column_missing(self):
        dedup = {"runs": {1: {"jockey_license": "31220", "jockey": "山本聡"}, 2: {"jockey": "x"}}}
        orig = lno.has_column
        try:
            lno.has_column = lambda *a, **k: False
            lno.drop_jockey_license_if_missing("u", "k", dedup, log=lambda *_: None)
            self.assertNotIn("jockey_license", dedup["runs"][1])
            dedup["runs"][1]["jockey_license"] = "31220"
            lno.has_column = lambda *a, **k: True
            lno.drop_jockey_license_if_missing("u", "k", dedup, log=lambda *_: None)
            self.assertEqual(dedup["runs"][1]["jockey_license"], "31220")
        finally:
            lno.has_column = orig


if __name__ == "__main__":
    unittest.main()

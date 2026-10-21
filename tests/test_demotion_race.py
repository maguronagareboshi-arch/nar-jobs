# -*- coding: utf-8 -*-
"""§294 cloud/demotion_race.py の毎日の便の絞り込み(⛔今日より前は書かない・今日は発走前だけ)。
実行: python -m unittest tests/test_demotion_race.py"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import demotion_race as DR  # noqa: E402


class LiveRows(unittest.TestCase):
    def setUp(self):
        self._e, self._p = DR.load_entries, DR.load_posts
        DR.load_entries = lambda url, key, tracks, a, b: [
            ("笠松", "2026-09-30", 1, "今日の前"), ("笠松", "2026-09-30", 9, "今日の後"),
            ("笠松", "2026-10-01", 1, "明日"), ("笠松", "2026-10-01", 1, "明日")]
        DR.load_posts = lambda url, key, tracks, d: {("笠松", 1): "1030", ("笠松", 9): "1600"}

    def tearDown(self):
        DR.load_entries, DR.load_posts = self._e, self._p

    def test_filter(self):
        now = dt.datetime(2026, 9, 30, 12, 0, tzinfo=DR.JST)
        rows = DR.live_rows("u", "k", "tokai", lambda t, n: {"horse_name": n} if n == "明日" else None,
                            lambda t: {"pending": False}, now)
        self.assertEqual([(r["race_date"], r["race_no"], r["horse_name"]) for r in rows],
                         [("2026-09-30", 9, "今日の後"), ("2026-10-01", 1, "明日")])
        self.assertEqual(rows[0]["venue"], "kasamatsu")
        self.assertIsNone(rows[0]["v"])
        self.assertEqual(rows[1]["v"], {"horse_name": "明日"})
        self.assertEqual(rows[1]["asof"], "2026-09-30")



class PreRaceLists(unittest.TestCase):
    def test_meta_needs_list_before_d(self):
        meta = {"KS": {"2026-09": "2026-09-24", "2026-06": "2026-06-20"}}
        days = ["2026-06-15", "2026-06-25", "2026-09-20", "2026-10-05"]
        # 9 月の見直しの日 9/24 を決めた一覧は 10/5= 10/1 の行には使わない
        self.assertEqual(DR.ks_meta_upto(meta, days, "2026-10-01"), {"2026-06": "2026-06-20"})
        self.assertEqual(DR.ks_meta_upto(meta, days, "2026-10-05"), meta["KS"])

if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""§212 能検の --backfill は既存の日を捨てない(合流)。⛔通信なし。py -3.12 -m unittest tests.test_noken_merge -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import noken_public as nk                                          # noqa: E402

KEY = lambda d: d["date"]                                         # noqa: E731
OLD = [{"date": f"2026-08-{i:02d}", "v": "old"} for i in range(1, 14)]      # 既存 13 日
NEW = [{"date": f"2026-08-{i:02d}", "v": "new"} for i in (11, 12, 13)]      # 取れた 3 日(重なり 3)


class NokenMerge(unittest.TestCase):
    def test_backfill_keeps_stored(self):
        days = nk.merge_days(OLD, NEW, KEY, backfill=True)
        self.assertEqual(len(days), 13)
        self.assertEqual([d["v"] for d in days[:3]], ["new"] * 3)   # 同じ鍵は取り直した方
        self.assertEqual(days[0]["date"], "2026-08-13")

    def test_replace_only_new(self):
        self.assertEqual(len(nk.merge_days(OLD, NEW, KEY, backfill=True, replace=True)), 3)

    def test_diff_unchanged(self):
        days = nk.merge_days(OLD, [{"date": "2026-08-14", "v": "new"}], KEY)
        self.assertEqual((len(days), days[0]["date"]), (14, "2026-08-14"))


if __name__ == "__main__":
    unittest.main()

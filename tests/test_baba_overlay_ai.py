# -*- coding: utf-8 -*-
"""2026-10-26 南関の馬場差を予想 AI の日の値(D5)にそろえる= si5_store.write_d5 と cloud/baba.py overlay_ai。"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline/ai/v3"))
sys.path.insert(0, str(ROOT / "pipeline/ai"))
sys.path.insert(0, str(ROOT / "cloud"))
import base_v1 as B1  # noqa: E402
import si5_store as S  # noqa: E402
import baba  # noqa: E402


class WriteD5Test(unittest.TestCase):
    def setUp(self):
        U = pd.DataFrame({"track": ["大井", "大井", "名古屋", "川崎", "川崎"],
                          "race_date": ["2026-10-01", "2026-10-01", "2026-10-01", "2026-09-01", "2026-10-13"]})
        S.CACHE.clear()
        S.CACHE.update(U=U, R=pd.DataFrame({"D5": [-0.456, -0.456, 0.3, 0.111, np.nan]}))
        self.meta = {}
        self.saved = B1.creds, B1.upsert, B1.sb_get

        def up(base, key, table, conflict, rows):
            self.assertEqual((table, conflict), ("nar_meta", "key"))
            self.assertIn("updated_at", rows[0])
            self.meta[rows[0]["key"]] = rows[0]["value"]
            return 201, ""
        B1.creds = lambda: ("http://x", "k")
        B1.upsert = up
        B1.sb_get = lambda base, key, path: ([{"value": self.meta[S.META]}] if S.META in self.meta else [])

    def tearDown(self):
        B1.creds, B1.upsert, B1.sb_get = self.saved

    def test_days(self):
        self.assertEqual(S.d5_days(), {"2026-10-01": {"ooi": -0.46}, "2026-09-01": {"kawasaki": 0.11}})

    def test_first_full_then_recent(self):
        S.write_d5("2026-10-14")                      # まだ無い= 全期間(当日より前)
        self.assertEqual(self.meta[S.META]["days"], {"2026-09-01": {"kawasaki": 0.11}, "2026-10-01": {"ooi": -0.46}})
        self.meta[S.META]["days"]["2026-01-01"] = {"ooi": 9.0}
        S.CACHE["R"] = pd.DataFrame({"D5": [-0.2, -0.2, 0.3, 0.5, np.nan]})
        n = S.write_d5("2026-10-14")                  # 直近 21 日だけ足し直す= 9/1 と 1/1 はそのまま
        self.assertEqual(n, 1)
        self.assertEqual(self.meta[S.META]["days"],
                         {"2026-01-01": {"ooi": 9.0}, "2026-09-01": {"kawasaki": 0.11}, "2026-10-01": {"ooi": -0.2}})

    def test_two_values_stop(self):
        S.CACHE["R"] = pd.DataFrame({"D5": [-0.4, -0.5, 0.3, 0.1, np.nan]})
        with self.assertRaises(AssertionError):
            S.d5_days()


class OverlayTest(unittest.TestCase):
    def test_overlay(self):
        smp = [("大井", "2026-10-01", 1200, "C1", 73.0, "良", 1, 1), ("大井", "2026-10-01", 1600, "C1", 99.0, "良", 2, 1),
               ("大井", "2026-10-01", 1600, "C1", 99.5, "良", 2, 2),
               ("川崎", "2026-10-02", 1400, "C1", 88.0, "良", 1, 1), ("園田", "2026-10-01", 1400, "C1", 88.0, "良", 1, 1)]
        days = {"2026-10-01": {"ooi": {"d": -1.0, "g": -0.5, "d1": -0.7, "n": 9}, "sonoda": {"d": 0.4, "d1": 0.3}},
                "2026-10-02": {"kawasaki": {"d": 0.2, "d1": 0.1, "p": True}}}
        ai = {"2026-10-01": {"ooi": -0.45, "sonoda": 9.9}, "2026-10-02": {"kawasaki": 0.3}}
        self.assertEqual(baba.overlay_ai(days, smp, ai), 1)
        # 平均距離= レースごとに 1 回(1200・1600)= 1400 → d = −0.45 × 1.4 = −0.63 → −0.6。g はそのまま
        self.assertEqual(days["2026-10-01"]["ooi"], {"d": -0.6, "g": -0.5, "d1": -0.45, "n": 9, "s": "ai"})
        self.assertEqual(days["2026-10-01"]["sonoda"], {"d": 0.4, "d1": 0.3}, "南関以外は触らない")
        self.assertEqual(days["2026-10-02"]["kawasaki"], {"d": 0.2, "d1": 0.1, "p": True}, "暫定の日は触らない")


if __name__ == "__main__":
    unittest.main()

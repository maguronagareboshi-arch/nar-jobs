# -*- coding: utf-8 -*-
"""2026-10-26 pipeline/ai/v3/si5_store.py= 南関だけ・SI5 の無い走は書かない・直近 21 日(全期間)・読み直しの照合。
2026-10-27 表示の直し disp(流れの升 − 帯の平均・大井の砂替え)= 定数が 0 なら SI5 のまま・手で数えた値と一致。"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline/ai/v3"))
sys.path.insert(0, str(ROOT / "pipeline/ai"))
import base_v1 as B1  # noqa: E402
import si5_store as S  # noqa: E402
import sealed  # noqa: E402

ZERO = {"TAG": "t", "DB_CUT": [1250, 1650], "POS": [0.25, 0.5], "CUT": [[0.0] * 9] * 3, "ERR": [], "MEAN": [0.0, 0.0, 0.0], "SAND": []}


class Si5StoreTest(unittest.TestCase):
    def setUp(self):
        U = pd.DataFrame({"track": ["大井", "大井", "名古屋", "川崎", "川崎"],
                          "race_date": ["2026-10-01", "2026-10-01", "2026-10-01", "2026-09-01", "2026-10-13"],
                          "race_no": [1, 1, 1, 2, 3], "runner_number": [1, 2, 1, 1, 4],
                          "hk": ["A|2020", "B|2021", "C|2020", "D|2019", "E|2022"]})
        U = U.assign(dtk=U.race_date + "_" + U.track, distance_m=1200, r_F=0.0, r_L=0.0, time_sec=75.0, last3f=38.0,
                     Draw_T=0.0, D_T=0.0, bc_T=62.0, n_T=12)
        S.CACHE.clear()
        S.CACHE.update(U=U, R=pd.DataFrame({"SI5": [71.234, np.nan, 50.0, 80.0, 66.66], "D_proj": np.nan}))
        self.get0 = sealed.get
        sealed.get = lambda part: ZERO if part == "si5_disp" else self.get0(part)
        self.db = {}
        self.saved = B1.creds, B1.upsert, B1.sb_get

        def up(base, key, table, conflict, rows):
            self.assertEqual((table, conflict), ("nar_si5", S.CONFLICT))
            for r in rows:
                self.db[(r["track"], r["race_date"], r["race_no"], r["runner_number"])] = r["si5"]
            return 201, ""
        B1.creds = lambda: ("http://x", "k")
        B1.upsert = up
        B1.sb_get = lambda base, key, path: [
            dict(track=k[0], race_date=k[1], race_no=k[2], runner_number=k[3], si5=v)
            for k, v in self.db.items() if "offset=0" in path]

    def tearDown(self):
        B1.creds, B1.upsert, B1.sb_get = self.saved
        sealed.get = self.get0

    def test_recent(self):
        c = S.write("2026-10-14")
        self.assertEqual(self.db, {("大井", "2026-10-01", 1, 1): 71.2, ("川崎", "2026-10-13", 3, 4): 66.7})
        self.assertEqual(c, {"行": 2, "DB にある": 2, "一致": 2})

    def test_all(self):
        c = S.write("2026-10-14", days=None)
        self.assertEqual(len(self.db), 3)
        self.assertEqual(c["一致"], 3)


    def test_disp(self):
        c = dict(ZERO, CUT=[[-4, -3, -2, -1, 0, 0.5, 0.8, 1.0, 1.2]] * 3, ERR=[[0, 9, 2, 3.0]], MEAN=[0.5, 0.0, 0.0],
                 SAND=[["大井", "2023-10-26", "2024-12-31"]])
        sealed.get = lambda part: c
        n = 6
        U = pd.DataFrame({"track": ["大井"] * n, "race_date": ["2024-01-10"] * n, "race_no": [1, 1, 1, 1, 2, 2],
                          "runner_number": [1, 2, 3, 4, 1, 2], "hk": list("ABCDEF"), "dtk": ["2024-01-10_大井"] * n,
                          "distance_m": 1200, "r_F": [2.0] * 4 + [0.0] * 2, "r_L": [-1.0] * 4 + [0.0] * 2,
                          "time_sec": [75.0, 76.0, 77.0, 78.0, 75.0, 76.0], "last3f": 38.0,
                          "Draw_T": 1.0, "D_T": 0.6, "bc_T": 62.5, "n_T": 12})
        R = pd.DataFrame({"SI5": 70.0, "D_proj": [0.1, np.nan, 0.1, 0.1, 0.1, 0.1]}, index=range(n))
        # 配分: 1R = (2 − 1) − (−1 + 0.5) = 1.5 → 分位 9・2R = −1.5 → 分位 3。位置: 1R の 3・4 番 = 後ろ。砂替え = 0.4 × f × 16。
        np.testing.assert_allclose(S.disp(U, R), [72.7, 75.9, 75.7, 75.7, 72.7, 72.7])
        x = S.frame(U.assign(track=["川崎"] * n), R)
        np.testing.assert_allclose(x.si5, [69.5, 69.5, 72.5, 72.5, 69.5, 69.5])


if __name__ == "__main__":
    unittest.main()

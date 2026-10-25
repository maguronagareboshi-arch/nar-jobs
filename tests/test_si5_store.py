# -*- coding: utf-8 -*-
"""2026-10-26 pipeline/ai/v3/si5_store.py= 南関だけ・SI5 の無い走は書かない・直近 21 日(全期間)・読み直しの照合。"""
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


class Si5StoreTest(unittest.TestCase):
    def setUp(self):
        U = pd.DataFrame({"track": ["大井", "大井", "名古屋", "川崎", "川崎"],
                          "race_date": ["2026-10-01", "2026-10-01", "2026-10-01", "2026-09-01", "2026-10-13"],
                          "race_no": [1, 1, 1, 2, 3], "runner_number": [1, 2, 1, 1, 4],
                          "hk": ["A|2020", "B|2021", "C|2020", "D|2019", "E|2022"]})
        S.CACHE.clear()
        S.CACHE.update(U=U, R=pd.DataFrame({"SI5": [71.234, np.nan, 50.0, 80.0, 66.66]}))
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

    def test_recent(self):
        c = S.write("2026-10-14")
        self.assertEqual(self.db, {("大井", "2026-10-01", 1, 1): 71.2, ("川崎", "2026-10-13", 3, 4): 66.7})
        self.assertEqual(c, {"行": 2, "DB にある": 2, "一致": 2})

    def test_all(self):
        c = S.write("2026-10-14", days=None)
        self.assertEqual(len(self.db), 3)
        self.assertEqual(c["一致"], 3)


if __name__ == "__main__":
    unittest.main()

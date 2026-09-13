# -*- coding: utf-8 -*-
"""§169 段 3 逃げそうな馬 1 頭(pick)と隊列の見込み(order)の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_tenkai*.py"

確かめるのは=
  ①pick_order= 1 角の平均位置 p が最小の馬・同点は馬番の小さい方・型なし(p の無い馬)は入れない
  ②build_races= 各レースに pick と order を足す・既存の鍵(n/k/lead/front/mid/back/none/h/w)はそのまま
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud.tenkai import build_races, pick_order                      # noqa: E402


class Pick(unittest.TestCase):
    def test_pick_order(self):
        hh = {"3": {"s": "先行", "p": 0.31}, "7": {"s": "逃げ", "p": 0.12},
              "1": {"s": "差し", "p": 0.55}, "5": {"s": "逃げ", "p": 0.12}}
        self.assertEqual(pick_order(hh), (5, [5, 7, 3, 1]), "同点は馬番の小さい方")
        self.assertEqual(pick_order({}), (None, []))
        self.assertEqual(pick_order({"2": {"s": "追込"}}), (None, []), "p の無い馬を並べている")

    def test_build_races(self):
        # 1 レース 3 頭。過去 2 走ずつの 1 角の順位(頭数 10)で型を付ける。4 番は過去走なし= 型なし
        day_races = [{"track": "大井", "race_no": 5}]
        day_runs = [{"track": "大井", "race_no": 5, "runner_number": u, "horse_name": nm}
                    for u, nm in ((1, "A"), (2, "B"), (3, "C"), (4, "D"))]
        ranks_of = {("大井", "2026-08-01", 1): {11: 1, 12: 5, 13: 9},
                    ("大井", "2026-08-08", 1): {11: 2, 12: 4, 13: 10}}
        for k in ranks_of:
            for x in range(1, 11):
                ranks_of[k].setdefault(20 + x, x)   # 頭数を 10 に(順位の重複はしない)
        ranks_of[("大井", "2026-08-01", 1)] = {11: 1, 12: 5, 13: 9, 21: 2, 22: 3, 23: 4, 24: 6, 25: 7, 26: 8, 27: 10}
        ranks_of[("大井", "2026-08-08", 1)] = {11: 2, 12: 4, 13: 10, 21: 1, 22: 3, 23: 5, 24: 6, 25: 7, 26: 8, 27: 9}
        past = {nm: [{"track": "大井", "race_date": d, "race_no": 1, "runner_number": u}
                     for d in ("2026-08-08", "2026-08-01")]
                for nm, u in (("A", 13), ("B", 11), ("C", 12))}
        out, _k = build_races(day_races, day_runs, past, ranks_of)
        rec = out["ooi-5"]
        self.assertEqual(rec["pick"], 2)                       # B= 平均位置 0.15
        self.assertEqual(rec["order"], [2, 3, 1])              # 型なしの 4 番は入れない
        self.assertEqual(rec["none"], [4])
        for key in ("n", "k", "lead", "front", "mid", "back", "none", "h", "w"):
            self.assertIn(key, rec)
        self.assertEqual(rec["lead"], [2])


if __name__ == "__main__":
    unittest.main()

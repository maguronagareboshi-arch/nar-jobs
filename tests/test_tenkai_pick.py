# -*- coding: utf-8 -*-
"""§169 段 3 逃げそうな馬 1 頭(pick)と隊列の見込み(order)の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_tenkai*.py"

確かめるのは=
  ①pick_order= 1 角の平均位置 p が最小の馬・同点は馬番の小さい方・型なし(p の無い馬)は入れない
  ②build_races= 派生表 nar_run_facts の型をそのまま写し、pick と order を足す(既存の鍵はそのまま)
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
        # §238a2 型は派生表 nar_run_facts の写し(style/style_p/style_n)を渡すだけ。4 番は行なし= 型なし
        day_races = [{"track": "大井", "race_no": 5}]
        day_runs = [{"track": "大井", "race_no": 5, "runner_number": u, "horse_name": nm}
                    for u, nm in ((1, "A"), (2, "B"), (3, "C"), (4, "D"))]
        past = {nm: [{"track": "大井", "race_date": d, "race_no": 1, "runner_number": u}
                     for d in ("2026-08-08", "2026-08-01")]
                for nm, u in (("A", 13), ("B", 11), ("C", 12))}
        style_of_row = {("大井", 5, 1): ("差し", 0.95, 2),      # A= 9,10 着位置 / 10 頭
                        ("大井", 5, 2): ("逃げ", 0.15, 2),      # B= 1,2 番手
                        ("大井", 5, 3): ("先行", 0.45, 2)}      # C= 5,4 番手
        out, _k = build_races(day_races, day_runs, past, style_of_row)
        rec = out["ooi-5"]
        self.assertEqual(rec["pick"], 2)                       # B= 平均位置 0.15
        self.assertEqual(rec["order"], [2, 3, 1])              # 型なしの 4 番は入れない
        self.assertEqual(rec["none"], [4])
        self.assertEqual(rec["h"]["1"], {"s": "差し", "p": 0.95, "m": 2})
        for key in ("n", "k", "lead", "front", "mid", "back", "none", "h", "w"):
            self.assertIn(key, rec)
        self.assertEqual(rec["lead"], [2])


if __name__ == "__main__":
    unittest.main()

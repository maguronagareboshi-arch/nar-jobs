# -*- coding: utf-8 -*-
"""§200 D1 cloud/class_calc.py の履歴の段= 走の日ごとに 1 行・asof=D・D=きょう の値は calc 列と同じ手順。"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import class_calc as C  # noqa: E402

D = dt.date.fromisoformat
LINES = [("Ａ", 11_000_000, None), ("Ｂ", 7_000_000, 11_000_000), ("Ｃ１", 4_600_000, 7_000_000),
         ("Ｃ２", 3_000_000, 4_600_000), ("Ｃ３上", 2_000_000, 3_000_000), ("Ｃ３下", 0, 2_000_000)]


def run(d, tr, fin=1, prize=1_000_000, jra=False):
    return {"d": d, "tr": tr, "fin": fin, "prize": prize, "jra": jra, "name": "Ｃ２", "cls": "Ｃ２"}


HORSE = {"code": "1", "horse_name": "テスト", "age": 5,
         "runs": [run("2026-09-13", "高知"), run("2026-09-06", "佐賀"), run("2026-08-30", "高知"),
                  run("2026-08-01", "Ｊ東京", jra=True)]}


class T(unittest.TestCase):
    def test_targets(self):
        # その場の地方の走の日ごとに 1 つ(他場・中央・窓の外は作らない)+ 出馬表(同名の別馬は除く)
        got = C.hist_targets([HORSE], {"1": "2021-04-01"}, ("高知",), D("2026-09-01"),
                             [("テスト", "2021-04-01", D("2026-09-20"), "高知"), ("テスト", "2020-01-01", D("2026-09-27"), "高知")])
        self.assertEqual(sorted(got), [("1", D("2026-09-13"), "高知"), ("1", D("2026-09-20"), "高知")])

    def test_last_local(self):
        self.assertEqual(C.last_local(HORSE["runs"], D("2026-09-13")), "佐賀")    # 当日の走は含めない
        self.assertEqual(C.last_local(HORSE["runs"], D("2026-09-14")), "高知")
        self.assertIsNone(C.last_local(HORSE["runs"], D("2026-08-30")))

    def test_same_as_calc_column(self):
        # D= きょう の行 = apply が calc 列に書く値(kochi_calc(asof=きょう))・転入前の note も同じ規則
        b = D("2021-04-01")
        ctx = {"lines": LINES, "lag": C.KOCHI_LAG}
        c = C.hist_calc("kochi", ctx, HORSE, b, D("2026-09-14"), "高知")
        want = C.kochi_calc(LINES, HORSE["runs"], D("2026-09-14"), C.KOCHI_LAG, lambda x: x.year - b.year)
        self.assertEqual(c, want)
        self.assertEqual(c["asof"], "2026-09-14")
        # D=9/13 はその日の走を数えない・前の地方の走が佐賀= 転入前の note
        c13 = C.hist_calc("kochi", ctx, HORSE, b, D("2026-09-13"), "高知")
        self.assertEqual(c["value"] - c13["value"], 1_000_000)
        self.assertTrue(c13["note"].startswith("転入前の場の走"))
        self.assertNotIn("note", c)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""cloud/pace_pred_test.py の 3 則(⛔ネット・DB なし)。
実行: py -3.12 -X utf8 -m unittest tests.pace_pred_test_test"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud import pace_pred_test as pp  # noqa: E402


def run(d, no, u, name="馬"):
    return {"track": "大井", "race_date": d, "race_no": no, "runner_number": u, "horse_name": name, "birth_date": None}


class FeatureLeak(unittest.TestCase):
    def test_future_runs_not_used(self):
        d = "2026-03-10"
        past = [run("2026-01-%02d" % (i + 1), 1, 1) for i in range(3)]
        future = [run("2026-03-10", 2, 1), run("2026-04-01", 1, 1), run("2026-05-01", 1, 1)]
        ten_of = {("大井", r["race_date"], 1, 1): (36.0, 1200) for r in past}
        for r in future:   # 未来の走は極端に速い
            ten_of[("大井", r["race_date"], r["race_no"], 1)] = (30.0, 1200)
        std = {("大井", 1200): 36.5}
        band = {"大井": [-0.3, 0.3]}
        rows = [run(d, 5, 1)]
        sty = {1: "逃げ"}
        hist_only = {"馬": sorted(past, key=lambda x: x["race_date"], reverse=True)}
        hist_all = {"馬": sorted(past + future, key=lambda x: (x["race_date"], x["race_no"]), reverse=True)}
        f0, a0 = pp.race_features("大井", d, rows, hist_only, sty, ten_of, std, band)
        f1, a1 = pp.race_features("大井", d, rows, hist_all, sty, ten_of, std, band)
        self.assertEqual(f0, f1)
        self.assertEqual(a0, a1)
        self.assertEqual(f0["f1"], -0.5)
        self.assertEqual(a0, "速い")


class ConstModeLast12(unittest.TestCase):
    def test_c_is_mode_of_previous_12_months(self):
        recs = []

        def add(ym, y, n):
            for _ in range(n):
                recs.append({"t": "大井", "ym": ym, "y": y, "f": {}, "a": None})
        add("2024-08", "遅い", 50)          # 13 か月前= 窓の外(入れば「遅い」が最頻)
        add("2024-09", "速い", 10)
        add("2025-03", "平均", 12)
        add("2025-08", "速い", 3)           # 前 12 か月= 速い 13・平均 12
        add("2025-09", "速い", 4)
        add("2025-09", "平均", 6)           # 当てる月(自分の月は窓に入らない)
        st = pp.walk_forward(recs, ["2025-09"], use_b=False)["大井"]
        self.assertEqual(st["n"], 10)
        self.assertEqual(st["c_n"], 10)
        self.assertEqual(st["c_hit"], 4)    # 「速い」と言い続けて 4 本当たる
        self.assertEqual(pp.mode_label(["平均", "速い"]), "速い")
        self.assertIsNone(pp.mode_label([]))


class McNemarCount(unittest.TestCase):
    def test_pairs_and_p(self):
        # 同じレースの (B 当たり, C 当たり)。両方当たり・両方外れは数えない
        pairs = [(True, False)] * 7 + [(False, True)] * 2 + [(True, True)] * 30 + [(False, False)] * 11
        self.assertEqual(pp.mc_count(pairs), (7, 2))
        self.assertAlmostEqual(pp.mc_p(7, 2), 0.1796875)     # 2×P(X≤2), X~Bin(9, 1/2)= 2×46/512
        self.assertEqual(pp.mc_p(0, 0), 1.0)
        self.assertAlmostEqual(pp.mc_p(10, 0), 2 / 1024)
        adj = pp.holm({"甲": 0.01, "乙": 0.04, "丙": 0.03})
        self.assertAlmostEqual(adj["甲"], 0.03)
        self.assertAlmostEqual(adj["丙"], 0.06)
        self.assertAlmostEqual(adj["乙"], 0.06)               # 単調にそろえる(0.04×1 より前の 0.06)
        st = {"大井": {"bc_b": 10, "bc_c": 0}, "高知": {"bc_b": 0, "bc_c": 10}}
        r = pp.mcnemar_rows(st, ("大井", "高知"), "bc_b", "bc_c")
        self.assertTrue(r["大井"]["pass"])
        self.assertFalse(r["高知"]["pass"])                    # 有意でも C が多い向きは合格にしない


if __name__ == "__main__":
    unittest.main()

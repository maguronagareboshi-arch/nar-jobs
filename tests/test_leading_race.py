# -*- coding: utf-8 -*-
"""リーディング争い cloud/leading_race.py の固定テスト(通信なし)。"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
import leading_race as L  # noqa: E402

NOW = dt.datetime(2026, 10, 26, 5, 50)


def w(d, t, r, j, tr="調教師A"):
    return {"race_date": d, "track": t, "race_no": r, "runner_number": 1, "jockey": j, "trainer": tr}


ROWS = [
    w("2026-01-02", "高知", 1, "乙"), w("2026-01-02", "高知", 2, "乙"), w("2026-01-02", "大井", 1, "甲"),
    w("2026-01-03", "大井", 2, "甲"), w("2026-01-03", "佐賀", 1, "丙"), w("2026-01-03", "佐賀", 2, "丙"),
    w("2026-01-05", "高知", 3, "丁"),
]
KDAYS = {"2026-01-05": [["kochi", 1]], "2026-10-27": [["kochi", 1], ["ooi", 1]],
         "2026-10-28": [["saga", 1]], "2027-01-01": [["kochi", 1]]}


class T(unittest.TestCase):
    def setUp(self):
        self.out = L.build(ROWS, KDAYS, "2026-10-26", NOW)

    def test_sum_d_equals_w(self):
        for kind in ("jockey", "trainer"):
            for g, lst in self.out[kind].items():
                for p in lst:
                    self.assertEqual(sum(L.B36.index(c) for c in p["d"]), p["w"], (kind, g, p["name"]))
                    self.assertEqual(len(p["d"]), len(self.out["days"]))

    def test_tie_order(self):
        # 甲 乙 丙 が 2 勝・丁 1 勝 → 勝ち数→名前順
        self.assertEqual([(p["name"], p["w"]) for p in self.out["jockey"]["all"]],
                         sorted([("乙", 2), ("甲", 2), ("丙", 2)], key=lambda x: x[0]) + [("丁", 1)])
        self.assertEqual([p["name"] for p in self.out["jockey"]["kochi"]], ["乙", "丁"])
        self.assertEqual(self.out["jockey"]["kochi"][0]["d"], "200")
        self.assertEqual(self.out["trainer"]["all"][0]["w"], 7)

    def test_gdays(self):
        self.assertEqual(self.out["days"], ["2026-01-02", "2026-01-03", "2026-01-05"])
        self.assertEqual(self.out["gdays"]["kochi"], "101")
        self.assertEqual(self.out["gdays"]["minamikanto"], "110")
        self.assertEqual(self.out["gdays"]["saga"], "010")
        self.assertEqual(self.out["gdays"]["banei"], "000")

    def test_remain(self):
        r = self.out["remain"]
        self.assertEqual((r["all"], r["kochi"], r["minamikanto"], r["saga"], r["hyogo"]), (2, 1, 1, 1, 0))
        self.assertEqual(self.out["schedule_through"], "2027-01-01")
        self.assertEqual((self.out["year"], self.out["asof"], self.out["made"]), (2026, "2026-10-26", "2026-10-26T05:50+09:00"))

    def test_unknown_track(self):
        with self.assertRaises(SystemExit):
            L.build(ROWS + [w("2026-01-02", "東京", 1, "甲")], KDAYS, "2026-10-26", NOW)


if __name__ == "__main__":
    unittest.main()

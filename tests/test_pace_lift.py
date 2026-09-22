# -*- coding: utf-8 -*-
"""§224 段 2a 脚質 × ペースの倍率の数え方の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_pace_lift*.py"

確かめるのは=
  ①距離帯= 200m 刻みに丸める・1200m 未満は出さない
  ②月の並び= 年をまたぐ・既定は直前の月で終わる 12 か月
  ③数え方= ペースの行の無いレース / 脚質の無い馬 / 取消(そもそも行が来ない)を数えない・
    表に無い場(帯広ば)を落とす・3 着内は finish<=3
  ④20 走未満の枡は rate も lift も null(⛔1.0 で埋めない)
  ⑤lift= その枡の率 ÷ 場×距離帯の全体の率
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud.pace_lift import (band_of, count, default_months, month_range,   # noqa: E402
                             pack, split_by_track)
import datetime as dt                                                       # noqa: E402


def race(track, no, dist):
    return {"track": track, "race_date": "2026-05-01", "race_no": no, "distance_m": dist}


def pace(no, word):
    return {"track": "高知", "race_date": "2026-05-01", "race_no": no, "pace": word}


def fact(no, umaban, style):
    return {"track": "高知", "race_date": "2026-05-01", "race_no": no,
            "umaban": umaban, "style": style}


def run(track, no, umaban, finish):
    return {"track": track, "race_date": "2026-05-01", "race_no": no,
            "runner_number": umaban, "finish": finish}


class Band(unittest.TestCase):
    def test_round(self):
        self.assertEqual(band_of(1300), 1400)
        self.assertEqual(band_of(1400), 1400)
        self.assertEqual(band_of(1490), 1400)
        self.assertEqual(band_of(1510), 1600)
        self.assertEqual(band_of(1200), 1200)

    def test_short(self):
        self.assertIsNone(band_of(1199))
        self.assertIsNone(band_of(800))


class Months(unittest.TestCase):
    def test_range(self):
        m = month_range("2025-11", "2026-02")
        self.assertEqual([x[0] for x in m], ["2025-11", "2025-12", "2026-01", "2026-02"])
        self.assertEqual(m[0][1], "2025-11-01")
        self.assertEqual(m[0][2], "2025-11-30")
        self.assertEqual(m[1][2], "2025-12-31")
        self.assertEqual(m[3][2], "2026-02-28")

    def test_default(self):
        self.assertEqual(default_months(dt.date(2026, 9, 22)), ("2025-09", "2026-08"))
        self.assertEqual(default_months(dt.date(2026, 1, 3)), ("2025-01", "2025-12"))


class Count(unittest.TestCase):
    def setUp(self):
        # 1R= 高知 1400m 速い / 2R= 高知 1400m 平均 / 3R= 高知 1400m だがペースの行なし
        # 4R= 帯広ば(表に無い場)/ 5R= 高知 1000m(1200m 未満)
        self.paces = [pace(1, "速い"), pace(2, "平均"), pace(5, "速い"),
                      {"track": "帯広ば", "race_date": "2026-05-01", "race_no": 4, "pace": "速い"}]
        self.races = [race("高知", 1, 1400), race("高知", 2, 1400), race("高知", 3, 1400),
                      race("帯広ば", 4, 1600), race("高知", 5, 1000)]
        self.facts = [fact(1, 1, "逃げ"), fact(1, 2, "逃げ"), fact(1, 3, "差し"),
                      fact(2, 1, "逃げ"), fact(3, 1, "逃げ"), fact(5, 1, "逃げ"),
                      {"track": "帯広ば", "race_date": "2026-05-01", "race_no": 4,
                       "umaban": 1, "style": "逃げ"}]
        self.runs = [run("高知", 1, 1, 1), run("高知", 1, 2, 5), run("高知", 1, 3, 3),
                     run("高知", 1, 4, 2),                      # 脚質が無い= 数えない
                     run("高知", 2, 1, 4),
                     run("高知", 3, 1, 1),                      # ペースの行が無い= 数えない
                     run("帯広ば", 4, 1, 1),                    # 表に無い場= 数えない
                     run("高知", 5, 1, 1)]                      # 1000m= 数えない

    def test_cells(self):
        base, cells = count(self.paces, self.races, self.facts, self.runs)
        self.assertEqual(base, {("kochi", 1400): [4, 2]})       # 1R の 3 頭 + 2R の 1 頭・3 着内 2
        self.assertEqual(cells[("kochi", 1400, "逃げ", "速い")], [2, 1])
        self.assertEqual(cells[("kochi", 1400, "差し", "速い")], [1, 1])
        self.assertEqual(cells[("kochi", 1400, "逃げ", "平均")], [1, 0])
        self.assertEqual(len(cells), 3)
        self.assertNotIn(("kochi", 1000, "逃げ", "速い"), cells)

    def test_accumulates(self):
        acc = count(self.paces, self.races, self.facts, self.runs)
        acc = count(self.paces, self.races, self.facts, self.runs, acc)
        self.assertEqual(acc[0][("kochi", 1400)], [8, 4])
        self.assertEqual(acc[1][("kochi", 1400, "逃げ", "速い")], [4, 2])


class Pack(unittest.TestCase):
    months = [("2025-09", "2025-09-01", "2025-09-30"), ("2026-08", "2026-08-01", "2026-08-31")]

    def test_small_cell_is_null(self):
        base = {("kochi", 1400): [400, 100]}                    # 全体 25%
        cells = {("kochi", 1400, "逃げ", "速い"): [100, 41],      # 41% → 1.64 倍
                 ("kochi", 1400, "追込", "速い"): [19, 9]}        # 20 走未満
        v = pack(base, cells, self.months, "2026-09-22")
        hit = v["cells"]["kochi|1400|逃げ|速い"]
        self.assertEqual(hit["n"], 100)
        self.assertEqual(hit["rate"], 0.41)
        self.assertEqual(hit["base_rate"], 0.25)
        self.assertEqual(hit["lift"], 1.64)
        thin = v["cells"]["kochi|1400|追込|速い"]
        self.assertEqual(thin["n"], 19)
        self.assertIsNone(thin["rate"])
        self.assertIsNone(thin["lift"])                          # ⛔1.0 で埋めない
        self.assertEqual(v["months"], ["2025-09", "2026-08"])
        self.assertEqual(v["min_n"], 20)

    def test_thin_base_gives_no_lift(self):
        v = pack({("saga", 1800): [10, 4]}, {("saga", 1800, "逃げ", "遅い"): [10, 4]},
                 self.months, "2026-09-22")
        self.assertIsNone(v["base"]["saga|1800"]["rate"])
        self.assertIsNone(v["cells"]["saga|1800|逃げ|遅い"]["lift"])

    def test_split(self):
        v = pack({("kochi", 1400): [400, 100], ("saga", 1400): [400, 100]},
                 {("kochi", 1400, "逃げ", "速い"): [100, 41],
                  ("saga", 1400, "逃げ", "速い"): [100, 20]}, self.months, "2026-09-22")
        rows = dict(split_by_track(v))
        self.assertEqual(rows["pace_lift:v1"]["tracks"], ["kochi", "saga"])
        self.assertTrue(rows["pace_lift:v1"]["split"])
        self.assertEqual(list(rows["pace_lift:v1:kochi"]["cells"]), ["kochi|1400|逃げ|速い"])
        self.assertEqual(rows["pace_lift:v1:saga"]["months"], ["2025-09", "2026-08"])


if __name__ == "__main__":
    unittest.main()

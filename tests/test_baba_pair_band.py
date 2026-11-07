# -*- coding: utf-8 -*-
"""馬場差の AB・BC 帯の「両側の級の平均」段と "rq"(2026-11-08)。⛔通信ゼロ・作り物の値はこの試験の中だけ。

確かめるのは 3 つ=
  ①AB で b の段(365・1095)が足りないとき、基準= "*A" と "*B" の中央値の平均(c の窓 365 で取れる)→ r に入り rq=1
  ②字だけの帯(c の段)で出た基準も rq=1・b の段で出たら rq なし
  ③d の段(場×距離の全クラス)で出た基準は r に入れない(d/g の計算には今どおり使う)
"""
import datetime as dt
import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud import baba  # noqa: E402

DAY = dt.date(2026, 9, 13)


def hist(by_band, by_dist, dist, band, fin, base, n, step=7):
    for i in range(1, n + 1):
        day = (DAY - dt.timedelta(days=i * step)).isoformat()
        t = base + fin * 0.3 + (i % 3) * 0.1
        by_band.setdefault((dist, band, "良", fin), []).append((day, t))
        cb = baba.coarse_key(band)
        if cb:
            by_band.setdefault((dist, cb, "良", fin), []).append((day, t))
        by_dist.setdefault((dist, "良", fin), []).append((day, t))


def finish(by_band, by_dist):
    for dct in (by_band, by_dist):
        for k in dct:
            dct[k].sort()


class T(unittest.TestCase):
    def setUp(self):
        bb, bd = {}, {}
        for fin in range(1, 6):
            hist(bb, bd, 1600, "A1", fin, 104.0, 10)    # *A の 1 年= 10 本
            hist(bb, bd, 1600, "B1", fin, 106.0, 10)    # *B の 1 年= 10 本
            hist(bb, bd, 1600, "AB", fin, 105.5, 5)     # AB は 5 本だけ= b の段は足りない
            hist(bb, bd, 1400, "C1", fin, 92.0, 10)     # C1 の 1 年= b の段
            hist(bb, bd, 1300, "C2", fin, 86.0, 10)     # C2 の細かい帯= C は *C(c の段)で引かせる
            hist(bb, bd, 1800, "OP", fin, 115.0, 5)     # OP= 5 本・粗い段なし→ d の段
            hist(bb, bd, 1800, "C1", fin, 113.0, 5)     # 場×距離を 10 本に
        finish(bb, bd)
        self.bb, self.bd = bb, bd
        rows = []
        for rno, dist, band, base in ((1, 1600, "AB", 104.5), (2, 1400, "C1", 91.5), (3, 1300, "C3", 85.5),
                                      (4, 1800, "OP", 114.0)):
            for fin in range(1, 6):
                rows.append((dist, band, base + fin * 0.3, "重", rno, fin))
        self.rows = rows

    def med(self, key, sp):
        lo = (DAY - dt.timedelta(days=sp)).isoformat()
        v = [t for d_, t in self.bb[key] if lo <= d_ < DAY.isoformat()]
        return statistics.median(v)

    def test_pair_rq_and_d_stage(self):
        inf = {}
        c = baba.day_cell_going(self.rows, self.bb, self.bd, DAY, stages=baba.CLASSFIRST_STAGES,
                                none_band="drop", info=inf)
        pair = (self.med((1600, "*A", "良", 1), 365) + self.med((1600, "*B", "良", 1), 365)) / 2.0
        self.assertEqual(c["r"]["1"], round(pair, 1))                          # ①
        self.assertEqual(c["r"]["2"], round(self.med((1400, "C1", "良", 1), 365), 1))
        self.assertEqual(c["r"]["3"], round(self.med((1300, "*C", "良", 1), 365), 1))
        self.assertEqual(c["rq"], {"1": 1, "3": 1})                            # ② b の段(2R)は印なし
        self.assertNotIn("4", c["r"])                                          # ③ d の段は r に入れない
        self.assertIn(4, inf["race_d"])                                        # ③ d の計算には使う
        # ① 2〜5 着も両側平均の基準でレース差を作る
        diffs = []
        for dist, band, t, _g, rno, fin in self.rows:
            if rno == 1:
                p = (self.med((1600, "*A", "良", fin), 365) + self.med((1600, "*B", "良", fin), 365)) / 2.0
                diffs.append(t - p)
        self.assertAlmostEqual(inf["race_d"][1], statistics.median(diffs), places=6)
        self.assertEqual(inf["stage_d"][1], [2] * 5)                           # 段の番号= 使った c の段(365)

    def test_pair_falls_to_d_when_one_side_short(self):
        for fin in range(1, 6):
            self.bb[(1600, "*B", "良", fin)] = self.bb[(1600, "*B", "良", fin)][:3]
        c = baba.day_cell_going(self.rows, self.bb, self.bd, DAY, stages=baba.CLASSFIRST_STAGES, none_band="drop")
        self.assertNotIn("1", c["r"])
        self.assertNotIn("1", c.get("rq", {}))


if __name__ == "__main__":
    unittest.main()

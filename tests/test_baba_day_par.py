# -*- coding: utf-8 -*-
"""馬場差のセルの "r"(2026-11-04 開催日ページ「この日の時計」)= レースごとの 1 着の基準の秒。⛔通信ゼロ。

  py -3 -m unittest discover -s tests -p "test_baba_day_par.py"

確かめるのは 5 つ=
  ①r の値= d の計算の中で 1 着に使った基準(med_of)と同じ= 勝ち時計 − r が、内訳のレース差の材料と一致する
  ②r の値= 別に数え直した中央値(同じ場×距離×帯・良・1 着・[d-365, d))と一致する。帯の 1 年が足りなければ 3 年の段
  ③帯なしのレース(classfirst は外す)・基準の無いレースは r に入れない
  ④blend_proj(半々)・overlay_ai(南関)は r を動かさない
  ⑤baba_hist.merge_days は r を残す・確定済みの日(r なし)は据え置く
"""
import datetime as dt
import os
import random
import statistics
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud import baba  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import baba_hist  # noqa: E402

DAY = dt.date(2026, 9, 13)


def make(track="高知", seed=7):
    """本物の形の samples= (track, date, dist, band, time, going, race_no, finish)。
    過去 3 年ぶん: C1 1300 は毎週・C2 1400 は 2 年前〜1 年前だけ(1 年の段が足りず 3 年の段へ)・OP 1600 は 3 本だけ"""
    rnd = random.Random(seed)
    out = []
    for i in range(1, 1100, 3):
        day = (DAY - dt.timedelta(days=i)).isoformat()
        g = rnd.choice(["良", "良", "稍重", "重"])
        for fin in range(1, 6):
            out.append((track, day, 1300, "C1", round(82.0 + fin * 0.3 + rnd.uniform(-1, 1), 1), g, 1, fin))
            if 400 < i < 730:
                out.append((track, day, 1400, "C2", round(89.0 + fin * 0.3 + rnd.uniform(-1, 1), 1), g, 2, fin))
    for i in (30, 60, 90):
        day = (DAY - dt.timedelta(days=i)).isoformat()
        for fin in range(1, 6):
            out.append((track, day, 1600, "OP", 101.0 + fin * 0.3, "良", 3, fin))
    d = DAY.isoformat()
    for rno, dist, band, base in ((1, 1300, "C1", 81.0), (2, 1300, "C1", 81.2), (3, 1400, "C2", 88.1),
                                  (4, 1300, "C1", 81.5), (5, 1600, "OP", 100.0), (6, 1300, None, 81.0),
                                  (7, 1300, "C1", 80.9)):
        for fin in range(1, 6):
            out.append((track, d, dist, band, round(base + fin * 0.3, 1), "不良", rno, fin))
    return out


def recount(samples, dist, band, sp):
    lo, hi = (DAY - dt.timedelta(days=sp)).isoformat(), DAY.isoformat()
    v = [s[4] for s in samples if s[2] == dist and s[3] == band and s[5] == "良" and s[7] == 1 and lo <= s[1] < hi]
    return statistics.median(v) if len(v) >= baba.MIN_BAND else None


class T(unittest.TestCase):
    def build(self, samples, track="高知"):
        info = {}
        days, _, _ = baba.build_days(samples, {DAY.isoformat()}, "classfirst", today=DAY + dt.timedelta(days=1),
                                     info_of=info)
        return days[DAY.isoformat()][baba.TRACK2PREFIX[track]], info[(DAY.isoformat(), track)]

    def test_r_matches_inner_and_recount(self):
        s = make()
        c, _inf = self.build(s)
        r = c["r"]
        self.assertEqual(set(r), {"1", "2", "3", "4", "7"})           # ③ 6R= 帯なし(外す)・5R= OP の標本 3 本で基準なし
        self.assertNotIn("5", r)
        self.assertNotIn("6", r)
        self.assertEqual(r["1"], round(recount(s, 1300, "C1", 365), 1))   # ② 1 年の段
        self.assertIsNone(recount(s, 1400, "C2", 365))
        self.assertEqual(r["3"], round(recount(s, 1400, "C2", 1095), 1))  # ② 3 年の段
        # ① 内訳と同じ基準: day_cell_going を直接呼び、1 着の差 = 勝ち時計 − 基準 を確かめる
        rows = [(x[2], x[3], x[4], x[5], x[6], x[7]) for x in s if x[1] == DAY.isoformat()]
        bb, bd = {}, {}
        for track, date, dist, band, t, g, _rno, fin in sorted(s, key=lambda z: z[1]):
            bd.setdefault((dist, g, fin), []).append((date, t))
            if band:
                bb.setdefault((dist, band, g, fin), []).append((date, t))
                if baba.coarse_key(band):
                    bb.setdefault((dist, baba.coarse_key(band), g, fin), []).append((date, t))
        out = baba.day_cell_going(rows, bb, bd, DAY, stages=baba.CLASSFIRST_STAGES, none_band="drop")
        self.assertEqual(out["r"], r)
        self.assertEqual(out["d"], c["d"])

    def test_blend_and_overlay_keep_r(self):
        s = make()
        c, _ = self.build(s)
        r0 = dict(c["r"])
        days = {DAY.isoformat(): {"kochi": c}}
        baba.blend_proj(days, {}, {(DAY.isoformat(), "高知"): -0.5}, rebuild_all=True, samples=s)
        self.assertEqual(days[DAY.isoformat()]["kochi"]["r"], r0)
        s2 = make("大井")
        c2, _ = self.build(s2, "大井")
        r2 = dict(c2["r"])
        days2 = {DAY.isoformat(): {"ooi": c2}}
        baba.overlay_ai(days2, s2, {DAY.isoformat(): {"ooi": -0.4}})
        self.assertEqual(days2[DAY.isoformat()]["ooi"]["s"], "ai")
        self.assertEqual(days2[DAY.isoformat()]["ooi"]["r"], r2)

    def test_hist_keeps_r_and_frozen(self):
        s = make()
        old = {"2026-09-06": {"d": 1.1, "k": "良"}}
        days, rebuilt = baba_hist.merge_days("kochi", s, {DAY.isoformat(), "2026-09-06"}, old,
                                             DAY + dt.timedelta(days=1), False, "classfirst")
        self.assertEqual(days["2026-09-06"], {"d": 1.1, "k": "良"})
        self.assertIn("r", days[DAY.isoformat()])
        self.assertEqual(rebuilt, 1)


if __name__ == "__main__":
    unittest.main()

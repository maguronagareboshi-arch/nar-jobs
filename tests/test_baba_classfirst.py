# -*- coding: utf-8 -*-
"""馬場差 classfirst(クラス優先の 5 段・研究用 2026-10-25)の検算。⛔通信ゼロ。

  py -3 -m unittest discover -s tests -p "test_baba_classfirst.py"

確かめるのは 4 つ=
  ①退避の順= 細かい帯(1年)→細かい帯(3年)→字だけの帯(1年)→字だけの帯(3年)→場×距離(1年)
  ②帯なしの走= classfirst の既定は外す・"dist" なら場×距離へ・going の既定は今まで通り場×距離へ
  ③going 版の値は 1 件も変わらない(書き換え前の関数の写しと乱数の材料で突き合わせ)
  ④読む期間= going は今まで通り 395 日・classfirst だけ 3 年ぶん
"""
import datetime as dt
import os
import random
import statistics
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud import baba  # noqa: E402

TR, PF = "大井", "ooi"
D = dt.date(2026, 9, 1)
DAY = D.isoformat()


def _old_day_cell_going(day_rows, by_band_g, by_dist_g, d):
    """書き換え前(2026-10-25 時点の origin/master)の day_cell_going の写し。③の物差し"""
    ranges = baba.baseline_ranges(d, "going")
    cache = {}

    def med_of(dist, band, going, fin):
        cb = baba.coarse_key(band)
        for k, src, kk in ((("b", dist, band, going, fin), by_band_g, (dist, band, going, fin)),
                           (("c", dist, cb, going, fin), by_band_g, (dist, cb, going, fin)),
                           (("d", dist, going, fin), by_dist_g, (dist, going, fin))):
            if k[0] != "d" and not k[2]:
                continue
            m = cache.get(k, "?")
            if m == "?":
                v = baba._vals_in(src.get(kk, []), ranges)
                m = statistics.median(v) if len(v) >= baba.MIN_BAND else None
                cache[k] = m
            if m is not None:
                return m
        return None

    per_d, per_g = {}, {}
    for dist, band, t, going, rno, fin in day_rows:
        if not fin or fin > baba.TOP_N:
            continue
        m = med_of(dist, band, baba.GOING_BASE, fin)
        if m is not None:
            per_d.setdefault(rno, []).append(t - m)
        if going:
            m = med_of(dist, band, going, fin)
            if m is not None:
                per_g.setdefault(rno, []).append(t - m)
    dv = [statistics.median(v) for _, v in sorted(per_d.items(), key=lambda kv: str(kv[0]))
          if len(v) >= baba.MIN_HORSES]
    gv = [statistics.median(v) for _, v in sorted(per_g.items(), key=lambda kv: str(kv[0]))
          if len(v) >= baba.MIN_HORSES]
    out = {}
    if len(dv) >= baba.MIN_RACES:
        out["d"], out["n"], out["devs"] = round(statistics.median(dv), 1), len(dv), dv
    if len(gv) >= baba.MIN_RACES:
        out["g"], out["ng"] = round(statistics.median(gv), 1), len(gv)
    return out


def index(samples):
    """build_days と同じ索引(1 場ぶん)"""
    bb, bd = {}, {}
    for _tr, date, dist, band, t, g, _r, fin in sorted(samples, key=lambda s: s[1]):
        if not g or not fin or fin > baba.TOP_N:
            continue
        bd.setdefault((dist, g, fin), []).append((date, t))
        if band:
            bb.setdefault((dist, band, g, fin), []).append((date, t))
            if baba.coarse_key(band):
                bb.setdefault((dist, baba.coarse_key(band), g, fin), []).append((date, t))
    return bb, bd


def hist(band, days_ago, base, n=8):
    """band の時計を days_ago 日前から n 日ぶん(各日 1R・1〜5着= base+0.2f・良・1200m)"""
    out = []
    for k in range(n):
        d = (D - dt.timedelta(days=days_ago + k)).isoformat()
        for f in range(1, 6):
            out.append((TR, d, 1200, band, base + 0.2 * f, "良", 1, f))
    return out


def day(band="C1", add=0.0):
    return [(1200, band, 70 + 0.2 * f + add, "良", r, f) for r in range(1, 5) for f in range(1, 6)]


def run(samples, rows, stages, none_band="dist"):
    bb, bd = index(samples)
    info = {}
    c = baba.day_cell_going(rows, bb, bd, D, stages=stages, none_band=none_band, info=info)
    return c, info


CF = baba.CLASSFIRST_STAGES


class ClassFirstTest(unittest.TestCase):
    def test_stage_order(self):
        # 細かい帯 1年(差 +1)・細かい帯 3年だけ(差 +2)・字だけ 1年(+3)・字だけ 3年(+4)・場×距離(+5)
        c1_1y = hist("C1", 30, 69.0)
        c1_3y = hist("C1", 800, 68.0)
        c2_1y = hist("C2", 30, 67.0)          # 字だけの帯 *C に入る(C1 の段には入らない)
        c2_3y = hist("C2", 800, 66.0)
        dist1y = hist("AB", 30, 65.0)         # AB は字だけの帯なし= 場×距離にだけ入る
        cases = [
            (c1_1y + c1_3y + c2_1y + c2_3y + dist1y, 0, 1.0),
            (c1_3y + c2_1y + c2_3y + dist1y, 1, 2.0),
            (c2_1y + c2_3y + dist1y, 2, 3.0),
            (c2_3y + dist1y, 3, 4.0),
            (dist1y, 4, 5.0),
        ]
        for smp, st, want in cases:
            c, info = run(smp, day(), CF)
            self.assertEqual(c["d"], want, st)
            self.assertEqual(info["reach_d"][st], 20, st)
            self.assertEqual(set(x for v in info["stage_d"].values() for x in v), {st})
        # 字だけ 1年は C1 の 3 年より後= C1 3年と *C 1年が両方あれば C1 3年
        c, _ = run(c1_3y + c2_1y, day(), CF)
        self.assertEqual(c["d"], 2.0)
        # going(今の本番)は C1 3年を見ずに字だけ 1年へ
        c, info = run(c1_3y + c2_1y + dist1y, day(), baba.GOING_STAGES)
        self.assertEqual(c["d"], 3.0)
        # 基準が無い時計は最後の要素
        c, info = run([], day(), CF)
        self.assertEqual(c, {})
        self.assertEqual(info["reach_d"][-1], 20)

    def test_no_band_drop_or_dist(self):
        smp = hist("C1", 30, 69.0) + hist(None, 30, 65.0)
        rows = day("C1") + [(1200, None, 70 + 0.2 * f, "良", r, f) for r in range(5, 9) for f in range(1, 6)]
        c, info = run(smp, rows, CF, none_band="drop")
        self.assertEqual((c["d"], c["n"]), (1.0, 4))
        self.assertEqual(info["drop"], 20)
        c, info = run(smp, rows, CF, none_band="dist")
        self.assertEqual(c["n"], 8)
        self.assertEqual(info["drop"], 0)
        self.assertEqual(info["reach_d"][4], 20)        # 帯なしは場×距離(1年)
        # build_days= classfirst の既定は外す・going の既定は場×距離へ
        full = smp + [(TR, DAY) + r for r in rows]
        today = D + dt.timedelta(days=1)
        cf, _, _ = baba.build_days(full, {DAY}, "classfirst", today=today)
        gd, _, _ = baba.build_days(full, {DAY}, "going", today=today)
        gx, _, _ = baba.build_days(full, {DAY}, "going", today=today, none_band="drop")
        cd, _, _ = baba.build_days(full, {DAY}, "classfirst", today=today, none_band="dist")
        self.assertEqual(cf[DAY][PF]["n"], 4)
        self.assertEqual(gd[DAY][PF]["n"], 8)
        self.assertEqual(gx[DAY][PF]["n"], 4)
        self.assertEqual(cd[DAY][PF]["n"], 8)
        # 帯なしだけの日は classfirst で値が出ない
        only_none = smp + [(TR, DAY) + r for r in rows if r[1] is None]
        cf2, _, _ = baba.build_days(only_none, {DAY}, "classfirst", today=today)
        self.assertNotIn(DAY, cf2)

    def test_going_unchanged_random(self):
        rnd = random.Random(20261025)
        bands = ["C1", "C2", "C3", "B1", "B2", "A1", "C", "AB", "OP", "OPy", "2y", "3y", None]
        goings = ["良", "稍重", "重", "不良", ""]
        dists = [1200, 1400, 1600]
        smp = []
        start = D - dt.timedelta(days=700)
        for k in range(0, 760, 2):
            d = (start + dt.timedelta(days=k)).isoformat()
            g = rnd.choice(goings)
            for r in range(1, 9):
                b, di = rnd.choice(bands), rnd.choice(dists)
                for f in range(1, 7):
                    if rnd.random() < 0.1:
                        continue
                    smp.append((TR, d, di, b, 60 + di / 100 + 0.2 * f + rnd.gauss(0, 1), g, r, f))
        bb, bd = index(smp)
        n_cmp = 0
        dates = sorted({s[1] for s in smp if s[1] >= (D - dt.timedelta(days=200)).isoformat()})
        for d in dates:
            rows = [s[2:] for s in smp if s[1] == d]
            dd = dt.date.fromisoformat(d)
            old = _old_day_cell_going(rows, bb, bd, dd)
            new = baba.day_cell_going(rows, bb, bd, dd)
            new2 = baba.day_cell_going(rows, bb, bd, dd, stages=baba.GOING_STAGES, none_band="dist", info={})
            # d1/g1(10/26 距離の直し)は足しただけ= それ以外は書き換え前と同じ
            new = {k: v for k, v in new.items() if k not in ("d1", "g1")}
            new2 = {k: v for k, v in new2.items() if k not in ("d1", "g1")}
            self.assertEqual(old, new, d)
            self.assertEqual(old, new2, d)
            n_cmp += 1 if old else 0
        self.assertGreater(n_cmp, 50)
        # build_days(going) も書き換え前の関数で組んだ値と同じ
        targets = set(dates)
        days, _, _ = baba.build_days(smp, targets, "going", today=D + dt.timedelta(days=30), rebuild_all=True)
        for d in dates:
            old = _old_day_cell_going([s[2:] for s in smp if s[1] == d], bb, bd, dt.date.fromisoformat(d))
            got = days.get(d, {}).get(PF) or {}
            self.assertEqual({k: got[k] for k in ("d", "g", "n", "ng") if k in got},
                             {k: old[k] for k in ("d", "g", "n", "ng") if k in old}, d)

    def test_fetch_days(self):
        self.assertEqual(baba.fetch_days("going"), 395)
        self.assertEqual(baba.fetch_days("classfirst"), 1125)
        self.assertEqual(baba.fetch_days("365"), 395)
        self.assertEqual(baba.fetch_days("1095"), 1125)
        self.assertIn("classfirst", baba.BASELINES)


if __name__ == "__main__":
    unittest.main()

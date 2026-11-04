# -*- coding: utf-8 -*-
"""馬場差のセルの "rg"(組の差)と FRONT_KEY(前半)= 2026-11-04 開催日ページ「この日の時計」。⛔通信ゼロ。

  py -3 -m unittest discover -s tests -p "test_baba_grp_front.py"

確かめるのは=
  ①group_box の級と箱(組 1〜7 はそのまま・8 以上は 4 つずつ・選抜/選定・重賞と混ざった級は外す・全場の書き方)
  ②group_table が作り物の「箱の差+日の速さ」を取り戻し、級の中で重み付き平均 0 になる
  ③front_value の式・≤800m/欠けは None・race_rows_of が最初のコーナーの 1 番手(6 着以下も)を使う
  ④add_grp_front= 15 R 未満の箱・0.0 は入れない・据え置きのセルは触らない・d/r は変えない・前半は 1 年の中央値との差
  ⑤baba_hist.KEEP が rg・pc を残す
"""
import datetime as dt
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud import baba  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import baba_hist  # noqa: E402

FK = baba.FRONT_KEY


class GroupBox(unittest.TestCase):
    def test_boxes(self):
        g = baba.group_box
        self.assertEqual(g("C3-1"), ("C3", "1"))
        self.assertEqual(g("Ｃ３－５"), ("C3", "5"))       # 全角も読む(サイトの raceClassParts と同じ)
        self.assertEqual(g("C3-11"), ("C3", "8-11"))
        self.assertEqual(g("C3-19"), ("C3", "16-19"))
        self.assertEqual(g("C3-24"), ("C3", "20+"))
        self.assertEqual(g("C2-3"), ("C2", "3"))
        self.assertEqual(g("C2-9"), ("C2", "8-11"))
        self.assertEqual(g("3歳-2"), ("3歳", "2"))
        self.assertEqual(g("C2選抜馬"), ("C2", "選抜"))
        self.assertEqual(g("C1記者選抜"), ("C1", "記者選抜" if baba.KISHA_SEPARATE else "選抜"))
        self.assertEqual(g("A選定馬"), ("A", "選抜"))
        self.assertIsNone(g("C3-1", "重賞"))
        self.assertIsNone(g("一般"))

    def test_all_tracks(self):
        g = baba.group_box
        self.assertEqual(g("C2八 九", None, "大井"), ("C2", "8-11"))           # 南関= 漢数字・並びは先頭
        self.assertEqual(g("日刊スポーツ賞B3四選抜特別", None, "大井"), ("B3", "選抜"))
        self.assertEqual(g("C1四組", None, "盛岡"), ("C1", "4"))               # 岩手
        self.assertEqual(g("3歳C2五組", None, "水沢"), ("3歳C2", "5"))         # 3歳限定は分ける
        self.assertEqual(g("C1十二", None, "金沢"), ("C1", "12-15"))
        self.assertEqual(g("ベガ賞C2一3歳以上", None, "園田"), ("C2", "1"))
        self.assertEqual(g("乳岩疾風戦C14", None, "名古屋"), ("C", "12-15"))   # 名古屋・笠松= 字の後ろの数字が組
        self.assertEqual(g("C11組", None, "笠松"), ("C", "8-11"))
        self.assertEqual(g("グランシャリオドリーム79C4-2", None, "門別"), ("C4", "2"))
        self.assertEqual(g("C2-25組", None, "佐賀"), ("C2", "20+"))
        for n, t in (("特別C1七C2一", "浦和"), ("賞A2B1選定馬", "川崎"), ("特別C3-2C4-1", "門別"),
                     ("C1 3歳以上", "園田"), ("2歳新馬", "佐賀")):
            self.assertIsNone(g(n, None, t), n)                                 # 混ざった級・組なし・新馬


def synth(track="高知", seed=3, n_days=400, start=dt.date(2023, 10, 1)):
    """作り物: 1 日 8R・C3 の箱(2: −0.5・20+: +0.6・8-11: 0)と C2 の箱(2: −0.3・6: +0.3)・日の速さ ±1"""
    rnd = random.Random(seed)
    eff = {("C3", 2): -0.5, ("C3", 22): 0.6, ("C3", 9): 0.0, ("C2", 2): -0.3, ("C2", 6): 0.3}
    best, meta = {}, {}
    for i in range(n_days):
        d = (start + dt.timedelta(days=i * 2)).isoformat()
        sp = rnd.uniform(-1, 1)
        for rno, (cls, n) in enumerate(list(eff) + [("C3", 9), ("C3", 2), ("C2", 6)], start=1):
            dist = 1300 if (rno + i) % 2 else 1400
            base = 82.0 if dist == 1300 else 89.0
            t = base + (0.8 if cls == "C3" else 0.0) + sp + eff[(cls, n)] + rnd.uniform(-0.05, 0.05)
            best[(track, d, rno, 1)] = {"time_sec": round(t, 2)}
            meta[(track, d, rno)] = {"distance_m": dist, "race_name": f"{cls}-{n}", "race_kind": None}
    return best, meta


class GroupTable(unittest.TestCase):
    def test_recovers_and_centers(self):
        best, meta = synth()
        rows = baba.race_rows_of(best, meta, [])
        gr = [(d, dist, c, b, t) for _tr, d, _r, dist, c, b, t, _f in rows if b]
        tb = baba.group_table(gr, "2023-01-01", "2026-01-01")
        # C3: 箱の数= 2 は 2 本/日・4..: 作り物の差 −0.5/+0.6/0 を級の重み付き平均で中心化したもの
        c3 = {k: v for k, v in tb.items() if k[0] == "C3"}
        w = {("C3", "2"): 2, ("C3", "20+"): 1, ("C3", "8-11"): 2}
        raw = {("C3", "2"): -0.5, ("C3", "20+"): 0.6, ("C3", "8-11"): 0.0}
        mean = sum(raw[k] * w[k] for k in w) / sum(w.values())
        for k in w:
            self.assertAlmostEqual(c3[k][0], raw[k] - mean, delta=0.05, msg=k)
        for cls in ("C3", "C2"):
            xs = [(v, n) for k, (v, n) in tb.items() if k[0] == cls]
            self.assertAlmostEqual(sum(v * n for v, n in xs) / sum(n for _, n in xs), 0.0, places=6)
        self.assertEqual(tb[("C2", "6")][1], 800)


class Front(unittest.TestCase):
    def test_formula(self):
        # 1400m・走破 90.0・上がり 38.4 → (51.6 / 800 × 200) − 12.8 = 12.9 − 12.8 = 0.1
        self.assertAlmostEqual(baba.front_value(1400, 90.0, 38.4), 0.1, places=9)
        self.assertIsNone(baba.front_value(800, 50.0, 37.0))
        self.assertIsNone(baba.front_value(1400, 90.0, None))

    def test_lead_from_first_corner(self):
        best = {("高知", "2026-10-01", 1, 1): {"time_sec": 90.0}}
        meta = {("高知", "2026-10-01", 1): {"distance_m": 1400, "race_name": "C3-1",
                                             "corners": [{"order": "7,3,(1,5)"}]}}
        runs = [{"track": "高知", "race_date": "2026-10-01", "race_no": 1, "runner_number": 7,
                 "finish": 9, "time_sec": 91.0, "last3f": 40.0}]
        rows = baba.race_rows_of(best, meta, runs)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][7], (91.0 - 40.0) / 800 * 200 - 40.0 / 3, places=9)
        meta[("高知", "2026-10-01", 1)]["corners"] = [{"order": "(7,3),1"}]   # 1 番手が 2 頭= 先頭が分からない
        self.assertIsNone(baba.race_rows_of(best, meta, runs)[0][7])


class AddCells(unittest.TestCase):
    def test_add(self):
        best, meta = synth(n_days=200)
        rows = baba.race_rows_of(best, meta, [])
        day = max(r[1] for r in rows)
        # 前半: その日の 1R だけ前半を付け、1 年の中にも同じ距離の前半を 10 本(値 0.3)
        rows = [r[:7] + ((0.8 if (r[1] == day and r[2] == 1) else None),) for r in rows]
        d0 = dt.date.fromisoformat(day)
        dist1 = next(r[3] for r in rows if r[1] == day and r[2] == 1)
        for i in range(10):
            rows.append(("高知", (d0 - dt.timedelta(days=10 + i)).isoformat(), 99, dist1, None, None, None, 0.3))
        rows.append(("高知", (d0 - dt.timedelta(days=400)).isoformat(), 99, dist1, None, None, None, 9.0))  # 1 年より前= 使わない
        nxt = (d0 + dt.timedelta(days=40)).replace(day=1).isoformat()
        rows = [r if r[1] != day else r for r in rows]
        frozen_cell = {"d": 0.1, "r": {"1": 80.0}}
        days = {day: {"kochi": {"d": -0.2, "n": 8, "r": {"1": 82.5}}},
                "2020-01-01": {"kochi": frozen_cell}}
        frozen = {"2020-01-01": {"kochi": frozen_cell}}
        baba.add_grp_front(days, frozen, rows)
        c = days[day]["kochi"]
        self.assertEqual(c["d"], -0.2)
        self.assertEqual(c["r"], {"1": 82.5})
        self.assertEqual(c[FK], {"1": 0.5})
        self.assertNotIn("rg", frozen_cell)
        # 1R= C3-2(2 の箱)・その月の 1 日より前 3 年の表と一致
        ms = d0.replace(day=1)
        gr = [(d, dist, cl, b, t) for _tr, d, _r, dist, cl, b, t, _f in rows if b and t is not None]
        tb = baba.group_table(gr, (ms - dt.timedelta(days=1095)).isoformat(), ms.isoformat())
        self.assertEqual(c["rg"]["1"], round(tb[("C3", "2")][0], 1))
        self.assertTrue(all(v != 0 for v in c["rg"].values()))
        self.assertIsNotNone(nxt)

    def test_min_races(self):
        rows = [("高知", f"2026-0{1 + i // 10}-{1 + i % 10:02d}", 1, 1300, "C1", "2", 80.0 + i * 0.01, None)
                for i in range(14)]
        rows.append(("高知", "2026-09-01", 1, 1300, "C1", "2", 80.0, None))
        days = {"2026-09-01": {"kochi": {"d": 0.0, "n": 4}}}
        baba.add_grp_front(days, {}, rows)
        self.assertNotIn("rg", days["2026-09-01"]["kochi"])


class Hist(unittest.TestCase):
    def test_keep(self):
        self.assertIn("rg", baba_hist.KEEP)
        self.assertIn(FK, baba_hist.KEEP)


if __name__ == "__main__":
    unittest.main()

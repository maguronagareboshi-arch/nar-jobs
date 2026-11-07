# -*- coding: utf-8 -*-
"""2026-11-07 走破指数を全場へ(cloud/si_all.py)。行は REST の nar_runs / nar_races の列名・型そのまま。"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))
import si_all as S  # noqa: E402


def run_row(track, date, rno, num, name, fin, t, w=56.0, note=None, birth="2020-04-01"):
    return {"track": track, "race_date": date, "race_no": rno, "runner_number": num, "horse_name": name,
            "birth_date": birth, "finish": fin, "finish_note": note, "time_sec": t, "carried_weight": w, "si5": None}


def race_row(track, date, rno, dist, name, going="良", kind=None, surface="ダ"):
    return {"track": track, "race_date": date, "race_no": rno, "distance_m": dist, "race_name": name,
            "going": going, "race_kind": kind, "surface": surface}


def synth(years=(2021, 2022, 2023, 2024), track="高知"):
    """1 日 4 R(C1 1300m・C3 1300m・C1 1400m・C3 1400m)を月 1 日。時計= 64.0 s/1000m(C1)・C3 は +0.5・着順ごと +0.2 秒"""
    runs, races = [], []
    for y in years:
        for mth in range(1, 13):
            d = f"{y}-{mth:02d}-10"
            for rno, (dist, cls) in enumerate([(1300, "C1"), (1300, "C3"), (1400, "C1"), (1400, "C3")], 1):
                races.append(race_row(track, d, rno, dist, f"{cls}-1"))
                base = (64.0 + (0.5 if cls == "C3" else 0.0)) * dist / 1000
                for fin in range(1, 7):
                    runs.append(run_row(track, d, rno, fin, f"馬{rno}{fin}", fin, round(base + 0.2 * (fin - 1), 1)))
    return runs, races


class FrameTest(unittest.TestCase):
    def test_runs_frame_drops_cancel_and_keys(self):
        rows = [run_row("高知", "2024-05-01", 3, 1, "アイ", 1, 80.1),
                run_row("高知", "2024-05-01", 3, 2, "カキ", None, None, note="取消"),
                run_row("高知", "2024-05-01", 3, 3, "サシ", None, None, note="中止"),
                run_row("帯広ば", "2024-05-01", 1, 1, "ばん", 1, 120.0)]
        U = S.runs_frame(rows)
        self.assertEqual(list(U.runner_number), [1, 3])            # 取消と帯広ばは落ちる・中止は残る(指数は出ない)
        self.assertEqual(U.hk.iloc[0], "アイ|2020-04-01")

    def test_races_frame_band_course_gmode(self):
        R = S.races_frame([race_row("名古屋", "2024-05-01", 1, 1400, "Ｃ１５組", going="稍重"),
                           race_row("名古屋", "2024-05-01", 2, 1400, "Ｃ１６組", going="良"),
                           race_row("名古屋", "2024-05-01", 3, 1500, "Ｃ１７組", going="良")])
        self.assertEqual(list(R.k0), ["C", "C", "C"])               # 東海は字だけ(baba.band_of)
        self.assertEqual(R.course.iloc[0], "名古屋_1400_ダ")
        self.assertEqual(R.gmode.iloc[0], "良")

    def test_kmap_pool(self):
        S.MIN_R = 30
        m = S.kmap_make({"C1": 40, "C2": 20, "C3": 15, "OP": 5})
        self.assertEqual(m, {"C1": "C1", "C2": "C*", "C3": "C*", "OP": None})


class FormulaTest(unittest.TestCase):
    def test_si_hand_and_cut(self):
        U = S.runs_frame([run_row("高知", "2024-05-01", 1, 1, "ア", 1, 84.0, w=56.0),
                          run_row("高知", "2024-05-01", 1, 2, "イ", 2, 84.5, w=54.0),
                          run_row("高知", "2024-05-01", 1, 3, "ウ", 9, 95.0, w=55.0)])
        R = pd.DataFrame({"track": ["高知"], "race_date": ["2024-05-01"], "race_no": [1], "distance_m": [1300.0],
                          "k0": ["C1"], "year": [2024], "bc": [64.5], "D_t4": [0.3], "Draw": [0.3], "n": [8.0],
                          "dtk": ["2024-05-01_高知"]})
        X = S.si_table(U, R, {("2024-05-01", "高知"): -0.2})
        B = 64.5 * 1.3
        self.assertAlmostEqual(X.SI[0], 80 + 1000 / B * (B - 84.0 - 0.2 * 1.3) + 2 * 1, 6)
        self.assertAlmostEqual(X.SI_t4[1], 80 + 1000 / B * (B - 84.5 + 0.3 * 1.3) - 2, 6)
        self.assertAlmostEqual(X.Tt[2], 84.0 + 2.6, 6)               # 大負けは勝ち時計 + 1000m あたり 2 秒で打ち切り
        x = S.out_frame(X)
        self.assertEqual(list(x.columns), ["track", "race_date", "race_no", "runner_number", "horse_key", "si5"])

    def test_why_and_out_frame_skips_nankan(self):
        U = S.runs_frame([run_row("高知", "2024-05-01", 1, 1, "ア", 1, None, note="中止"),
                          run_row("大井", "2024-05-01", 1, 1, "イ", 1, 80.0)])
        R = pd.DataFrame({"track": ["高知", "大井"], "race_date": ["2024-05-01"] * 2, "race_no": [1, 1],
                          "distance_m": [1300.0, 1200.0], "k0": ["C1", "C1"], "year": [2024, 2024],
                          "bc": [64.5, np.nan], "D_t4": [0.0, 0.0], "Draw": [0, 0], "n": [5, 5], "dtk": ["a", "b"]})
        X = S.si_table(U, R, {("2024-05-01", "大井"): 0.0})
        self.assertEqual(list(X.why), ["no_time", "no_base"])
        self.assertEqual(len(S.out_frame(X)), 0)
        with self.assertRaises(AssertionError):
            S.push(pd.DataFrame({"track": ["大井"]}))


class BaseTest(unittest.TestCase):
    def test_build_base_recovers_course_and_class(self):
        S.MIN_R = 30
        runs, races = synth()
        U, R = S.runs_frame(runs), S.races_frame(races)
        R = S.race_values(U, R)
        R = S.build_base(R, [["高知"]], [2024])
        y = R[R.year == 2024]
        # 1〜3 着の平均= 1 着 + 0.2 秒 → 1000m あたり 64.0 + 0.2/距離。基準 + 日の差 = C1 の値
        # (毎日が同じ作り物では b と D の定数の分け方が決まらない= t4_base と同じ。指数に効くのは b + D だけ)
        c1 = y[(y.k0 == "C1") & (y.distance_m == 1300)]
        self.assertTrue(np.allclose(c1.bc + c1.D_t4, 64.0 + 0.2 / 1.3, atol=0.01))
        self.assertAlmostEqual(y[y.k0 == "C3"].dl.iloc[0], 0.5, 1)   # C3 は C1 より 1000m あたり 0.5 秒遅い
        self.assertLess(float(np.ptp(y.D_t4)), 0.01)                 # どの日も同じ速さ

    def test_baba_inputs_shape(self):
        runs, races = synth(years=(2024,))
        U, R = S.runs_frame(runs), S.races_frame(races)
        samples, pr = S.baba_inputs(U, R)
        self.assertEqual(samples[0], ("高知", "2024-01-10", 1300, "C1", 83.2, "良", 1, 1))
        self.assertEqual(pr[0], ("高知", "2024-01-10", 1, "馬11|2020-04-01", 1300, "ダ", 1, 83.2))
        self.assertTrue(all(s[7] <= 5 for s in samples))             # baba は 1〜5 着

    def test_compute_end_to_end(self):
        S.MIN_R = 30
        runs, races = synth()
        X, cf, pv = S.compute(runs, races, "2024-01-01", "2024-12-31")
        self.assertTrue((X.race_date >= "2024-01-01").all())
        self.assertGreater(len(cf), 0)                               # baba.build_days(classfirst)の日の値が出る
        ok = X[np.isfinite(X.SI)]
        self.assertGreater(len(ok), 0)
        self.assertTrue(ok.why.eq("").all())
        x = S.out_frame(X)
        self.assertEqual(set(x.track), {"高知"})


if __name__ == "__main__":
    unittest.main()

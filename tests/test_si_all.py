# -*- coding: utf-8 -*-
"""2026-11-07 走破指数を全場へ(cloud/si_all.py)。行は REST の nar_runs / nar_races の列名・型そのまま。"""
import os
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


class OsTest(unittest.TestCase):
    """o_s(場の間の物差し)= 南関は本番の si5 で 0 に固定・100 組未満の線は使わない・前の年の組だけ"""
    def frame(self):
        rows = []
        def add(h, d, t, v):
            rows.append({"hk": h, "race_date": d, "race_no": 1, "track": t, "year": int(d[:4]),
                         "si5": v if t in S.NANKAN else np.nan, "SI": np.nan if t in S.NANKAN else v})
        for i in range(300):                               # 大井→高知→大井(高知の値は 5 高い= 物差しが甘い)
            v = 50 + i % 30
            add(f"a{i}|", "2023-03-01", "大井", v); add(f"a{i}|", "2023-04-01", "高知", v + 5)
            add(f"a{i}|", "2023-05-01", "大井", v)
        for i in range(400):                               # 同じ場の組(当てはめの a・b 用)
            v = 45 + i % 40
            add(f"s{i}|", "2023-06-01", "大井", v); add(f"s{i}|", "2023-07-01", "大井", v)
        for i in range(50):                                # 佐賀とは 50 組だけ= 使わない
            v = 60 + i % 10
            add(f"g{i}|", "2023-03-01", "大井", v); add(f"g{i}|", "2023-04-01", "佐賀", v - 8)
            add(f"g{i}|", "2023-05-01", "大井", v)
        return pd.DataFrame(rows)

    def test_o_table(self):
        X = self.frame()
        X["hk"] = X.hk.str.replace("|", "|x", regex=False)
        O, info = S.o_table(X, [2023, 2024])
        self.assertTrue(all(v == 0.0 for v in O[2023].values()))          # 2023 の組は 2023 に使わない(未来を入れない)
        self.assertAlmostEqual(O[2024]["高知"], -5.0, 6)
        self.assertEqual(O[2024]["大井"], 0.0)                               # 南関は動かさない
        self.assertEqual(O[2024]["佐賀"], 0.0)
        self.assertIn("佐賀", info[2024]["alone"])
        self.assertNotIn("高知", info[2024]["alone"])
        Y = S.apply_o(X.assign(year=2024), O)
        k = Y[Y.track == "高知"]
        self.assertTrue(np.allclose(k.F, k.SI - 5))
        n = Y[Y.track == "大井"]
        self.assertTrue(np.allclose(n.F, n.si5))


    def test_years_summary_md(self):
        S.MIN_R = 30
        runs, races = synth(years=(2021, 2022, 2023, 2024, 2025))
        X, sec = S.compute_years(pd.DataFrame(runs), pd.DataFrame(races), "2024-01-01", "2025-12-31")
        self.assertEqual(sorted(sec), [2024, 2025])
        O, info = S.o_table(X, [2024, 2025])
        self.assertEqual(info[2025]["alone"], S.TARGETS)                    # 南関とつながらない= 0 のまま
        X = S.apply_o(X, O)
        res = S.summarize(X, O, info, {}, sec, "2024-01-01", "2025-12-31", 1)
        md = S.to_md2(res)
        self.assertIn("| 高知 |", md)
        __import__("json").dumps(res, ensure_ascii=False)


class Check3Test(unittest.TestCase):
    def test_young_pairs_and_resid(self):
        X = OsTest.frame(None)
        X["hk"] = X.hk.str.replace("|", "|x", regex=False)
        X["age"] = [2 if h.startswith("a") and int(h[1:].split("|")[0]) < 150 else 5 for h in X.hk]
        X["k0"] = "C1"
        O1, _ = S.o_table(X, [2024])
        O2, i2 = S.o_table(X, [2024], young=False)                          # 若馬の組を外すと高知は 150 頭= 100 組以上のまま
        self.assertAlmostEqual(O1[2024]["高知"], -5.0, 6)
        self.assertAlmostEqual(O2[2024]["高知"], -5.0, 6)
        O3, i3 = S.o_table(X.assign(age=2), [2024], young=False)            # 全部若馬= 組が無い→ 0
        self.assertEqual(O3[2024]["高知"], 0.0)
        Y = S.apply_o(X.assign(year=2024, race_date=X.race_date.str.replace("2023", "2024")), O1)
        r = S.resid_check(Y, "F")
        self.assertAlmostEqual(r["高知"]["all"]["in"][0], 0.0, 6)          # 足した後は残りのずれ 0
        self.assertEqual(r["高知"]["all"]["in"][1], 300)
        self.assertEqual(r["高知"]["young"]["in"][1], 150)
        r0 = S.resid_check(Y, "F0")
        self.assertAlmostEqual(r0["高知"]["all"]["in"][0], 5.0, 6)          # 足す前は高知に入ると +5
        self.assertAlmostEqual(r0["高知"]["all"]["out"][0], -5.0, 6)
        ct = S.class_table(Y, "F", min_n=1)
        self.assertIn("C1", ct["高知"])
        S.to_md3  # noqa: B018


    def test_summarize3_md(self):
        S.MIN_R = 30
        runs, races = synth(years=(2021, 2022, 2023, 2024, 2025))
        X, sec = S.compute_years(pd.DataFrame(runs), pd.DataFrame(races), "2024-01-01", "2025-12-31")
        res = S.summarize3(X, sec, "2025-12-31", 0)
        md = S.to_md3(res)
        self.assertIn("級ごとの指数", md)
        self.assertIn("C1", res["class"]["高知"])
        __import__("json").dumps(res, ensure_ascii=False)


class WriteTest(unittest.TestCase):
    """2026-11-07 書く口: 1,000 行ずつ・3 回まで引き直して止まる・南関と帯広ばは弾く・o_s=0・月ごとに順に"""
    def setUp(self):
        self.saved = S.baba.req, S.load_frames, S.time.sleep
        S.time.sleep = lambda *_: None

    def tearDown(self):
        S.baba.req, S.load_frames, S.time.sleep = self.saved

    def frame(self, n, track="高知"):
        return pd.DataFrame({"track": [track] * n, "race_date": ["2024-05-01"] * n, "race_no": [1] * n,
                             "runner_number": list(range(1, n + 1)), "horse_key": ["ア|2020-04-01"] * n,
                             "si5": [61.2] * n})

    def test_push_chunks_and_retry(self):
        calls = []

        def req(base, key, path, method="GET", body=None):
            calls.append((path, len(__import__("json").loads(body))))
            if len(calls) == 2:
                raise OSError("接続切れ")                                    # 2 回目の POST だけ落ちる→ 引き直す
            return 201, ""
        S.baba.req = req
        n = S.push(self.frame(2500), "u", "k")
        self.assertEqual(n, 2500)
        self.assertEqual([c[1] for c in calls], [1000, 1000, 1000, 500])
        self.assertTrue(calls[0][0].startswith("/rest/v1/nar_si5?on_conflict=track,race_date,race_no,runner_number"))

    def test_push_stops_after_3_retries(self):
        calls = []

        def req(base, key, path, method="GET", body=None):
            calls.append(1)
            return 500, "err"
        S.baba.req = req
        with self.assertRaises(SystemExit):
            S.push(self.frame(10), "u", "k")
        self.assertEqual(len(calls), 4)                                       # 最初の 1 回 + 引き直し 3 回

    def test_push_rejects_nankan_banei(self):
        for t in ["大井", "帯広ば"]:
            with self.assertRaises(AssertionError):
                S.push(self.frame(1, t), "u", "k")

    def test_month_range(self):
        self.assertEqual(S.month_range("2024-01", "2024-12"), ("2024-01-01", "2024-12-31"))
        self.assertEqual(S.month_range("2024-02", "2024-02"), ("2024-02-01", "2024-02-29"))
        self.assertEqual(S.month_range("2024", "2025"), ("2024-01-01", "2025-12-31"))

    def args(self, **kw):
        d = dict(track="高知", lo="2024-01", hi="2024-02", days=None, apply=True, beat=False, out=None, compare=None)
        d.update(kw)
        return __import__("argparse").Namespace(**d)

    def test_run_rejects_nankan_and_banei(self):
        for t in ["大井", "帯広ば", "高知,川崎"]:
            with self.assertRaises(SystemExit):
                S.run(self.args(track=t))

    def test_run_reads_all_tracks_and_window_writes_target_by_month(self):
        S.MIN_R = 30
        runs, races = synth(years=(2021, 2022, 2023, 2024))
        got, posts = {}, []

        def lf(base, key, tracks, lo, hi, workers=6, cols=None):
            got.update(tracks=tracks, lo=lo, hi=hi, cols=cols)
            U, R = pd.DataFrame(runs), pd.DataFrame(races)
            return U[(U.race_date >= lo) & (U.race_date <= hi)], R[(R.race_date >= lo) & (R.race_date <= hi)], {"x": {"mb": 1.0}}
        S.load_frames = lf

        def req(base, key, path, method="GET", body=None):
            posts.append(__import__("json").loads(body))
            return 201, ""
        S.baba.req = req
        os.environ.setdefault("SUPABASE_URL", "http://x")
        os.environ.setdefault("SUPABASE_SERVICE_KEY", "k")
        self.assertEqual(S.run(self.args()), 0)
        self.assertEqual(got["tracks"], S.ALL)                              # ふだんの力の走歴は全場(照合と同じ)
        self.assertEqual((got["lo"], got["hi"]), ("2021-01-01", "2024-02-29"))    # 前の 3 年の 1 月から対象の月まで
        self.assertNotIn("si5", got["cols"])
        self.assertEqual([p[0]["race_date"][:7] for p in posts], ["2024-01", "2024-02"])   # 月ごとに順に
        self.assertTrue(all(r["track"] == "高知" for p in posts for r in p))
        X, _ = S.compute_years(pd.DataFrame(runs), pd.DataFrame(races), "2024-01-01", "2024-02-29")
        x = S.out_frame(X, "SI")                                               # 書く値= o_s を足さない SI
        self.assertEqual(sorted(r["si5"] for p in posts for r in p), sorted(x.si5.tolist()))


class DailyTest(unittest.TestCase):
    """毎日の口(②)= 1〜3 着だけの基準+baba_diff の d1 が、埋め直し(①)と同じ値になる"""
    def test_daily_equals_backfill(self):
        S.MIN_R = 30
        runs, races = synth(years=(2021, 2022, 2023, 2024))
        lo, hi = "2024-06-01", "2024-06-21"
        X1, cf, pv = S.compute(runs, races, lo, hi)                          # ①(全部の走を読む・baba の関数で日の値)
        # baba_diff の blob の形(cloud/baba.py build_days+blend_proj の出力= {日: {prefix: {d, d1, n, ...}}})
        blob = {}
        for (d, t), v in cf.items():
            d1 = round(0.5 * v + 0.5 * pv[(d, t)], 2) if (d, t) in pv else v
            blob.setdefault(d, {})[S.baba.TRACK2PREFIX[t]] = {"d": round(d1 * 1.35, 1), "d1": d1, "n": 4, "k": "良"}
        blob.setdefault("2024-06-21", {})["kochi"] = {"d": 0.1, "d1": 0.1, "n": 4, "p": True}   # 暫定は使わない
        w0, top_hi = S.daily_ranges(lo, hi)
        self.assertEqual((w0, top_hi), ("2021-01-01", "2024-01-01"))
        top = [r for r in runs if w0 <= r["race_date"] < top_hi and r["finish"] <= 3 and r["time_sec"] is not None]
        tgt = [r for r in runs if lo <= r["race_date"] <= hi]
        rr = [r for r in races if (w0 <= r["race_date"] < top_hi) or (lo <= r["race_date"] <= hi)]
        U = pd.DataFrame([{k: r[k] for k in S.TOP_COLS} for r in top] + tgt)
        X2 = S.compute_daily(U, pd.DataFrame(rr), blob, lo, hi)
        a, b = S.out_frame(X1, "SI"), S.out_frame(X2, "SI")
        self.assertGreater(len(a), 0)
        pd.testing.assert_frame_equal(a, b)
        X3 = S.compute_daily(U, pd.DataFrame(rr), {}, lo, hi)                  # その日のセルが無ければ書かない
        self.assertEqual(len(S.out_frame(X3, "SI")), 0)
        self.assertTrue((X3.why[X3.time_sec.notna()] == "no_day").all())

    def test_daily_ranges_year_edge(self):
        self.assertEqual(S.daily_ranges("2026-12-20", "2027-01-09"), ("2023-01-01", "2026-12-20"))

    def test_compare_ref(self):
        S.MIN_R = 30
        runs, races = synth(years=(2021, 2022, 2023, 2024))
        X, _, _ = S.compute(runs, races, "2024-01-01", "2024-12-31")
        g = X[np.isfinite(X.SI)]
        ref = {"lo": "2024-01-01", "hi": "2024-12-31", "o_all": {"2024": {"高知": 0.0}},
               "mean": {"高知": round(float(g.SI.mean()), 1)}, "OP": {"高知": None},
               "class": {"高知": S.class_table(g, "SI")["高知"]}}
        f = Path(__import__("tempfile").mkdtemp()) / "ref.json"
        f.write_text(__import__("json").dumps(ref, ensure_ascii=False), encoding="utf-8")
        d = S.compare_ref(X, str(f))
        self.assertTrue(d and max(x[0] for x in d) == 0)
        ref["mean"]["高知"] += 1
        f.write_text(__import__("json").dumps(ref, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SystemExit):
            S.compare_ref(X, str(f))

    def test_ref_fixture_shape(self):
        ref = __import__("json").loads((ROOT / "tests/fixtures/si_all_check3_ref.json").read_text(encoding="utf-8"))
        self.assertEqual(set(ref["mean"]), set(S.TARGETS))
        self.assertEqual(ref["hi"], "2026-11-06")


if __name__ == "__main__":
    unittest.main()

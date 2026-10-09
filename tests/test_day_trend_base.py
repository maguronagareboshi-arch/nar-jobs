# -*- coding: utf-8 -*-
"""今日ここまでの傾向 ふだんの値(cloud/day_trend_base.py)の検算。⛔通信ゼロ。

  py -3.12 -m unittest discover -s tests -p "test_day_trend_base.py"

①クラス帯の直し(「歳以上」でクラス字なし= 上)・baba.band_of は変えない
②1 レースの値(3着以内の段・人気の付け直し・上がりの差・取消/中止)
③枠= 1R あたりの平均と標本分散・角ごとの n・L0→L3 の鍵
④期間= 区切りの後 300R 未満なら 1 つ前の区切りへ・名古屋は 2022-04-08 より前を入れない
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import baba  # noqa: E402
import day_trend_base as m  # noqa: E402


class BandFix(unittest.TestCase):
    CASES = [
        # (レース名, 条件, 場, 期待)
        ("珊瑚冠賞３歳以上", None, "高知", "上"),          # SPEC の例(高知 2026-09-27 7R)
        ("一般 ４歳以上", None, "高知", "上"),              # baba は None
        ("黒潮スプリンター特別", "３歳以上", "高知", "上"),  # 条件に「歳以上」
        ("Ｃ３－１ ３歳以上", None, "高知", "C3"),           # クラス字があればそのまま
        ("３歳", None, "高知", "3y"),                         # 3 歳限定戦は 3y のまま
        ("２歳新馬", None, "高知", "2y"),
        ("Ｃ１５組", None, "名古屋", "C"),                    # 東海は字だけ
        ("ファイナルレース", None, "高知", None),
    ]

    def test_cases(self):
        for name, cond, track, want in self.CASES:
            self.assertEqual(m.band_fix(name, cond, track), want, name)

    def test_baba_unchanged(self):
        self.assertIsNone(baba.band_of("珊瑚冠賞３歳以上", "高知"))
        self.assertIsNone(baba.band_of("一般 ４歳以上", "高知"))


def _race(**kw):
    r = {"track": "高知", "race_date": "2026-09-01", "race_no": 1, "race_name": "Ｃ３－１", "condition": None,
         "surface": "ダ", "distance_m": 1400, "going": "良", "cancelled": False,
         "corners": [{"name": "３コーナー", "order": "1,2,3,4,5,6,7,8,9"},
                     {"name": "４コーナー", "order": "9,8,7,6,5,4,3,2,1"}]}
    r.update(kw)
    return r


def _runs(fin, l3=None, pop=None, notes=None):
    out = []
    for i, f in enumerate(fin):
        out.append({"runner_number": i + 1, "finish": f, "finish_note": (notes or {}).get(i + 1),
                    "popularity": (pop or list(range(1, len(fin) + 1)))[i],
                    "last3f": (l3 or [40.0] * len(fin))[i]})
    return out


class RaceRecord(unittest.TestCase):
    def test_zones_pop_agari(self):
        # 1〜3 着= 馬番 1,2,3。3角は 1〜3番手(前)・4角は 7〜9番手(後ろ)
        l3 = [36.0, 36.0, 36.0, 40, 40, 40, 39.0, 39.0, 39.0]
        rec = m.race_record(_race(), _runs([1, 2, 3, 4, 5, 6, 7, 8, 9], l3=l3))
        self.assertEqual(rec["cz"], {"3": [3, 0, 0], "4": [0, 0, 3]})
        self.assertEqual(rec["pop"], {"1": 1, "2-3": 2, "4-6": 0, "7+": 0})
        self.assertEqual(rec["dk"], "ダ1400")
        # 4角 9 頭= 後ろ 7〜9番手(馬番 3,2,1= 36.0)− 前 1〜3番手(馬番 9,8,7= 39.0)
        self.assertAlmostEqual(rec["ag"], -3.0)

    def test_rerank_and_scratch(self):
        # 取消の馬(人気 1)を外して付け直す= 人気 2 が 1 番人気になる
        rec = m.race_record(_race(corners=[]), _runs([None, 1, 2, 3], pop=[1, 2, 3, 4], notes={1: "取消"}))
        self.assertEqual(rec["pop"], {"1": 1, "2-3": 2, "4-6": 0, "7+": 0})
        self.assertEqual(rec["cz"], {})
        self.assertIsNone(rec["ag"])

    def test_dropped(self):
        self.assertIsNone(m.race_record(_race(cancelled=True), _runs([1, 2])))
        self.assertIsNone(m.race_record(_race(), _runs([None, None])))
        self.assertIsNone(m.race_record(_race(track="名古屋", race_date="2022-04-07"), _runs([1, 2])))

    def test_agari_out_of_range(self):
        l3 = [0.0, 0.0, 36.0, 40, 40, 40, 39.0, 39.0, 39.0]   # 0.0= 非計測は数えない→ 後ろが 1 頭= 出さない
        rec = m.race_record(_race(), _runs([1, 2, 3, 4, 5, 6, 7, 8, 9], l3=l3))
        self.assertIsNone(rec["ag"])


class Cells(unittest.TestCase):
    def test_mean_var(self):
        recs = [{"d": "2026-01-01", "no": 1, "band": "C3", "going": "良", "dk": "ダ1400", "pop": {"1": 1, "2-3": 1, "4-6": 1, "7+": 0},
                 "cz": {"4": [3, 0, 0]}, "ag": 1.0},
                {"d": "2026-01-02", "no": 1, "band": "C3", "going": "良", "dk": "ダ1400", "pop": {"1": 0, "2-3": 2, "4-6": 1, "7+": 0},
                 "cz": {"4": [1, 1, 1], "1": [2, 1, 0]}, "ag": 0.0},
                {"d": "2026-01-03", "no": 1, "band": None, "going": "重", "dk": "ダ1400", "pop": None,
                 "cz": {}, "ag": None}]
        c = m.build_cells(recs)
        self.assertEqual(sorted(c), ["L0|C3|良|ダ1400", "L1|良|ダ1400", "L1|重|ダ1400", "L2|ダ1400", "L3"])
        a = c["L0|C3|良|ダ1400"]
        self.assertEqual(a["n"], 2)
        self.assertEqual(a["corners"]["4"], {"n": 2, "front": [2.0, 2.0], "mid": [0.5, 0.5], "back": [0.5, 0.5]})
        self.assertEqual(a["corners"]["1"], {"n": 1, "front": [2.0, 0.0], "mid": [1.0, 0.0], "back": [0.0, 0.0]})
        self.assertEqual(a["pop"]["n"], 2)
        self.assertEqual(a["pop"]["1"], [0.5, 0.5])
        self.assertEqual(a["agari"], {"n": 2, "mean": 0.5, "var": 0.5})
        z = c["L1|重|ダ1400"]
        self.assertEqual(z, {"n": 1})          # n が 0 の段(角・人気・上がり)は書かない
        self.assertEqual(c["L3"]["n"], 3)

    def test_banei(self):
        recs = [{"d": "2026-01-01", "no": 1, "band": "B1", "going": "1.0〜1.9", "dk": "ダート200",
                 "pop": {"1": 1, "2-3": 1, "4-6": 1, "7+": 0}}]
        c = m.build_cells(recs, banei=True)
        self.assertEqual(set(c["L0|B1|1.0〜1.9|ダート200"]), {"n", "pop"})
        self.assertEqual(m.moist_bucket("0.9"), "〜0.9")
        self.assertEqual(m.moist_bucket("3.0"), "3.0〜")


class Window(unittest.TestCase):
    SAND = {"venues": {"kochi": [
        {"raw": "2026-08-03〜09-01", "types": ["下地の工事"], "text": "本走路の下地の改修"},
        {"raw": "2024-08", "types": ["下地の工事"], "text": "下地工事"},
        {"raw": "2025-01-10", "types": ["砂厚の調整"], "text": "区切りではない"}]}}

    def test_cut_from(self):
        self.assertEqual(m.cut_from("2026-08-03〜09-01").isoformat(), "2026-09-02")
        self.assertEqual(m.cut_from("2024-08").isoformat(), "2024-09-01")
        self.assertEqual(m.cut_from("2019-10-05〜08").isoformat(), "2019-10-09")

    def test_widen(self):
        dates = ["2026-09-10"] * 70 + ["2025-06-01"] * 400
        w0, cut, note, post = m.window_of("高知", "2026-10-01", dates, self.SAND)
        self.assertEqual((w0, post, cut["raw"]), ("2024-09-01", 70, "2026-08-03〜09-01"))
        self.assertEqual(note, "2026-08-03〜09-01 の改修の後は 70R のため 2024-09-01 以降を使う")

    def test_enough_and_5y(self):
        w0, cut, note, post = m.window_of("高知", "2026-10-01", ["2026-09-10"] * 300, self.SAND)
        self.assertEqual((w0, note, post), ("2026-09-02", None, 300))
        w0, *_ = m.window_of("高知", "2026-10-01", ["2026-09-10"] * 10, self.SAND)
        self.assertEqual(w0, "2021-10-01")          # 1 つ前も届かない= 5 年
        w0, cut, note, post = m.window_of("佐賀", "2026-10-01", [], self.SAND)
        self.assertEqual((w0, cut), ("2021-10-01", None))

    def test_nagoya(self):
        w0, cut, *_ = m.window_of("名古屋", "2026-10-01", ["2023-01-01"] * 500, {"venues": {}})
        self.assertEqual((w0, cut["raw"]), ("2022-04-08", "2022-04-08"))
        w0, *_ = m.window_of("名古屋", "2026-10-01", [], {"venues": {}})
        self.assertEqual(w0, "2022-04-08")          # 広げても移転の前は入れない

    def test_value_excludes_month(self):
        recs = [{"d": "2026-10-01", "no": 1, "band": None, "going": None, "dk": "ダ1400", "pop": None, "cz": {}, "ag": None},
                {"d": "2026-09-30", "no": 1, "band": None, "going": None, "dk": "ダ1400", "pop": None, "cz": {}, "ag": None}]
        v = m.build_value("佐賀", "2026-10", recs, {"venues": {}}, "x")
        self.assertEqual(v["cells"]["L3"]["n"], 1)  # 当月(1 日以降)は入れない
        self.assertEqual(v["window"]["to"], "2026-09-30")
        self.assertEqual(v["venue"], "saga")


if __name__ == "__main__":
    unittest.main()

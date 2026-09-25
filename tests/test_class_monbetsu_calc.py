# -*- coding: utf-8 -*-
"""§284① cloud/class_monbetsu_calc.py= 公式の起点+自前の加算(表2・同着・上限・表3・中央欠け)と答え合わせ。
最後の 1 本は手元の写し(scratchpad の cls26/・cache_*.json)で「第12回を起点に第13回を当てる」回帰。無ければ飛ばす。"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
try:
    import class_monbetsu_calc as C  # noqa: E402
except ImportError as e:              # pipeline/ の部品が無い環境
    raise unittest.SkipTest(f"class_monbetsu_calc が読めない {e}")

M = 10000
SCR = Path(os.environ.get("S284_SCRATCH", r"C:\Users\kouki\AppData\Local\Temp\claude\C--Users-kouki-nar-site"
                          r"\e584ed58-6739-49e7-a7a7-575235d02fc4\scratchpad"))


def race(no, name, p1=1_000_000, kind=None, date="2026-09-10", track="門別"):
    return {"track": track, "race_date": date, "race_no": no, "race_name": name, "race_kind": kind,
            "prize_yen": [p1, p1 * 28 // 100, p1 * 21 // 100, p1 * 14 // 100, p1 * 7 // 100]}


def run(no, f, name="甲", age=4, date="2026-09-10", track="門別", **kw):
    return dict({"track": track, "race_date": date, "race_no": no, "horse_name": name, "age": age,
                 "birth_date": None, "finish": f, "finish_note": None}, **kw)


def one(base_man, races, runs, wins=0, others=()):
    rs = {(r["track"], r["race_date"], r["race_no"]): r for r in races}
    rn = C.runners_of(list(runs) + list(others))
    acc = C.Acc(base_man, wins, rs, rn)
    for r in runs:
        acc.add(r)
    return acc


class Table2(unittest.TestCase):
    def test_b_win_and_c_upper_lower(self):
        self.assertEqual(one(100, [race(1, "Ｂ３－１")], [run(1, 1)]).val, 150)          # B 1着 50
        self.assertEqual(one(100, [race(2, "Ｃ１－２")], [run(2, 2)]).val, 111)          # C上位 2着 11
        self.assertEqual(one(100, [race(3, "Ｃ３－２")], [run(3, 2)]).val, 100)          # C下位 2着 0
        self.assertEqual(one(100, [race(4, "来年も門別でＪＢＣ２歳優駿特別Ｂ４－２Ｃ１")], [run(4, 4)]).val, 107)  # ＪＢＣ の Ｃ は級でない→B

    def test_tie_average_floor(self):
        # ※4 同着 2着×2 頭 = (11+8)/2 = 9.5 → 9(1万円未満切捨て)
        a = one(100, [race(5, "Ｃ２－１")], [run(5, 2)], others=[run(5, 2, name="乙")])
        self.assertEqual(a.val, 109)
        self.assertIn("同着", a.flags)

    def test_cap_4000(self):
        self.assertEqual(one(3990, [race(6, "Ａ１")], [run(6, 1)]).val, 4000)

    def test_real_prize_caps_amount(self):
        r = race(7, "Ｂ２")
        r["prize_yen"] = [300_000, 60_000, 40_000, 20_000, 10_000]
        self.assertEqual(one(100, [r], [run(7, 1)]).val, 130)      # 表は50だが実賞金30万

    def test_nisai_cap2_40(self):
        r = race(8, "２歳", p1=900_000)                             # K12(1着100万未満)
        self.assertEqual(one(30, [r], [run(8, 2, age=2)]).val, 40)  # 30+14 → ※2 で 40 止め
        self.assertEqual(one(30, [r], [run(8, 1, age=2)]).val, 80)  # 1着は止めない

    def test_nisai_cap1_15(self):
        r = race(9, "ＪＲＡ認定アタックチャレンジ２歳", p1=1_500_000)
        self.assertEqual(one(12, [r], [run(9, 2, age=2)]).val, 15)            # ※1 未勝利は 15 止め
        self.assertEqual(one(12, [r], [run(9, 2, age=2)], wins=1).val, 17)    # 勝ち上がり馬は止めない


class OtherTracks(unittest.TestCase):
    def test_table3_nar(self):
        r = race(1, "Ｃ１", p1=3_000_000, track="大井")
        self.assertEqual(one(100, [r], [run(1, 1, track="大井")]).val, 175)   # 300万×25%=75

    def test_jra_missing(self):
        a = one(100, [], [run(3, 3, track="中央", surface="ダ")])
        self.assertEqual((a.val, "中央の賞金なし" in a.flags), (100, True))
        b = one(100, [], [run(3, 8, track="中央", surface="ダ")])
        self.assertEqual((b.val, "中央の賞金なし" in b.flags), (100, False))  # 6着以下は 0 で欠けでない


class Build(unittest.TestCase):
    def test_check_and_rebase(self):
        off12 = {"fy": 2026, "kai": 12, "asof": "2026-09-11", "asof_by": {"ipan": "2026-09-11"},
                 "horses": {"甲": {"prize": 700_000, "age": 4, "cls": "Ｃ４－１"},
                            "乙": {"prize": 700_000, "age": 4, "cls": "Ｃ４－１"}}}
        hist = {"fy": 2026, "kais": {"12": off12}}
        off13 = {"fy": 2026, "kai": 13, "asof": "2026-09-25", "asof_by": {"ipan": "2026-09-25"},
                 "horses": {"甲": {"prize": 1_200_000, "age": 4, "cls": "Ｃ３－１"},
                            "乙": {"prize": 900_000, "age": 4, "cls": "Ｃ３－２"}}}
        rs = [race(1, "Ｂ４", date="2026-09-15"), race(1, "Ｃ２", date="2026-09-26")]
        runs = [run(1, 1, date="2026-09-15"), run(1, 1, name="乙", date="2026-09-26")]
        v = C.build(off13, hist, None, runs, {}, {(r["track"], r["race_date"], r["race_no"]): r for r in rs}, "2026-09-30")
        self.assertEqual((v["check"]["n"], v["check"]["match"]), (2, 1))       # 乙は公式が 90 万= 外れ
        self.assertEqual(v["check"]["miss"][0][:3], ["乙", 700_000, 900_000])
        self.assertEqual(v["horses"]["乙"]["base"], 900_000)                    # 新しい公式で置き直し
        self.assertEqual(v["horses"]["乙"]["prize"], 1_300_000)                 # 9/26 Ｃ２ 1着 40
        self.assertEqual(v["horses"]["乙"]["kaku"], "Ｃ２")
        self.assertEqual(v["horses"]["甲"]["prize"], 1_200_000)                 # 9/15 は第13回に入っている
        self.assertEqual(C.note_of(v)[0], False)

    def test_check_from_saved_calc(self):
        # hist は無い(本番どおり)。保存済みの calc(第12回起点)を持った状態で第13回の公式を当てる
        off12 = {"fy": 2026, "kai": 12, "asof": "2026-09-11", "asof_by": {"ipan": "2026-09-11"},
                 "horses": {"甲": {"prize": 700_000, "age": 4, "cls": "Ｃ４－１"},
                            "乙": {"prize": 700_000, "age": 4, "cls": "Ｃ４－１"}}}
        rs = {(r["track"], r["race_date"], r["race_no"]): r
              for r in [race(1, "Ｂ４", date="2026-09-15"), race(2, "Ｃ２", date="2026-09-16")]}
        runs = [run(1, 1, date="2026-09-15"), run(2, 1, name="乙", date="2026-09-16")]
        prev = C.build(off12, None, None, runs, {}, rs, "2026-09-20")
        self.assertIsNone(prev["check"])                                        # 初回は照合なし
        self.assertEqual(prev["horses"]["甲"]["prize"], 1_200_000)
        off13 = {"fy": 2026, "kai": 13, "asof": "2026-09-25", "asof_by": {"ipan": "2026-09-25"},
                 "horses": {"甲": {"prize": 1_200_000, "age": 4, "cls": "Ｃ３－１"},
                            "乙": {"prize": 1_000_000, "age": 4, "cls": "Ｃ３－２"}}}
        prev = json.loads(json.dumps(prev))                                     # nar_meta を通った形
        v = C.build(off13, None, prev, runs, {}, rs, "2026-09-25")
        c = v["check"]
        self.assertEqual((c["kai"], c["n"], c["match"], c["new"]), (13, 2, 1, True))
        self.assertEqual(c["miss"], [["乙", 1_100_000, 1_000_000, 12]])
        self.assertEqual((v["base_kai"], v["horses"]["乙"]["base_kai"], v["horses"]["乙"]["prize"]), (13, 13, 1_000_000))
        self.assertEqual(sorted(v["cuts"]), ["12", "13"])
        v2 = C.build(off13, None, json.loads(json.dumps(v)), runs, {}, rs, "2026-09-26")
        self.assertEqual((v2["check"]["new"], C.note_of(v2)[0]), (False, True))  # 翌朝の便は照合を持ち越し ok


@unittest.skipUnless((SCR / "cls26" / "kai13.json").exists() and (SCR / "cache_runs.json").exists(),
                     "手元の写し(scratchpad)が無い")
class Regression(unittest.TestCase):
    def test_kai12_to_kai13(self):
        ld = lambda p: json.loads((SCR / p).read_text(encoding="utf-8"))  # noqa: E731
        kais = {k: ld(f"cls26/kai{k:02d}.json") for k in range(1, 14)}
        hist = {"fy": 2026, "kais": {str(k): v for k, v in kais.items() if k < 13}}
        nar = ld("cache_runs.json") + ld("cache_runs2.json")
        races = {(r["track"], r["race_date"], r["race_no"]): r for r in ld("cache_races.json") + ld("cache_races2.json")}
        j = ld("cache_jra.json")
        jra = C.jra_group(j["horses"], j["runs"])
        v = C.build(dict(kais[13], fy=2026), hist, None, nar, jra, races, "2026-09-24")
        c = v["check"]
        k12 = [m for m in c["miss"] if m[3] == 12]
        print(f"\n第12回起点→第13回: {c['match']}/{c['n']} 外れ {len(c['miss'])}(起点が第12回の馬 {len(k12)})"
              f" {[m[0] for m in c['miss']][:10]}")
        self.assertLessEqual(len(k12), 2)       # stage3 12->13 の外れ 2(同着の端数の揺れ)以下


if __name__ == "__main__":
    unittest.main()

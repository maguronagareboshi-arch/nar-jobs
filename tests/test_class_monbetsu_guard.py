# -*- coding: utf-8 -*-
"""2026-10-09 事故(第14回 2歳 PDF の「前走馬体重」386〜420 を番組賞金(万)と読んだ)の再発防止。
  ・parse_cell は見出しを見ない(数字の語は全部賞金と読む)= 列の意味は枠の見出し(drop_weight_prizes)で決める
  ・取り込み前の番人(guard_shape / guard_rise)が事故の形を止め、正しい表は止めない
  ・自前の加算の照合は、同じ回が取り直されたらやり直す(stale_check / build の redo)
最後の組は手元の写し(第1〜14回の正しい表と事故の読み方の第14回 kaiNN.json)で回帰。無ければ飛ばす。"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
try:
    import class_monbetsu as CM  # noqa: E402
    import class_monbetsu_calc as C  # noqa: E402
except ImportError as e:              # pipeline/ の部品が無い環境
    raise unittest.SkipTest(f"class_monbetsu が読めない {e}")

M = 10000
KAIS = Path(os.environ.get("S284G_KAIS", r"C:\Users\kouki\AppData\Local\Temp\claude\C--Users-kouki-nar-site"
                           r"\c8a75b7b-1461-4547-942c-92f456811cf4\scratchpad\kais"))


def w(text, x):
    return {"text": text, "x0": x, "top": 100.0}


def nisai_row(weight_or_prize):
    """2歳の紙面の 1頭: 馬名 [数字] 牝 調教師"""
    return [w("ウワサノリクチャン", 10), w(str(weight_or_prize), 80), w("牝", 100), w("田中", 120)]


def table(kai, horses, fy=2026, asof="2026-10-09"):
    return {"fy": fy, "kai": kai, "asof": asof, "asof_by": {}, "horses": horses}


def nisai_mi(prizes, start=0):
    return {f"ウマ{i + start:03d}": {"prize": p, "age": None, "cls": "未勝利"} for i, p in enumerate(prizes)}


class ParseCell(unittest.TestCase):
    def test_parse_cell_reads_any_number_as_prize(self):
        # 固定: parse_cell は見出しを見ない。412 は(馬体重でも)賞金 412万 と読む
        row = CM.parse_cell(nisai_row(412), [], "t")
        self.assertEqual(row["prize"], 412 * M)
        self.assertEqual(row["sex"], "牝")

    def test_weight_heading_drops_prize(self):
        # 枠の見出しに「前走馬体重」があれば、その枠の数字は賞金でない
        rows = [CM.parse_cell(nisai_row(v), [], "t") for v in (386, 420)]
        lines = {50.0: [(10, "ＪＲＡ認定アタックチャレンジ"), (90, "前走馬体重４２０㎏以下")]}
        self.assertEqual(CM.drop_weight_prizes(lines, rows), 2)
        self.assertTrue(all("prize" not in r for r in rows))

    def test_other_heading_keeps_prize(self):
        rows = [CM.parse_cell(nisai_row(15), [], "t")]
        self.assertEqual(CM.drop_weight_prizes({50.0: [(10, "未勝利")]}, rows), 0)
        self.assertEqual(rows[0]["prize"], 15 * M)


class Guard(unittest.TestCase):
    def setUp(self):
        # 前の回: 2歳未勝利 187頭(賞金あり 128 頭・0〜15万)+3歳以上
        self.old_h = nisai_mi([(i % 16) * M if i % 3 else 0 for i in range(187)])
        self.old_h |= {f"フルウマ{i:03d}": {"prize": (60 + i % 40) * M, "age": 4, "cls": "Ｃ３－１"} for i in range(500)}
        self.old = table(13, self.old_h, asof="2026-09-25")

    def misread(self):
        """事故の形= 31頭の 0〜15万 が 386〜420万(前走馬体重)に"""
        h = json.loads(json.dumps(self.old_h))
        for i, nm in enumerate(sorted(nm for nm in h if nm.startswith("ウマ"))[:31]):
            h[nm]["prize"] = (386 + i) * M
        return table(14, h)

    def test_misread_is_stopped_by_shape(self):
        why = CM.guard_shape(self.misread(), self.old)
        self.assertTrue(any("40万超" in x for x in why), why)

    def test_misread_is_stopped_by_rise(self):
        new = self.misread()
        # 31頭とも 9/25〜10/8 に門別の2歳未勝利を 2 走(最大加算= 表2 MI の 1着 15万 ×2)
        bound = {nm: 2 * C.T2_2["MI"][0] for nm in new["horses"] if nm.startswith("ウマ")}
        why, over = CM.guard_rise(new, self.old, bound)
        self.assertEqual(len(over), 31)
        self.assertTrue(why)

    def test_rise_without_runs_uses_cap(self):
        new = table(14, {"ア": {"prize": 4100 * M, "age": 5}, "イ": {"prize": 3000 * M, "age": 5},
                         "ウ": {"prize": 4200 * M, "age": 5}, "エ": {"prize": 4500 * M, "age": 5}})
        old = table(13, {k: {"prize": 100 * M, "age": 5} for k in new["horses"]}, asof="2026-09-25")
        why, over = CM.guard_rise(new, old, {})
        self.assertEqual([x[0] for x in over], ["ア", "ウ", "エ"])   # 4,000万を超える上がりだけ
        self.assertTrue(why)

    def test_rise_same_kai_not_checked(self):
        why, over = CM.guard_rise(self.misread() | {"kai": 13}, self.old, {})
        self.assertEqual((why, over), ([], []))

    def test_fix_direction_passes(self):
        # 読み違いの直し(第14回の取り直し)= 減る向きは止めない
        bad = self.misread()
        good = table(14, json.loads(json.dumps(self.old_h)))
        self.assertEqual(CM.guard_shape(good, bad), [])

    def test_normal_round_passes(self):
        h = json.loads(json.dumps(self.old_h))
        for nm in list(h)[:20]:
            h[nm]["prize"] += 5 * M
        self.assertEqual(CM.guard_shape(table(14, h), self.old), [])

    def test_other_fy_not_checked(self):
        self.assertEqual(CM.guard_shape(self.misread(), self.old | {"fy": 2025}), [])

    def test_guard_check_without_db(self):
        # DB が無くても形の 2 つで止まる
        self.assertTrue(CM.guard_check("", "", self.misread(), self.old))


class RiseBounds(unittest.TestCase):
    """rise_bounds は新しい表の全馬の走を読む(上がった馬だけだと 3 歳限定戦の出走馬が欠ける)。
    期間内に走が無い馬は上限 C.CAP で見る(止める数に入れない)。"""
    RACE = ("門別", "2026-10-01", 5)

    def setUp(self):
        # 前の回 9/25 締め→新しい回 10/9 締め。フェルカド特別Ｃ１(名前に「３歳」なし)に 3歳 8頭
        self.horses = [f"サンサイ{i}" for i in range(8)]
        old_h = {nm: {"prize": 100 * M, "age": 3} for nm in self.horses}
        old_h["スハッチェ"] = {"prize": 100 * M, "age": 3}
        new_h = json.loads(json.dumps(old_h))
        new_h[self.horses[0]]["prize"] = 150 * M      # 1着 +50万
        new_h["スハッチェ"]["prize"] = 152 * M          # 期間内の走が DB に無い
        self.old = table(13, old_h, asof="2026-09-26")
        self.new = table(14, new_h, asof="2026-10-10")
        tr, d, no = self.RACE
        self.nar = [{"track": tr, "race_date": d, "race_no": no, "horse_name": nm, "birth_date": None,
                     "age": 3, "finish": i + 1, "finish_note": None} for i, nm in enumerate(self.horses)]
        self.races = {self.RACE: {"track": tr, "race_date": d, "race_no": no, "race_name": "フェルカド特別Ｃ１",
                                  "race_kind": "一般", "prize_yen": [500000]}}
        self.asked = None
        self._fetch = C.fetch

        def fake(base, key, names, since, cut_min):
            self.asked = set(names)
            return [r for r in self.nar if r["horse_name"] in names], self.races, {}
        C.fetch = fake

    def tearDown(self):
        C.fetch = self._fetch

    def test_all_runners_make_3yo_race(self):
        bound = CM.rise_bounds("b", "k", self.new, self.old)
        self.assertEqual(self.asked, set(self.new["horses"]))   # 全馬を読む
        self.assertEqual(bound[self.horses[0]], 50)               # 3歳 K13= 50万(3歳以上と見ると 40万)
        why, over = CM.guard_rise(self.new, self.old, bound)
        self.assertEqual(over, [])

    def test_partial_runners_would_misjudge(self):
        # 上がった馬 1頭だけの出走馬では 3歳以上(40万)と取り違える= 直した理由
        runners = C.runners_of([self.nar[0]])
        self.assertEqual(C.race_group(runners[self.RACE], self.races[self.RACE]), "3u")
        self.assertEqual(C.race_group(C.runners_of(self.nar)[self.RACE], self.races[self.RACE]), "3")

    def test_no_runs_in_period_uses_cap(self):
        bound = CM.rise_bounds("b", "k", self.new, self.old)
        self.assertEqual(bound["スハッチェ"], C.CAP)
        why, over = CM.guard_rise(self.new, self.old, bound)
        self.assertNotIn("スハッチェ", [x[0] for x in over])


class RedoCheck(unittest.TestCase):
    """自前の加算: 同じ回(第14回)が取り直されたら、その回の照合を第13回までの公式からやり直す。"""

    def setUp(self):
        self.hist = {"fy": 2026, "kais": {"13": {"asof": "2026-09-25", "asof_by": {},
                                                 "horses": {"甲": {"prize": 0, "age": 2, "cls": "未勝利"}}}}}
        self.bad = {"fy": 2026, "kai": 14, "asof": "2026-10-09", "asof_by": {},
                    "horses": {"甲": {"prize": 408 * M, "age": 2, "cls": "未勝利"}}}
        self.good = dict(self.bad, horses={"甲": {"prize": 0, "age": 2, "cls": "未勝利"}})
        # 19:46 の calc= 読み違いの第14回で照合し(外れ)、起点も 408万
        self.prev = C.build(self.bad, self.hist, None, [], {}, {}, "2026-10-09")
        self.assertEqual(self.prev["check"]["match"], 0)

    def test_stale_detected(self):
        self.assertTrue(C.stale_check(self.good, self.prev))
        self.assertFalse(C.stale_check(self.bad, self.prev))

    def test_redo_overwrites_check(self):
        redo = C.redo_plan(self.good, self.hist)
        v = C.build(self.good, None, self.prev, [], {}, {}, "2026-10-10", redo)
        self.assertEqual((v["check"]["kai"], v["check"]["n"], v["check"]["match"], v["check"]["new"]), (14, 1, 1, True))
        self.assertEqual(v["horses"]["甲"]["base"], 0)

    def test_without_redo_old_check_stays(self):
        v = C.build(self.good, None, self.prev, [], {}, {}, "2026-10-10")
        self.assertEqual(v["check"]["match"], 0)        # 従来の動き(だから redo が要る)
        self.assertFalse(v["check"]["new"])

    def test_redo_needs_previous_round(self):
        self.assertIsNone(C.redo_plan(self.good, {"fy": 2026, "kais": {}}))


@unittest.skipUnless((KAIS / "kai14_misread.json").exists(), "手元の写し(kaiNN.json)が無い")
class RealTables(unittest.TestCase):
    """令和8年度 第1〜14回の正しい表= 誤検知 0・事故の読み方の第14回= 止める(しきい値の根拠)。"""

    def load(self, name):
        v = json.loads((KAIS / name).read_text(encoding="utf-8"))
        return table(v["kai"], v["horses"], asof=v.get("asof") or "2026-10-09")

    def test_correct_rounds_pass(self):
        ks = [self.load(f"kai{k:02d}.json") for k in range(1, 15)]
        for a, b in zip(ks, ks[1:]):
            self.assertEqual(CM.guard_shape(b, a), [], f"第{a['kai']}→{b['kai']}回")

    def test_misread_14_stopped(self):
        why = CM.guard_shape(self.load("kai14_misread.json"), self.load("kai13.json"))
        self.assertTrue(any("40万超" in x for x in why), why)
        self.assertTrue(any("賞金あり" in x for x in why), why)
        self.assertTrue(any("2歳の中央値" in x for x in why), why)


if __name__ == "__main__":
    unittest.main()

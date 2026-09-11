# -*- coding: utf-8 -*-
"""§149 D 高知の「結果はあるのにレース名が空」の行を埋め直す部分の検算。⛔通信ゼロ。

  py -3.12 -m unittest discover -s tests -p "test_kochi*.py"

2026-09-06 の穴= 出馬表を nar から組んだ時点で `nar_races` にまだ名前が入っておらず、
名前・距離・クラスが**空のまま**保存された。その後は「着順あり → 触らない」の規則で
二度と直らず 12 行残った(#551 で Fable が手で埋めた)。

確かめるのは 6 つ=
  ①空の行だけ埋まる(名前がもう入っている行は触らない= None を返す)
  ②**結果列は 1 つも変わらない**(着順・タイム・上がり・通過・人気・オッズ・馬体重)
  ③計測・談話・血統コード等の既存の値も落ちない(⛔部分行を送らない)
  ④公式にまだ名前が無ければ**空のまま残す**(推測で埋めない)
  ⑤既存の馬の行が 1 つも無ければ送らない(部分行で既存値を消さない)
  ⑥通し= 空の行が無ければ**問い合わせ 1 本**で終わる(毎日の便を重くしない)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud.kochi_results import (  # noqa: E402
    HORSE_KEYS, RACE_KEYS, RESULT_KEYS, fill_missing_names, fill_name_bundle, name_meta_of, simple_class,
)

D = "2026/09/06"
META = {"race_date": "2026-09-06", "race_no": 3, "race_name": "３歳－４", "distance_m": 1300}

# 結果保存が終わった後の既存行(名前だけ空)。⚠計測列(first3f)・談話・血統コードが同居している
EX_RACE = {
    "race_date": D, "race_no": 3, "baba_code": "31", "race_name": "", "distance": "", "race_class": "",
    "track_cond": "良", "first3f": "35.8", "first3f_source": "ラップから", "agari4f": "51.2",
    "agari3f_race": "38.4", "pace_type": "", "memo": "手で書いたメモ", "lap_times": "12.1,11.9",
}
EX_HORSES = [
    {"race_date": D, "race_no": 3, "baba_code": "31", "uma_ban": 2, "waku_ban": "2",
     "horse_name": "タロウ", "belong": "高知", "sex_age": "牝3", "kinryo": "54.0", "jockey": "赤岡修",
     "trainer": "別府真", "weight": "430", "chakujun": "1", "ninki": "2", "odds": "3.4",
     "time": "1:25.6", "diff": "", "agari3f": "38.4", "corner": "2-2", "first3f": "35.8",
     "pace_type": "", "mukae_shoumen": "12.3", "shoumen_straight": "", "post_comment": "談話の写し",
     "lineage_login_code": "K0001"},
    {"race_date": D, "race_no": 3, "baba_code": "31", "uma_ban": 1, "waku_ban": "1",
     "horse_name": "ハナコ", "belong": "高知", "sex_age": "牡3", "kinryo": "56.0", "jockey": "永森大",
     "trainer": "雑賀正", "weight": "455", "chakujun": "2", "ninki": "1", "odds": "2.1",
     "time": "1:25.8", "diff": "1 1/4", "agari3f": "38.9", "corner": "1-1", "first3f": "35.5",
     "pace_type": "", "mukae_shoumen": "", "shoumen_straight": "", "post_comment": "",
     "lineage_login_code": "K0002"},
]


class FillNameTest(unittest.TestCase):
    def test_fills_only_the_empty_name(self):
        """①空の行だけ埋まる・名前が入っている行は触らない"""
        b = fill_name_bundle(D, 3, EX_RACE, EX_HORSES, META)
        self.assertIsNotNone(b)
        self.assertEqual(b["race"]["race_name"], "３歳－４")
        self.assertEqual(b["race"]["distance"], "1300ｍ")          # 手動保存の実物に合わせた全角
        self.assertEqual(b["race"]["race_class"], simple_class("３歳－４"))
        self.assertEqual(b["race"]["race_class"], "3歳")
        self.assertEqual(b["race_id"], "race_31_2026/09/06_3")
        self.assertEqual(b["expected_uma_ban"], [1, 2])
        # もう名前が入っている行は送らない
        self.assertIsNone(fill_name_bundle(D, 3, {**EX_RACE, "race_name": "既にある"}, EX_HORSES, META))

    def test_result_columns_never_change(self):
        """②結果列は 1 つも変わらない(⛔埋め直しで着順が動いたら事故)"""
        b = fill_name_bundle(D, 3, EX_RACE, EX_HORSES, META)
        by_ban = {h["uma_ban"]: h for h in b["horses"]}
        for ex in EX_HORSES:
            got = by_ban[int(ex["uma_ban"])]
            for k in sorted(RESULT_KEYS):
                self.assertEqual(str(got.get(k) or ""), str(ex.get(k) or ""), f"{k} が変わった")
        # 並びは馬番順(⛔送る中身の順で取り違えない)
        self.assertEqual([h["uma_ban"] for h in b["horses"]], [1, 2])

    def test_keeps_everything_else(self):
        """③計測・談話・血統コード・メモ・ラップも落ちない(部分行を送らない)"""
        b = fill_name_bundle(D, 3, EX_RACE, EX_HORSES, META)
        for k in RACE_KEYS:
            if k in ("race_name", "distance", "race_class"):
                continue
            self.assertEqual(str(b["race"].get(k) or ""), str(EX_RACE.get(k) or ""), f"race.{k} が変わった")
        by_ban = {h["uma_ban"]: h for h in b["horses"]}
        for ex in EX_HORSES:
            got = by_ban[int(ex["uma_ban"])]
            for k in HORSE_KEYS:
                self.assertEqual(str(got.get(k) or ""), str(ex.get(k) or ""), f"horse.{k} が変わった")
            self.assertEqual(sorted(got), sorted(HORSE_KEYS), "列の顔ぶれが手動保存と違う")

    def test_no_official_name_means_leave_it_empty(self):
        """④公式にまだ名前が無ければ空のまま(⛔推測で埋めない)"""
        self.assertIsNone(fill_name_bundle(D, 3, EX_RACE, EX_HORSES, None))
        self.assertIsNone(fill_name_bundle(D, 3, EX_RACE, EX_HORSES, {"race_name": ""}))
        self.assertIsNone(fill_name_bundle(D, 3, EX_RACE, EX_HORSES, {"race_name": "   "}))
        self.assertIsNone(fill_name_bundle(D, 3, EX_RACE, EX_HORSES, {"race_name": None, "distance_m": 1300}))

    def test_no_horses_means_do_not_send(self):
        """⑤既存の馬の行が無ければ送らない(部分行で既存値を消さない)"""
        self.assertIsNone(fill_name_bundle(D, 3, EX_RACE, [], META))
        self.assertIsNone(fill_name_bundle(D, 3, EX_RACE, None, META))

    def test_distance_and_class_only_when_empty(self):
        """⚠距離・クラスは**空のときだけ**入れる(手で直した値に勝たせない)"""
        ex = {**EX_RACE, "distance": "1600ｍ", "race_class": "C1"}
        b = fill_name_bundle(D, 3, ex, EX_HORSES, META)
        self.assertEqual(b["race"]["distance"], "1600ｍ")
        self.assertEqual(b["race"]["race_class"], "C1")
        # 公式に距離が無い回は距離を空のまま残す
        b2 = fill_name_bundle(D, 3, EX_RACE, EX_HORSES, {"race_name": "３歳－４"})
        self.assertEqual(b2["race"]["distance"], "")

    def test_race_row_missing_is_still_ok(self):
        """⚠keiba_races に行が無い日(馬の行だけある)でも組める"""
        b = fill_name_bundle(D, 3, None, EX_HORSES, META)
        self.assertEqual(b["race"]["race_name"], "３歳－４")
        self.assertEqual(b["race"]["track_cond"], "")
        self.assertEqual(sorted(b["race"]), sorted(RACE_KEYS))


class MetaTest(unittest.TestCase):
    def test_name_meta_of(self):
        """公式の 1 本の結果を (日, R) で引ける形にするだけ。⛔壊れた行は飛ばす(止めない)"""
        rows = [{"race_date": "2026-09-06", "race_no": 3, "race_name": "A"},
                {"race_date": "2026-09-06", "race_no": "4", "race_name": "B"},
                {"race_date": None, "race_no": None},
                {"race_no": "x"}]
        m = name_meta_of(rows)
        self.assertEqual(m[("2026-09-06", 3)]["race_name"], "A")
        self.assertEqual(m[("2026-09-06", 4)]["race_name"], "B")     # 文字の R も数に直す
        self.assertEqual(len(m), 2)
        self.assertEqual(name_meta_of(None), {})


class Out:
    """書き出し先の代わり(⛔テストでファイルを作らない)"""
    def __truediv__(self, name):
        self.name = name
        return self

    def write_text(self, *a, **k):
        return None


class FillMissingNamesTest(unittest.TestCase):
    """⑥通し= 空の行を探す 1 本 → 見つかった日だけ既存行を読む → 送る形にする"""

    def run_with(self, holes):
        seen = []

        def keiba(path):
            seen.append(path.split("?")[0] + ("|" + path.split("&or=")[1] if "&or=" in path else ""))
            if "or=" in path:
                return holes
            if path.startswith("keiba_races"):
                return [EX_RACE]
            return EX_HORSES

        sent = []

        def post(b, label):
            sent.append((label, b))
            return 0

        fails = fill_missing_names(keiba, name_meta_of([META]), Out(), True, post)
        return seen, sent, fails

    def test_no_holes_costs_one_query(self):
        """⛔空の行が 1 つも無ければ**問い合わせは 1 本だけ**で終わる(毎日の便を重くしない)"""
        seen, sent, fails = self.run_with([])
        self.assertEqual(len(seen), 1)
        self.assertEqual(sent, [])
        self.assertEqual(fails, 0)

    def test_one_hole_is_filled(self):
        """見つかった日だけ既存行を読み、名前・距離・クラスを入れた完全な行を送る"""
        seen, sent, fails = self.run_with([{"race_date": D, "race_no": 3}])
        self.assertEqual(len(seen), 3)                      # 空の行を探す 1 + その日の races/horses 2
        self.assertEqual(fails, 0)
        self.assertEqual(len(sent), 1)
        label, b = sent[0]
        self.assertIn("2026/09/06 3R", label)
        self.assertEqual(b["race"]["race_name"], "３歳－４")
        self.assertEqual(b["race"]["memo"], "手で書いたメモ")     # ⛔既存の値は落とさない
        self.assertEqual([h["chakujun"] for h in b["horses"]], ["2", "1"])   # ⛔着順はそのまま(馬番順)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)

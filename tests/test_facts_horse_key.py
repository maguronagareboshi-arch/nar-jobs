# -*- coding: utf-8 -*-
"""§238e 馬の鍵(名前|生年の後退)と脚質の過去走の (名前, 生年) 照合・ドライランの差の数え方。
標準ライブラリだけ・**通信ゼロ**(REST を読む関数は差し替える)。

  py -3.12 -X utf8 -m unittest tests.test_facts_horse_key -v

確かめるのは=
  ①horse_key= 生年月日があれば 名前|生年月日(今のまま)・無い行だけ 名前|生年・名前か age が無ければ None
  ②birth_year_of= 生年月日の年 or レースの年 − age(1/1 に一斉に加算)・age 空文字は None
  ③build_window= 楽天(2022-10・生年月日なし)→ 公式(2022-11・生年月日あり)の走がつながって脚質が付く・
    同じ名前でも生年が違う馬はつながない・名前だけの行は鍵も脚質も空
  ④ドライラン= 書かない(upsert を呼ばない)・本番との差を数える
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import facts                                            # noqa: E402
from cloud import run_facts                                           # noqa: E402


class HorseKey(unittest.TestCase):
    def test_birth_date(self):
        self.assertEqual(facts.horse_key("テスト馬", "2021-04-01"), "テスト馬|2021-04-01")
        self.assertEqual(facts.horse_key("テスト馬", "2021-04-01T00:00:00"), "テスト馬|2021-04-01")
        self.assertEqual(facts.horse_key("テスト馬", "2021-04-01", 9, "2024-10-15"), "テスト馬|2021-04-01",
                         "生年月日があるのに age を見ている")

    def test_fallback_birth_year(self):
        self.assertEqual(facts.horse_key("テスト馬", None, 3, "2022-10-15"), "テスト馬|2019")
        self.assertEqual(facts.horse_key("テスト馬", "", "3", "2022-10-15"), "テスト馬|2019")
        self.assertEqual(facts.horse_key("テスト馬", None, 4, "2023-01-03"), "テスト馬|2019", "年明けの加算")

    def test_none(self):
        self.assertIsNone(facts.horse_key("テスト馬", None))
        self.assertIsNone(facts.horse_key("テスト馬", None, "", "2022-10-15"), "age 空文字")
        self.assertIsNone(facts.horse_key("テスト馬", None, None, "2022-10-15"))
        self.assertIsNone(facts.horse_key("テスト馬", None, 3, None), "レース日が無い")
        self.assertIsNone(facts.horse_key(None, "2021-04-01"), "名前だけでなく名前なしも None")
        self.assertIsNone(facts.horse_key("", None, 3, "2022-10-15"))

    def test_birth_year_of(self):
        import datetime as dt
        self.assertEqual(facts.birth_year_of("2019-04-01", 3, "2022-11-05"), 2019)
        self.assertEqual(facts.birth_year_of("2019-04-01", 9, "2022-11-05"), 2019, "生年月日が先")
        self.assertEqual(facts.birth_year_of(None, 3, "2022-10-15"), 2019)
        self.assertEqual(facts.birth_year_of(None, "3", dt.date(2022, 10, 15)), 2019)
        self.assertEqual(facts.birth_year_of(None, 3.0, "2022-10-15"), 2019)
        self.assertIsNone(facts.birth_year_of(None, "", "2022-10-15"))
        self.assertIsNone(facts.birth_year_of(None, 0, "2022-10-15"))
        self.assertIsNone(facts.birth_year_of(None, "三", "2022-10-15"))
        self.assertIsNone(facts.birth_year_of(None, None, None))

    def test_selftest(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(facts.selftest(), 0)


def _corners(order):
    return [{"name": "1角", "order": order}]


class Window(unittest.TestCase):
    """2022-11 の窓を焼く。過去走は 2022-10(楽天= 生年月日なし・age あり)。"""

    RACES_NOV = [{"track": "高知", "race_date": "2022-11-05", "race_no": 1,
                  "corners": _corners("1,2,3,4,5,6,7,8,9,10"), "source": "official"}]
    RUNS_NOV = [
        # 楽天期から続く馬(公式に移って生年月日が付いた)
        {"track": "高知", "race_date": "2022-11-05", "race_no": 1, "runner_number": 1,
         "horse_name": "ツナガル", "birth_date": "2019-04-01", "age": 3, "last3f": 40.1},
        # 同じ名前・生年の違う別の馬(⛔つなげない)
        {"track": "高知", "race_date": "2022-11-05", "race_no": 1, "runner_number": 2,
         "horse_name": "ドウメイ", "birth_date": "2017-05-01", "age": 5, "last3f": 40.2},
        # 名前だけ(生年月日も age も無い)= 鍵も脚質も空
        {"track": "高知", "race_date": "2022-11-05", "race_no": 1, "runner_number": 3,
         "horse_name": "ナマエダケ", "birth_date": None, "age": None, "last3f": None},
    ]
    PAST = [
        {"track": "高知", "race_date": "2022-10-01", "race_no": 2, "runner_number": 1,
         "horse_name": "ツナガル", "birth_date": None, "age": 3},
        {"track": "高知", "race_date": "2022-10-15", "race_no": 3, "runner_number": 1,
         "horse_name": "ツナガル", "birth_date": None, "age": 3},
        {"track": "高知", "race_date": "2022-10-01", "race_no": 2, "runner_number": 2,
         "horse_name": "ドウメイ", "birth_date": None, "age": 3},     # 2019 年生まれ= 別の馬
        {"track": "高知", "race_date": "2022-10-15", "race_no": 3, "runner_number": 2,
         "horse_name": "ドウメイ", "birth_date": None, "age": 3},
        {"track": "高知", "race_date": "2022-10-01", "race_no": 2, "runner_number": 3,
         "horse_name": "ナマエダケ", "birth_date": None, "age": None},
        {"track": "高知", "race_date": "2022-10-15", "race_no": 3, "runner_number": 3,
         "horse_name": "ナマエダケ", "birth_date": None, "age": None},
    ]
    PAST_CORNERS = {("高知", "2022-10-01", 2): _corners("1,3,2,4,5,6,7,8,9,10"),
                    ("高知", "2022-10-15", 3): _corners("1,3,2,4,5,6,7,8,9,10")}

    def _build(self):
        seen = []

        def rows_all(_b, _k, path):
            seen.append(path)
            self.assertIn("/rest/v1/nar_runs?", path, "過去走以外を REST で引いている")
            self.assertIn("age", path.split("&")[0], "過去走の select に age が無い")
            return list(self.PAST) + list(self.RUNS_NOV)

        with mock.patch.object(run_facts, "fetch_races", return_value=self.RACES_NOV), \
                mock.patch.object(run_facts, "fetch_runs", return_value=self.RUNS_NOV), \
                mock.patch.object(run_facts, "fetch_first3f", return_value={}), \
                mock.patch.object(run_facts, "fetch_ticks", return_value={}), \
                mock.patch.object(run_facts, "fetch_corners", return_value=self.PAST_CORNERS), \
                mock.patch.object(run_facts, "rows_all", side_effect=rows_all):
            rows = run_facts.build_window("http://x", "k", "2022-11-01", "2022-11-30")
        return {r["umaban"]: r for r in rows}, seen

    def test_cross_boundary(self):
        rows, seen = self._build()
        self.assertEqual(len(seen), 1)
        r1 = rows[1]
        self.assertEqual(r1["horse_key"], "ツナガル|2019-04-01")
        self.assertEqual((r1["style"], r1["style_n"]), ("逃げ", 2), "楽天→公式の過去走がつながっていない")
        self.assertAlmostEqual(r1["style_p"], 0.1)

    def test_other_birth_year_not_linked(self):
        rows, _ = self._build()
        r2 = rows[2]
        self.assertEqual(r2["horse_key"], "ドウメイ|2017-05-01")
        self.assertEqual((r2["style"], r2["style_n"]), (None, 0), "生年の違う同名馬をつないでいる")

    def test_name_only(self):
        rows, _ = self._build()
        r3 = rows[3]
        self.assertIsNone(r3["horse_key"])
        self.assertEqual((r3["style"], r3["style_n"]), (None, 0), "名前だけでつないでいる")
        self.assertEqual(r3["c1"], 3, "c1 は鍵が無くても焼く")

    def test_rakuten_row_key(self):
        row = facts.build_row(
            race={"track": "高知", "race_date": "2022-10-15", "race_no": 3,
                  "corners": _corners("1,3,2")},
            run={"runner_number": 1, "horse_name": "ツナガル", "birth_date": None, "age": 3, "last3f": None},
            past=[], first3f_cands=None, ticks=None, computed_at="t")
        self.assertEqual(row["horse_key"], "ツナガル|2019")
        self.assertIsNone(row["first3f"], "⛔材料が無いのに first3f を埋めている")

    def test_match_key(self):
        self.assertEqual(run_facts.match_key({"horse_name": "A", "birth_date": "2019-04-01",
                                              "age": 9, "race_date": "2022-11-05"}), ("A", 2019))
        self.assertEqual(run_facts.match_key({"horse_name": "A", "birth_date": None,
                                              "age": 3, "race_date": "2022-10-15"}), ("A", 2019))
        self.assertIsNone(run_facts.match_key({"horse_name": "A", "birth_date": None,
                                               "age": "", "race_date": "2022-10-15"}))
        self.assertIsNone(run_facts.match_key({"horse_name": None, "birth_date": "2019-04-01",
                                               "age": 3, "race_date": "2022-10-15"}))


class DryRun(unittest.TestCase):
    ROWS = [
        {"race_date": "2022-10-15", "track": "高知", "race_no": 3, "umaban": 1,
         "horse_key": "ツナガル|2019", "style": "逃げ", "c1": 1},       # 本番で空 → 埋まる
        {"race_date": "2022-10-15", "track": "高知", "race_no": 3, "umaban": 2,
         "horse_key": "B|2018", "style": "差し", "c1": 2},             # 本番と同じ
        {"race_date": "2022-10-15", "track": "高知", "race_no": 3, "umaban": 3,
         "horse_key": "C|2018", "style": None, "c1": None},            # 本番は先行 → 空
        {"race_date": "2022-10-15", "track": "高知", "race_no": 3, "umaban": 4,
         "horse_key": None, "style": "追込", "c1": 4},                 # 本番は差し → 別の値
        {"race_date": "2022-10-15", "track": "高知", "race_no": 4, "umaban": 1,
         "horse_key": "D|2019", "style": None, "c1": 1},               # 本番に無い
    ]
    OLD = {
        ("2022-10-15", "高知", 3, 1): {"style": None, "horse_key": None},
        ("2022-10-15", "高知", 3, 2): {"style": "差し", "horse_key": "B|2018"},
        ("2022-10-15", "高知", 3, 3): {"style": "先行", "horse_key": None},
        ("2022-10-15", "高知", 3, 4): {"style": "差し", "horse_key": None},
        ("2022-10-15", "高知", 9, 9): {"style": None, "horse_key": None},   # 本番にだけ有る
    }

    def test_diff_counts(self):
        c = run_facts.diff_counts(self.ROWS, self.OLD)
        self.assertEqual((c["rows"], c["old"], c["new"], c["gone"]), (5, 4, 1, 1))
        self.assertEqual((c["style_diff"], c["style_fill"], c["style_drop"], c["style_change"]), (3, 1, 1, 1))
        self.assertEqual((c["hk"], c["hk_fill"]), (4, 2))
        self.assertEqual((c["style"], c["c1"]), (3, 4))

    def test_same_rows_zero_diff(self):
        old = {(r["race_date"], r["track"], r["race_no"], r["umaban"]):
               {"style": r["style"], "horse_key": r["horse_key"]} for r in self.ROWS}
        c = run_facts.diff_counts(self.ROWS, old)
        self.assertEqual((c["style_diff"], c["new"], c["gone"], c["hk_fill"]), (0, 0, 0, 0))

    def test_dry_run_does_not_write(self):
        out = io.StringIO()
        with mock.patch.object(run_facts, "build_window", return_value=self.ROWS), \
                mock.patch.object(run_facts, "fetch_existing", return_value=self.OLD) as fe, \
                mock.patch.object(run_facts, "upsert", side_effect=AssertionError("ドライランで書いた")), \
                redirect_stdout(out):
            rc = run_facts.run("http://x", "k", "2022-10-01", "2022-10-31", apply_=False)
        self.assertEqual(rc, 0)
        self.assertEqual(fe.call_count, 1)
        log = out.getvalue()
        self.assertIn("style 違う 3", log)
        self.assertIn("horse_key 埋まる 4", log)
        self.assertIn("差の合計", log)

    def test_apply_does_not_read_existing(self):
        with mock.patch.object(run_facts, "build_window", return_value=self.ROWS), \
                mock.patch.object(run_facts, "fetch_existing", side_effect=AssertionError("apply で差を読んだ")), \
                mock.patch.object(run_facts, "upsert", return_value=(201, "")) as up, \
                redirect_stdout(io.StringIO()):
            rc = run_facts.run("http://x", "k", "2022-10-01", "2022-10-31", apply_=True)
        self.assertEqual(rc, 0)
        self.assertEqual(up.call_count, 1)


if __name__ == "__main__":
    unittest.main()

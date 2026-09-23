# -*- coding: utf-8 -*-
"""監査 #21 案 乙: profiles の二重書き・番号の埋め・同名表・news の馬リンク(⛔通信なし)

  py -3.12 -m unittest tests.test_s21_horse_profiles
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "pipeline"), os.path.join(HERE, "..", "cloud")):
    sys.path.insert(0, p)

import load_nar_official as L  # noqa: E402
import horse_ledger as HL  # noqa: E402
import horse_homonyms as HH  # noqa: E402
import news_writer as NW  # noqa: E402


def _h(name, date, no, bd=None, sire="父", runner=1, **kw):
    h = {"track": "浦和", "race_date": date, "race_no": no, "runner_number": runner, "horse_name": name,
         "sex": "牡", "age": 3, "sire": sire, "dam": "母", "owner": "馬主", "finish": 1}
    if bd is not None:
        h["birth_date"] = bd
    h.update(kw)
    return h


def _doc(horses):
    return {"races": [], "horses": horses, "payouts": [], "source_snapshot_hash": "x"}


class Dedup(unittest.TestCase):
    def test_profiles_keep_homonyms_apart(self):
        docs = [("2026-09-01", "a", _doc([_h("シンドラー", "2026-09-01", 1, "2016-04-01", sire="甲"),
                                          _h("シンドラー", "2026-09-02", 2, "2022-03-03", sire="乙", runner=2)]))]
        dedup, _ = L.build_dedup(docs)
        self.assertEqual(len(dedup["horses"]), 1)                 # nar_horses は今のまま 1 名 1 行(新しい走が勝つ)
        self.assertEqual(dedup["horses"]["シンドラー"]["sire"], "乙")
        prof = dedup["profiles"]
        self.assertEqual(set(prof), {("シンドラー", "2016-04-01"), ("シンドラー", "2022-03-03")})
        self.assertEqual(prof[("シンドラー", "2016-04-01")]["sire"], "甲")
        self.assertNotIn("code", prof[("シンドラー", "2016-04-01")])   # code は送らない(null で消さない)

    def test_no_birth_date_not_in_profiles(self):
        docs = [("1", "a", _doc([_h("ア", "2026-09-01", 1), _h("イ", "2026-09-01", 1, "", runner=2),
                                 _h("ウ", "2026-09-01", 1, "2020/01/01", runner=3)]))]
        dedup, _ = L.build_dedup(docs)
        self.assertEqual(dedup["profiles"], {})
        self.assertEqual(len(dedup["horses"]), 3)

    def test_newer_run_wins_within_same_horse(self):
        docs = [("1", "a", _doc([_h("ア", "2026-09-02", 1, "2020-01-01", sire="新"),
                                 _h("ア", "2026-09-01", 1, "2020-01-01", sire="旧")]))]
        dedup, _ = L.build_dedup(docs)
        self.assertEqual(dedup["profiles"][("ア", "2020-01-01")]["sire"], "新")

    def test_only_choices_and_keys(self):
        self.assertIn("profiles", L.TABLES)
        self.assertEqual(L.KEYS["profiles"], ("nar_horse_profiles", "horse_name,birth_date"))


class Upsert404(unittest.TestCase):
    def _run(self, codes):
        calls = []

        def fake(url, key, table, conflict, rows):
            calls.append(table)
            return codes.get(table, 201), "msg"
        dedup = {k: {} for k in L.TABLES}
        dedup["horses"] = {"ア": {"horse_name": "ア"}}
        dedup["profiles"] = {("ア", "2020-01-01"): {"horse_name": "ア", "birth_date": "2020-01-01"}}
        logs = []
        orig = L.upsert
        L.upsert = fake
        try:
            rc = L.upsert_all("u", "k", dedup, only="horses", log=logs.append), \
                L.upsert_all("u", "k", dedup, only="profiles", log=logs.append)
        finally:
            L.upsert = orig
        return rc, calls, logs

    def test_missing_profiles_table_is_skipped(self):
        rc, calls, logs = self._run({"nar_horse_profiles": 404})
        self.assertEqual(rc, (0, 0))
        self.assertEqual(sum("HTTP404" in x for x in logs), 1)    # 警告は 1 行だけ

    def test_other_errors_still_fail(self):
        rc, _, _ = self._run({"nar_horse_profiles": 400})
        self.assertEqual(rc, (0, 1))
        rc, _, _ = self._run({"nar_horses": 404})                 # profiles 以外の 404 は今までどおり失敗
        self.assertEqual(rc[0], 1)


class LedgerCodes(unittest.TestCase):
    def test_profile_code_rows(self):
        codes = [{"code": "1", "horse_name": "ア", "birth_date": "2020-01-01"},
                 {"code": "2", "horse_name": "イ", "birth_date": "2020-01-01"},
                 {"code": "3", "horse_name": "イ", "birth_date": "2020-01-01"},      # 番号 2 つ= 埋めない
                 {"code": "4", "horse_name": "ウ", "birth_date": None}]              # 生年月日なし= 使わない
        profs = [{"horse_name": "ア", "birth_date": "2020-01-01"}, {"horse_name": "イ", "birth_date": "2020-01-01"},
                 {"horse_name": "ウ", "birth_date": "2021-01-01"}, {"horse_name": "ア", "birth_date": "2018-01-01"}]
        self.assertEqual(HL.profile_code_rows(profs, codes),
                         [{"horse_name": "ア", "birth_date": "2020-01-01", "code": "1"}])

    def test_fill_skips_when_table_missing(self):
        class E(Exception):
            code = 404

        def boom(*a, **k):
            raise E("404")
        self.assertEqual(HL.fill_profile_codes("u", "k", [], True, read=boom), 0)

    def test_fill_writes(self):
        got = []
        rc = HL.fill_profile_codes(
            "u", "k", [{"code": "1", "horse_name": "ア", "birth_date": "2020-01-01"}], True,
            read=lambda *a: [{"horse_name": "ア", "birth_date": "2020-01-01"}],
            write=lambda url, key, t, c, rows: (got.append((t, c, rows)) or (201, "")))
        self.assertEqual(rc, 0)
        self.assertEqual(got[0][:2], ("nar_horse_profiles", "horse_name,birth_date"))


class Homonyms(unittest.TestCase):
    def test_birth_year(self):
        self.assertEqual(HH.birth_year("2026-09-01", 5, "2021-04-02"), 2021)
        self.assertEqual(HH.birth_year("2019-12-31", 3, None), 2016)
        self.assertIsNone(HH.birth_year("2019-12-31", None, None))
        self.assertIsNone(HH.birth_year("2019-12-31", 0, ""))

    def test_from_pairs_and_merge(self):
        pairs = [("ア", 2016), ("ア", 2022), ("イ", 2019), ("イ", 2020), ("ウ", 2020), ("ウ", 2020)]
        self.assertEqual(HH.homonyms_from_pairs(pairs), ["ア", "イ"])
        merge = HH.merge_map({"イ": [[2019, 2020]], "壊れ": "x"})
        self.assertEqual(HH.homonyms_from_pairs(pairs, merge), ["ア"])
        self.assertEqual(HH.merge_map([1, 2]), {})

    def test_overlapping_periods_are_one_horse(self):
        # 馬齢の書き誤り: 同じ時期に 2 生年= 1 頭。期間が離れた 2 生年= 同名の別馬
        typo = [("ア", 2020, "2023-01-05"), ("ア", 2020, "2024-06-01"), ("ア", 2019, "2023-08-10")]
        apart = [("イ", 2010, "2012-04-01"), ("イ", 2010, "2016-03-01"), ("イ", 2020, "2023-05-01"),
                 ("イ", 2019, "2023-06-01")]                         # 2019/2020 は重なる= 1 頭・2010 と合わせ 2 頭
        self.assertEqual(HH.homonyms_from_pairs(typo + apart), ["イ"])
        def g(f, last, banei=False, bds=()):
            return {"first": f, "last": last, "banei": banei, "bds": set(bds)}
        self.assertEqual(HH.count_horses([g("2012-04-01", "2016-03-01"), g("2023-05-01", "2023-05-01"),
                                          g("2023-01-01", "2023-06-01")]), 2)
        runs = {"ア": [{"race_date": "2023-01-05", "age": 3}, {"race_date": "2023-08-10", "age": 4},
                       {"race_date": "2024-06-01", "birth_date": "2020-03-01"}],
                "イ": [{"race_date": "2012-04-01", "age": 2}, {"race_date": "2023-05-01", "birth_date": "2020-01-01"}]}
        self.assertEqual(HH.confirm_additions(["ア", "イ"], runs.get), ["イ"])

    def test_banei_and_birth_dates_not_merged(self):
        # viewer dry-run の 3 例: ばんえいと平地で同時期に走る別馬= 期間が重なっても同名として残す
        pairs = []
        for n in ("オトコギ", "シンドラー", "タカラシップ"):
            pairs += [(n, 2018, "2023-01-05", "帯広", None), (n, 2018, "2024-03-01", "帯広", None),
                      (n, 2020, "2023-06-01", "浦和", None), (n, 2020, "2024-01-01", "浦和", None)]
        # 両群とも生年月日があって値が違う= 期間が重なっても別馬
        pairs += [("エ", 2020, "2023-01-05", "大井", "2020-04-01"), ("エ", 2021, "2023-06-01", "大井", "2021-05-01")]
        # 平地どうし・一方に生年月日が無い(馬齢の書き誤り)= 1 頭
        pairs += [("オ", 2020, "2023-01-05", "大井", "2020-04-01"), ("オ", 2020, "2023-12-01", "大井", "2020-04-01"),
                  ("オ", 2019, "2023-06-01", "大井", None)]
        self.assertEqual(HH.homonyms_from_pairs(pairs), ["エ", "オトコギ", "シンドラー", "タカラシップ"])
        runs = {"シンドラー": [{"track": "帯広", "race_date": "2023-01-05", "age": 5},
                               {"track": "浦和", "race_date": "2023-06-01", "birth_date": "2020-04-01"}]}
        self.assertEqual(HH.confirm_additions(["シンドラー"], runs.get), ["シンドラー"])

    def test_daily_additions(self):
        runs = [{"horse_name": "ア", "birth_date": "2022-03-03", "age": 4, "race_date": "2026-09-23"},
                {"horse_name": "イ", "birth_date": "2021-01-01", "age": 5, "race_date": "2026-09-23"},
                {"horse_name": "既", "birth_date": "2021-01-01", "age": 5, "race_date": "2026-09-23"}]
        profs = [{"horse_name": "ア", "birth_date": "2016-04-01"}, {"horse_name": "ア", "birth_date": "2022-03-03"},
                 {"horse_name": "イ", "birth_date": "2021-01-01"}]
        self.assertEqual(HH.daily_additions(runs, profs, ["既"]), ["ア"])
        self.assertEqual(HH.daily_additions(runs, profs, [], HH.merge_map({"ア": [[2016, 2022]]})), [])


class NewsLink(unittest.TestCase):
    def _nar(self, homos, runs, horses=1):
        def nar(path):
            if path.startswith("nar_meta"):
                return [{"value": homos}] if homos is not None else []
            if path.startswith("nar_runs"):
                return runs
            if path.startswith("nar_horses"):
                return [{"horse_name": "x"}] * horses
            return []
        return nar

    def test_not_homonym_keeps_nar(self):
        out = NW.relate({"horses": ["ア"]}, nar=self._nar([], []))
        self.assertEqual(out[0]["path"], "/horse/" + NW._q("nar:ア"))

    def test_homonym_gets_nary(self):
        runs = [{"race_date": "2026-09-23", "age": 4, "birth_date": None}]
        out = NW.relate({"horses": ["ア"], "dates": ["2026-09-23"]}, nar=self._nar(["ア"], runs))
        self.assertEqual(out[0]["path"], "/horse/" + NW._q("nary:2022:ア"))
        out = NW.relate({"horses": ["ア"]}, nar=self._nar(["ア"], [{"race_date": "2026-09-23", "birth_date": "2021-05-01"}]),
                        date="2026-09-23")
        self.assertEqual(out[0]["path"], "/horse/" + NW._q("nary:2021:ア"))

    def test_homonym_undecided_no_link(self):
        self.assertEqual(NW.relate({"horses": ["ア"]}, nar=self._nar(["ア"], [])), [])     # 日付なし
        two = [{"race_date": "2026-09-23", "birth_date": "2021-01-01"}, {"race_date": "2026-09-23", "birth_date": "2016-01-01"}]
        self.assertEqual(NW.relate({"horses": ["ア"], "dates": ["2026-09-23"]}, nar=self._nar(["ア"], two)), [])

    def test_meta_unreadable_falls_back_to_nar(self):
        out = NW.relate({"horses": ["ア"]}, nar=self._nar(None, []))
        self.assertEqual(out[0]["path"], "/horse/" + NW._q("nar:ア"))


if __name__ == "__main__":
    unittest.main()

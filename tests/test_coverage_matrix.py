# -*- coding: utf-8 -*-
"""§238c 網羅表の**数え方**の検算。標準ライブラリだけ・**通信ゼロ**(固定入力)。

  py -3.12 -m unittest discover -s tests -p "test_coverage_matrix.py"

確かめるのは=
  ①枡の単位= 場 × 年月・知らない場は枡を作らない・レースの行が無い走は数えない
  ②母数= payout/votes はレース数・それ以外は出走数。派生表の行が無い走は 0% 側(⛔推定で埋めない)
  ③母数 0 は None(「欠けて 0%」と区別する)
  ④出どころの内訳= official / rakuten / kochi_legacy / unknown
  ⑤月の並び(ym_add / ym_range / ym_bounds)と 枡の差し替え(merge_cells)
  ⑥年ごとの区切り(year_groups)・索引の年の足し算(merge_years / build_index)
  ⑦読みの出直し= 6 回・10/20/40/60/90/120 秒・駄目なら ReadFailed(⛔途中の結果を捨てない)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud.coverage_matrix import (COLS, RETRY_WAITS, ReadFailed,             # noqa: E402
                                   build_index, count_month, get, merge_cells,
                                   merge_years, rate, src_of, venue_of, year_groups,
                                   ym_add, ym_bounds, ym_range)

RACES = [
    {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "source": "official"},
    {"track": "大井", "race_date": "2026-08-01", "race_no": 2, "source": "rakuten"},
    {"track": "高知", "race_date": "2026-08-02", "race_no": 1, "source": "kochi_legacy"},
    {"track": "謎場", "race_date": "2026-08-03", "race_no": 1, "source": "official"},
]
RUNS = [
    {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "runner_number": 1,
     "finish": 1, "time_sec": 70.0, "last3f": 38.0, "body_weight": 480},
    {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "runner_number": 2,
     "finish": 2, "time_sec": 70.5, "last3f": None, "body_weight": None},
    {"track": "大井", "race_date": "2026-08-01", "race_no": 2, "runner_number": 1,
     "finish": None, "time_sec": None, "last3f": None, "body_weight": 450},
    {"track": "高知", "race_date": "2026-08-02", "race_no": 1, "runner_number": 1,
     "finish": 3, "time_sec": 71.0, "last3f": None, "body_weight": None},
    # ⛔レースの行が無い走(8-09)は枡に入れない
    {"track": "大井", "race_date": "2026-08-09", "race_no": 9, "runner_number": 1,
     "finish": 1, "time_sec": 70.0, "last3f": 38.0, "body_weight": 480},
]
FACTS = [
    {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "umaban": 1,
     "c1": 3, "style": "先行", "first3f": 36.2, "win_odds_close": 2.1},
    {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "umaban": 2,
     "c1": None, "style": "", "first3f": None, "win_odds_close": 5.0},
]
PAYOUTS = [
    {"track": "大井", "race_date": "2026-08-01", "race_no": 1, "payouts": [{"t": "win", "y": 240}]},
    {"track": "大井", "race_date": "2026-08-01", "race_no": 2, "payouts": []},       # 空は「無い」
]
VOTES = [{"track": "高知", "race_date": "2026-08-02", "race_no": 1, "votes": {"win": 100}}]


class Cells(unittest.TestCase):
    def setUp(self):
        self.cells = count_month("2026-08", RACES, RUNS, FACTS, PAYOUTS, VOTES)
        self.by = dict((c["v"], c) for c in self.cells)

    def test_venues(self):
        self.assertEqual([c["v"] for c in self.cells], ["ooi", "kochi"])   # 北から・謎場は作らない
        self.assertTrue(all(c["ym"] == "2026-08" for c in self.cells))

    def test_counts(self):
        self.assertEqual((self.by["ooi"]["races"], self.by["ooi"]["runs"]), (2, 3))
        self.assertEqual((self.by["kochi"]["races"], self.by["kochi"]["runs"]), (1, 1))

    def test_run_rates(self):
        r = self.by["ooi"]["r"]
        self.assertEqual(r["finish"], round(100 * 2 / 3, 1))
        self.assertEqual(r["time"], round(100 * 2 / 3, 1))
        self.assertEqual(r["last3f"], round(100 * 1 / 3, 1))
        self.assertEqual(r["weight"], round(100 * 2 / 3, 1))

    def test_fact_rates_missing_is_zero_side(self):
        r = self.by["ooi"]["r"]
        self.assertEqual(r["c1"], round(100 * 1 / 3, 1))          # 派生表の行が無い走は 0% 側
        self.assertEqual(r["style"], round(100 * 1 / 3, 1))       # style='' は無い扱い
        self.assertEqual(r["first3f"], round(100 * 1 / 3, 1))
        self.assertEqual(r["odds_close"], round(100 * 2 / 3, 1))
        self.assertEqual(self.by["kochi"]["r"]["c1"], 0.0)        # ⛔空欄でなく 0%

    def test_race_rates(self):
        self.assertEqual(self.by["ooi"]["r"]["payout"], 50.0)     # 空の payouts は数えない
        self.assertEqual(self.by["ooi"]["r"]["votes"], 0.0)
        self.assertEqual(self.by["kochi"]["r"]["votes"], 100.0)
        self.assertEqual(self.by["kochi"]["r"]["payout"], 0.0)

    def test_all_cols_present(self):
        for c in self.cells:
            self.assertEqual(sorted(c["r"]), sorted(COLS))

    def test_src(self):
        self.assertEqual(self.by["ooi"]["src"], {"official": 1, "rakuten": 1})
        self.assertEqual(self.by["kochi"]["src"], {"kochi_legacy": 1})

    def test_no_races(self):
        self.assertEqual(count_month("2026-08", [], RUNS, FACTS, PAYOUTS, VOTES), [])


class Bits(unittest.TestCase):
    def test_rate(self):
        self.assertIsNone(rate(0, 0))                 # 母数 0 は None
        self.assertEqual(rate(0, 5), 0.0)             # 欠けは 0%
        self.assertEqual(rate(1, 3), 33.3)

    def test_src_of(self):
        self.assertEqual(src_of("nar_official_csv"), "official")
        self.assertEqual(src_of("rakuten"), "rakuten")
        self.assertEqual(src_of("kb_archive"), "rakuten")
        self.assertEqual(src_of("kochi_legacy"), "kochi_legacy")
        self.assertEqual(src_of(None), "unknown")

    def test_venue_of(self):
        self.assertEqual(venue_of("帯広ば"), "obihiro")
        self.assertEqual(venue_of("大井"), "ooi")
        self.assertIsNone(venue_of("謎場"))

    def test_months(self):
        self.assertEqual(ym_add("2026-01", -1), "2025-12")
        self.assertEqual(ym_add("2026-12", 1), "2027-01")
        self.assertEqual(ym_range("2025-11", "2026-02"),
                         ["2025-11", "2025-12", "2026-01", "2026-02"])
        self.assertEqual(ym_range("2026-03", "2026-03"), ["2026-03"])
        self.assertEqual(ym_bounds("2026-12"), ("2026-12-01", "2027-01-01"))
        self.assertEqual(ym_bounds("2026-02"), ("2026-02-01", "2026-03-01"))

    def test_merge_cells(self):
        old = [{"v": "ooi", "ym": "2026-07", "races": 1}, {"v": "ooi", "ym": "2026-08", "races": 1}]
        new = [{"v": "ooi", "ym": "2026-08", "races": 2}, {"v": "kochi", "ym": "2026-08", "races": 3}]
        got = merge_cells(old, new)
        self.assertEqual([(c["v"], c["ym"], c["races"]) for c in got],
                         [("ooi", "2026-07", 1), ("ooi", "2026-08", 2), ("kochi", "2026-08", 3)])


class Years(unittest.TestCase):
    """⛔年が終わるごとに焼くための区切りと、索引の年の足し算。"""

    def test_year_groups(self):
        self.assertEqual(year_groups(["2014-11", "2014-12", "2015-01", "2015-02"]),
                         [("2014", ["2014-11", "2014-12"]), ("2015", ["2015-01", "2015-02"])])
        self.assertEqual(year_groups(["2026-09"]), [("2026", ["2026-09"])])
        self.assertEqual(year_groups([]), [])

    def test_merge_years_keeps_old(self):
        # ⛔前に焼いた年(2014)を今回数えていなくても索引から消さない
        self.assertEqual(merge_years(["2014", "2015"], ["2016"]), ["2014", "2015", "2016"])
        self.assertEqual(merge_years([], ["2015", "2015"]), ["2015"])
        self.assertEqual(merge_years(None, None), [])

    def test_build_index(self):
        idx = build_index("2026-09-22T09:00+09:00", "2026-09", ["2014", "2015"])
        self.assertEqual(idx["years"], ["2014", "2015"])
        self.assertEqual(idx["keys"], ["coverage:v1:2014", "coverage:v1:2015"])
        self.assertEqual((idx["from"], idx["to"]), ("2014-01", "2026-09"))
        self.assertEqual(idx["cols"], COLS)


class Retry(unittest.TestCase):
    """⛔9/21 の事故= 3 回で諦めて途中の結果を全部捨てた。6 回・10〜120 秒に直した。"""

    def test_waits(self):
        self.assertEqual(RETRY_WAITS, [10, 20, 40, 60, 90, 120])

    def test_get_retries_then_succeeds(self):
        import cloud.coverage_matrix as cm
        slept, calls = [], [0]

        class Res:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return False

            def read(self_inner):
                return b'[{"ok": 1}]'

        def fake_urlopen(_req, timeout=None):
            self.assertEqual(timeout, cm.READ_TIMEOUT)      # ⛔待ちは 120 秒
            calls[0] += 1
            if calls[0] < 4:
                raise OSError("The read operation timed out")
            return Res()

        real = cm.urllib.request.urlopen
        cm.urllib.request.urlopen = fake_urlopen
        try:
            got = get("https://x", "k", "/rest/v1/nar_meta", sleep=slept.append)
        finally:
            cm.urllib.request.urlopen = real
        self.assertEqual(got, [{"ok": 1}])
        self.assertEqual(slept, [10, 20, 40])               # 3 回待って 4 回目で通った

    def test_get_raises_after_six_retries(self):
        import cloud.coverage_matrix as cm
        slept = []

        def fake_urlopen(_req, timeout=None):
            raise OSError("The read operation timed out")

        real = cm.urllib.request.urlopen
        cm.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(ReadFailed):
                get("https://x", "k", "/rest/v1/nar_meta", sleep=slept.append)
        finally:
            cm.urllib.request.urlopen = real
        self.assertEqual(slept, RETRY_WAITS)                # 7 回試して 6 回待つ


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""§239a 分析タブの事実(pipeline/karte.py・cloud/karte_facts.py)。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -X utf8 -m unittest tests.test_karte -v

確かめるのは=
  ①各事実の関数を小さな作り物のデータで(出遅れ・位置の幅・粘り/失速・使われ方・相性・相手関係・調子)
  ②材料が無いときは None(⛔0 で埋めない)
  ③能力検査・取消・除外・取りやめ(着なし)を走数に数えない
  ④その日と未来の走を数えない(発走前の値だけ)
  ⑤便= 同名で生年の違う馬をつながない・ドライランは書かない・割合表の数え方
  ⑥追加の 4 列(出遅れた走の位置・脚質の回数・今回の間隔・ベストの着順)
  ⑦run_facts が出走前の行(着順・通過が空)を焼ける= 夕方に明日の脚質を先に焼く段の前提
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import karte                                            # noqa: E402
from cloud import karte_facts, run_facts                              # noqa: E402

D = "2026-09-22"


def R(d, track="浦和", no=1, finish=5, **kw):
    r = {"track": track, "race_date": d, "race_no": no, "umaban": 1, "finish": finish, "note": None}
    r.update(kw)
    return r


class Select(unittest.TestCase):
    def test_today_and_future_are_not_counted(self):
        runs = [R(D, finish=1), R("2026-09-23", finish=1), R("2026-09-21", finish=2)]
        self.assertEqual([r["race_date"] for r in karte.past_starts(runs, D)], ["2026-09-21"])
        self.assertEqual(karte.runs_30d(karte.past_starts(runs, D), D), 1)

    def test_noken_is_not_counted(self):
        runs = [R("2026-09-03", noken=True), R("2026-09-02", race_name="能力検査"), R("2026-09-01", race_name="能検")]
        self.assertEqual(karte.past_starts(runs, D), [])
        self.assertEqual(karte.runs_30d(karte.past_starts(runs, D), D), 0)
        self.assertEqual(karte.run_of_year(karte.past_starts(runs, D), D), 1)

    def test_scratch_and_cancelled_race_are_not_counted(self):
        runs = [R("2026-09-10", finish=None, note="出走取消"), R("2026-09-09", finish=None, note="競走除外"),
                R("2026-09-08", finish=None, note=None)]                      # 取りやめ(着なし・注記なし)
        self.assertEqual(karte.past_starts(runs, D), [])

    def test_stopped_is_a_start(self):
        runs = [R("2026-09-10", finish=None, note="競走中止")]
        self.assertEqual(len(karte.past_starts(runs, D)), 1)


class Start(unittest.TestCase):
    def test_late_only_recorded_runs(self):
        st = karte.past_starts([R("2026-09-%02d" % d, late=v) for d, v in
                                ((20, True), (15, None), (10, False), (5, True), (1, None), (2, True))], D)
        # 直近 5 走= 20,15,10,5,2 → 記録あり 20(T),10(F),5(T),2(T)= 3/4(1 日の走は 6 走目)
        self.assertEqual(karte.late_count(st), (3, 4))

    def test_late_runs_positions(self):
        st = karte.past_starts([R("2026-09-%02d" % d, late=v) for d, v in
                                ((20, True), (15, None), (10, False), (5, True), (2, True), (1, True))], D)
        self.assertEqual(karte.late_runs(st), [1, 4, 5], "位置は記録の無い走も含めた直近 5 走の順番(6 走目は入れない)")
        st = karte.past_starts([R("2026-09-01", late=False)], D)
        self.assertEqual(karte.late_runs(st), [], "記録はあって出遅れ 0 回= 空の並び")
        self.assertIsNone(karte.late_runs(karte.past_starts([R("2026-09-01", late=None)], D)))
        self.assertIsNone(karte.late_runs([]))

    def test_late_empty_is_none(self):
        self.assertEqual(karte.late_count([]), (None, None))
        st = karte.past_starts([R("2026-09-01", late=None)], D)
        self.assertEqual(karte.late_count(st), (None, None), "記録が 1 本も無いのに 0 と書いた")

    def test_late_next_pct_lookup(self):
        t = {"buckets": [{"k": 0, "pct": 6.1}, {"k": 1, "pct": 13.0}, {"k": 2, "pct": 24.5}, {"k": 3, "pct": 40.2}]}
        self.assertEqual(karte.late_next_pct(0, t), 6.1)
        self.assertEqual(karte.late_next_pct(5, t), 40.2, "3 回以上は同じ段")
        self.assertIsNone(karte.late_next_pct(1, None), "表が無いのに値を出した")
        self.assertIsNone(karte.late_next_pct(None, t))


class LateAllAndPace(unittest.TestCase):
    """§274 通算の出遅れ・ふだんの間隔・近ごろの間隔。"""

    def test_late_all_not_cut_at_5(self):
        st = karte.past_starts([R("2026-09-%02d" % d, late=v) for d, v in
                                ((20, True), (15, None), (10, False), (5, True), (2, True), (1, True))], D)
        self.assertEqual(karte.late_count(st), (3, 4))
        self.assertEqual(karte.late_all(st), (4, 5), "6 走目を数えていない・記録なしを分母に入れた")
        self.assertEqual(karte.late_all([]), (None, None))
        self.assertEqual(karte.late_all(karte.past_starts([R("2026-09-01", late=None)], D)), (None, None))

    def test_late_all_skips_noken_and_scratch(self):
        st = karte.past_starts([R("2026-09-10", late=True), R("2026-09-05", late=True, noken=True),
                                R("2026-09-03", finish=None, note="出走取消", late=True), R("2026-09-01", late=False)], D)
        self.assertEqual(karte.late_all(st), (1, 2))

    def test_gaps_recent_newest_first_max5(self):
        days = ["2026-09-15", "2026-09-01", "2026-08-25", "2026-08-04", "2026-07-21", "2026-07-07", "2026-06-01"]
        st = karte.past_starts([R(d) for d in days], D)
        self.assertEqual(karte.gaps_recent(st), [14, 7, 21, 14, 14])
        self.assertEqual(karte.gap_usual(karte.gaps_recent(st)), 14, "奇数個の中央値")

    def test_gap_usual_even_floor(self):
        self.assertEqual(karte.gap_usual([7, 21, 14, 28]), 17, "偶数個= (14+21)//2")
        self.assertEqual(karte.gap_usual([7, 8]), 7)

    def test_gap_usual_needs_two(self):
        st = karte.past_starts([R("2026-09-01"), R("2026-08-01")], D)
        self.assertEqual(karte.gaps_recent(st), [31])
        self.assertIsNone(karte.gap_usual(karte.gaps_recent(st)))
        self.assertEqual(karte.gaps_recent(karte.past_starts([R("2026-09-01")], D)), [])
        self.assertIsNone(karte.gap_usual([]))

    def test_gaps_skip_noken(self):
        st = karte.past_starts([R("2026-09-15"), R("2026-09-08", race_name="能力検査"),
                                R("2026-09-01", finish=None, note="出走取消"), R("2026-08-18"), R("2026-08-04")], D)
        self.assertEqual(karte.gaps_recent(st), [28, 14], "能検・取消を間隔の走に数えた")
        self.assertEqual(karte.gap_usual([28, 14]), 21)

    def test_build_row_columns(self):
        runs = [R("2026-09-15", late=True), R("2026-09-01", late=False), R("2026-08-18", late=None), R("2026-08-04")]
        row = karte.build_row({"race_date": D, "track": "浦和", "race_no": 1, "umaban": 1, "horse_name": "x",
                               "horse_key": "x|2021"}, runs, [], None, None, "t")
        self.assertEqual((row["late_all_n"], row["late_all_den"], row["gap_usual_days"], row["gaps_recent"]),
                         (1, 2, 14, [14, 14, 14]))


class Style(unittest.TestCase):
    def test_pos_range(self):
        st = karte.past_starts([R("2026-09-%02d" % d, c1=c) for d, c in
                                ((20, 3), (15, None), (10, 7), (5, 4), (3, 5), (1, 12))], D)
        self.assertEqual(karte.pos_range(st), ("3〜7", 4), "直近 5 走の外(12)を入れた")
        self.assertEqual(karte.pos_range(karte.past_starts([R("2026-09-01", c1=5)], D)), ("5", 1))
        self.assertEqual(karte.pos_range([]), (None, None))

    def test_lead_hold_and_fade_window(self):
        st = karte.past_starts([
            R("2026-09-01", finish=2, c1=1, c4=2),
            R("2026-08-01", finish=6, c1=3, c4=3),
            R("2026-07-01", finish=None, note="競走中止", c1=2, c4=1),           # 中止= 残れなかった/失速
            R("2026-06-01", finish=1, c1=5, c4=5),
            R("2025-09-21", finish=1, c1=1, c4=1),                               # ⛔365 日より前
        ], D)
        self.assertEqual(karte.lead_hold(st, D), (1, 3))
        self.assertEqual(karte.fade4(st, D), (2, 3))

    def test_style_counts_same_runs_as_style(self):
        runs = [R("2026-09-%02d" % d, c1=c, n1=10) for d, c in ((20, 1), (15, 3), (10, 6), (5, 9), (3, 5), (1, 1))]
        runs.append(R("2025-09-01", c1=1, n1=10))                                # ⛔365 日より前
        runs.append(R("2026-09-18", track="園田", c1=10, n1=10))                  # 浦和が 3 走以上= 園田は外れる
        runs.append(R(D, c1=1, n1=10))                                           # ⛔今日
        self.assertEqual(karte.style_counts(runs, "浦和", D), {"逃": 1, "先": 1, "差": 2, "追": 1})
        self.assertIsNone(karte.style_counts([R("2026-09-01")], "浦和", D), "位置が無いのに 0 回と書いた")
        self.assertIsNone(karte.style_counts([], "浦和", D))

    def test_style_rates_empty_is_none(self):
        st = karte.past_starts([R("2026-09-01", finish=2)], D)                 # c1/c4 の読めない走だけ
        self.assertEqual(karte.lead_hold(st, D), (None, None))
        self.assertEqual(karte.fade4(st, D), (None, None))
        st = karte.past_starts([R("2026-09-01", finish=2, c1=8, c4=8)], D)
        self.assertEqual(karte.lead_hold(st, D), (0, 0), "材料はあるが 3 番手以内が無い= 分母 0")
        self.assertIsNone(karte.ratio(0, 0))


class Usage(unittest.TestCase):
    def test_runs_30d_window(self):
        st = karte.past_starts([R("2026-08-23"), R("2026-08-22"), R("2026-09-21")], D)
        self.assertEqual(karte.runs_30d(st, D), 2, "30 日前の日は入る・31 日前は入らない")

    def test_gap_days(self):
        st = karte.past_starts([R("2026-09-01"), R("2026-09-15", finish=None, note="出走取消"), R("2026-08-01")], D)
        self.assertEqual(karte.gap_days(st, D), 21, "取消を前走にした")
        self.assertIsNone(karte.gap_days([], D))

    def test_run_of_year(self):
        st = karte.past_starts([R("2026-01-01"), R("2025-12-31"), R("2026-05-01")], D)
        self.assertEqual(karte.run_of_year(st, D), 3)

    def test_since_layoff(self):
        # 181 日空いた後の 2 走目が今回
        st = karte.past_starts([R("2025-01-10"), R("2025-09-01"), R("2025-09-30")], "2025-10-20")
        self.assertEqual(karte.since_layoff(st, "2025-10-20"), 3)
        st = karte.past_starts([R("2026-03-26")], D)                             # 180 日= 休み明けではない
        self.assertIsNone(karte.since_layoff(st, D))
        st = karte.past_starts([R("2026-03-25")], D)                             # 181 日= 今回が休み明け 1 戦目
        self.assertEqual(karte.since_layoff(st, D), 1)
        self.assertIsNone(karte.since_layoff([], D), "初出走を休み明けにした")


class Condition(unittest.TestCase):
    def test_course_split_south_only(self):
        st = karte.past_starts([R("2026-09-01", track="大井", finish=1), R("2026-08-01", track="船橋", finish=4),
                                R("2026-07-01", track="浦和", finish=3), R("2026-06-01", track="園田", finish=1)], D)
        self.assertEqual(karte.course_split(st), ((1, 1), (1, 2)))
        st = karte.past_starts([R("2026-06-01", track="園田", finish=1)], D)
        self.assertEqual(karte.course_split(st), ((None, None), (None, None)), "南関の走が無いのに 0 と書いた")

    def test_time_split_1700(self):
        st = karte.past_starts([R("2026-09-01", post_time="1700", finish=1), R("2026-08-01", post_time="1659", finish=2),
                                R("2026-07-01", post_time=None, finish=1),
                                R("2026-06-01", track="金沢", post_time="1900", finish=1)], D)
        self.assertEqual(karte.time_split(st), ((1, 1), (1, 1)))


class HeadToHead(unittest.TestCase):
    def test_h2h(self):
        mine = karte.past_starts([
            R("2026-09-01", no=3, finish=2), R("2026-08-01", no=4, finish=5), R("2026-07-01", no=5, finish=None, note="競走中止"),
            R("2026-06-01", no=6, finish=1, track="園田"), R("2026-05-01", no=7, finish=3)], D)
        opp = [R("2026-09-01", no=3, finish=4), R("2026-08-01", no=4, finish=1), R("2026-07-01", no=5, finish=2),
               R("2026-06-01", no=6, finish=2, track="園田"), R("2026-05-01", no=7, finish=3),
               R(D, no=1, finish=1)]
        got = karte.h2h(mine, [(4, "相手", karte.past_starts(opp, D))])
        self.assertEqual(got, ([{"umaban": 4, "horse_name": "相手", "w": 1, "l": 1}], 1, 1),
                         "中止・南関の外・同着・今日を数えた")
        self.assertEqual(karte.h2h(mine, [(4, "相手", [])]), (None, None, None))


class Form(unittest.TestCase):
    def test_form(self):
        st = karte.past_starts([
            R("2026-09-01", finish=4, pop=2, time=86.0, win_time=85.2),
            R("2026-08-01", finish=1, pop=3, time=85.0, win_time=85.0),
            R("2026-07-01", finish=3, pop=6, time=84.5, win_time=84.1),
            R("2026-06-01", finish=1, pop=1, time=84.0, win_time=84.0),
            R("2026-05-01", finish=2, pop=1, time=90.0, win_time=None),                # 1 着のタイムが無い
            R("2025-01-01", finish=1, pop=9, time=80.0, win_time=80.0),                # ⛔365 日より前
        ], D)
        f = karte.form(st, D)
        self.assertEqual((f["best_margin"], f["best_margin_date"], f["best_finish"]), (0.0, "2026-08-01", 1),
                         "同じ差は新しい方")
        self.assertEqual(f["recent3_margin"], 0.4)                                   # (0.8+0.0+0.4)/3
        self.assertEqual(f["pop_beat"], (2, 5))                                      # 8/1(1<3)・7/1(3<6)
        self.assertEqual(f["win_conv"], (2, 4))

    def test_form_no_year_is_none(self):
        st = karte.past_starts([R("2025-01-01", finish=1, pop=9, time=80.0, win_time=80.0)], D)
        f = karte.form(st, D)
        self.assertEqual(f, {"best_margin": None, "best_margin_date": None, "best_finish": None,
                             "recent3_margin": None, "pop_beat": (None, None), "win_conv": (None, None)})

    def test_margin_unreadable(self):
        self.assertIsNone(karte.margin_sec(R("2026-09-01", finish=2, time=80.0, win_time=81.0)), "1 着より速い")
        self.assertIsNone(karte.margin_sec(R("2026-09-01", finish=None, note="競走中止", time=80.0, win_time=79.0)))
        self.assertEqual(karte.round1(0.25), 0.3)


class Row(unittest.TestCase):
    ENTRY = {"race_date": D, "track": "浦和", "race_no": 1, "umaban": 3, "horse_name": "テスト馬",
             "horse_key": "テスト馬|2021-04-01"}

    def test_columns(self):
        row = karte.build_row(self.ENTRY, [], [], None, None, "2026-09-22T08:00:00+09:00")
        self.assertEqual(tuple(row), karte.COLUMNS, "表の列と並びが違う")

    def test_debut_is_not_zero_filled(self):
        row = karte.build_row(self.ENTRY, [], [], "差し", None, "t")
        for c in ("late_n", "late_den", "late_next_pct", "late_runs", "style_counts", "lead_hold_rate", "lead_hold_n",
                  "pos_var", "oi_n", "night_n", "h2h", "h2h_w", "best_margin", "best_finish", "recent3_margin",
                  "pop_beat_n", "win_conv_n", "since_layoff", "gap_days",
                  "late_all_n", "late_all_den", "gap_usual_days", "gaps_recent"):
            self.assertIsNone(row[c], c)
        self.assertEqual((row["runs_30d"], row["run_of_year"], row["style"]), (0, 1, "差し"))

    def test_no_key_all_none(self):
        row = karte.build_row(dict(self.ENTRY, horse_key=None), [R("2026-09-01", finish=1)], [], None, None, "t")
        self.assertIsNone(row["runs_30d"])
        self.assertIsNone(row["run_of_year"])

    def test_future_runs_do_not_leak(self):
        runs = [R("2026-09-21", finish=1, late=True, c1=1, c4=1, pop=3, time=80.0, win_time=80.0, post_time="1330")]
        future = runs + [R("2026-09-25", finish=1, late=True, c1=1, c4=1, pop=9, time=70.0, win_time=70.0),
                         R(D, finish=1, late=True)]
        a = karte.build_row(self.ENTRY, runs, [], None, None, "t")
        b = karte.build_row(self.ENTRY, future, [], None, None, "t")
        self.assertEqual(a, b)


class LateTable(unittest.TestCase):
    def test_targets_and_counts(self):
        runs = [R("2025-08-01", late=True), R("2025-08-15", late=True), R("2025-08-20", late=None),
                R("2025-09-10", late=True),                   # 直前 3 走で記録 2・出遅れ 2 → 段 2・出遅れた
                R("2025-09-20", late=False),                  # 直前= 9/10,8/20,8/15,8/1 → 記録 3・出遅れ 3 → 段 3
                R("2025-09-25", track="園田", late=True),     # ⛔南関の外= その走にしない(直前の 5 走には入る)
                R("2025-10-01", late=None),                   # ⛔その走に記録なし
                R("2025-10-05", late=False, noken=True)]      # ⛔能力検査
        got = karte.late_targets(runs, "2025-09-01", "2026-08-31")
        self.assertEqual(got, [(True, 2), (False, 3)])
        b = karte.late_table_counts(got + [(False, 0), (True, 0), (False, 0), (False, 0)])
        self.assertEqual([(x["k"], x["n"], x["late"], x["pct"]) for x in b],
                         [(0, 4, 1, 25.0), (1, 0, 0, None), (2, 1, 1, 100.0), (3, 1, 0, 0.0)])

    def test_selftest(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(karte.selftest(), 0)


def _entries():
    base = {"track": "浦和", "race_date": D, "race_no": 1, "age": 5}
    return [dict(base, runner_number=1, horse_name="テスト馬", birth_date="2021-04-01"),
            dict(base, runner_number=2, horse_name="相手馬", birth_date="2020-03-01", age=6)]


def _history():
    h = {"track": "浦和", "race_no": 2, "finish_note": None, "popularity": 2}
    return [
        dict(h, race_date="2026-09-01", runner_number=3, horse_name="テスト馬", birth_date="2021-04-01", age=5,
             finish=1, time_sec=85.0),
        dict(h, race_date="2026-09-01", runner_number=5, horse_name="相手馬", birth_date="2020-03-01", age=6,
             finish=3, time_sec=85.6),
        # ⛔同じ名前で生年の違う馬(つながない)
        dict(h, race_date="2026-08-01", runner_number=4, horse_name="テスト馬", birth_date="2015-04-01", age=11,
             finish=1, time_sec=84.0),
        # 楽天期(生年月日なし・age から生年 2021)= つながる
        dict(h, race_date="2022-10-01", track="大井", runner_number=6, horse_name="テスト馬", birth_date=None, age=1,
             finish=2, time_sec=70.0),
    ]


class Job(unittest.TestCase):
    def patches(self):
        return [
            mock.patch.object(karte_facts, "fetch_entries", return_value=_entries()),
            mock.patch.object(karte_facts, "fetch_history", return_value=_history()),
            mock.patch.object(karte_facts, "fetch_kb", return_value={("浦和", "2026-09-01", 2, "テスト馬"): "出遅れ"}),
            mock.patch.object(karte_facts, "fetch_run_facts", return_value={
                (D, "浦和", 1, 1): {"style": "先行"},
                ("2026-09-01", "浦和", 2, 3): {"c1": 2, "n1": 12, "c4": 1, "n4": 12}}),
            mock.patch.object(karte_facts, "fetch_races", return_value={("浦和", "2026-09-01", 2): {"post_time": "1400"}}),
            mock.patch.object(karte_facts, "fetch_win_times", return_value={("浦和", "2026-09-01", 2): 85.0}),
        ]

    def test_build_day(self):
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            rows = karte_facts.build_day("b", "k", D, ["浦和"], {"buckets": [{"k": 1, "pct": 13.0}]}, now="t")
        finally:
            for p in ps:
                p.stop()
        a, b = rows
        self.assertEqual((a["horse_key"], a["style"], a["late_n"], a["late_den"], a["late_next_pct"]),
                         ("テスト馬|2021-04-01", "先行", 1, 1, 13.0))
        self.assertEqual((a["run_of_year"], a["runs_30d"], a["since_layoff"]), (2, 1, 2), "生年違いの 8/1 をつないだ")
        self.assertEqual((a["oi_n"], a["other3_n"], a["day_n"], a["night_n"]), (1, 1, 1, 0))
        self.assertEqual(a["h2h"], [{"umaban": 2, "horse_name": "相手馬", "w": 1, "l": 0}])
        self.assertEqual((b["h2h_w"], b["h2h_l"]), (0, 1))
        self.assertEqual((a["pos_var"], a["lead_hold_n"], a["best_margin"], a["best_margin_date"]),
                         ("2", 1, 0.0, "2026-09-01"))
        self.assertEqual((a["late_runs"], a["gap_days"], a["best_finish"]), ([1], 21, 1))
        self.assertEqual(a["style_counts"], {"逃": 1, "先": 0, "差": 0, "追": 0}, "p= 2/12 の 1 走だけ")
        self.assertIsNone(b["style_counts"], "位置の無い馬に 0 回と書いた")

    def test_dry_run_does_not_write(self):
        ps = self.patches() + [
            mock.patch.object(karte_facts, "fetch_late_table", return_value=None),
            mock.patch.object(karte_facts, "env", return_value=("b", "k")),
        ]
        for p in ps:
            p.start()
        try:
            with mock.patch.object(karte_facts, "upsert") as up, \
                    mock.patch.object(sys, "argv", ["karte_facts.py", "--date", D, "--track", "浦和"]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    self.assertEqual(karte_facts.main(), 0)
                up.assert_not_called()
        finally:
            for p in ps:
                p.stop()
        self.assertIn("テスト馬", buf.getvalue())
        self.assertIn("ドライラン", buf.getvalue())

    def test_track_outside_south_is_refused(self):
        with mock.patch.object(sys, "argv", ["karte_facts.py", "--track", "高知"]), \
                mock.patch.object(karte_facts, "env") as e:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(karte_facts.main(), 2)
            e.assert_not_called()


class RunFactsPreRace(unittest.TestCase):
    """④ 夕方に明日の出走表の行へ脚質を焼く= run_facts.build_window が着順・通過・上がり・オッズの空な行を焼けること。"""

    def test_pre_race_rows(self):
        tomorrow = "2026-09-23"
        races = [{"track": "浦和", "race_date": tomorrow, "race_no": 1, "corners": None, "source": "nar_official_csv"}]
        runs = [{"track": "浦和", "race_date": tomorrow, "race_no": 1, "runner_number": 1, "horse_name": "マエノウマ",
                 "birth_date": "2021-04-01", "age": 5, "last3f": None},
                {"track": "浦和", "race_date": tomorrow, "race_no": 1, "runner_number": 2, "horse_name": "シンバ",
                 "birth_date": "2023-04-01", "age": 3, "last3f": None}]                # 初出走= 過去走なし
        past = [{"track": "浦和", "race_date": "2026-09-%02d" % d, "race_no": 2, "runner_number": 1,
                 "horse_name": "マエノウマ", "birth_date": "2021-04-01", "age": 5} for d in (1, 10)]
        corners = {("浦和", "2026-09-01", 2): [{"name": "1角", "order": "1,2,3,4,5,6,7,8,9,10"}],
                   ("浦和", "2026-09-10", 2): [{"name": "1角", "order": "1,2,3,4,5,6,7,8,9,10"}]}
        with mock.patch.object(run_facts, "fetch_races", return_value=races),                 mock.patch.object(run_facts, "fetch_runs", return_value=runs),                 mock.patch.object(run_facts, "fetch_first3f", return_value={}),                 mock.patch.object(run_facts, "fetch_ticks", return_value={}),                 mock.patch.object(run_facts, "fetch_corners", return_value=corners),                 mock.patch.object(run_facts, "rows_all", return_value=past + runs):
            rows = {r["umaban"]: r for r in run_facts.build_window("http://x", "k", tomorrow, tomorrow)}
        a, b = rows[1], rows[2]
        self.assertEqual((a["style"], a["style_n"]), ("逃げ", 2), "明日の行に過去走の脚質が付かない")
        for c in ("c1", "n1", "c2", "n2", "c3", "n3", "c4", "n4", "first3f", "first3f_src", "last3f", "win_odds_close"):
            self.assertIsNone(a[c], c + " は出走前なので空のはず")
        self.assertEqual((b["style"], b["style_n"]), (None, 0))
        self.assertEqual((a["horse_key"], a["src"]), ("マエノウマ|2021-04-01", "official"))


if __name__ == "__main__":
    unittest.main()

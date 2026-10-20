# -*- coding: utf-8 -*-
"""トップの帯 cloud/top_band.py の数え方(休み明け・距離・前走の場・移籍の内訳・取消除外・前走の選び方)を確かめる(DB なし)。"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "cloud"))
_spec = importlib.util.spec_from_file_location("top_band", os.path.join(ROOT, "cloud", "top_band.py"))
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)

D = "2026-10-15"


def run(track, rno, u, name, note=None, bd=None, date=D):
    return {"track": track, "race_date": date, "race_no": rno, "runner_number": u, "horse_name": name,
            "birth_date": bd, "finish_note": note, "margin": None}


class TopBandTest(unittest.TestCase):
    def test_counts_and_edges(self):
        runs = [run("川崎", 1, 1, "A"), run("川崎", 1, 2, "B"), run("川崎", 1, 3, "C"),
                run("川崎", 1, 4, "D", note="出走取消"), run("園田", 2, 5, "E")]
        races = {("川崎", 1): {"post_time": "14:45", "distance_m": 1400}, ("園田", 2): {"post_time": "1110", "distance_m": 820}}
        prevs = {("川崎", 1, 1): {"track": "川崎", "race_date": "2026-08-06", "race_no": 3},   # 70 日ちょうど= 休み明け
                 ("川崎", 1, 2): {"track": "浦和", "race_date": "2026-08-07", "race_no": 1},   # 69 日= 休み明けでない・別の場
                 ("川崎", 1, 3): None,                                                    # 前走なし= どれにも入らない
                 ("川崎", 1, 4): {"track": "大井", "race_date": "2026-01-01", "race_no": 1},   # 取消= 数えない
                 ("園田", 2, 5): {"track": "園田", "race_date": "2026-10-01", "race_no": 2, "finish": "3", "popularity": 2}}
        prev_dist = {("川崎", "2026-08-06", 3): 1000, ("浦和", "2026-08-07", 1): 1001, ("大井", "2026-01-01", 1): 2000,
                     ("園田", "2026-10-01", 2): 1230}
        got = tb.count_band(D, runs, races, prevs, prev_dist, [])
        self.assertEqual(got["n"], {"transfer": 0, "layoff": 1, "dist": 2, "venue": 1})
        self.assertEqual(got["rows"]["layoff"], [["1445", "川崎", 1, 1, "A", 70, None, None, None]])
        # 発走順(11:10 の園田が先)・399m 差は入らない・400m ちょうどは入る
        self.assertEqual([r[4] for r in got["rows"]["dist"]], ["E", "A"])
        self.assertEqual(got["rows"]["dist"][0][5:], [1230, 820, 3, 2, None])   # 末尾= 前走の着順・人気(10/20)
        self.assertEqual(got["rows"]["dist"][1][7:], [None, None, None])        # 前走の行に無い値は null
        self.assertEqual(got["rows"]["venue"], [["1445", "川崎", 1, 2, "B", "浦和", None, None, None]])

    def test_jra_newer(self):
        # 10/20 ラヴァグロウ: 地方の最後は 2024-07-31(門別)・中央の最後は 2026-09-06 → 中央が前走(中 5 週)
        r = {"race_date": "2026-10-20", "birth_date": "2020-05-09"}
        p = {"race_date": "2024-07-31"}
        h = {"last_jra_date": "2026-09-06", "birth_date": "2020-05-09"}
        self.assertTrue(tb.jra_newer(r, p, h))
        self.assertTrue(tb.jra_newer(r, None, h))                                          # 地方の前走なし
        self.assertFalse(tb.jra_newer(r, {"race_date": "2026-10-01"}, h))                  # 地方の前走のほうが新しい
        self.assertFalse(tb.jra_newer(r, p, dict(h, birth_date="2019-01-01")))             # 生年月日が違えば別の馬
        self.assertFalse(tb.jra_newer(r, p, dict(h, last_jra_date="2026-10-20")))          # 今日以後は前走でない
        self.assertFalse(tb.jra_newer(r, p, dict(h, last_jra_date=None)))

    def test_jra_prev_gives_week_count(self):
        runs = [dict(run("浦和", 11, 11, "L"), birth_date="2020-05-09")]
        races = {("浦和", 11): {"post_time": "1745", "distance_m": 1400}}
        prevs = {("浦和", 11, 11): {"track": "中山", "race_date": "2026-09-06", "race_no": 9, "finish": 14, "popularity": 15, "jra": True}}
        got = tb.count_band(D, runs, races, prevs, {("中山", "2026-09-06", 9): 1200}, [])
        self.assertEqual(got["rows"]["layoff"], [])                      # 44 日= 休み明け(70 日)ではない
        self.assertEqual(got["rows"]["venue"][0][5:], ["中山", 14, 15, "jra_in"])    # 移籍の表に無くても前走が中央なら「中央から」

    def test_transfer_mark_on_rows(self):
        # 今日が移籍後の初戦の馬は、行の末尾に移籍の種類が付く(遠征ではなく所属替えと分けるため・10/20)
        runs = [dict(run("川崎", 1, 1, "A"), birth_date="2022-01-01"), run("川崎", 1, 2, "B")]
        races = {("川崎", 1): {"post_time": "14:45", "distance_m": 1400}}
        prevs = {("川崎", 1, 1): {"track": "船橋", "race_date": "2026-08-06", "race_no": 3, "finish": 2, "popularity": 5},
                 ("川崎", 1, 2): {"track": "船橋", "race_date": "2026-08-06", "race_no": 3}}
        ch = [{"horse_name": "A", "birth_date": "2022-01-01", "kind": "transfer_in"}]
        got = tb.count_band(D, runs, races, prevs, {}, ch)
        self.assertEqual([r[5:] for r in got["rows"]["venue"]], [["船橋", 2, 5, "transfer_in"], ["船橋", None, None, None]])

    def test_transfer_breakdown_one_per_horse(self):
        ch = [{"horse_name": "X", "birth_date": "2022-04-01", "kind": "transfer_in"},
              {"horse_name": "X", "birth_date": "2022-04-01", "kind": "jra_in"},          # 同じ馬= 中央からに 1 回
              {"horse_name": "Y", "birth_date": "2021-05-01", "kind": "transfer_in"},
              {"horse_name": "Z", "birth_date": "2020-03-01", "kind": "stable_change"},
              {"horse_name": "W", "birth_date": "2020-03-01", "kind": "owner_change"}]    # 馬主替わりは数えない
        got = tb.count_band(D, [], {}, {}, {}, ch)
        self.assertEqual(got["n"]["transfer"], 3)
        self.assertEqual(got["transfer"], {"jra": 1, "area": 1, "stable": 1})

    def test_pick_prev_birth_date_and_order(self):
        r = run("川崎", 1, 1, "同名", bd="2022-01-01")
        cands = [{"race_date": D, "birth_date": "2022-01-01", "track": "川崎", "race_no": 1},          # 今日= 前走でない
                 {"race_date": "2026-10-01", "birth_date": "2019-01-01", "track": "大井", "race_no": 2},  # 別の馬(生年が違う)
                 {"race_date": "2026-09-25", "birth_date": None, "track": "浦和", "race_no": 1},          # 生年月日の無い行= 別の馬とみる
                 {"race_date": "2026-09-20", "birth_date": "2022-01-01", "track": "船橋", "race_no": 3}]
        self.assertEqual(tb.pick_prev(r, cands)["track"], "船橋")
        self.assertIsNone(tb.pick_prev(r, cands[:3]))

    def test_head_value_night_drops_transfer(self):
        got = {"n": {"transfer": 5, "layoff": 1, "dist": 2, "venue": 3}, "transfer": {"jra": 1, "area": 3, "stable": 1}}
        night = tb.head_value("2026-10-17", "b", got, with_transfer=False)
        self.assertEqual(night["n"], {"transfer": None, "layoff": 1, "dist": 2, "venue": 3})
        self.assertIsNone(night["transfer"])
        self.assertEqual(got["n"]["transfer"], 5)                      # 元の数は壊さない
        day = tb.head_value("2026-10-17", "b", got)
        self.assertEqual((day["n"]["transfer"], day["transfer"]["area"], day["date"]), (5, 3, "2026-10-17"))


if __name__ == "__main__":
    unittest.main()

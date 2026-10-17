# -*- coding: utf-8 -*-
"""B3 区切りの勝利 cloud/milestones.py の固定テスト(通信なし)。"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
import milestones as M  # noqa: E402

HTML = """<div>佐　野　　遥　久</div><div>（サノ　ハルク）</div><td>所属</td><td>川崎</td>
<td>生涯成績</td><td>地方競馬</td><td>128</td><td>153</td><td>206</td><td>193</td><td>185</td><td>1087</td><td>1952</td>
<td>6.6%</td><td>14.4%</td><td>JRA</td><td>0</td><td>1</td>"""


def run(d, r, h="", f=1, note=None, t="浦和"):
    return {"race_date": d, "race_no": r, "track": t, "horse_name": h, "finish": f, "finish_note": note}


class T(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(M.parse_mark(HTML), {"name": "佐野 遥久", "area": "川崎", "wins": 128, "starts": 1952, "years": {}})

    def test_next(self):
        self.assertEqual(M.next_mark(128), 200)
        self.assertEqual(M.next_mark(99), 100)
        self.assertEqual(M.next_mark(100), 200)

    def test_kth_and_doc(self):
        # 公式 102 勝= 区切り 100 は新しい順 3 番目の勝ち。そのあと 4 走(1 つは取消)→ 何戦目= 1952 − 3
        wins = [run("2026-10-10", 3, "A"), run("2026-10-12", 5, "B"), run("2026-10-12", 9, "C")]
        rows = wins + [run("2026-10-11", 1, f=4), run("2026-10-12", 7, f=None, note="出走取消")]
        today = dt.date(2026, 10, 17)
        people = [{"lic": "1", "short": "佐野遥"}, {"lic": "2", "short": "山本聡"}]
        marks = {"1": {"name": "佐野 遥久", "area": "川崎", "wins": 102, "starts": 1952, "years": {"2026": [39, 621]}},
                 "2": {"name": "山本 聡哉", "area": "岩手", "wins": 199, "starts": 9000, "years": {"2026": [50, 400]}}}
        yw = {"佐野遥": 39, "山本聡": 49}            # 山本聡 は今年の勝ち数が合わない= あとだけ
        doc, miss = M.build_doc(today, people, marks, {"佐野遥": [{"t": "浦和", "r": 1}], "山本聡": [{"t": "盛岡", "r": 2}]},
                                lambda s, k: M.kth_from_wins(wins, k),
                                lambda s, hit: sum(1 for x in rows if M.run_key(x) > M.run_key(hit) and M.counts_as_start(x)),
                                yw, made="x")
        self.assertEqual(miss, [])
        self.assertEqual([(j["short"], j["rem"], len(j["today"]), j["dup"]) for j in doc["jockeys"]],
                         [("山本聡", 1, 0, True), ("佐野遥", 98, 1, False)])
        self.assertEqual(len(doc["recent"]), 1)
        r = doc["recent"][0]
        self.assertEqual((r["m"], r["date"], r["r"], r["h"], r["nth"]), (100, "2026-10-10", 3, "A", 1952 - 3))

    def test_map_shorts(self):
        # 名簿の略称と走りの略称が違う人(山本聡紀→山本紀・本田正重→本田重・所 蛍)と、同じ略称を 2 人が取る場合
        people = [{"lic": "a", "short": "山本聡"}, {"lic": "b", "short": "山本聡"}, {"lic": "c", "short": "本田正"},
                  {"lic": "d", "short": "所蛍"}, {"lic": "e", "short": "藤田凌"}, {"lic": "f", "short": "藤田凌"}]
        marks = {"a": {"name": "山本 聡哉", "years": {"2026": [80, 1]}}, "b": {"name": "山本 聡紀", "years": {"2026": [20, 1]}},
                 "c": {"name": "本田 正重", "years": {"2026": [30, 1]}}, "d": {"name": "所 蛍", "years": {"2026": [5, 1]}},
                 "e": {"name": "藤田 凌駕", "years": {"2026": [7, 1]}}, "f": {"name": "藤田 凌", "years": {"2026": [8, 1]}}}
        yw = {"山本聡": 80, "山本紀": 20, "本田重": 30, "所　蛍": 5, "藤田駕": 7, "藤田凌": 8}
        mp, why = M.map_shorts(people, marks, yw, 2026)
        self.assertEqual(mp, {"a": "山本聡", "b": "山本紀", "c": "本田重", "d": "所　蛍", "e": "藤田駕", "f": "藤田凌"})
        mp2, why2 = M.map_shorts(people[:2], {"a": marks["a"], "b": {"name": "山本 聡也", "years": {"2026": [80, 1]}}}, yw, 2026)
        self.assertEqual((mp2, why2), ({}, {"a": "shared", "b": "shared"}))

    def test_foreign_name(self):
        self.assertIn("ゴンサ", M.name_candidates("Ｆ．ゴンサルベス", "Ｆ．"))

    def test_parse_years(self):
        h = HTML + "<td>2026年 地方競馬成績</td><td>1番人気</td>" + "".join("<td>%d</td>" % n for n in range(7)) +             "<td>合計</td><td>39</td><td>47</td><td>71</td><td>63</td><td>63</td><td>338</td><td>621</td>"
        self.assertEqual(M.parse_mark(h)["years"], {"2026": [39, 621]})

    def test_old_achievement_dropped(self):
        wins = [run("2026-07-01", 3)]
        doc, _ = M.build_doc(dt.date(2026, 10, 17), [{"lic": "1", "short": "x"}],
                             {"1": {"wins": 100, "starts": 500, "years": {"2026": [1, 9]}}}, {},
                             lambda s, k: M.kth_from_wins(wins, k), lambda s, h: 0, {"x": 1})
        self.assertEqual(doc["recent"], [])

    def test_rides(self):
        got = M.rides_from_rows([{"track": "高知", "race_no": 2, "horse_name": "A", "jockey": "赤岡修", "finish_note": None},
                                 {"track": "高知", "race_no": 1, "horse_name": "B", "jockey": "赤岡修", "finish_note": "出走取消"}],
                                [{"track": "高知", "race_no": 2, "post_time": "15:00"}])
        self.assertEqual(got, {"赤岡修": [{"t": "高知", "r": 2, "h": "A", "post": "15:00"}]})


if __name__ == "__main__":
    unittest.main()

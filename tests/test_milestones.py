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
        self.assertEqual(M.parse_mark(HTML), {"name": "佐野 遥久", "area": "川崎", "wins": 128, "starts": 1952})

    def test_next(self):
        self.assertEqual(M.next_mark(128), 200)
        self.assertEqual(M.next_mark(99), 100)
        self.assertEqual(M.next_mark(100), 200)

    def test_kth_and_doc(self):
        # 公式 102 勝= 区切り 100 は新しい順 3 番目の勝ち。そのあと 4 走(1 つは取消)→ 何戦目= 1952 − 3
        wins = [run("2026-10-10", 3, "A"), run("2026-10-12", 5, "B"), run("2026-10-12", 9, "C")]
        rows = wins + [run("2026-10-11", 1, f=4), run("2026-10-12", 7, f=None, note="出走取消")]
        today = dt.date(2026, 10, 17)
        people = [{"lic": "1", "short": "佐野遥", "dup": False}, {"lic": "2", "short": "山本聡", "dup": True}]
        marks = {"1": {"name": "佐野 遥久", "area": "川崎", "wins": 102, "starts": 1952},
                 "2": {"name": "山本 聡哉", "area": "岩手", "wins": 199, "starts": 9000}}
        doc, miss = M.build_doc(today, people, marks, {"佐野遥": [{"t": "浦和", "r": 1}], "山本聡": [{"t": "盛岡", "r": 2}]},
                                lambda s, k: M.kth_from_wins(wins, k),
                                lambda s, hit: sum(1 for x in rows if M.run_key(x) > M.run_key(hit) and M.counts_as_start(x)),
                                made="x")
        self.assertEqual(miss, [])
        self.assertEqual([(j["short"], j["rem"], len(j["today"])) for j in doc["jockeys"]], [("山本聡", 1, 0), ("佐野遥", 98, 1)])
        self.assertEqual(len(doc["recent"]), 1)
        r = doc["recent"][0]
        self.assertEqual((r["m"], r["date"], r["r"], r["h"], r["nth"]), (100, "2026-10-10", 3, "A", 1952 - 3))

    def test_old_achievement_dropped(self):
        wins = [run("2026-07-01", 3)]
        doc, _ = M.build_doc(dt.date(2026, 10, 17), [{"lic": "1", "short": "x", "dup": False}],
                             {"1": {"wins": 100, "starts": 500}}, {}, lambda s, k: M.kth_from_wins(wins, k), lambda s, h: 0)
        self.assertEqual(doc["recent"], [])

    def test_rides(self):
        got = M.rides_from_rows([{"track": "高知", "race_no": 2, "horse_name": "A", "jockey": "赤岡修", "finish_note": None},
                                 {"track": "高知", "race_no": 1, "horse_name": "B", "jockey": "赤岡修", "finish_note": "出走取消"}],
                                [{"track": "高知", "race_no": 2, "post_time": "15:00"}])
        self.assertEqual(got, {"赤岡修": [{"t": "高知", "r": 2, "h": "A", "post": "15:00"}]})


if __name__ == "__main__":
    unittest.main()

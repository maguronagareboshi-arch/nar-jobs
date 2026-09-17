# -*- coding: utf-8 -*-
"""§202 cloud/ai_last_today.py= 取りに行く条件・DB に無い体重だけ重ねる・NULL で上書きしない。"""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
import ai_last_today as A  # noqa: E402

DAY = "2026-09-16"
NOW = dt.datetime(2026, 9, 16, 14, 50, tzinfo=A.JST)


def run(track, no, uma, bw=None, note=None):
    return {"track": track, "race_date": DAY, "race_no": no, "runner_number": uma, "body_weight": bw, "finish_note": note}


class T(unittest.TestCase):
    def test_waiting_races(self):
        races = [{"track": "名古屋", "race_date": DAY, "race_no": 4, "post_time": "1550"},   # 60 分前・未そろい= 待つ
                 {"track": "名古屋", "race_date": DAY, "race_no": 5, "post_time": "16:25"},   # 95 分前= まだ
                 {"track": "名古屋", "race_date": DAY, "race_no": 3, "post_time": "15:04"},   # 14 分前= 締切の後
                 {"track": "園田", "race_date": DAY, "race_no": 9, "post_time": "15:30"},     # そろっている
                 {"track": "園田", "race_date": DAY, "race_no": 10, "post_time": "15:40"},    # 空は取消だけ= そろっている
                 {"track": "園田", "race_date": DAY, "race_no": 11, "post_time": ""}]         # 発走時刻なし
        runs = [run("名古屋", 4, 1, 480), run("名古屋", 4, 2), run("名古屋", 5, 1), run("名古屋", 3, 1),
                run("園田", 9, 1, 450), run("園田", 10, 1, 460), run("園田", 10, 2, None, "出走取消"), run("園田", 11, 1)]
        self.assertEqual(A.waiting_races(races, runs, NOW), [("名古屋", 4)])
        self.assertEqual(A.waiting_races(races, runs, NOW + dt.timedelta(minutes=45)), [("名古屋", 4), ("名古屋", 5)])   # 15 分前ちょうど・50 分前
        self.assertEqual(A.waiting_races(races, runs, NOW + dt.timedelta(minutes=46)), [("名古屋", 5)])

    def test_overlay_rows(self):
        horses = [{"track": "名古屋", "race_date": DAY, "race_no": 4, "runner_number": 1, "body_weight": 480, "body_weight_change": 2},
                  {"track": "名古屋", "race_date": DAY, "race_no": 4, "runner_number": 2, "body_weight": 455, "body_weight_change": None},
                  {"track": "名古屋", "race_date": DAY, "race_no": 4, "runner_number": 3, "body_weight": None, "body_weight_change": None},
                  {"track": "名古屋", "race_date": "2026-09-17", "race_no": 1, "runner_number": 1, "body_weight": 470, "body_weight_change": 0}]
        rows, new = A.overlay_rows(horses, DAY, {("名古屋", 4, 2), ("名古屋", 4, 3)})
        self.assertEqual([(r["runner_number"], r["body_weight"]) for r in rows], [(1, 480), (2, 455)])   # 体重なし・別の日は出さない
        self.assertEqual(new, [("名古屋", 4, 2)])                                                        # DB に無かった走だけ
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.tsv"
            A.write_tsv(p, A.H_COLS, rows)
            self.assertEqual(p.read_text(encoding="utf-8").splitlines(),
                             [f"名古屋\t{DAY}\t4\t1\t480\t2", f"名古屋\t{DAY}\t4\t2\t455\t\\N"])      # 増減の空は NULL
            A.write_tsv(p, A.H_COLS, [])
            self.assertEqual(p.read_text(encoding="utf-8"), "")                                         # 取らない回も空の TSV

    def test_race_rows_and_post_at(self):
        rr = A.race_rows([{"track": "園田", "race_date": DAY, "race_no": 9, "going": "重", "post_time": "15:30"},
                          {"track": "園田", "race_date": DAY, "race_no": 10, "going": "", "post_time": ""}], DAY)
        self.assertEqual([(r["race_no"], r["going"]) for r in rr], [(9, "重")])
        self.assertIsNone(A.post_at(DAY, "発走未定"))
        self.assertEqual(A.post_at(DAY, "9:05").hour, 9)
        self.assertEqual(A.post_at(DAY, "1550").minute, 50)     # 本番と公式 CSV の書き方(コロンなし)


if __name__ == "__main__":
    unittest.main()

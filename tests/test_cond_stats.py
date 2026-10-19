# -*- coding: utf-8 -*-
"""条件で集計 /stats の便 cloud/cond_stats.py の約束(外す規則・期間の端・列の形)を確かめる(DB なし)。
行の形は本番 REST の select と同じ列名(nar_runs / nar_races)・出力の列は試作 proto/build_proto.py と同じ。"""
import datetime as dt
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
_spec = importlib.util.spec_from_file_location("cond_stats", os.path.join(ROOT, "cloud", "cond_stats.py"))
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

# 10/19 段2: 馬名の列 h と dict.h は抜いた(画面は rpc stats_horse_names で引く)
PROTO_COLS = ["d", "r", "u", "dist", "g", "w", "n", "f", "p", "j", "t", "s", "b", "st"]
PROTO_KEYS = ["v", "track", "from", "to", "n", "legend", "dict", "cols"]


def run(date, rno, u, finish, note=None, horse=None):
    return {"race_date": date, "race_no": rno, "runner_number": u, "gate": u, "horse_name": horse or f"馬{rno}-{u}",
            "finish": finish, "finish_note": note, "popularity": u, "jockey": "騎手A", "trainer": "調教師B"}


class FakeRest:
    """REST の select に当日分も返す(サーバー側の絞りが漏れても当日を入れないことを確かめる)。"""
    def __init__(self, races, runs):
        self.races, self.runs, self.nreq = races, runs, 0

    def paged(self, q, order):
        return list(self.races if q.startswith("nar_races") else self.runs)

    def get(self, q):
        return [{"horse_name": "馬1-1", "sire": "父X", "broodmare_sire": "母父Y"}]


class TestCondStats(unittest.TestCase):
    def test_period_ends_yesterday(self):
        today = dt.date(2026, 10, 15)
        self.assertEqual(cs.period(today, "1y"), (dt.date(2025, 10, 15), dt.date(2026, 10, 14)))
        self.assertEqual(cs.period(today, "3y"), (dt.date(2023, 10, 16), dt.date(2026, 10, 14)))

    def test_keep_runs_drops_scratch_exclusion_and_no_winner_race(self):
        runs = [run("2026-10-01", 1, 1, 1), run("2026-10-01", 1, 2, 2),
                run("2026-10-01", 1, 3, None, "出走取消"), run("2026-10-01", 1, 4, None, "競走除外"),
                run("2026-10-01", 1, 5, None, "競走中止"),
                # 不成立(1 着なし)= 全走外す
                run("2026-10-01", 2, 1, None, "競走中止"), run("2026-10-01", 2, 2, None)]
        got = [(x["race_no"], x["runner_number"]) for x in cs.keep_runs(runs)]
        self.assertEqual(got, [(1, 1), (1, 2), (1, 5)])

    def test_build_venue_excludes_today_and_matches_proto_shape(self):
        today = dt.date(2026, 10, 15)
        races = [{"race_date": d, "race_no": 1, "distance_m": 1400, "going": "良", "field_size": 2,
                  "corners": [{"order": "2,1"}, {"order": "1,2"}]} for d in ("2025-10-14", "2025-10-15", "2026-10-14", "2026-10-15")]
        runs = []
        for d in ("2025-10-14", "2025-10-15", "2026-10-14", "2026-10-15"):
            runs += [run(d, 1, 1, 1, horse="馬1-1"), run(d, 1, 2, 2, "", "馬1-2")]
        rest = FakeRest(races, runs)
        out = cs.build_venue(rest, "高知", today)   # 本物の fetch(FakeRest は当日分も返す)
        d1 = out["1y"][0]
        self.assertEqual(list(d1.keys()), PROTO_KEYS)
        self.assertEqual(list(d1["cols"].keys()), PROTO_COLS)
        self.assertNotIn("h", d1["dict"])
        self.assertNotIn("馬1-1", json.dumps(d1, ensure_ascii=False))
        self.assertEqual((d1["from"], d1["to"]), ("2025-10-15", "2026-10-14"))
        self.assertEqual(d1["n"], 4)                      # 2025-10-14(範囲外)と当日 2026-10-15 は入らない
        self.assertEqual(out["1y"][2], "2025-10-15")
        self.assertEqual(d1["cols"]["d"], [0, 0, 364, 364])
        self.assertEqual(d1["cols"]["st"], [0, 1, 0, 1])  # 最後のコーナー 1,2
        self.assertEqual(d1["cols"]["s"], [0, -1, 0, -1])
        self.assertEqual(out["3y"][0]["n"], 6)
        json.loads(out["1y"][1].decode("utf-8"))

    def test_proto_reader_same_cols(self):
        src = open(os.path.join(ROOT, "cloud", "cond_stats.py"), encoding="utf-8").read()
        self.assertIn('"Cache-Control": CACHE', src)
        self.assertEqual(cs.CACHE, "max-age=3600")
        self.assertEqual(cs.BUCKET, "cond-stats")
        self.assertEqual(cs.ROOT, "v1/")
        self.assertEqual(cs.MIME, ["application/json"])
        self.assertEqual(len(cs.VENUES), 15)


if __name__ == "__main__":
    unittest.main()

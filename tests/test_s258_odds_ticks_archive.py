"""§258: odds_archive の単複 nar_odds_ticks(9 点の選び方・パス・2 表の記録)(⛔通信なし)"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))

import odds_archive as oa  # noqa: E402

D = dt.date


def race(track, no, times, start_id, f_last=True):
    rows = []
    for i, t in enumerate(times):
        rows.append({"id": start_id + i, "track": track, "race_date": "2026-09-22", "race_no": no, "t": t,
                     "f": (f_last and i == len(times) - 1)})
    return rows


class Keep(unittest.TestCase):
    def test_before_min(self):
        self.assertEqual(oa.before_min("2030", "20:00"), 30)
        self.assertEqual(oa.before_min("2030", "20:00:59"), 30)
        self.assertIsNone(oa.before_min(None, "20:00"))
        self.assertIsNone(oa.before_min("20:30", "20:00"))
        self.assertIsNone(oa.before_min("203", "20:00"))

    def test_nine_points_2min(self):
        # 16:00〜20:28 の 2 分刻み(135 点)・発走 20:30 → 初回/240/120/60/30/20/10/5 分前/最終= 9 点
        times = ["%02d:%02d" % divmod(16 * 60 + 2 * k, 60) for k in range(135)]
        rows = race("kochi", 7, times, 1000)
        keep = oa.keep_ids(rows, {("kochi", 7): "2030"})
        by_t = {r["t"]: r["id"] for r in rows}
        want = {by_t[t] for t in ["16:00", "16:30", "18:30", "19:30", "20:00", "20:10", "20:20", "20:24", "20:28"]}
        # 5 分前= 20:25 は 20:24 と 20:26 が同点(1 分差)→ id の小さい 20:24
        self.assertEqual(keep, want)
        self.assertEqual(len(keep), 9)

    def test_no_post_time_first_last_only(self):
        rows = race("kochi", 1, ["19:00", "19:02", "19:04", "19:06"], 10)
        self.assertEqual(oa.keep_ids(rows, {}), {10, 13})
        self.assertEqual(oa.keep_ids(rows, {("kochi", 1): ""}), {10, 13})

    def test_last_prefers_f_true(self):
        rows = race("kochi", 1, ["19:00", "19:02", "19:04"], 10, f_last=False)
        rows[1]["f"] = True
        self.assertEqual(oa.keep_ids(rows, {}), {10, 11})

    def test_last_null_f_first_like_postgres_desc(self):
        rows = race("kochi", 1, ["19:00", "19:02", "19:04"], 10, f_last=False)
        rows[0]["f"] = None
        rows[2]["f"] = True
        # order by f desc= NULL が先頭(Postgres)→ 最終は f が NULL の 19:00(= 初回と同じ点)
        self.assertEqual(oa.keep_ids(rows, {}), {10})

    def test_races_separate(self):
        a = race("kochi", 1, ["19:00", "19:02"], 10)
        b = race("kochi", 2, ["19:30", "19:32"], 20)
        c = race("mombetsu", 1, ["19:00", "19:02"], 30)
        self.assertEqual(oa.keep_ids(a + b + c, {}), {10, 11, 20, 21, 30, 31})

    def test_in_chunks(self):
        self.assertEqual(oa.in_chunks([5, 1, 3], 2), [[1, 3], [5]])
        self.assertEqual(oa.in_chunks([]), [])


class PathMeta(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(oa.archive_path(D(2026, 9, 22), oa.TICKS), "nar_odds_ticks/2026/2026-09-22.jsonl.gz")
        self.assertEqual(oa.archive_path(D(2026, 9, 22), oa.TICKS, test=True),
                         "_test/nar_odds_ticks/2026/2026-09-22.jsonl.gz")
        self.assertEqual(oa.archive_path(D(2026, 9, 10)), "nar_odds_full_ticks/2026/2026-09-10.jsonl.gz")

    def test_two_tables_meta_keys(self):
        self.assertEqual(oa.TABLES[oa.TABLE], {"mode": "all", "meta": "odds_archive:v1"})
        self.assertEqual(oa.TABLES[oa.TICKS]["mode"], "thin9")
        self.assertEqual(oa.TABLES[oa.TICKS]["meta"], "odds_archive:nar_odds_ticks:v1")
        self.assertEqual(oa.TABLE_ALIAS["all"], [oa.TABLE, oa.TICKS])

    def test_next_after(self):
        self.assertIsNone(oa.next_after({}))
        self.assertIsNone(oa.next_after(None))
        self.assertEqual(oa.next_after({"2026-07-01": {}, "2026-07-03": {}, "x": 1}), D(2026, 7, 3))

    def test_already_thinned(self):
        full = [{"id": i} for i in (1, 2, 3, 4)]
        f = oa.gz(oa.to_jsonl(full))
        self.assertTrue(oa.already_thinned(oa.summarize(oa.to_jsonl(full[:2])), f)[0])
        self.assertFalse(oa.already_thinned(oa.summarize(oa.to_jsonl(full)), f)[0])
        self.assertFalse(oa.already_thinned(oa.summarize(oa.to_jsonl([{"id": 9}])), f)[0])

    def test_remove_object_only_test(self):
        with self.assertRaises(ValueError):
            oa.remove_object("http://x", "k", "nar_odds_ticks/2026/2026-09-22.jsonl.gz")


if __name__ == "__main__":
    unittest.main()

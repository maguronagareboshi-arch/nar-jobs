"""監査 #28: odds_archive の純粋関数(対象日・JST 境目・照合・小分け)(⛔通信なし)"""
import datetime as dt
import gzip
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))

import odds_archive as oa  # noqa: E402

D = dt.date


class Dates(unittest.TestCase):
    def test_jst_boundary(self):
        utc = dt.timezone.utc
        self.assertEqual(oa.jst_today(dt.datetime(2026, 9, 22, 14, 59, tzinfo=utc)), D(2026, 9, 22))
        self.assertEqual(oa.jst_today(dt.datetime(2026, 9, 22, 15, 0, tzinfo=utc)), D(2026, 9, 23))

    def test_cutoff_same_as_old_sql(self):
        # race_date < current_date - 60
        self.assertEqual(oa.cutoff_date(D(2026, 9, 23)), D(2026, 7, 25))

    def test_pick_oldest_first_and_max(self):
        ds = ["2026-07-24", "2026-07-20", D(2026, 7, 25), "2026-07-22", "2026-07-20"]
        self.assertEqual(oa.pick_dates(ds, D(2026, 9, 23), 3), [D(2026, 7, 20), D(2026, 7, 22), D(2026, 7, 24)])
        self.assertEqual(oa.pick_dates(ds, D(2026, 9, 23), 1), [D(2026, 7, 20)])
        self.assertEqual(oa.pick_dates(ds, D(2026, 9, 23), 0), [])

    def test_boundary_day_excluded(self):
        self.assertEqual(oa.pick_dates([D(2026, 7, 25)], D(2026, 9, 23), 3), [])
        self.assertEqual(oa.pick_dates([D(2026, 7, 24)], D(2026, 9, 23), 3), [D(2026, 7, 24)])

    def test_path(self):
        self.assertEqual(oa.archive_path(D(2026, 9, 10)), "nar_odds_full_ticks/2026/2026-09-10.jsonl.gz")


class Verify(unittest.TestCase):
    rows = [{"id": 5, "track": "ooi", "combos": {"1-2": 3.4}}, {"id": 9, "track": "ooi", "combos": {"1-3": 12.0}}]

    def test_match(self):
        raw = oa.to_jsonl(self.rows)
        ok, _ = oa.verify(oa.summarize(raw), oa.gz(raw))
        self.assertTrue(ok)

    def test_gz_deterministic(self):
        raw = oa.to_jsonl(self.rows)
        self.assertEqual(oa.gz(raw), oa.gz(raw))
        self.assertEqual(gzip.decompress(oa.gz(raw)), raw)

    def test_row_missing(self):
        exp = oa.summarize(oa.to_jsonl(self.rows))
        ok, why = oa.verify(exp, oa.gz(oa.to_jsonl(self.rows[:1])))
        self.assertFalse(ok)
        self.assertIn("行数", why)

    def test_id_differs(self):
        exp = oa.summarize(oa.to_jsonl(self.rows))
        other = [dict(self.rows[0]), dict(self.rows[1], id=10)]
        ok, why = oa.verify(exp, oa.gz(oa.to_jsonl(other)))
        self.assertFalse(ok)
        self.assertIn("id", why)

    def test_content_differs(self):
        exp = oa.summarize(oa.to_jsonl(self.rows))
        other = [dict(self.rows[0]), dict(self.rows[1], combos={"1-3": 12.5})]
        ok, why = oa.verify(exp, oa.gz(oa.to_jsonl(other)))
        self.assertFalse(ok)
        self.assertIn("sha256", why)

    def test_broken_file(self):
        ok, _ = oa.verify(oa.summarize(oa.to_jsonl(self.rows)), b"not gzip")
        self.assertFalse(ok)


class Chunks(unittest.TestCase):
    def test_chunks_le_size(self):
        ids = list(range(1, 12001, 1))
        r = oa.chunk_ranges(ids, 5000)
        self.assertEqual(r, [(1, 5000), (5001, 10000), (10001, 12000)])

    def test_unsorted_and_gaps(self):
        self.assertEqual(oa.chunk_ranges([30, 10, 20, 50, 40], 2), [(10, 20), (30, 40), (50, 50)])

    def test_empty(self):
        self.assertEqual(oa.chunk_ranges([], 5000), [])

    def test_default_5000(self):
        r = oa.chunk_ranges(list(range(5001)))
        self.assertEqual(len(r), 2)


if __name__ == "__main__":
    unittest.main()

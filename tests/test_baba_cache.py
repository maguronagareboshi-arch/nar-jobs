"""baba.rows_cached(2026-11-05 通信量)の試験: 控えを使った読み方が丸ごと読みと同じ行・同じ順になること。"""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cloud import baba  # noqa: E402

TODAY = dt.date(2026, 11, 5)


def make_db():
    rows = []
    for k in range(400):
        d = (TODAY - dt.timedelta(days=k)).isoformat()
        for no in (1, 2):
            for fin in (1, 2, 3):
                rows.append({"track": "園田", "race_date": d, "race_no": no, "finish": fin, "time_sec": 70.0 + fin})
    rows.sort(key=lambda r: (r["race_date"], r["track"], r["race_no"], r["finish"]))
    return rows


class RowsCached(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.calls = []

        def fake_rows_all(base, key, path):
            self.calls.append(path)
            lo = path.split("race_date=gte.")[1].split("&")[0]
            return [dict(r) for r in self.db if r["race_date"] >= lo]
        self._orig = baba.rows_all
        baba.rows_all = fake_rows_all
        self.tmp = tempfile.TemporaryDirectory()
        self._cache = baba.BABA_CACHE

    def tearDown(self):
        baba.rows_all = self._orig
        baba.BABA_CACHE = self._cache
        self.tmp.cleanup()

    def run_once(self, today=TODAY):
        since = (today - dt.timedelta(days=300)).isoformat()
        return baba.rows_cached("u", "k", "t", "/rest/v1/nar_runs?select=x", since, "race_date.asc", today)

    def test_no_cache_is_full_read(self):
        baba.BABA_CACHE = ""
        self.assertEqual(self.run_once(), [r for r in self.db if r["race_date"] >= "2026-01-09"])
        self.assertEqual(len(self.calls), 1)

    def test_second_run_same_rows_and_reads_only_fresh(self):
        baba.BABA_CACHE = self.tmp.name
        first = self.run_once()
        # 2 回目の前に直近の行を直す(読み直しの窓の中)= 直した値が入ること
        for r in self.db:
            if r["race_date"] == TODAY.isoformat():
                r["time_sec"] = 99.0
        second = self.run_once()
        self.assertEqual(len(first), len(second))
        self.assertEqual(second, [r for r in self.db if r["race_date"] >= "2026-01-09"])
        self.assertIn(f"race_date=gte.{(TODAY - dt.timedelta(days=baba.FRESH_DAYS)).isoformat()}", self.calls[-1])

    def test_next_day_reads_whole_again(self):
        baba.BABA_CACHE = self.tmp.name
        self.run_once()
        nxt = TODAY + dt.timedelta(days=1)
        self.run_once(nxt)
        self.assertIn(f"race_date=gte.{(nxt - dt.timedelta(days=300)).isoformat()}", self.calls[-1])


if __name__ == "__main__":
    unittest.main()

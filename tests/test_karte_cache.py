"""karte_facts の控え(2026-11-05 通信量)の試験: 控え+直近の読み直し= 丸ごと読みと同じ行・同じ順。通信ゼロ。"""
import datetime as dt
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cloud import karte_facts as kf  # noqa: E402

TODAY = dt.date(2026, 11, 5)
NAMES = ["アアア", "イイイ", "ウウウ"]


def make_db():
    rows = []
    for k in range(1, 500, 3):
        d = (TODAY - dt.timedelta(days=k)).isoformat()
        for no in (1, 2):
            for i, n in enumerate(NAMES):
                rows.append({"track": "浦和", "race_date": d, "race_no": no, "runner_number": i + 1, "horse_name": n,
                             "finish": i + 1, "time_sec": 80.0 + i, "umaban": i + 1, "start_note": ""})
    return rows


def fake_filter(db, path):
    q = urllib.parse.parse_qsl(path.split("?", 1)[1])
    out = list(db)
    for k, v in q:
        if k != "race_date" and k != "finish":
            continue
        op, val = v.split(".", 1)
        if k == "finish":
            out = [r for r in out if r["finish"] == int(val)]
        elif op == "gte":
            out = [r for r in out if r["race_date"] >= val]
        elif op == "lte":
            out = [r for r in out if r["race_date"] <= val]
        elif op == "in":
            days = {x.strip('"') for x in val.strip("()").split(",")}
            out = [r for r in out if r["race_date"] in days]
    out.sort(key=lambda r: (r["race_date"], r["track"], r["race_no"], r["runner_number"]))
    return [dict(r) for r in out]


class KarteCache(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.calls = []

        def fake_rows_all(base, key, path):
            self.calls.append(path)
            return fake_filter(self.db, path)
        self._orig = (kf.rows_all, kf.KARTE_CACHE, kf._cache_today)
        kf.rows_all = fake_rows_all
        self.today = TODAY
        kf._cache_today = lambda: self.today
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        kf.rows_all, kf.KARTE_CACHE, kf._cache_today = self._orig
        self.tmp.cleanup()

    def full(self, fn, *a):
        kf.KARTE_CACHE = ""
        r = fn("u", "k", *a)
        kf.KARTE_CACHE = self.tmp.name
        return r

    def all_three(self):
        hi = (self.today - dt.timedelta(days=1)).isoformat()
        need = {("浦和", r["race_date"]) for r in self.db}
        return (kf.fetch_history("u", "k", NAMES, hi), kf.fetch_kb("u", "k", NAMES, hi),
                kf.fetch_races("u", "k", need), kf.fetch_win_times("u", "k", need))

    def expect(self):
        kf.KARTE_CACHE = ""
        r = self.all_three()
        kf.KARTE_CACHE = self.tmp.name
        return r

    def test_no_cache_unchanged(self):
        kf.KARTE_CACHE = ""
        self.all_three()
        self.assertFalse(any("gte.2026-10-22" in c for c in self.calls))
        self.assertFalse(os.listdir(self.tmp.name))

    def test_cached_equals_full_and_reads_less(self):
        kf.KARTE_CACHE = self.tmp.name
        first = self.all_three()
        self.assertEqual(first, self.expect())
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, ".dirty")))
        # 2 回目の前に直近の行を直し、直近に新しい走を足す(読み直しの窓の中)= 入ること
        for r in self.db:
            if r["race_date"] >= (TODAY - dt.timedelta(days=5)).isoformat():
                r["time_sec"] = 99.0
        self.db.append({"track": "浦和", "race_date": (TODAY - dt.timedelta(days=1)).isoformat(), "race_no": 9,
                        "runner_number": 1, "horse_name": "アアア", "finish": 1, "time_sec": 77.0, "umaban": 1,
                        "start_note": "出遅れ"})
        os.remove(os.path.join(self.tmp.name, ".dirty"))
        n0 = len(self.calls)
        second = self.all_three()
        self.assertEqual(second, self.expect())
        new_calls = self.calls[n0:n0 + len(self.calls)]
        fresh = (TODAY - dt.timedelta(days=kf.FRESH_DAYS)).isoformat()
        self.assertTrue(all(f"race_date=gte.{fresh}" in c or "race_date=in." in c for c in new_calls[:2]))

    def test_next_day_reads_whole(self):
        kf.KARTE_CACHE = self.tmp.name
        self.all_three()
        self.today = TODAY + dt.timedelta(days=1)
        n0 = len(self.calls)
        got = self.all_three()
        self.assertEqual(got, self.expect())
        hist_calls = [c for c in self.calls[n0:] if "horse_name=in." in c]
        self.assertTrue(hist_calls and not any("gte.2026-10-23&limit" in c for c in hist_calls))

    def test_broken_cache_falls_back(self):
        kf.KARTE_CACHE = self.tmp.name
        self.all_three()
        d = os.path.join(self.tmp.name, "k")
        for f in os.listdir(d):
            if f.endswith(".json.gz"):
                with open(os.path.join(d, f), "wb") as fh:
                    fh.write(b"broken")
        self.assertEqual(self.all_three(), self.expect())


if __name__ == "__main__":
    unittest.main()

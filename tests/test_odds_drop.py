# -*- coding: utf-8 -*-
"""odds_drop: 基準 tick の選び方・下落率・週の境目・帯広ば→帯広(2026-10-17)"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
import odds_drop as od  # noqa: E402


def tick(i, t, w, f=False):
    return {"id": i, "track": "門別", "race_no": 5, "t": t, "f": f, "w": w}


class TestBase(unittest.TestCase):
    def setUp(self):
        # 発走 15:30。14:50(40)・15:00(30)・15:09(21)・15:10(20) が 2 本・15:21(9)・最終
        self.ticks = [tick(1, "14:50", {"3": "30.0"}), tick(2, "15:00", {"3": "24.1"}),
                      tick(3, "15:09", {"3": "25.5"}), tick(4, "15:10", {"3": "25.0"}),
                      tick(5, "15:10", {"3": "25.2"}), tick(6, "15:21", {"3": "26.8"}),
                      tick(7, "15:29", {"3": "3.5"}, True), tick(8, "15:30", {"3": "3.0"}, True)]
        self.pre = od.pre_ticks(self.ticks, od.mins("1530"))

    def test_base_latest_at_or_before(self):
        self.assertEqual(od.base_tick(self.pre, 30)["3"], "24.1")
        self.assertEqual(od.base_tick(self.pre, 21)["3"], "25.5")
        self.assertEqual(od.base_tick(self.pre, 20)["3"], "25.2")   # 同じ時刻なら id の大きい方
        self.assertEqual(od.base_tick(self.pre, 10)["3"], "25.2")
        self.assertEqual(od.base_tick(self.pre, 5)["3"], "26.8")

    def test_base_none_when_too_late(self):
        pre = od.pre_ticks([tick(1, "15:28", {"3": "5"})], od.mins("1530"))
        self.assertIsNone(od.base_tick(pre, 3))
        self.assertEqual(od.base_tick(pre, 2)["3"], "5")

    def test_final_is_last_f(self):
        self.assertEqual(od.final_tick(self.ticks)["id"], 8)
        self.assertIsNone(od.final_tick([tick(1, "15:00", {})]))

    def test_drop_and_bases(self):
        self.assertAlmostEqual(od.drop(3.0, 24.0), 0.875)
        self.assertAlmostEqual(od.drop(8.0, 10.0), 0.2)
        b, ok = od.horse_bases(self.pre, "3", 3.0)
        self.assertTrue(ok)
        self.assertEqual(b, {"30": 24.1, "20": 25.2, "10": 25.2, "5": 26.8, "3": 26.8})
        b, ok = od.horse_bases(self.pre, "3", 24.0)
        self.assertFalse(ok)
        b, ok = od.horse_bases(self.pre, "9", 3.0)     # 基準に無い馬= b は空
        self.assertEqual(b, {})
        self.assertFalse(ok)

    def test_spark(self):
        s = od.spark(self.pre, "3", 3.0)
        self.assertEqual(s[0], [40, 30.0])
        self.assertEqual(s[-1], [0, 3.0])
        self.assertEqual([p[0] for p in s], [40, 30, 21, 20, 20, 9, 0])

    def test_build_day(self):
        races = [{"track": "門別", "race_no": 5, "post_time": "1530", "race_name": "テスト", "surface": "ダート",
                  "distance_m": 1000}]
        runs = [{"track": "門別", "race_no": 5, "runner_number": 3, "horse_name": "ウマ", "finish": 1,
                 "popularity": 2}]
        nr, nh, hs = od.build_day("2026-10-13", self.ticks, races, runs)
        self.assertEqual((nr, nh, len(hs)), (1, 1, 1))
        h = hs[0]
        self.assertEqual((h["tr"], h["tp"], h["sf"], h["u"], h["h"], h["fin"], h["pop"], h["fo"]),
                         ("門別", "monbetsu", "ダ", 3, "ウマ", 1, 2, 3.0))


class FakeRest:
    def __init__(self, tables):
        self.tables, self.calls = tables, []

    def paged(self, path, order):
        self.calls.append(path)
        return list(self.tables.get(path.split("?")[0], []))


class TestToday(unittest.TestCase):
    def test_only_races_with_final_tick(self):
        ticks = [tick(1, "15:20", {"3": "10.0"}), tick(2, "15:30", {"3": "5.0"}, True),
                 {"id": 3, "track": "門別", "race_no": 6, "t": "15:50", "f": False, "w": {"1": "9.0"}}]
        races = [{"track": "門別", "race_no": 5, "post_time": "1530"},
                 {"track": "門別", "race_no": 6, "post_time": "1600"}]
        rest = FakeRest({"nar_odds_ticks": ticks, "nar_races": races, "nar_runs": []})
        doc = od.build_today(rest, dt.date(2026, 10, 17), now=dt.datetime(2026, 10, 17, 16, 0, tzinfo=od.JST))
        self.assertEqual(len(doc["weeks"]), 1)
        w = doc["weeks"][0]
        self.assertEqual((w["key"], w["from"], w["to"], w["races"], w["runners"], len(w["horses"])),
                         ("today", "2026-10-17", "2026-10-17", 1, 1, 1))
        self.assertEqual(w["horses"][0]["r"], 5)
        self.assertTrue(all("race_date=eq.2026-10-17" in c for c in rest.calls))

    def test_no_races_day(self):
        doc = od.build_today(FakeRest({}), dt.date(2026, 10, 19))
        self.assertEqual(doc["weeks"], [{"key": "today", "from": "2026-10-19", "to": "2026-10-19",
                                         "races": 0, "runners": 0, "horses": []}])
        self.assertIn("built", doc)


class TestWeeks(unittest.TestCase):
    def test_saturday(self):
        w = od.weeks(dt.date(2026, 10, 17))
        self.assertEqual([(k, a.isoformat(), b.isoformat()) for k, a, b in w],
                         [("this", "2026-10-11", "2026-10-17"), ("last", "2026-10-04", "2026-10-10")])

    def test_sunday_starts_new_week(self):
        w = od.weeks(dt.date(2026, 10, 18))
        self.assertEqual((w[0][1], w[0][2]), (dt.date(2026, 10, 18), dt.date(2026, 10, 18)))
        self.assertEqual((w[1][1], w[1][2]), (dt.date(2026, 10, 11), dt.date(2026, 10, 17)))


class TestTrack(unittest.TestCase):
    def test_obihiro(self):
        self.assertEqual(od.track_name("帯広ば"), "帯広")
        self.assertEqual(od.track_prefix("帯広ば"), "obihiro")
        self.assertEqual(od.track_name("名古屋"), "名古屋")
        self.assertEqual(od.track_prefix("名古屋"), "nagoya")
        self.assertIsNone(od.track_prefix("東京"))


if __name__ == "__main__":
    unittest.main()

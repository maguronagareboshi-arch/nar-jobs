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


def crow(kind, c, o0, r0, o1, r1, t0, t1, of=None, fin="2026-11-04T05:25:00+00:00", hf=True, track="盛岡", r=6):
    """public.combo_drops の 1 行(PostgREST の返り値の形)。時刻は UTC。"""
    return {"track": track, "race_no": r, "kind": kind, "t0": t0, "t1": t1, "fin": fin, "has_final": hf,
            "c": c, "o0": o0, "r0": r0, "o1": o1, "r1": r1, "ofin": of}


A0, A1 = "2026-11-04T05:22:00+00:00", "2026-11-04T05:23:00+00:00"   # JST 14:22→14:23
B0, B1 = "2026-11-04T05:20:00+00:00", "2026-11-04T05:21:00+00:00"   # JST 14:20→14:21


class TestCombo(unittest.TestCase):
    def setUp(self):
        self.rows = [
            crow("sanrentan", [5, 3, 4], 118.1, 32, 29.8, 4, A0, A1, 30.1),
            crow("sanrentan", [5, 3, 4], 100.0, 30, 60.0, 9, B0, B1, 30.1),   # 同じ組の別の刻み(下がり小)
            crow("umaren", [3, 5], 20.0, 6, 9.0, 2, A0, A1, 8.5),
            crow("wide", [3, 7], 10.0, 8, 4.0, 3, B0, B1, None),
            crow("umatan", [5, 3], 30.0, 9, 14.0, 4, A0, A1, "13.9"),
        ]
        self.wt = [{"id": 1, "track": "盛岡", "race_no": 6, "t": "14:22", "f": False, "w": {"3": "8.2", "5": "2.5"}},
                   {"id": 2, "track": "盛岡", "race_no": 6, "t": "14:23", "f": False, "w": {"3": "4.6", "5": "3.3"}},
                   {"id": 3, "track": "盛岡", "race_no": 6, "t": "14:25", "f": True, "w": {"3": "1.0", "5": "9.9"}}]
        self.runs = [{"track": "盛岡", "race_no": 6, "runner_number": 5, "finish": 1},
                     {"track": "盛岡", "race_no": 6, "runner_number": 3, "finish": 2},
                     {"track": "盛岡", "race_no": 6, "runner_number": 4, "finish": 3}]

    def test_race_card(self):
        x = od.combo_race("2026-11-04", self.rows, self.wt, self.runs)
        self.assertEqual((x["d"], x["track"], x["r"], x["t0"], x["t1"], x["left"], x["fin"]),
                         ("2026-11-04", "盛岡", 6, "14:22", "14:23", 2, "B"))
        self.assertEqual([(i["k"], i["c"]) for i in x["items"]],
                         [("sanrentan", [5, 3, 4]), ("wide", [3, 7]), ("umaren", [3, 5]), ("umatan", [5, 3])])
        self.assertEqual(x["items"][0], {"k": "sanrentan", "c": [5, 3, 4], "o0": 118.1, "r0": 32, "o1": 29.8,
                                         "r1": 4, "of": 30.1})
        self.assertIsNone(x["items"][1]["of"])
        self.assertEqual(x["items"][3]["of"], 13.9)
        self.assertEqual(x["focus"], [3, 5])            # 3 は 4 回・5 は 3 回(4 組の半分以上)・4・7 は 1 回
        self.assertEqual(x["tan"], [[3, 8.2, 4.6], [5, 2.5, 3.3]])
        self.assertEqual(x["res"], [5, 3, 4])

    def test_no_final_no_result(self):
        rows = [crow("umaren", [1, 2], 10.0, 5, 5.0, 1, A0, A1, None, fin="2026-11-04T05:30:00+00:00", hf=False)]
        x = od.combo_race("2026-11-04", rows, [], self.runs[:2])
        self.assertEqual((x["fin"], x["left"], x["res"], x["tan"], x["focus"]), (None, 7, None, [], [1, 2]))

    def test_obihiro_and_day_week(self):
        rows = self.rows + [crow("umaren", [1, 2], 10.0, 5, 4.0, 1, A0, A1, track="帯広ば", r=3)]
        day = od.combo_day("2026-11-04", rows, self.wt, self.runs, races_all=59)
        self.assertEqual([(r["track"], r["r"]) for r in day["races"]], [("帯広", 3), ("盛岡", 6)])
        self.assertEqual(day["races"][0]["tan"], [])     # 帯広の単勝 tick は渡していない= 省く
        w = od.combo_week("this", "2026-11-01", "2026-11-05", [day, {"d": "2026-11-05", "races_all": 0, "races": []}])
        self.assertEqual((w["key"], w["races_all"], w["n_races"], w["n_combos"]), ("this", 59, 2, 5))

    def test_empty_day(self):
        day = od.combo_day("2026-11-03", [], [], [], races_all=0)
        self.assertEqual(day, {"d": "2026-11-03", "races_all": 0, "races": []})


if __name__ == "__main__":
    unittest.main()

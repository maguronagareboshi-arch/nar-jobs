# -*- coding: utf-8 -*-
"""§284 cloud/class_monbetsu.py の timing= 級別表の見込み日(最新回の asof + 14 日)と今季終わりの判定。"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))
try:
    import class_monbetsu as M  # noqa: E402
except ImportError as e:        # pipeline/ の部品が無い環境
    raise unittest.SkipTest(f"class_monbetsu が読めない {e}")

D = dt.date.fromisoformat
KAIS = [{"kai": 12, "asof": "2026-08-28"}, {"kai": 13, "asof": "2026-09-11"}]   # 次の見込み= 9/25(金)


def at(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=M.JST)


def sched(*mon, end="2026-11-30"):
    days = {d: [["monbetsu", "☆"]] for d in mon}
    days.setdefault(end, [["kochi", "☆"]])
    return M.monbetsu_days({"days": days})


IN_SEASON = sched("2026-09-30", "2026-10-01", "2026-10-02")


class T(unittest.TestCase):
    def test_before(self):
        self.assertEqual(M.timing(KAIS, *IN_SEASON, at("2026-09-23T12:30")), ("before", D("2026-09-25")))

    def test_thursday_exception(self):      # 見込み日の前日(木曜)から見に行く
        self.assertEqual(M.timing(KAIS, *IN_SEASON, at("2026-09-24T12:30"))[0], "due")

    def test_on_day(self):
        self.assertEqual(M.timing(KAIS, *IN_SEASON, at("2026-09-25T12:30")), ("due", D("2026-09-25")))

    def test_overdue(self):
        self.assertEqual(M.timing(KAIS, *IN_SEASON, at("2026-09-25T15:30"))[0], "overdue")
        self.assertEqual(M.timing(KAIS, *IN_SEASON, at("2026-09-27T12:30"))[0], "overdue")

    def test_season_end(self):
        mon, end = sched("2026-09-20", "2026-11-20")     # 見込み 9/25 から 10 日以内に開催なし
        self.assertEqual(M.timing(KAIS, mon, end, at("2026-09-25T12:30")), ("season_end", D("2026-09-25")))

    def test_schedule_unknown_is_not_season_end(self):
        self.assertEqual(M.timing(KAIS, None, None, at("2026-09-25T12:30"))[0], "due")
        mon, end = sched(end="2026-09-30")            # 日程が見込み+10 日まで無い= 決めない
        self.assertEqual(M.timing(KAIS, mon, end, at("2026-09-25T12:30"))[0], "due")

    def test_new_season(self):              # 前季の最後(11/6)から空いて、7 日以内に門別の開催
        kais = [{"kai": 16, "asof": "2026-11-06"}]
        mon, end = sched("2027-04-15", "2027-04-16", end="2027-05-31")
        self.assertEqual(M.timing(kais, mon, end, at("2027-04-01T12:30"))[0], "season_end")
        self.assertEqual(M.timing(kais, mon, end, at("2027-04-09T12:30")), ("due", D("2027-04-09")))

    def test_no_stored(self):
        self.assertEqual(M.timing([], *IN_SEASON, at("2026-09-25T12:30")), ("unknown", None))

    def test_monbetsu_days(self):
        self.assertEqual(M.monbetsu_days(None), (None, None))
        self.assertEqual(M.monbetsu_days('{"days":{"2026-10-01":[["monbetsu","☆"]]}}'),
                         ([D("2026-10-01")], D("2026-10-01")))


if __name__ == "__main__":
    unittest.main()

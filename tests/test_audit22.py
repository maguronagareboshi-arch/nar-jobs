"""監査 #22: persons の個票失敗で birth/area を送らない・convene は読めた月だけ置換(⛔通信なし)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))

import convene  # noqa: E402
import persons  # noqa: E402


class Persons(unittest.TestCase):
    def test_failed_profile_not_sent(self):
        o = (persons.fetch_list, persons.fetch_profile, persons.WAIT, persons.log)
        persons.fetch_list = lambda kind: ({"1": "山田  太郎", "2": "佐藤  花子"}, 2)

        def prof(kind, lic):
            if lic == "2":
                raise OSError("down")
            return {"birth": "1990-01-01", "area": "高知"}
        persons.fetch_profile, persons.WAIT, persons.log = prof, 0, lambda *_: None
        try:
            rows, _ = persons.collect(next(iter(persons.KINDS)), full=True)
        finally:
            persons.fetch_list, persons.fetch_profile, persons.WAIT, persons.log = o
        a, b = rows
        self.assertEqual((a["birth"], a["area"]), ("1990-01-01", "高知"))
        self.assertNotIn("birth", b)
        self.assertNotIn("area", b)
        self.assertEqual(len(persons.column_groups(rows)), 2)     # 列の違う行は別の POST


class Convene(unittest.TestCase):
    def test_keep_failed_month(self):
        old = {"months": ["2026-09", "2026-10"],
               "days": {"2026-09-05": [["kochi", "☆"]], "2026-10-03": [["saga", "☆"]]}}
        new = {"months": ["2026-09"], "days": {"2026-09-06": [["kochi", "☆"]]}, "others": {}}
        convene.keep_failed_months(new, old, ["2026-10"])
        self.assertEqual(new["months"], ["2026-09", "2026-10"])
        self.assertEqual(list(new["days"]), ["2026-09-06", "2026-10-03"])   # 読めた 9 月は置換・10 月は前回

    def test_jst(self):
        self.assertEqual(convene.JST.utcoffset(None).total_seconds(), 9 * 3600)


if __name__ == "__main__":
    unittest.main()

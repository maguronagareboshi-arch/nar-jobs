# -*- coding: utf-8 -*-
"""cloud/watchdog_dedupe.py の判定(同じ赤のメールは 1 日 1 通・2026-10-03)。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
import watchdog_dedupe as wd  # noqa: E402

D1, D2 = "2026-10-03", "2026-10-04"
A = wd.summarize("stats が今日まだ成功していない(最終 2026-10-02 22:01:00+09:00)")
B = wd.summarize("DB の大きさ: 1 日の伸び 286MB が 150MB を越えた")


class Decide(unittest.TestCase):
    def test_first_red_notifies(self):
        act, save = wd.decide(None, D1, [A])
        self.assertEqual(act, "notify")
        self.assertEqual(save, {"date": D1, "reasons": [A]})

    def test_same_reasons_silent(self):
        act, save = wd.decide({"date": D1, "reasons": [A, B]}, D1, [A])
        self.assertEqual(act, "silent")
        self.assertIsNone(save)

    def test_new_reason_notifies(self):
        act, save = wd.decide({"date": D1, "reasons": [A]}, D1, [A, B])
        self.assertEqual(act, "notify")
        self.assertEqual(save["reasons"], sorted([A, B]))

    def test_new_day_notifies(self):
        act, save = wd.decide({"date": D1, "reasons": [A]}, D2, [A])
        self.assertEqual(act, "notify")
        self.assertEqual(save, {"date": D2, "reasons": [A]})

    def test_no_red_clears(self):
        act, save = wd.decide({"date": D1, "reasons": [A]}, D1, [])
        self.assertEqual(act, "clear")
        self.assertIsNone(save)


class Collect(unittest.TestCase):
    def test_numbers_removed_and_job_fallback(self):
        self.assertEqual(wd.summarize("refresh の最終成功が 70 分より古い(2026-10-03 10:00)"),
                         wd.summarize("refresh の最終成功が 70 分より古い(2026-10-04 11:30)"))
        self.assertEqual(wd.summarize("k43_daily が今日まだ成功していない(最終 2026-10-09 06:52)"),
                         wd.summarize("k43_daily が今日まだ成功していない(最終 2026-10-10 06:50)"))
        needs = {
            "freshness": {"result": "success", "outputs": {"red": "true", "reasons": ""}},
            "heartbeat": {"result": "success", "outputs": {"red": "true", "reasons": json.dumps(["x の last_status= fail(note=n 3)"])}},
            "odds-live": {"result": "success", "outputs": {"red": "false", "reasons": ""}},
            "db-size": {"result": "skipped", "outputs": {}},
        }
        self.assertEqual(wd.collect(needs), sorted(["freshness が赤", "x の last_status= fail(note=n #)"]))


if __name__ == "__main__":
    unittest.main()

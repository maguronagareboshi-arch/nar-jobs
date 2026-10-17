# -*- coding: utf-8 -*-
"""baba_hist.merge_days: 確定済みの日を据え置く・暫定(p)と新しい日だけ組む(2026-10-17)"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud"))
import baba_hist  # noqa: E402


def samples():
    out = []
    d0 = dt.date(2025, 1, 1)
    for i in range(0, 400, 7):            # 1 年ぶんの標準(良・1200m・C1・1〜5着)
        day = (d0 + dt.timedelta(days=i)).isoformat()
        for rno in range(1, 6):
            for fin in range(1, 6):
                out.append(("高知", day, 1200, "C1", 75.0 + fin * 0.2 + (0.5 if day >= "2026-02-01" else 0),
                            "良", rno, fin))
    return out


class T(unittest.TestCase):
    def test_frozen_kept_and_new_built(self):
        s = samples()
        last = max(x[1] for x in s)
        old = {"2025-01-01": {"d": 9.9, "k": "良"}}
        days, rebuilt = baba_hist.merge_days("kochi", s, {last, "2025-01-01"}, old,
                                             dt.date.fromisoformat(last) + dt.timedelta(days=1), False)
        self.assertEqual(days["2025-01-01"]["d"], 9.9)     # 確定済みは据え置き
        self.assertIn("d", days[last])
        self.assertEqual(set(days[last]) - set(baba_hist.KEEP), set())
        self.assertEqual(rebuilt, 1)

    def test_today_is_provisional(self):
        s = samples()
        last = max(x[1] for x in s)
        days, _ = baba_hist.merge_days("kochi", s, {last}, None, dt.date.fromisoformat(last), False)
        self.assertTrue(days[last].get("p"))


if __name__ == "__main__":
    unittest.main()

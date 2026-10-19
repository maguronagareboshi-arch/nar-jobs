# -*- coding: utf-8 -*-
"""東海の 3 歳の一斉編入日(class_calc.TOKAI_HEN)の固定テスト。通信なし。

  python -m unittest tests.tokai_hen_test -v

9/29〜10/2 の開催が 9 月の四半期末の開催= 一斉編入は 10/3。翌日が 10/1 を過ぎる日は候補から外していたので、
10/1〜2 に出た 3 歳馬が一般格として 25% 調整されていた(2026-10-19 名古屋 8R 出馬表と不一致)。
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
import class_calc as C                                             # noqa: E402


def _races(track, blocks):
    out = {}
    for a, b in blocks:
        d, end = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
        while d <= end:
            out[(track, d.isoformat(), 1)] = {}
            d += dt.timedelta(days=1)
    return out


class TokaiHen(unittest.TestCase):
    def test_straddling_meeting_sets_hen_after_it(self):
        races = _races("名古屋", [("2026-09-14", "2026-09-18"), ("2026-09-29", "2026-10-02"), ("2026-10-13", "2026-10-16")])
        races.update(_races("笠松", [("2026-09-07", "2026-09-11"), ("2026-09-23", "2026-09-25"), ("2026-10-12", "2026-10-16")]))
        adj = C.tokai_adj_dates(races)
        self.assertEqual([d.isoformat() for d in adj["名古屋"]], ["2026-10-03"])
        self.assertEqual(C.TOKAI_HEN[2026], dt.date(2026, 10, 3))


if __name__ == "__main__":
    unittest.main()

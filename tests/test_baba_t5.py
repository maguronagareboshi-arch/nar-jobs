# -*- coding: utf-8 -*-
"""馬場差 T5(1〜5着)方式の検算(2026-09-28)。⛔通信ゼロ。

  py -3 -m unittest discover -s tests -p "test_baba_t5.py"

確かめるのは 5 つ=
  ①レース差= 1〜5着それぞれの「時計 − 同じ着順の基準」の中央値・日×場= レース差の中央値・n はレース数
  ②6着以下は使わない
  ③頭数が MIN_HORSES 未満のレースは落ち、MIN_RACES R 未満なら d/g を出さない
  ④as-of= その日以降の時計は基準に入らない
  ⑤旧版の窓(365)は 1 着だけで組む(2〜5着を混ぜない)
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloud import baba  # noqa: E402

TR, PF = "大井", "ooi"
DAY = "2026-09-01"
TODAY = dt.date(2026, 9, 2)


def hist():
    """8/1〜8/10 の 10 日・各日 1R・着順 f の時計= 70 + 0.2f(良・1200m・帯なし)"""
    out = []
    for k in range(10):
        d = (dt.date(2026, 8, 1) + dt.timedelta(days=k)).isoformat()
        for f in range(1, 7):
            out.append((TR, d, 1200, None, 70 + 0.2 * f, "良", 1, f))
    return out


def day_rows(n_races=4, add=0.5, add_2to5=None, sixth=5.0, short_race=None):
    out = []
    for r in range(1, n_races + 1):
        for f in range(1, 7):
            if short_race == r and f > 2:
                continue
            a = add if f == 1 or add_2to5 is None else add_2to5
            if f == 6:
                a = sixth
            out.append((TR, DAY, 1200, None, 70 + 0.2 * f + a, "良", r, f))
    return out


def cell(samples, baseline="going"):
    days, _, _ = baba.build_days(samples, {DAY}, baseline, today=TODAY)
    return days.get(DAY, {}).get(PF)


class T5Test(unittest.TestCase):
    def test_race_and_day_median(self):
        c = cell(hist() + day_rows())
        self.assertEqual(c["d"], 0.5)
        self.assertEqual(c["g"], 0.5)
        self.assertEqual(c["n"], 4)       # レース数
        self.assertEqual(c["ng"], 4)
        self.assertEqual(c["k"], "良")
        self.assertNotIn("p", c)

    def test_mixed_finishers(self):
        # 1 着 +0.5・2〜5着 +3.0 → レース差 = median(0.5,3,3,3,3) = 3.0
        c = cell(hist() + day_rows(add_2to5=3.0))
        self.assertEqual(c["d"], 3.0)

    def test_sixth_ignored(self):
        self.assertEqual(cell(hist() + day_rows(sixth=-50.0))["d"], 0.5)

    def test_min_horses_and_races(self):
        # 4R のうち 1R が 2 頭だけ → 3R しか残らず d/g は出ない
        self.assertIsNone(cell(hist() + day_rows(short_race=2)))
        # 5R あれば 1R 落ちても 4R で出る
        c = cell(hist() + day_rows(n_races=5, short_race=2))
        self.assertEqual((c["d"], c["n"]), (0.5, 4))

    def test_asof_future_excluded(self):
        fut = [(TR, "2026-09-%02d" % k, 1200, None, 90.0, "良", 1, f)
               for k in range(1, 20) for f in range(1, 6)]
        self.assertEqual(cell(hist() + day_rows() + fut)["d"], 0.5)

    def test_legacy_winner_only(self):
        s = hist() + day_rows(add_2to5=3.0)
        c = cell(s, "365")
        self.assertEqual((c["d"], c["n"]), (0.5, 4))
        # 6 要素(旧形)でも同じ
        s6 = [x[:6] for x in s if x[7] == 1]
        self.assertEqual(cell(s6, "365")["d"], 0.5)


if __name__ == "__main__":
    unittest.main()

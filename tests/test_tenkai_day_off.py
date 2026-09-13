# -*- coding: utf-8 -*-
"""§169 テンの日の補正(day_off)の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_tenkai*.py"

確かめるのは=
  ①day_offsets= その場・その日の x(前半3F − 標準)を集める・標準の無い組は捨てる
  ②day_off_of= その走を除いた中央値・TEN_DAY_MIN 未満の日は None
  ③ten_values= 補正後の値と「補正が入ったか」・day_off が無ければ旧の値のまま
  ④ten_std の before= その日より前の走だけで標準を作る(--backtest のリーク止め)
  ⑤ten_band= day_off を渡すと補正後の最速テンで四分位を作る
"""
import statistics
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud import tenkai                                                 # noqa: E402
from cloud.tenkai import day_off_of, day_offsets, ten_band, ten_std, ten_values   # noqa: E402


def make_day(track, date, base, n, dist=1400, start_no=1):
    """1 日ぶん n 走。前半3F= base + i*0.1(1 レース 1 頭ずつ)"""
    return {(track, date, start_no + i, 1): (round(base + i * 0.1, 2), dist) for i in range(n)}


class DayOff(unittest.TestCase):
    def test_offsets_and_loo(self):
        ten_of = make_day("大井", "2026-08-01", 36.0, 21)
        ten_of[("大井", "2026-08-01", 99, 1)] = (40.0, 1800)          # 標準の無い距離= 捨てる
        std = {("大井", 1400): 36.0}
        off = day_offsets(ten_of, std)
        xs = off[("大井", "2026-08-01")]
        self.assertEqual(len(xs), 21)
        self.assertEqual(xs, sorted(xs))
        # その走を除いた中央値(自分で自分を補正しない)
        x0 = xs[0]
        self.assertAlmostEqual(day_off_of(off, "大井", "2026-08-01", x0), statistics.median(xs[1:]))
        x_last = xs[-1]
        self.assertAlmostEqual(day_off_of(off, "大井", "2026-08-01", x_last), statistics.median(xs[:-1]))
        self.assertIsNone(day_off_of(off, "大井", "2026-08-02", 0.0))

    def test_min_sample(self):
        ten_of = make_day("高知", "2026-08-01", 37.0, tenkai.TEN_DAY_MIN - 1)
        off = day_offsets(ten_of, {("高知", 1400): 37.0})
        self.assertIsNone(day_off_of(off, "高知", "2026-08-01", 0.5), "TEN_DAY_MIN 未満の日を補正している")

    def test_ten_values(self):
        ten_of = make_day("船橋", "2026-08-01", 35.0, 25)
        ten_of.update(make_day("船橋", "2026-08-02", 36.0, 5, start_no=1))
        std = {("船橋", 1400): 35.5}
        runs = [{"track": "船橋", "race_date": "2026-08-01", "race_no": 3, "runner_number": 1},
                {"track": "船橋", "race_date": "2026-08-02", "race_no": 2, "runner_number": 1},
                {"track": "船橋", "race_date": "2026-08-03", "race_no": 1, "runner_number": 1}]
        old = ten_values(runs, ten_of, std)
        self.assertEqual([round(v, 2) for v, _a in old], [-0.3, 0.6])
        self.assertEqual([a for _v, a in old], [False, False])
        off = day_offsets(ten_of, std)
        new = ten_values(runs, ten_of, std, off)
        self.assertEqual([a for _v, a in new], [True, False], "標本の少ない日は x のまま")
        x = 35.2 - 35.5
        want = x - day_off_of(off, "船橋", "2026-08-01", x)
        self.assertAlmostEqual(new[0][0], want)
        self.assertAlmostEqual(new[1][0], old[1][0])

    def test_std_before(self):
        ten_of = make_day("門別", "2026-06-01", 36.0, 30)
        ten_of.update(make_day("門別", "2026-08-01", 40.0, 30))
        self.assertEqual(ten_std(ten_of, "2026-07-01"), {("門別", 1400): statistics.median(
            [v for (_t, d, _n, _u), (v, _dm) in ten_of.items() if d < "2026-07-01"])})
        self.assertEqual(ten_std(ten_of, "2026-06-01"), {}, "窓の日の走を標準に入れている")
        self.assertEqual(len(ten_std(ten_of)), 1)

    def test_band_adjusted(self):
        # 2 日= 片方は全体に速い日・もう片方は遅い日。1 レース 1 頭なので最速テン= その走
        ten_of = {}
        for i in range(40):
            ten_of[("大井", "2026-05-01", i + 1, 1)] = (35.0 + i * 0.01, 1400)
            ten_of[("大井", "2026-05-02", i + 1, 1)] = (37.0 + i * 0.01, 1400)
        std = ten_std(ten_of)
        old = ten_band(ten_of, std)
        new = ten_band(ten_of, std, day_offsets(ten_of, std))
        self.assertLess(new["大井"][1] - new["大井"][0], old["大井"][1] - old["大井"][0],
                        "日の差を引いた四分位の幅が狭くならない")


if __name__ == "__main__":
    unittest.main()

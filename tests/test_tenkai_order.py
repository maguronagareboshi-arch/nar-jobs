# -*- coding: utf-8 -*-
"""§169 段 2 隊列の見込み q の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_tenkai*.py"

確かめるのは=
  ①直線の当てはめ(fit_line / ten_fits)= 標本の下限・x が同じなら出さない・窓の外の走を入れない
  ②q の合成と qs= 両方/テンだけ/通過順だけ/どちらも無し
  ③order= q の昇順・同点は馬番順
  ④型の付け直し= 閾値(LEAD_P/FRONT_P/MID_P)を動かしていない
  ⑤順位相関= そろえば 1・逆なら −1・3 頭未満は None
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud import tenkai                                                  # noqa: E402
from cloud.tenkai import fit_line, order_of, q_merge, spearman, style_of_q, ten_fits   # noqa: E402


class Order(unittest.TestCase):
    def test_fit_line(self):
        xs = [i * 0.01 - 1.0 for i in range(tenkai.TEN_Q_MIN)]
        ys = [0.5 + 0.3 * x for x in xs]
        a, b = fit_line(xs, ys)
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(b, 0.3)
        self.assertIsNone(fit_line(xs[:-1], ys[:-1]), "標本の下限を守っていない")
        self.assertIsNone(fit_line([1.0] * tenkai.TEN_Q_MIN, ys), "x がすべて同じでも当てている")

    def test_ten_fits_window(self):
        ten_of, ranks_of = {}, {}
        n = tenkai.TEN_Q_MIN
        for i in range(n):
            d = "2026-05-%02d" % (1 + i % 28)
            ten_of[("大井", d, i + 1, 1)] = (35.0 + i * 0.01, 1400)
            ranks_of[("大井", d, i + 1)] = {1: 1 + i % 10, 2: 11}
            # 窓の外(検証の窓の日)= 当てはめに入れない
            ten_of[("大井", "2026-07-01", 1000 + i, 1)] = (35.0, 1400)
            ranks_of[("大井", "2026-07-01", 1000 + i)] = {1: 11, 2: 1}
        std = {("大井", 1400): 36.0}
        fits = ten_fits(ten_of, ranks_of, std, None, "2026-01-01", "2026-06-15")
        self.assertIn("大井", fits)
        self.assertEqual(fits["大井"][2], n, "窓の外の走を入れている")
        self.assertEqual(ten_fits(ten_of, ranks_of, std, None, "2026-06-15", "2026-06-30"), {})

    def test_q_merge(self):
        q, qs = q_merge(0.2, 0.6, 0.7)
        self.assertAlmostEqual(q, 0.7 * 0.2 + 0.3 * 0.6)
        self.assertEqual(qs, "both")
        self.assertEqual(q_merge(0.2, None, 0.7), (0.2, "ten"))
        self.assertEqual(q_merge(None, 0.6, 0.7), (0.6, "pos"))
        self.assertEqual(q_merge(None, None, 0.7), (None, None))
        self.assertEqual(q_merge(0.2, 0.6, 1.0)[0], 0.2)

    def test_order(self):
        self.assertEqual(order_of({5: 0.3, 2: 0.1, 9: 0.3, 1: 0.8}), [2, 5, 9, 1])
        self.assertEqual(order_of({}), [])

    def test_style_thresholds(self):
        self.assertEqual((tenkai.LEAD_P, tenkai.FRONT_P, tenkai.MID_P, tenkai.MIN_RUNS, tenkai.TEN_MIN_RUNS),
                         (0.2, 0.4, 0.7, 2, 3), "閾値を動かしている")
        self.assertEqual([style_of_q(q) for q in (0.0, 0.2, 0.21, 0.4, 0.41, 0.7, 0.71, 1.0)],
                         ["逃げ", "逃げ", "先行", "先行", "差し", "差し", "追込", "追込"])
        self.assertIsNone(style_of_q(None))

    def test_spearman(self):
        ranks = {1: 1, 2: 2, 3: 3, 4: 4}
        self.assertAlmostEqual(spearman([1, 2, 3, 4], ranks), 1.0)
        self.assertAlmostEqual(spearman([4, 3, 2, 1], ranks), -1.0)
        self.assertIsNone(spearman([1, 2], ranks))
        self.assertIsNone(spearman([1, 2, 7], ranks), "実際の順位の無い馬を数えている")
        self.assertIsNotNone(spearman([1, 2, 3], {1: 1, 2: 1, 3: 3}))   # 同着は平均順位


if __name__ == "__main__":
    unittest.main()

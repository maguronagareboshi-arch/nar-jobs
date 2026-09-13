# -*- coding: utf-8 -*-
"""§169 段 2 隊列の見込み q の検算。標準ライブラリだけ・**通信ゼロ**。

  py -3.12 -m unittest discover -s tests -p "test_tenkai*.py"

確かめるのは=
  ①q_ten(段 2-A′)= そのレースのテン順位の百分位・同点は同じ順位・テンのある馬が TEN_RANK_MIN 頭未満なら出さない
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
from cloud.tenkai import order_of, q_merge, spearman, style_of_q, ten_ranks   # noqa: E402


class Order(unittest.TestCase):
    def test_ten_ranks(self):
        q = ten_ranks({3: -0.8, 7: 0.4, 1: -0.1, 5: 1.2})
        self.assertEqual(q, {3: 0.125, 1: 0.375, 7: 0.625, 5: 0.875})
        # 同点は同じ順位(小さい方)
        self.assertEqual(ten_ranks({1: 0.0, 2: 0.0, 3: 0.5}), {1: 0.5 / 3, 2: 0.5 / 3, 3: 2.5 / 3})
        self.assertEqual(tenkai.TEN_RANK_MIN, 3)
        self.assertEqual(ten_ranks({1: 0.0, 2: 0.5}), {}, "テンのある馬が 3 頭未満でも出している")
        self.assertEqual(ten_ranks({}), {})
        self.assertFalse(hasattr(tenkai, "fit_line") or hasattr(tenkai, "ten_fits") or hasattr(tenkai, "TEN_Q_MIN"),
                         "直線の部品が残っている")

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

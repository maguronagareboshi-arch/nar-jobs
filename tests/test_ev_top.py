# -*- coding: utf-8 -*-
"""§190 案 1 `ev_backtest.py --top N`= EV の候補を p の順位 N 位以内に絞る。標準ライブラリだけ・通信ゼロ・材料ファイル不要。

  py -3.12 -m unittest tests.test_ev_top
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai'))

from ev_backtest import candidates, p_ranks  # noqa: E402


class EvTop(unittest.TestCase):
    def test_top6_takes_p_order_only(self):
        # 作り物の 1 レース 8 頭。3 番と 5 番は同じ p= 馬番の小さい 3 番が上
        pairs = [(1, 0.10), (2, 0.55), (3, 0.30), (4, 0.05), (5, 0.30), (6, 0.70), (7, 0.20), (8, 0.25)]
        ranks = p_ranks(pairs)
        self.assertEqual([u for u, _ in sorted(ranks.items(), key=lambda x: x[1])], [6, 2, 3, 5, 8, 7, 1, 4])
        horses = [dict(u=u, p=p, prank=ranks[u]) for u, p in pairs]
        self.assertEqual(sorted(h['u'] for h in candidates(horses, 6)), [2, 3, 5, 6, 7, 8], 'p の上位 6 頭でない')
        self.assertEqual(len(candidates(horses, 0)), 8, '--top 0 が全頭でない')
        # 順位は全頭で数える= f10_lo の無い馬(ここでは 6 番)を落としても、残りの順位は繰り上がらない
        rest = [h for h in horses if h['u'] != 6]
        self.assertEqual(sorted(h['u'] for h in candidates(rest, 6)), [2, 3, 5, 7, 8])


if __name__ == '__main__':
    unittest.main()

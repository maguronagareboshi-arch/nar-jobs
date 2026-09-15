# -*- coding: utf-8 -*-
"""§190 案 2 `wide_ev.py`= 組の確率(Plackett–Luce)・時刻でワイドを選ぶ・c_wide の帯と月。通信ゼロ・材料ファイル不要。

  py -3.12 -m unittest tests.test_wide_ev
"""
import sys
import unittest
from itertools import permutations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai'))

from wide_ev import c_tables, pair_probs, pick_wide, w_band  # noqa: E402


def brute_pair(s, a, b):
    """全部の着順(4! 通り)を Plackett–Luce で数え、a と b が両方 3 着以内の確率を足す(pair_probs と別の数え方)"""
    tot = 0.0
    for order in permutations(range(len(s))):
        pr, left = 1.0, 1.0
        for x in order:
            pr *= s[x] / left
            left -= s[x]
        if a in order[:3] and b in order[:3]:
            tot += pr
    return tot


class WideEv(unittest.TestCase):
    def test_pair_probs_sum_three_and_one_pair(self):
        s = [0.4, 0.3, 0.2, 0.1]
        P = pair_probs(s)
        total = sum(P[i, j] for i in range(4) for j in range(4) if i < j)
        self.assertAlmostEqual(total, 3.0, places=9)
        for a, b in ((0, 1), (2, 3), (0, 3)):
            self.assertAlmostEqual(P[a, b], brute_pair(s, a, b), places=9)
            self.assertAlmostEqual(P[a, b], P[b, a], places=12)
        self.assertEqual(P[1, 1], 0.0)
        # 強さの合計が 1 でなくても揃えて数える
        self.assertAlmostEqual(pair_probs([4, 3, 2, 1])[0, 1], brute_pair(s, 0, 1), places=9)

    def test_pick_wide_by_time_label(self):
        times = ['最終', '13:58', '13:55']
        pops = [{'1-2': 3.0}, {'1-2': 3.1}, {'2-1': 3.4, '1-3': 5.0, '4-5': '---'}]
        self.assertEqual(pick_wide(times, pops, '13:55'), {(1, 2): 3.4, (1, 3): 5.0})
        self.assertIsNone(pick_wide(times, pops, '13:50'))        # 同じ時刻が無い= 飛ばす
        self.assertIsNone(pick_wide(times, pops, None))           # t10 が無い= 飛ばす
        self.assertIsNone(pick_wide(times, pops, '最終'))          # 最終は締切前でない

    def test_c_wide_bands_and_months(self):
        self.assertEqual([w_band(v) for v in (1.0, 9.9, 10.0, 29.9, 30.0, 99.9, 100.0)],
                         ['<10', '<10', '10-29.9', '10-29.9', '30-99.9', '30-99.9', '≥100'])
        obs = {'2025-09': [('<10', 1.2), ('<10', 1.0), ('≥100', 2.0)], '2025-10': [('<10', 0.8)]}
        c = c_tables(obs, ['2025-09', '2025-10', '2025-11'])
        self.assertEqual(c['2025-09'], {'<10': 1.0, '10-29.9': 1.0, '30-99.9': 1.0, '≥100': 1.0})   # 最初の月は 1
        self.assertEqual(c['2025-10']['<10'], 1.1)                 # 9 月だけ(10 月を覗かない)
        self.assertEqual(c['2025-11']['<10'], 1.0)                 # 9・10 月の中央値
        self.assertEqual(c['2025-11']['≥100'], 2.0)


if __name__ == '__main__':
    unittest.main()

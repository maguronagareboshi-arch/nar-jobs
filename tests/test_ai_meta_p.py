# -*- coding: utf-8 -*-
"""§170 B build_marks の meta.p(全頭の s= p/Σp)の検算。**通信ゼロ**(模型の予測は差し替える)。

  py -3.12 -m unittest discover -s tests -p "test_ai_meta_p.py"

確かめるのは=
  ①meta.p の頭数= 走る馬(取消・除外を外した)の頭数・鍵は馬番の文字
  ②合計 1.000±0.001
  ③meta.p の上位 4 頭の並び(同点は馬番の小さい方)= marks の並び・marks の形は今までどおり
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai'))

import base_v1                                                   # noqa: E402


class MetaP(unittest.TestCase):
    def setUp(self):
        day = '2026-09-14'
        rows = []
        # 大井 5R= 7 頭(うち 6 番は取消)・同点あり(2 番と 4 番)
        for u, p, note in ((1, 0.30, ''), (2, 0.55, ''), (3, 0.12, ''), (4, 0.55, ''),
                           (5, 0.41, ''), (6, 0.90, '取消'), (7, 0.07, '')):
            rows.append(dict(rid=f'大井|{day}|5', track='大井', race_no=5, runner_number=u,
                             race_date=pd.Timestamp(day), finish=None, finish_note=note, _p=p))
        self.df = pd.DataFrame(rows)
        self.day = day
        self._orig = base_v1.predict_df
        base_v1.predict_df = lambda d, m, b, r: d['_p'].values

    def tearDown(self):
        base_v1.predict_df = self._orig

    def test_meta_p(self):
        m = {'trained_to': '2026-09-13', 'rounds': 100}
        out = base_v1.build_marks(self.df, self.day, m, None, None, 'morning')
        self.assertEqual(len(out), 1)
        r = out[0]
        p = r['meta']['p']
        self.assertEqual(sorted(p, key=int), ['1', '2', '3', '4', '5', '7'], '取消の 6 番が入っている/頭数が違う')
        self.assertEqual(r['meta']['n'], len(p))
        self.assertAlmostEqual(sum(p.values()), 1.0, delta=0.001)
        top = sorted(p, key=lambda k: (-p[k], int(k)))[:4]
        self.assertEqual([str(x['num']) for x in r['marks']], top, 'marks の並びと meta.p の上位 4 頭が違う')
        self.assertEqual([x['mark'] for x in r['marks']], base_v1.MARKS)
        self.assertEqual(set(r['marks'][0]), {'num', 'mark', 'score'}, 'marks の形が変わった')
        self.assertAlmostEqual(r['marks'][0]['score'], round(p['2'] * 100, 1), delta=0.05)


if __name__ == '__main__':
    unittest.main()

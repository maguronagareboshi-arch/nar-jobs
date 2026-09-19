# -*- coding: utf-8 -*-
"""§224a meta.p_win= 較正表は 10 帯そろう・p_win は合計 1・meta.p と marks は 1 着の模型があっても不変。通信ゼロ"""
import sys, unittest
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'ai'))
import base_v1  # noqa: E402


class PWin(unittest.TestCase):
    def test_p_win(self):
        day = '2026-09-14'
        df = pd.DataFrame([dict(rid=f'大井|{day}|5', track='大井', race_no=5, runner_number=u, race_date=pd.Timestamp(day), finish=None,
                                finish_note=n, _p=p, _w=w) for u, p, w, n in ((1, .3, .1, ''), (2, .55, .4, ''), (3, .12, .02, ''),
                                                                             (4, .5, .3, ''), (5, .41, .2, ''), (6, .9, .9, '取消'))])
        cal = base_v1.cal_table(np.array([.003, .007, .03, .03, .1, .2, .3, .5, .7]), np.array([0, 0, 0, 1, 0, 0, 1, 1, 1]))
        self.assertEqual((len(cal['n']), len(cal['pred']), len(cal['rate'])), (10, 10, 10), '10 帯そろわない')
        self.assertEqual((cal['n'][2], cal['pred'][2], cal['rate'][2]), (0, None, None), '件数 0 の帯は None')
        orig, base_v1.predict_df = base_v1.predict_df, (lambda d, m, b, r: d['_p'].values)
        try:
            m, win = {'trained_to': day, 'rounds': 1, 'cols': ['_w'], 'cal_win': cal}, type('W', (), {'predict': staticmethod(lambda x: x['_w'].values)})()
            a, b = (base_v1.build_marks(df, day, m, None, None, 'morning', w)[0] for w in (None, win))
        finally:
            base_v1.predict_df = orig
        self.assertEqual((a['meta']['p'], a['marks']), (b['meta']['p'], b['marks']), 'meta.p / marks が変わった')
        self.assertEqual(('p_win' in a['meta'], set(b['meta']['p_win']), b['meta']['cal']), (False, set(b['meta']['p']), 'win-v1'))
        self.assertAlmostEqual(sum(b['meta']['p_win'].values()), 1.0, delta=0.001)

if __name__ == '__main__':
    unittest.main()

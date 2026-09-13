# -*- coding: utf-8 -*-
"""§170 段 2 C 勝つ確率の模型(WF)。**読むだけ**(手元の feat だけ・DB に書かない)。

  py -3.12 -X utf8 pipeline/ai/win_wf.py [--from 2025-09] [--to 2026-08]

- 中身は <HOME>/research_walkforward.py を**そのまま**呼ぶ(同じ材料 feat.parquet・同じ折= 月ごとに前だけで学習・
  同じ PARAMS と列)。⛔違うのは y だけ= 1 着(feat の y_win・無ければ finish==1)。⛔設定は探さない。
- 出力= <HOME>/wf1_win_pred_a.parquet(研究の道具の名前の決まり)と、その写しの <HOME>/wf1_win_pred.parquet(p_win)。
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_hist import HOME  # noqa: E402

sys.path.insert(0, str(HOME))
import research_walkforward as rw  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='test_from', default='2025-09')
    ap.add_argument('--to', dest='test_to', default='2026-08')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    base_load = rw.load

    def load_win():
        df = base_load()
        if 'y_win' in df.columns and df['y_win'].notna().all():
            df['y'] = df['y_win'].astype(int)
            how = 'y_win'
        elif 'finish' in df.columns:
            df['y'] = (df['finish'] == 1).astype(int)
            how = 'finish==1'
        else:
            raise SystemExit('⛔feat に 1 着の印(y_win / finish)が無い= ここで止める')
        print('y= 1 着(', how, ')・1 着の割合', round(float(df['y'].mean()), 4), flush=True)
        return df

    rw.load = load_win
    rw.run(['a'], a.test_from, a.test_to, 'wf1_win')
    import pandas as pd
    src = HOME / 'wf1_win_pred_a.parquet'
    df = pd.read_parquet(src).rename(columns={'p': 'p_win'})
    part = HOME / 'wf1_win_pred.part'
    df.to_parquet(part, index=False)
    os.replace(part, HOME / 'wf1_win_pred.parquet')
    print('->', HOME / 'wf1_win_pred.parquet', len(df), 'rows', flush=True)


if __name__ == '__main__':
    main()

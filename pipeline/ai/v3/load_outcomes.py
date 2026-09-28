# -*- coding: utf-8 -*-
"""v3 着順・払戻の読み込みはすべてここを通す(探索中は 2021-12-31 まで)。

  from load_outcomes import load_outcomes
  runs, payouts = load_outcomes()

- 着順= raw/archive/nar_runs_archive.csv.gz(2014-01〜2022-10)を南関 4 場・race_date < 2022-01-01 に絞る。
- 払戻= v3/db_payouts_explore_2014_2021.parquet。
- ⛔返す直前に race_date >= 2022-01-01 が 1 行でもあれば止める(SystemExit)。確認・封印を開けるときは別関数を足す。
"""
from pathlib import Path

import pandas as pd

RAW = Path(__import__('os').environ.get('V3_RAW', 'C:/Users/kouki/nankan_ai/raw'))
V3 = Path(__import__('os').environ.get('V3_DATA', 'C:/Users/kouki/nankan_ai/v3'))
TRACKS = ['浦和', '船橋', '大井', '川崎']
LIMIT = '2022-01-01'
RUN_COLS = ['track', 'race_date', 'race_no', 'runner_number', 'finish', 'finish_note', 'popularity']


def _guard(df, name):
    bad = int((df.race_date.astype(str) >= LIMIT).sum())
    if bad:
        raise SystemExit(f'⛔{name} に {LIMIT} 以降が {bad} 行。探索中は開けない')
    return df


def load_outcomes():
    runs = pd.read_csv(RAW / 'archive/nar_runs_archive.csv.gz', usecols=RUN_COLS, dtype={'race_date': str})
    runs = runs[runs.track.isin(TRACKS) & (runs.race_date < LIMIT)].rename(columns={'runner_number': 'umaban'})
    pay = pd.read_parquet(V3 / 'db_payouts_explore_2014_2021.parquet')
    pay = pay[pay.track.isin(TRACKS) & (pay.race_date < LIMIT)]
    return _guard(runs.reset_index(drop=True), 'runs'), _guard(pay.reset_index(drop=True), 'payouts')


HIST_COLS = ['track', 'race_date', 'race_no', 'runner_number', 'horse_name', 'jockey', 'body_weight',
             'body_weight_change', 'finish', 'finish_note']


def load_history():
    """H2 の走歴用: 全 NAR 場の走り(race_date < 2022-01-01)。同じ見張りを通す。"""
    h = pd.read_csv(RAW / 'archive/nar_runs_archive.csv.gz', usecols=HIST_COLS, dtype={'race_date': str})
    h = h[h.race_date < LIMIT].rename(columns={'runner_number': 'umaban'})
    return _guard(h.reset_index(drop=True), 'history')


def load_archive(name):
    """馬を見る予想 AI の材料用(2 日目): RAW の nar_runs・nar_run_facts・nar_races の全列・全 NAR 場を
    race_date < 2022-01-01 に絞る。同じ見張りを通す。name = runs・facts・races。"""
    f = {'runs': 'nar_runs_archive', 'facts': 'nar_run_facts_archive', 'races': 'nar_races_archive'}[name]
    d = pd.read_csv(RAW / f'archive/{f}.csv.gz', dtype={'race_date': str}, low_memory=False)
    d = d[d.race_date < LIMIT]
    return _guard(d.reset_index(drop=True), name)

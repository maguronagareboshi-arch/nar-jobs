# -*- coding: utf-8 -*-
"""base-v2 便: nar-ai-feat 便の成果物 `nar_ai_feat_run.csv.gz`(旧 245 列)を
`feat.parquet`(= 研究で使っている C:/Users/kouki/ai_v1/feat.parquet)と同じ列名・型の parquet にする。

  python -X utf8 legacy_to_parquet.py --in in/feat/nar_ai_feat_run.csv.gz --out nai/legacy_feat.parquet

⛔列の並び・名前・型は下の SCHEMA(2026-09-23 に ai_v1/feat.parquet の dtypes から写した 245 列)に合わせる。
  race_date は datetime64[ns]・race_no/runner_number ほかは int64・残りは float32/object。
⛔計算はしない(型を合わせるだけ)。
"""
from __future__ import annotations
import argparse, sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

# (列名, dtype) を ai_v1/feat.parquet の並びのまま
SCHEMA = [
    ('track', 'object'), ('race_date', 'datetime64[ns]'), ('race_no', 'int64'), ('runner_number', 'int64'),
    ('horse_key', 'object'), ('finish', 'float32'), ('finish_note', 'object'), ('popularity', 'float32'),
    ('y_top3', 'float32'), ('y_win', 'float32'), ('prev_chakujun', 'float32'), ('prev_chakusa', 'float32'),
    ('prev_corner4', 'float32'), ('prev_ninki', 'float32'), ('avg_chakujun_3', 'float32'), ('fukusho_rate_5',
    'float32'), ('days_since_prev', 'float32'), ('dist_change', 'float32'), ('track_change', 'float32'),
    ('futan', 'float32'), ('futan_diff', 'float32'), ('prev_bataiju', 'float32'), ('barei', 'int64'),
    ('seibetsu', 'int64'), ('tosu', 'int64'), ('wakuban', 'int64'), ('kyori', 'int64'), ('keibajo', 'int64'),
    ('prize1_log', 'float32'), ('dist_fukusho_rate', 'float32'), ('dist_n', 'int64'), ('kishu_fuku_1y',
    'float32'), ('kishu_n_1y', 'float32'), ('chokyo_fuku_1y', 'float32'), ('chokyo_n_1y', 'float32'),
    ('sire_fuku_band', 'float32'), ('sire_n_band', 'float32'), ('uma_place_fuku', 'float32'), ('uma_place_n',
    'int64'), ('norikae', 'float32'), ('prev_time_z', 'float32'), ('avg_time_z_3', 'float32'),
    ('prev_pos2_rate', 'float32'), ('prev_pos4_rate', 'float32'), ('avg_pos2_3', 'float32'), ('class_diff',
    'float32'), ('prev_ra_pace', 'float32'), ('race_month', 'int64'), ('hasso_hour', 'int64'), ('r_fuku5_pct',
    'float32'), ('r_timez_pct', 'float32'), ('r_pchakusa_pct', 'float32'), ('waku_bias_365', 'float32'),
    ('waku_bias_30', 'float32'), ('pace_bias_365', 'float32'), ('pace_bias_30', 'float32'), ('prev_time_za',
    'float32'), ('avg_time_za_3', 'float32'), ('r_timeza_pct', 'float32'), ('runs_this_year', 'int64'),
    ('season_debut', 'int64'), ('prevyear_fukusho', 'float32'), ('prevyear_timez', 'float32'), ('prevyear_n',
    'float32'), ('p1_chaku', 'float32'), ('p2_chaku', 'float32'), ('p3_chaku', 'float32'), ('p4_chaku',
    'float32'), ('p5_chaku', 'float32'), ('p1_sa', 'float32'), ('p2_sa', 'float32'), ('p3_sa', 'float32'),
    ('p4_sa', 'float32'), ('p5_sa', 'float32'), ('p1_tz', 'float32'), ('p2_tz', 'float32'), ('p3_tz',
    'float32'), ('p4_tz', 'float32'), ('p5_tz', 'float32'), ('p1_pos2', 'float32'), ('p2_pos2', 'float32'),
    ('p3_pos2', 'float32'), ('p4_pos2', 'float32'), ('p5_pos2', 'float32'), ('p1_pos4', 'float32'), ('p2_pos4',
    'float32'), ('p3_pos4', 'float32'), ('p4_pos4', 'float32'), ('p5_pos4', 'float32'), ('p1_ninki', 'float32'),
    ('p2_ninki', 'float32'), ('p3_ninki', 'float32'), ('p4_ninki', 'float32'), ('p5_ninki', 'float32'),
    ('p1_dkyori', 'float32'), ('p2_dkyori', 'float32'), ('p3_dkyori', 'float32'), ('p4_dkyori', 'float32'),
    ('p5_dkyori', 'float32'), ('p1_cls', 'float32'), ('p2_cls', 'float32'), ('p3_cls', 'float32'), ('p4_cls',
    'float32'), ('p5_cls', 'float32'), ('p1_gap', 'float32'), ('p2_gap', 'float32'), ('p3_gap', 'float32'),
    ('p4_gap', 'float32'), ('p5_gap', 'float32'), ('p1_same', 'float32'), ('p2_same', 'float32'), ('p3_same',
    'float32'), ('p4_same', 'float32'), ('p5_same', 'float32'), ('best_tz_5', 'float32'), ('worst_tz_5',
    'float32'), ('std_tz_5', 'float32'), ('best_chaku_5', 'float32'), ('n_tz_5', 'int64'), ('p1_rz', 'float32'),
    ('p2_rz', 'float32'), ('p3_rz', 'float32'), ('p4_rz', 'float32'), ('p5_rz', 'float32'), ('p1_rzin',
    'float32'), ('p2_rzin', 'float32'), ('p3_rzin', 'float32'), ('avg_rz_3', 'float32'), ('avg_rz_5',
    'float32'), ('best_rz_5', 'float32'), ('std_rz_5', 'float32'), ('avg_rzin_3', 'float32'), ('n_rz_5',
    'int64'), ('r_rz_pct', 'float32'), ('r_bestrz_pct', 'float32'), ('opp_str_now', 'float32'), ('p1_fld',
    'float32'), ('p2_fld', 'float32'), ('p3_fld', 'float32'), ('avg_fld_3', 'float32'), ('relief_3', 'float32'),
    ('bataiju_now', 'float32'), ('bataiju_diff', 'float32'), ('baba_now', 'float32'), ('wet_n', 'int64'),
    ('wet_fuku', 'float32'), ('wet_tza_gap', 'float32'), ('p1_kishu_fuku', 'float32'), ('kishu_delta',
    'float32'), ('bw_slope_5', 'float32'), ('bw_dev', 'float32'), ('p1_season_debut', 'float32'),
    ('pair_fuku_3y', 'float32'), ('pair_n_3y', 'float32'), ('pair_vs_kishu', 'float32'), ('p1_lappace',
    'float32'), ('p1_lapfade', 'float32'), ('mf_fuku_band', 'float32'), ('mf_n_band', 'float32'),
    ('sire_rgm_gap', 'float32'), ('mf_rgm_gap', 'float32'), ('rgm_gap', 'float32'), ('rgm_n', 'int64'),
    ('trk_recent_dmz', 'float32'), ('dist_match', 'float32'), ('p1_dist_match', 'float32'), ('pl_theta',
    'float32'), ('pl_n', 'float32'), ('jk_beta', 'float32'), ('tr_gamma', 'float32'), ('r_plth_pct', 'float32'),
    ('pl_gap_top', 'float32'), ('jk_beta_delta', 'float32'), ('bw_season_dev', 'float32'), ('sex_summer',
    'int64'), ('rest_leq3', 'float32'), ('rest_gt42', 'float32'), ('oshi_nose2', 'int64'), ('oshi_nose4',
    'int64'), ('oshi_rate', 'float32'), ('c4lead_lost_rate', 'float32'), ('mak_gain_m3', 'float32'),
    ('pos2_var5', 'float32'), ('fade34_rate5', 'float32'), ('qpts', 'float32'), ('race_qsum', 'float32'),
    ('race_qmax', 'float32'), ('minarai_now', 'float32'), ('since_layoff', 'float32'), ('prev_best5',
    'float32'), ('bounce_risk', 'float32'), ('has_hist', 'int64'), ('ten_kb', 'float32'), ('ten_kb_dev',
    'float32'), ('avg_f', 'float32'), ('ten_rank', 'float32'), ('p1_l3z', 'float32'), ('p2_l3z', 'float32'),
    ('p3_l3z', 'float32'), ('avg_l3z_3', 'float32'), ('best_l3z_5', 'float32'), ('r_l3z_pct', 'float32'),
    ('p1_l3gap', 'float32'), ('style', 'float32'), ('avg_pos_5', 'float32'), ('lead_n', 'int64'), ('n_front',
    'int64'), ('front_ratio', 'float32'), ('jc_changed', 'float32'), ('jc_rejoin', 'float32'), ('jc_tier',
    'float32'), ('jc_pair_n', 'float32'), ('jc_pair_hit', 'float32'), ('jc_tj_n', 'float32'), ('jc_tj_hit',
    'float32'), ('gear_now', 'float32'), ('gear_first', 'float32'), ('gear_off', 'float32'), ('gear_n',
    'int64'), ('gear_hit', 'float32'), ('start_note_n', 'int64'), ('prize_local', 'float32'),
    ('prize_local_log', 'float32'), ('r_prize_pct', 'float32'), ('baba_diff_d', 'float32'), ('baba_io_365',
    'float32'), ('course_waku_hit', 'float32'), ('course_front_win', 'float32'), ('course_pos_hit', 'float32'),
    ('ill_n_365', 'int64'), ('ill_last_days', 'float32'), ('scratch_n_365', 'int64'), ('p1_scratch', 'float32'),
    ('noken_days', 'float32'), ('noken_time', 'float32'), ('is_noken_debut', 'float32'), ('owner_hit',
    'float32'), ('owner_n', 'float32'), ('breeder_hit', 'float32'), ('breeder_n', 'float32'), ('sale_price',
    'float32'), ('sale_year', 'float32'), ('jockey_penalty_90d', 'int64'), ('race_sales', 'float32'),
    ('sales_vs_venue_avg', 'float32')
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', dest='dst', required=True)
    a = ap.parse_args()

    df = pd.read_csv(a.src, low_memory=False)
    print('read', a.src, df.shape)

    out = pd.DataFrame(index=df.index)
    missing = []
    for c, t in SCHEMA:
        if c not in df.columns:
            missing.append(c)
            s = pd.Series(np.nan, index=df.index)
        else:
            s = df[c]
        if t == 'datetime64[ns]':
            out[c] = pd.to_datetime(s, errors='coerce')
        elif t == 'object':
            out[c] = s.astype('object').where(s.notna(), None)
        elif t == 'int64':
            out[c] = pd.to_numeric(s, errors='coerce').fillna(0).astype('int64')
        else:
            out[c] = pd.to_numeric(s, errors='coerce').astype(t)
    extra = [c for c in df.columns if c not in dict(SCHEMA)]
    if missing:
        print('⚠csv に無い列(NaN で埋めた) %d 本: %s' % (len(missing), missing[:12]))
    if extra:
        print('⚠csv にだけある列(落とした) %d 本: %s' % (len(extra), extra[:12]))
    out.to_parquet(a.dst, index=False)
    print('→', a.dst, out.shape)
    return 0


if __name__ == '__main__':
    sys.exit(main())

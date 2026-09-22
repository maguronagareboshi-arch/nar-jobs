# -*- coding: utf-8 -*-
"""base-v2 便: nar-ai-feat 便が写した dump_<表>.tsv.gz を raw/<表>.csv.gz に直す。

  python -X utf8 tsv_to_csv.py --in in/feat/dump_nar_runs.tsv.gz --table nar_runs --out nai/raw/nar_runs.csv.gz
  python -X utf8 tsv_to_csv.py --in-dir in/feat --out-dir nai/raw        # 4 表まとめて

psql の `\\copy … to 'x.tsv'`(text 形式)= タブ区切り・ヘッダ無し・NULL は `\\N`・
値の中の タブ/改行/復帰/円記号 は `\\t \\n \\r \\\\` で逃がしてある。
ここではそれを解いて **ヘッダ付き CSV(NULL は空欄)** に直す。

⛔列名は .github/workflows/nar-ai-feat.yml の各 select 文の並びをそのまま写したもの
  (2026-09-23 時点)。⛔本番の列が増えた日は yml と ここ を同じ並びで直す。
⛔nar_paper_runs は便 A(nar-ai-v2-raw)が header 付き CSV で写すので、ここは通さない。
"""
from __future__ import annotations
import argparse, csv, gzip, os, sys

sys.stdout.reconfigure(encoding='utf-8')

COLS = {
    'nar_runs': ['track', 'race_date', 'race_no', 'runner_number', 'gate', 'horse_name', 'sex', 'age',
                 'jockey', 'trainer', 'carried_weight', 'body_weight', 'body_weight_change', 'finish',
                 'finish_note', 'time_raw', 'time_sec', 'margin', 'last3f', 'popularity', 'updated_at',
                 'birth_date', 'trainer_area', 'weight_mark'],
    'nar_races': ['track', 'race_date', 'race_no', 'post_time', 'race_name', 'surface', 'direction',
                  'distance_m', 'weather', 'going', 'field_size', 'condition', 'prize_yen',
                  'race_last4f', 'race_last3f', 'furlongs', 'corners', 'source', 'source_snapshot_hash',
                  'updated_at', 'race_kind', 'cancelled', 'cancel_note', 'nankan'],
    'nar_kb_runs': ['track', 'race_date', 'race_no', 'umaban', 'horse_name', 'kb_race_id', 'blinker',
                    'gear', 'first3f', 'avg_f', 'pace', 'kimete', 'start_note', 'updated_at'],
    'nar_run_facts': ['race_date', 'track', 'race_no', 'umaban', 'horse_key', 'horse_name',
                      'c1', 'n1', 'c2', 'n2', 'c3', 'n3', 'c4', 'n4', 'style', 'style_p', 'style_n',
                      'first3f', 'first3f_src', 'last3f', 'win_odds_close', 'src', 'computed_at'],
}

ESC = {'t': '\t', 'n': '\n', 'r': '\r', '\\': '\\', 'b': '\b', 'f': '\f', 'v': '\v'}


def unesc(s):
    """psql text 形式の逃がしを解く。'\\N' は None(= NULL)。"""
    if s == '\\N':
        return None
    if '\\' not in s:
        return s
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            n = s[i + 1]
            out.append(ESC.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def convert(src, table, dst):
    cols = COLS[table]
    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with gzip.open(src, 'rt', encoding='utf-8', newline='') as fi, \
            gzip.open(dst, 'wt', encoding='utf-8', newline='') as fo:
        w = csv.writer(fo)
        w.writerow(cols)
        for line in fi:
            if line.endswith('\n'):
                line = line[:-1]
            if line == '\\.' or line == '':
                continue
            parts = line.split('\t')
            if len(parts) != len(cols):
                raise SystemExit('⛔%s の列数が合わない 行%d: %d 列(要 %d 列)'
                                 % (table, n + 1, len(parts), len(cols)))
            w.writerow(['' if (v := unesc(p)) is None else v for p in parts])
            n += 1
    print('%s %d 行 → %s' % (table, n, dst))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src')
    ap.add_argument('--table')
    ap.add_argument('--out', dest='dst')
    ap.add_argument('--in-dir')
    ap.add_argument('--out-dir')
    a = ap.parse_args()
    if a.in_dir:
        for t in COLS:
            convert(os.path.join(a.in_dir, 'dump_%s.tsv.gz' % t), t,
                    os.path.join(a.out_dir, '%s.csv.gz' % t))
        return 0
    if not (a.src and a.table and a.dst):
        raise SystemExit('--in/--table/--out か --in-dir/--out-dir')
    convert(a.src, a.table, a.dst)
    return 0


if __name__ == '__main__':
    sys.exit(main())

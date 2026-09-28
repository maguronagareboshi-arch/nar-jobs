# -*- coding: utf-8 -*-
"""南関 AI v3 第 8 版の毎日の前日版(= t8_forecast.py table DATE pre)を便で回す入口。学習はしない。

  python -X utf8 pipeline/ai/v3/v3_daily.py DATE OUTDIR [--write]

1. 追い切りの毎日の分: 鍵(SUPABASE_URL・SUPABASE_SERVICE_KEY)があれば nar_kb_works から(kb_works.install)、
   無ければ(または V3_WORKS_SRC=json)手元の JSON(V3_CYOKYO_JSON)から = 従来の道。
2. t8_forecast.table(DATE, 'pre', OUTDIR) → OUTDIR/DATE_第8版_前日版.csv・.md
3. --write のときだけ nar_ai_marks に model='v3-8'・timing='morning' で書く(base_v1.write_marks = 朝の行は凍結・読み直し)。
   marks = 印の付いた馬(◎○▲△・順位の順)・score = 3 着以内の確率 p3′ × 100。
   meta = n・model・stamp・works の元・runners(全馬の num・p1 = 勝つ確率・p3 = 3 着以内の確率 p3′(表の値)・p3_raw = 上乗せ後の p3)。
固定ファイルの置き場は環境変数 V3_DATA・V3_RAW・V3_MODELS・V3_CYOKYO_CSV・V3_KD(無ければ手元のパス)。
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import t8_forecast as t8  # noqa: E402
import kb_works  # noqa: E402

if sys.platform != 'win32':
    # v8s1_run.wait_mem は Windows の tasklist で他の python を待つ。便(Linux)には tasklist が無い = 待たない(1 本しか走らない)
    t8.s1.wait_mem = lambda: None

MODEL_ID = 'v3-8'
TIMING = 'morning'
STAMP = 't7e_Y1/Y3+t8_s2(2022-01〜2026-08)'
MK = ['◎', '○', '▲', '△']


def log(*a):
    print('[v3]', *a, flush=True)


def build_rows(csv_path, day, src):
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    rows = []
    for (tr, rd, rno), g in x.groupby(['track', 'race_date', 'race_no'], sort=False):
        g = g.sort_values('rank', kind='mergesort')
        marks = [{'num': int(r.umaban), 'mark': r.mark, 'score': round(float(r.p3p) * 100, 1)}
                 for r in g.itertuples() if r.mark in MK]
        runners = [{'num': int(r.umaban), 'p1': round(float(r.p1), 4), 'p3': round(float(r.p3p), 4),
                    'p3_raw': round(float(r.p3), 4)} for r in g.sort_values('umaban').itertuples()]
        meta = {'n': int(len(g)), 'model': MODEL_ID, 'stamp': STAMP, 'works_src': src, 'runners': runners}
        rows.append({'track': tr, 'race_date': str(day), 'race_no': int(rno), 'marks': marks, 'meta': meta})
    return rows


def main():
    a = sys.argv[1:]
    day, out = a[0], Path(a[1])
    write = '--write' in a
    if kb_works.enabled():
        kb_works.install(t8, hi=day)
        src = 'nar_kb_works'
    else:
        src = 'json'
    log('day', day, 'works', src, 'write', write)
    t8.table(day, 'pre', str(out))
    csv_path = out / f'{day}_第8版_前日版.csv'
    rows = build_rows(csv_path, day, src)
    log('races', len(rows), '◎', ' '.join(f"{r['track']}{r['race_no']}R:{r['marks'][0]['num']}" for r in rows[:12] if r['marks']))
    (out / f'{day}_v3-8_marks.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    if write and rows:
        sys.path.insert(0, str(HERE.parent))
        import base_v1 as B1
        B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(predict_v2 と同じ作法)
        took = B1.write_marks(rows, day, TIMING)
        log('took', took)


if __name__ == '__main__':
    main()

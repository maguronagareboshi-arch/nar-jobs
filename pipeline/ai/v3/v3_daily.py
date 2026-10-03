# -*- coding: utf-8 -*-
"""南関 AI v3 第 9 版(人気を見ない版・182 列)の毎日の前日版(= t9_forecast.py table DATE pre)を便で回す入口。学習はしない。

  python -X utf8 pipeline/ai/v3/v3_daily.py DATE OUTDIR [--write]

1. 追い切りの毎日の分: 鍵(SUPABASE_URL・SUPABASE_SERVICE_KEY)があれば nar_kb_works から(kb_works.install)、
   無ければ(または V3_WORKS_SRC=json)手元の JSON(V3_CYOKYO_JSON)から = 従来の道。
2. t9_forecast.table(DATE, 'pre', OUTDIR) → OUTDIR/DATE_第9版_前日版.csv・.md(追い切り・材料の差し替えは t8 の関数に入れる = t9 が呼ぶ)
3. --write のときだけ nar_ai_marks に model='v3-9'・timing='morning' で書く(base_v1.write_marks = 朝の行は凍結・読み直し)。
   marks = 印の付いた馬(◎○▲△・順位の順)・score = 3 着以内の確率 p3′ × 100。
   meta = n・model・stamp・works の元・runners(全馬の num・p1 = 勝つ確率・p3 = 3 着以内の確率 p3′(表の値)・p3_raw = 上乗せ後の p3)。
   runners には札のある馬だけ note(公式の成績と発走状況から)・note_kb(競馬ブックの寸評から)を足す(v3_notes・表示だけ)。
固定ファイルの置き場は環境変数 V3_DATA・V3_RAW・V3_MODELS・V3_CYOKYO_CSV・V3_KD(無ければ手元のパス)。
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import t8_forecast as t8  # noqa: E402
import t9_forecast as t9  # noqa: E402  (import 時に t7e の列を 182・模型の名前を t9 に差し替える)
import kb_works  # noqa: E402

if sys.platform != 'win32':
    # v8s1_run.wait_mem は Windows の tasklist で他の python を待つ。便(Linux)には tasklist が無い = 待たない(1 本しか走らない)
    t8.s1.wait_mem = lambda: None

MODEL_ID = 'v3-9'
TIMING = 'morning'
STAMP = 't9_Y1/Y3(182 列・j7_last_pop なし)+t9_s2(2022-01〜2026-08)+t10 上乗せ+談話の印 3 定数(v13y)'
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


def table_digest(csv_path):
    """照合用(公開ログに表は出さない): ◎ の馬番と、全馬の (race_no, 馬番, p1, p3 を小数 4 桁) を並べた sha256。"""
    import hashlib
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    x = x.sort_values(['race_no', 'umaban'], kind='mergesort')
    hon = ' '.join(f"{int(r.race_no)}:{int(r.umaban)}" for r in x.itertuples() if r.mark == '◎')
    body = '\n'.join(f"{int(r.race_no)},{int(r.umaban)},{float(r.p1):.4f},{float(r.p3):.4f}" for r in x.itertuples())
    return hon, hashlib.sha256(body.encode('utf-8')).hexdigest()


def _dump_feats(day, out):
    """t8.table の中の e7.features と t8.cy_feats の戻り値をその日の分だけ out/feat_*.csv に書く(写した台本は変えない)。"""
    out.mkdir(parents=True, exist_ok=True)

    def cut(df):
        return df[df.race_date.astype(str).str[:10] == str(day)] if 'race_date' in df.columns else df

    f0, c0 = t8.e7.features, t8.cy_feats

    def f1(*a, **k):
        r = f0(*a, **k)
        cut(r[0]).to_csv(out / 'feat_T.csv', index=False, encoding='utf-8-sig')
        return r

    def c1(*a, **k):
        r = c0(*a, **k)
        cut(r).to_csv(out / 'feat_F.csv', index=False, encoding='utf-8-sig')
        return r
    t8.e7.features, t8.cy_feats = f1, c1


def _capture(cap):
    """v29(市場のずれ模型)の前日の土台のために、t9.table の中の e7.features の (h, T) と t8.cy_feats の F を控える(値は変えない)。"""
    f0, c0 = t8.e7.features, t8.cy_feats

    def f1(h, races, *a, **k):
        r = f0(h, races, *a, **k)
        cap['h'], cap['T'], cap['races'] = h, r[0], races
        return r

    def c1(*a, **k):
        r = c0(*a, **k)
        cap['F'] = r
        return r
    t8.e7.features, t8.cy_feats = f1, c1


def main():
    a = sys.argv[1:]
    if a and a[0] == 'digest':  # 手元で同じ関数を使う: python v3_daily.py digest <csv>
        hon, h = table_digest(a[1])
        log('digest ◎', hon, 'sha256', h)
        return
    day, out = a[0], Path(a[1])
    write = '--write' in a
    if kb_works.enabled():
        kb_works.install(t8, hi=day)
        src = 'nar_kb_works'
    else:
        src = 'json'
    log('day', day, 'works', src, 'write', write)
    if __import__('os').environ.get('V3_DUMP_FEATS') == '1':  # 照合用: 材料(T・調教 F)をその日の分だけ csv に出す
        _dump_feats(day, out)
    cap = {}
    _capture(cap)
    t9.table(day, 'pre', str(out))
    csv_path = out / f'{day}_第9版_前日版.csv'
    try:  # v29 の前日の土台(失敗しても予想の表と書き込みは止めない)
        import v29_gap
        vb = v29_gap.base(day, cap['h'], cap['T'], cap.get('F'), csv_path)
        try:  # v31: 前に捨てた材料の前日版 51 本(失敗しても v29 の土台は書く = 模型は欠けとして読む)
            import time as _t
            import v31_bundle
            t0 = _t.time()
            F51 = t9.LAST_F51.get(day)  # 第 10 版の上乗せで作った分を使い回す(無ければ作る)
            if F51 is None:
                F51 = v31_bundle.feats51(day, cap['h'], cap['races'], log=log)
            vb = vb.merge(F51, on=['track', 'race_date', 'race_no', 'umaban'], how='left', validate='1:1')
            log('v31 51 本', F51.shape, '秒', round(_t.time() - t0), 'あり率', round(float(F51.drop(columns=['track', 'race_date', 'race_no', 'umaban']).notna().mean().mean()), 3))
        except Exception as e:  # noqa: BLE001
            log('v31 51 本 失敗', type(e).__name__, str(e)[:200])
        vb.to_csv(out / f'{day}_v29_base.csv', index=False, encoding='utf-8-sig')
        log('v29 base', len(vb), '頭', 'hist', round(float(vb.bw_norm.notna().mean()), 3))
    except Exception as e:  # noqa: BLE001
        log('v29 base 失敗', type(e).__name__, str(e)[:200])
    try:  # 談話の印の 3 定数(v13y・2026-10)= 印と p3′ だけ。v29 の土台・v31 は上の第10版のまま(土台には dw_u を足す = 当日版の印が使う)
        import danwa_marks
        danwa_marks.apply_csv(csv_path, day, base_csv=out / f'{day}_v29_base.csv', log=log)
    except Exception as e:  # noqa: BLE001
        log('談話の印 失敗(第10版のまま)', type(e).__name__, str(e)[:200])
    notes = {}
    try:  # ひとこと(表示だけ・予想の計算には使わない・失敗しても予想の表と書き込みは止めない)
        import v3_notes
        notes = v3_notes.make(day, cap['h'], cap['T'], log=log)
    except Exception as e:  # noqa: BLE001
        log('ひとこと 失敗', type(e).__name__, str(e)[:200])
    del cap
    rows = build_rows(csv_path, day, src)
    if notes:
        log('ひとこと 付けた', v3_notes.attach(rows, notes), '頭')
    log('races', len(rows), '◎', ' '.join(f"{r['track']}{r['race_no']}R:{r['marks'][0]['num']}" for r in rows[:12] if r['marks']))
    hon, h = table_digest(csv_path)
    log('digest ◎', hon, 'sha256', h)
    (out / f'{day}_v3-9_marks.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    if write and rows:
        sys.path.insert(0, str(HERE.parent))
        import base_v1 as B1
        B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(predict_v2 と同じ作法)
        took = B1.write_marks(rows, day, TIMING)
        log('took', took)


if __name__ == '__main__':
    main()

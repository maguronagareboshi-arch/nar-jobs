# -*- coding: utf-8 -*-
"""南関 AI v3 第 9 版(人気を見ない版・182 列)の毎日の前日版(= t9_forecast.py table DATE pre)を便で回す入口。学習はしない。

  python -X utf8 pipeline/ai/v3/v3_daily.py DATE OUTDIR [--write]

1. 追い切りの毎日の分: 鍵(SUPABASE_URL・SUPABASE_SERVICE_KEY)があれば nar_kb_works から(kb_works.install)、
   無ければ(または V3_WORKS_SRC=json)手元の JSON(V3_CYOKYO_JSON)から = 従来の道。
2. t9_forecast.table(DATE, 'pre', OUTDIR) → OUTDIR/DATE_第9版_前日版.csv・.md(追い切り・材料の差し替えは t8 の関数に入れる = t9 が呼ぶ)
2b. 談話の印 3 定数(danwa_marks)→ 束 t14(t14_bundle・第11版・2026-10)を前日の表に足す(どちらも失敗したら前のまま)。
2c. 束 t14 を足せた日だけ、束 f10k(f10k_bundle・第12版・材料 1 万個のふるいの 60 列の木・2026-10)を足す(失敗・見張りで止まったら第11版のまま)。
2a. --write のときだけ、走破指数 SI5(表の材料と同じ値)の直近 21 日分を nar_si5 に書く(si5_store・サイトの「指数」の列)。
3. --write のときだけ nar_ai_marks に model='v3-9'・timing='morning' で書く(ai_common.write_marks = 朝の行は凍結・読み直し)。
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
STAMP11 = STAMP + '+束 t14(37 列の木・学び 2023-01〜2026-08)'  # 第11版(束を足せた日だけ)
STAMP12 = STAMP11 + '+束 f10k(60 列の木・学び 2023-01〜2026-08)'  # 第12版(束 t14 と f10k を両方足せた日だけ)
STAMP_DEB = '+初出走の層(寸評・時計 35 列の木・学び 2023-01〜2026-08)'  # 決め 28(初出走のいる日だけ)
MK = ['◎', '○', '▲', '△']
STAMP_TPL = '+短評の層(段・型・前走の段 15 列の木 2 本・学び 2023-01〜2026-08)'  # 決め 30(勝つ率の直しの後・足せた日だけ)
TPL_TAG = 'tpl 決め30 短評の層'  # tanpyo_live.TAG と同じ字
STAMP_AW = '+併せの相手(最終追いの先着/遅れ + 秒差)'  # 決め 60(短評の層の後・相手の行のあるレースだけ)
AW_TAG = '決め60 併せの相手'  # awase_live.TAG と同じ字
STAMP_SQ = '+並び読みの前日分(当日の 8 列を空にして前日の木の上で学び直し)'  # 決め 63(併せの相手の層の後・足せたレースだけ)
SQ_TAG = '決め63 前日版の並び読み'
STAMP_CAP = '+勝つ率の守り(勝つ率 ≦ 3 着内の率)'  # 決め 67-2(全部の段の後・守りを通した日)
CAP_TAG = '決め67-2 勝つ率の守り'  # p1cap.TAG と同じ字
STAMP_G68 = '+枠の内外の有利の直し(場 × 枠の前 56 日 + 同じ開催の前の日まで・前の日を含まない)'  # 決め 68(前日版の並び読みの後・勝つ率の守りの前)
STAMP_PT = '+3 着内の率の温度(なだらかに・勝つ率は動かさない)'  # 決め 69(枠の内外の有利の直しの後・勝つ率の守りの前)
STAMP_PM = '+勝つ率に 3 着内の率を混ぜる(3 着内の率・印は動かさない)'  # 決め 71(3 着内の率の温度の後・勝つ率の守りの前)
STAMP_PT74 = '+前日の一本の木 5 割(当日の 8 列なし・勝つ率は付いていく)+前日の F3 2 割'
STAMP_PT76 = '+前日の一本の木 5 割(種 3 本の平均・調教の元の記録 88 列・当日の 8 列なし・勝つ率は付いていく)+前日の F3 2 割'  # 決め 74(勝つ率の守りの後・混ぜたレースだけ = 南関 第27版 前日版)
STAMP_NK675 = '+能力試験の記録を台帳に無い馬にも結ぶ(決め 67-5)'  # 2026-11-09 第29版 前日版 = 第28版 前日版 + 能検の結びの直し(台帳 KDSCOPE が 2026-03 で止まった穴)


def log(*a):
    print('[v3]', *a, flush=True)


def build_rows(csv_path, day, src, stamp=STAMP):
    x = pd.read_csv(csv_path, encoding='utf-8-sig')
    rows = []
    for (tr, rd, rno), g in x.groupby(['track', 'race_date', 'race_no'], sort=False):
        g = g.sort_values('rank', kind='mergesort')
        marks = [{'num': int(r.umaban), 'mark': r.mark, 'score': round(float(r.p3p) * 100, 1)}
                 for r in g.itertuples() if r.mark in MK]
        runners = [{'num': int(r.umaban), 'p1': round(float(r.p1), 4), 'p3': round(float(r.p3p), 4),
                    'p3_raw': round(float(r.p3), 4)} for r in g.sort_values('umaban').itertuples()]
        meta = {'n': int(len(g)), 'model': MODEL_ID, 'stamp': stamp, 'works_src': src, 'runners': runners}
        if 'dbt_pre_u' in g.columns and g.dbt_pre_u.notna().any():  # 初出走の層を足したレース = 足した頭数(表の行で確かめる)
            meta['debut'] = int(g.dbt_pre_u.notna().sum())
        if 'p1_t10' in g.columns and g.p1_t10.notna().all():  # 勝つ率の直し(決め 29)を掛けたレース = p1 は直した値・元は p1_t10
            import p1_follow  # 記録の字 = p1_follow.TAG['pre'](暗号化した定数)
            meta['p1f'] = p1_follow.TAG['pre']
        if 'tpl_u3' in g.columns and (g.tpl_u3.fillna(0) != 0).any():  # 短評の層(決め 30)を足したレース = 元の率は p3p_tpl0・p1_tpl0
            meta['tpl'] = TPL_TAG
        if 'aw60_n' in g.columns and g.aw60_n.fillna(0).max() > 0:  # 併せの相手(決め 60)を足したレース = 元の率は p3p_aw0・p1_aw0
            meta['aw60'] = AW_TAG
            meta['aw60_n'] = int(g.aw60_n.max())
        if 'sq_u' in g.columns and g.sq_u.notna().any():  # 前日版の並び読み(決め 63)を足したレース = 元の率は p3p_sq0・p1_sq0
            meta['sq63'] = SQ_TAG
        if 'g68_a' in g.columns and g.g68_a.notna().all():  # 枠の内外の有利の直し(決め 68)を足したレース = 元の率は p3p_g0・p1_g0(次の日からの窓の元)
            import gate68_live  # 記録の字 = gate68_live.tag()(暗号化した定数)
            meta['g68'] = {'tag': gate68_live.tag(), 'lag': 1, 'a': {str(int(r.umaban)): round(float(r.g68_a), 4) for r in g.itertuples()},
                           'p0': {str(int(r.umaban)): round(float(r.p3p_g0), 6) for r in g.itertuples()},
                           'q0': {str(int(r.umaban)): round(float(r.p1_g0), 6) for r in g.itertuples()}}
        if 'p3p_pt0' in g.columns:  # 3 着内の率の温度(決め 69)を掛けたレース = 直しの前の 3 着内の率(次の日からの枠の直しの窓の元は p0 のまま)
            import pre69_live  # 記録の字 = pre69_live.tag()(暗号化した定数)
            meta['pt69'] = {'tag': pre69_live.tag(), 'p3_before': {str(int(r.umaban)): round(float(r.p3p_pt0), 6) for r in g.itertuples()}}
        if 'pm71' in g.columns and (g.pm71 == 1).all():  # 勝つ率に 3 着内の率を混ぜたレース(決め 71)= 混ぜる前の勝つ率(= 第24版の勝つ率・下流で混ぜる前の率で学んだ物はこちらを読む)
            import p1mix71_live  # 記録の字 = p1mix71_live.tag()(暗号化した定数)
            meta['pm71'] = {'tag': p1mix71_live.tag(), 'p1_before': {str(int(r.umaban)): round(float(r.p1_pm0), 6) for r in g.itertuples()}}
        if 'p1_cap0' in g.columns:  # 勝つ率の守り(決め 67-2)を通したレース = 元の勝つ率は p1_cap0・動かした頭数
            meta['p1cap'] = CAP_TAG
            meta['p1cap_n'] = int(((g.p1_t74 if 'p1_t74' in g.columns else g.p1) != g.p1_cap0).sum())   # 決め 74 の段の前の勝つ率で数える
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
    try:  # 束 t14 のために土台 U と nar_kb_works の行を控える(計算は変えない)
        import t14_bundle
        t14_bundle.install()
    except Exception as e:  # noqa: BLE001
        log('束 t14 の控え 失敗', type(e).__name__, str(e)[:200])
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
    try:  # 走破指数 SI5 を控える(サイトの「指数」の列・計算は変えない・2026-10-26)
        import si5_store
        si5_store.install()
    except Exception as e:  # noqa: BLE001
        log('SI5 の控え 失敗', type(e).__name__, str(e)[:200])
    t9.table(day, 'pre', str(out))
    if __import__('os').environ.get('V3_SI5_DUMP'):  # 照合・過去分の書き込み用: 控えた SI5 を全期間 parquet に出す(手元だけ)
        si5_store.frame().to_parquet(__import__('os').environ['V3_SI5_DUMP'])
    si5_all = __import__('os').environ.get('V3_SI5_ALL') == 'yes'
    if write or si5_all:
        try:  # 直近 21 日(si5_all = 2014〜前日の全部)の南関の SI5 を nar_si5 へ(失敗しても予想の表と書き込みは止めない)
            si5_store.write(day, days=None if si5_all else si5_store.DAYS)
        except Exception as e:  # noqa: BLE001
            log('SI5 の保存 失敗', type(e).__name__, str(e)[:200])
        try:  # 10/26 南関の日の馬場の速さ D5 を nar_meta nankan_d5 へ(サイトの馬場差を予想 AI にそろえる・失敗しても止めない)
            si5_store.write_d5(day, days=None if si5_all else si5_store.DAYS)
        except Exception as e:  # noqa: BLE001
            log('D5 の保存 失敗', type(e).__name__, str(e)[:200])
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
    try:  # 勝つ率の直し(決め 29)が使う木の 3着内 p3p_t10 を、上乗せの前に控える(談話の印が書くのと同じ値・談話が落ちても残る)
        _t = pd.read_csv(csv_path, encoding='utf-8-sig')
        if 'p3p_t10' not in _t.columns:
            _t['p3p_t10'] = _t.p3p
            _t.to_csv(csv_path, index=False, encoding='utf-8-sig')
    except Exception as e:  # noqa: BLE001
        log('木の 3着内の控え 失敗', type(e).__name__, str(e)[:200])
    try:  # 談話の印の 3 定数(v13y・2026-10)= 印と p3′ だけ。v29 の土台・v31 は上の第10版のまま(土台には dw_u を足す = 当日版の印が使う)
        import danwa_marks
        danwa_marks.apply_csv(csv_path, day, base_csv=out / f'{day}_v29_base.csv', log=log)
    except Exception as e:  # noqa: BLE001
        log('談話の印 失敗(第10版のまま)', type(e).__name__, str(e)[:200])
    bundle = False
    try:  # 束 t14(第11版・Glicko 18・事実 5・談話 14 の木・研究 nankan-ai-v3 t14・ユーザー承認 2026-10-10)。v29 の土台は第10版のまま
        import t14_bundle
        bundle = t14_bundle.run(day, cap['h'], cap['races'], cap['T'], csv_path, log=log)
    except Exception as e:  # noqa: BLE001
        log('束 t14 失敗(第10版 + 談話の印のまま)', type(e).__name__, str(e)[:200])
    b12 = False
    if bundle:
        try:  # 束 f10k(第12版・研究 nankan-ai-v3 f10k・ユーザー承認 2026-10-11)。第11版の上で学んだ木なので束 t14 を足せた日だけ
            import f10k_bundle
            b12 = f10k_bundle.run(day, cap['h'], cap['races'], csv_path, log=log)
        except Exception as e:  # noqa: BLE001
            log('束 f10k 失敗(第11版のまま)', type(e).__name__, str(e)[:200])
    PNX77 = None
    if b12:  # 決め 77(南関 第28版 直前版)の前日の土台 p_Nx = 束 f10k の直後・初出走の層の前の 3 着内率を控える(読むだけ・前日版の表は変えない)
        try:
            import dayonpre77_live
            PNX77 = dayonpre77_live.capture_pnx(csv_path)
        except Exception as e:  # noqa: BLE001
            log('決め 77 の前日の土台の控え 失敗(直前版は第26版のまま)', type(e).__name__, str(e)[:200])
    if bundle:  # 当日版も第12版に(研究 nankan-ai-v3 own_day.py・2026-10-12): 束の足し分 b14_u・b19_u を土台へ。当日の便が当日の木の後に足す
        try:
            bp = out / f'{day}_v29_base.csv'
            tb = pd.read_csv(csv_path, encoding='utf-8-sig')
            vb = pd.read_csv(bp, encoding='utf-8-sig').drop(columns=['b14_u', 'b19_u'], errors='ignore')
            k4 = ['track', 'race_date', 'race_no', 'umaban']
            for d_ in (tb, vb):
                d_['race_date'] = d_.race_date.astype(str).str[:10]
            add = tb[k4 + [c for c in ('b14_u', 'b19_u') if c in tb.columns and (c == 'b14_u' or b12)]]
            vb = vb.merge(add, on=k4, how='left', validate='1:1')
            vb.to_csv(bp, index=False, encoding='utf-8-sig')
            log('当日版へ束の足し分', [c for c in ('b14_u', 'b19_u') if c in vb.columns], 'あり率', round(float(vb['b14_u'].notna().mean()), 3))
        except Exception as e:  # noqa: BLE001
            log('当日版へ束の足し分 失敗(当日版は第10版 + 体重のまま)', type(e).__name__, str(e)[:200])
    if b12:  # 並び読み(決め 24・研究 nankan-ai-v3 seq2_day.py・seq2_prod_fit.py・2026-10-12): 第12版の上で学んだので束 f10k を足せた日だけ
        try:  # 公式の表(V3_OFFICIAL)と土台 U から、その日の南関の出走馬の過去 10 走 → out/DAY_seq2.npz(当日の便が第12版の後に足す)
            import t14_bundle
            import seq2_live
            if (seq2_live.SEQ2 / 'seq2_std.csv').exists() and not (seq2_live.OFFICIAL / 'runs.parquet').exists():
                sys.path.append(str(HERE.parent / 'kochi'))  # 末尾に足す = v3 の同じ名前の台本を隠さない
                import k0_dl  # 公式の表(全場・中央)を落とす = 読むだけ・約 3 分(便ではこの手順にだけ鍵がある)
                seq2_live.OFFICIAL.mkdir(parents=True, exist_ok=True)
                k0_dl.main([str(seq2_live.OFFICIAL).replace('\\', '/'), 'races', 'runs', 'jra', 'jrah'])
            seq2_live.prep(day, t14_bundle.CACHE.get('U'), out, log=log)
        except Exception as e:  # noqa: BLE001
            log('並び読み 失敗(当日版は第12版のまま)', type(e).__name__, str(e)[:200])
    nd = 0
    if b12:  # 初出走の層(決め 28・研究 nankan-ai-v3 debut_tp.py・debut_prod_fit.py・ユーザー承認 2026-10-14): 第12版の前日の表を直し、直前版の外した分 dbt_u を土台へ
        try:
            import debut_live
            nd = debut_live.run(day, cap['T'], cap.get('F'), csv_path, out / f'{day}_v29_base.csv', t8._W.get('parsed'), t8.works()[0], log=log)
        except Exception as e:  # noqa: BLE001
            log('初出走の層 失敗(第12版のまま)', type(e).__name__, str(e)[:200])
    try:  # 勝つ率の直し(決め 29・研究 nankan-ai-v3 p1_fix.py・2026-10-14): 上乗せを全部足した後に p1 を 3着内に付いて行かせる。
        #   v29 の土台・v31・v3_tri は上で第10版の p1 を読み済み(学んだ時と同じ = 変えない)
        import p1_follow
        p1_follow.apply_csv(csv_path, log=log)
    except Exception as e:  # noqa: BLE001
        log('勝つ率の直し 失敗(木の勝つ率のまま)', type(e).__name__, str(e)[:200])
    nt = 0
    if b12:  # 全馬の短評の層(決め 30・研究 nankan-ai-v3 tanpyo_layer.py・tanpyo_prod.py・ユーザー承認 2026-10-14): 勝つ率の直しの後に
        #   前日の表の p3′・p1 を直し、直前版の材料 tpl_ を土台へ(当日の便が勝つ率の直しの後に足す)。失敗しても前の段のまま
        try:
            import tanpyo_live
            nt = tanpyo_live.run(day, cap['T'], cap.get('F'), csv_path, out / f'{day}_v29_base.csv', t8._W.get('parsed'), log=log)
        except Exception as e:  # noqa: BLE001
            log('短評の層 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    if nt:  # 平らな模型 F3 の混ぜ(決め 49・研究 nankan-ai-v3 blend_f3_polish3.py・f3_prod_fit.py・ユーザー承認 2026-10-22): 直前版だけ。
        #   部品(束 t14・f10k・短評の層・初出走の層)が作った表から 284 列を v29 の土台へ。当日の便が状況の印の後に混ぜる。前日版は変えない
        try:
            import f3_live
            import t14_bundle
            import f10k_bundle
            import debut_live
            import tanpyo_live
            f3_live.LAST.update(t14=t14_bundle.LASTF.get(day), f10k=f10k_bundle.LASTF.get(day), tanpyo=tanpyo_live.LASTD.get(day),
                                debut=debut_live.LASTD.get(day))
            f3_live.run(day, cap['h'], out / f'{day}_v29_base.csv', log=log)
        except Exception as e:  # noqa: BLE001
            log('F3 の材料 失敗(当日は前の段のまま)', type(e).__name__, str(e)[:200])
        try:  # 一本の木の段 1 の材料(決め 72・研究 nankan-ai-v3 onetree72_prod.py・判定 2026-11-06 合格): 直前版だけ。t9.table の材料 T のその日の
            #   182 列を v29 の土台へ 'OT:'(F3 の列は上の 'F3:' をそのまま使う)。当日の便が第23版の後に混ぜる。前日版は変えない。失敗しても当日は第23版のまま
            import onetree72_live
            onetree72_live.run_pre(day, cap['T'], out / f'{day}_v29_base.csv', log=log)
        except Exception as e:  # noqa: BLE001
            log('一本の木の材料 失敗(当日は第23版のまま)', type(e).__name__, str(e)[:200])
    naw = 0
    A_aw = None
    if nt:  # 併せ馬の相手の層(決め 60・研究 nankan-ai-v3 awase60_pre.py・ユーザー承認 2026-10-28 = 前日版は例外で採る): 短評の層の後の最後の段。
        #   その日の nar_kb_works の相手の行(partners)・前日版の上で学んだ重み(暗号化の定数)。失敗しても前の段のまま
        try:
            import awase_live
            A, n_aw = awase_live.load(day)
            log('併せの相手', f'相手の行のある馬 {len(A)} / 調教の行 {n_aw}')
            naw = awase_live.apply_csv_pre(A, csv_path, log=log)
            A_aw = A   # 決め 74 の一本の木の側の併せ馬が同じ相手の行を使う
        except Exception as e:  # noqa: BLE001
            log('併せの相手 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    nsq = 0
    if nt:  # 前日版の並び読み(決め 63・研究 nankan-ai-v3 pre_seq_judge_1030.py・pre_seq_prod_fit.py・ユーザー承認 2026-10-30): 併せの相手の層の後の最後の段。
        #   上の並び読みの材料(out/DAY_seq2.npz)を前日版の重み(V3_SEQ2 の seqpre_*)で読む。失敗しても前の段のまま
        try:
            import seq2_live
            import seqpre_live
            SQ = seqpre_live.load(seq2_live.SEQ2, out / f'{day}_seq2.npz')
            if SQ is None:
                log('前日版の並び読み 重みか材料なし(前の段のまま)')
            else:
                nsq = seqpre_live.apply_csv_pre(SQ, csv_path, log=log)
        except Exception as e:  # noqa: BLE001
            log('前日版の並び読み 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    ng = 0
    G68m = None
    if b12 and nt and nsq:  # 枠の内外の有利の直し(決め 68・研究 nankan-ai-v3 gate68_judge.py・ユーザー採用 2026-11-03 = 前日版にも §8 の条件で入れる): 前日版の並び読みの後・
        #   勝つ率の守りの前。前 56 日の朝の行(meta.g68.p0 か runners の p3)と nar_runs の結果から場 × 枠の a(前の日を含まない)。失敗しても前の段のまま
        try:
            import gate68_live
            G68m = gate68_live.load(day, 'morning', log=log)
            ng = gate68_live.apply_csv_pre(G68m, csv_path, log=log)
        except Exception as e:  # noqa: BLE001
            log('枠の内外の有利の直し 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    npt = 0
    if ng:  # 3 着内の率の温度(決め 69・研究 nankan-ai-v3 pre69_judge.py・ユーザー承認 2026-11-04): 枠の内外の有利の直しの後・勝つ率の守りの前。
        #   土台が第23版の時だけ(研究の土台 = 決め 68 の後)。p3 = sig(a·logit p3 + k)・勝つ率は動かさない。失敗しても前の段のまま
        try:
            import pre69_live
            npt = pre69_live.apply_csv_pre(csv_path, log=log)
        except Exception as e:  # noqa: BLE001
            log('3 着内の率の温度 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    npm = 0
    if ng and npt:  # 勝つ率に 3 着内の率を混ぜる(決め 71・研究 nankan-ai-v3 p1mix71_judge.py・判定 2026-11-05 合格・ユーザー承認 11/5): 温度の後・勝つ率の守りの前。
        #   土台が第24版の時だけ(研究の土台 = 決め 69 の後)。p1 ∝ exp(B·ln p1 + BETA·logit p3)・3 着内の率は動かさない。失敗しても前の段のまま
        try:
            import p1mix71_live
            npm = p1mix71_live.apply_csv_pre(csv_path, log=log)
        except Exception as e:  # noqa: BLE001
            log('勝つ率の混ぜ 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    ncap = None
    try:  # 勝つ率 ≦ 3 着内の率 の守り(決め 67-2・研究 nankan-ai-v3 correct67_2_guard.py・ユーザー承認 2026-11-01): 全部の段の後
        import p1cap
        ncap = p1cap.apply_csv(csv_path, log=log)
    except Exception as e:  # noqa: BLE001
        log('勝つ率の守り 失敗(前の段のまま)', type(e).__name__, str(e)[:200])
    notes = {}
    try:  # ひとこと(表示だけ・予想の計算には使わない・失敗しても予想の表と書き込みは止めない)
        import v3_notes
        notes = v3_notes.make(day, cap['h'], cap['T'], log=log)
    except Exception as e:  # noqa: BLE001
        log('ひとこと 失敗', type(e).__name__, str(e)[:200])
    cyb = {}
    try:  # 調教の札(表示だけ・cy_day_pct の 4 段・cy_band.py・ユーザー承認 2026-11-04)
        import cy_band
        cyb = cy_band.make(cap.get('F'))
    except Exception as e:  # noqa: BLE001
        log('調教の札 失敗', type(e).__name__, str(e)[:200])
    del cap
    ver = '南関 第21版 前日版' if b12 and nt and nsq and ncap is not None else '南関 第20版 前日版' if b12 and nt and nsq else '南関 第19版 前日版' if b12 and nt and naw else '南関 第15版 前日版' if b12 and nt else '南関 第12版 前日版' if b12 else '南関 第11版 前日版' if bundle else '南関 第10版 前日版'  # 版の名前(研究 nankan-ai-v3 VERSIONS.md)
    import c67_cancel
    c67 = c67_cancel.c67_tag() if ver == '南関 第21版 前日版' else None  # 決め 67-1(砂替えと取りやめの直し・直した重み)
    if c67:
        ver = '南関 第25版 前日版' if ng and npt and npm else '南関 第24版 前日版' if ng and npt else '南関 第23版 前日版' if ng else '南関 第22版 前日版'  # 第23版 = 第22版 + 枠の内外の有利の直し(決め 68)・第24版 = 第23版 + 3 着内の率の温度(決め 69)・第25版 = 第24版 + 勝つ率の混ぜ(決め 71)
    PT74 = {}
    if ver == '南関 第25版 前日版' and G68m is not None:  # 前日版の作り直し(決め 74・研究 nankan-ai-v3 preday74_judge.py・preday74_prod.py・判定 2026-11-06 合格):
        #   第25版の最後(勝つ率の守りの後)に前日の一本の木 5 割 + 前日の F3 2 割(1 つの段)。混ぜたレースだけ「南関 第27版 前日版」。
        #   混ぜる日(定数 pt74.ON)の前は率を変えず meta.pt74.p0 だけ残す(一本の木の側の枠の窓をためる)。失敗しても第25版のまま
        try:
            import preday74_live
            M74 = preday74_live.load()
            if M74 is None:
                log('前日の一本の木 模型なし(第25版のまま)')
            else:
                log('前日の一本の木 読めた', M74.get('cut'), len(M74['cols']), '列・F3', len(M74['F3']['cols']), '列・混ぜる日', preday74_live.consts()['ON'])
                GT74 = preday74_live.load_gate(day, G68m, log=log)
                CY76 = None
                if 'cy' in M74:  # 決め 76: その日の出走表の追い切り欄から調教の元の記録 88 列(出走表の全部の馬・失敗したら決め 74 の木)
                    try:
                        import cy76_live
                        import debut_live
                        Ccy, csrc = debut_live.card_src(day, t8._W.get('parsed'))
                        CY76 = cy76_live.feats(Ccy)
                        log('調教の元の記録', csrc, len(Ccy), '本 →', len(CY76), '頭')
                    except Exception as e:  # noqa: BLE001
                        log('調教の元の記録 失敗(決め 74 の木で作る)', type(e).__name__, str(e)[:200])
                        CY76 = None
                PT74 = preday74_live.apply_csv_pre(M74, GT74, A_aw, day, csv_path, out / f'{day}_v29_base.csv', log=log, cy=CY76)
        except Exception as e:  # noqa: BLE001
            log('前日の一本の木 失敗(第25版のまま)', type(e).__name__, str(e)[:200])
            PT74 = {}
    rows = build_rows(csv_path, day, src, ver + ' = ' + ((STAMP12 + (STAMP_DEB if nd else '') + (STAMP_TPL if nt else '') + (STAMP_AW if naw else '') + (STAMP_SQ if nsq else '') + (STAMP_G68 if ng else '') + (STAMP_PT if npt else '') + (STAMP_PM if npm else '') + (STAMP_CAP if ncap is not None else '')) if b12 else (STAMP11 if bundle else STAMP)))
    for r in rows if c67 else ():
        r['meta']['c67'] = c67
    n74 = n76 = 0
    try:  # 2026-11-11 決め 79: 直前版に調教入りの並び読みを足す日から前日版も同じ番号(第30版・前日版の中身は第29版と同じ)
        import cy79_live
        v30 = cy79_live.is_on(day)
    except Exception:  # noqa: BLE001
        v30 = False
    v29n = '南関 第30版 前日版' if v30 else '南関 第29版 前日版'
    for r in rows:  # 決め 74: 混ぜたレースは版の字を第27版に(混ぜないレース・影の日は第25版のまま + meta.pt74.p0)
        m74 = PT74.get((r['track'], int(r['race_no'])))
        if m74 is None:
            continue
        r['meta']['pt74'] = m74
        if m74.get('on'):
            v28 = int(m74.get('ver', 27)) == 28   # 決め 76: 前日の一本の木を種 3 本の平均 + 調教の元の記録 88 列に = 南関 第28版 前日版 → 11/9 決め 67-5 の能検の結びの直しを足して第29版(番号の決まり: 変えたら両方の版を 1 つ上げる)
            r['meta']['stamp'] = r['meta']['stamp'].replace('南関 第25版 前日版', v29n if v28 else '南関 第27版 前日版', 1) + (STAMP_PT76 + STAMP_NK675 if v28 else STAMP_PT74)
            n74 += 1
            n76 += v28
    if PT74:
        log('版', v29n, n76, 'R ・南関 第27版 前日版', n74 - n76, 'R ・第25版のまま', len(rows) - n74, 'R')
    try:  # 決め 77(南関 第28版 直前版・研究 nankan-ai-v3 dayonpre77_judge.py・判定 2026-11-09 合格): 第28版 前日版の最後の率・u_P・p_Nx を土台へ。
        #   当日の便がそのレースの前日版が第28版の時だけ足す。前日版の表と行には触らない。失敗したら直前版は第26版のまま
        import dayonpre77_live
        dayonpre77_live.write_base(csv_path, out / f'{day}_v29_base.csv', PT74, PNX77, log=log)
    except Exception as e:  # noqa: BLE001
        log('決め 77 の土台 失敗(直前版は第26版のまま)', type(e).__name__, str(e)[:200])
    if notes:
        log('ひとこと 付けた', v3_notes.attach(rows, notes), '頭')
    if cyb:
        log('調教の札 付けた', cy_band.attach(rows, cyb), '頭')
    log('races', len(rows), '◎', ' '.join(f"{r['track']}{r['race_no']}R:{r['marks'][0]['num']}" for r in rows[:12] if r['marks']))
    hon, h = table_digest(csv_path)
    log('digest ◎', hon, 'sha256', h)
    (out / f'{day}_v3-9_marks.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    if write and rows:
        sys.path.insert(0, str(HERE.parent))
        import ai_common
        took = ai_common.write_marks(rows, day, TIMING, model=MODEL_ID)
        log('took', took)


if __name__ == '__main__':
    main()

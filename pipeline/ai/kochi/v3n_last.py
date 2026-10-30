# -*- coding: utf-8 -*-
"""他場版 v3n の直前の行 = 朝の行から取消・除外の馬を外して割り直すだけ(2026-10-11・模型は使わない)。

  python -X utf8 pipeline/ai/kochi/v3n_last.py 2026-10-11 [--write] [--only-scratched] [--now "2026-10-11 09:00"]
  python -X utf8 pipeline/ai/kochi/v3n_last.py 2026-10-11 --prep   # 直前便の頭で 1 回 = 並び読みの直前版の材料(today/v3n_seq_prep.npz)
2026-10-12 直前版: 材料と重み(V3N_SEQ_DAY)があれば、体重と馬場が全頭そろったレースで並び読みを当日の値で計算し直す(meta.direct = true)。
2026-10-17 決め 41: 直前版(direct)の第 10 版の行だけ、E1・能検の後の 3 着内率に「今日と同じ騎手で走った時の成績」など 29 個の直線のずらしを足す
(v3n_f41.py・材料は --prep で today/v3n_f41.npz・定数は暗号化の consts.json の v3n_f41・meta.f41)。朝の行・直前版でない行は今までどおり。
2026-10-31 決め 61(第 12 版・meta.rb61 のある朝の行): 取消の後の馬で 2 本目の木の割合 meta.rb61.pm も割り直して混ぜ、勝つ率の直しの k は mo4/di4。
最後に朝の便が数えた有利 a(直前版 = meta.rb61.a_di・直前版でない行 = meta.rb61.a)を印の率と勝つ率に足す(v3n_rb61.shift)。
直す前の率は meta.rb61.fin0・q0・g0 に書き直す(次の日からの直前の窓の元)。DB はここでは読まない。

確かめ(v3 の out/v3n_last3.md): 本番 base-v1 朝 9/8〜10/10・他場 763 R で取消・除外のあるレース 8.7%・
取消の馬に 11.5% が割り振られていた・◎ が取消 12 R → 割り直しで ◎ 71.95 → 73.39%。直前の材料(体重・当日の偏り)は
3 回とも線を通らなかった = 直前に足すのは割り直しだけ。

1. 朝の行(nar_ai_marks・model='v3n-1'・timing='morning')を読む。
2. 本番 nar_runs の finish_note が「出走取消」「競走除外」の馬を外し、meta.p(混ぜた割合)・runners の p1・p3 を
   残りの馬で割り直す(p3 = 3 × 割合・朝と同じ式)。印 5 頭を付け直す。
3. --write のときだけ timing='last' で書く。前の回と外した馬が同じレースは書かない(5 分おきに呼ばれても書くのは変わった時だけ)。
   既定は朝の行のある全レースを書く(取消の無いレースは朝と同じ中身・meta.scratched=[])。--only-scratched で取消のあるレースだけ。
⛔本番に書くのは nar_ai_marks の model='v3n-1'・timing='last' だけ(base_v1.write_marks)。発走 15 分前を過ぎた行は
  DB のトリガー(nar_ai_marks_guard)が捨てる = 最後に通った値が残る。
"""
import datetime as dt
import os
import re
import sys
import urllib.parse
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
MODEL_ID = 'v3n-1'
MARKS = ['◎', '○', '▲', '△', '△']  # v3n_daily と同じ
OUT_NOTES = ('出走取消', '競走除外')   # 走る前に外れる馬だけ(競走中止・失格は走った後)
JST = dt.timezone(dt.timedelta(hours=9))


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def post_at(day, post_time):
    """'1550' / '15:50' → その日の JST の時刻(cloud/ai_last_today.py と同じ読み)。読めなければ None"""
    m = re.fullmatch(r'(\d{1,2}):?(\d{2})', str(post_time or '').strip())
    if not m:
        return None
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(int(m.group(1)), int(m.group(2))), JST)


def q(s):
    return urllib.parse.quote(s)


F41_TAG = '決め41 直前 29 個'  # meta.f41(本番の行で入ったかを確かめる)
SEQ_FORM = ''  # 直前版の並び読みの版(load_day の重みの添え書き)= 行の meta.seq_day に残す(本番の行で版を確かめる)


def relabel(meta, gone, ud=None, sf=None, rk=None):
    """朝の meta と外す馬番の集合 → (marks, 新しい meta)。外すと 1 頭も残らないときは None。
    ud = 直前版の並び読みの外した分(馬番 → logit・当日の馬場と体重入り)。あれば朝の u の代わりに足し meta.direct = True
    sf = 決め 41 の材料(v3n_f41.load)・rk = (場, R)。直前版(ud あり)の第 10 版の行だけ使う"""
    p = {int(k): float(v) for k, v in (meta.get('p') or {}).items()}
    keep = [n for n in sorted(p) if n not in gone]
    if not keep:
        return None
    s = sum(p[n] for n in keep) or 1.0
    c = {n: p[n] / s for n in keep}
    run = {int(r['num']): r for r in (meta.get('runners') or [])}
    s1 = sum(float(run[n]['p1']) for n in keep if n in run) or 1.0
    one = bool(meta.get('one'))  # 第 9 版(イ' 全国 1 本・決め 31)の朝の行 = イの曲線と k(それより前の行は今までどおり)
    if one:
        import v3n_one as cal
    else:
        import k26_cal as cal  # 朝(v3n_daily)と同じ 3 着内の率の曲線
    q3 = dict(zip(keep, cal.p3([c[n] for n in keep], len(keep))))
    rb = meta.get('rb61') or None   # 第 12 版(決め 61)の朝の行 = 2 本目の木の割合を割り直して logit で混ぜる
    if rb is not None:
        import v3n_rb61
        pm = {int(k): float(v) for k, v in (rb.get('pm') or {}).items()}
        assert all(n in pm for n in keep), ('meta.rb61.pm に無い馬', rk)
        sm = sum(pm[n] for n in keep) or 1.0
        q3 = dict(zip(keep, v3n_rb61.lmix([q3[n] for n in keep], v3n_rb61.p3([pm[n] / sm for n in keep], len(keep)))))
    u = {int(k): float(v) for k, v in (ud if ud is not None else (meta.get('u') or {})).items()}
    if u and all(n in u for n in keep):  # 第 6 版: 朝の並び読みの外した分を足す(朝と同じ式・取消の後の頭数で計算し直すのは未対応)
        q3 = {n: min(max(1 / (1 + np.exp(-(np.log(q3[n] / (1 - q3[n])) + u[n]))), 0.001), 0.999) for n in keep}
        key = q3
    else:
        key = q3 if rb is not None else c   # 混ぜた後は今の木の割合 c と並びが同じとは限らない
    # 2026-10-13 第 7 版: 取消の後の頭数で E1 + 能検(朝の meta.noken_z・4 頭未満はかけない)。q3 は meta.p から作り直すので 2 度かからない
    import v3n_e1
    nz = {int(k): float(v) for k, v in (meta.get('noken_z') or {}).items() if int(k) not in gone}
    arr, e1on = v3n_e1.apply([q3[n] for n in keep], [nz.get(n, 0.0) for n in keep])
    q3 = dict(zip(keep, arr))
    if e1on and nz:
        key = q3
    # 2026-10-17 決め 41: 直前版の第 10 版の行だけ、E1・能検の後の q3 に 29 個の直線のずらしを足して合計 3 にそろえる(印もこの順)。
    #   ずらし s は勝つ率の直しの x にも足す(上乗せは勝つ率も一緒に動かす・決め 29 の作法)。材料に無い馬がいる R は足さない。
    fs = None
    if ud is not None and sf is not None and rk is not None and meta.get('one15'):
        import v3n_f41
        try:
            r41 = v3n_f41.race_shift(sf, rk[0], rk[1], keep, [q3[n] for n in keep])
        except Exception as e:  # noqa: BLE001
            print('決め 41 のずらしに失敗', rk, type(e).__name__, str(e)[:120])
            r41 = None
        if r41 is not None:
            q3 = dict(zip(keep, (float(v) for v in r41[0])))
            fs = dict(zip(keep, (float(v) for v in r41[1])))
            key = q3
    # 勝つ率の直し(決め 29): 朝の meta.p1c(直す前の c1)を取消の後の馬で割り直し、x = 並び読み u(直前は u_day)+ 能検 β·z を掛け直す。
    #   表示の p3 = max(p3, p1)(印は key の順のまま)。p1c の無い古い朝の行は今までどおり runners の p1 を割り直す。
    p1n = p1r = mv = rb_new = None
    pc = {int(k): float(v) for k, v in (meta.get('p1c') or {}).items()}
    if pc and all(n in pc for n in keep):
        import v3n_p1
        xs = np.array([(u[n] if (u and all(m in u for m in keep)) else 0.0) + (v3n_e1.BETA_NOKEN * nz.get(n, 0.0) if e1on else 0.0) + (fs[n] if fs is not None else 0.0) for n in keep])
        ver = ('di' if ud is not None else 'mo') + ('4' if rb is not None else '3' if meta.get('trees54') else '2' if meta.get('one15') else '1' if one else '')  # 第 10 版(決め 32)の朝の行 = k mo2・di2・第 11 版(決め 54)= mo3・di3・第 12 版(決め 61)= mo4・di4
        p1n = dict(zip(keep, v3n_p1.follow([pc[n] for n in keep], xs, ver)))
        import v3n_p1mix
        if meta.get('one15') and len(keep) >= v3n_p1mix.MIN_N:  # 決め 40: 画面の勝つ率を 3 着内率(E1・能検の後・max の前)と混ぜる。第 10 版の行だけ・印は key の順のまま
            mv = ('di' if ud is not None else 'mo') + ('3' if meta.get('trees54') else '')  # 決め 54 の行 = 学び直した混ぜ
            p1r = dict(p1n)
            p1n = dict(zip(keep, v3n_p1mix.mix([p1r[n] for n in keep], [q3[n] for n in keep], mv)))
        rb_new = None
        if rb is not None:   # 決め 61: 有利 a を印の率と勝つ率に足す(印もこの順)。直す前の率を残す
            fin0, q0 = dict(q3), dict(p1n)
            av = rb.get('a_di' if ud is not None else 'a') or {}
            a_ = [float(av.get(str(n), 0.0)) for n in keep]
            f2, q2 = v3n_rb61.shift([fin0[n] for n in keep], [q0[n] for n in keep], a_)
            q3, p1n, key = dict(zip(keep, f2)), dict(zip(keep, q2)), dict(zip(keep, f2))
            rb_new = {**{k: ({kk: vv for kk, vv in v.items() if int(kk) not in gone} if isinstance(v, dict) and k not in ('win', 'win_di') else v)
                         for k, v in rb.items()},
                      'tag': v3n_rb61.TAG['di' if ud is not None else 'mo'],
                      'fin0': {str(n): round(float(fin0[n]), 6) for n in keep}, 'q0': {str(n): round(float(q0[n]), 6) for n in keep},
                      'g0': {str(n): round(float(max(fin0[n], q0[n])), 6) for n in keep}}
        q3 = {n: max(q3[n], p1n[n]) for n in keep}
    f0 = str(meta.get('form') or '').replace('+e1+noken', '').replace('+e1', '')
    ks = sum(key.values()) or 1.0
    order = sorted(keep, key=lambda n: (-key[n], keep.index(n)))
    marks = [{'num': n, 'mark': MARKS[i], 'score': round(key[n] / ks * 100, 1)} for i, n in enumerate(order[:5])]
    new = {k: v for k, v in meta.items() if k not in ('p1_raw', 'p1mix', 'f41', 'f41_s')}  # 朝の混ぜの記録は持ち越さない(直前で混ぜた時だけ下で書き直す)
    new.update({
        'n': len(keep),
        'p': {str(n): round(c[n], 4) for n in keep},
        'runners': [{'num': n, 'p1': (round(float(p1n[n]), 4) if p1n is not None else round(float(run[n]['p1']) / s1, 4) if n in run else None),
                     'p3': round(float(q3[n]), 4)} for n in keep],
        'own': {k: v for k, v in (meta.get('own') or {}).items() if int(k) not in gone},
        **({'u': {k: v for k, v in (meta.get('u') or {}).items() if int(k) not in gone}} if meta.get('u') else {}),
        'scratched': sorted(gone),
        'form': f0 + (('+e1+noken' if 'noken_z' in meta else '+e1') if e1on else ''),
        **({'noken_z': {str(k): v for k, v in sorted(nz.items())}} if 'noken_z' in meta else {}),
        'from': 'morning',
        **({'p1c': {str(n): v for n, v in sorted(pc.items()) if n in keep}, 'p1f': v3n_p1.TAG[ver]} if p1n is not None else {}),
        **({'p1_raw': {str(n): round(float(p1r[n]), 6) for n in keep}, 'p1mix': v3n_p1mix.TAG[mv]} if p1r is not None else {}),
        'direct': ud is not None,
        **({'u_day': {str(k): round(float(v), 4) for k, v in ud.items()}} if ud is not None else {}),
        **({'seq_day': SEQ_FORM} if ud is not None and SEQ_FORM else {}),
        **({'f41': F41_TAG, 'f41_s': {str(n): round(fs[n], 4) for n in keep}} if fs is not None else {}),
        **({'rb61': rb_new} if rb_new is not None else {}),
    })
    return marks, new


def day_inputs(day, sb):
    """今日の馬場(場, R → going)と体重(場, R → {馬番: 体重})。直前便の手元の DB(公式の当日 ZIP を重ねた値)を先に読み、
    無ければ本番の REST(nar_runs・nar_races)。"""
    try:
        import pg8000.native
        if not os.environ.get('LOCAL_PGPASSWORD'):
            raise RuntimeError('手元の DB なし')
        con = pg8000.native.Connection(user=os.environ.get('PGUSER', 'postgres'), host=os.environ.get('PGHOST', 'localhost'),
                                       port=int(os.environ.get('PGPORT', '5432')), database=os.environ.get('PGDATABASE', 'postgres'),
                                       password=os.environ['LOCAL_PGPASSWORD'])
        try:
            ra = [dict(zip(('track', 'race_no', 'going'), r)) for r in con.run(
                'select track, race_no, going from public.nar_races where race_date = cast(:d as date)', d=day)]
            ru = [dict(zip(('track', 'race_no', 'runner_number', 'body_weight'), r)) for r in con.run(
                'select track, race_no, runner_number, body_weight from public.nar_runs where race_date = cast(:d as date)', d=day)]
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        ra = sb.get(f'/rest/v1/nar_races?select=track,race_no,going&race_date=eq.{day}&limit=1000')
        ru = sb.get(f'/rest/v1/nar_runs?select=track,race_no,runner_number,body_weight&race_date=eq.{day}&limit=5000')
    going = {(r['track'], int(r['race_no'])): r.get('going') for r in ra}
    bws = {}
    for r in ru:
        if r.get('body_weight'):
            bws.setdefault((r['track'], int(r['race_no'])), {})[int(r['runner_number'])] = float(r['body_weight'])
    return going, bws


def prep(day):
    """直前便の頭(1 回): 公式の表を落として(k0_dl・約 3 分)直前版の並び読みの材料を作る。⛔失敗しても周は続ける"""
    import k0_dl
    import k29_seq_live as SQ
    off = Path(arg('--official', 'today/official'))
    k0_dl.main([str(off).replace('\\', '/'), 'races', 'runs', 'jra', 'jrah', 'profiles'])   # profiles = 決め 41 の父・生産者
    tracks = ['門別', '盛岡', '水沢', '金沢', '笠松', '名古屋', '園田', '姫路', '高知', '佐賀']
    out = SQ.prep_day(off, day, tracks, arg('--prep-file', 'today/v3n_seq_prep.npz'))
    try:  # 2026-10-17 決め 41 の材料(失敗しても周は続ける = 決め 41 を足さないだけ)
        import v3n_f41
        v3n_f41.prep(off, day, tracks, arg('--f41-file', 'today/v3n_f41.npz'))
    except Exception as e:  # noqa: BLE001
        print('決め 41 の材料を作れない = 足さない', type(e).__name__, str(e)[:160])
    return out


def main():
    day = sys.argv[1]
    if '--prep' in sys.argv:
        prep(day)
        return 0
    write, only = '--write' in sys.argv, '--only-scratched' in sys.argv
    import k0_dl
    sb = k0_dl.sb
    # 2026-10-12 直前版: 頭で作った並び読みの材料と重みがあれば、体重と馬場が全頭そろったレースで計算し直す(無ければ取消の割り直しだけ)
    try:
        import k29_seq_live as SQ
        SD = SQ.load_day(arg('--prep-file', 'today/v3n_seq_prep.npz'))
        global SEQ_FORM
        SEQ_FORM = (SD or {}).get('form', '')
    except Exception as e:  # noqa: BLE001
        print('並び読み 直前版を読めない = 取消の割り直しだけ', type(e).__name__, str(e)[:160])
        SD = None
    going, bws = day_inputs(day, sb) if SD is not None else ({}, {})
    SF = None
    try:  # 2026-10-17 決め 41 の材料(--prep で作った npz)
        import v3n_f41
        SF = v3n_f41.load(arg('--f41-file', 'today/v3n_f41.npz'))
    except Exception as e:  # noqa: BLE001
        print('決め 41 の材料を読めない = 足さない', type(e).__name__, str(e)[:160])
    print('決め 41 の材料', '無し' if SF is None else f"{len(SF['ix'])} 頭")
    morning = sb.get(f'/rest/v1/nar_ai_marks?select=track,race_no,marks,meta&model=eq.{MODEL_ID}'
                     f'&timing=eq.morning&race_date=eq.{day}&limit=1000')
    if not morning:
        print('朝の行が無い', day)
        return 0
    notes = ','.join(f'"{x}"' for x in OUT_NOTES)
    scr = sb.get(f'/rest/v1/nar_runs?select=track,race_no,runner_number,finish_note&race_date=eq.{day}'
                 f'&finish_note=in.({q(notes)})&limit=5000')
    gone = {}
    for r in scr:
        gone.setdefault((r['track'], int(r['race_no'])), set()).add(int(r['runner_number']))
    last = sb.get(f'/rest/v1/nar_ai_marks?select=track,race_no,meta&model=eq.{MODEL_ID}'
                  f'&timing=eq.last&race_date=eq.{day}&limit=1000')
    done = {(r['track'], int(r['race_no'])): (sorted((r.get('meta') or {}).get('scratched') or []), bool((r.get('meta') or {}).get('direct')))
            for r in last}
    # 発走 15 分前を過ぎたレースは書かない(どうせトリガーが捨てる = 毎回書きに行かない)。--now は検算用
    now = dt.datetime.fromisoformat(arg('--now')).replace(tzinfo=JST) if arg('--now') else dt.datetime.now(JST)
    post = {(r['track'], int(r['race_no'])): r.get('post_time') for r in
            sb.get(f'/rest/v1/nar_races?select=track,race_no,post_time&race_date=eq.{day}&limit=1000')}
    rows, show = [], []
    for m in sorted(morning, key=lambda r: (r['track'], int(r['race_no']))):
        key = (m['track'], int(m['race_no']))
        g = gone.get(key, set())
        meta = m.get('meta') or {}
        g = {n for n in g if str(n) in (meta.get('p') or {})}
        if only and not g:
            continue
        at = post_at(day, post.get(key))
        if at is not None and (at - now).total_seconds() < 15 * 60:
            continue
        ud = None
        if SD is not None:
            keep = [int(n) for n in (meta.get('p') or {}) if int(n) not in g]
            try:
                r_ = SQ.resid_day(SD, key[0], key[1], sorted(keep), going.get(key), bws.get(key, {}))
            except Exception as e:  # noqa: BLE001
                print('並び読み 直前版の計算に失敗', key, type(e).__name__, str(e)[:120])
                r_ = None
            if r_ is not None:
                ud = dict(zip(sorted(keep), r_))
        prev = done.get(key)
        if prev is not None and prev[0] == sorted(g) and (prev[1] or ud is None):
            continue   # 外した馬が同じで、直前版を書いた後か まだ書けない = 書き直さない
        res = relabel(meta, g, ud, SF, key)
        if res is None:
            show.append(f'{key[0]}{key[1]}R 全頭が外れた = 書かない')
            continue
        marks, new = res
        rows.append({'track': key[0], 'race_date': day, 'race_no': key[1], 'marks': marks, 'meta': new})
        if g or ud is not None:
            was = ' '.join(f"{x['mark']}{x['num']}" for x in (m.get('marks') or []))
            show.append(f"{key[0]}{key[1]}R {'直前版' if ud is not None else ''} 外す {sorted(g)}: 朝 {was} → "
                        + ' '.join(f"{x['mark']}{x['num']}({x['score']})" for x in marks))
    print('\n'.join(show))
    print('朝の行', len(morning), '・取消のあるレース', sum(1 for k in gone if any(k == (m['track'], int(m['race_no'])) for m in morning)),
          '・書く行', len(rows), '(前の回と同じは書かない)')
    print('勝つ率の混ぜ(決め 40)', sum(1 for r in rows if r['meta'].get('p1mix')), '/', len(rows), 'R')
    print('決め 41 のずらし', sum(1 for r in rows if r['meta'].get('f41')), '/', len(rows), 'R')
    print('決め 61 の有利の直し', sum(1 for r in rows if (r['meta'].get('rb61') or {}).get('fin0')), '/', len(rows), 'R')
    if write and rows:
        sys.path.insert(0, os.environ.get('NAR_JOBS_AI', str(HERE.parent)))
        import base_v1 as B1
        B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(v3n_daily と同じ作法)
        took = B1.write_marks(rows, day, 'last')
        print('書いた', took, '/', len(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""他場版 v3n の直前の行 = 朝の行から取消・除外の馬を外して割り直すだけ(2026-10-11・模型は使わない)。

  python -X utf8 pipeline/ai/kochi/v3n_last.py 2026-10-11 [--write] [--only-scratched] [--now '2026-10-11 09:00']

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


def relabel(meta, gone):
    """朝の meta と外す馬番の集合 → (marks, 新しい meta)。外すと 1 頭も残らないときは None"""
    p = {int(k): float(v) for k, v in (meta.get('p') or {}).items()}
    keep = [n for n in sorted(p) if n not in gone]
    if not keep:
        return None
    s = sum(p[n] for n in keep) or 1.0
    c = {n: p[n] / s for n in keep}
    run = {int(r['num']): r for r in (meta.get('runners') or [])}
    s1 = sum(float(run[n]['p1']) for n in keep if n in run) or 1.0
    order = sorted(keep, key=lambda n: (-c[n], keep.index(n)))
    import k26_cal  # 朝(v3n_daily)と同じ 3 着内の率の曲線
    q3 = dict(zip(keep, k26_cal.p3([c[n] for n in keep], len(keep))))
    marks = [{'num': n, 'mark': MARKS[i], 'score': round(c[n] * 100, 1)} for i, n in enumerate(order[:5])]
    new = dict(meta)
    new.update({
        'n': len(keep),
        'p': {str(n): round(c[n], 4) for n in keep},
        'runners': [{'num': n, 'p1': round(float(run[n]['p1']) / s1, 4) if n in run else None,
                     'p3': round(float(q3[n]), 4)} for n in keep],
        'own': {k: v for k, v in (meta.get('own') or {}).items() if int(k) not in gone},
        'scratched': sorted(gone),
        'from': 'morning',
    })
    return marks, new


def main():
    day = sys.argv[1]
    write, only = '--write' in sys.argv, '--only-scratched' in sys.argv
    import k0_dl
    sb = k0_dl.sb
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
    done = {(r['track'], int(r['race_no'])): sorted((r.get('meta') or {}).get('scratched') or []) for r in last}
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
        if done.get(key) == sorted(g):
            continue
        at = post_at(day, post.get(key))
        if at is not None and (at - now).total_seconds() < 15 * 60:
            continue
        res = relabel(meta, g)
        if res is None:
            show.append(f'{key[0]}{key[1]}R 全頭が外れた = 書かない')
            continue
        marks, new = res
        rows.append({'track': key[0], 'race_date': day, 'race_no': key[1], 'marks': marks, 'meta': new})
        if g:
            was = ' '.join(f"{x['mark']}{x['num']}" for x in (m.get('marks') or []))
            show.append(f"{key[0]}{key[1]}R 外す {sorted(g)}: 朝 {was} → " + ' '.join(f"{x['mark']}{x['num']}({x['score']})" for x in marks))
    print('\n'.join(show))
    print('朝の行', len(morning), '・取消のあるレース', sum(1 for k in gone if any(k == (m['track'], int(m['race_no'])) for m in morning)),
          '・書く行', len(rows), '(前の回と同じは書かない)')
    if write and rows:
        sys.path.insert(0, os.environ.get('NAR_JOBS_AI', str(HERE.parent)))
        import base_v1 as B1
        B1.MODEL_ID = MODEL_ID  # ⛔write_marks が見る先をここで差し替える(v3n_daily と同じ作法)
        took = B1.write_marks(rows, day, 'last')
        print('書いた', took, '/', len(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())

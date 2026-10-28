# -*- coding: utf-8 -*-
"""全券種の参考の買い目(決め 53・2026-10-24)。研究 nankan-ai-v3 の out/pair53_plan.md・src/f5_scripts/pair53_gen_sql.py と同じ選び。

入力は nar_v3_gap に書く発走 10 分前の行の runners(num・pg1・odds)と、そのレースの枠番(あれば)だけ。組のオッズ(板)は使わない。
  AI の率 pn = pg1(合計 1)・市場の率 mn = 1/単勝オッズ(合計 1)・組の率 = ハーヴィルの式。
  割安度 evp = 払戻率 × AI の組の率 ÷ 市場の組の率(単勝・複勝は pn × 単勝オッズ)≥ 線
  かつ 市場の組の値段 pm(= 払戻率 ÷ 市場の組の率)≤ 上限(倍)。
出力 = {'ver', 'n', 券種: [[組, 値段(倍), 割安度], …]}(割安度の大きい順)。単勝・複勝の組は馬番・値段は 10 分前の単勝オッズ。
枠連・枠単は出走する全馬の枠番が分かるときだけ作る(分からなければ鍵ごと無い = 画面は「なし」と言わない)。
2026-10-28 ユーザー「想定オッズがめちゃくちゃ」→ 選びはそのまま、attach_board() で選んだ組に 10 分前の実際のオッズ(板)を 4 つ目に添える
  (単勝・枠連・枠単・馬連・馬単・3連複・3連単 = 倍率 / 複勝・ワイド = [下限, 上限] / 板に無い組 = None)。値段(2 つ目)は物差しで、画面には出さない。
⛔公開 repo のログに候補は出さない(件数だけ)。使う側は v29_gap.live()(行の value.b53)。

  python -X utf8 pipeline/ai/v3/b53.py selftest     # 率の合計が 1 になる等の自己検査(通信なし)
"""
import itertools
import sys

VER = 'b53-1'
EPS = 1e-9
MIN_RUN = 5
# 券種 = (払戻率, 線, 上限(倍・None = なし))。研究 pair53_gen_sql.py の SPEC(決め 53 で固定)と同じ
SPEC = {
    'tan': (0.80, 1.1, None),
    'fuku': (0.80, 1.2, None),
    'wakuren': (0.75, 1.3, None),
    'wakutan': (0.75, 1.3, None),
    'wide': (0.75, 1.2, 100),
    'umaren': (0.75, 1.3, 300),
    'umatan': (0.75, 1.3, 1000),
    'sanrenpuku': (0.725, 2.0, 3000),
    'sanrentan': (0.725, 1.5, 3000),
}
KINDS = tuple(SPEC)


def _g(x):
    """SQL の greatest(x, 1e-9)"""
    return x if x > EPS else EPS


def usable(runners):
    """pg1 > 0 かつ odds > 0 の馬だけ(研究 SQL の pr と同じ)。→ [(馬番, pg1, 単勝オッズ)]"""
    out = []
    for r in runners or []:
        try:
            n, p, o = int(r['num']), float(r['pg1']), float(r['odds'])
        except (KeyError, TypeError, ValueError):
            continue
        if p > 0 and o > 0:
            out.append((n, p, o))
    return out


def _tri6(p, a, b, c):
    """3 頭 a・b・c が 3 着内を占める率(6 通りの並びの合計・研究 SQL と同じ足し順)"""
    pa, pb, pc = p[a], p[b], p[c]
    return (pa * pb / _g(1 - pa) * pc / _g(1 - pa - pb) + pb * pa / _g(1 - pb) * pc / _g(1 - pb - pa)
            + pa * pc / _g(1 - pa) * pb / _g(1 - pa - pc) + pc * pa / _g(1 - pc) * pb / _g(1 - pc - pa)
            + pb * pc / _g(1 - pb) * pa / _g(1 - pb - pc) + pc * pb / _g(1 - pc) * pa / _g(1 - pc - pb))


def _pick(kind, cand):
    """cand = [(組, AI の組の率, 市場の組の率)] → 線・上限を通った [[組, 値段, 割安度], …](割安度の大きい順)"""
    keep, line, cap = SPEC[kind]
    rows = []
    for key, qa, qm in cand:
        if not qm > 0:
            continue
        evp, pm = keep * qa / qm, keep / qm
        if evp >= line and (cap is None or pm <= cap):
            rows.append((key, pm, evp))
    rows.sort(key=lambda t: (-t[2], str(t[0])))
    return [[k, round(pm, 1), round(ev, 3)] for k, pm, ev in rows]


def make(runners, gates=None):
    """→ {'ver', 'n', 券種: [[組, 値段, 割安度], …]}。使える馬が 5 頭未満なら None。
    gates = {馬番: 枠番}。使う馬の全部に枠番が無いときは 枠連・枠単の鍵を作らない。"""
    u = usable(runners)
    n = len(u)
    if n < MIN_RUN:
        return None
    nums = sorted(x[0] for x in u)
    sp = sum(x[1] for x in u)
    inv = {x[0]: 1.0 / x[2] for x in u}
    sm = sum(inv.values())
    pn = {x[0]: x[1] / sp for x in u}
    mn = {k: v / sm for k, v in inv.items()}
    win = {x[0]: x[2] for x in u}
    out = {'ver': VER, 'n': n}
    # 単勝・複勝 = 勝つ率 × 10 分前の単勝オッズ(複勝も同じ値・線だけ違う)
    for kind in ('tan', 'fuku'):
        line = SPEC[kind][1]
        rows = sorted(((k, win[k], pn[k] * win[k]) for k in nums if pn[k] * win[k] >= line), key=lambda t: (-t[2], t[0]))
        out[kind] = [[k, o, round(ev, 3)] for k, o, ev in rows]
    # 枠連・枠単 = 馬の「1 着 → 2 着」の並びの率を枠でまとめる
    if gates and all(k in gates and gates[k] is not None for k in nums):
        fr = {k: int(gates[k]) for k in nums}
        un, od = {}, {}
        for a, b in itertools.permutations(nums, 2):
            pa = pn[a] * pn[b] / _g(1 - pn[a])
            pm = mn[a] * mn[b] / _g(1 - mn[a])
            fa, fb = fr[a], fr[b]
            for d, key in ((un, (min(fa, fb), max(fa, fb))), (od, (fa, fb))):
                x = d.get(key, (0.0, 0.0))
                d[key] = (x[0] + pa, x[1] + pm)
        out['wakuren'] = _pick('wakuren', [(f'{k[0]}-{k[1]}', v[0], v[1]) for k, v in un.items()])
        out['wakutan'] = _pick('wakutan', [(f'{k[0]}-{k[1]}', v[0], v[1]) for k, v in od.items()])
    # 馬連・馬単
    um, ut = [], []
    for a, b in itertools.combinations(nums, 2):
        qa = pn[a] * pn[b] / _g(1 - pn[a]) + pn[b] * pn[a] / _g(1 - pn[b])
        qm = mn[a] * mn[b] / _g(1 - mn[a]) + mn[b] * mn[a] / _g(1 - mn[b])
        um.append((f'{a}-{b}', qa, qm))
    for a, b in itertools.permutations(nums, 2):
        ut.append((f'{a}-{b}', pn[a] * pn[b] / _g(1 - pn[a]), mn[a] * mn[b] / _g(1 - mn[a])))
    out['umaren'] = _pick('umaren', um)
    out['umatan'] = _pick('umatan', ut)
    # ワイド(2 頭とも 3 着内)・3 連複(3 頭が 3 着内)
    wd, tr = {}, []
    for a, b, c in itertools.combinations(nums, 3):
        sa, sm3 = _tri6(pn, a, b, c), _tri6(mn, a, b, c)
        tr.append((f'{a}-{b}-{c}', sa, sm3))
        for k in ((a, b), (a, c), (b, c)):
            x = wd.get(k, (0.0, 0.0))
            wd[k] = (x[0] + sa, x[1] + sm3)
    out['wide'] = _pick('wide', [(f'{k[0]}-{k[1]}', v[0], v[1]) for k, v in wd.items()])
    out['sanrenpuku'] = _pick('sanrenpuku', tr)
    # 3 連単
    tt = []
    for a, b, c in itertools.permutations(nums, 3):
        tt.append((f'{a}-{b}-{c}',
                   pn[a] * pn[b] / _g(1 - pn[a]) * pn[c] / _g(1 - pn[a] - pn[b]),
                   mn[a] * mn[b] / _g(1 - mn[a]) * mn[c] / _g(1 - mn[a] - mn[b])))
    out['sanrentan'] = _pick('sanrentan', tt)
    return out


# 板の 1 行の並び(nar_odds_full_ticks.combos): 馬番 or 枠番の数・倍率の位置・上限の位置(ワイドだけ)・順不同か
BOARD = {
    'wakuren': (2, 2, None, True),     # [a, b, 倍率]
    'wakutan': (2, 2, None, False),
    'umaren': (2, 2, None, True),      # [a, b, 倍率, 人気]
    'umatan': (2, 2, None, False),
    'wide': (2, 2, 4, True),           # [a, b, 下限, 人気, 上限]
    'sanrenpuku': (3, 3, None, True),  # [a, b, c, 倍率, 人気]
    'sanrentan': (3, 3, None, False),
}


def _odds(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def board_map(kind, combos):
    """板の combos → {'a-b(-c)': 倍率 or [下限, 上限]}(順不同の券種は小さい順の鍵)"""
    n, io, ih, un = BOARD[kind]
    out = {}
    for e in combos or []:
        try:
            nums = [int(v) for v in e[:n]]
        except (TypeError, ValueError):
            continue
        lo = _odds(e[io]) if len(e) > io else None
        if lo is None:
            continue
        key = '-'.join(str(v) for v in (sorted(nums) if un else nums))
        if ih is None:
            out[key] = lo
        else:
            hi = _odds(e[ih]) if len(e) > ih else None
            out[key] = [lo, hi if hi is not None else lo]
    return out


def attach_board(b53, boards, win=None, place=None):
    """選んだ組の行 [組, 値段, 割安度] に 4 つ目 = 10 分前の実際のオッズを足す(選びは変えない)。
    boards = {券種: combos}・win = {馬番: 単勝}・place = {馬番: [下限, 上限]}。板の無い組は None。"""
    if not b53:
        return b53
    for kind in KINDS:
        rows = b53.get(kind)
        if not isinstance(rows, list):
            continue
        if kind == 'tan':
            m = {str(k): _odds(v) for k, v in (win or {}).items()}
        elif kind == 'fuku':
            m = {}
            for k, v in (place or {}).items():
                lo = _odds(v[0]) if isinstance(v, (list, tuple)) and v else None
                if lo is not None:
                    hi = _odds(v[1]) if len(v) > 1 else None
                    m[str(k)] = [lo, hi if hi is not None else lo]
        else:
            m = board_map(kind, (boards or {}).get(kind))
        for r in rows:
            del r[3:]
            r.append(m.get(str(r[0])))
    return b53


def count(b53):
    """全券種の点数(ログ用・中身は出さない)"""
    return sum(len(v) for k, v in (b53 or {}).items() if k in SPEC and isinstance(v, list))


def selftest():
    import random
    rnd = random.Random(53)
    for trial in range(40):
        n = rnd.randint(5, 16)
        raw = [rnd.random() ** 2 + 0.01 for _ in range(n)]
        s = sum(raw)
        rows = [{'num': i + 1, 'pg1': round(r / s, 4) or 0.0001, 'odds': round(0.8 / (rnd.random() ** 2 * 0.5 + 0.02 + r / s), 1) + 1.0} for i, r in enumerate(raw)]
        gates = {i + 1: min(8, (i * 8) // n + 1) for i in range(n)}
        b = make(rows, gates)
        assert b and b['n'] == n and set(KINDS) <= set(b), trial
        for k in KINDS:
            ev = [x[2] for x in b[k]]
            assert ev == sorted(ev, reverse=True), (trial, k)
            assert all(x[2] >= SPEC[k][1] for x in b[k]), (trial, k)
            cap = SPEC[k][2]
            assert cap is None or all(x[1] <= cap + 0.05 for x in b[k]), (trial, k)
        # 率の合計が 1(研究の確認と同じ: 並びの率の合計・組の率の合計)
        u = usable(rows)
        sp = sum(x[1] for x in u)
        p = {x[0]: x[1] / sp for x in u}
        nums = sorted(p)
        assert abs(sum(p[a] * p[b] / _g(1 - p[a]) for a, b in itertools.permutations(nums, 2)) - 1) < 1e-9
        assert abs(sum(_tri6(p, a, b, c) for a, b, c in itertools.combinations(nums, 3)) - 1) < 1e-9
        # 枠番が欠けた馬がいれば枠連・枠単の鍵は無い
        g2 = dict(gates)
        g2.pop(1)
        b2 = make(rows, g2)
        assert 'wakuren' not in b2 and 'wakutan' not in b2 and 'umaren' in b2
    # 板を添えても選び(組・値段・割安度)は変わらない・順不同の鍵は小さい順・板に無い組は None
    rows = [{'num': i, 'pg1': p, 'odds': o} for i, p, o in ((1, .40, 4.0), (2, .05, 3.0), (3, .05, 8.0), (4, .30, 9.0), (5, .20, 6.0))]
    b = make(rows, {1: 1, 2: 2, 3: 3, 4: 4, 5: 4})
    before = {k: [list(r) for r in b[k]] for k in KINDS}
    boards = {'umaren': [[4, 1, 7.7, 3]], 'wide': [[1, 4, 2.1, 1, 2.9]], 'wakutan': [[4, 4, 30.5]], 'sanrentan': [[1, 4, 5, 55.0, 9]]}
    attach_board(b, boards, win={1: 4.0, 4: 9.0}, place={1: [1.2, 1.5]})
    attach_board(b, boards, win={1: 4.0, 4: 9.0}, place={1: [1.2, 1.5]})  # 2 回足しても 4 つ目は 1 つ
    for k in KINDS:
        assert [r[:3] for r in b[k]] == before[k] and all(len(r) == 4 for r in b[k]), k
    assert board_map('umaren', boards['umaren']) == {'1-4': 7.7}
    assert board_map('wide', boards['wide']) == {'1-4': [2.1, 2.9]}
    assert board_map('wakutan', boards['wakutan']) == {'4-4': 30.5}
    assert board_map('sanrentan', [[3, 1, 2, 0, 1], [3, 1, 2, 120.5, 4]]) == {'3-1-2': 120.5}  # 0 倍(取消など)は無いとする
    assert all(r[3] == (4.0 if r[0] == 1 else 9.0 if r[0] == 4 else None) for r in b['tan'])
    assert all(r[3] in ([1.2, 1.5], None) for r in b['fuku'])
    assert make([{'num': i, 'pg1': 0.25, 'odds': 4.0} for i in range(1, 5)]) is None  # 4 頭
    assert make([{'num': i, 'pg1': 0.2, 'odds': 5.0} for i in range(1, 5)] + [{'num': 5, 'pg1': 0, 'odds': 5.0}]) is None  # pg1 = 0 の馬は数えない
    print('selftest OK', file=sys.stderr)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        selftest()
    else:
        print(__doc__)

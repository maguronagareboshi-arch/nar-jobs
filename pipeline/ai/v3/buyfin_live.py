# -*- coding: utf-8 -*-
"""南関 買い方の最終案。参考の買い目の記録だけ(今の単勝の買いは変えない)。
  2026-11-18 の形(研究 nankan-ai-v3 out/buy_final_1118.md)→ 2026-11-21 買い方 決め 7 の形(研究 out/buy_judge7_1121_judge.md・2024-01〜10 で合格)。

  軸   = 10 分前の買いの模型の期待値(runners の ev = 新しい模型の勝つ率 × 10 分前の単勝)≥ AX_EV かつ 単勝 AX_LO 以上 AX_HI 未満の馬。
  相手 = 同じレースで 3 着内率(p3)≥ P3 かつ その馬の期待値 ≥ EV_S の馬(軸を除く・頭数の制限なし)。
  券   = 定数の KINDS の券種(無い = 11/18 の 6 券種)。単勝・複勝(軸)・ワイド・馬連(軸−相手)・馬単(軸→相手 と 相手→軸)・
         3連複(軸 + 相手 2 頭)・3連単(軸 2 着 = 相手 2 頭ごとに 相手→軸→相手 を 1・3 着を入れ替えて 2 点)。1 点 100 円。
  軸が 2 頭以上のレースは軸ごとに買う(同じ券を 2 枚買うことがある・ユーザー 2026-11-18「2 枚にしよう」)。
選びに使うのは ev・p3・単勝だけ。組のオッズは画面と答え合わせの添え物(選びに使わない・無ければ空)。
数(線)は暗号化したリリース v3-consts の consts.json の buyfin(公開のコードに数を置かない)。
buyfin に PREV(同じ形の辞書)があれば、その形も val['buyfin_prev'] に並べて記録する(v29_gap.add_buyfin)。
"""
import sys
from itertools import combinations
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

KINDS_1118 = ('tan', 'fuku', 'wide', 'umaren', 'umatan', 'sanrenpuku')
ALL_KINDS = KINDS_1118 + ('sanrentan',)
BOARD_KINDS = ('wide', 'umaren', 'umatan', 'sanrenpuku', 'sanrentan')
KINDS = KINDS_1118  # 古い呼び名(11/18 の形の券種)
_C = None


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('buyfin')
    return _C


def prev():
    """並べて記録する前の形の定数(無い = None)"""
    p = consts().get('PREV')
    return p if isinstance(p, dict) else None


def kinds(C=None):
    C = C or consts()
    k = tuple(C.get('KINDS') or KINDS_1118)
    bad = [x for x in k if x not in ALL_KINDS]
    if bad:
        raise KeyError(f'buyfin の KINDS に知らない券種 {bad}')
    return k


def boards_needed(C=None):
    """この形で組のオッズを添える券種(板を読む券種)"""
    return tuple(k for k in kinds(C) if k in BOARD_KINDS)


def tag(C=None):
    return (C or consts())['TAG']


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def pick(rows, C=None):
    """rows = [(馬番, 期待値, 3 着内率, 単勝)]。→ [(軸, [相手])](軸は馬番の順)。研究 buy_pastjudge_1121.tickets(相手の上限なし)と同じ当てはめ。"""
    C = C or consts()
    ok = [(int(u), e, p, o) for u, e, p, o in rows if e is not None and p is not None and o is not None]
    out = []
    for a, e, p, o in sorted(ok):
        if e >= C['AX_EV'] and C['AX_LO'] <= o < C['AX_HI']:
            out.append((a, sorted(u for u, e2, p2, _ in ok if u != a and p2 >= C['P3'] and e2 >= C['EV_S'])))
    return out


def tickets(a, S, ks=KINDS_1118):
    """軸 a と相手 S → {券種: [組の字]}(馬連・ワイド・3連複は小さい順・馬単は 1 着-2 着・3連単は 1 着-2 着(軸)-3 着)。"""
    j = lambda xs: '-'.join(str(x) for x in xs)  # noqa: E731
    pairs = list(combinations(S, 2))
    full = {'tan': [str(a)], 'fuku': [str(a)],
            'wide': [j(sorted((a, s))) for s in S], 'umaren': [j(sorted((a, s))) for s in S],
            'umatan': [j((a, s)) for s in S] + [j((s, a)) for s in S],
            'sanrenpuku': [j(sorted((a, s1, s2))) for s1, s2 in pairs],
            'sanrentan': [c for s1, s2 in pairs for c in (j((s1, a, s2)), j((s2, a, s1)))]}
    return {k: full[k] for k in ks}


def _board_odds(boards):
    """板 {券種: nar_odds_full_ticks.combos} → {券種: {組の字: オッズ}}(ワイドは下限)。並びは buy4_live.board_arrays と同じ。"""
    out = {}
    for k in BOARD_KINDS:
        nn = 3 if k in ('sanrenpuku', 'sanrentan') else 2
        d = {}
        for e in (boards or {}).get(k) or []:
            try:
                hs = [int(x) for x in e[:nn]]
            except (TypeError, ValueError):
                continue
            if len(e) <= nn:
                continue
            o = _f(e[nn])
            if o is None or o <= 0:
                continue
            if k in ('wide', 'umaren', 'sanrenpuku'):
                hs = sorted(hs)
            d['-'.join(str(h) for h in hs)] = o
        out[k] = d
    return out


def race(rows, win, place, boards, C=None):
    """1 レース。rows = [(馬番, 期待値, 3 着内率, 単勝)](便がいま決めた全頭・丸めない値)・win = {馬番: 単勝}・place = {馬番: [下限, 上限]}・boards = 組の板。
    C = 形の定数(無い = buyfin)。
    → {'tag', 'n', 'axes': [{'num', 'odds', 'ev', 'partners', 'tickets': {券種: [[組, オッズ], …]}}], 'points'}(軸なし = axes 空)か {'tag', 'why'}。"""
    C = C or consts()
    ks = kinds(C)
    out = {'tag': tag(C)}
    if len(rows) < 5:
        out['why'] = '5 頭未満'
        return out
    if any(int(u) > 16 for u, *_ in rows):
        out['why'] = '馬番が 16 より大きい'
        return out
    bo = _board_odds(boards)
    ev = {int(u): e for u, e, _, _ in rows}
    axes = []
    for a, S in pick(rows, C):
        tk = tickets(a, S, ks)
        od = {'tan': {str(a): _f((win or {}).get(a))},
              'fuku': {str(a): _f(((place or {}).get(a) or [None])[0])}}
        od.update(bo)
        axes.append({'num': a, 'odds': _f((win or {}).get(a)), 'ev': round(ev[a], 3), 'partners': S,
                     'tickets': {k: [[c, od.get(k, {}).get(c)] for c in tk[k]] for k in ks}})
    out['n'] = len(rows)
    out['axes'] = axes
    out['points'] = count(out)
    return out


def count(v):
    """ログ用の点数(買い目の中身は出さない)"""
    if not isinstance(v, dict):
        return 0
    return sum(len(L or []) for x in v.get('axes') or [] for L in (x.get('tickets') or {}).values())

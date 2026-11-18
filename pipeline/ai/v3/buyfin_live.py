# -*- coding: utf-8 -*-
"""南関 買い方の最終案(研究 nankan-ai-v3 out/buy_final_1118.md・監査 out/buy_final_audit_1118.md・ユーザー 2026-11-18)。参考の買い目の記録だけ(今の単勝の買いは変えない)。

  軸   = 10 分前の買いの模型の期待値(runners の ev = 新しい模型の勝つ率 × 10 分前の単勝)≥ AX_EV かつ 単勝 AX_LO 以上 AX_HI 未満の馬。
  相手 = 同じレースで 3 着内率(p3)≥ P3 かつ その馬の期待値 ≥ EV_S の馬(軸を除く)。
  券   = 単勝・複勝(軸)・ワイド・馬連(軸−相手)・馬単(軸→相手 と 相手→軸)・3連複(軸 + 相手 2 頭)。1 点 100 円。
  軸が 2 頭以上のレースは軸ごとに買う(同じ券を 2 枚買うことがある・ユーザー 2026-11-18「2 枚にしよう」)。
選びに使うのは ev・p3・単勝だけ。組のオッズは画面と答え合わせの添え物(選びに使わない・無ければ空)。
数(線)は暗号化したリリース v3-consts の consts.json の buyfin(公開のコードに数を置かない)。
"""
import sys
from itertools import combinations
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))  # 末尾に足す = pipeline/ai の sealed

KINDS = ('tan', 'fuku', 'wide', 'umaren', 'umatan', 'sanrenpuku')
_C = None


def consts():
    global _C
    if _C is None:
        import sealed
        _C = sealed.get('buyfin')
    return _C


def tag():
    return consts()['TAG']


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def pick(rows):
    """rows = [(馬番, 期待値, 3 着内率, 単勝)]。→ [(軸, [相手])](軸は馬番の順)。研究 buy_final_audit_1118.engine と同じ当てはめ。"""
    C = consts()
    ok = [(int(u), e, p, o) for u, e, p, o in rows if e is not None and p is not None and o is not None]
    out = []
    for a, e, p, o in sorted(ok):
        if e >= C['AX_EV'] and C['AX_LO'] <= o < C['AX_HI']:
            out.append((a, sorted(u for u, e2, p2, _ in ok if u != a and p2 >= C['P3'] and e2 >= C['EV_S'])))
    return out


def tickets(a, S):
    """軸 a と相手 S → {券種: [組の字]}(馬連・ワイド・3連複は小さい順・馬単は 1 着-2 着)。"""
    j = lambda xs: '-'.join(str(x) for x in xs)  # noqa: E731
    return {'tan': [str(a)], 'fuku': [str(a)],
            'wide': [j(sorted((a, s))) for s in S], 'umaren': [j(sorted((a, s))) for s in S],
            'umatan': [j((a, s)) for s in S] + [j((s, a)) for s in S],
            'sanrenpuku': [j(sorted((a, s1, s2))) for s1, s2 in combinations(S, 2)]}


def _board_odds(boards):
    """板 {券種: nar_odds_full_ticks.combos} → {券種: {組の字: オッズ}}(ワイドは下限)。並びは buy4_live.board_arrays と同じ。"""
    out = {}
    for k in ('wide', 'umaren', 'umatan', 'sanrenpuku'):
        nn = 3 if k == 'sanrenpuku' else 2
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


def race(rows, win, place, boards):
    """1 レース。rows = [(馬番, 期待値, 3 着内率, 単勝)](便がいま決めた全頭・丸めない値)・win = {馬番: 単勝}・place = {馬番: [下限, 上限]}・boards = 組の板。
    → {'tag', 'n', 'axes': [{'num', 'odds', 'ev', 'partners', 'tickets': {券種: [[組, オッズ], …]}}], 'points'}(軸なし = axes 空)か {'tag', 'why'}。"""
    out = {'tag': tag()}
    if len(rows) < 5:
        out['why'] = '5 頭未満'
        return out
    if any(int(u) > 16 for u, *_ in rows):
        out['why'] = '馬番が 16 より大きい'
        return out
    bo = _board_odds(boards)
    ev = {int(u): e for u, e, _, _ in rows}
    axes = []
    for a, S in pick(rows):
        tk = tickets(a, S)
        od = {'tan': {str(a): _f((win or {}).get(a))},
              'fuku': {str(a): _f(((place or {}).get(a) or [None])[0])}}
        od.update(bo)
        axes.append({'num': a, 'odds': _f((win or {}).get(a)), 'ev': round(ev[a], 3), 'partners': S,
                     'tickets': {k: [[c, od.get(k, {}).get(c)] for c in tk[k]] for k in KINDS}})
    out['n'] = len(rows)
    out['axes'] = axes
    out['points'] = count(out)
    return out


def count(v):
    """ログ用の点数(買い目の中身は出さない)"""
    if not isinstance(v, dict):
        return 0
    return sum(len(x['tickets'].get(k) or []) for x in v.get('axes') or [] for k in KINDS)

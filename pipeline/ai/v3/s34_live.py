# -*- coding: utf-8 -*-
"""南関 第34版 = 整理の 2 つ(研究 nankan-ai-v3 src/f5_scripts/simplify92_judge.py・correct67_9_judge.py・判定 2026-11-25)。

決め 67-9(前日版・正しさの直し): 前日の F3 の段の勝つ率で、F3 の勝つ率を logit でなく ln で混ぜる。勝ち o1 = 0.8 × ln p1 + 0.2 × (ln q + u_P)。
  3 着内は今のまま(0.8 × logit + 0.2 × (F3 + u_P))。→ preday74_live.add_f3(log1=f3log())。直したレースは meta.pt74.s34 = True。
  → dayonpre77_live.write_base がそのレースの土台を D77:v = 34 にする(決め 87 のレース・u_P旧 に依らない)。
決め 92(直前版): D77:v = 34 のレースだけ、当日の 3 段(並び読みの差・3 案まとめの差・67-8 の戻し)を 1 段に。
  D = u_X − u_P + 0.5 × (u_b − u_X)(u_b の無い馬は差 0・u_X・u_P の無い馬は 0)→ 勝つ率の log に WB34(0.4)倍・3 着内の logit に 1 倍 →
  そのあとは今と同じ(合計 1・3・当日の土台の差・付いていき)。→ dayonpre77_live.apply_day(meta.dp77.s34)。
定数(F3LOG34・WB34・ON34・TAG34)は暗号化したリリース v3-consts の consts.json の dp77(無ければ動かない = 第33版のまま)。
"""


def consts():
    import dayonpre77_live
    C = dayonpre77_live.consts()
    for k in ('F3LOG34', 'WB34', 'ON34'):
        if k not in C:
            raise KeyError(f'dp77 に {k} が無い')
    return C


def is_on(day):
    """その日(レースの日)が第34版の ON 以降か(定数が無ければ例外)。"""
    return str(day) >= str(consts().get('ON34') or '9999-12-31')


def tag():
    return consts().get('TAG34', '決め92・67-9 第34版')


def f3log():
    return bool(int(consts()['F3LOG34']))


def wb():
    return float(consts()['WB34'])

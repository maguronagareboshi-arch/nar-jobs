# -*- coding: utf-8 -*-
"""研究用の便の期間指定(trifecta_anomaly / early_money / yari_situations 共通)。
既定= 各台本の固定値(手動 workflow_dispatch の数字は変わらない)。
環境変数 D_FROM / D_TO(YYYY-MM-DD)で上書きできる。
schedule 起動(GITHUB_EVENT_NAME=schedule か RESEARCH_SCHEDULE=1)の時だけ 終わり= 起動日の前月末(JST)、
開始= データの初日(yearly=True なら終わり日から 1 年)。結果は result-<終わり月>.md に分ける。"""
import datetime as dt
import os

JST = dt.timezone(dt.timedelta(hours=9))


def scheduled():
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule" or os.environ.get("RESEARCH_SCHEDULE") == "1"


def prev_month_end(today):
    return today.replace(day=1) - dt.timedelta(days=1)


def one_year_from(d_to):
    n = d_to + dt.timedelta(days=1)
    return dt.date(n.year - 1, n.month, n.day) if not (n.month == 2 and n.day == 29) else dt.date(n.year - 1, 3, 1)


def add_months(d, k):
    m = d.month - 1 + k
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


def midpoint(d_from, d_to):
    return d_from + dt.timedelta(days=((d_to - d_from).days + 1) // 2)


def period(default_from, default_to, data_from=None, yearly=False, today=None):
    """(D_FROM, D_TO, 予定起動か) を返す。"""
    sch = scheduled()
    d_from, d_to = default_from, default_to
    if sch:
        today = today or dt.datetime.now(JST).date()
        d_to = prev_month_end(today)
        d_from = one_year_from(d_to) if yearly else data_from
    if os.environ.get("D_FROM"):
        d_from = dt.date.fromisoformat(os.environ["D_FROM"])
    if os.environ.get("D_TO"):
        d_to = dt.date.fromisoformat(os.environ["D_TO"])
    return d_from, d_to, sch


def out_name(sch, d_to):
    return "result-%s.md" % d_to.strftime("%Y-%m") if sch else "result.md"


def md(d):
    return "%d/%d" % (d.month, d.day)


def ym(d):
    return d.strftime("%Y-%m")

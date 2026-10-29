# -*- coding: utf-8 -*-
"""直前の便の生存の見張り(nar-watchdog の heartbeat から毎時・2026-10-30)。

10/29 12:29 JST に nar-ai-last(他場の直前)と v3-gap-live(南関の直前)が GitHub 側の内部エラーで消えた。
機械ごと消えると終わりの段(heartbeat fail)が走らず、表は ok のまま = 見張りは「赤なし」で、
午後の便まで 2.5 時間・15 R の直前の印が抜けた(nankan-ai-v3 out/incident_20261029_last.md)。

ふだんは DB の時計 private.nar_live_guard(5 分おき・pipeline/sql/live_guard_20261030.sql)が
生存の途切れ 15 分で便を回し直す。ここはその後ろの守り:
  ⑦ 開催中に、まだ発走前(15 分より先)のレースがあるのに、生存の記録が 30 分より古い → 赤(回し直しも効いていない)
  ⑧ 今日その回し直しがあった(nar_job_heartbeat の live_guard) → 赤(1 日 1 通・何を回し直したかを知らせる)
見る時間と引き継ぎの時間は private.nar_live_guard と同じ表(LIVE)。変えるときは両方を直す。
"""
import datetime as dt
import re

JST = dt.timezone(dt.timedelta(hours=9))
NANKAN = ("大井", "川崎", "船橋", "浦和")
# job: (見始め HHMM, 引き継ぎの始め, 引き継ぎの終わり, 南関の便か)
#   ai_last = nar-ai-last(09:08 / 15:08 起動・朝の便は 14:55 まで)・v3_gap_live = v3-gap-live(10:15 am / 15:50 pm・am は 16:05 まで)
LIVE = {
    "ai_last": (940, 1450, 1535, False),
    "v3_gap_live": (1045, 1545, 1620, True),
}
STALE_MIN = 30   # 回し直し(15 分)より長く途切れている = 回し直しも効いていない
AHEAD_MIN = 15   # 発走まで 15 分より先のレースがあるときだけ見る(それより近いと回し直しても間に合わない)


def _ts(v):
    if not v:
        return None
    return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(JST)


def left_races(races, day, now, nankan):
    """その便が受け持つ、まだ発走前(AHEAD_MIN 分より先)のレースの数。取消・発走時刻の無いレースは数えない。帯広はどちらの便も受け持たない。"""
    n = 0
    for r in races or []:
        pt = str(r.get("post_time") or "")
        tr = r.get("track")
        if str(r.get("cancelled") or "").strip() or not re.fullmatch(r"\d{4}", pt) or tr == "帯広":
            continue
        if (tr in NANKAN) != nankan:
            continue
        at = dt.datetime.combine(day, dt.time(int(pt[:2]), int(pt[2:])), tzinfo=JST)
        if at > now + dt.timedelta(minutes=AHEAD_MIN):
            n += 1
    return n


def live_bad(got, races, now):
    """got = {job: nar_job_heartbeat の行}・races = 今日の nar_races(track, post_time, cancelled)・now = JST。赤の理由の list。"""
    bad = []
    hm = now.hour * 100 + now.minute
    if races is not None:
        for job, (h0, hf, ht, nk) in LIVE.items():
            if hm < h0 or hf <= hm < ht:
                continue
            left = left_races(races, now.date(), now, nk)
            t = _ts((got.get(job) or {}).get("last_ok"))
            if left and (t is None or (now - t).total_seconds() > STALE_MIN * 60):
                bad.append(f"{job}(直前の便)が止まっている: 最後の生存 {t}・まだ発走前 {left} R"
                           "(自動の回し直しも効いていない = GitHub の便の一覧を見る)")
    g = got.get("live_guard") or {}
    t = _ts(g.get("last_try"))
    if t is not None and t.date() == now.date():
        bad.append(f"直前の便の生存が途切れ、今日自動で回し直しを送った(note={g.get('note')})")
    return bad

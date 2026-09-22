# -*- coding: utf-8 -*-
"""§239a 分析タブ(カルテ)の事実を焼く便 nar_karte_facts(2026-09-22)。数え方は pipeline/karte.py に 1 つだけ。

対象= 南関 4 場(大井・船橋・川崎・浦和)で、その日の出走表の行が nar_runs にあるレース。1 頭 1 行。
⛔発走前の値だけ= **その日より前の走だけ**で数える。馬の見分け= (名前, 生年)(§238e facts.birth_year_of)。
材料= nar_runs(着順・人気・走破タイム・日付)/ nar_races(post_time・レース名)/ nar_kb_runs(start_note)/
      nar_run_facts(今日の行の style・過去走の c1〜c4)/ nar_meta karte:late_next:v1(出遅れの割合表)。

  py -3.12 -X utf8 cloud/karte_facts.py                          # ドライラン(JST の今日と明日・書かずに表で出す)
  py -3.12 -X utf8 cloud/karte_facts.py --date 2026-09-22 --track 浦和
  py -3.12 -X utf8 cloud/karte_facts.py --apply                  # upsert
  py -3.12 -X utf8 cloud/karte_facts.py --late-table             # 出遅れの割合表を数え直す(--apply で nar_meta へ)
  py -3.12 -X utf8 cloud/karte_facts.py --selftest               # 数え方だけ(通信なし)

環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(⛔鍵はコードに書かない・ログにも出さない)。
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000 行キャップ: 全取得はページングで回す(order は主キーで一意)。⛔URL 長: in.() は 80 件ずつ。
⛔本番 DB に重い SQL は流さない(組み立ては全部ここ= 便の中)。
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import facts, karte                                   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

UA = "nar-jobs/1.0"
JST = dt.timezone(dt.timedelta(hours=9))
PAGE = 1000
CHUNK = 80
BATCH = 500
PAUSE = 0.0               # 1 本ごとの間(秒)。手元の読むだけの模擬では上げる
TABLE = "nar_karte_facts"
PK = "race_date,track,race_no,umaban"
HIST_FROM = "2014-01-01"  # 通算の始め(楽天 2014〜)


def log(msg):
    print(msg, flush=True)


def env():
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が要る(⛔鍵はコードに書かない)")
    return base, key


def get(base, key, path):
    req = urllib.request.Request(base + path, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA, "Accept": "application/json"})
    for n in range(3):
        try:
            if PAUSE:
                time.sleep(PAUSE)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:                                       # noqa: BLE001
            if n == 2:
                log("  ⛔読み取り失敗 %s: %s" % (path.split("?")[0], str(e)[:120]))
                raise SystemExit(2) from e
            time.sleep(2 + n * 3)
    return []


def rows_all(base, key, path):
    """⛔order= 主キーで一意にしてから offset を進める(PostgREST の offset は order が一意でないと欠ける)。"""
    out, off = [], 0
    joiner = "&" if "?" in path else "?"
    while True:
        rows = get(base, key, "%s%slimit=%d&offset=%d" % (path, joiner, PAGE, off))
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        off += PAGE


def q_in(values):
    return urllib.parse.quote(",".join('"%s"' % str(v).replace('"', "") for v in values), safe='(),"')


def chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def upsert(base, key, table, rows, on_conflict):
    """⛔run_facts.upsert と同じ作法(merge-duplicates・return=minimal・5xx は 3 回まで)。"""
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "%s/rest/v1/%s?on_conflict=%s" % (base, table, on_conflict), data=body, method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal", "User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, ""
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code >= 500 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, msg
        except Exception as e:                                       # noqa: BLE001
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return 0, str(e)
    return 0, "unreachable"


def match_key(r):
    """(名前, 生年)。⛔名前か生年が無ければ None(名前だけでつながない)= run_facts.match_key と同じ。"""
    name = r.get("horse_name")
    if not name:
        return None
    by = facts.birth_year_of(r.get("birth_date"), r.get("age"), r.get("race_date"))
    return None if by is None else (name, by)


# ---------------------------------------------------------------- 取得(⛔読むだけ)

RUN_COLS = "track,race_date,race_no,runner_number,horse_name,birth_date,age"


def fetch_entries(base, key, date, tracks):
    """その日の出走表(nar_runs の行)。⛔南関 4 場だけ。"""
    return rows_all(base, key,
                    "/rest/v1/nar_runs?select=%s&race_date=eq.%s&track=in.(%s)"
                    "&order=track.asc,race_no.asc,runner_number.asc" % (RUN_COLS, date, q_in(tracks)))


def fetch_history(base, key, names, hi):
    """馬名の束 → その馬名の全走(2014〜hi)。⛔同名の別馬は呼ぶ側が (名前, 生年) で分ける。"""
    out = []
    for part in chunks(sorted(set(names))):
        out.extend(rows_all(
            base, key,
            "/rest/v1/nar_runs?select=%s,finish,finish_note,popularity,time_sec"
            "&horse_name=in.(%s)&race_date=gte.%s&race_date=lte.%s"
            "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc" % (RUN_COLS, q_in(part), HIST_FROM, hi)))
    return out


def fetch_kb(base, key, names, hi):
    """{(場, 日, R, 馬名): start_note('' は記録あり・出遅れ等の字なし)}。⛔行が無い走= 記録なし。"""
    out = {}
    for part in chunks(sorted(set(names))):
        for r in rows_all(base, key,
                          "/rest/v1/nar_kb_runs?select=track,race_date,race_no,umaban,horse_name,start_note"
                          "&horse_name=in.(%s)&race_date=lte.%s"
                          "&order=race_date.asc,track.asc,race_no.asc,umaban.asc" % (q_in(part), hi)):
            out[(r["track"], str(r["race_date"])[:10], int(r["race_no"]), r["horse_name"])] = r.get("start_note") or ""
    return out


def fetch_run_facts(base, key, hkeys):
    """nar_run_facts を horse_key で(⛔索引 nar_run_facts_horse_idx)。{(日, 場, R, 馬番): 行}。"""
    out = {}
    for part in chunks(sorted({k for k in hkeys if k})):
        for r in rows_all(base, key,
                          "/rest/v1/nar_run_facts?select=race_date,track,race_no,umaban,c1,n1,c4,n4,style"
                          "&horse_key=in.(%s)&order=race_date.asc,track.asc,race_no.asc,umaban.asc" % q_in(part)):
            out[(str(r["race_date"])[:10], r["track"], int(r["race_no"]), int(r["umaban"]))] = r
    return out


def fetch_races(base, key, need):
    """{(場, 日)} → {(場, 日, R): {post_time, race_name}}。場ごと・日付 80 個ずつ(⛔run_facts.fetch_corners と同じ割り方)。"""
    by_track = {}
    for t, d in need:
        by_track.setdefault(t, set()).add(d)
    out = {}
    for t, days in sorted(by_track.items()):
        for part in chunks(sorted(days)):
            for r in rows_all(base, key,
                              "/rest/v1/nar_races?select=track,race_date,race_no,post_time,race_name"
                              "&track=eq.%s&race_date=in.(%s)&order=race_date.asc,race_no.asc"
                              % (urllib.parse.quote(t), q_in(part))):
                out[(r["track"], str(r["race_date"])[:10], int(r["race_no"]))] = r
    return out


def fetch_win_times(base, key, need):
    """{(場, 日)} → {(場, 日, R): 1 着の走破タイム}(同着は速い方= 同じ値)。"""
    by_track = {}
    for t, d in need:
        by_track.setdefault(t, set()).add(d)
    out = {}
    for t, days in sorted(by_track.items()):
        for part in chunks(sorted(days)):
            for r in rows_all(base, key,
                              "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,time_sec"
                              "&track=eq.%s&race_date=in.(%s)&finish=eq.1"
                              "&order=race_date.asc,race_no.asc,runner_number.asc" % (urllib.parse.quote(t), q_in(part))):
                v = karte.num_or_none(r.get("time_sec"))
                if v is None:
                    continue
                k = (r["track"], str(r["race_date"])[:10], int(r["race_no"]))
                out[k] = v if k not in out else min(out[k], v)
    return out


def fetch_late_table(base, key):
    rows = get(base, key, "/rest/v1/nar_meta?select=value&key=eq.%s" % urllib.parse.quote(karte.LATE_KEY))
    v = rows[0].get("value") if rows else None
    return v if isinstance(v, dict) else None


# ---------------------------------------------------------------- 組み立て

def to_run(r, kb=None, rf=None, race=None, win=None):
    """nar_runs の 1 行 + 材料 → karte の「走 1 本の形」。"""
    d = str(r["race_date"])[:10]
    no = int(r["race_no"])
    u = karte.int_or_none(r.get("runner_number"))
    run = {"track": r["track"], "race_date": d, "race_no": no, "umaban": u,
           "finish": karte.int_or_none(r.get("finish")), "note": r.get("finish_note"),
           "pop": karte.int_or_none(r.get("popularity")), "time": karte.num_or_none(r.get("time_sec")),
           "win_time": None, "post_time": None, "race_name": None, "late": None,
           "c1": None, "n1": None, "c4": None, "n4": None}
    k3 = (r["track"], d, no)
    if race is not None and k3 in race:
        run["post_time"] = race[k3].get("post_time")
        run["race_name"] = race[k3].get("race_name")
    if win is not None:
        run["win_time"] = win.get(k3)
    if kb is not None:
        note = kb.get((r["track"], d, no, r.get("horse_name")))
        run["late"] = None if note is None else bool(karte.LATE_RE.search(note))
    if rf is not None and u is not None:
        f = rf.get((d, r["track"], no, u))
        if f:
            for c in ("c1", "n1", "c4", "n4"):
                run[c] = f.get(c)
    return run


def hkeys_of(r):
    """nar_run_facts の horse_key の 2 通りの字面(公式= 名前|生年月日・楽天= 名前|生年)。"""
    name = r.get("horse_name")
    by = facts.birth_year_of(r.get("birth_date"), r.get("age"), r.get("race_date"))
    out = set()
    if name and r.get("birth_date"):
        out.add("%s|%s" % (name, str(r["birth_date"])[:10]))
    if name and by is not None:
        out.add("%s|%d" % (name, by))
    return out


def build_day(base, key, date, tracks, late_table, race_no=None, now=None):
    """1 日ぶんの nar_karte_facts の行。⛔読むのは REST だけ・数えるのは pipeline/karte.py。

    race_no= 1 レースだけ(手元の読むだけの模擬で読む量を減らすため)。
    """
    entries = [e for e in fetch_entries(base, key, date, tracks)
               if e.get("runner_number") is not None and (race_no is None or int(e["race_no"]) == int(race_no))]
    if not entries:
        return []
    for e in entries:
        e["race_date"] = date
    names = sorted({e["horse_name"] for e in entries if e.get("horse_name")})
    prev = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    hist = fetch_history(base, key, names, prev)                  # ⛔その日より前だけ
    kb = fetch_kb(base, key, names, prev)
    hk = set()
    for r in hist + entries:
        hk |= hkeys_of(r)
    rf = fetch_run_facts(base, key, hk)
    d0 = (dt.date.fromisoformat(date) - dt.timedelta(days=karte.FORM_DAYS)).isoformat()
    need_race = {(r["track"], str(r["race_date"])[:10]) for r in hist if r["track"] in karte.SOUTH}
    need_win = {(r["track"], str(r["race_date"])[:10]) for r in hist
                if str(r["race_date"])[:10] >= d0 and r.get("time_sec") is not None}
    race = fetch_races(base, key, need_race)
    win = fetch_win_times(base, key, need_win)
    by_key = {}
    for r in hist:
        mk = match_key(r)
        if mk:
            by_key.setdefault(mk, []).append(to_run(r, kb=kb, rf=rf, race=race, win=win))
    now = now or dt.datetime.now(JST).isoformat(timespec="seconds")
    by_race = {}
    for e in entries:
        by_race.setdefault((e["track"], int(e["race_no"])), []).append(e)
    out = []
    for (track, no), group in sorted(by_race.items()):
        for e in group:
            mk = match_key(e)
            u = int(e["runner_number"])
            opps = [(o["runner_number"], o["horse_name"], by_key.get(match_key(o), []) if match_key(o) else [])
                    for o in group if o is not e]
            style = (rf.get((date, track, no, u)) or {}).get("style")
            entry = {"race_date": date, "track": track, "race_no": no, "umaban": u,
                     "horse_name": e.get("horse_name"),
                     "horse_key": facts.horse_key(e.get("horse_name"), e.get("birth_date"), e.get("age"), date)
                     if mk else None}
            out.append(karte.build_row(entry, by_key.get(mk, []) if mk else [], opps, style, late_table, now))
    return out


def build_late_table(base, key, lo=karte.LATE_FROM, hi=karte.LATE_TO):
    """出遅れの割合表(⛔南関 lo〜hi の走)。記録のある直近 5 走の出遅れ回数 0/1/2/3+ → その走で出遅れた割合。"""
    t0 = time.time()
    targets = rows_all(base, key,
                       "/rest/v1/nar_runs?select=%s&track=in.(%s)&race_date=gte.%s&race_date=lte.%s"
                       "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc"
                       % (RUN_COLS, q_in(karte.SOUTH), lo, hi))
    names = sorted({r["horse_name"] for r in targets if r.get("horse_name")})
    log("  割合表: 南関 %s〜%s の行 %s・馬名 %s" % (lo, hi, format(len(targets), ","), format(len(names), ",")))
    hist = fetch_history(base, key, names, hi)
    kb = fetch_kb(base, key, names, hi)
    by_key = {}
    for r in hist:
        mk = match_key(r)
        if mk:
            by_key.setdefault(mk, []).append(to_run(r, kb=kb))
    pairs = []
    for runs in by_key.values():
        pairs.extend(karte.late_targets(runs, lo, hi))
    buckets = karte.late_table_counts(pairs)
    log("  割合表: 材料 %s 走 (%.0f 秒)" % (format(len(pairs), ","), time.time() - t0))
    return {"from": lo, "to": hi, "tracks": list(karte.SOUTH), "n": len(pairs), "buckets": buckets,
            "rule": "記録のある直近5走の出遅れ回数(0/1/2/3以上)→その走で出遅れた割合。その走も記録のある実走だけ",
            "built": dt.datetime.now(JST).isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 表で出す(ドライラン)

def _kn(rate, n):
    if n is None:
        return "-"
    return "%d/%d" % (round((rate or 0) * n), n)


def fmt_row(r):
    late = "-" if r["late_n"] is None else "%d/%d" % (r["late_n"], r["late_den"])
    pct = "-" if r["late_next_pct"] is None else "%g%%" % r["late_next_pct"]
    h2h = "-" if r["h2h"] is None else "%d勝%d敗(%d頭)" % (r["h2h_w"], r["h2h_l"], len(r["h2h"]))
    best = "-" if r["best_margin"] is None else "%.1f(%s)" % (r["best_margin"], r["best_margin_date"])
    rec = "-" if r["recent3_margin"] is None else "%.1f" % r["recent3_margin"]
    return ("%s%2dR %2d %-10s 出遅%s 次%s | %s 位置%s | 粘%s 失速%s | 30日%s 今年%s 休明%s | 大井%s 他3%s 夜%s 昼%s"
            " | 相手%s | 良%s 近%s 人気上%s 勝切%s"
            % (r["track"], r["race_no"], r["umaban"], r["horse_name"], late, pct, r["style"] or "-",
               r["pos_var"] or "-", _kn(r["lead_hold_rate"], r["lead_hold_n"]), _kn(r["fade4_rate"], r["fade4_n"]),
               r["runs_30d"], r["run_of_year"], r["since_layoff"] if r["since_layoff"] is not None else "-",
               _kn(r["oi_top3_rate"], r["oi_n"]), _kn(r["other3_top3_rate"], r["other3_n"]),
               _kn(r["night_top3_rate"], r["night_n"]), _kn(r["day_top3_rate"], r["day_n"]),
               h2h, best, rec, _kn(r["pop_beat_rate"], r["pop_beat_n"]), _kn(r["win_conv_rate"], r["win_conv_n"])))


def dates_of(a):
    if a.date:
        return [a.date]
    today = dt.datetime.now(JST).date()
    return [today.isoformat(), (today + dt.timedelta(days=1)).isoformat()]


def main():
    ap = argparse.ArgumentParser(description="分析タブの事実 nar_karte_facts を焼く(§239a)")
    ap.add_argument("--date", help="YYYY-MM-DD(既定= JST の今日と明日)")
    ap.add_argument("--track", help="場名(大井/船橋/川崎/浦和)。既定= 4 場")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定はドライラン= 書かずに表で出す)")
    ap.add_argument("--late-table", action="store_true", help="出遅れの割合表を数え直す(--apply で nar_meta へ)")
    ap.add_argument("--selftest", action="store_true", help="数え方の自己診断だけ(通信なし)")
    a = ap.parse_args()
    if a.selftest:
        return karte.selftest()
    if karte.selftest(quiet=True) or facts.selftest(quiet=True):   # ⛔走る前に必ず規則を通す(黙って通る)
        log("⛔数え方の自己診断が落ちた= 走らない")
        return 2
    if a.track and a.track not in karte.SOUTH:
        log("⛔--track は南関 4 場だけ(%s)" % "・".join(karte.SOUTH))
        return 2
    tracks = [a.track] if a.track else list(karte.SOUTH)
    base, key = env()
    mode = "(apply)" if a.apply else "(ドライラン)"
    if a.late_table:
        table = build_late_table(base, key)
        log("割合表 %s %s" % (mode, json.dumps(table["buckets"], ensure_ascii=False)))
        if a.apply:
            st, err = upsert(base, key, "nar_meta", [{"key": karte.LATE_KEY, "value": table,
                                                      "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}], "key")
            log("nar_meta/%s 更新 HTTP%s %s" % (karte.LATE_KEY, st, err))
            if st >= 300 or st == 0:
                return 1
    else:
        table = fetch_late_table(base, key)
        if table is None:
            log("⚠ 出遅れの割合表(nar_meta %s)が無い= late_next_pct は空のまま(--late-table で作る)" % karte.LATE_KEY)
    total = 0
    for d in dates_of(a):
        t0 = time.time()
        rows = build_day(base, key, d, tracks, table)
        total += len(rows)
        log("nar_karte_facts %s %s %s 行 (%.0f 秒) %s" % (d, "・".join(tracks), len(rows), time.time() - t0, mode))
        if not a.apply:
            for r in rows:
                log("  " + fmt_row(r))
            continue
        for i in range(0, len(rows), BATCH):
            st, err = upsert(base, key, TABLE, rows[i:i + BATCH], PK)
            if st >= 300 or st == 0:
                log("  %s: HTTP%s %s (batch %d)" % (d, st, err, i))
                return 1
    log("合計 %s 行 %s" % (format(total, ","), "投入" if a.apply else "ドライラン(⛔書いていない)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

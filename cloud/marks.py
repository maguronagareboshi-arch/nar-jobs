# -*- coding: utf-8 -*-
"""本体 cloud: AI印の型 — base-v0(公式データの単純スコア)の印を計算し発走前に凍結保存する(DESIGN §15)。

nar_ai_marks に (model, track, race_date, race_no, timing) で upsert する。凍結ルール:
  - timing='morning'(朝予想): その日の最初の1回だけ書く(行が既にあれば触らない)
  - timing='last'(直前予想): 発走15分前までは上書きし、それ以降は書かない
  - どちらも「今が発走15分前を過ぎたレース」には新規でも書かない(発走後の後出しを作らない)
成績集計(pipeline/sql/ai_record.sql)は computed_at >= 発走時刻 の行を保険としてさらに除外する。
Codex 製 AI も同じ契約で自分の model 名の行を書けば、同じ成績ページに載る(DESIGN §15.4)。

  python cloud/marks.py                     # 今日(JST)の全レース
  python cloud/marks.py --dry-run           # 計算だけ(投入しない)
  python cloud/marks.py --env pipeline/.env.nar --date 2026-08-24
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(GitHub Secrets)
終了コード: 0 正常(対象なし含む)/ 1 投入失敗 / 2 前提の読み取りに失敗
"""
import argparse
import datetime as dt
import os
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
from load_nar_official import load_env, upsert  # noqa: E402
from odds import sb_get, log  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
MODEL = "base-v0"
TABLE = "nar_ai_marks"
CONFLICT = "model,track,race_date,race_no,timing"
FREEZE_MIN = 15                 # 発走の何分前で凍結するか
MARKS = ["◎", "○", "▲", "△"]
HIST_N = 6                      # 各馬の過去何走を見るか
SCRATCH = ("取消", "除外")       # 発走前に分かる出走しない馬

# base-v0 のスコア(足し算だけの見える式。重みは決め打ち・学習していない)
#   近走: 直近6走の着順点(1着10/2着6/3着4/4-5着2/6-9着0.5)を新しい順に 0.85 倍ずつ減衰して合計(最大 ~33)
#   実績: 同距離帯(±200m)の3着内率 ×6 + 当地(同じ場)の3着内率 ×4
#   騎手: その場での騎手勝率(%) ×0.3(nar_person_stats・出走10以上の行が無ければ 0)
#   休み明け: 前走から180日以上で −3
W_DIST, W_TRACK, W_JOCKEY, PENALTY_LAYOFF = 6.0, 4.0, 0.3, 3.0
DECAY = 0.85
FIN_PTS = {1: 10.0, 2: 6.0, 3: 4.0}


def enc(s):
    return urllib.parse.quote(str(s), safe="")


def post_dt(race_date, hhmm):
    """post_time 'HHMM' → JST datetime。読めなければ None。"""
    s = str(hhmm or "").strip()
    if len(s) != 4 or not s.isdigit():
        return None
    return dt.datetime.combine(race_date, dt.time(int(s[:2]), int(s[2:])), tzinfo=JST)


# ---------------------------------------------------------------- 素点

def form_score(hist):
    """直近 HIST_N 走の着順点(新しい順に減衰)。hist は race_date 降順。"""
    total = 0.0
    for k, h in enumerate(hist[:HIST_N]):
        fin = h.get("finish")
        if not isinstance(fin, int) or fin < 1:
            continue
        if fin in FIN_PTS:
            pts = FIN_PTS[fin]
        elif fin <= 5:
            pts = 2.0
        elif fin <= 9:
            pts = 0.5
        else:
            pts = 0.0
        total += pts * (DECAY ** k)
    return total


def top3_rate(hist, cond):
    """条件 cond(h)→bool を満たす過去走の3着内率(該当2走未満は None)。"""
    rows = [h for h in hist if cond(h) and isinstance(h.get("finish"), int) and h["finish"] >= 1]
    if len(rows) < 2:
        return None
    return sum(1 for h in rows if h["finish"] <= 3) / len(rows)


def score_runner(entry, hist, jockey_win, race):
    """(score, factors[]) を返す。factors は「データ上位馬」で見せる短い根拠。"""
    factors = []
    s_form = form_score(hist)
    dist = race.get("distance_m")

    def near_dist(h):
        return bool(dist and h.get("distance_m") and abs(h["distance_m"] - dist) <= 200)

    r_dist = top3_rate(hist, near_dist)
    r_track = top3_rate(hist, lambda h: h.get("track") == race["track"])
    score = s_form
    if r_dist is not None:
        score += W_DIST * r_dist
        if r_dist >= 0.5:
            factors.append("同距離実績")
    if r_track is not None:
        score += W_TRACK * r_track
        if r_track >= 0.5:
            factors.append("当地実績")
    if jockey_win is not None:
        score += W_JOCKEY * jockey_win
        if jockey_win >= 15:
            factors.append("騎手好調")
    if s_form >= 14:
        factors.insert(0, "近走好調")
    if hist:
        try:
            days = (race["race_date"] - dt.date.fromisoformat(str(hist[0]["race_date"]))).days
            if days >= 180:
                score -= PENALTY_LAYOFF
                factors.append("休み明け")
        except (KeyError, ValueError):
            pass
    else:
        factors.append("初出走")
    return score, factors


# ---------------------------------------------------------------- 1日ぶんの取得と計算

def fetch_history(base, key, names, today):
    """馬名リスト → {馬名: 過去走(新しい順・最大 HIST_N)}。過去走の距離は nar_races から2段で付ける。"""
    hist = {}
    keys = set()
    names = sorted({n for n in names if n})
    for i in range(0, len(names), 25):
        inlist = ",".join('"' + n.replace('"', "") + '"' for n in names[i:i + 25])
        rows = sb_get(base, key,
                      f"nar_runs?select=horse_name,track,race_date,race_no,finish"
                      f"&horse_name=in.({enc(inlist)})&race_date=lt.{today}&order=race_date.desc&limit=3000")
        for r in rows:
            lst = hist.setdefault(r["horse_name"], [])
            if len(lst) < HIST_N:
                lst.append(r)
                keys.add((r["track"], r["race_date"], r["race_no"]))
    dist = {}
    keys = sorted(keys)
    for i in range(0, len(keys), 80):
        ors = ",".join(f"and(track.eq.{enc(t)},race_date.eq.{d},race_no.eq.{n})" for t, d, n in keys[i:i + 80])
        rows = sb_get(base, key, f"nar_races?select=track,race_date,race_no,distance_m&or=({ors})&limit=1000")
        for r in rows:
            dist[(r["track"], r["race_date"], r["race_no"])] = r.get("distance_m")
    for lst in hist.values():
        for h in lst:
            h["distance_m"] = dist.get((h["track"], h["race_date"], h["race_no"]))
    return hist


def fetch_jockey_win(base, key, jockeys, track):
    """{騎手名: その場の勝率%}。行が無い(その場で出走10未満)騎手は載らない。"""
    out = {}
    names = sorted({j for j in jockeys if j})
    for i in range(0, len(names), 25):
        inlist = ",".join('"' + n.replace('"', "") + '"' for n in names[i:i + 25])
        rows = sb_get(base, key,
                      f"nar_person_stats?select=name,win:stats->win&kind=eq.jockey&period=eq.all"
                      f"&track=eq.{enc(track)}&name=in.({enc(inlist)})&limit=100")
        for r in rows:
            try:
                out[r["name"]] = float(r["win"])
            except (TypeError, ValueError):
                pass
    return out


def build_day(base, key, day, now):
    """今日の全レースの印(morning/last の書き込み候補)を作る。"""
    races = sb_get(base, key, f"nar_races?select=track,race_date,race_no,post_time,distance_m"
                              f"&race_date=eq.{day}&order=track.asc,race_no.asc&limit=300")
    if not races:
        log(f"{day}: レースなし")
        return [], 0
    runs = sb_get(base, key, f"nar_runs?select=track,race_no,runner_number,horse_name,jockey,finish,finish_note"
                             f"&race_date=eq.{day}&limit=3000")
    entries = {}
    for r in runs:
        entries.setdefault((r["track"], r["race_no"]), []).append(r)
    existing = sb_get(base, key, f"{TABLE}?select=track,race_no,timing&model=eq.{MODEL}&race_date=eq.{day}&limit=1000")
    have = {(r["track"], r["race_no"], r["timing"]) for r in existing}

    hist = fetch_history(base, key, [r.get("horse_name") for r in runs], day)
    jw_by_track = {}
    rows, skipped = [], 0
    for race in races:
        track, no = race["track"], race["race_no"]
        pdt = post_dt(dt.date.fromisoformat(day), race.get("post_time"))
        race["race_date"] = dt.date.fromisoformat(day)
        if pdt is None:
            skipped += 1
            continue
        if now >= pdt - dt.timedelta(minutes=FREEZE_MIN):   # 凍結後は新規も上書きもしない
            continue
        want = ["last"]
        if (track, no, "morning") not in have:
            want.insert(0, "morning")
        ent = [e for e in entries.get((track, no), [])
               if e.get("finish") is None and not any(k in str(e.get("finish_note") or "") for k in SCRATCH)]
        if len(ent) < 4:      # 印4つ打てない頭数は対象外
            continue
        if track not in jw_by_track:
            names_j = [e.get("jockey") for (t2, _n2), es in entries.items() if t2 == track for e in es]
            jw_by_track[track] = fetch_jockey_win(base, key, names_j, track)
        jw = jw_by_track[track]
        scored = []
        for e in ent:
            sc, factors = score_runner(e, hist.get(e.get("horse_name"), []), jw.get(e.get("jockey")), race)
            scored.append((sc, e["runner_number"], factors))
        scored.sort(key=lambda x: (-x[0], x[1]))
        marks = [{"num": num, "mark": MARKS[i], "score": round(sc, 2)} for i, (sc, num, _f) in enumerate(scored[:4])]
        factors = {str(num): f for _sc, num, f in scored[:4] if f}
        for timing in want:
            rows.append({"model": MODEL, "track": track, "race_date": day, "race_no": no, "timing": timing,
                         "marks": marks, "meta": {"factors": factors, "n": len(ent)},
                         "computed_at": now.isoformat()})
    return rows, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env")
    ap.add_argument("--url")
    ap.add_argument("--key")
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    base = args.url or os.environ.get("SUPABASE_URL")
    key = args.key or os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    now = dt.datetime.now(JST)
    day = args.date or now.date().isoformat()
    try:
        rows, skipped = build_day(base, key, day, now)
    except Exception as e:
        log(f"読み取り失敗: {e}")
        return 2
    n_m = sum(1 for r in rows if r["timing"] == "morning")
    log(f"{day}: 書き込み {len(rows)} 行(morning {n_m} / last {len(rows) - n_m})・post_time 不明 {skipped}R")
    for r in rows[:6]:
        log("  " + f"{r['track']} {r['race_no']}R {r['timing']}: " +
            " ".join(f"{m['mark']}{m['num']}({m['score']})" for m in r["marks"]))
    if args.dry_run or not rows:
        return 0
    st, err = upsert(base, key, TABLE, CONFLICT, rows)
    if st not in (200, 201):
        log(f"投入失敗 {st} {err}")
        return 1
    log("投入完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())

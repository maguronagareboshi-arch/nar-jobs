# -*- coding: utf-8 -*-
"""統合ビューア cloud: コース特性(場×距離の 枠番/型/逃げ馬・§103)。

過去1年(**当日を含まない**)の公式の結果を、場ごと1行の nar_meta `course_stats:<prefix>` に数える。
⛔全部「地方競馬全国協会の発表(公式)の結果を当サイトが数えたもの」= 推定は1つも入れない。
⛔率は入れない(画面で割る)。小数を持つのは 平均頭数 と 勝ち時計 だけ。

  頭数   = 距離ごとの レース数・平均頭数・勝ち時計(finish=1 の time_sec の中央値)・馬場状態の内訳
  枠番別 = 枠 1〜8 の 出走数 n・1着 w・連対 p2・3着内 p3(距離の出走が GATE_MIN 走以上のときだけ)
  型別   = 1番目のコーナーの位置 p(§99a と同じ 順位÷そのコーナーに並んだ頭数)を4つに割る
           p<=0.2 前 / <=0.4 やや前 / <=0.7 中 / >0.7 後ろ(⛔通過順の読めた走だけ)
  逃げ馬 = 1番目のコーナーで**単独1位**だった馬の 勝率/連対率/3着内率(n= レース数・LEAD_MIN 本以上)
  勝ち時計 = **過去3年**の 馬場状態×クラス帯 の中央値(§104・⛔ここだけ窓が3年。上の4つは1年のまま)

  py -3.12 -X utf8 cloud/course_stats.py --env pipeline/.env.nar                    # ドライラン(数だけ)
  py -3.12 -X utf8 cloud/course_stats.py --env pipeline/.env.nar --apply            # nar_meta へ upsert(14行)
  py -3.12 -X utf8 cloud/course_stats.py --env pipeline/.env.nar --prefix kochi --verify  # 検品(§3)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY  ⛔#465: --env が無ければ環境変数だけで動く
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ(#8): 全取得はページング。⛔offset の order= は**一意**に(#468)。
⛔updated_at を必ず送る(#155)。⛔帯広ばは対象外(#111: コーナーの通過順が無い)。
⛔「走った」の定義は**サイトで1つ**(#262/#267 と pipeline/sql/venue_stats.sql):
  着順あり or 競走中止/失格。「競走取止め」(レース不成立)は走っていないので入れない。
⛔通過順の読み方・30日窓の取得・場の表は **cloud/tenkai.py から import**(3か所目を作らない)。
"""
import argparse
import datetime as dt
import io
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
# ⛔§99 の読み方・取得の割り方・場の表をそのまま使う(§5.4)
import tenkai                                                   # noqa: E402
from tenkai import TRACK2PREFIX, first_corner, rows_window        # noqa: E402
# ⛔クラス帯の読み方(race_name からの粗い抽出)は cloud/baba.py の 1 か所だけ(§5.4)
from baba import band_of                                          # noqa: E402

UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"
META_PREFIX = "course_stats:"
JST = dt.timezone(dt.timedelta(hours=9))
DAYS = 365              # 窓(当日は入れない= until は前日)
# §104 勝ち時計だけ**別の窓**。2026-09-05 ユーザーFB「良〜不良でもクラスでも違う。1年では弱い」。
# ⛔DB にレースがあるのは 2022年10月以降なので、そこで床を打つ(空の期間を名乗らない)
TIME_DAYS = 1095
TIME_FLOOR = "2022-10-01"
TIME_MIN = 8            # 勝ち時計の組(クラス×馬場)を出す最少の本数。⛔小サンプルから中央値を言わない
ANY = "*"               # times の cls/going の「問わない」。⛔going の生の値と混ざらない字にする
OTHER = "その他"        # クラス帯を読み取れなかったレース
GATE_MIN = 200          # 枠番別・型別を出す最少の出走数(その距離ぜんぶで)
LEAD_MIN = 30           # 逃げ馬を出す最少のレース数
GATES = range(1, 9)     # 枠は 1〜8(9・10 枠があるのは帯広ばだけ=対象外)
# 位置 p の切れ目。⛔§99a の LEAD_P/FRONT_P/MID_P と**同じ数**だが、あちらは「馬の型」・
#   こちらは「その走の位置」で別の量なので写さずここに置く(名前も画面の言葉に合わせる)
STYLE_BANDS = ((0.2, "前"), (0.4, "やや前"), (0.7, "中"), (1.01, "後ろ"))
STYLES = [s for _p, s in STYLE_BANDS]
# 「走った」= 着順あり or 競走中止/失格(#262/#267)。⛔日本語は URL に入る前に符号化する
RAN_IN = "finish.gt.0,finish_note.in.(%s,%s)" % (
    urllib.parse.quote('"競走中止"'), urllib.parse.quote('"失格"'))
RAN = "or=(" + RAN_IN + ")"          # 単独で足すとき
RAN_NEST = "or(" + RAN_IN + ")"      # and=(…) の中に入れるとき(検品)
RACE_TMPL = ("/rest/v1/nar_races?select=track,race_date,race_no,distance_m,going,corners"
             "&race_date=gte.{lo}&race_date=lte.{hi}"
             "&order=race_date.asc,track.asc,race_no.asc")
RUN_TMPL = ("/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,gate,finish,time_sec"
            "&race_date=gte.{lo}&race_date=lte.{hi}&" + RAN +
            "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")
# §104 勝ち時計の材料。⛔3年ぶんの nar_runs を**全部は引かない**= 1着で時計のある行だけ
#   (cloud/baba.py の wins と同じ書き方)。⛔1レース1行なので order は一意
WIN_TMPL = ("/rest/v1/nar_runs?select=track,race_date,race_no,time_sec"
            "&finish=eq.1&time_sec=not.is.null&race_date=gte.{lo}&race_date=lte.{hi}"
            "&order=race_date.asc,track.asc,race_no.asc")
# 3年ぶんのレース属性(距離・レース名・馬場状態)。⛔通過順(corners)は要らないので引かない
RACE_TIME_TMPL = ("/rest/v1/nar_races?select=track,race_date,race_no,distance_m,race_name,going"
                  "&race_date=gte.{lo}&race_date=lte.{hi}"
                  "&order=race_date.asc,track.asc,race_no.asc")

N_REQ = [0]


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None, prefer=None, tries=2):
    """⛔Supabase は一時的に 500 を返す(台帳の既知挙動)。GET は1回だけ待って引き直す。"""
    last = None
    for i in range(tries):
        N_REQ[0] += 1
        r = urllib.request.Request(base + path, method=method, data=body, headers={
            "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
            "Content-Type": "application/json",
            "Prefer": prefer or "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return x.status, x.headers.get("Content-Range"), x.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last = e
            if method != "GET" or e.code < 500 or i == tries - 1:
                raise
            log("  ⚠ HTTP %d。5秒待って引き直す" % e.code)
            time.sleep(5)
        except urllib.error.URLError as e:
            last = e
            if i == tries - 1:
                raise
            log("  ⚠ 通信に失敗。5秒待って引き直す: %s" % str(e)[:80])
            time.sleep(5)
    raise last


def window(base, key, tmpl, lo, hi):
    """tenkai.rows_window(30日の窓+一意な order)を**そのまま**使い、窓ごとに1回だけ引き直す。

    ⛔ページングの規則を写さない(#468 はあちらの docstring が正)。ここで足すのは
      「窓ぜんぶを1回やり直す」だけ= 読み取りなので何度やっても同じ。
    """
    for i in range(2):
        try:
            return rows_window(base, key, tmpl, lo, hi)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if i:
                raise
            log("  ⚠ 取得に失敗(%s)。10秒待って窓ごと引き直す" % str(e)[:60])
            time.sleep(10)
    return []


# ---------------------------------------------------------------- 集計

def blank_dist():
    return {"races": 0, "starts": 0, "win_times": [], "going": {},
            "gate": {g: [0, 0, 0, 0] for g in GATES},          # n, w, p2, p3
            "style": {s: [0, 0, 0, 0] for s in STYLES},
            "lead": [0, 0, 0, 0], "read": 0}


def pos_band(p):
    for edge, name in STYLE_BANDS:
        if p <= edge:
            return name
    return STYLES[-1]


def add_row(cell, row):
    """1走を 枠 に足す。⛔戻り値は (1着か, 連対か, 3着内か)= 型・逃げ馬でも同じ数え方を使う"""
    fin = row.get("finish")
    f = int(fin) if isinstance(fin, int) or (isinstance(fin, str) and str(fin).isdigit()) else None
    w = 1 if f == 1 else 0
    p2 = 1 if f is not None and f <= 2 else 0
    p3 = 1 if f is not None and f <= 3 else 0
    g = row.get("gate")
    if g is not None and int(g) in cell["gate"]:
        c = cell["gate"][int(g)]
        c[0] += 1
        c[1] += w
        c[2] += p2
        c[3] += p3
    return w, p2, p3


def aggregate(races, runs):
    """(races, runs) → {prefix: {距離: セル}}。⛔表に無い場(帯広ば)は落とす"""
    by_race = {}
    for r in runs:
        by_race.setdefault((r["track"], r["race_date"], r["race_no"]), []).append(r)
    out = {}
    for r in races:
        track = r.get("track")
        if track not in TRACK2PREFIX or r.get("distance_m") is None:
            continue
        rows = by_race.get((track, r["race_date"], r["race_no"]))
        if not rows:
            continue                                   # 走った馬が1頭も無い= 数えない
        cell = out.setdefault(TRACK2PREFIX[track], {}).setdefault(int(r["distance_m"]), blank_dist())
        cell["races"] += 1
        cell["starts"] += len(rows)
        going = str(r.get("going") or "").strip()
        if going:
            cell["going"][going] = cell["going"].get(going, 0) + 1
        ranks = first_corner(r.get("corners"))
        leaders = [u for u, k in (ranks or {}).items() if k == 1]
        for row in rows:
            w, p2, p3 = add_row(cell, row)
            u = row.get("runner_number")
            if not ranks or u is None or int(u) not in ranks:
                continue
            cell["read"] += 1
            b = cell["style"][pos_band(ranks[int(u)] / len(ranks))]
            b[0] += 1
            b[1] += w
            b[2] += p2
            b[3] += p3
            # 逃げ馬= 1番目のコーナーで**単独**1位。⛔並走(同順位が2頭以上)は「逃げ馬」を決められない
            if len(leaders) == 1 and int(u) == leaders[0] and row.get("finish") is not None:
                cell["lead"][0] += 1
                cell["lead"][1] += w
                cell["lead"][2] += p2
                cell["lead"][3] += p3
    return out


def pack(dists, times=None, t_since=None, t_until=None):
    """1場ぶんのセル → blob の dist ブロック。⛔条件に満たない節は**キーごと省く**。

    ⛔`times`(§104・3年)を渡したときだけ `times` キーを足す。渡さなければ §103 と1バイトも変わらない。
    """
    out = {}
    for d in sorted(dists):
        c = dists[d]
        cell = {"races": c["races"],
                "avg_head": round(c["starts"] / c["races"], 1) if c["races"] else None}
        if c["win_times"]:
            cell["win_time"] = round(statistics.median(c["win_times"]), 1)
        if c["going"]:
            cell["going"] = dict(sorted(c["going"].items(), key=lambda kv: -kv[1]))
        if c["starts"] >= GATE_MIN:
            gate = [{"g": g, "n": v[0], "w": v[1], "p2": v[2], "p3": v[3]}
                    for g, v in sorted(c["gate"].items()) if v[0]]
            if gate:
                cell["gate"] = gate
            style = [{"s": s, "n": c["style"][s][0], "w": c["style"][s][1],
                      "p2": c["style"][s][2], "p3": c["style"][s][3]}
                     for s in STYLES if c["style"][s][0]]
            if style:
                cell["style"] = style
        if c["lead"][0] >= LEAD_MIN:
            cell["lead"] = {"n": c["lead"][0], "w": c["lead"][1],
                            "p2": c["lead"][2], "p3": c["lead"][3]}
        if times is not None:
            t = pack_times(times.get(d) or {}, t_since, t_until)
            if t:
                cell["times"] = t
        out[str(d)] = cell
    return out


def collect_win_times(dists, races, runs):
    """勝ち時計(finish=1 の time_sec)を距離ごとに集める。⛔別の走査にしない= aggregate の中で
    やると「走った」の判定と混ざるので、着順1だけを見るここに分けた"""
    dist_of = {}
    for r in races:
        if r.get("track") in TRACK2PREFIX and r.get("distance_m") is not None:
            dist_of[(r["track"], r["race_date"], r["race_no"])] = (
                TRACK2PREFIX[r["track"]], int(r["distance_m"]))
    for row in runs:
        if row.get("finish") != 1 or row.get("time_sec") is None:
            continue
        hit = dist_of.get((row["track"], row["race_date"], row["race_no"]))
        if not hit:
            continue
        cell = dists.get(hit[0], {}).get(hit[1])
        if cell:
            cell["win_times"].append(float(row["time_sec"]))


# ---------------------------------------------------------------- §104 勝ち時計(3年・馬場状態×クラス)

def time_since(today):
    """勝ち時計の窓の始まり。⛔DB にレースがあるのは 2022年10月以降= そこで床を打つ"""
    return max((today - dt.timedelta(days=TIME_DAYS)).isoformat(), TIME_FLOOR)


def collect_times(win_rows, race_rows):
    """(1着の時計, レース属性)→ {prefix: {距離: {(cls, going): [秒, …]}}}。

    ⛔クラス帯は cloud/baba.py の band_of(race_name の粗い抽出)をそのまま使う。読めない走は「その他」。
    ⛔(cls, going) のほかに「問わない」(ANY)の口も同時に積む= 画面の「全体」列/行が
      **中央値の中央値**にならないようにするため(平均と違って median は積み直せない)。
    """
    attr = {}
    for r in race_rows:
        if r.get("track") in TRACK2PREFIX and r.get("distance_m") is not None:
            attr[(r["track"], r["race_date"], r["race_no"])] = (
                TRACK2PREFIX[r["track"]], int(r["distance_m"]),
                band_of(r.get("race_name"), r.get("track")) or OTHER, str(r.get("going") or "").strip())
    out = {}
    for w in win_rows:
        hit = attr.get((w["track"], w["race_date"], w["race_no"]))
        if not hit or w.get("time_sec") is None:
            continue
        prefix, dist, cls, going = hit
        cell = out.setdefault(prefix, {}).setdefault(dist, {})
        t = float(w["time_sec"])
        cell.setdefault((ANY, ANY), []).append(t)
        cell.setdefault((cls, ANY), []).append(t)
        if going:
            cell.setdefault((ANY, going), []).append(t)
            cell.setdefault((cls, going), []).append(t)
    return out


def pack_times(cell, since, until):
    """1距離ぶんの {(cls, going): [秒]} → blob の times。⛔TIME_MIN 未満の組は載せない"""
    if not cell:
        return None
    out = {"since": since, "until": until}
    total = cell.get((ANY, ANY)) or []
    if not total:
        return None
    out["all"] = {"n": len(total), "med": round(statistics.median(total), 1)}
    by = []
    for (cls, going), xs in cell.items():
        if (cls, going) == (ANY, ANY) or len(xs) < TIME_MIN:
            continue
        by.append({"cls": cls, "going": going, "n": len(xs),
                   "med": round(statistics.median(xs), 1)})
    by.sort(key=lambda x: (x["cls"], x["going"]))
    if by:
        out["by"] = by
    return out


def build(base, key, since, until, t_since=None):
    """1年の数(頭数・枠番・型・逃げ馬)と、3年の勝ち時計を組む。⛔窓が違うので取得も別。"""
    t0 = dt.datetime.now()
    races = window(base, key, RACE_TMPL, since, until)
    runs = window(base, key, RUN_TMPL, since, until)
    dists = aggregate(races, runs)
    collect_win_times(dists, races, runs)
    times = {}
    if t_since:
        # §104 ⛔3年ぶんは「1着で時計のある行」と「レースの属性」だけ(全走は引かない)
        wins = window(base, key, WIN_TMPL, t_since, until)
        t_races = window(base, key, RACE_TIME_TMPL, t_since, until)
        times = collect_times(wins, t_races)
        log("   §104 勝ち時計の材料: 1着 %d行 / レース %d行(%s〜)" % (len(wins), len(t_races), t_since))
    # ⛔取得は tenkai.rows_window がやるので、要求の数もあちらの数え(N_REQ)を足す
    log("■ %s〜%s  レース %d / 走 %d → %d場  (%.0f秒 / 要求 %d 回)"
        % (since, until, len(races), len(runs), len(dists),
           (dt.datetime.now() - t0).total_seconds(), N_REQ[0] + tenkai.N_REQ[0]))
    return dists, times


def upsert(base, key, prefix, value):
    st, _cr, _b = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                      json.dumps([{"key": META_PREFIX + prefix, "value": value,
                                   "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]
                                 ).encode("utf-8"))
    return st


# ---------------------------------------------------------------- 検品

def count_exact(base, key, path):
    """Prefer: count=exact の総数(サーバに数えさせる)。⛔こちらで行を集めない=別の書き方"""
    _st, cr, _b = req(base, key, path + "&limit=1", prefer="count=exact")
    return int(str(cr or "*/0").rsplit("/", 1)[-1])


def race_or(chunk):
    """[(日付, R), …] → PostgREST の or(...)。⛔日付と R は必ず対で見る(同じ日に別距離がある)"""
    return "or(" + ",".join("and(race_date.eq.%s,race_no.eq.%d)" % (d, n) for d, n in chunk) + ")"


def verify(base, key, prefix, since, until, t_since=None):
    track = next((t for t, p in TRACK2PREFIX.items() if p == prefix), None)
    if not track:
        log("⛔知らない場: %s" % prefix)
        return 2
    dist = 1400
    log("■ %s %dm の枠番別を、同じ1年の nar_runs を**サーバに数えさせて**突き合わせる" % (track, dist))
    races = window(base, key, RACE_TMPL, since, until)
    runs = window(base, key, RUN_TMPL, since, until)
    mine = pack(aggregate(races, runs).get(prefix, {})).get(str(dist))
    if not mine or "gate" not in mine:
        log("  この距離の枠番別は出していない(出走 %d 走未満)= 検品する数が無い" % GATE_MIN)
        return 2
    keys = sorted((r["race_date"], r["race_no"]) for r in races
                  if r.get("track") == track and r.get("distance_m") == dist)
    log("  対象レース %d 本(%s〜%s)" % (len(keys), keys[0][0], keys[-1][0]))
    tq = urllib.parse.quote(track)
    bad = 0
    for row in mine["gate"]:
        n = w = 0
        for i in range(0, len(keys), 40):                 # ⛔URL が長くなりすぎない粒(#365)
            cond = race_or(keys[i:i + 40])
            n += count_exact(base, key, "/rest/v1/nar_runs?select=runner_number&track=eq." + tq +
                             "&gate=eq.%d&and=(%s,%s)" % (row["g"], RAN_NEST, cond))
            w += count_exact(base, key, "/rest/v1/nar_runs?select=runner_number&track=eq." + tq +
                             "&gate=eq.%d&finish=eq.1&and=(%s)" % (row["g"], cond))
        ok = (n == row["n"] and w == row["w"])
        bad += 0 if ok else 1
        log("   %s 枠%d  出走 %4d / %-4d   1着 %3d / %-3d"
            % ("OK " if ok else "⛔NG", row["g"], row["n"], n, row["w"], w))
    lead = mine.get("lead")
    ok_lead = not lead or lead["n"] <= mine["races"]
    ok_time = verify_times(base, key, track, prefix, dist, t_since, until) if t_since else True
    log("  逃げ馬の n=%s ≦ レース数 %d = %s"
        % (lead["n"] if lead else "—", mine["races"], "OK" if ok_lead else "⛔NG"))
    log("\nゲート: 枠番別が全一致= %s / 逃げ馬の n が過大でない= %s / 勝ち時計が一致= %s"
        % ("OK" if not bad else "⛔NG(%d枠)" % bad, "OK" if ok_lead else "⛔NG",
           "OK" if ok_time else "⛔NG"))
    return 0 if (not bad and ok_lead and ok_time) else 1


def verify_times(base, key, track, prefix, dist, t_since, until):
    """§104 勝ち時計の組を、**その組のレースだけを名指しで引き直して**手で数え直す。

    ⛔画面と同じ道(collect_times)で引き直さない= レースを1本ずつ列挙して REST から時計を取り、
      本数と中央値を別の書き方で出す。
    """
    log("")
    log("■ %s %dm の勝ち時計(%s〜)を、組ごとにレースを名指しで引き直して突き合わせる" % (
        track, dist, t_since))
    wins = window(base, key, WIN_TMPL, t_since, until)
    t_races = window(base, key, RACE_TIME_TMPL, t_since, until)
    mine = pack_times((collect_times(wins, t_races).get(prefix) or {}).get(dist) or {},
                      t_since, until)
    if not mine:
        log("  この距離の勝ち時計は出していない= 検品する数が無い")
        return False
    log("  全体 n=%d 中央値 %.1f秒" % (mine["all"]["n"], mine["all"]["med"]))
    tq = urllib.parse.quote(track)
    bad = 0
    # ⛔全部は引かない(要求が増える)= クラスも馬場状態も実名の組のうち、本数の多い3組だけ
    picks = [x for x in (mine.get("by") or []) if x["cls"] != ANY and x["going"] != ANY]
    picks.sort(key=lambda x: -x["n"])
    for row in picks[:3]:
        keys = sorted((r["race_date"], r["race_no"]) for r in t_races
                      if r.get("track") == track and r.get("distance_m") == dist
                      and str(r.get("going") or "").strip() == row["going"]
                      and (band_of(r.get("race_name"), r.get("track")) or OTHER) == row["cls"])
        got = []
        for i in range(0, len(keys), 40):                 # ⛔URL が長くなりすぎない粒(#365)
            _st, _cr, body = req(base, key,
                                 "/rest/v1/nar_runs?select=time_sec&track=eq." + tq +
                                 "&finish=eq.1&time_sec=not.is.null&and=(%s)&limit=1000"
                                 % race_or(keys[i:i + 40]))
            got.extend(float(x["time_sec"]) for x in json.loads(body))
        med = round(statistics.median(got), 1) if got else None
        ok = (len(got) == row["n"] and med == row["med"])
        bad += 0 if ok else 1
        log("   %s %-4s × %-3s  本数 %3d / %-3d   中央値 %s / %s"
            % ("OK " if ok else "⛔NG", row["cls"], row["going"], row["n"], len(got),
               row["med"], med))
    return not bad


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--verify", action="store_true", help="検品(§3)")
    ap.add_argument("--prefix", help="--verify の場(既定 kochi)")
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    today = dt.datetime.now(JST).date()
    until = (today - dt.timedelta(days=1)).isoformat()     # ⛔当日は入れない
    since = (today - dt.timedelta(days=DAYS)).isoformat()
    t_since = time_since(today)                            # §104 勝ち時計だけ3年
    if a.verify:
        return verify(base, key, a.prefix or "kochi", since, until, t_since)

    dists, times = build(base, key, since, until, t_since)
    rc = 0
    for prefix in sorted(dists):
        value = {"built": today.isoformat(), "since": since, "until": until,
                 "dist": pack(dists[prefix], times.get(prefix) or {}, t_since, until)}
        n_gate = sum(1 for c in value["dist"].values() if "gate" in c)
        n_lead = sum(1 for c in value["dist"].values() if "lead" in c)
        n_time = sum(len(c["times"].get("by") or []) for c in value["dist"].values() if "times" in c)
        line = "  %-10s 距離 %2d(枠番別 %d・逃げ馬 %d・勝ち時計の組 %3d)  %d バイト" % (
            prefix, len(value["dist"]), n_gate, n_lead, n_time,
            len(json.dumps(value, ensure_ascii=False).encode("utf-8")))
        if not a.apply:
            log(line + "  ← ドライラン(--apply なし)")
            continue
        st = upsert(base, key, prefix, value)
        log(line + "  → nar_meta/%s%s %s" % (META_PREFIX, prefix, st))
        if st not in (200, 201):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""§294 降級の目安を「レースごと・出走馬ごと」に残す表 nar_demotion_race(過去のレースでも発走前の値を出すため)。

  表= pipeline/sql/demotion_race_20260926.sql(1 行= 1 レースの 1 頭。v= その馬の目安の行(今の 3 表の行と同じ形)・
      一覧に居ない馬は v= null。meta= 画面の見出しに要る値。asof= 計算に使った最後の日・calc_date= 計算した日)。
  ① 毎日の便(書き手= cloud/tokai_demotion.py・nankan_demotion.py・saga_demotion.py の --apply の最後に store_live)
      今日以降のレースで出走表がある馬を upsert。⛔今日のレースは発走時刻(nar_races.post_time)より前の便だけ。
      ⛔レースの日が今日より前の行は書かない(表の trigger でも止める)= 発走前の値を凍結。
  ② 過去 1 年の埋め戻し(便 demotion-race-backfill.yml・手で回す)
      python cloud/demotion_race.py --from 2025-09-26 --to 2026-09-25 [--kinds tokai,nankan,saga] [--apply]
      各レースの日 d について「d の前日まで」の材料で計算する(このレースの着は入らない):
        南関= nar_nankan_point_hist の meet_end < d の最後の行(点・kaku_ran)を nankan_demotion.forecast(today=d) に渡す。
              ⚠級は kaku_ran(出走した級)= Ａ１ は記録が無い→ 埋め戻しに出ない。馬コード→馬名は nar_nankan_points(引退馬は出ない)。
        佐賀= nar_horse_prize.runs を d より前の走だけにして saga_demotion.forecast(today=d)(saga_state は元々 d より前だけ)。
        東海= 主催者の一覧 PDF のうち日付が d 以前の行 + d の前日までの nar_runs の収得で tokai_demotion.forecast(today=d)。
              所属= d より前の最後の nar_runs.trainer_area。
      埋めない期間(理由は BACKTEST-demotion-*.md の範囲):
        笠松 2025-10-21 より前= 一覧 PDF が主催者サイトに残っていない(第11回 10/21 から)。
        名古屋 2026-04-01 より前= R7 の一覧は BACKTEST で取っておらず、R7 の見直し(第19・26回の後)で式を確かめていない。
      ⛔埋め戻しは既にある行を上書きしない(resolution=ignore-duplicates)。行が MAX_ROWS を超えたら書かずに止める。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(ドライランは読める鍵なら何でもよい)。終了コード: 0 正常 / 1 投入失敗 / 2 読み・計算の失敗
"""
import argparse
import bisect
import collections
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

JST = dt.timezone(dt.timedelta(hours=9))
TABLE = "nar_demotion_race"
CONFLICT = "venue,race_date,race_no,horse_name"
VENUE_OF = {"笠松": "kasamatsu", "名古屋": "nagoya", "大井": "ooi", "川崎": "kawasaki", "船橋": "funabashi",
            "浦和": "urawa", "佐賀": "saga"}
KIND_TRACKS = {"tokai": ("笠松", "名古屋"), "nankan": ("大井", "川崎", "船橋", "浦和"), "saga": ("佐賀",)}
FILL_FROM = {"笠松": "2025-10-21", "名古屋": "2026-04-01"}   # 埋め戻しの下限(理由は上)
LIVE_DAYS = 14          # 毎日の便で見る先の日数
MAX_ROWS = 100_000
q = urllib.parse.quote


def log(*a):
    print(*a, flush=True)


def sb_all(url, key, path, page=1000):
    out, off = [], 0
    while True:
        req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items",
            "Range": f"{off}-{off + page - 1}"})
        with urllib.request.urlopen(req, timeout=90) as r:
            got = json.loads(r.read())
        out += got
        if len(got) < page:
            return out
        off += page


def post(url, key, rows, ignore):
    """ignore= True: 既にある行は触らない(埋め戻し)/False: 上書き(毎日の便・今日以降だけ)。"""
    pref = "resolution=ignore-duplicates" if ignore else "resolution=merge-duplicates"
    for i in range(0, len(rows), 500):
        body = json.dumps(rows[i:i + 500], ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{url}/rest/v1/{TABLE}?on_conflict={CONFLICT}", data=body, method="POST", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Prefer": pref + ",return=minimal"})
        with urllib.request.urlopen(req, timeout=90) as r:
            if r.status >= 300:
                raise RuntimeError(f"upsert {r.status}")


# ---------- 出走表 ----------
def load_entries(url, key, tracks, dfrom, dto):
    """[(track, race_date, race_no, horse_name)](nar_runs の出走表。order= 主キー= 一意)。"""
    got = sb_all(url, key, f"nar_runs?select=track,race_date,race_no,horse_name&track=in.({q(','.join(tracks))})"
                           f"&race_date=gte.{dfrom}&race_date=lte.{dto}&order=track,race_date,race_no,runner_number")
    return [(g["track"], g["race_date"][:10], int(g["race_no"]), g["horse_name"]) for g in got if g.get("horse_name")]


def load_posts(url, key, tracks, d):
    got = sb_all(url, key, f"nar_races?select=track,race_no,post_time&track=in.({q(','.join(tracks))})"
                           f"&race_date=eq.{d}&order=track,race_no")
    return {(g["track"], int(g["race_no"])): str(g.get("post_time") or "").strip() for g in got}


def make_rows(kind, ents, lookup, meta_of, asof, calc_date):
    out, seen = [], set()
    for trk, d, no, name in ents:
        k = (VENUE_OF[trk], d, no, name)
        if k in seen:
            continue
        seen.add(k)
        v = lookup(trk, name)
        out.append(dict(venue=k[0], race_date=d, race_no=no, horse_name=name, kind=kind,
                        v=(dict(v) if v else None), meta=meta_of(trk), asof=asof, calc_date=calc_date))
    return out


# ---------- 画面の見出しに要る値 ----------
def tokai_meta(m):
    return {"pending": bool(m.get("pending")), "adj": m.get("adj"), "D": m.get("D"), "D2": m.get("D2")}


def nankan_meta(rows, s1, today, asof=None):
    import nankan_demotion as NK
    a = asof or max((r["pts_asof"] for r in rows if r.get("pts_asof")), default=None)
    return {"next": NK.label(s1, today), "asof": a}


def saga_meta(today):
    return {"calc_date": today.isoformat(), "target": dt.date(today.year + 1, 1, 1).isoformat()}


# ---------- ① 毎日の便 ----------
def live_rows(url, key, kind, lookup, meta_of, now=None):
    now = now or dt.datetime.now(JST)
    today = now.date().isoformat()
    tracks = KIND_TRACKS[kind]
    ents = load_entries(url, key, tracks, today, (now.date() + dt.timedelta(days=LIVE_DAYS)).isoformat())
    posts = load_posts(url, key, tracks, today) if any(e[1] == today for e in ents) else {}
    hhmm = now.strftime("%H%M")

    def before_post(e):
        p = posts.get((e[0], e[2]), "")
        return p.isdigit() and hhmm < p.zfill(4)
    keep = [e for e in ents if e[1] > today or (e[1] == today and before_post(e))]
    return make_rows(kind, keep, lookup, meta_of, today, today)


def store_live(url, key, kind, lookup, meta_of, write=True, now=None):
    """毎日の便の最後に呼ぶ。⛔落ちても例外を投げない(便を止めない)。→ 書いた行数(失敗 -1)"""
    try:
        if not (url and key):
            raise ValueError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        rows = live_rows(url, key, kind, lookup, meta_of, now)
        if write and rows:
            post(url, key, rows, ignore=False)
        log(f"§294 {TABLE} {kind}: 出走馬 {len(rows)} 行(うち目安あり {sum(1 for r in rows if r['v'])})"
            + ("" if write else "(ドライラン= 書かない)"))
        return len(rows)
    except Exception as e:
        log(f"::warning::§294 {TABLE} {kind} を書けない(続行): {type(e).__name__}: {e}")
        return -1


# ---------- ② 埋め戻し ----------
def day_before(d):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


def by_date(ents):
    g = collections.defaultdict(list)
    for e in ents:
        g[e[1]].append(e)
    return g


def bf_nankan(url, key, ents, dfrom):
    import nankan_demotion as NK
    pts = sb_all(url, key, "nar_nankan_points?select=code,horse_name,birth_date&order=code")
    code_of, birth = {}, {}
    for p in pts:
        if p.get("horse_name"):
            code_of.setdefault(p["horse_name"], str(p["code"]))
            birth[str(p["code"])] = p.get("birth_date")
    codes = sorted({code_of[e[3]] for e in ents if e[3] in code_of})
    since = (dt.date.fromisoformat(dfrom) - dt.timedelta(days=400)).isoformat()
    H = collections.defaultdict(list)
    for i in range(0, len(codes), 100):
        for h in sb_all(url, key, f"nar_nankan_point_hist?select=code,meet_end,points,kaku_ran"
                                  f"&code=in.({','.join(codes[i:i + 100])})&meet_end=gte.{since}&order=code,meet_end"):
            H[str(h["code"])].append((h["meet_end"][:10], h.get("points"), h.get("kaku_ran")))
    log(f"南関: 名前→コード {len(code_of)}・出走馬のコード {len(codes)}・点の履歴 {sum(len(v) for v in H.values())} 行")
    out, why = [], collections.Counter()
    for d, es in sorted(by_date(ents).items()):
        src, lastme = [], None
        for n in {e[3] for e in es}:
            c = code_of.get(n)
            L = H.get(c) if c else None
            if not L:
                why["コードか点の履歴なし"] += 1
                continue
            i = bisect.bisect_left([x[0] for x in L], d) - 1
            if i < 0:
                why["レースの前の点なし"] += 1
                continue
            me, p, k = L[i]
            lastme = max(lastme or me, me)
            src.append(dict(code=c, horse_name=n, kaku=k, points=p, asof=me, birth_date=birth.get(c), seen_track=None))
        today = dt.date.fromisoformat(d)
        rows, w, (sp, s0, s1) = NK.forecast(src, today)
        why.update(w)
        byn = {r["horse_name"]: r for r in rows}
        mt = nankan_meta(rows, s1, today, asof=lastme)
        out += make_rows("nankan", es, lambda trk, n: byn.get(n), lambda trk: mt, day_before(d), today.isoformat())
    log("南関: 除いた数(馬×日): " + " ".join(f"{k}={v}" for k, v in why.most_common()))
    return out


def bf_saga(url, key, ents, dfrom, node=None):
    import class_calc as cc
    import saga_demotion as SG
    consts = cc.load_consts(node)
    lines = cc.saga_lines(next(s for s in consts["SYSTEMS"] if s["id"] == "saga"))
    ledger, births, _entered, races = cc.fetch_saga(url, key, dt.date.fromisoformat(dfrom) - dt.timedelta(days=365))
    byname = collections.defaultdict(list)
    for r in ledger:
        byname[r.get("horse_name")].append(r)
    log(f"佐賀: 台帳 {len(ledger)} 頭")
    out, why = [], collections.Counter()
    for d, es in sorted(by_date(ents).items()):
        names = {e[3] for e in es}
        rows_d = [dict(r, runs=[x for x in (r.get("runs") or []) if str(x.get("d") or "")[:10] < d])
                  for n in names for r in byname.get(n, [])]
        today = dt.date.fromisoformat(d)
        got, w = SG.forecast(lines, rows_d, births, names, races, today, cc.SAGA_LAG)
        why.update(w)
        byn = {r["horse_name"]: r for r in got}
        mt = saga_meta(today)
        out += make_rows("saga", es, lambda trk, n: byn.get(n), lambda trk: mt, day_before(d), today.isoformat())
    log("佐賀: 除いた数(馬×日): " + " ".join(f"{k}={v}" for k, v in why.most_common()))
    return out


def bf_tokai(url, key, ents, dfrom, dto):
    import tokai_demotion as TK
    real_today = dt.datetime.now(JST).date()
    # 一覧= 笠松はページにある全部・名古屋は FY2026 の全部(2026-04-01 より前は埋めない)
    h = TK.http(TK.KS_PAGE).decode("utf-8", "replace")
    import re
    ks_rows = []
    for href, label in re.findall(r'href="(/resources/pdfs/raceprogram/[^"]+\.pdf)"[^>]*>\s*<p[^>]*>([^<]*)<', h):
        if "一覧" in label:
            ks_rows += TK.parse_ks(TK.http(TK.KS_BASE + href), real_today)
    ng_rows = []
    fy = TK.fiscal(dt.date.fromisoformat(max(dto, FILL_FROM["名古屋"])))
    for y in sorted({TK.fiscal(dt.date.fromisoformat(FILL_FROM["名古屋"])), fy}):
        miss = 0
        for k in range(1, 31):
            got = 0
            for dd in range(1, 9):
                u = TK.NG_FILE.format(fy=y, k=k, d=dd)
                data = TK.http(u)
                if data is None:
                    break
                ng_rows += TK.parse_ng(data, y, k)
                got += 1
            miss = miss + 1 if not got else 0
            if miss >= 2:
                break
    log(f"東海: 一覧の行 笠松 {len(ks_rows)}(最初の日 {min((r['date'] for r in ks_rows), default=None)})・"
        f"名古屋 {len(ng_rows)}(最初の日 {min((r['date'] for r in ng_rows), default=None)})")
    since = (dt.date.fromisoformat(dfrom) - dt.timedelta(days=400)).isoformat()
    # 所属= d より前の最後の trainer_area
    names = sorted({r["name"] for r in ks_rows + ng_rows})
    aff = collections.defaultdict(list)
    for i in range(0, len(names), 80):
        inq = q(",".join('"' + n + '"' for n in names[i:i + 80]))
        for x in sb_all(url, key, f"nar_runs?select=horse_name,race_date,trainer_area&horse_name=in.({inq})"
                                  f"&race_date=gte.{since}&trainer_area=not.is.null&order=race_date,race_no,horse_name,track"):
            t = {"愛知": "NG", "笠松": "KS", "岐阜": "KS"}.get(x["trainer_area"])
            aff[TK.NF(x["horse_name"])].append((x["race_date"][:10], t))
    cnt = collections.Counter((r["name"], r["trk"]) for r in ks_rows + ng_rows)

    def home(n, t, d):
        L = aff.get(TK.NF(n)) or []
        i = bisect.bisect_left([x[0] for x in L], d) - 1
        if i >= 0:
            return L[i][1] == t
        return cnt[(n, t)] > cnt[(n, "NG" if t == "KS" else "KS")]
    ks_days = TK.ks_race_days(url, key, since)
    ng_days = TK.ng_race_days(url, key, since)
    meta_all = TK.load_adj_meta(url, key)
    detected = TK.ks_detect_adj(ks_rows)
    ern_all = TK.load_earn_all(url, key, (dt.date.fromisoformat(dfrom) - dt.timedelta(days=200)).isoformat(), day_before(dto))
    log(f"東海: 所属の記録 {len(aff)} 頭・収得の馬 {len(ern_all)}")
    out, fails = [], collections.Counter()
    TKLOG = TK.log
    for d, es in sorted(by_date(ents).items()):
        today = dt.date.fromisoformat(d)
        for trk, lists, name in (("KS", ks_rows, "笠松"), ("NG", ng_rows, "名古屋")):
            e2 = [e for e in es if e[0] == name]
            if not e2 or d < FILL_FROM[name]:
                continue
            ls = [r for r in lists if r["date"] <= d and home(r["name"], trk, d)]
            if not ls:
                fails[name + " 一覧なし"] += 1
                continue
            try:
                TK.log = lambda *a: None
                if trk == "KS":
                    known, _ = TK.ks_known_adj({"KS": {k: v for k, v in ((meta_all or {}).get("KS") or {}).items() if v < d}},
                                               {k: v for k, v in detected.items() if v < d})
                    cands = TK.ks_candidates(today, [x for x in ks_days if x < d], known)
                else:
                    cands = TK.ng_candidates(today, ls, ng_days)
                rows, m = TK.forecast(trk, ls, cands, today, url, key, ern_all=ern_all, cutoff=day_before(d))
            except Exception as ex:
                fails[f"{name} 計算失敗 {type(ex).__name__}"] += 1
                continue
            finally:
                TK.log = TKLOG
            byn = {TK.NF(r["horse_name"]): r for r in rows}
            mt = tokai_meta(m)
            out += make_rows("tokai", e2, lambda t, n: byn.get(TK.NF(n)), lambda t: mt, day_before(d), d)
    if fails:
        log("東海: 埋めなかった(場×日): " + " ".join(f"{k}={v}" for k, v in fails.most_common()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", required=True)
    ap.add_argument("--to", dest="dto", required=True)
    ap.add_argument("--kinds", default="tokai,nankan,saga")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--node", help="node の場所(佐賀の線の表 class.js を読む)")
    ap.add_argument("--sample", type=int, default=1, help="種類ごとに見せる目安ありの馬の数")
    ap.add_argument("--out", help="行を JSON で書き出す先(ドライランの確かめ用)")
    a = ap.parse_args()
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    today = dt.datetime.now(JST).date().isoformat()
    if a.dto >= today:
        log(f"::error::--to は今日({today})より前に(今日以降は毎日の便が書く)")
        return 2
    allrows = []
    try:
        if not (url and key):
            raise ValueError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        for kind in [k.strip() for k in a.kinds.split(",") if k.strip()]:
            ents = load_entries(url, key, KIND_TRACKS[kind], a.dfrom, a.dto)
            log(f"{kind}: 出走表 {len(ents)} 行({a.dfrom}〜{a.dto})")
            rows = (bf_tokai(url, key, ents, a.dfrom, a.dto) if kind == "tokai"
                    else bf_nankan(url, key, ents, a.dfrom) if kind == "nankan"
                    else bf_saga(url, key, ents, a.dfrom, a.node))
            c = collections.Counter(r["venue"] for r in rows)
            cv = collections.Counter(r["venue"] for r in rows if r["v"])
            for v in sorted(c):
                days = sorted({r["race_date"] for r in rows if r["venue"] == v})
                log(f"  {v}: 行 {c[v]}(目安あり {cv[v]})・日 {len(days)}({days[0]}〜{days[-1]})")
            for r in [r for r in rows if r["v"]][-a.sample:]:
                log("  例: " + json.dumps({k: r[k] for k in ("venue", "race_date", "race_no", "horse_name", "asof", "v", "meta")},
                                         ensure_ascii=False))
            allrows += rows
    except Exception as e:
        log(f"::error::読み・計算に失敗: {type(e).__name__}: {e}")
        return 2
    log(f"合計 {len(allrows)} 行(目安あり {sum(1 for r in allrows if r['v'])})")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(allrows, f, ensure_ascii=False)
        log(f"JSON= {a.out}")
    if len(allrows) > MAX_ROWS:
        log(f"::error::{MAX_ROWS} 行を超えた= 書かずに止める")
        return 2
    if not a.apply:
        log("ドライラン= 書かない")
        return 0
    try:
        post(url, key, allrows, ignore=True)
    except Exception as e:
        log(f"::error::投入失敗: {e}")
        return 1
    log(f"書いた(既にある行は触らない) {len(allrows)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())

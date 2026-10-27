#!/usr/bin/env python3
# 「2026 年の地方競馬」まとめ(2026-10-27 試し・wip/year-review-20261027)。画面 nar-viewer /year/<年> の材料を作り、
#   公開バケット cond-stats の v1/year-review-<年>.json へ上げる(便 .github/workflows/year-review.yml)。
#   数え方は nar-site\research\year-review-2026\SPEC.md:
#   期間= 1/1〜asof(既定= JST の前日)・地方の場だけ(nar_runs に中央は無い)・着順のある走だけ(取消・除外・中止を数えない)。
#   暦= 場×日の最高払戻(単勝〜三連単の 9 券種・100 円あたり)・最多勝の馬/騎手(1 着の数・同数は全部)・最高払戻 5 位まで・
#   最年長の勝ち馬・場×距離の最速(同タイムは早い日)・開催日数/レース数/出走のべ頭数。
# ⛔本番 DB では REST の単純 select だけ(月ごとに区切り・order は一意)。書くのは Storage の cond-stats/v1/year-review-<年>.json だけ。
#   python3 cloud/year_review.py --apply
#   python3 cloud/year_review.py --dry-run --out FILE
# 環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TRACKS = [("帯広ば", "obihiro", "帯広"), ("門別", "monbetsu", "門別"), ("盛岡", "morioka", "盛岡"), ("水沢", "mizusawa", "水沢"),
          ("浦和", "urawa", "浦和"), ("船橋", "funabashi", "船橋"), ("大井", "ooi", "大井"), ("川崎", "kawasaki", "川崎"),
          ("金沢", "kanazawa", "金沢"), ("笠松", "kasamatsu", "笠松"), ("名古屋", "nagoya", "名古屋"), ("園田", "sonoda", "園田"),
          ("姫路", "himeji", "姫路"), ("高知", "kochi", "高知"), ("佐賀", "saga", "佐賀")]
SLUG = {t: s for t, s, _n in TRACKS}
KINDS = ["win", "place", "wakuren", "wakutan", "quinella", "exacta", "wide", "trio", "trifecta"]   # 重勝式は入れない
TOPN = 5
TIE_CAP = 30   # 同数を全部出すときの上限(超えたら打ち切って印 cut を付ける)


def req(base, key, path, headers=None):
    h = {"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"}
    h.update(headers or {})
    r = urllib.request.Request(base.rstrip("/") + "/rest/v1/" + path, headers=h)
    with urllib.request.urlopen(r, timeout=180) as x:
        return x.read().decode("utf-8")


def fetch_all(base, key, path, page=1000):
    """Range で 1000 行ずつ。⛔order は呼び出し側が一意にする。"""
    out, lo = [], 0
    while True:
        body = req(base, key, path, {"Range-Unit": "items", "Range": "%d-%d" % (lo, lo + page - 1)})
        rows = json.loads(body) if body else []
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def months(year, asof):
    m, out = 1, []
    while True:
        d0 = "%s-%02d-01" % (year, m)
        if d0 > asof:
            return out
        d1 = "%s-%02d-01" % (year, m + 1) if m < 12 else "%d-01-01" % (int(year) + 1)
        out.append((d0, d1))
        if m == 12:
            return out
        m += 1


def fetch(base, key, year, asof):
    runs, races, pays = [], [], []
    for d0, d1 in months(year, asof):
        w = "&race_date=gte.%s&race_date=lt.%s&race_date=lte.%s" % (d0, d1, asof)
        runs += fetch_all(base, key, "nar_runs?select=race_date,track,race_no,runner_number,horse_name,birth_date,age,finish,jockey,time_sec"
                          "&finish=not.is.null" + w + "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")
        races += fetch_all(base, key, "nar_races?select=race_date,track,race_no,race_name,race_kind,distance_m,going"
                           + w + "&order=race_date.asc,track.asc,race_no.asc")
        pays += fetch_all(base, key, "nar_race_payouts?select=race_date,track,race_no,payouts"
                          + w + "&order=race_date.asc,track.asc,race_no.asc")
        print("%s runs=%d races=%d pays=%d" % (d0[:7], len(runs), len(races), len(pays)), flush=True)
    return runs, races, pays


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def tsec(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def top_with_ties(counter, label):
    """Counter(鍵→数) → 上位 TOPN(同数は全部・上限 TIE_CAP)。鍵の並びは数の多い順・同数は名前順。"""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], label(kv[0])))
    if not ranked:
        return [], False
    cut = ranked[min(TOPN, len(ranked)) - 1][1]
    keep = [kv for kv in ranked if kv[1] >= cut]
    return keep[:TIE_CAP], len(keep) > TIE_CAP


def build(runs, races, pays, asof, now):
    """副作用なし。"""
    year = asof[:4]
    unknown = sorted({r["track"] for r in runs} - set(SLUG))
    if unknown:
        sys.exit("知らない場: %s" % unknown)
    rinfo = {(r["race_date"], r["track"], int(r["race_no"])): r for r in races}
    fin = [r for r in runs if (num(r.get("finish")) or 0) >= 1]
    # 頭の数字
    vdays, vraces, vstarts = defaultdict(set), defaultdict(set), Counter()
    for r in fin:
        s = SLUG[r["track"]]
        vdays[s].add(r["race_date"])
        vraces[s].add((r["race_date"], int(r["race_no"])))
        vstarts[s] += 1
    alldays = set().union(*vdays.values()) if vdays else set()
    by_venue = {s: {"days": len(vdays[s]), "races": len(vraces[s]), "starters": vstarts[s]} for _t, s, _n in TRACKS if s in vdays}
    totals = {"days": len(alldays), "venue_days": sum(v["days"] for v in by_venue.values()),
              "races": sum(v["races"] for v in by_venue.values()), "starters": sum(vstarts.values())}
    held = {(r["race_date"], SLUG[r["track"]]) for r in fin}
    heldrace = {(r["race_date"], r["track"], int(r["race_no"])) for r in fin}

    # 暦と最高払戻
    cal = defaultdict(dict)
    allpay = []
    for p in pays:
        k = (p["race_date"], p["track"], int(p["race_no"]))
        if p["track"] not in SLUG or k not in heldrace:
            continue
        s = SLUG[p["track"]]
        nm = (rinfo.get(k) or {}).get("race_name") or ""
        for x in p.get("payouts") or []:
            if x.get("t") not in KINDS or num(x.get("y")) is None:
                continue
            y = num(x["y"])
            e = [y, k[2], x["t"], str(x.get("c") or ""), num(x.get("p"))]
            allpay.append((-y, k[0], k[2], KINDS.index(x["t"]), s, e, nm))
            cur = cal[s].get(k[0])
            if cur is None or y > cur[0] or (y == cur[0] and k[2] < cur[1]):
                cal[s][k[0]] = e
    for d, s in held:
        cal[s].setdefault(d, None)   # 開催はあったが払戻の行が無い日= null
    allpay.sort(key=lambda a: a[:5])
    top_pay = [{"date": a[1], "venue": a[4], "r": a[2], "t": a[5][2], "c": a[5][3], "y": a[5][0], "p": a[5][4], "race_name": a[6]}
               for a in allpay[:TOPN]]

    wins = [r for r in fin if num(r.get("finish")) == 1]
    # 最多勝の馬
    hw, hv = Counter(), defaultdict(Counter)
    for r in wins:
        h = ((r.get("horse_name") or "").strip(), str(r.get("birth_date") or "")[:10])
        if not h[0]:
            continue
        hw[h] += 1
        hv[h][SLUG[r["track"]]] += 1
    hl, hcut = top_with_ties(hw, lambda h: h[0])
    horses = [{"name": h[0], "birth": h[1] or None, "w": n, "by": dict(hv[h].most_common())} for h, n in hl]
    # 最多勝の騎手
    jw, jv = Counter(), defaultdict(Counter)
    for r in wins:
        j = (r.get("jockey") or "").strip()
        if not j:
            continue
        jw[j] += 1
        jv[j][SLUG[r["track"]]] += 1
    jl, jcut = top_with_ties(jw, lambda j: j)
    jockeys = [{"name": j, "w": n, "by": dict(jv[j].most_common())} for j, n in jl]
    # 最年長の勝ち馬
    def age_of(r):
        a = num(r.get("age"))
        if a:
            return a
        b = str(r.get("birth_date") or "")
        return int(r["race_date"][:4]) - int(b[:4]) if b[:4].isdigit() else None
    aged = [(age_of(r), r) for r in wins]
    aged = [x for x in aged if x[0]]
    amax = max((a for a, _r in aged), default=None)
    oldest = {"age": amax, "list": sorted([{"name": r.get("horse_name"), "date": r["race_date"], "venue": SLUG[r["track"]],
                                            "r": int(r["race_no"])} for a, r in aged if a == amax],
                                          key=lambda o: (o["date"], o["venue"], o["r"]))}
    # 場×距離の最速(1 着の時計)
    best, cnt = {}, Counter()
    for r in wins:
        k = (r["race_date"], r["track"], int(r["race_no"]))
        ri = rinfo.get(k) or {}
        dist = num(ri.get("distance_m"))
        t = tsec(r.get("time_sec"))
        if not dist:
            continue
        s = SLUG[r["track"]]
        if (s, dist, k) in cnt:
            continue
        cnt[(s, dist, k)] = 1
        if t is None:
            continue
        o = (t, k[0], k[2])
        cur = best.get((s, dist))
        if cur is None or o < cur[0]:
            best[(s, dist)] = (o, {"dist": dist, "time": t, "name": r.get("horse_name"), "date": k[0], "r": k[2],
                                   "going": ri.get("going") or None, "cls": ri.get("race_name") or None, "kind": ri.get("race_kind") or None})
    nrace = Counter()
    for (s, dist, _k) in cnt:
        nrace[(s, dist)] += 1
    fastest = {}
    for _t, s, _n in TRACKS:
        lst = [dict(best[(s2, d)][1], n=nrace[(s2, d)]) for (s2, d) in best if s2 == s]
        if lst:
            fastest[s] = sorted(lst, key=lambda o: (-o["n"], o["dist"]))
    return {
        "v": 1, "year": int(year), "asof": asof, "made": now.strftime("%Y-%m-%dT%H:%M+09:00"),
        "venues": [{"slug": s, "name": n} for _t, s, n in TRACKS],
        "totals": totals, "by_venue": by_venue,
        "cal": {s: dict(sorted(v.items())) for s, v in cal.items()},
        "top_pay": top_pay,
        "horses": horses, "horses_cut": hcut,
        "jockeys": jockeys, "jockeys_cut": jcut,
        "oldest": oldest, "fastest": fastest,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--asof")
    a = ap.parse_args(argv)
    if a.dry_run and not a.out:
        ap.error("--dry-run には --out が要る")
    base, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    asof = a.asof or (now.date() - dt.timedelta(days=1)).isoformat()
    year = asof[:4]
    runs, races, pays = fetch(base, key, year, asof)
    if not any((num(r.get("finish")) or 0) == 1 for r in runs):
        print("asof=%s 今年の 1 着が 0 件= 上げない" % asof)
        return 0
    out = build(runs, races, pays, asof, now)
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    name = "year-review-%s.json" % year
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "wb") as f:
            f.write(data)
    print("asof=%s totals=%s bytes=%d" % (asof, out["totals"], len(data)))
    print("horses", [(h["name"], h["w"]) for h in out["horses"]], "cut", out["horses_cut"])
    print("jockeys", [(j["name"], j["w"]) for j in out["jockeys"]])
    print("top_pay", [(p["date"], p["venue"], p["r"], p["t"], p["y"]) for p in out["top_pay"]])
    print("oldest", out["oldest"])
    if a.apply:
        from cond_stats import Rest, ensure_bucket, upload
        rest = Rest(base, key)
        ensure_bucket(rest)
        upload(rest, name, data)
        print("上げた cond-stats/v1/%s" % name)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                            # noqa: BLE001
            pass
    sys.exit(main())

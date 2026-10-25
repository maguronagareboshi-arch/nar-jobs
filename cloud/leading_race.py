#!/usr/bin/env python3
# リーディング争い(2026-10-26)。画面 nar-viewer /leading/race の材料を毎朝作り直し、公開バケット cond-stats の
#   v1/leading-race.json へ上げる(便 .github/workflows/leading-race.yml・JST 05:50)。
#   今年の 1 着を日ごとに数え、全国と地区ごとの上位 10 人の「日ごとの勝ち数」を JSON 1 本にする。
#   出所= nar_runs の finish=1(同着も 1 着)。全国リーディング(nar_person_stats の track=all)と同じ数え方。
#   地区= その地区の競馬場のレースでの勝ち数(他地区からの遠征の勝ちも入る)。中央のレースは nar_runs に無い。
#   残り開催日= nar_meta kaisai_schedule(主催者の月別開催日程)で asof の翌日〜12/31 にその地区の場がある日の数。
#   今年の 1 着が 0 件なら上げずに終わる(前の版を残す・終了コード 0)。
# ⛔本番 DB では REST の単純 select だけ。書くのは Storage の cond-stats/v1/leading-race.json だけ(と便の heartbeat)。
#   python3 cloud/leading_race.py --apply                 # 本番(上げる)
#   python3 cloud/leading_race.py --dry-run --out FILE    # 上げずに FILE へ書く
# 環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GROUPS = [  # (鍵, 見出し, nar_runs.track の値)。北から
    ("banei", "ばんえい", ["帯広ば"]),
    ("monbetsu", "門別", ["門別"]),
    ("iwate", "岩手", ["盛岡", "水沢"]),
    ("minamikanto", "南関東", ["浦和", "船橋", "大井", "川崎"]),
    ("kanazawa", "金沢", ["金沢"]),
    ("kasamatsu", "笠松", ["笠松"]),
    ("nagoya", "名古屋", ["名古屋"]),
    ("hyogo", "兵庫", ["園田", "姫路"]),
    ("kochi", "高知", ["高知"]),
    ("saga", "佐賀", ["佐賀"]),
]
SLUG = {"帯広ば": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa", "船橋": "funabashi",
        "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa", "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda",
        "姫路": "himeji", "高知": "kochi", "佐賀": "saga"}
# 主な場の地区名= 今年いちばん勝った場(画面 js/data.js VENUE_AREA の値= 勝負服の引き当てに使う)
AREA = {"帯広ば": "ばんえい", "門別": "北海道", "盛岡": "岩手", "水沢": "岩手", "浦和": "浦和", "船橋": "船橋", "大井": "大井",
        "川崎": "川崎", "金沢": "金沢", "笠松": "笠松", "名古屋": "愛知", "園田": "兵庫", "姫路": "兵庫", "高知": "高知", "佐賀": "佐賀"}
TOP = 10
NAME = "leading-race.json"
B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def req(base, key, path, headers=None):
    h = {"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"}
    h.update(headers or {})
    r = urllib.request.Request(base.rstrip("/") + "/rest/v1/" + path, headers=h)
    with urllib.request.urlopen(r, timeout=180) as x:
        return x.read().decode("utf-8")


def fetch_all(base, key, path, page=1000):
    """Range で 1000 行ずつ。⛔order は呼び出し側が一意にする(#postgrest-offset)。"""
    out, lo = [], 0
    while True:
        body = req(base, key, path, {"Range-Unit": "items", "Range": "%d-%d" % (lo, lo + page - 1)})
        rows = json.loads(body) if body else []
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def kaisai_days(base, key):
    rows = json.loads(req(base, key, "nar_meta?key=eq.kaisai_schedule&select=value") or "[]")
    return ((rows[0].get("value") or {}).get("days") or {}) if rows else {}


def remain_days(days, asof):
    """副作用なし。days= {日付: [[場の slug, ...], ...]}。"""
    end = asof[:4] + "-12-31"
    fut = {d: {v[0] for v in lst if v} for d, lst in days.items() if asof < d <= end}
    res = {"all": sum(1 for s in fut.values() if s)}
    for g, _label, tracks in GROUPS:
        slugs = {SLUG[t] for t in tracks}
        res[g] = sum(1 for s in fut.values() if s & slugs)
    return res, (max(days) if days else None)


def build(rows, kdays, asof, now):
    """副作用なし。rows= nar_runs の 1 着の行・kdays= kaisai_schedule の days・now= JST の datetime。"""
    year = asof[:4]
    unknown = sorted({r["track"] for r in rows} - set(SLUG))
    if unknown:
        sys.exit("知らない場: %s" % unknown)
    days = sorted({r["race_date"] for r in rows})
    di = {d: i for i, d in enumerate(days)}
    g_of = {t: g for g, _label, tracks in GROUPS for t in tracks}
    remain, sched_last = remain_days(kdays, asof)
    # 地区ごとの開催日= days と同じ長さの 0/1(1 着の行がある日= その地区で開催があった日)。再生中の「残り開催日」を数えるのに使う
    gdays = {g: ["0"] * len(days) for g, _label, _tracks in GROUPS}
    for r in rows:
        gdays[g_of[r["track"]]][di[r["race_date"]]] = "1"
    out = {
        "v": 1, "year": int(year), "asof": asof, "made": now.strftime("%Y-%m-%dT%H:%M+09:00"),
        "days": days, "remain": remain, "schedule_through": sched_last,
        "gdays": {g: "".join(v) for g, v in gdays.items()},
        "groups": [{"key": "all", "label": "全国", "venues": [SLUG[t] for _g, _l, ts in GROUPS for t in ts]}]
        + [{"key": g, "label": label, "venues": [SLUG[t] for t in tracks]} for g, label, tracks in GROUPS],
    }
    for kind in ("jockey", "trainer"):
        daily = defaultdict(lambda: defaultdict(Counter))  # 地区 → 名前 → Counter(日の番号)
        home = defaultdict(Counter)                        # 名前 → Counter(地区名)
        for r in rows:
            name = (r.get(kind) or "").strip()
            if not name:
                continue
            i = di[r["race_date"]]
            daily["all"][name][i] += 1
            daily[g_of[r["track"]]][name][i] += 1
            home[name][AREA[r["track"]]] += 1
        res = {}
        for g in ["all"] + [x[0] for x in GROUPS]:
            ranked = sorted(daily[g].items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:TOP]
            lst = []
            for name, c in ranked:
                if max(c.values()) > 35:
                    sys.exit("1 日 36 勝以上: %s %s" % (g, name))
                lst.append({"name": name, "area": home[name].most_common(1)[0][0], "w": sum(c.values()),
                            "d": "".join(B36[c.get(i, 0)] for i in range(len(days)))})
            res[g] = lst
        out[kind] = res
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="cond-stats/v1/leading-race.json へ上げる")
    g.add_argument("--dry-run", action="store_true", help="上げずに --out へ書く")
    ap.add_argument("--out", default="", help="--dry-run の書き先ファイル(--apply でも指定すれば書く)")
    ap.add_argument("--asof", help="この日まで数える(既定= JST の前日)")
    a = ap.parse_args(argv)
    if a.dry_run and not a.out:
        ap.error("--dry-run には --out が要る")
    base, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    asof = a.asof or (now.date() - dt.timedelta(days=1)).isoformat()
    year = asof[:4]
    rows = fetch_all(base, key, "nar_runs?select=race_date,track,race_no,runner_number,jockey,trainer"
                     "&finish=eq.1&race_date=gte.%s-01-01&race_date=lte.%s"
                     "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc" % (year, asof))
    if not rows:
        print("asof=%s 今年の 1 着が 0 件= 上げない(前の版を残す)" % asof)
        return 0
    out = build(rows, kaisai_days(base, key), asof, now)
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "wb") as f:
            f.write(data)
    remain = out["remain"]
    print("asof=%s days=%d wins=%d remain_all=%s schedule_through=%s bytes=%d" % (
        asof, len(out["days"]), len(rows), remain["all"], out["schedule_through"], len(data)))
    for g in ["all"] + [x[0] for x in GROUPS]:
        print(g, " ".join("%s=%d" % (p["name"], p["w"]) for p in out["jockey"][g][:3]), "残り", remain.get(g))
    if a.apply:
        from cond_stats import Rest, ensure_bucket, upload
        rest = Rest(base, key)
        ensure_bucket(rest)
        upload(rest, NAME, data)
        print("上げた cond-stats/v1/%s" % NAME)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                            # noqa: BLE001
            pass
    sys.exit(main())

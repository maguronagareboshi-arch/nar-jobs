#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""条件で集計 /stats(2026-10-15・ユーザー了承済み見本 v3)の明細ファイルを毎朝作り、専用の公開バケット cond-stats へ上げる
(share は PNG・1MB までで入らない= 10/15 ユーザー了承で新設・無ければ初回に作る)。

  py -3.12 -X utf8 cloud/cond_stats.py --dry-run --out out/ --venue kochi   # 上げずに手元へ書く(読み取りだけ)
  python3 cloud/cond_stats.py --apply                                       # 便(cond-stats.yml)。全 15 場→cond-stats→照合

約束の正本= nar-site research/site-boost-20261015/SPEC-condstats.md。形の元= proto/build_proto.py(列 d r u h dist g w n f p j t s b st)。
- 置き場: バケット cond-stats の v1/<prefix>_1y.json・<prefix>_3y.json・index.json(Cache-Control max-age=3600・上げたら取り直して sha256 照合)。
- 期間: 1y= 前日から 365 日・3y= 前日から 1095 日(どちらも前日まで= 当日は入れない)。日付は JST。
- 走数から外す: 出走取消・競走除外・1 着の無いレース(不成立)の全走。競走中止は入れる。
- ⛔本番 DB は REST の単純 select だけ(場ごと・一意の order でページ送り)。書くのは Storage の cond-stats だけ(無ければ公開・JSON だけ・5MB までで作る)。
- 全場を作り終えてから上げる= 1 場でも作れなければ何も上げずに exit 1(古い目次とファイルが残る)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(dry-run は SUPABASE_ANON_KEY でも可)。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BUCKET = "cond-stats"
ROOT = "v1/"
MIME = ["application/json"]
SIZE_LIMIT = 5 * 1024 * 1024
CACHE = "max-age=3600"
UA = "nar-jobs cond_stats (+https://yukochi.com/)"
JST = dt.timezone(dt.timedelta(hours=9))
BEAT_JOB = "cond_stats"
DAYS = {"1y": 365, "3y": 1095}
# サイトの URL 表記(viewer js/data.js VENUES の prefix・share_image.py の TRACK_PREFIX と同じ)→ nar_races の track
VENUES = [("obihiro", "帯広ば", "帯広"), ("monbetsu", "門別", "門別"), ("morioka", "盛岡", "盛岡"),
          ("mizusawa", "水沢", "水沢"), ("urawa", "浦和", "浦和"), ("funabashi", "船橋", "船橋"),
          ("ooi", "大井", "大井"), ("kawasaki", "川崎", "川崎"), ("kanazawa", "金沢", "金沢"),
          ("kasamatsu", "笠松", "笠松"), ("nagoya", "名古屋", "名古屋"), ("sonoda", "園田", "園田"),
          ("himeji", "姫路", "姫路"), ("kochi", "高知", "高知"), ("saga", "佐賀", "佐賀")]
COLS = ["d", "r", "u", "h", "dist", "g", "w", "n", "f", "p", "j", "t", "s", "b", "st"]
DROP_NOTES = ("出走取消", "競走除外")
LEGEND = {"d": "from からの日数", "f": ">0 着順 / -2-i = fn[i]", "st": "0逃げ 1先行 2差し 3追込 -1不明(horse.js LEG)",
          "辞書列": "h,g,j,t,s,b は番号(-1=空)"}


def log(msg):
    print(msg, flush=True)


# ---------- 期間・外す規則(試験はここを直接呼ぶ) ----------
def period(today, key):
    """today(JST の当日)→ (from, to)。to= 前日・from= 前日から DAYS 日(前日を 1 日目に数える)。"""
    to = today - dt.timedelta(days=1)
    return today - dt.timedelta(days=DAYS[key]), to


def keep_runs(runs):
    """出走取消・競走除外の走と、1 着の無いレースの全走を外す。競走中止は残す。並びは保つ。"""
    won = {(x["race_date"], x["race_no"]) for x in runs if x.get("finish") == 1}
    return [x for x in runs
            if (x["race_date"], x["race_no"]) in won and (x.get("finish_note") or "") not in DROP_NOTES]


# ---------- 脚質(proto/build_proto.py と同じ= pages/horse.js の LEG・data.js の通過の読み) ----------
def corner_ranks(order):
    s = str(order or "").strip()
    if not s:
        return None
    out, rank, i = {}, 1, 0
    while i < len(s):
        ch = s[i]
        if ch in ",-= 　":
            i += 1
            continue
        if ch == "(":
            end = s.find(")", i)
            if end < 0:
                return None
            try:
                nums = [int(x.strip()) for x in s[i + 1:end].split(",")]
            except ValueError:
                return None
            if not nums or any(n <= 0 for n in nums):
                return None
            for n in nums:
                out.setdefault(n, rank)
            rank += len(nums)
            i = end + 1
            continue
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == i:
            return None
        out.setdefault(int(s[i:j]), rank)
        rank += 1
        i = j
    return out or None


def last_corner_map(corners):
    per = [m for m in (corner_ranks(c.get("order") if isinstance(c, dict) else None) for c in (corners or [])) if m]
    out = {}
    for m in per:
        for u, p in m.items():
            out[u] = p
    return out


def leg(p):
    if p is None:
        return -1
    return 0 if p == 1 else 1 if p <= 3 else 2 if p <= 6 else 3


class Dic:
    def __init__(self):
        self.idx, self.names = {}, []

    def __call__(self, v):
        if v is None or v == "":
            return -1
        if v not in self.idx:
            self.idx[v] = len(self.names)
            self.names.append(v)
        return self.idx[v]


def build_doc(track, d_from, d_to, races, runs, ped):
    """試作 build() と同じ形の 1 ファイル。runs は keep_runs 済み・期間内だけを渡す。"""
    rmap = {(r["race_date"], r["race_no"]): r for r in races}
    lc = {k: last_corner_map(r.get("corners")) for k, r in rmap.items()}
    base = d_from
    dH, dJ, dT, dS, dB, dG, dN = Dic(), Dic(), Dic(), Dic(), Dic(), Dic(), Dic()
    cols = {k: [] for k in COLS}
    for x in runs:
        key = (x["race_date"], x["race_no"])
        rc = rmap.get(key)
        hp = ped.get(x["horse_name"])
        cols["d"].append((dt.date.fromisoformat(x["race_date"]) - base).days)
        cols["r"].append(x["race_no"])
        cols["u"].append(x["runner_number"])
        cols["h"].append(dH(x["horse_name"]))
        cols["dist"].append(rc["distance_m"] if rc else None)
        cols["g"].append(dG(rc["going"] if rc else None))
        cols["w"].append(x["gate"])
        cols["n"].append(rc["field_size"] if rc else None)
        f = x["finish"]
        cols["f"].append(f if isinstance(f, int) and f > 0 else -2 - dN(x.get("finish_note") or "不明"))
        cols["p"].append(x["popularity"])
        cols["j"].append(dJ(x["jockey"]))
        cols["t"].append(dT(x["trainer"]))
        cols["s"].append(dS(hp.get("sire") if hp else None))
        cols["b"].append(dB(hp.get("broodmare_sire") if hp else None))
        p = lc.get(key, {}).get(x["runner_number"]) if x["runner_number"] is not None else None
        cols["st"].append(leg(p))
    return {"v": 1, "track": track, "from": d_from.isoformat(), "to": d_to.isoformat(), "n": len(runs),
            "legend": LEGEND,
            "dict": {"h": dH.names, "g": dG.names, "j": dJ.names, "t": dT.names, "s": dS.names, "b": dB.names,
                     "fn": dN.names},
            "cols": cols}


def dumps(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ---------- REST ----------
class Rest:
    def __init__(self, base, key):
        self.base, self.key, self.nreq = base.rstrip("/"), key, 0

    def req(self, path, method="GET", body=None, headers=None, timeout=120):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA}
        if headers:
            h.update(headers)
        for i in range(3):
            self.nreq += 1
            try:
                r = urllib.request.Request(self.base + path, method=method, data=body, headers=h)
                with urllib.request.urlopen(r, timeout=timeout) as x:
                    return x.read()
            except urllib.error.HTTPError as e:
                if e.code < 500 or i == 2:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if i == 2:
                    raise
            time.sleep(3 * (i + 1))

    def get(self, q):
        return json.loads(self.req("/rest/v1/" + q, headers={"Accept": "application/json"}) or b"[]")

    def paged(self, q, order):
        # ⛔offset には一意の並び
        rows, off = [], 0
        while True:
            part = self.get(f"{q}&order={order}&limit=1000&offset={off}")
            rows += part
            if len(part) < 1000:
                return rows
            off += 1000


def enc(v):
    return urllib.parse.quote(str(v), safe="")


def fetch(rest, track, d_from, d_to):
    tq = enc(track)
    rng = f"&track=eq.{tq}&race_date=gte.{d_from.isoformat()}&race_date=lte.{d_to.isoformat()}"
    races = rest.paged("nar_races?select=race_date,race_no,distance_m,going,field_size,corners" + rng,
                       "race_date,race_no")
    runs = rest.paged("nar_runs?select=race_date,race_no,runner_number,gate,horse_name,finish,finish_note,popularity,"
                      "jockey,trainer" + rng, "race_date,race_no,runner_number")
    runs = [x for x in runs if d_from.isoformat() <= x["race_date"] <= d_to.isoformat()]
    names = sorted({x["horse_name"] for x in runs if x["horse_name"]})
    ped = {}
    for k in range(0, len(names), 80):
        inl = ",".join('"' + n.replace("\\", "\\\\").replace('"', '\\"') + '"' for n in names[k:k + 80])
        for h in rest.get("nar_horses?select=horse_name,sire,broodmare_sire&horse_name=in.(" + enc(inl) + ")"):
            ped[h["horse_name"]] = h
    return races, runs, ped


def build_venue(rest, track, today):
    """3y 分を 1 回だけ取り、1y はその中から切る。→ {key: (doc, raw, first_date)}"""
    f3, to = period(today, "3y")
    races, runs, ped = fetch(rest, track, f3, to)
    out = {}
    for key in ("1y", "3y"):
        fr, _ = period(today, key)
        part = keep_runs([x for x in runs if x["race_date"] >= fr.isoformat()])
        doc = build_doc(track, fr, to, races, part, ped)
        first = min((x["race_date"] for x in part), default=None)
        out[key] = (doc, dumps(doc), first)
    return out


# ---------- 上げる ----------
def ensure_bucket(rest):
    """公開バケット cond-stats が無ければ作る(odds_archive.py と同じ作法・JSON だけ・1 個 5MB まで)。"""
    try:
        rest.req("/storage/v1/bucket/%s" % BUCKET)
        return
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):
            raise
    body = json.dumps({"id": BUCKET, "name": BUCKET, "public": True,
                       "allowed_mime_types": MIME, "file_size_limit": SIZE_LIMIT}).encode("utf-8")
    rest.req("/storage/v1/bucket", "POST", body, {"Content-Type": "application/json"})
    log("バケット %s を作った(公開・JSON だけ・5MB まで)" % BUCKET)


def upload(rest, name, data):
    path = ROOT + name
    rest.req("/storage/v1/object/%s/%s" % (BUCKET, path), "POST", data,
             {"Content-Type": "application/json; charset=utf-8", "x-upsert": "true", "Cache-Control": CACHE})
    back = rest.req("/storage/v1/object/%s/%s" % (BUCKET, path))
    if hashlib.sha256(back).hexdigest() != hashlib.sha256(data).hexdigest():
        raise RuntimeError("取り直した中身が違う: %s/%s" % (BUCKET, path))
    log("上げた %s/%s(%d bytes・照合 OK)" % (BUCKET, path, len(data)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="cond-stats へ上げる")
    g.add_argument("--dry-run", action="store_true", help="上げずに --out へ書く")
    ap.add_argument("--out", default="cond_stats_out", help="--dry-run の出し先")
    ap.add_argument("--venue", default="", help="場の URL 名(カンマ区切り・空= 全 15 場。--apply は全場のみ)")
    ap.add_argument("--today", default="", help="JST の当日(YYYY-MM-DD・既定= 今日)。前日までを数える")
    a = ap.parse_args(argv)
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "") or (os.environ.get("SUPABASE_ANON_KEY", "") if a.dry_run else "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    want = [v.strip() for v in a.venue.split(",") if v.strip()]
    if a.apply and want:
        raise SystemExit("--apply は全場だけ(目次が欠けるため)")
    venues = [v for v in VENUES if not want or v[0] in want]
    if want and len(venues) != len(want):
        raise SystemExit("知らない場: %s" % sorted(set(want) - {v[0] for v in venues}))
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    rest = Rest(base, key)
    built, fails = {}, {}
    for prefix, track, name in venues:
        t0 = time.time()
        try:
            built[prefix] = build_venue(rest, track, today)
            log("%s 1y=%d 3y=%d(%.0f 秒)" % (prefix, built[prefix]["1y"][0]["n"], built[prefix]["3y"][0]["n"],
                                           time.time() - t0))
        except Exception as e:                       # noqa: BLE001
            fails[prefix] = "%s: %s" % (type(e).__name__, str(e)[:200])
            log("⚠%s が作れない: %s" % (prefix, fails[prefix]))
    if fails:
        log("作れない場 %d= 何も上げない: %s" % (len(fails), fails))
        return 1
    asof = (today - dt.timedelta(days=1)).isoformat()
    index = {"v": 1, "built_at": dt.datetime.now(JST).isoformat(timespec="seconds"), "asof": asof, "venues": []}
    files = []
    for prefix, track, name in venues:
        b = built[prefix]
        index["venues"].append({"prefix": prefix, "name": name, "n1y": b["1y"][0]["n"], "n3y": b["3y"][0]["n"],
                                "bytes1y": len(b["1y"][1]), "bytes3y": len(b["3y"][1]),
                                "from1y": b["1y"][2], "from3y": b["3y"][2]})
        files += [("%s_1y.json" % prefix, b["1y"][1]), ("%s_3y.json" % prefix, b["3y"][1])]
    files.append(("index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
    if a.dry_run:
        os.makedirs(a.out, exist_ok=True)
        for n, data in files:
            with open(os.path.join(a.out, n), "wb") as f:
                f.write(data)
        log("dry-run: %d ファイルを %s へ(REST %d 回)" % (len(files), a.out, rest.nreq))
        return 0
    ensure_bucket(rest)
    for n, data in files:                            # 目次は最後
        upload(rest, n, data)
    log("上げた %d ファイル(REST %d 回)" % (len(files), rest.nreq))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:                            # noqa: BLE001
            pass
    sys.exit(main())

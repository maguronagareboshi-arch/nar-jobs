"""§304 「今日ここまで」のふだんの値(2026-10-22)。

場ごとに、過去 1 年の開催日ごとに「今日ここまで」の札と**同じ計算**をして、
  pos  = 前(4角1〜3番手)の「人気−着順」平均 − 後ろ(4角7番手以下)の同じ平均
  gate = 内(1〜4枠)の同じ平均 − 外(5枠以上)の同じ平均(出走 8 頭以上で全頭に枠があるレースだけ)
の中央値と 10〜90%(中央 8 割)を nar_meta `day_trend_norm` に入れる。
  形= {場prefix: {pos:{med,lo,hi,n}, gate:{med,lo,hi,n}}}(n= 数えた日数・確定 3 レース以上の日だけ)

⛔計算は js/day-trend.js(computeDayTrend の posGap / gateGap)の写し。変えたら両方を直し、
  tests/test_day_trend_norm.py の照合(js で出した値を固定)を通すこと。
  ・取消・除外= 出走していない(数えない)。中止・失格ほか note のある馬= 着順なし(着外)。
  ・人気は出走馬の中で付け直す(同じ値は同じ順位= 1,2,2,4)。
  ・4角= 名前に「４角/4コーナー」がある点。**並びの最後の点が 4 角のときだけ**(でなければその日の位置取りに数えない)。
  ・通過順の読み方は pipeline/facts.py corner_ranks の 1 か所だけ。

使い方:
  python cloud/day_trend_norm.py            # ドライラン(書かない)
  python cloud/day_trend_norm.py --apply    # nar_meta へ upsert
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--env で .env を読む)
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from pipeline.facts import corner_ranks                  # noqa: E402

UA = "nar-jobs/1.0"
META_KEY = "day_trend_norm"
JST = dt.timezone(dt.timedelta(hours=9))
# ⛔cloud/baba_trend.py と同じ表(帯広ばは 4 角が無い= 入れない)
TRACK2PREFIX = {"門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa",
                "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
                "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji",
                "高知": "kochi", "佐賀": "saga"}
DAYS = 365              # 前日までの 1 年
MIN_RACES = 3           # その日に数えたレースがこれ以上の日だけ(js の WORD_MIN_RACES)
MIN_DAYS = 20           # これ未満の日数しかない場はその項目を書かない(画面は目盛を出さない)
GATE_MIN_FIELD = 8      # js の GATE_MIN_FIELD
WINDOW_STEP = 30
N_REQ = [0]

CN = re.compile(r"([１２３４1234])(?:角|コーナー)")
DIG = {"１": 1, "２": 2, "３": 3, "４": 4, "1": 1, "2": 2, "3": 3, "4": 4}
NOTE_RE = re.compile(r"(取消|除外|中止|失格)")
NONSTART_RE = re.compile(r"(取消|除外)")


def log(msg):
    print(msg, flush=True)


def load_env(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def num(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def sstr(v):
    """js の str(): 空白だけ・空は None"""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ---------------------------------------------------------------- js/day-trend.js の写し

def note_of(run):
    """js/data.js narNote の写し= (note)"""
    n = sstr(run.get("finish_note"))
    if n:
        return n
    m = sstr(run.get("margin"))
    if m and NOTE_RE.search(m):
        return m
    return None


def c4_of(corners):
    """js cornerPoints の 4 角だけ。cornerList(order の空を落とす)→ 名前の数字で引く → 最後の点が 4 角のときだけ"""
    lst = [c for c in (corners or []) if isinstance(c, dict) and sstr(c.get("order"))]
    pts = {}
    for c in lst:
        m = CN.search(str(c.get("name") or ""))
        if not m:
            continue
        pts[DIG[m.group(1)]] = corner_ranks(c.get("order"))
    if not lst:
        return None
    lm = CN.search(str(lst[-1].get("name") or ""))
    if not (lm and DIG[lm.group(1)] == 4):
        return None
    return pts.get(4) or None


def race_runners(runs):
    """1 レースの nar_runs 行 → 出走馬 [{finish, pop, gate, no}](人気は付け直し済み)"""
    rs = []
    for x in runs:
        note = note_of(x)
        f = num(x.get("finish"))
        f = None if (f is None or f <= 0) else f        # narFinish
        if note is not None:
            f = None
        f = f if (f is not None and f >= 1 and not note) else None
        p = num(x.get("popularity"))
        g = num(x.get("gate"))
        rs.append({"no": int(x["runner_number"]), "note": note, "finish": f,
                   "pop": p if (p is not None and p >= 1) else None,
                   "gate": g if (g is not None and g >= 1) else None})
    st = [x for x in rs if not NONSTART_RE.search(x["note"] or "")]
    pops = sorted(x["pop"] for x in st if x["pop"] is not None)
    for x in st:
        if x["pop"] is not None:
            x["pop"] = 1 + sum(1 for u in pops if u < x["pop"])
    return st


def has_fin(runs):
    """js hasFin: 着順 1 以上で note の無い馬が 1 頭でもいる(⛔取得時の note= narNote)"""
    for x in runs:
        note = note_of(x)
        f = num(x.get("finish"))
        if note is None and f is not None and f >= 1:
            return True
    return False


def gap_of(races, pred):
    n, s = 0, 0.0
    for rn in races:
        for x in rn:
            if x["finish"] is None or x["pop"] is None or not pred(x):
                continue
            n += 1
            s += x["pop"] - x["finish"]
    return s / n if n else None


def day_values(day_races):
    """1 場 1 日 [(corners, runs)] → {"pos": 値|None, "gate": 値|None, "pos_races", "gate_races"}"""
    ev = []
    for corners, runs in day_races:
        if not has_fin(runs):
            continue
        st = race_runners(runs)
        c4 = c4_of(corners)
        for x in st:
            x["c4"] = c4.get(x["no"]) if c4 else None
        ev.append((c4 is not None, st))
    evc = [st for ok, st in ev if ok]
    gev = [st for ok, st in ev if len(st) >= GATE_MIN_FIELD and all(x["gate"] is not None for x in st)]
    out = {"pos": None, "gate": None, "pos_races": len(evc), "gate_races": len(gev)}
    if len(evc) >= MIN_RACES:
        f = gap_of(evc, lambda x: x["c4"] is not None and x["c4"] <= 3)
        b = gap_of(evc, lambda x: x["c4"] is not None and x["c4"] >= 7)
        if f is not None and b is not None:
            out["pos"] = f - b
    if len(gev) >= MIN_RACES:
        i = gap_of(gev, lambda x: x["gate"] <= 4)
        o = gap_of(gev, lambda x: x["gate"] > 4)
        if i is not None and o is not None:
            out["gate"] = i - o
    return out


def quant(xs, q):
    """直線補間の分位(numpy の既定と同じ)"""
    s = sorted(xs)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(vals):
    if len(vals) < MIN_DAYS:
        return None
    return {"med": round(quant(vals, 0.5), 2), "lo": round(quant(vals, 0.1), 2),
            "hi": round(quant(vals, 0.9), 2), "n": len(vals)}


# ---------------------------------------------------------------- 通信

def req(base, key, path, method="GET", body=None, tries=2):
    last = None
    for i in range(tries):
        N_REQ[0] += 1
        r = urllib.request.Request(base + path, method=method, data=body, headers={
            "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return x.status, x.read().decode("utf-8")
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


def rows_all(base, key, path):
    """⛔offset で送るので order= は一意"""
    out, off = [], 0
    while True:
        _, body = req(base, key, f"{path}&limit=1000&offset={off}")
        c = json.loads(body)
        out.extend(c)
        if len(c) < 1000:
            return out
        off += 1000


def rows_window(base, key, tmpl, lo, hi):
    out = []
    a = dt.date.fromisoformat(lo)
    end = dt.date.fromisoformat(hi)
    while a <= end:
        b = min(a + dt.timedelta(days=WINDOW_STEP - 1), end)
        out.extend(rows_all(base, key, tmpl.format(lo=a.isoformat(), hi=b.isoformat())))
        a = b + dt.timedelta(days=1)
    return out


def fetch(base, key, lo, hi):
    races = rows_window(base, key,
                        "/rest/v1/nar_races?select=track,race_date,race_no,corners"
                        "&race_date=gte.{lo}&race_date=lte.{hi}"
                        "&order=race_date.asc,track.asc,race_no.asc", lo, hi)
    runs = rows_window(base, key,
                       "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,gate,finish,"
                       "finish_note,margin,popularity"
                       "&race_date=gte.{lo}&race_date=lte.{hi}"
                       "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc", lo, hi)
    return ([r for r in races if r["track"] in TRACK2PREFIX],
            [r for r in runs if r["track"] in TRACK2PREFIX])


def build(races, runs):
    """→ ({prefix: {pos, gate}}, {prefix: {date: day_values}})"""
    rby = {}
    for x in runs:
        rby.setdefault((x["track"], x["race_date"], int(x["race_no"])), []).append(x)
    days = {}
    for r in races:
        k = (r["track"], r["race_date"], int(r["race_no"]))
        days.setdefault((r["track"], r["race_date"]), []).append((r.get("corners"), rby.get(k, [])))
    per = {}
    for (track, date), lst in days.items():
        per.setdefault(TRACK2PREFIX[track], {})[date] = day_values(lst)
    out = {}
    for p, dd in sorted(per.items()):
        cell = {}
        for part in ("pos", "gate"):
            s = summarize([v[part] for v in dd.values() if v[part] is not None])
            if s:
                cell[part] = s
        if cell:
            out[p] = cell
    return out, per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--env")
    ap.add_argument("--show", default="urawa", help="ログに直近の日の値を出す場")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    today = dt.datetime.now(JST).date()
    lo = (today - dt.timedelta(days=DAYS)).isoformat()
    hi = (today - dt.timedelta(days=1)).isoformat()
    t0 = time.time()
    races, runs = fetch(base, key, lo, hi)
    value, per = build(races, runs)
    log("■ %s〜%s  レース %d / 走 %d → %d場  (%.0f秒 / 要求 %d 回)"
        % (lo, hi, len(races), len(runs), len(value), time.time() - t0, N_REQ[0]))
    for p, c in value.items():
        log("  %-10s 位置取り %s / 枠 %s" % (p, json.dumps(c.get("pos")), json.dumps(c.get("gate"))))
    sd = per.get(a.show) or {}
    for d in sorted(sd)[-3:]:
        log("  例 %s %s: %s" % (a.show, d, json.dumps(sd[d])))
    if not a.apply:
        log("   ドライラン(--apply なし)")
        return 0
    body = json.dumps([{"key": META_KEY, "value": value,
                       "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}], ensure_ascii=False).encode("utf-8")
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST", body)
    log("   nar_meta/%s 更新 %s(%d場)" % (META_KEY, st, len(value)))
    return 0 if st in (200, 201, 204) else 1


if __name__ == "__main__":
    sys.exit(main())

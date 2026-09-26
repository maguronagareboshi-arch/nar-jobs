# -*- coding: utf-8 -*-
"""締め切り直前の票(最後の票)の月次集計。便 .github/workflows/late-money.yml から毎月 1 日 JST 06:40 に走る。

  python3 cloud/late_money.py                      … JST の前月を集計して docs/late-money/YYYY-MM.json/.md と README.md を書く
  python3 cloud/late_money.py --month 2026-08      … 指定月
  python3 cloud/late_money.py --from 2026-08-01 --to 2026-08-03   … 検証用(ファイルは書かず標準出力)
  python3 cloud/late_money.py --dry-run            … ファイルを書かず標準出力

⛔本番 DB では REST の単純 select だけ(日付ごと・id 昇順の続き取り limit 1000)。集計 SQL・rpc は流さない。重い計算は全部ここ。
⛔標準ライブラリだけ。環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。

定義(本体の検証済み SQL と同じ):
  分= 時*60+分。確定の分 fm= 単勝の確定行(f=true の最大 id)の t。post_time と |fm-post|<=10 のレースだけ。
  単勝の最後の途中= f=false で w が確定の w と違う最後の行(id 最大)。その asof(無ければ t)の分 am・gap=fm-am<=4 のレースだけ。
  pf/pl= 確定/最後の途中 の 1/倍率 をレース内で合計 1 に正規化(両方に数値 >0 の倍率がある馬だけ)。
  rk= 最後の途中の倍率の順位(同値は同順位)。ws= pf/pl>=1.3。
  馬単・3連単の 1着の売れ方= 1着がその馬の組の 1/倍率 の和をレース内で正規化。確定= f=true の最大 id、
    途中= 確定より前(id が小さい)・observed_at が確定の 15 分以内・h が確定と違う最後の行。us= 確定/途中>=1.3。
    途中行が無いレースはその券種の表から外す。どちらかの売れ方が 0 の馬はその券種の表から外す。
  見込み= pf の和、実際= 1 着の数(finish が数字の馬だけ)。
"""
import argparse
import datetime as dt
import glob
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
UA = "nar-jobs late_money"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "docs", "late-money")
PAGE = 1000
COMBO_CHUNK = 20

A_BANDS = [("1.3 以上", 1.3, None), ("1.1〜1.3", 1.1, 1.3), ("0.91〜1.1", 0.91, 1.1), ("0.91 未満", None, 0.91)]
KINDS = ("umatan", "sanrentan")
KIND_JA = {"umatan": "馬単", "sanrentan": "3連単"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 取得
def req(base, key, path, tries=2):
    """⛔Supabase は一時的に 500 を返す。1 回だけ待って引き直す。"""
    last = None
    for i in range(tries):
        r = urllib.request.Request(base + path, headers={
            "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return json.loads(x.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 or i == tries - 1:
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


def rows_by_id(base, key, path):
    """id 昇順の続き取り(id=gt.最後の id・limit 1000)。path に select と絞り込みを入れる(order・limit は入れない)。"""
    out, last = [], None
    while True:
        p = path + "&order=id.asc&limit=%d" % PAGE + ("" if last is None else "&id=gt.%d" % last)
        c = req(base, key, p)
        out.extend(c)
        if len(c) < PAGE:
            return out
        last = c[-1]["id"]


def rows_offset(base, key, path):
    """⛔offset で送るので path の order= は一意にすること。"""
    out, off = [], 0
    while True:
        c = req(base, key, "%s&limit=%d&offset=%d" % (path, PAGE, off))
        out.extend(c)
        if len(c) < PAGE:
            return out
        off += PAGE


def fetch_day(base, key, day):
    """1 日ぶんの生データ → dict(races, runs, win, full, combos)。"""
    d = urllib.parse.quote(day)
    races = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,post_time"
                        "&race_date=eq.%s&order=track.asc,race_no.asc" % d)
    runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,finish"
                       "&race_date=eq.%s&order=track.asc,race_no.asc,runner_number.asc" % d)
    win = rows_by_id(base, key, "/rest/v1/nar_odds_ticks?select=id,track,race_date,race_no,t,asof,f,w"
                     "&race_date=eq.%s" % d)
    full = rows_by_id(base, key, "/rest/v1/nar_odds_full_ticks?select=id,track,race_date,race_no,kind,observed_at,f,h"
                      "&race_date=eq.%s&kind=in.(umatan,sanrentan)" % d)
    need = set()
    for pair in pick_full(full).values():
        need.update(pair)
    combos = {}
    ids = sorted(need)
    for i in range(0, len(ids), COMBO_CHUNK):
        part = ids[i:i + COMBO_CHUNK]
        for r in req(base, key, "/rest/v1/nar_odds_full_ticks?select=id,combos&id=in.(%s)"
                     % ",".join(str(x) for x in part)):
            combos[r["id"]] = r["combos"]
    return {"races": races, "runs": runs, "win": win, "full": full, "combos": combos}


# ---------------------------------------------------------------- 部品
def hm(s):
    """'HH:MM' / 'HHMM' → 分。読めなければ None。"""
    if s is None:
        return None
    s = str(s).strip()
    try:
        if ":" in s:
            h, m = s.split(":")[:2]
        elif len(s) in (3, 4) and s.isdigit():
            h, m = s[:-2], s[-2:]
        else:
            return None
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def rkey(r):
    return (r["track"], r["race_date"], int(r["race_no"]))


def pick_full(full):
    """(レース, kind) → (確定 id, 途中 id)。途中が無いものは入れない。"""
    by = {}
    for r in full:
        by.setdefault(rkey(r) + (r["kind"],), []).append(r)
    out = {}
    for k, rows in by.items():
        fins = [r for r in rows if r.get("f")]
        if not fins:
            continue
        fin = max(fins, key=lambda r: r["id"])
        ft = ts(fin["observed_at"])
        if ft is None:
            continue
        lo = ft - dt.timedelta(minutes=15)
        cand = [r for r in rows if r["id"] < fin["id"] and not r.get("f") and r.get("h") != fin.get("h")
                and ts(r["observed_at"]) is not None and lo <= ts(r["observed_at"]) <= ft]
        if cand:
            out[k] = (fin["id"], max(cand, key=lambda r: r["id"])["id"])
    return out


def first_share(combos):
    """combos → {1着の馬番: 正規化した売れ方}。"""
    s = {}
    for c in combos or []:
        if not isinstance(c, (list, tuple)) or len(c) < 3:
            continue
        o = num(c[-2])
        if o is None:
            continue
        h = str(c[0])
        s[h] = s.get(h, 0.0) + 1.0 / o
    tot = sum(s.values())
    return {h: v / tot for h, v in s.items()} if tot > 0 else {}


def cell():
    return {"n": 0, "win": 0, "exp": 0.0, "n7": 0, "win7": 0, "exp7": 0.0, "races": 0}


def empty_stats():
    return {"A": {b[0]: cell() for b in A_BANDS},
            "B": {"%s|%s" % (a, b): cell() for a in ("T", "F") for b in ("T", "F")},
            "C": {"%s|%s" % (a, b): cell() for a in ("T", "F") for b in ("T", "F")},
            "D": {}, "races": 0, "days": []}


def band(ratio):
    for name, lo, hi in A_BANDS:
        if (lo is None or ratio >= lo) and (hi is None or ratio < hi):
            return name
    return A_BANDS[-1][0]


def add(c, h, seen, rid):
    c["n"] += 1
    c["win"] += h["won"]
    c["exp"] += h["pf"]
    if h["rk"] >= 7:
        c["n7"] += 1
        c["win7"] += h["won"]
        c["exp7"] += h["pf"]
    if (id(c), rid) not in seen:
        seen.add((id(c), rid))
        c["races"] += 1


# ---------------------------------------------------------------- 集計
def aggregate(day_data, st=None):
    """1 日ぶん(fetch_day の形)を st に足す。st を返す。"""
    st = st or empty_stats()
    post = {rkey(r): hm(r.get("post_time")) for r in day_data["races"]}
    fin_of = {}
    for r in day_data["runs"]:
        f = r.get("finish")
        try:
            fn = int(str(f).strip())
        except (TypeError, ValueError):
            continue
        fin_of.setdefault(rkey(r), {})[str(r["runner_number"])] = fn
    wins = {}
    for r in day_data["win"]:
        wins.setdefault(rkey(r), []).append(r)
    fullpick = pick_full(day_data["full"])
    combos = day_data["combos"]
    seen = set()
    for rk_, rows in sorted(wins.items()):
        fins = [r for r in rows if r.get("f")]
        if not fins or rk_ not in fin_of:
            continue
        fin = max(fins, key=lambda r: r["id"])
        fm, pm = hm(fin.get("t")), post.get(rk_)
        if fm is None or pm is None or abs(fm - pm) > 10:
            continue
        fw = fin.get("w") or {}
        mids = [r for r in rows if not r.get("f") and (r.get("w") or {}) != fw]
        if not mids:
            continue
        mid = max(mids, key=lambda r: r["id"])
        am = hm(mid.get("asof")) if mid.get("asof") else hm(mid.get("t"))
        if am is None:
            continue
        gap = fm - am
        if gap > 4:
            continue
        lw = mid.get("w") or {}
        hs = [h for h in fw if num(fw[h]) is not None and num(lw.get(h)) is not None]
        if not hs:
            continue
        sf = sum(1.0 / num(fw[h]) for h in hs)
        sl = sum(1.0 / num(lw[h]) for h in hs)
        lodds = {h: num(lw[h]) for h in hs}
        horses = {}
        for h in hs:
            pf, pl = (1.0 / num(fw[h])) / sf, (1.0 / num(lw[h])) / sl
            rank = 1 + sum(1 for x in hs if lodds[x] < lodds[h])
            horses[h] = {"pf": pf, "pl": pl, "rk": rank}
        # 入れ替わり量(D)は finish に関係なくレースの全馬で
        if gap <= 2:
            d = st["D"].setdefault(rk_[0], {"sum": 0.0, "races": 0})
            d["sum"] += sum(abs(v["pf"] - v["pl"]) for v in horses.values()) / 2
            d["races"] += 1
        fo = fin_of[rk_]
        use = {}
        for h, v in horses.items():
            if h in fo:
                v["won"] = 1 if fo[h] == 1 else 0
                use[h] = v
        if not use:
            continue
        st["races"] += 1
        rid = "%s|%s|%d" % rk_
        for h, v in use.items():
            ratio = v["pf"] / v["pl"]
            v["ws"] = ratio >= 1.3
            add(st["A"][band(ratio)], v, seen, rid)
        for kind, tab in (("umatan", "B"), ("sanrentan", "C")):
            pk = fullpick.get(rk_ + (kind,))
            if not pk or pk[0] not in combos or pk[1] not in combos:
                continue
            ef, el = first_share(combos[pk[0]]), first_share(combos[pk[1]])
            for h, v in use.items():
                a, b = ef.get(h, 0.0), el.get(h, 0.0)
                if a <= 0 or b <= 0:
                    continue
                us = a / b >= 1.3
                add(st[tab]["%s|%s" % ("T" if v["ws"] else "F", "T" if us else "F")], v, seen, rid)
    return st


def merge(a, b):
    """json の生の和どうしを足す。"""
    out = empty_stats()
    for s in (a, b):
        for t in ("A", "B", "C"):
            for k, c in s[t].items():
                o = out[t].setdefault(k, cell())
                for f in o:
                    o[f] += c.get(f, 0)
        for tr, d in s["D"].items():
            o = out["D"].setdefault(tr, {"sum": 0.0, "races": 0})
            o["sum"] += d["sum"]
            o["races"] += d["races"]
        out["races"] += s.get("races", 0)
        out["days"] = sorted(set(out["days"]) | set(s.get("days", [])))
    return out


# ---------------------------------------------------------------- 書き出し
def fmt_row(label, c):
    ratio = "%.2f" % (c["win"] / c["exp"]) if c["exp"] > 0 else "-"
    ratio7 = "%.2f" % (c["win7"] / c["exp7"]) if c["exp7"] > 0 else "-"
    return "| %s | %d | %d | %.1f | %s | %d | %d | %.1f | %s | %d |" % (
        label, c["n"], c["win"], c["exp"], ratio, c["n7"], c["win7"], c["exp7"], ratio7, c["races"])


HEAD = ("| 区分 | 頭数 | 実際の1着 | 見込み | 実際÷見込み | 7番人気以下 頭数 | 同 1着 | 同 見込み | 同 実際÷見込み | レース数 |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")


def render_tables(st):
    L = []
    L.append("## A. 単勝の最後の動き(締め切り時の見込み ÷ 直前の見込み)\n")
    L.append(HEAD)
    for name, _, _ in A_BANDS:
        L.append(fmt_row(name, st["A"][name]))
    for tab, kind in (("B", "umatan"), ("C", "sanrentan")):
        L.append("\n## %s. 単勝 × %s(1着の売れ方)で最後に売れたか\n" % (tab, KIND_JA[kind]))
        L.append(HEAD)
        for a in ("T", "F"):
            for b in ("T", "F"):
                lab = "単勝 %s × %s %s" % ("売れた" if a == "T" else "それ以外", KIND_JA[kind], "売れた" if b == "T" else "それ以外")
                L.append(fmt_row(lab, st[tab]["%s|%s" % (a, b)]))
    L.append("\n## D. 場ごとの最後の入れ替わり量(直前の票が締め切り 2 分以内のレース)\n")
    L.append("| 場 | 入れ替わり量の平均 | レース数 |\n|---|---:|---:|")
    for tr in sorted(st["D"]):
        d = st["D"][tr]
        L.append("| %s | %s | %d |" % (tr, "%.3f" % (d["sum"] / d["races"]) if d["races"] else "-", d["races"]))
    return "\n".join(L)


DEFS = """## 読み方
- 見込み= 締め切り時の単勝の票から出した勝つ確率の合計(1 頭ぶんは 1/倍率をレース内で合計 1 にした値)。実際÷見込みが 1 より大きい区分は、見込みより多く勝っている。
- 最後の動き= 締め切り時の見込み ÷ 締め切り直前(4 分以内)の見込み。1.3 以上を「最後に売れた」とする。
- 馬単・3連単の「売れ方」= その馬が 1 着の組の票の合計(レース内で合計 1)。締め切り時 ÷ 直前(15 分以内)が 1.3 以上を「売れた」とする。
- 7番人気以下= 直前の単勝の倍率の順位(同じ倍率は同じ順位)。
- 対象= 締め切りの時刻が発走時刻の前後 10 分以内で、直前の票が締め切りの 4 分以内にあるレース。着順が数字の馬だけ。
- 入れ替わり量= レースごとの |締め切り時の見込み − 直前の見込み| の合計 ÷ 2 の平均。
"""


def render_month(month, st):
    return "# 締め切り直前の票 %s\n\n対象 %d レース・%d 日\n\n%s\n\n%s\n[累計へ](README.md)\n" % (
        month, st["races"], len(st["days"]), render_tables(st), DEFS)


def render_readme(total, months):
    lo = min(months) if months else "-"
    hi = max(months) if months else "-"
    links = "\n".join("- [%s](%s.md)" % (m, m) for m in sorted(months, reverse=True))
    return ("# 締め切り直前の票(累計)\n\n"
            "対象期間 %s 〜 %s(%d か月・%d レース)。毎月 1 日に前月ぶんを足す(便 late-money)。累計は各月の json の和。\n\n"
            "> ⚠ 1 年分たまるまで結論にしない。個別の厩舎・騎手名は出さない。\n\n"
            "%s\n\n%s\n## 各月\n%s\n") % (lo, hi, len(months), total["races"], render_tables(total), DEFS, links)


# ---------------------------------------------------------------- 本体
def prev_month_jst():
    today = dt.datetime.now(JST).date()
    last = today.replace(day=1) - dt.timedelta(days=1)
    return last.strftime("%Y-%m")


def month_range(m):
    y, mo = int(m[:4]), int(m[5:7])
    a = dt.date(y, mo, 1)
    b = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1))
    return a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month")
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    if a.dfrom or a.dto:
        lo = dt.date.fromisoformat(a.dfrom or a.dto)
        hi = dt.date.fromisoformat(a.dto or a.dfrom)
        label, write = "%s_%s" % (lo, hi), False   # 検証用は書かない
    else:
        label = a.month or prev_month_jst()
        lo, hi = month_range(label)
        write = not a.dry_run
    st = empty_stats()
    d = lo
    while d <= hi:
        day = d.isoformat()
        data = fetch_day(base, key, day)
        before = st["races"]
        aggregate(data, st)
        if data["win"]:
            st["days"].append(day)
        log("%s 単勝 %d 行・券種 %d 行・組 %d 件 → %d レース" % (
            day, len(data["win"]), len(data["full"]), len(data["combos"]), st["races"] - before))
        d += dt.timedelta(days=1)
    st["month"] = label
    st["generated_at"] = dt.datetime.now(JST).isoformat(timespec="seconds")
    if not write:
        print(json.dumps(st, ensure_ascii=False, indent=1))
        print(render_month(label, st))
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(os.path.join(OUT_DIR, label + ".json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(OUT_DIR, label + ".md"), "w", encoding="utf-8") as f:
        f.write(render_month(label, st))
    write_readme()
    log("書いた: docs/late-money/%s.json/.md・README.md" % label)


def write_readme():
    total, months = empty_stats(), []
    for p in sorted(glob.glob(os.path.join(OUT_DIR, "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        with io.open(p, encoding="utf-8") as f:
            total = merge(total, json.load(f))
        months.append(os.path.basename(p)[:-5])
    with io.open(os.path.join(OUT_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write(render_readme(total, months))


if __name__ == "__main__":
    main()

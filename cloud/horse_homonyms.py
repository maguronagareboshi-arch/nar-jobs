# -*- coding: utf-8 -*-
"""監査 #21 案 乙: 同名表 nar_meta `horse_homonyms`(馬名の配列)を毎朝 軽く足す。

「同名」= 同じ馬名で 生年 が 2 つ以上。生年= 生年月日の年、無ければ 開催年 − 馬齢(日本の馬齢は 1/1 加算)。
nar_meta `horse_homonym_merge`(手で持つ束ね表・無ければ空)を反映する。形:
  {"<馬名>": [[2019, 2020], ...]}   内側の配列 1 つ= 同じ馬(馬齢の書き誤りで割れた生年を束ねる)

初回(全期間)は Actions 便 horse-homonyms.yml が pipeline/sql/horse_homonyms.sql を 1 本流して作る。
この台本は「直近の出走馬の (馬名, 生年) が nar_horse_profiles の既存の生年と違う」ものだけ足す(消さない)。

  py -3.12 -X utf8 cloud/horse_homonyms.py --env pipeline/.env.nar            # ドライラン(足す馬名を出すだけ)
  py -3.12 -X utf8 cloud/horse_homonyms.py --env pipeline/.env.nar --apply
終了コード: 0 正常(表がまだ無い= 警告して 0) / 1 書き込み失敗 / 2 読み取り失敗
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
UA = "nar-jobs-horse-homonyms/1.0"
META_KEY = "horse_homonyms"
MERGE_KEY = "horse_homonym_merge"
T_PROFILES = "nar_horse_profiles"
NAME_BATCH = 80


def log(msg):
    print(f"[{dt.datetime.now(JST):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 純な関数(tests が読む)

def birth_year(race_date=None, age=None, birth_date=None):
    """生年。生年月日があればその年、無ければ 開催年 − 馬齢。決められなければ None"""
    bd = str(birth_date or "").strip()
    if len(bd) >= 4 and bd[:4].isdigit():
        return int(bd[:4])
    rd = str(race_date or "").strip()
    try:
        a = int(age)
    except (TypeError, ValueError):
        return None
    if a <= 0 or len(rd) < 4 or not rd[:4].isdigit():
        return None
    return int(rd[:4]) - a


def merge_map(value):
    """束ね表 → {馬名: {生年: 代表の生年(群の最小)}}。形が違えば空(壊れない)"""
    out = {}
    if not isinstance(value, dict):
        return out
    for name, groups in value.items():
        if not isinstance(groups, list):
            continue
        m = {}
        for g in groups:
            if not isinstance(g, list):
                continue
            ys = []
            for y in g:
                try:
                    ys.append(int(y))
                except (TypeError, ValueError):
                    pass
            if ys:
                lo = min(ys)
                for y in ys:
                    m[y] = lo
        if m:
            out[str(name)] = m
    return out


def year_groups(name, years, merge):
    """その馬名の生年の集合を束ね表で畳んだ集合"""
    m = merge.get(name) or {}
    return {m.get(y, y) for y in years if y is not None}


def homonyms_from_pairs(pairs, merge=None):
    """[(馬名, 生年)] → 同名の馬名(並べた配列)。merge= merge_map の戻り"""
    merge = merge or {}
    by = {}
    for name, y in pairs:
        if name and y is not None:
            by.setdefault(name, set()).add(y)
    return sorted(n for n, ys in by.items() if len(year_groups(n, ys, merge)) >= 2)


def daily_additions(runs, profiles, current, merge=None):
    """直近の走 runs [{horse_name, birth_date, age, race_date}] と profiles [{horse_name, birth_date}] から、
    今の同名表 current に無く、生年が 2 つ以上になった馬名(並べた配列)"""
    merge = merge or {}
    have = set(current or ())
    years = {}
    for r in runs:
        n = r.get("horse_name")
        y = birth_year(r.get("race_date"), r.get("age"), r.get("birth_date"))
        if n and y is not None and n not in have:
            years.setdefault(n, set()).add(y)
    for p in profiles:
        n = p.get("horse_name")
        if n in years:
            y = birth_year(birth_date=p.get("birth_date"))
            if y is not None:
                years[n].add(y)
    return sorted(n for n, ys in years.items() if len(year_groups(n, ys, merge)) >= 2)


def is_404(e):
    return getattr(e, "code", None) == 404 or getattr(getattr(e, "response", None), "status_code", None) == 404


# ---------------------------------------------------------------- REST

def rest(url, key, path, method="GET", body=None, prefer=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json"
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=body, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
        return r.status, (json.loads(raw) if raw.strip() else None)


def rest_all(url, key, path, page=1000):
    out, off = [], 0
    while True:
        _, rows = rest(url, key, f"{path}&limit={page}&offset={off}")
        out.extend(rows or [])
        if len(rows or []) < page:
            return out
        off += page


def in_list(names):
    return "(" + ",".join('"%s"' % n.replace('"', '') for n in names) + ")"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=1, help="今日の何日前から見るか(既定 1= 昨日〜明日)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    today = dt.datetime.now(JST).date()
    lo, hi = today - dt.timedelta(days=args.days), today + dt.timedelta(days=1)
    try:
        _, meta = rest(url, key, f"nar_meta?select=key,value&key=in.({META_KEY},{MERGE_KEY})")
        vals = {m["key"]: m.get("value") for m in meta or []}
        current = vals.get(META_KEY) if isinstance(vals.get(META_KEY), list) else []
        merge = merge_map(vals.get(MERGE_KEY))
        runs = rest_all(url, key, f"nar_runs?select=horse_name,birth_date,age,race_date&race_date=gte.{lo}"
                                  f"&race_date=lte.{hi}&order=track.asc,race_date.asc,race_no.asc,runner_number.asc")
    except Exception as e:                       # noqa: BLE001
        log(f"読み取りに失敗: {type(e).__name__}: {str(e)[:200]}"); return 2
    names = sorted({r["horse_name"] for r in runs if r.get("horse_name")} - set(current))
    profiles = []
    try:
        for i in range(0, len(names), NAME_BATCH):
            q = urllib.parse.quote(in_list(names[i:i + NAME_BATCH]), safe='(),"')
            profiles += rest_all(url, key, f"{T_PROFILES}?select=horse_name,birth_date&horse_name=in.{q}"
                                           "&order=horse_name.asc,birth_date.asc")
    except Exception as e:                       # noqa: BLE001
        if is_404(e):
            log(f"⚠{T_PROFILES} が無い(HTTP404)= 同名表の追記を飛ばす(DDL は docs/s21_ddl_20260923.sql)"); return 0
        log(f"{T_PROFILES} の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}"); return 2
    add = daily_additions(runs, profiles, current, merge)
    log(f"{lo}〜{hi}: 走 {len(runs)} / 同名表 {len(current)} 名 / profiles {len(profiles)} 行 / 足す {len(add)} 名 {add[:10]}")
    if not add:
        return 0
    if not args.apply:
        log("dry-run: 書かない"); return 0
    value = sorted(set(current) | set(add))
    body = json.dumps([{"key": META_KEY, "value": value,
                        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}], ensure_ascii=False).encode("utf-8")
    try:
        st, _ = rest(url, key, "nar_meta?on_conflict=key", "POST", body, "resolution=merge-duplicates,return=minimal")
    except Exception as e:                       # noqa: BLE001
        log(f"書き込み失敗: {type(e).__name__}: {str(e)[:200]}"); return 1
    log(f"nar_meta/{META_KEY} 更新 {st}({len(value)} 名)")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)

# -*- coding: utf-8 -*-
"""中央(JRA)の戦績を競馬ブックの馬の頁から取り込む(nankan-ai 定義書 69・9/25 決定 A〜D)。

動かす場所= PC タスク(run_daily.bat → scraper/daily_update.py)の 1 手順。
  py -3 -u scraper/fetch_jra_runs.py --dates 20260925,20260926 --collect-cards          # 既定= dry-run(CSV/JSON)
  py -3 -u scraper/fetch_jra_runs.py --dates 20260925,20260926 --collect-cards --push   # 本番 nar-official へ upsert
  py -3 -u scraper/fetch_jra_runs.py --horse-ids 0872577,0954110                        # 馬を直接
  py -3 -u scraper/fetch_jra_runs.py --html-dir DIR                                     # 保存済み HTML を解析(頁を取らない)
  py -3 -u scraper/fetch_jra_runs.py --backfill --from 20230101 --to 20230107 --select-only  # 過去分: kb 馬ID を集めて数える
  py -3 -u scraper/fetch_jra_runs.py --backfill --from 20230101 --to 20230131 --max-horses 200 # 過去分: 馬の頁も取る(dry-run)
--backfill: 転入初戦(3 歳以上・その日より前に地方の走が無い)の馬を nar_runs から日ごとに選び、kb 馬ID を
  nar_kb_danwa か 成績頁(日程頁→レースID)で拾う。state ファイルに済んだ日・集めた ID・取った馬を残し、再実行で飛ばす。

--collect-cards: 日程頁 → ばんえい(帯広)を除く全場のうち、能力表 JSON がまだ無いレースの能力表を取る
  (既存の parsers.parse_nouryoku の horse_id をそのまま使う)。
対象の馬(9/25 決定 B):
  ① 本番 nar_runs にその馬の、出馬表の日より前の地方の走が無い(馬名で引く)
  ② 能力表の過去 5 走に中央の走がある
  nar_jra_horses に取得済みの馬は飛ばす。ただし過去 5 走に last_jra_date より新しい中央の走があれば取り直す。
  前回 fetch_error の馬も取り直す(no_kanzendata_blocks= 頁に走が無い馬は除く・9/25 決定)。
鍵= s77-w1/pipeline/.env.nar(push_kb_runs.py と同じ読み方。⛔os.environ に入れない・印字しない)。
書き先: nar_jra_runs(鍵= kb_horse_id, race_date, place, race_no)・nar_jra_horses(鍵= kb_horse_id)。
"""

import argparse
import csv
import datetime as dt
import time
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

from jra_runs import parse_kanzen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ["KB_DATA_DIR"]) if os.environ.get("KB_DATA_DIR") else ROOT / "data"   # cloud
NAR_ENV = Path(r"C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\.env.nar")
MIN_WAIT = 1.5  # 過去分の一括だけ 1.5 秒まで(毎日の便は既定 3 秒のまま)
BANEI_CODE = "58"                       # レースID 6-8 桁目。帯広(ばんえい)は対象外
KB_TRACK = {"名古": "名古屋"}           # 競馬ブックの場名 → 本番 nar_runs の場名(違うのは名古屋だけ・日程頁 1,255 日で確認)
JRA_ABBR = set("札函福新東中京阪小")     # 能力表の過去走の場の略字(中央)
RETRIES = 3                             # 本番 DB への通信の打ち直し回数(間隔は RETRY_BASE × 1,2,4 秒)
RETRY_BASE = 5.0
SLEEP = time.sleep                      # 単体テストで差し替える
HB_JOB = "jra_runs"                     # nar_job_heartbeat の job 名
RUN_COLS = [
    "kb_horse_id", "race_date", "place", "race_no", "kai", "nichi", "kb_race_id",
    "race_name", "race_cond", "surface", "course", "direction", "distance", "weather", "going",
    "field_size", "gate", "finish", "finish_note", "time_raw", "time_sec", "margin",
    "last3f", "last4f", "first3f", "race_last3f", "passing", "pace", "popularity", "win_odds",
    "carried_weight", "jockey", "body_weight",
]
HORSE_COLS = ["kb_horse_id", "horse_name", "birth_year", "birth_date", "fetched_at",
              "last_jra_date", "jra_runs", "fetch_error"]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(msg):
    print(msg, flush=True)


# ---- 能力表から対象を選ぶ ----

def is_jra_run(run):
    """能力表の過去 1 走が中央か。'名' は名古屋と中京が同じ略字なので芝・中央のクラス名で中京とみなす。"""
    if run.get("is_trial"):
        return False
    t = run.get("track") or ""
    if t in JRA_ABBR:
        return True
    if t == "名":
        raw = run.get("raw") or ""
        return bool(re.search(r"芝|\s(新馬|未勝|[123]勝|ＯＰ|OP|オープン)\s", raw))
    return False


def run_dates(card_date, runs):
    """過去 5 走(5 走前→前走)の月日に年を付ける。前走から遡り、月日が後ろに戻ったら前の年。"""
    cur = card_date
    out = [None] * len(runs)
    for i in range(len(runs) - 1, -1, -1):
        mm, dd = runs[i].get("provisional_mm"), runs[i].get("provisional_dd")
        if not mm or not dd:
            continue
        y = cur.year if (mm, dd) <= (cur.month, cur.day) else cur.year - 1
        try:
            d = dt.date(y, mm, dd)
        except ValueError:
            continue
        out[i] = d
        cur = d
    return out


def ages_from_nouryoku_html(html):
    """能力表の頁 → {馬番: 年齢}。血統の欄(5 列目)の '牝 5' を読む(parse_nouryoku は年齢を残さない)。"""
    from bs4 import BeautifulSoup
    out = {}
    table = BeautifulSoup(html, "lxml").select_one("table.nouryoku_html_table")
    if table is None:
        return out
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 12:
            continue
        ub = tds[1].get_text(strip=True)
        m = re.search(r"(?:牡|牝|セ|騸)\s*(\d{1,2})(?:\s|$)", tds[4].get_text(" ", strip=True))
        if ub.isdigit() and m:
            out[int(ub)] = int(m.group(1))
    return out


def candidates_from_nouryoku(data_dir, dates):
    """{kb_horse_id: {name, track, card_date, jra_in_5, last_jra_in_5}}(同じ馬は早い日の出馬表を使う)"""
    want = {f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in dates}
    out = {}
    for f in sorted((Path(data_dir) / "json" / "nouryoku").glob("*.json")):
        if f.stem[6:8] == BANEI_CODE:
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        race = doc.get("race") or {}
        if race.get("date") not in want:
            continue
        card = dt.date.fromisoformat(race["date"])
        ages = None
        for h in doc.get("horses", []):
            hid = h.get("horse_id")
            if not hid:
                continue
            age = h.get("age")
            if age is None:
                if ages is None:   # fetch.py が保存した JSON には年齢が無い→ 同じレースのキャッシュ HTML から
                    cache = Path(data_dir) / "cache" / f"chihou_nouryoku_html_{f.stem}.html"
                    ages = ages_from_nouryoku_html(cache.read_text(encoding="utf-8")) if cache.exists() else {}
                age = ages.get(h.get("umaban"))
            runs = h.get("runs") or []
            ds = run_dates(card, runs)
            jra = [d for r, d in zip(runs, ds) if is_jra_run(r)]
            c = {"name": h.get("name"), "track": nar_track(race.get("track")), "card_date": race["date"],
                 "race_no": race.get("race_no"), "umaban": h.get("umaban"),
                 "birth_year": card.year - age if age else None,
                 "jra_in_5": len(jra), "last_jra_in_5": max((d for d in jra if d), default=None)}
            if hid not in out or c["card_date"] < out[hid]["card_date"]:
                out[hid] = c
    return out


def select_targets(cands, known, no_prior_local):
    """→ [(kb_horse_id, 理由)]。理由= '①' / '②' / '①②' / '再取得'。
    known: {kb_horse_id: {last_jra_date, fetch_error}} / no_prior_local: ① に当たる kb_horse_id の集合"""
    out = []
    for hid, c in sorted(cands.items()):
        k = known.get(hid)
        if k is not None:
            # 馬の頁に走が無い馬(新馬など)は毎日取り直さない。過去 5 走に中央の走が出たら下で取り直す
            if k.get("fetch_error") and k["fetch_error"] != "no_kanzendata_blocks":
                out.append((hid, "再取得"))
                continue
            last = k.get("last_jra_date")
            last = dt.date.fromisoformat(last) if isinstance(last, str) and last else last
            if c["last_jra_in_5"] and (last is None or c["last_jra_in_5"] > last):
                out.append((hid, "再取得"))
            continue
        r1 = hid in no_prior_local
        r2 = c["jra_in_5"] > 0
        if r1 or r2:
            out.append((hid, ("①" if r1 else "") + ("②" if r2 else "")))
    return out


def no_prior_from_rows(group, rows):
    """① の判定(同じ出馬表の日の馬だけ)。rows= nar_runs の {horse_name, race_date, age, track, race_no}(日付 <= 出馬表の日)。
    生まれ年= レースの年 − 年齢。出馬表側の生まれ年は能力表の年齢から。無ければ同じレースの nar_runs 行の年齢で補う。
    それでも分からない馬は馬名だけで判定する。"""
    def by(r):
        return int(str(r["race_date"])[:4]) - int(r["age"]) if r.get("age") is not None else None
    out = set()
    for hid, c in group.items():
        mine = [r for r in rows if r["horse_name"] == c["name"]]
        cd = str(c["card_date"])
        byear = c.get("birth_year")
        if byear is None:
            same = [r for r in mine if str(r["race_date"]) == cd and r.get("track") == c.get("track")
                    and (c.get("race_no") is None or r.get("race_no") == c.get("race_no"))]
            byear = by(same[0]) if same else None
        prior = [r for r in mine if str(r["race_date"]) < cd]
        if byear is not None:
            prior = [r for r in prior if by(r) == byear]
        if not prior:
            out.add(hid)
    return out


# ---- 過去分(--backfill): 転入初戦のレースの成績頁から kb 馬ID を集める ----
# 方法(定義書 69 の過去分): 日ごとに本番 nar_runs から「3 歳以上で、その日より前に地方の走が無い馬」(=転入初戦)を選ぶ。
#   kb 馬ID は ① nar_kb_danwa(南関の一部)にあればそれ(頁不要) ② 無ければ日程頁(1 日 1 頁)でレースIDを引き、
#   そのレースの成績頁(1 レース 1 頁・全馬の /db/uma/ リンク)から馬名(無ければ馬番)で拾う。
#   日程頁と成績頁はキャッシュ(data/cache)を使う= 取り直さない。進み具合は state ファイル(JSON)に残す。

def nar_track(t):
    return KB_TRACK.get(t, t)


def norm_name(s):
    import unicodedata
    return re.sub(r"[\s★☆]", "", unicodedata.normalize("NFKC", s or ""))


def first_runs_from_rows(day, day_rows, prior_rows):
    """day の nar_runs 行(3 歳以上・ばんえい除く)→ 転入初戦の行のリスト(その日より前の走が無い馬)。
    生まれ年= レースの年 − 年齢 で同名の別馬を分ける(no_prior_from_rows と同じ判定)。"""
    group = {}
    for r in day_rows:
        if r.get("age") is None or int(r["age"]) < 3 or str(r.get("track", "")).startswith("帯広"):
            continue
        key = f'{r["track"]}|{r["race_no"]}|{r["horse_name"]}'
        group[key] = {"name": r["horse_name"], "card_date": day, "birth_year": int(day[:4]) - int(r["age"]),
                      "track": r["track"], "race_no": r["race_no"], "row": r}
    hit = no_prior_from_rows(group, [r for r in prior_rows if str(r["race_date"]) < day])
    return [group[k]["row"] for k in sorted(hit)]


def race_map_from_nittei(meets, day):
    """日程頁 → {(場, R): レースID}(その日のレースだけ・ばんえい除く)"""
    ymd = day.replace("-", "")
    out = {}
    for m in meets:
        for race in m["races"]:
            rid = race["race_id"]
            if rid[:4] == ymd[:4] and rid[12:16] == ymd[4:8] and rid[6:8] != BANEI_CODE:
                out[(nar_track(m["track"]), int(race["race_no"]))] = rid
    return out


def pick_id(results, name, umaban):
    """成績頁/厩舎の話の行 → 馬名(正規化)で kb 馬ID。無ければ馬番で。"""
    n = norm_name(name)
    for r in results:
        if r.get("horse_id") and norm_name(r.get("horse_name") or r.get("name")) == n:
            return r["horse_id"]
    for r in results:
        if r.get("horse_id") and umaban is not None and str(r.get("umaban")) == str(umaban):
            return r["horse_id"]
    return None


def load_state(path):
    try:
        st = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    for k, v in (("done_dates", []), ("ids", {}), ("unresolved", {}), ("fetched", {})):
        st.setdefault(k, v)
    return st


def save_state(path, st):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, p)


def backfill_collect(nar, get_client, day_list, st, state_path, max_pages):
    """日ごとに転入初戦の馬の kb 馬ID を集める。→ 新しく取った頁数。頁の上限に達したらその日は済みにせず止める。"""
    from parsers import parse_nittei, parse_seiseki, parse_nouryoku
    new_pages = 0
    done = set(st["done_dates"])

    def page(path):
        nonlocal new_pages
        c = get_client()
        if not c._cache_file(path).exists():
            if new_pages >= max_pages:
                raise StopIteration
            new_pages += 1
        return c.get(path, cache=True)

    for day in day_list:
        if day in done:
            continue
        rows = nar.get_all("nar_runs", {"select": "track,race_no,runner_number,horse_name,age",
                                        "race_date": f"eq.{day}", "age": "gte.3", "order": "track,race_no,runner_number"})
        names = sorted({r["horse_name"] for r in rows if not str(r["track"]).startswith("帯広")})
        prior = []
        for i in range(0, len(names), 20):
            q = ",".join('"' + n.replace('"', '') + '"' for n in names[i:i + 20])
            prior += nar.get_all("nar_runs", {"select": "horse_name,race_date,age", "horse_name": f"in.({q})",
                                              "race_date": f"lt.{day}", "order": "horse_name,race_date"})
        firsts = first_runs_from_rows(day, rows, prior)
        danwa = nar.get_all("nar_kb_danwa", {"select": "track,race_no,umaban,horse_name,horse_id,race_id",
                                             "race_date": f"eq.{day}"}) or []
        dmap, rmap = {}, {}
        for d in danwa:
            dmap.setdefault((nar_track(d["track"]), int(d["race_no"])), []).append(d)
            if d.get("race_id"):
                rmap[(nar_track(d["track"]), int(d["race_no"]))] = d["race_id"]
        day_ids, day_un, how = {}, {}, {"談話": 0, "成績頁": 0}
        try:
            seiseki, nittei = {}, None
            for r in firsts:
                key = (r["track"], int(r["race_no"]))
                label = f'{day}|{r["track"]}|{r["race_no"]}|{r["horse_name"]}'
                hid = pick_id(dmap.get(key, []), r["horse_name"], r.get("runner_number"))
                if hid:
                    how["談話"] += 1
                else:
                    rid = rmap.get(key)
                    if rid is None:
                        if nittei is None:
                            c = get_client()
                            nittei = race_map_from_nittei(parse_nittei(page(c.nittei_path(day.replace("-", "")))), day)
                        rid = nittei.get(key)
                    if rid is None:
                        day_un[label] = "no_race_id"
                        continue
                    if rid not in seiseki:
                        seiseki[rid] = parse_seiseki(page(get_client().seiseki_path(rid)), rid).get("results") or []
                        if not seiseki[rid]:   # 競走取止めなどで成績頁が空→ 能力表頁の馬で拾う
                            seiseki[rid] = parse_nouryoku(page(get_client().nouryoku_path(rid)), rid).get("horses") or []
                    hid = pick_id(seiseki[rid], r["horse_name"], r.get("runner_number"))
                    if hid:
                        how["成績頁"] += 1
                if hid:
                    day_ids[label] = hid
                else:
                    day_un[label] = "no_horse_id"
        except StopIteration:
            log(f"  頁の上限 {max_pages} に達した: {day} から先は次回")
            break
        st["ids"].update(day_ids)
        st["unresolved"].update(day_un)
        st["done_dates"].append(day)
        done.add(day)
        save_state(state_path, st)
        log(f"  {day}: 転入初戦 {len(firsts)} 頭・ID {len(day_ids)}({json.dumps(how, ensure_ascii=False)})"
            f"・不明 {len(day_un)}・新しい頁 累計 {new_pages}")
    return new_pages


def day_range(frm, to):
    a, b = dt.datetime.strptime(frm, "%Y%m%d").date(), dt.datetime.strptime(to, "%Y%m%d").date()
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


# ---- 本番(nar-official)。鍵はファイルから読むだけ ----

def read_env(path):
    # cloud(2026-09-29): 鍵は secrets→環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY(⛔印字しない)
    if os.environ.get("SUPABASE_URL"):
        return {"SUPABASE_URL": os.environ["SUPABASE_URL"],
                "SUPABASE_SERVICE_KEY": os.environ.get("SUPABASE_SERVICE_KEY", "")}
    env = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class Nar:
    def __init__(self, env_path):
        env = read_env(env_path)
        self.base = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
        key = env.get("SUPABASE_SERVICE_KEY", "")
        if not key:
            raise RuntimeError("SUPABASE_SERVICE_KEY が無い")
        self._h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _call(self, method, url, what, headers=None, **kw):
        """通信の切れ(SSL EOF など)と 5xx は 間隔を伸ばして 3 回まで打ち直す(5→10→20 秒)。4 回目も駄目なら上げる。"""
        h = headers or self._h
        for attempt in range(RETRIES + 1):
            try:
                r = requests.request(method, url, headers=h, timeout=60, **kw)
            except requests.exceptions.RequestException as e:
                if attempt == RETRIES:
                    raise
                wait = RETRY_BASE * (2 ** attempt)
                log(f"  ! {what} {type(e).__name__}→ {wait:g} 秒後に打ち直す({attempt + 1}/{RETRIES})")
                SLEEP(wait)
                continue
            if r.status_code >= 500 and attempt < RETRIES:
                wait = RETRY_BASE * (2 ** attempt)
                log(f"  ! {what} HTTP {r.status_code}→ {wait:g} 秒後に打ち直す({attempt + 1}/{RETRIES})")
                SLEEP(wait)
                continue
            return r

    def get(self, table, params):
        r = self._call("GET", self.base + table, f"GET {table}", params=params)
        if r.status_code == 404 or (r.status_code == 400 and "PGRST205" in r.text):
            return None          # 表がまだ無い(DDL 前)
        if r.status_code >= 300:
            raise RuntimeError(f"GET {table}: HTTP {r.status_code}")
        return r.json()

    def get_all(self, table, params, page=1000):
        """1000 行ずつ offset で全部取る(PostgREST の行数上限の対策)"""
        out, off = [], 0
        while True:
            rows = self.get(table, dict(params, limit=str(page), offset=str(off)))
            if not rows:
                return out
            out += rows
            if len(rows) < page:
                return out
            off += page

    def known(self, ids):
        out = {}
        ids = sorted(ids)
        for i in range(0, len(ids), 100):
            rows = self.get("nar_jra_horses", {"select": "kb_horse_id,last_jra_date,fetch_error",
                                               "kb_horse_id": f"in.({','.join(ids[i:i + 100])})"})
            if rows is None:
                log("nar_jra_horses がまだ無い= 取得済み 0 頭とみなす")
                return {}
            out.update({r["kb_horse_id"]: r for r in rows})
        return out

    def no_prior_local(self, cands):
        """① 出馬表の日より前の地方の走が nar_runs に無い馬(馬名+生まれ年で引く)"""
        by_date = {}
        for hid, c in cands.items():
            if c["name"]:
                by_date.setdefault(c["card_date"], {})[hid] = c
        hit = set()
        for d, group in by_date.items():
            ns = sorted({c["name"] for c in group.values()})
            rows = []
            for i in range(0, len(ns), 40):
                q = ",".join('"' + n.replace('"', '') + '"' for n in ns[i:i + 40])
                rows += self.get("nar_runs", {"select": "horse_name,race_date,age,track,race_no",
                                              "horse_name": f"in.({q})", "race_date": f"lte.{d}",
                                              "order": "horse_name,race_date.desc", "limit": "5000"}) or []
            hit |= no_prior_from_rows(group, rows)
        return hit

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return
        h = dict(self._h, Prefer="resolution=merge-duplicates,return=minimal")
        for i in range(0, len(rows), 500):
            body = json.dumps(rows[i:i + 500], ensure_ascii=False).encode("utf-8")
            # §300 通信の切れ(SSL EOF など)は 3 回まで間を伸ばして打ち直す(9/27 に 24 頭分が書けずに落ちた)
            r = self._call("POST", self.base + table + "?on_conflict=" + urllib.parse.quote(on_conflict),
                           f"upsert {table}", headers=h, data=body)
            if r.status_code >= 300:
                raise RuntimeError(f"upsert {table}: HTTP {r.status_code} {r.text[:200]}")

    def drop_kd_twins(self, horses):
        """案 F: KDSCOPE から入れた仮の馬(kb_horse_id が 'kd' で始まる)のうち、いま競馬ブックで取れた馬と
        同じ 馬名+生年 の行を消す(競馬ブックの行で置き換える)。KD 側は 2026-03 で止まり・騎手が 4 文字なので本物を優先。
        → 消した仮 id の数"""
        n = 0
        for h in horses:
            if not h.get("horse_name") or not h.get("birth_year"):
                continue
            rows = self.get("nar_jra_horses", {"select": "kb_horse_id", "kb_horse_id": "like.kd*",
                                               "horse_name": f"eq.{h['horse_name']}",
                                               "birth_year": f"eq.{h['birth_year']}"}) or []
            for r in rows:
                kid = r["kb_horse_id"]
                for table in ("nar_jra_runs", "nar_jra_horses"):     # 走→馬の順(途中で落ちても馬が残れば翌日また消せる)
                    d = self._call("DELETE", self.base + table, f"delete {table}",
                                   headers=dict(self._h, Prefer="return=minimal"), params={"kb_horse_id": f"eq.{kid}"})
                    if d.status_code >= 300:
                        raise RuntimeError(f"delete {table} {kid}: HTTP {d.status_code} {d.text[:200]}")
                log(f"  仮の行を置き換え: {kid} → {h['kb_horse_id']}({h['horse_name']} {h['birth_year']})")
                n += 1
        return n

    def heartbeat(self, ok, note):
        """nar_job_heartbeat に便の成否を書く(job=HB_JOB)。失敗の時は last_ok を書かない= 前回の成功時刻が残る。
        ここで落ちても本処理の結果は変えない(1 回だけ試す)。"""
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        row = {"job": HB_JOB, "last_try": now, "last_status": "ok" if ok else "fail", "note": note[:200]}
        if ok:
            row["last_ok"] = now
        try:
            h = dict(self._h, Prefer="resolution=merge-duplicates,return=minimal")
            r = requests.post(self.base + "nar_job_heartbeat?on_conflict=job", headers=h,
                              data=json.dumps([row], ensure_ascii=False).encode("utf-8"), timeout=30)
            if r.status_code >= 300:
                log(f"  ! heartbeat HTTP {r.status_code}")
        except requests.exceptions.RequestException as e:
            log(f"  ! heartbeat {type(e).__name__}")


# ---- 出馬表(能力表)をばんえい以外の全場ぶん集める ----

def collect_cards(client, data_dir, dates, max_pages):
    from parsers import parse_nittei, parse_nouryoku
    fetched, per_track = 0, {}
    for d in dates:
        meets = parse_nittei(client.get(client.nittei_path(d)))
        for m in meets:
            for race in m["races"]:
                rid = race["race_id"]
                if rid[12:16] != d[4:8] or rid[6:8] == BANEI_CODE:
                    continue
                per_track[m["track"]] = per_track.get(m["track"], 0) + 1
                if (Path(data_dir) / "json" / "nouryoku" / f"{rid}.json").exists():
                    continue
                if fetched >= max_pages:
                    log(f"  能力表の上限 {max_pages} 頁に達した: {rid} は取らない")
                    continue
                fetched += 1
                try:
                    html = client.get(client.nouryoku_path(rid), cache=False)
                    parsed = parse_nouryoku(html, rid)
                except Exception as e:
                    log(f"  ! nouryoku {rid}: {type(e).__name__}")
                    continue
                ages = ages_from_nouryoku_html(html)
                for h in parsed["horses"]:
                    h["age"] = ages.get(h.get("umaban"))   # 生まれ年(① の判定)用
                if parsed["horses"]:
                    jdir = Path(data_dir) / "json" / "nouryoku"   # fetch.save_json と同じ形(古い fetch.py は data_dir を取らない)
                    jdir.mkdir(parents=True, exist_ok=True)
                    (jdir / f"{rid}.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"出馬表のレース数: {json.dumps(per_track, ensure_ascii=False)}・能力表を新たに {fetched} 頁")
    return fetched


# ---- 出力 ----

def write_outputs(out_dir, runs, horses, targets):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    files = []
    for name, cols, rows in (("nar_jra_runs", RUN_COLS, runs), ("nar_jra_horses", HORSE_COLS, horses)):
        p = out_dir / f"{name}_{stamp}.csv"
        with p.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        files.append(p)
    p = out_dir / f"jra_runs_{stamp}.json"
    p.write_text(json.dumps({"targets": targets, "horses": horses, "runs": runs},
                            ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    files.append(p)
    return files


def process_html(hid, html, now):
    parsed = parse_kanzen(html, hid)
    horse = {c: parsed["horse"].get(c) for c in HORSE_COLS}
    horse["fetched_at"] = now
    horse["fetch_error"] = None if parsed["n_blocks"] else "no_kanzendata_blocks"
    runs = [{c: r.get(c) for c in RUN_COLS} for r in parsed["runs"]]
    return horse, runs


def main(argv=None):
    ap = argparse.ArgumentParser(description="競馬ブック 馬の頁から中央の戦績を取り込む")
    ap.add_argument("--dates", default="", help="出馬表の日付 YYYYMMDD のカンマ区切り")
    ap.add_argument("--days-ahead", type=int, default=None,
                    help="--dates を省いた時に 今日〜N 日先 を使う(2= 今日・明日・明後日。出馬表は 2 日先まで出る)")
    ap.add_argument("--no-heartbeat", action="store_true", help="nar_job_heartbeat に書かない")
    ap.add_argument("--collect-cards", action="store_true", help="ばんえい以外の全場の能力表を集めてから選ぶ")
    ap.add_argument("--select-only", action="store_true", help="対象を選んで数えるだけ(馬の頁は取らない)")
    ap.add_argument("--horse-ids", default="", help="kb 馬ID のカンマ区切り(対象の選定を飛ばす)")
    ap.add_argument("--html-dir", type=Path, help="保存済み HTML(member_{ID}.html)を解析する")
    ap.add_argument("--dry-run", action="store_true", help="書かない(既定。--push が無ければ常に dry-run)")
    ap.add_argument("--push", action="store_true", help="本番へ upsert する")
    ap.add_argument("--max-horses", type=int, default=300, help="1 回で取る馬の頁の上限")
    ap.add_argument("--max-card-pages", type=int, default=400, help="1 回で取る能力表の頁の上限")
    ap.add_argument("--backfill", action="store_true", help="過去分: 転入初戦のレースから kb 馬ID を集めて取る")
    ap.add_argument("--from", dest="date_from", default="", help="--backfill の開始日 YYYYMMDD")
    ap.add_argument("--to", dest="date_to", default="", help="--backfill の終了日 YYYYMMDD")
    ap.add_argument("--max-pages", type=int, default=400, help="--backfill で 1 回に新しく取る日程頁+成績頁の上限")
    ap.add_argument("--retry-unresolved", action="store_true", help="--backfill で不明の馬がいた日をやり直す")
    ap.add_argument("--state-file", type=Path, help="--backfill の進み具合(既定 out-dir/backfill_state.json)")
    ap.add_argument("--wait-seconds", type=float, default=3.0)
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--out-dir", type=Path, default=DATA / "jra_runs")
    ap.add_argument("--nar-env", type=Path, default=NAR_ENV)
    ap.add_argument("--env-file", type=Path, help="競馬ブックのログイン(.env)")
    args = ap.parse_args(argv)
    push = args.push and not args.dry_run
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    client = None

    def get_client():
        nonlocal client
        if client is None:
            from fetch import load_env
            from keibabook import KeibabookClient
            load_env(args.env_file) if args.env_file else load_env()   # 競馬ブックの ID/パスワード(古い fetch.py は引数なし)
            client = KeibabookClient(login_id=os.environ.get("KEIBABOOK_LOGIN_ID"),
                                     password=os.environ.get("KEIBABOOK_PASSWORD"),
                                     data_dir=args.data_dir,
                                     wait_seconds=max(MIN_WAIT, args.wait_seconds))
            client.ensure_login()
        return client

    horses, runs, targets = [], [], []
    st = state_path = None
    mode = "push" if push else "dry"
    pending = []   # まだ本番へ書いていない (馬, 走) — flush() で書いてから取得済みにする

    def flush():
        if not pending:
            return
        nar_w = Nar(args.nar_env)
        hs = [h for h, _ in pending]
        rs = [x for _, r in pending for x in r]
        try:
            nar_w.upsert("nar_jra_runs", rs, "kb_horse_id,race_date,place,race_no")
            nar_w.upsert("nar_jra_horses", [h for h in hs if not h.get("fetch_error")], "kb_horse_id")
            # 失敗は既存の馬名・中央走数を消さないよう 3 列だけ書く
            nar_w.upsert("nar_jra_horses", [{k: h[k] for k in ("kb_horse_id", "fetch_error", "fetched_at")}
                                            for h in hs if h.get("fetch_error")], "kb_horse_id")
            # 案 F: 本物を書けた馬だけ、同じ 馬名+生年 の KDSCOPE の仮の行を消す(書く前に消すと取りこぼし時に走が無くなる)
            nar_w.drop_kd_twins([h for h in hs if not h.get("fetch_error")])
        except Exception:
            # 打ち直しても書けなかった分は手元に残す(取った頁を捨てない)。nar_jra_horses に入っていないので
            # 翌日の便が同じ馬を選び直して取り直す。急ぐときは --html-dir でなく --horse-ids で打ち直す。
            for p in write_outputs(Path(args.out_dir) / "unsent", rs, hs, [(h["kb_horse_id"], "未送信") for h in hs]):
                log(f"書けなかった分を手元に保存: {p}")
            raise
        if st is not None:
            st["fetched"].setdefault(mode, []).extend(h["kb_horse_id"] for h in hs)
            save_state(state_path, st)
        pending.clear()
    if args.backfill:
        if not (args.date_from and args.date_to):
            ap.error("--backfill には --from と --to が要る")
        state_path = args.state_file or (args.out_dir / "backfill_state.json")
        st = load_state(state_path)
        nar = Nar(args.nar_env)
        days = day_range(args.date_from, args.date_to)
        if args.retry_unresolved:     # 不明の馬がいた日だけ済みから外してやり直す(頁はキャッシュを使う)
            redo = {k[:10] for k in st["unresolved"] if k[:10] in set(days)}
            st["done_dates"] = [d for d in st["done_dates"] if d not in redo]
            st["unresolved"] = {k: v for k, v in st["unresolved"].items() if k[:10] not in redo}
            log(f"不明のやり直し: {len(redo)} 日")
        backfill_collect(nar, get_client, days, st, state_path, args.max_pages)
        in_range = {k: v for k, v in st["ids"].items() if k[:10] in set(days)}
        un = [k for k in st["unresolved"] if k[:10] in set(days)]
        done_in = sum(1 for d in days if d in set(st["done_dates"]))
        ids = sorted(set(in_range.values()))
        fetched = set(st["fetched"].get(mode, []))
        known = nar.known(ids)
        targets = [(h, "過去分") for h in ids
                   if h not in fetched and not (h in known and not known[h].get("fetch_error"))]
        log(f"過去分 {args.date_from}〜{args.date_to}: 済んだ日 {done_in}/{len(days)}・転入初戦の ID {len(in_range)} 件"
            f"({len(ids)} 頭)・不明 {len(un)}・取得済み {len(ids) - len(targets)} 頭・これから取る {len(targets)} 頭")
    if args.html_dir and not args.backfill:
        for f in sorted(args.html_dir.glob("member_*.html")):
            m = re.fullmatch(r"member_(\d+)\.html", f.name)
            if m:
                h, r = process_html(m.group(1), f.read_text(encoding="utf-8"), now)
                horses.append(h)
                runs.extend(r)
                pending.append((h, r))
    else:
        if args.backfill:
            pass                      # 対象は上で選んだ
        elif args.horse_ids:
            targets = [(x.strip(), "指定") for x in args.horse_ids.split(",") if x.strip()]
        else:
            dates = [d.strip() for d in args.dates.split(",") if d.strip()]
            if not dates and args.days_ahead is not None:
                today = dt.date.today()
                dates = [(today + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(args.days_ahead + 1)]
                log(f"出馬表の日付: {','.join(dates)}")
            if not dates:
                ap.error("--dates か --horse-ids か --html-dir を指定")
            if args.collect_cards:
                collect_cards(get_client(), args.data_dir, dates, args.max_card_pages)
            cands = candidates_from_nouryoku(args.data_dir, dates)
            nar = Nar(args.nar_env)
            targets = select_targets(cands, nar.known(cands), nar.no_prior_local(cands))
            summary = {}
            for hid, why in targets:
                t = cands[hid]["track"]
                summary.setdefault(t, {}).setdefault(why, 0)
                summary[t][why] += 1
            per_track = {}
            for c in cands.values():
                per_track[c["track"]] = per_track.get(c["track"], 0) + 1
            log(f"出馬表の馬 {len(cands)} 頭 {json.dumps(per_track, ensure_ascii=False)}")
            log(f"対象 {len(targets)} 頭 {json.dumps(summary, ensure_ascii=False)}")
        if not args.select_only:
            for hid, _why in targets[: args.max_horses]:
                try:
                    h, r = process_html(hid, get_client().get(f"/db/uma/{hid}/kanzen", cache=False), now)
                except Exception as e:  # 失敗は fetch_error に残して翌日再試行
                    h = {c: None for c in HORSE_COLS}
                    h.update(kb_horse_id=hid, fetched_at=now, fetch_error=type(e).__name__)
                    r = []
                horses.append(h)
                runs.extend(r)
                pending.append((h, r))
                if push and len(pending) >= 50:   # 50 頭ごとに本番へ書いてから「取得済み」にする(途中で落ちても取りこぼさない)
                    flush()

    ok = [h for h in horses if not h.get("fetch_error")]
    # 頁に走が無い馬(初出走など= 中央を走っていない)は失敗に数えない(10/3: 「失敗 26」の多くがこれで紛らわしかった)
    no_jra = sum(1 for h in horses if h.get("fetch_error") == "no_kanzendata_blocks")
    summary_line = (f"馬 {len(horses)} 頭(中央の走なし {no_jra}・失敗 {len(horses) - len(ok) - no_jra})"
                    f"・中央の走 {len(runs)} 行")
    log(summary_line)
    # cloud(2026-09-29): 失敗の種類を件数だけ出す(初回の dry-run で 56 頭中 18 頭が失敗・種類がログに無かった)
    errs = {}
    for h in horses:
        if h.get("fetch_error"):
            errs[h["fetch_error"]] = errs.get(h["fetch_error"], 0) + 1
    if errs:
        log(f"失敗の種類: {json.dumps(errs, ensure_ascii=False)}")
    if push:
        flush()
        log("本番へ upsert 済み")
        if not args.no_heartbeat:
            Nar(args.nar_env).heartbeat(True, summary_line)
    else:
        for p in write_outputs(args.out_dir, runs, horses, targets):
            log(f"dry-run 出力: {p}")
    return 0


def main_with_heartbeat(argv=None):
    """--push の便が例外で落ちたら nar_job_heartbeat に fail を書いてから exit 1(便の止まりを見張りで拾う)。"""
    argv = sys.argv[1:] if argv is None else argv
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception as e:
        if "--push" in argv and "--dry-run" not in argv and "--no-heartbeat" not in argv:
            env = NAR_ENV
            if "--nar-env" in argv:
                env = Path(argv[argv.index("--nar-env") + 1])
            try:
                Nar(env).heartbeat(False, f"{type(e).__name__}: {str(e)[:150]}")
            except Exception as e2:   # 鍵が読めない等。本来の例外を優先して上げる
                log(f"  ! heartbeat を書けなかった {type(e2).__name__}")
        raise


if __name__ == "__main__":
    raise SystemExit(main_with_heartbeat())

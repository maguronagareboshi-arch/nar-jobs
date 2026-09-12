# -*- coding: utf-8 -*-
"""§52 高知の結果保存の自動化(2026-08-29 ユーザー裁定・手動ルーチン廃止)。

公式(keiba.go.jp)の競走成績 RaceMarkTable を読み、旧DB(keiba_races/keiba_horses)へ
既存 Worker RPC `/rpc/save-keiba-race-bundle` 経由で書く。管理者ビューアの手動「取り込み→保存」と
**同じソース・同じ口・同じ行の形**(modules/app-main.js 7664-7678 から採取)。

⛔安全の要:
- **既存行の非結果列は保全する**= keiba_horses には first3f(映像計測)・post_comment(談話)・
  lineage_login_code 等が同居している。既存行を読んでから結果列だけを上書きして完全な行を送る
  (部分行を送ると RPC の upsert が既存値を消しうる)
- **結果が既にある日は触らない**(日付単位・全量置き換えしない=feedback-one-year-scope)。
  ⚠§149 D(2026-09-11)で**1 つだけ例外**: レース名が空の行は、公式に名前があるときだけ
  名前・距離・クラスを埋め直す(結果列は 1 つも触らない)。2026-09-06 に 12 行が空のまま残り、
  この規則のせいで二度と直らなかったため(#551)
- SINCE(2026-08-01)より前は対象外(それ以前は手動保存済み)

使い方:
  py -3.12 -X utf8 cloud/kochi_results.py --env pipeline/.env.nar                 # ドライラン(対象日の検出+パース+bundle書き出し)
  py -3.12 -X utf8 cloud/kochi_results.py --env pipeline/.env.nar --check 2026/07/26   # オラクル= 手動保存済みの日とdiff(書かない)
  py -3.12 -X utf8 cloud/kochi_results.py --env pipeline/.env.nar --apply          # 実弾(Worker経由で保存+read-back検算)
環境変数: SUPABASE_URL/SUPABASE_ANON_KEY(nar読み)・KOCHI_WRITE_TOKEN(--apply の Worker 認証)
終了コード: 0 正常(対象なし含む) / 1 保存失敗 / 2 前提の読み取り失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; unified-viewer/1.0; +maguronagareboshi@gmail.com)"
SINCE = "2026-08-01"                     # これより前の日は対象外(手動保存済み・1年単位ルールの床とは別物)
BABA = "31"                              # 高知
WORKER_URL = "https://keiba-proxydeploy.maguronagareboshi.workers.dev"

# 旧DB(keiba_*)の読み。anon は公開キー= js/data.js の SUPABASE_KEY と同一(cloud/noken_index.py と同じ)
CHIHOU_URL = "https://jcrcftvrsgmsewwdkqha.supabase.co"
CHIHOU_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjcmNmdHZyc2dtc2V3d2RrcWhhIiwi"
               "cm9sZSI6ImFub24iLCJpYXQiOjE3ODA4MDY0NjgsImV4cCI6MjA5NjM4MjQ2OH0."
               "UED2rJNsuTPqofrhhNhQ2RM0NKc2eJ6qHllfbnebMe0")


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def http_get(url, headers=None, tries=3, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as e:
            last = e
            if n < tries - 1:
                time.sleep(2 * (n + 1))
    raise RuntimeError(f"GET {url[:100]} 失敗: {type(last).__name__}: {str(last)[:120]}")


def sb_rows(base, key, path):
    raw = http_get(f"{base}/rest/v1/{path}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------- 公式ページのパース(stdlibだけ)

class _Tables(HTMLParser):
    """HTML → [table…]・table = [[セル文字列…]…]。RaceMarkTable の結果表(table0)は rowspan 無し(2026-08-29 実測)
    なので素直な行×列で足りる。th/td は区別しない(1行目が見出し)"""

    def __init__(self):
        super().__init__()
        self.tables, self._t, self._row, self._cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._t.append(self._row)
            self._row = None
        elif tag == "table" and self._t is not None:
            self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


# 結果表の列(公式の見出しそのまま・2026-08-29 実測: 着順/枠/馬番/馬名/所属/性齢/負担/騎手/調教師/馬体重/タイム/着差/上がり/コーナー/人気/単勝)
_COLS = {"着順": "chakujun", "枠": "waku_ban", "馬番": "uma_ban", "馬名": "horse_name", "所属": "belong",
         "性齢": "sex_age", "負担": "kinryo", "騎手": "jockey", "調教師": "trainer", "馬体重": "weight",
         "タイム": "time", "着差": "diff", "上がり": "agari3f", "コーナー": "corner", "人気": "ninki", "単勝": "odds"}


def parse_mark_table(html):
    """成績ページ → {'horses': [dict…], 'track_cond', 'agari4f', 'agari3f_race', 'lineage': {馬名: コード}}。
    結果表が無ければ None(未確定・非開催)"""
    p = _Tables()
    p.feed(html)
    body = re.sub(r"<[^>]+>", " ", html)
    out = {"horses": [], "track_cond": "", "agari4f": "", "agari3f_race": "", "lineage": {}}
    # §52続き: 馬名リンクの血統コード(手動保存の lineage_login_code と同じ出所。空のときだけ埋める用)
    for code, name in re.findall(r"k_lineageLoginCode=(\d+)[^>]*>\s*([^<]+)", html):
        nm = re.sub(r"\s+", "", name)
        if nm and nm not in out["lineage"]:
            out["lineage"][nm] = code
    m = re.search(r"馬場状態\s*[：:]?\s*(良|稍重|重|不良)", body) or re.search(r"[（(](良|稍重|重|不良)[）)]", body)
    if m:
        out["track_cond"] = m.group(1)
    best, head_map = None, None
    for t in p.tables:
        if not t:
            continue
        hm = {}
        for i, h in enumerate(t[0]):
            key = next((v for k, v in _COLS.items() if h.startswith(k)), None)
            if key and key not in hm.values():
                hm[i] = key
        # 着順と馬番と馬名が揃う表だけが結果表
        if {"chakujun", "uma_ban", "horse_name"} <= set(hm.values()) and (best is None or len(t) > len(best)):
            best, head_map = t, hm
    if best is None:
        return None
    for row in best[1:]:
        h = {v: (row[i] if i < len(row) else "") for i, v in head_map.items()}
        if not re.fullmatch(r"\d{1,2}", h.get("uma_ban", "")):
            continue
        # ⛔全角→半角はしない(手動保存の実物が半角で入っている列は公式も半角。形は公式のまま)
        out["horses"].append(h)
    # 上がりタイム表(ヘッダー [ ,4F,3F] / データ [上がりタイム,51.1,38.9])
    for t in p.tables:
        if len(t) >= 2 and any("4F" in c for c in t[0]) and any("3F" in c for c in t[0]):
            idx4 = next((i for i, c in enumerate(t[0]) if c.strip() == "4F"), None)
            idx3 = next((i for i, c in enumerate(t[0]) if c.strip() == "3F"), None)
            for row in t[1:]:
                if any("上がり" in c for c in row):
                    if idx4 is not None and idx4 < len(row) and re.fullmatch(r"\d{2,3}\.\d", row[idx4]):
                        out["agari4f"] = row[idx4]
                    if idx3 is not None and idx3 < len(row) and re.fullmatch(r"\d{2}\.\d", row[idx3]):
                        out["agari3f_race"] = row[idx3]
            break
    return out if out["horses"] else None


def fetch_race(date_slash, race_no):
    url = ("https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable"
           f"?k_raceDate={urllib.parse.quote(date_slash, safe='')}&k_raceNo={race_no}&k_babaCode={BABA}")
    return parse_mark_table(http_get(url).decode("utf-8", "replace"))


# ---------------------------------------------------------------- bundle(管理者ビューアの保存と同じ形)

RACE_KEYS = ["race_date", "race_no", "baba_code", "race_name", "distance", "race_class", "track_cond",
             "first3f", "first3f_source", "agari4f", "agari3f_race", "pace_type", "memo", "lap_times"]
HORSE_KEYS = ["race_date", "race_no", "baba_code", "uma_ban", "waku_ban", "horse_name", "belong", "sex_age",
              "kinryo", "jockey", "trainer", "weight", "chakujun", "ninki", "odds", "time", "diff", "agari3f",
              "corner", "first3f", "pace_type", "mukae_shoumen", "shoumen_straight", "post_comment",
              "lineage_login_code"]
RESULT_KEYS = {"weight", "chakujun", "ninki", "odds", "time", "diff", "agari3f", "corner"}   # 公式で上書きする列


def build_bundle(date_slash, race_no, parsed, ex_race, ex_horses):
    """既存行(あれば)の非結果列を保全し、公式パースの結果列を上書きした bundle を作る"""
    race = {k: "" for k in RACE_KEYS}
    race.update({"race_date": date_slash, "race_no": race_no, "baba_code": BABA})
    if ex_race:                                             # 出馬表保存時の値+計測系をそのまま持ち越す
        for k in RACE_KEYS:
            if k in ex_race and ex_race[k] is not None and k not in ("race_date", "race_no", "baba_code"):
                race[k] = ex_race[k]
    if parsed["track_cond"]:
        race["track_cond"] = parsed["track_cond"]
    if parsed["agari4f"]:
        race["agari4f"] = parsed["agari4f"]
    if parsed["agari3f_race"]:
        race["agari3f_race"] = parsed["agari3f_race"]

    ex_by_ban = {int(h["uma_ban"]): h for h in (ex_horses or []) if h.get("uma_ban") is not None}
    horses = []
    for h in parsed["horses"]:
        ban = int(h["uma_ban"])
        code = parsed.get("lineage", {}).get(re.sub(r"\s+", "", h.get("horse_name") or ""))
        if code:
            h = {**h, "lineage_login_code": code}       # 属性列=空のときだけ埋める規則に乗る(手動値は勝つ)
        row = {k: "" for k in HORSE_KEYS}
        row.update({"race_date": date_slash, "race_no": race_no, "baba_code": BABA, "uma_ban": ban})
        ex = ex_by_ban.get(ban)
        if ex:                                              # ⛔first3f・談話・血統コード等を消さない
            for k in HORSE_KEYS:
                if k in ex and ex[k] is not None and k not in ("race_date", "race_no", "baba_code", "uma_ban"):
                    row[k] = ex[k]
        for k in HORSE_KEYS:                                # 公式の値: 結果列は常に上書き・属性列は空のときだけ埋める
            v = h.get(k, "")
            if not v:
                continue
            if k in RESULT_KEYS or not row.get(k):
                row[k] = v
        horses.append(row)
    return {"race_id": f"race_{BABA}_{date_slash}_{race_no}", "race": race,
            "horses": horses, "expected_uma_ban": sorted(x["uma_ban"] for x in horses)}


# ---------------------------------------------------------------- §52続き: 出馬表(nar_runs から構築・スクレイプしない)

def simple_class(name):
    """レース名からの簡易クラス('２歳新馬'→'2歳'・'Ｃ３－１'→'C3' など)。取れなければ空(⛔推定を広げない)"""
    s = unicodedata_normalize(name)
    m = re.search(r"(\d)歳", s)
    if m:
        return f"{m.group(1)}歳"
    m = re.search(r"\b([ABC]\d?)", s)
    if m:
        return m.group(1)
    return ""


def unicodedata_normalize(s):
    import unicodedata
    return unicodedata.normalize("NFKC", str(s or ""))


def build_entry_bundles(nar_base, nar_key, d_iso):
    """今日/明日の高知の出馬表を nar_runs(公式・自動収集済み)から組む。
    ⛔オラクル(2026-08-29・8/1 手動保存出馬表と突合)= 枠/馬名/性齢/斤量/騎手/調教師が完全一致。
    belong は nar の trainer_area(手動は空の日もあった=こちらの方が充実)。
    lineage_login_code はこの段階では空(結果保存時に RaceMarkTable のリンクから補完される)"""
    d = d_iso.replace("-", "/")
    runs = sb_rows(nar_base, nar_key,
                   f"nar_runs?select=race_no,runner_number,gate,horse_name,sex,age,jockey,trainer,carried_weight,trainer_area"
                   f"&track=eq.{urllib.parse.quote('高知')}&race_date=eq.{d_iso}&order=race_no.asc,runner_number.asc&limit=1000")
    if not runs:
        return []
    races = sb_rows(nar_base, nar_key,
                    f"nar_races?select=race_no,race_name,distance_m&track=eq.{urllib.parse.quote('高知')}&race_date=eq.{d_iso}&limit=100")
    meta = {int(r["race_no"]): r for r in races}
    by_no = {}
    for r in runs:
        by_no.setdefault(int(r["race_no"]), []).append(r)
    bundles = []
    for no in sorted(by_no):
        m = meta.get(no, {})
        dist = m.get("distance_m")
        race = {k: "" for k in RACE_KEYS}
        race.update({"race_date": d, "race_no": no, "baba_code": BABA,
                     "race_name": str(m.get("race_name") or ""),
                     "distance": (str(dist) + "ｍ") if dist else "",     # 手動保存の実物 '1300ｍ'(全角)に合わせる
                     "race_class": simple_class(m.get("race_name"))})
        horses = []
        for r in by_no[no]:
            ban = r.get("runner_number")
            if ban is None:
                continue
            row = {k: "" for k in HORSE_KEYS}
            row.update({"race_date": d, "race_no": no, "baba_code": BABA, "uma_ban": int(ban),
                        "waku_ban": str(r.get("gate") or ""),
                        "horse_name": str(r.get("horse_name") or ""),
                        "belong": str(r.get("trainer_area") or ""),
                        "sex_age": f"{r.get('sex') or ''}{r.get('age') or ''}",
                        "kinryo": str(r.get("carried_weight") or ""),
                        "jockey": str(r.get("jockey") or ""),
                        "trainer": str(r.get("trainer") or "")})
            horses.append(row)
        if horses:
            bundles.append({"race_id": f"race_{BABA}_{d}_{no}", "race": race,
                            "horses": horses, "expected_uma_ban": sorted(x["uma_ban"] for x in horses)})
    return bundles


# ---------------------------------------------------------------- §149 D レース名の埋め直し(#551)

def fill_name_bundle(date_slash, race_no, ex_race, ex_horses, meta):
    """§149 D 「結果はあるのにレース名が空」の行を直す bundle。

    ⛔**結果列は 1 つも触らない**= 送るのは既存行をそのまま写したもので、変えるのは
      race_name / distance / race_class の 3 つだけ(しかも**空のときだけ**)。
    ⛔公式(nar_races)に名前が無ければ None を返す= 空のまま残す(推測で埋めない)。
    ⛔既存の馬の行が 1 つも無ければ None(部分行を送ると RPC の upsert が既存値を消しうる)。
    """
    name = str((meta or {}).get("race_name") or "").strip()
    if not name:
        return None
    if str((ex_race or {}).get("race_name") or "").strip():
        return None                                        # もう入っている= 触らない
    race = {k: "" for k in RACE_KEYS}
    race.update({"race_date": date_slash, "race_no": race_no, "baba_code": BABA})
    for k in RACE_KEYS:                                    # 既存の値(計測・メモ・ラップ)はそのまま持ち越す
        if ex_race and k in ex_race and ex_race[k] is not None and k not in ("race_date", "race_no", "baba_code"):
            race[k] = ex_race[k]
    race["race_name"] = name
    dist = (meta or {}).get("distance_m")
    if dist and not str(race.get("distance") or "").strip():
        race["distance"] = str(dist) + "ｍ"                 # 手動保存の実物 '1300ｍ'(全角)に合わせる
    if not str(race.get("race_class") or "").strip():
        race["race_class"] = simple_class(name)
    horses = []
    for ex in sorted(ex_horses or [], key=lambda x: int(x["uma_ban"])):
        row = {k: "" for k in HORSE_KEYS}
        row.update({"race_date": date_slash, "race_no": race_no, "baba_code": BABA, "uma_ban": int(ex["uma_ban"])})
        for k in HORSE_KEYS:                               # ⛔着順・タイム・上がり等は既存のまま写すだけ
            if k in ex and ex[k] is not None and k not in ("race_date", "race_no", "baba_code", "uma_ban"):
                row[k] = ex[k]
        horses.append(row)
    if not horses:
        return None
    return {"race_id": f"race_{BABA}_{date_slash}_{race_no}", "race": race,
            "horses": horses, "expected_uma_ban": sorted(x["uma_ban"] for x in horses)}


def name_meta_of(nar_days):
    """公式(nar_races)の行 → (日 ISO, R) → その行。⛔対象日の検出と**同じ 1 本**の結果を読み直すだけ"""
    meta = {}
    for r in (nar_days or []):
        try:
            meta[(str(r.get("race_date")), int(r.get("race_no")))] = r
        except (TypeError, ValueError):
            continue
    return meta


def fill_missing_names(keiba, meta, out, apply_, post):
    """§149 D 結果のある日でも「レース名が空」の行があれば埋め直す。返り値= 失敗の数。

    2026-09-06 の穴= 出馬表を nar から組んだ時点で nar_races にまだ名前が入っておらず、
    名前・距離・クラスが空のまま保存された。その後は「着順あり → 触らない」で二度と直らず 12 行残った。
    ⛔通信は**空の行が 1 つも無ければ 1 本だけ**(見つかった日だけ既存行を読みに行く)。
    """
    holes = keiba(f"keiba_races?select=race_date,race_no&baba_code=eq.{BABA}"
                  f"&race_date=gte.{urllib.parse.quote(SINCE.replace('-', '/'), safe='')}"
                  "&or=(race_name.is.null,race_name.eq.)&order=race_date.asc,race_no.asc&limit=1000")
    if not holes:
        return 0
    days = {}
    for r in holes:
        days.setdefault(str(r["race_date"]), set()).add(int(r["race_no"]))
    log(f"レース名が空の行: {len(holes)}件 / {len(days)}日 → 埋め直す(⛔結果列は触らない)")
    fails = 0
    for d in sorted(days):
        ex_r = keiba(f"keiba_races?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}")
        ex_h = keiba(f"keiba_horses?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&limit=1000")
        by_no_r = {int(r["race_no"]): r for r in ex_r}
        by_no_h = {}
        for h in ex_h:
            by_no_h.setdefault(int(h["race_no"]), []).append(h)
        for no in sorted(days[d]):
            b = fill_name_bundle(d, no, by_no_r.get(no), by_no_h.get(no, []),
                                 meta.get((d.replace("/", "-"), no)))
            if not b:
                log(f"  {d} {no}R: 公式にまだ名前が無い(か既存の馬の行が無い)→ 空のまま残す")
                continue
            path = out / f"name_{d.replace('/', '')}_{no}.json"
            path.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
            if not apply_:
                log(f"(dry) 名前 {d} {no}R: '{b['race']['race_name']}' {b['race']['distance']} "
                    f"{b['race']['race_class']} {len(b['horses'])}頭 → {path.name}")
            else:
                fails += post(b, f"名前 {d} {no}R")
                time.sleep(0.5)
    return fails


# ---------------------------------------------------------------- 対象日の検出と実行

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", help="オラクル: 保存済みの日(YYYY/MM/DD)をパースして既存行とdiff(書かない)")
    ap.add_argument("--check-entries", help="オラクル: 保存済みの出馬表(YYYY/MM/DD)を nar から組み直してdiff(書かない)")
    ap.add_argument("--out", default=str(HERE.parent / "scratchpad" / "kochi_results"))
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    nar_base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    nar_key = os.environ.get("SUPABASE_ANON_KEY", "") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    token = os.environ.get("KOCHI_WRITE_TOKEN", "")
    if not nar_base or not nar_key:
        log("SUPABASE_URL / SUPABASE_ANON_KEY が要る"); return 2
    if a.apply and not token:
        log("--apply には KOCHI_WRITE_TOKEN が要る(Worker の X-Write-Token)"); return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    def keiba(path):
        return sb_rows(CHIHOU_URL, CHIHOU_ANON, path)

    # ---- オラクル: 手動保存済みの日と突合(書かない) ----
    if a.check:
        d = a.check
        ex_h = keiba(f"keiba_horses?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&order=race_no.asc,uma_ban.asc")
        ex_r = keiba(f"keiba_races?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}")
        by_no_h, by_no_r = {}, {r["race_no"]: r for r in ex_r}
        for h in ex_h:
            by_no_h.setdefault(h["race_no"], []).append(h)
        ng = ok = 0
        for no in sorted(by_no_r):
            parsed = fetch_race(d, no)
            if not parsed:
                log(f"⚠ {d} {no}R: 公式ページに結果表なし"); ng += 1; continue
            b = build_bundle(d, no, parsed, by_no_r.get(no), by_no_h.get(no, []))
            for row in b["horses"]:
                ex = next((x for x in by_no_h.get(no, []) if int(x["uma_ban"]) == row["uma_ban"]), None)
                if not ex:
                    log(f"  NG {no}R 馬番{row['uma_ban']}: 既存行なし"); ng += 1; continue
                for k in sorted(RESULT_KEYS | {"waku_ban", "horse_name", "jockey"}):
                    a_, b_ = str(row.get(k) or ""), str(ex.get(k) or "")
                    if a_ != b_:
                        log(f"  NG {no}R 馬番{row['uma_ban']} {k}: 公式パース'{a_}' != 保存済み'{b_}'"); ng += 1
                    else:
                        ok += 1
            time.sleep(1.0)
        log(f"オラクル {d}: 一致 {ok} / 不一致 {ng}")
        return 0 if ng == 0 else 1

    # ---- オラクル(出馬表): 手動保存済みの日と nar 由来の構築を突合(書かない) ----
    if a.check_entries:
        d = a.check_entries
        bundles = build_entry_bundles(nar_base, nar_key, d.replace("/", "-"))
        ex_h = keiba(f"keiba_horses?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&order=race_no.asc,uma_ban.asc&limit=1000")
        ng = ok = gap = 0
        for b in bundles:
            no = b["race"]["race_no"]
            for row in b["horses"]:
                ex = next((x for x in ex_h if x["race_no"] == no and int(x["uma_ban"]) == row["uma_ban"]), None)
                if not ex:
                    log(f"  NG {no}R 馬番{row['uma_ban']}: 手動側に行なし"); ng += 1; continue
                for k in ("waku_ban", "horse_name", "sex_age", "kinryo", "jockey", "trainer"):
                    a_, b_ = str(row.get(k) or ""), str(ex.get(k) or "")
                    if k == "kinryo" and not a_ and b_:
                        # ⚠nar の carried_weight は減量騎手等で散発的に null(8/1 実測21頭)。
                        # kinryo は属性列=結果保存(RaceMarkTable の負担列)が「空のときだけ埋める」で補完する
                        gap += 1
                    elif a_.replace(" ", "") != b_.replace(" ", ""):  # 性齢の「牝 3」/「牝3」ゆらぎは同一視
                        log(f"  NG {no}R 馬番{row['uma_ban']} {k}: nar構築'{a_}' != 手動'{b_}'"); ng += 1
                    else:
                        ok += 1
        log(f"出馬表オラクル {d}: 一致 {ok} / 不一致 {ng} / nar欠測(結果保存で補完) {gap}(belong は nar 側が充実のため比較外)")
        return 0 if ng == 0 else 1

    def post_bundle(b, label):
        req = urllib.request.Request(f"{WORKER_URL}/rpc/save-keiba-race-bundle", method="POST",
                                     data=json.dumps(b, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Write-Token": token,
                                              "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                st = r.status
        except urllib.error.HTTPError as e:
            st = e.code
            log(f"  保存失敗 {label}: HTTP {st} {e.read()[:200]}")
        if st in (200, 201):
            log(f"保存 {label}: {len(b['horses'])}頭 OK")
            return 0
        return 1

    fails = 0

    # ---- 出馬表: 今日+明日の高知開催で keiba に行の無い日を nar から構築(§52続き・2026-08-29) ----
    today_d = dt.datetime.now(JST).date()
    for d_iso in (str(today_d), str(today_d + dt.timedelta(days=1))):
        d = d_iso.replace("-", "/")
        got = keiba(f"keiba_horses?select=uma_ban&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&limit=1")
        if got:
            continue                                    # 出馬表(または結果)が既にある日は触らない
        bundles = build_entry_bundles(nar_base, nar_key, d_iso)
        if not bundles:
            continue                                    # 高知の開催なし
        log(f"出馬表 {d}: {len(bundles)}R を nar から構築")
        for b in bundles:
            path = out / f"entries_{d.replace('/', '')}_{b['race']['race_no']}.json"
            path.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
            if not a.apply:
                log(f"(dry) 出馬表 {d} {b['race']['race_no']}R: {len(b['horses'])}頭 → {path.name}")
            else:
                fails += post_bundle(b, f"出馬表 {d} {b['race']['race_no']}R")
                time.sleep(0.5)

    # ---- 対象日の検出: 公式開催日(nar) ∩ 結果ゼロ(keiba) ----
    # §149 D レース名・距離も**同じ 1 本**で受け取る(⛔列を足すだけ= 通信は増えない)
    nar_days = sb_rows(nar_base, nar_key,
                       f"nar_races?select=race_date,race_no,race_name,distance_m,post_time&track=eq.{urllib.parse.quote('高知')}&race_date=gte.{SINCE}&order=race_date.asc&limit=1000")
    now = dt.datetime.now(JST)
    today = now.date().isoformat()
    # 当日は**最終レースの発走から 30 分たつまで**対象にしない(2026-09-12: 開催日の朝から 15 時まで
    #   便ごとに「結果表なし」で exit 1 になり、後ろの段(馬場差・傾向・コース別)が全部飛んでいた)。
    #   発走時刻の無い行は「まだ」とみなす(⛔推定で早めない)
    def _done(r):
        if r["race_date"] < today:
            return True
        if r["race_date"] > today:
            return False
        pt = str(r.get("post_time") or "")[:5]
        if not re.fullmatch(r"\d{2}:\d{2}", pt):
            return False
        h, m = int(pt[:2]), int(pt[3:])
        return now >= now.replace(hour=h, minute=m, second=0, microsecond=0) + dt.timedelta(minutes=30)
    pending_today = [r for r in nar_days if r["race_date"] == today and not _done(r)]
    days = {}
    for r in nar_days:
        if r["race_date"] < today or (r["race_date"] == today and not pending_today):
            days.setdefault(r["race_date"], set()).add(int(r["race_no"]))
    if pending_today:
        log(f"{today.replace('-', '/')}: 発走前(または発走 30 分以内)が {len(pending_today)}R → 今日はまだ見ない")
    targets = []
    for d_iso in sorted(days):
        d = d_iso.replace("-", "/")
        got = keiba(f"keiba_horses?select=race_no,chakujun&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&limit=1000")
        filled = sum(1 for x in got if str(x.get("chakujun") or "").strip())
        if filled == 0:
            targets.append((d, sorted(days[d_iso]), len(got)))
        else:
            log(f"{d}: 着順あり {filled}行 → 結果は触らない")
    log(f"対象日 {len(targets)}日: " + " ".join(t[0] for t in targets))

    # §149 D(#551) 結果のある日でも「レース名が空」の行だけは埋め直す。⛔結果列は触らない・
    #   ⛔対象日があってもなくても必ず通す(2026-09-06 の 12 行は「着順あり→触らない」で残ったため)
    fails += fill_missing_names(keiba, name_meta_of(nar_days), out, a.apply, post_bundle)

    if not targets:
        return 1 if fails else 0

    for d, race_nos, entry_rows in targets:
        ex_h = keiba(f"keiba_horses?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&limit=1000")
        ex_r = keiba(f"keiba_races?select=*&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}")
        by_no_h, by_no_r = {}, {r["race_no"]: r for r in ex_r}
        for h in ex_h:
            by_no_h.setdefault(h["race_no"], []).append(h)
        for no in race_nos:
            parsed = fetch_race(d, no)
            if not parsed:
                log(f"⚠ {d} {no}R: 結果表なし(未確定/中止?)→この日は残す"); fails += 1; continue
            b = build_bundle(d, no, parsed, by_no_r.get(no), by_no_h.get(no, []))
            path = out / f"bundle_{d.replace('/', '')}_{no}.json"
            path.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
            if not a.apply:
                log(f"(dry) {d} {no}R: {len(b['horses'])}頭 → {path.name}")
            else:
                req = urllib.request.Request(f"{WORKER_URL}/rpc/save-keiba-race-bundle", method="POST",
                                             data=json.dumps(b, ensure_ascii=False).encode("utf-8"),
                                             headers={"Content-Type": "application/json", "X-Write-Token": token,
                                                      "User-Agent": UA})
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        st = r.status
                except urllib.error.HTTPError as e:
                    st = e.code
                    log(f"  保存失敗 {d} {no}R: HTTP {st} {e.read()[:200]}")
                if st in (200, 201):
                    log(f"保存 {d} {no}R: {len(b['horses'])}頭 OK")
                else:
                    fails += 1
            time.sleep(1.2)                                 # 公式・Workerとも礼儀の間隔
        if a.apply:                                         # read-back 検算(この日の着順が埋まったか)
            back = keiba(f"keiba_horses?select=chakujun&baba_code=eq.{BABA}&race_date=eq.{urllib.parse.quote(d, safe='')}&limit=1000")
            filled = sum(1 for x in back if str(x.get("chakujun") or "").strip())
            log(f"read-back {d}: 着順あり {filled}/{len(back)}行")
            if not filled:
                fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

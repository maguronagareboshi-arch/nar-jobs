# -*- coding: utf-8 -*-
"""本体 cloud: 馬ごとの「格組」と「収得賞金」(全15場・公式)を keiba.go.jp から取る(DESIGN §79 P1・§38 1-B 第二弾)。

2つの表を育てる(どちらも insert/upsert だけ・冪等・再開可能):
  nar_horse_codes  馬名(+生年)→ 血統登録番号(11桁)。出典= 公式の出馬表 TodayRaceInfo/DebaTable(1レース1本・全出走馬のリンク)
  nar_horse_prize  番号 → 走歴(格組・収得賞金・着順…)と 地方収得賞金の合計。出典= DataRoom/HorseMarkInfo(1頭1本)

  py -3.12 -X utf8 cloud/horse_ledger.py --env pipeline/.env.nar                # ドライラン(今日+明日の出馬表・書かない)
  py -3.12 -X utf8 cloud/horse_ledger.py --env pipeline/.env.nar --apply        # 実弾(日次と同じ)
  py -3.12 -X utf8 cloud/horse_ledger.py --env pipeline/.env.nar --apply --from 2026-04-01 --to 2026-09-02 --max-horses 2000
                                                                               # 過去分の遡り(番号→馬ページ。何度でも再開できる)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔ 実地で分かったこと(2026-09-03):
 1. **血統登録番号は 11 桁**(調査書 §3.1 の「10桁」は誤り。10桁で引くと「ご指定の馬の情報がありません」)。
 2. HorseMarkInfo の走歴の**収得賞金(地方の走だけ)を足すと RaceHorseInfo の「地方収得賞金」と一致**(メロパール 43走 7,470,000)。
    → 合計のために 2本目(RaceHorseInfo)は引かない。生年月日は nar_runs.birth_date(公式CSV)にある。
 3. 公式の出馬表・成績は**約5か月で消える**(2025-09-05 高知 1R は空 7.7KB)。番号の遡りはそこまで。
    馬ページ自体は全走歴を返すので、番号さえ取れれば 1 年より前の走も入る。
 4. JRA の走は 競馬場 が「Ｊ札幌」のように「Ｊ」で始まる。地方収得の合計からは除く(中央収得は別勘定)。
 5. 着順の欄は 取消/除外/中止 などの字が入る。数字でなければ fin=null・note にその字。
 6. 同じ馬ページに同じ日・同じ場・同じRは1行しか無い=走の鍵は (d,tr,no)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
from load_nar_official import load_env, upsert            # noqa: E402
from odds import BABA, JST, http_get, log, _text          # noqa: E402

DEBA_URL = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable"
HORSE_URL = "https://www.keiba.go.jp/KeibaWeb/DataRoom/HorseMarkInfo"
SLEEP = 1.0            # 出馬表(1レース1本)
SLEEP_HORSE = 0.5      # 馬ページ(1頭1本・軽い静的ページ。日次 600 頭で 5 分= Actions の分予算を見て決めた)
T_CODES = "nar_horse_codes"
T_PRIZE = "nar_horse_prize"
CODE_RE = re.compile(r'HorseMarkInfo\?k_lineageLoginCode=(\d{11})"[^>]*>\s*([^<]+?)\s*<')


# ---------------------------------------------------------------- 取得と解析

def deba_codes(date, race_no, baba):
    """出馬表 1 ページ → [(code, 馬名)]。ページが無い(5か月超・未発表)なら []。"""
    url = f"{DEBA_URL}?k_raceDate={date:%Y/%m/%d}&k_raceNo={race_no}&k_babaCode={baba}"
    page = http_get(url).decode("utf-8", "replace")
    seen, out = set(), []
    for code, name in CODE_RE.findall(page):
        if code in seen:
            continue
        seen.add(code)
        out.append((code, _text(name)))
    return out


def _int(s):
    s = (s or "").replace(",", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def _float(s):
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_horse(page):
    """馬ページ → {name, sex, age, status, runs:[…新しい順], local_prize} / 無ければ None。"""
    if "ご指定の馬の情報がありません" in page:
        return None
    m = re.search(r'class="odd_title">(.*?)</h4>', page, re.S)
    name = _text(m.group(1)) if m else None
    sex = re.search(r'class="sex[^"]*">(.*?)</span>', page, re.S)
    age = re.search(r'class="age[^"]*">(.*?)</span>', page, re.S)
    status = re.search(r"</span>\s*</div>\s*</li>\s*<li>\s*<div>\s*([^<\s][^<]*?)\s*</div>", page, re.S)
    tbl = re.search(r'<table class="HorseMarkInfo_table">(.*?)</table>', page, re.S)
    runs = []
    if tbl:
        body = re.search(r"<tbody[^>]*>(.*?)</tbody>", tbl.group(1), re.S)
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S):
            tds = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) < 23:
                continue
            (d, tr_, no, rname, cls, dist, weather, going, night, head, waku, uma, ninki, fin,
             tm, margin, l3f, bw, jk, cw, trainer, prize, winner) = tds[:23]
            try:
                dd = dt.datetime.strptime(d, "%Y/%m/%d").date().isoformat()
            except ValueError:
                continue
            f = _int(fin)
            runs.append({
                "d": dd, "tr": tr_, "no": _int(no), "name": rname, "cls": cls or None,
                "dist": _int(dist), "wx": weather or None, "go": going or None, "nt": bool(night),
                "head": _int(head), "waku": _int(waku), "uma": _int(uma), "pop": _int(ninki),
                "fin": f, "note": (None if f is not None else (fin or None)),
                "time": tm or None, "mg": margin or None, "l3f": _float(l3f), "bw": _int(bw),
                "jk": jk or None, "cw": _float(cw), "trn": trainer or None,
                "prize": _int(prize) or 0, "win": winner or None,
                "jra": tr_.startswith("Ｊ") or tr_.startswith("J"),
            })
    local = sum(r["prize"] for r in runs if not r["jra"])
    return {"name": name, "sex": _text(sex.group(1)) if sex else None, "age": _int(age.group(1)) if age else None,
            "status": _text(status.group(1)) if status else None, "runs": runs, "local_prize": local}


# ---------------------------------------------------------------- DB

def sb_all(url, key, path, page=1000):
    """PostgREST を 1000 行ずつ全部読む(Range ヘッダ)。"""
    out, lo = [], 0
    while True:
        raw = http_get(f"{url}/rest/v1/{path}", {"apikey": key, "Authorization": f"Bearer {key}",
                                                  "Accept": "application/json", "Range": f"{lo}-{lo + page - 1}"})
        rows = json.loads(raw.decode("utf-8"))
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--from", dest="d_from", help="遡り: この日から(既定=今日)")
    ap.add_argument("--to", dest="d_to", help="遡り: この日まで(既定=明日)")
    ap.add_argument("--max-races", type=int, default=400, help="出馬表を引く上限(1本 1 秒)")
    ap.add_argument("--max-horses", type=int, default=1500, help="馬ページを引く上限(1本 1 秒)")
    ap.add_argument("--stale-days", type=int, default=3, help="日次: 直近この日数に走った馬を更新候補にする")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = (os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    today = dt.datetime.now(JST).date()
    d_from = dt.date.fromisoformat(args.d_from) if args.d_from else today
    d_to = dt.date.fromisoformat(args.d_to) if args.d_to else today + dt.timedelta(days=1)
    lo = min(d_from, today - dt.timedelta(days=args.stale_days))
    try:
        races = sb_all(url, key, f"nar_races?select=track,race_date,race_no&race_date=gte.{d_from}&race_date=lte.{d_to}"
                                 "&order=race_date.asc,track.asc,race_no.asc")
        runs = sb_all(url, key, f"nar_runs?select=track,race_date,race_no,horse_name,birth_date,finish,finish_note"
                                f"&race_date=gte.{lo}&race_date=lte.{d_to}&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")   # #468 一意な並び
        codes = sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date")
        ledger = sb_all(url, key, f"{T_PRIZE}?select=code,last_run,asof")
    except Exception as e:
        log(f"DB の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2
    log(f"{d_from}〜{d_to}: レース {len(races)} / 出走 {len(runs)}(候補窓 {lo}〜) / 番号 {len(codes)} / 台帳 {len(ledger)}")

    # ---- ① 番号: 出走馬の中で番号が無い馬がいるレースだけ出馬表を引く
    code_by_name = {}
    for c in codes:
        code_by_name.setdefault(c["horse_name"], []).append(c)
    by_race = {}
    for r in runs:
        by_race.setdefault((r["track"], r["race_date"], int(r["race_no"])), []).append(r)
    need_races = []
    for r in races:
        k = (r["track"], r["race_date"], int(r["race_no"]))
        ents = by_race.get(k, [])
        if not ents:
            continue
        if any(not code_by_name.get(e["horse_name"]) for e in ents):
            need_races.append(k)
    need_races = need_races[:args.max_races]
    log(f"① 出馬表を引くレース {len(need_races)}")
    new_codes, bad = [], 0
    for i, (track, date, no) in enumerate(need_races):
        baba = BABA.get(track)
        if not baba:
            continue
        if i:
            time.sleep(SLEEP)
        try:
            pairs = deba_codes(dt.date.fromisoformat(date), no, baba)
        except Exception as e:
            bad += 1
            log(f"  取得失敗 {track} {date} {no}R: {type(e).__name__}: {str(e)[:100]}")
            continue
        births = {e["horse_name"]: e.get("birth_date") for e in by_race[(track, date, no)]}
        for code, name in pairs:
            if any(c["code"] == code for c in code_by_name.get(name, [])):
                continue
            row = {"code": code, "horse_name": name, "birth_date": births.get(name), "seen_track": track, "seen_date": date}
            new_codes.append(row)
            code_by_name.setdefault(name, []).append(row)
    log(f"① 新しい番号 {len(new_codes)}(失敗 {bad})")
    if new_codes and args.apply:
        st, msg = upsert(url, key, T_CODES, "code", new_codes)
        if st >= 300 or st == 0:
            log(f"投入失敗 {T_CODES} status={st} {msg}")
            return 1
        log(f"投入 {len(new_codes)} 行 -> {T_CODES}")

    # ---- ② 馬ページ: 窓の中で走った(走る)馬のうち、台帳が無いか、台帳の最終走より新しい走が nar_runs にある馬
    last_by_name = {}
    for r in runs:
        # ⚠結果(着順か取消等の字)が入った走だけ数える= 出馬表の段階の行を「走った」と見なすと、
        #   公式の馬ページにまだ無い走を待って1日じゅう引き直してしまう
        if r["race_date"] <= today.isoformat() and (r.get("finish") is not None or r.get("finish_note")):
            n = r["horse_name"]
            if r["race_date"] > last_by_name.get(n, ""):
                last_by_name[n] = r["race_date"]
    led = {x["code"]: x for x in ledger}
    targets, seen_t = [], set()
    for r in runs:
        for c in code_by_name.get(r["horse_name"], []):
            code = c["code"]
            L = led.get(code)
            last = last_by_name.get(r["horse_name"], "")
            if (L is None or (L.get("last_run") or "") < last) and code not in seen_t:
                seen_t.add(code)
                targets.append(code)
    targets = targets[:args.max_horses]
    log(f"② 馬ページを引く馬 {len(targets)}")
    rows, miss, bad = [], 0, 0
    for i, code in enumerate(targets):
        if i:
            time.sleep(SLEEP_HORSE)
        try:
            page = http_get(f"{HORSE_URL}?k_lineageLoginCode={code}").decode("utf-8", "replace")
        except Exception as e:
            bad += 1
            log(f"  取得失敗 {code}: {type(e).__name__}: {str(e)[:100]}")
            continue
        h = parse_horse(page)
        if h is None or not h["name"]:
            miss += 1
            log(f"  情報なし {code}")
            continue
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        rows.append({"code": code, "horse_name": h["name"], "sex": h["sex"], "age": h["age"], "status": h["status"],
                     "local_prize": h["local_prize"], "runs": h["runs"], "n_runs": len(h["runs"]),
                     "last_run": h["runs"][0]["d"] if h["runs"] else None,
                     "last_cls": next((r["cls"] for r in h["runs"] if r["cls"] and not r["jra"]), None),
                     "asof": now, "updated_at": now})
        if len(rows) % 200 == 0 and args.apply:
            st, msg = upsert(url, key, T_PRIZE, "code", rows)
            if st >= 300 or st == 0:
                log(f"投入失敗 {T_PRIZE} status={st} {msg}")
                return 1
            log(f"  投入 {len(rows)} 行 -> {T_PRIZE}(途中)")
            rows = []
    log(f"② 取得 {len(targets) - miss - bad} / 情報なし {miss} / 失敗 {bad}")
    if rows:
        log(f"  例: {rows[0]['horse_name']} 走 {rows[0]['n_runs']} 地方収得 {rows[0]['local_prize']:,} 直近の格組 {rows[0]['last_cls']}")
        if args.apply:
            st, msg = upsert(url, key, T_PRIZE, "code", rows)
            if st >= 300 or st == 0:
                log(f"投入失敗 {T_PRIZE} status={st} {msg}")
                return 1
            log(f"投入 {len(rows)} 行 -> {T_PRIZE}")
    if not args.apply:
        log("dry-run: 書かない")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)

# -*- coding: utf-8 -*-
"""統合ビューア cloud: 当日の単勝・複勝オッズを公式サイトから取り nar_race_odds へ入れる(DESIGN §13.2C)。

公式 TodayRaceInfo の単複ページ(1レース1ページ)を、発走が近いレースだけ取りに行く。
1レース1行・最新だけ(履歴は持たない)。「（最終）」と書かれたレースは以後取りに行かない。
  python cloud/odds.py                  # 今日(JST)の「発走 80 分前〜発走 10 分後」のレース
  python cloud/odds.py --dry-run        # 取得と解析だけ(投入しない)
  python cloud/odds.py --env pipeline/.env.nar          # ローカル試験(人間が実行)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(GitHub Secrets)。読み取りだけの試験は --url/--key で anon も可
終了コード: 0 正常(対象なし・一部の取得失敗も 0=次の実行に任せる)/ 1 投入失敗 / 2 前提の読み取りに失敗
"""
import argparse
import datetime as dt
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env, upsert  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
ODDS_URL = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/OddsTanFuku"
# 連絡先付きの UA(公式サイトへの負荷を名乗る。DESIGN §13.5)
UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"
TIMEOUT = 20
SLEEP = 1.0            # 1リクエストの間隔(秒)
TABLE = "nar_race_odds"
CONFLICT = "track,race_date,race_no"

# 公式表記の場名 → k_babaCode(DESIGN §13.1。競馬ブックの場コードとは別物)
BABA = {
    "帯広ば": "03", "盛岡": "10", "水沢": "11", "浦和": "18", "船橋": "19", "大井": "20",
    "川崎": "21", "金沢": "22", "笠松": "23", "名古屋": "24", "園田": "27", "姫路": "28",
    "高知": "31", "佐賀": "32", "門別": "36",
}


def log(msg):
    print(f"[{dt.datetime.now(JST):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 取得

def http_get(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sb_get(base, key, path):
    """PostgREST の GET(読み取りだけ)。"""
    raw = http_get(f"{base}/rest/v1/{path}", {"apikey": key, "Authorization": f"Bearer {key}",
                                              "Accept": "application/json"})
    return json.loads(raw.decode("utf-8"))


def odds_url(date, race_no, baba):
    q = urllib.parse.urlencode({"k_raceDate": date.strftime("%Y/%m/%d"), "k_raceNo": race_no, "k_babaCode": baba})
    return f"{ODDS_URL}?{q}"


# ---------------------------------------------------------------- 解析(標準ライブラリだけ)

def _text(fragment):
    """タグを落として1行の文字列に。"""
    s = re.sub(r"<[^>]+>", " ", fragment)
    s = html_mod.unescape(s).replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def _num(text):
    """'6.2' → 6.2 / '1.7-' → 1.7 / '取消'・''・'---' → None。"""
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    if not m:
        return None
    # 「発売前」等の文字が数字と混ざっている行は採らない(全角の注記は _text で残る)
    return float(m.group(0))


def header_cols(thead):
    """見出しから列位置を決める(colspan を数える)。取れない見出しは既定値。"""
    cols = {"umaban": None, "win": None, "place": None, "place_span": 1}
    idx = 0
    for m in re.finditer(r"<th([^>]*)>(.*?)</th>", thead, re.S):
        attrs, label = m.group(1), _text(m.group(2))
        sp = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs)
        span = int(sp.group(1)) if sp else 1
        if "馬番" in label and cols["umaban"] is None:
            cols["umaban"] = idx
        elif "単勝" in label and cols["win"] is None:
            cols["win"] = idx
        elif "複勝" in label and cols["place"] is None:
            cols["place"], cols["place_span"] = idx, span
        idx += span
    if cols["umaban"] is None or cols["win"] is None:      # 見出しが変わったときの保険(2026-08-23 の並び)
        cols = {"umaban": 1, "win": 3, "place": 4, "place_span": 2}
    if cols["place"] is None:
        cols["place"], cols["place_span"] = cols["win"] + 1, 2
    return cols


def parse_odds(page):
    """単複ページ → (runners, is_final)。表が無ければ (None, False)。

    runners = [{"n":馬番, "w":単勝, "pl":複勝の下限, "ph":複勝の上限}]。数値でない(取消・発売前)は None。
    """
    m = re.search(r'<table[^>]*class="[^"]*odd_popular_table_02[^"]*"[^>]*>(.*?)</table>', page, re.S)
    if not m:
        return None, False
    table = m.group(1)
    title = re.search(r'class="odd_title"[^>]*>(.*?)</h4>', page, re.S)
    is_final = "最終" in _text(title.group(1)) if title else False
    thead = re.search(r"<thead[^>]*>(.*?)</thead>", table, re.S)
    cols = header_cols(thead.group(1) if thead else "")
    body = re.search(r"<tbody[^>]*>(.*?)</tbody>", table, re.S)
    need = max(cols["umaban"], cols["win"], cols["place"] + cols["place_span"] - 1)
    runners = []
    seen = set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else table, re.S):
        tds = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) <= need:
            continue
        n = _num(tds[cols["umaban"]])
        if n is None or int(n) in seen:
            continue
        seen.add(int(n))
        pi = cols["place"]
        if cols["place_span"] >= 2:
            pl, ph = _num(tds[pi]), _num(tds[pi + 1])
        else:                                              # 1セルに '1.7- 2.4' が入る形も読めるように
            parts = re.split(r"[-〜~]", tds[pi])
            pl = _num(parts[0])
            ph = _num(parts[1]) if len(parts) > 1 else None
        runners.append({"n": int(n), "w": _num(tds[cols["win"]]), "pl": pl, "ph": ph})
    # 馬番が 1 から順に並ばない = 列がずれている(rowspan 等)。誤った馬番で入れないよう捨てる
    nums = [x["n"] for x in runners]
    if nums != sorted(nums) or nums != list(range(1, len(nums) + 1)):
        return None, is_final
    return (runners or None), is_final


# ---------------------------------------------------------------- 対象レースの選び方

def post_minutes(post_time):
    """'1420' → 860(JST の分)。読めなければ None。"""
    m = re.fullmatch(r"(\d{2})(\d{2})", str(post_time or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def pick_targets(races, finals, now_min, before, after, limit):
    """発走 before 分前〜 after 分後のレース(最終オッズ済みは除く)。発走が近い順。"""
    done = {(r.get("track"), int(r.get("race_no"))) for r in finals if r.get("is_final")}
    out = []
    for r in races:
        track, no = r.get("track"), r.get("race_no")
        baba = BABA.get(track)
        pm = post_minutes(r.get("post_time"))
        if baba is None or no is None or pm is None:
            continue
        if (track, int(no)) in done:
            continue
        delta = pm - now_min                                # 正=これから発走・負=発走済み
        if delta > before or delta < -after:
            continue
        out.append({"track": track, "race_no": int(no), "baba": baba, "post": pm, "delta": delta})
    out.sort(key=lambda x: (x["post"], x["track"]))
    return out[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="取得・解析だけして投入しない")
    ap.add_argument("--env", help="ローカル試験用 .env(既定は環境変数)")
    ap.add_argument("--url", help="読み取り先の上書き(試験用)")
    ap.add_argument("--key", help="APIキーの上書き(読み取りだけの試験なら anon でよい)")
    ap.add_argument("--date", help="対象日 YYYY-MM-DD(既定=今日。公式は当日分しか返さない)")
    ap.add_argument("--before", type=int, default=80, help="発走の何分前から取るか(既定80)")
    ap.add_argument("--after", type=int, default=10, help="発走の何分後まで取るか(既定10)")
    ap.add_argument("--limit", type=int, default=20, help="1回の実行で取るレース数の上限(既定20)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = (args.url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = args.key or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    now = dt.datetime.now(JST)
    date = dt.date.fromisoformat(args.date) if args.date else now.date()
    now_min = now.hour * 60 + now.minute
    try:
        races = sb_get(url, key, f"nar_races?select=track,race_no,post_time&race_date=eq.{date.isoformat()}"
                                 "&order=track.asc,race_no.asc")
        finals = sb_get(url, key, f"{TABLE}?select=track,race_no,is_final,history&race_date=eq.{date.isoformat()}")
    except Exception as e:
        log(f"nar_races / {TABLE} の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2

    # §28.2 レースごとの履歴(これまでのスナップショット)。上書き upsert なので追記して持ち回る
    hist_by = {(r.get("track"), int(r.get("race_no"))): (r.get("history") or [])
               for r in finals if r.get("race_no") is not None}

    targets = pick_targets(races, finals, now_min, args.before, args.after, args.limit)
    log(f"{date} 当日のレース {len(races)} / 対象 {len(targets)}(発走 {args.before} 分前〜{args.after} 分後・"
        f"最終オッズ済み {sum(1 for r in finals if r.get('is_final'))} は除く)")
    if not targets:
        return 0

    rows, ok, ng, empty = [], 0, 0, 0
    for i, t in enumerate(targets):
        if i:
            time.sleep(SLEEP)
        u = odds_url(date, t["race_no"], t["baba"])
        try:
            page = http_get(u).decode("utf-8", "replace")
        except Exception as e:
            ng += 1
            log(f"  取得失敗 {t['track']} {t['race_no']}R: {type(e).__name__}: {str(e)[:120]}")
            continue
        runners, is_final = parse_odds(page)
        if not runners or all(x["w"] is None for x in runners):
            empty += 1
            log(f"  発売前/表なし {t['track']} {t['race_no']}R(発走まで {t['delta']} 分)")
            continue
        ok += 1
        # §28.2 履歴に今回の単勝を追記(複勝は幅があってかさばるので持たない)。
        # 1エントリ = {"t": "HH:MM"(JST), "f": 最終なら1, "w": {"馬番": 単勝}}。最大12件(超えたら2番目=中間を捨てる。最初と直近は残す)
        hist = list(hist_by.get((t["track"], t["race_no"]), []))
        entry = {"t": dt.datetime.now(JST).strftime("%H:%M"),
                 "w": {str(x["n"]): x["w"] for x in runners if x["w"] is not None}}
        if is_final:
            entry["f"] = 1
        hist.append(entry)
        while len(hist) > 12:
            hist.pop(1)
        rows.append({
            "track": t["track"], "race_date": date.isoformat(), "race_no": t["race_no"],
            "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "is_final": is_final, "runners": runners, "history": hist,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        low = min((x["w"] for x in runners if x["w"] is not None), default=None)
        log(f"  {t['track']} {t['race_no']}R {len(runners)}頭 単勝最低 {low}{' (最終)' if is_final else ''}")

    finalized = sum(1 for r in rows if r["is_final"])
    log(f"取得 成功 {ok} / 失敗 {ng} / 発売前 {empty} / 最終化 {finalized}")
    if args.dry_run:
        log("dry-run: 投入しない")
        return 0
    if not rows:
        return 0
    status, msg = upsert(url, key, TABLE, CONFLICT, rows)
    if status >= 300 or status == 0:
        log(f"投入失敗 status={status} {msg}")
        return 1
    log(f"投入 {len(rows)} 行 -> {TABLE}")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)

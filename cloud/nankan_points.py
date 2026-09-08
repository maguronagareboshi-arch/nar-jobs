# -*- coding: utf-8 -*-
"""統合ビューア cloud: 南関東4場(大井・船橋・川崎・浦和)の「格」「格付ポイント」を nankankeiba.com の馬ページから取る(DESIGN §38 1-C)。

大井だけだった 他場\\scraper\\fetch_nankan_points.py(PC の日次・chihou_meta ooi_points)の置き換え。PC を閉じていても回る。
  表= nar_nankan_points(鍵= nankankeiba の馬コード)。画面は 1レースの出走馬ぶんを馬名で引く(data.js getNankanPoints)。

  python cloud/nankan_points.py --env pipeline/.env.nar                 # ドライラン(直近2日に走った馬・書かない)
  python cloud/nankan_points.py --apply --days 2 --max-horses 400      # 日次(朝の便)
  python cloud/nankan_points.py --runs-csv runs.csv --state-json st.json --days 92 --max-horses 5000
                                                                       # 遡り(DB を読まずに CSV から・結果は JSON に)
  python cloud/nankan_points.py --apply --load-json st.json            # JSON の中身を表へ入れるだけ(通信は DB だけ)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

流れ(横着せず、走った馬だけ取り直す= #155 の教訓):
  ① nar_runs(窓= 直近 --days 日)から 場×日×R と出走馬名を集める
  ② 馬名がまだ表に無い馬がいるレースだけ 出馬表 uma_shosai/{YYYYMMDD+場2桁+回2+日2+R2}.do を引き、馬コードを集める
     (回・日は /calendar/000000.do(直近数か月ぶん・日々動くので毎回読む)と過去月 /calendar/YYYYMM.do から。⛔当月以降の月別URLは 404 #157)
  ③ 馬ページ uma_info/{code}.do → 馬名・格・格付ポイント・「◯日現在」・生年月日。取り直しの規則=
     きょう既に読んだ馬は飛ばす / asof(主催者の基準日)が最終出走日以上なら飛ばす / それ以外(走ったのに反映前)は読む
  ⛔ 抹消馬は格・ポイント欄ごと消える= kaku/points null で保存(解析不能が正常・出馬表に載らないので実害なし)
  ⛔ 「格付ポイント」は主催者の用語。画面でも「収得賞金」とは呼ばない
"""
import argparse
import csv
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
from odds import JST, log                                  # noqa: E402

import urllib.request

BASE = "https://www.nankankeiba.com"
# nankankeiba の場コードは公式(keiba.go.jp)の babaCode と同じ(/calendar/000000.do で 18/19/20/21 を実測 2026-09-04)
BA = {"浦和": "18", "船橋": "19", "大井": "20", "川崎": "21"}
BA_NAME = {v: k for k, v in BA.items()}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SLEEP = 1.5           # 1リクエストの間隔(秒)。他場版は 1.8。日次 ~150 頭で 4 分弱
TABLE = "nar_nankan_points"
ZEN2HAN = str.maketrans("ＡＢＣ１２３", "ABC123")

_last = [0.0]


def get(url):
    gap = time.monotonic() - _last[0]
    if gap < SLEEP:
        time.sleep(SLEEP - gap)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    _last[0] = time.monotonic()
    return raw.decode("cp932", errors="replace")


# ---------------------------------------------------------------- 主催者ページの読み取り

def calendar_map(months):
    """{(場コード, 'YYYY-MM-DD'): '回日(4桁)'}"""
    out = {}

    def scan(h):
        for m in re.finditer(r"/(?:program|race_trend)/(\d{8})(1[89]|2[01])(\d{4})", h):
            d = m.group(1)
            out[(m.group(2), f"{d[0:4]}-{d[4:6]}-{d[6:8]}")] = m.group(3)

    try:
        scan(get(f"{BASE}/calendar/000000.do"))
    except Exception as e:
        log(f"calendar 000000: ERR {type(e).__name__}: {str(e)[:100]}")
    this_ym = dt.datetime.now(JST).strftime("%Y%m")
    for ym in sorted(months):
        if ym >= this_ym:
            continue                                   # ⛔当月以降の月別URLは 404(#157)
        try:
            scan(get(f"{BASE}/calendar/{ym}.do"))
        except Exception as e:
            # ⚠2026-09-04 実測: 過去月(202606/202608)も 404 だった=月別URLは当てにしない。
            #   000000.do が持つ範囲(当月の前後 約2か月)より前の開催日は「回日が分からない」として飛ばす
            log(f"calendar {ym}: 読めない({type(e).__name__})=000000.do の範囲だけで進む")
    return out


def shosai_codes(rid):
    """出馬表 1 ページ → その場・日・R の馬コード集合(小さいページ=存在しないレースなら空)。"""
    h = get(f"{BASE}/uma_shosai/{rid}.do")
    if len(h) < 100000:
        return set()
    return set(re.findall(r"/uma_info/(\d+)\.do", h))


def parse_uma(h):
    t = re.sub(r"<script.*?</script>", "", h, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t)
    # 「競走馬詳細データ 2026年7月4日現在 ブラッドライン （サラ）…格 Ｃ１…格付ポイント 1,452」
    name_m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日現在\s*(?:&nbsp;)?\s*([ァ-ヶー]{2,18})", t)
    kaku_m = re.search(r"格\s+([ＡＢＣ][１２３])\s", t)
    pt_m = re.search(r"格付ポイント\s+([\d,]+)", t)
    b_m = re.search(r"生年月日\s+(\d{4})年(\d{1,2})月(\d{1,2})日", t)
    return {
        "horse_name": name_m.group(4) if name_m else None,
        "asof": f"{name_m.group(1)}-{int(name_m.group(2)):02d}-{int(name_m.group(3)):02d}" if name_m else None,
        "kaku": kaku_m.group(1).translate(ZEN2HAN) if kaku_m else None,
        "points": int(pt_m.group(1).replace(",", "")) if pt_m else None,
        "birth_date": f"{b_m.group(1)}-{int(b_m.group(2)):02d}-{int(b_m.group(3)):02d}" if b_m else None,
    }


# ---------------------------------------------------------------- DB

def sb_all(url, key, path, page=1000):
    out, lo = [], 0
    while True:
        req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json",
            "Range": f"{lo}-{lo + page - 1}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode("utf-8"))
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def push(url, key, rows):
    if not rows:
        return True
    for i in range(0, len(rows), 500):
        st, msg = upsert(url, key, TABLE, "code", rows[i:i + 500])
        if st >= 300 or st == 0:
            log(f"投入失敗 {TABLE} status={st} {msg}")
            return False
    log(f"投入 {len(rows)} 行 -> {TABLE}")
    return True


def read_runs_csv(path, lo, hi):
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if lo <= r["race_date"] <= hi]


def load_seed(path):
    """他場\\data\\nankan_points.json({code:{name,asof,kaku,points,b,fetched}})を表の行へ。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for code, v in d.items():
        rows.append({"code": code, "horse_name": v.get("name"),
                     "kaku": (v.get("kaku") or "").translate(ZEN2HAN) or None,
                     "points": v.get("points"), "asof": v.get("asof"), "birth_date": v.get("b"),
                     "last_run": None, "seen_track": "大井", "fetched": v.get("fetched")})
    return rows


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true", help="表へ書く(無ければドライラン)")
    ap.add_argument("--days", type=int, default=2, help="直近この日数に走った馬を対象にする")
    ap.add_argument("--max-horses", type=int, default=400, help="馬ページを引く上限(1本 1.5 秒)")
    ap.add_argument("--max-races", type=int, default=200, help="出馬表を引く上限")
    ap.add_argument("--runs-csv", help="nar_runs の代わりに読む CSV(track,race_date,race_no,horse_name,birth_date)")
    ap.add_argument("--state-json", help="表の代わりに読み書きする JSON(遡り用・DB に届かないとき)")
    ap.add_argument("--seed-json", help="他場の nankan_points.json を最初の中身として取り込む")
    ap.add_argument("--load-json", help="この JSON の行を表へ入れるだけ(取得はしない)")
    ap.add_argument("--test", action="store_true", help="馬ページを 1 頭だけ")
    ap.add_argument("--shard", help="遡りを並列に分ける: 'i/n'(馬ページの対象を n 等分した i 番目だけ・state は別ファイルへ)")
    ap.add_argument("--sleep", type=float, help=f"リクエスト間隔(秒・既定 {SLEEP})")
    args = ap.parse_args()
    if args.sleep:
        globals()["SLEEP"] = args.sleep
    if args.env:
        load_env(args.env)
    url = (os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    today = dt.datetime.now(JST).date()
    today_s = today.isoformat()

    if args.load_json:
        rows = list(json.loads(Path(args.load_json).read_text(encoding="utf-8")).values())
        log(f"load-json: {len(rows)} 行")
        if not args.apply:
            log("dry-run: 書かない")
            return 0
        return 0 if push(url, key, rows) else 1

    # ---- 既知の馬(表 or JSON or seed)
    known = {}
    if args.state_json and Path(args.state_json).exists():
        known = json.loads(Path(args.state_json).read_text(encoding="utf-8"))
    elif not args.state_json:
        if not url or not key:
            log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
            return 2
        try:
            for r in sb_all(url, key, f"{TABLE}?select=code,horse_name,kaku,points,asof,birth_date,last_run,seen_track,fetched"):
                known[r["code"]] = r
        except Exception as e:
            log(f"DB の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
            return 2
    seeded = []
    if args.seed_json:
        for r in load_seed(args.seed_json):
            if r["code"] not in known:
                known[r["code"]] = r
                seeded.append(r)
        log(f"seed: {len(seeded)} 行を取り込み")

    # ---- ① 窓の中の出走(nar_runs か CSV)
    lo = (today - dt.timedelta(days=args.days)).isoformat()
    try:
        if args.runs_csv:
            runs = read_runs_csv(args.runs_csv, lo, today_s)
        else:
            tr = ",".join(f'"{t}"' for t in BA)
            runs = sb_all(url, key, f"nar_runs?select=track,race_date,race_no,horse_name,birth_date"
                                    f"&track=in.({urllib.request.quote(tr)})&race_date=gte.{lo}&race_date=lte.{today_s}"
                                    "&order=race_date.asc,track.asc,race_no.asc")
    except Exception as e:
        log(f"出走の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2
    by_race = {}
    last_run = {}          # 馬名 → 最終出走日
    for r in runs:
        k = (r["track"], r["race_date"], int(r["race_no"]))
        by_race.setdefault(k, []).append(r)
        if r["race_date"] > last_run.get(r["horse_name"], ""):
            last_run[r["horse_name"]] = r["race_date"]
    log(f"{lo}〜{today_s}: 出走 {len(runs)} / レース {len(by_race)} / 馬 {len(last_run)} / 既知 {len(known)}")
    if not by_race:
        log("窓の中に南関の出走なし=終わり")
        if seeded and args.apply and not args.state_json:
            return 0 if push(url, key, seeded) else 1
        return 0

    names_known = {}
    for c, v in known.items():
        if v.get("horse_name"):
            names_known.setdefault(v["horse_name"], []).append(c)

    # ---- ② 馬名の無い馬がいるレースだけ出馬表を引いて馬コードを集める
    need = [k for k, ents in sorted(by_race.items()) if any(e["horse_name"] not in names_known for e in ents)]
    log(f"② 出馬表を引くレース {len(need)}(上限 {args.max_races})")
    need = need[:args.max_races]
    shard_i, shard_n = (int(x) for x in args.shard.split("/")) if args.shard else (0, 1)
    if args.shard:
        need = need[shard_i::shard_n]                    # 出馬表は分担して読み、下で寄せ集める
        log(f"  shard {shard_i}/{shard_n}: 出馬表 {len(need)} 本")
    months = {d[:7].replace("-", "") for (_, d, _) in need}
    cal = calendar_map(months) if need else {}
    new_codes = {}          # code → (track, date)
    miss_cal, bad = set(), 0
    for (track, date, no) in need:
        kd = cal.get((BA[track], date))
        if not kd:
            miss_cal.add((track, date))
            continue
        rid = f"{date.replace('-', '')}{BA[track]}{kd}{no:02d}"
        try:
            for c in shosai_codes(rid):
                if c not in known and c not in new_codes:
                    new_codes[c] = (track, date)
        except Exception as e:
            bad += 1
            log(f"  出馬表 {rid}: ERR {type(e).__name__}: {str(e)[:100]}")
    if miss_cal:
        log(f"  ⚠回日が分からない開催日: {sorted(miss_cal)}")
    log(f"② 新しい馬コード {len(new_codes)}(失敗 {bad})")
    if args.shard and args.state_json:
        # 分担した出馬表の結果をファイルで持ち寄る(全員そろうまで待つ)。馬ページは code % n で分ける
        base = re.sub(r"\.json$", "", args.state_json)
        Path(f"{base}.shosai{shard_i}.json").write_text(json.dumps(new_codes, ensure_ascii=False), encoding="utf-8")
        t_wait = time.time()
        while True:
            files = [Path(f"{base}.shosai{j}.json") for j in range(shard_n)]
            if all(f.exists() for f in files):
                break
            if time.time() - t_wait > 1800:
                log("  ⚠他の shard を 30 分待っても来ない=自分の分だけで進む")
                break
            time.sleep(5)
        for f in files:
            if f.exists():
                for c, v in json.loads(f.read_text(encoding="utf-8")).items():
                    new_codes.setdefault(c, tuple(v))
        new_codes = {c: v for c, v in new_codes.items() if int(c) % shard_n == shard_i}
        log(f"  shard {shard_i}/{shard_n}: 寄せ集め後の担当 {len(new_codes)} 頭")

    # ---- ③ 馬ページ: 新顔 + 走ったのに基準日が古い既知の馬
    targets = [(c, tr, d) for c, (tr, d) in new_codes.items()]
    for name, lr in last_run.items():
        for c in names_known.get(name, []):
            if args.shard and int(c) % shard_n != shard_i:
                continue
            v = known[c]
            if v.get("fetched") == today_s:
                continue                                     # きょう読んだ
            if (v.get("asof") or "") >= lr:
                continue                                     # 基準日が最終出走日以上=反映済み
            tr = next((t for (t, d, _), ents in by_race.items() if d == lr and any(e["horse_name"] == name for e in ents)), None)
            targets.append((c, tr, lr))
    log(f"③ 馬ページを引く馬 {len(targets)}(上限 {args.max_horses})")
    targets = targets[:1 if args.test else args.max_horses]
    state_out = args.state_json
    if args.shard:
        state_out = re.sub(r"\.json$", f".shard{shard_i}.json", args.state_json) if args.state_json else None
        known = {}                                       # 分担ぶんだけ書く(元の state は読み専用)
        log(f"  shard {shard_i}/{shard_n}: {len(targets)} 頭 → {state_out}")
    rows, bad, nopts = [], 0, 0
    for c, tr, d in targets:
        try:
            v = parse_uma(get(f"{BASE}/uma_info/{c}.do"))
        except Exception as e:
            bad += 1
            log(f"  馬 {c}: ERR {type(e).__name__}: {str(e)[:100]}")
            continue
        if v["points"] is None:
            nopts += 1
        prev = known.get(c, {})
        lr = max(last_run.get(v["horse_name"] or "", ""), prev.get("last_run") or "", d or "") or None
        row = {"code": c, **v, "last_run": lr, "seen_track": tr or prev.get("seen_track"),
               "fetched": today_s, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        rows.append(row)
        known[c] = row
        if args.test:
            log(f"TEST {c} {row}")
        if len(rows) % 100 == 0:
            log(f"  …{len(rows)} 頭")
            if state_out:
                Path(state_out).write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
    log(f"③ 取得 {len(rows)} / うち格・点なし {nopts} / 失敗 {bad}")
    if rows:
        ex = next((r for r in rows if r["points"] is not None), rows[0])
        log(f"  例: {ex['horse_name']} 格 {ex['kaku']} 点 {ex['points']} {ex['asof']}現在 生年 {ex['birth_date']}")

    if state_out:
        Path(state_out).write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
        log(f"state → {state_out}({len(known)} 頭)")
    if not args.apply:
        log("dry-run: 書かない")
        return 0
    out = seeded + rows
    return 0 if push(url, key, out) else 1


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)

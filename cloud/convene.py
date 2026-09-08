# -*- coding: utf-8 -*-
"""統合ビューア cloud: 公式の月別開催日程(未来ぶん)を nar_meta へ入れる(DESIGN §46.2・#146 の解決)。

keiba.go.jp `MonthlyConveneInfo/MonthlyConveneInfoTop?k_year=Y&k_month=M` に先の月の開催予定がある
(2026-08-28 実測: 表= tr が場・td が日・記号は「☆」「●」「Ｄ」。9月が全15場ぶん取れた)。
当月+先2か月の3ページを読み、nar_meta `kaisai_schedule` に入れる。/calendar とトップの週間日程が読む。

  出力 = nar_meta key='kaisai_schedule' の value:
    {"built":"YYYY-MM-DD", "months":["2026-08","2026-09","2026-10"],
     "days":{"2026-09-05":[["kochi","☆"],["saga","☆"]], …},
     "others":{"札幌":0,"中京":0, …}}   ← 15場の対応表に無い行(件数だけ。⛔推定して混ぜない)
  記号は公式の字のまま(☆/●/Ｄ)。意味づけは画面側の仕事(⚠凡例の公式文言を確認してから)。

  py -3 -X utf8 cloud/convene.py                      # ドライラン(既定)。取れた中身を出すだけ
  py -3 -X utf8 cloud/convene.py --verify             # オラクル= 過去月の予定を nar_races の実開催日と突合
  py -3 -X utf8 cloud/convene.py --env pipeline/.env.nar --apply   # 実弾(nar_meta へ upsert)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply と --verify で使う)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔ 実地で分かったこと(2026-08-28):
 1. 表の1列目と最終列は場名(同じ名前が両端に出る)。td の数= その月の日数+2。
 2. 場名は「帯広ば」型(nar と同じ表記)。**対応表に無い行(札幌・中京など)は others へ退避**して混ぜない。
 3. 記号が空のセルは開催なし。「Ｄ」はダートグレード競走の日(9月の5件が実在レースと一致するのを確認済み)。
 4. 未来月でまだ発表が無いページは表が空(エラーではない)。取れた月だけ months に書く。
"""

import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SRC = "https://www.keiba.go.jp/KeibaWeb/MonthlyConveneInfo/MonthlyConveneInfoTop"
META_KEY = "kaisai_schedule"

# 場名 → prefix(js/data.js VENUES と同じ15場)。⛔ここに無い行は others へ(推定しない)
VENUE = {"帯広ば": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa",
         "浦和": "urawa", "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki",
         "金沢": "kanazawa", "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda",
         "姫路": "himeji", "高知": "kochi", "佐賀": "saga"}


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None):
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(r, timeout=90) as x:
        return x.status, x.read().decode("utf-8")


def fetch_month(year, month):
    """{day: [(prefix, mark)]}, others(場名→開催セル数)。ページが読めなければ例外。"""
    url = f"{SRC}?k_year={year}&k_month={month}"
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=40) as x:
        h = x.read().decode("utf-8", errors="replace")
    i = h.find("monthlySchedule")
    if i < 0:
        raise RuntimeError("monthlySchedule が無い(ページ構造が変わった?)")
    # ⛔窓で切らない(200000字で切ったら最終行の佐賀が月によって落ちた=行が巨大)
    seg = re.sub(r"<script.*?</script>", "", h[i:], flags=re.S)
    days, others = {}, {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, flags=re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)]
        if len(cells) < 10:
            continue
        name = cells[0]
        marks = [(d + 1, m) for d, m in enumerate(cells[1:-1]) if m]
        if not name or name in ("月", "火", "水", "木", "金", "土", "日"):
            continue
        p = VENUE.get(name)
        if p is None:
            if marks:
                others[name] = others.get(name, 0) + len(marks)
            continue
        for day, mark in marks:
            days.setdefault(day, []).append((p, mark))
    return days, others


def month_list(today, n=3):
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="オラクル= 先月+当月の予定を nar_races の実開催日と突合(要 SUPABASE_URL/KEY)")
    ap.add_argument("--apply", action="store_true", help="実際に nar_meta へ入れる(既定はドライラン)")
    ap.add_argument("--env")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if (args.apply or args.verify) and (not base or not key):
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い(--apply/--verify には要る)")
        return 2

    today = dt.date.today()
    value = {"built": today.isoformat(), "months": [], "days": {}, "others": {}}
    for y, m in month_list(today):
        try:
            days, others = fetch_month(y, m)
        except Exception as e:
            log(f"{y}-{m:02d}: 読めない {type(e).__name__}: {str(e)[:120]}")
            continue
        ym = f"{y}-{m:02d}"
        if days:
            value["months"].append(ym)
        for d, lst in sorted(days.items()):
            value["days"][f"{ym}-{d:02d}"] = [[p, mk] for p, mk in lst]
        for k2, v2 in others.items():
            value["others"][k2] = value["others"].get(k2, 0) + v2
        log(f"{ym}: 開催日{len(days)}日 のべ{sum(len(v) for v in days.values())}場"
            + (f" / 対応表に無い行={others}" if others else ""))
    if not value["months"]:
        log("1か月も取れなかった")
        return 2

    if args.verify:
        # オラクル: 過去がある月(先月+当月の今日まで)の予定 vs nar_races の実開催日。
        # ⛔差は「中止・代替」でありうる=ゼロを強制しない。数えて見せて人が判断する
        prev = (today.replace(day=1) - dt.timedelta(days=1))
        ok = miss = extra = 0
        for y, m in [(prev.year, prev.month), (today.year, today.month)]:
            try:
                days, _ = fetch_month(y, m)
            except Exception as e:
                log(f"verify {y}-{m:02d}: 読めない {e}")
                continue
            ym = f"{y}-{m:02d}"
            # ⛔1000行キャップ(#8)を踏まない: race_no=1 に絞れば1場日=1行(月でも百数十行)
            st, body = req(base, key, "/rest/v1/nar_races?select=race_date,track&race_no=eq.1"
                           f"&race_date=gte.{ym}-01&race_date=lte.{ym}-31&limit=2000")
            actual = {}
            for r in json.loads(body):
                actual.setdefault(r["race_date"], set()).add(r["track"])
            name_of = {v: k for k, v in VENUE.items()}
            for d, lst in sorted(days.items()):
                date = f"{ym}-{d:02d}"
                if date > today.isoformat():
                    continue
                for p, mk in lst:
                    if name_of[p][:2] in {t[:2] for t in actual.get(date, set())}:
                        ok += 1
                    else:
                        miss += 1
                        log(f"  予定にあるのに実績なし: {date} {name_of[p]}({mk})")
            for date, tracks in sorted(actual.items()):
                if date > today.isoformat():
                    continue                      # 明日の出馬表(未来)は実績ではない
                d = int(date[8:10])
                sched = {name_of[p][:2] for p, _ in days.get(d, [])}
                for t in tracks:
                    if t[:2] not in sched:
                        extra += 1
                        log(f"  実績にあるのに予定なし: {date} {t}")
        log(f"オラクル: 一致{ok} / 予定のみ{miss} / 実績のみ{extra}")

    if not args.apply:
        out = {k: value[k] for k in ("built", "months", "others")}
        log(f"ドライラン(--apply なし): {json.dumps(out, ensure_ascii=False)}")
        sample = dict(list(value["days"].items())[:3])
        log(f"days 例: {json.dumps(sample, ensure_ascii=False)}")
        return 0

    # ⛔updated_at を必ず送る(#155 の教訓: 送らないと鮮度の物差しが腐る)
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": META_KEY, "value": value,
                             "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]).encode("utf-8"))
    log(f"nar_meta/{META_KEY} 更新 {st}(開催日{len(value['days'])}日ぶん)")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())

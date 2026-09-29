# -*- coding: utf-8 -*-
"""§117e 兵庫(園田・西脇)の能検を**本当のレース単位**に割るための取り込み(PC 側・JSON に出すだけ)。

なぜ要るか= 兵庫の公式の結果ページは「種別(ゲート検査/能力検査/発走検査/自主参加)×距離」で表を分けているだけで、
**レースの区切りを持たない**(2026-08-17 園田= 公式は 6 つの塊・本当は 4 レース)。
区切りと順番を持っている出どころが 2 つあるので、ここでは 1 つ目を取る:
  ①競馬ブックの能検ページ `/chihou/nouken/{YYYYMMDD}{場}`(園田= 37・西脇= 45)= レースごとの表。
  ②映像の板(§117d の out/offsets/hyogo_{date}.json)= R・距離・各行の馬名。①に無い馬を入れるために添える。

⛔DB には書かない(投入は Fable)。⛔寸評(他社の評)は取らない。⛔着順の抜けは埋めない(そのまま出す)。
⛔既存の fetch.py / build_noken.py / fetch_kb_all.py は触らない。

  py -3 -u scraper/fetch_kb_noken_hyogo.py --since 20260101      # 2026 の園田・西脇ぜんぶ(済みは飛ばす)
  py -3 -u scraper/fetch_kb_noken_hyogo.py --date 20260817       # 1 日だけ
  py -3 -u scraper/fetch_kb_noken_hyogo.py --date 20260817 --redo  # 済みでもやり直す

出力(data/kb_noken/):
  hyogo_split.json … {"days": {"2026-08-17": {date, venue, kb_id, races[], boards[], mismatch?}}}
  done.tsv         … 日付・場・レース数・行数・板の枚数・所要秒
"""

import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch import DATA, make_client                                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = DATA / "kb_noken"
SPLIT = OUT / "hyogo_split.json"
DONE = OUT / "done.tsv"
# 場コード → 公式の場名(⛔競馬ブックの見出しは略称なので名前では引かない)
TRACKS = {"37": "園田", "45": "西脇"}
# §117d の頭出し(板の読み)。⚠ここは**読むだけ**。
# ⚠DB に既にある日は out/offsets が §117c のときのまま(馬名を持たない)なので、
#   §117d で取り直した out/verify/…json の `redetect` を**先に**見る
# cloud(2026-09-30): 板の読み(映像)は PC の s77-w1 にしか無い。KB_NOKEN_OUT で差し替え可(cloud では無い)
NOKEN_OUT = Path(os.environ.get("KB_NOKEN_OUT") or
                 r"C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\noken_offsets\out")
OFFSETS = NOKEN_OUT / "offsets"
VERIFY = NOKEN_OUT / "verify"
# 行に出す鍵(⛔この順・この鍵だけ。⛔寸評は入れない)
ROW_KEYS = ("name", "fin", "umaban", "pass_order", "last3f", "kind", "weight", "sexage",
            "jockey", "trainer", "time", "ok")


def log(msg):
    print(msg, flush=True)


def cell(td):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", td)).strip()


def norm_name(s):
    """馬名の突き合わせ用。空白と「※」を落とす(⛔字は変えない= 全角カナのまま)。"""
    return re.sub(r"[\s　]+", "", str(s or "")).replace("※", "")


def parse_nouken(html):
    """競馬ブックの能検ページ → [{dist, weather, going, rows[]}](ページの上から= 番組順)。

    ⚠列= 着順・馬番・馬名・性齢・タイム・騎手・厩舎・通過順位・上り3F・寸評・馬体重・試験・合格。
    ⛔寸評(9列目)は取らない。⛔着順が抜けている表があるが**埋めない**(競馬ブックに無い馬がいる日)。"""
    races = []
    for sub, tab in re.findall(
            r'<div class="midasi_sub">\s*<p>([^<]+)</p>.*?(<table class="default nouken">.*?</table>)',
            html, re.S):
        dm = re.search(r"(\d{3,4})m", sub)
        gm = re.search(r"([晴曇雨雪小]+)\s*[・･]\s*([良稍重不]+)", sub)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tab, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 13:
                continue                                   # 見出し(<th>)や飾りの行
            v = [cell(x) for x in tds]
            rows.append({
                "name": v[2], "fin": v[0] or None, "umaban": v[1] or None,
                "pass_order": v[7] or None, "last3f": v[8] or None, "kind": v[11] or None,
                "weight": v[10] or None, "sexage": v[3] or None, "jockey": v[5] or None,
                "trainer": v[6] or None, "time": v[4] or None, "ok": v[12] or None,
            })
        if rows:
            races.append({"dist": int(dm.group(1)) if dm else None,
                          "weather": gm.group(1) if gm else None,
                          "going": gm.group(2) if gm else None, "rows": rows})
    return races


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        log(f"! {path.name} が読めないので作り直す")
        return default


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def boards_of(date):
    """§117d の頭出しの結果から、その日の板= [{no(R), dist, start_sec, names[]}]。無ければ []。"""
    v = VERIFY / ("hyogo_%s.json" % date)
    f = OFFSETS / ("hyogo_%s.json" % date)
    if v.exists():
        res = (read_json(v, {}) or {}).get("redetect") or {}
    elif f.exists():
        res = read_json(f, {})
    else:
        return []
    out = []
    for r in ((res.get("detail") or {}).get("reads") or []):
        if r.get("why"):
            continue                                       # 落とした板は使わない
        names = [x[0] for x in (r.get("names") or []) if x and x[0]]
        if not names:
            continue
        out.append({"no": r.get("no"), "dist": r.get("dist"),
                    "start_sec": int(r["start"]) if r.get("start") is not None else None,
                    "names": names})
    out.sort(key=lambda x: (x["no"] if x["no"] is not None else 99))
    return out


def check_order(races, boards):
    """板の R と競馬ブックの並びがそろっているか。ずれていたら理由(str)、そろっていれば None。

    ⚠板 3R の馬名が競馬ブックの 2 レース目に居るような日は、どちらを信じても嘘になるので**その日は出さない**。"""
    if not races or not boards:
        return None
    idx = {}
    for i, r in enumerate(races):
        for row in r["rows"]:
            idx.setdefault(norm_name(row["name"]), set()).add(i + 1)
    bad = []
    for b in boards:
        hit = {}
        for nm in b["names"]:
            for no in idx.get(norm_name(nm), ()):
                hit[no] = hit.get(no, 0) + 1
        if not hit:
            continue                                       # 競馬ブックに1頭も居ない板は判定しない
        best = max(hit.items(), key=lambda kv: kv[1])[0]
        # ⚠1頭しか重ならない板は**判定しない**(同じ馬が別の回にも出ているだけのことがある。
        #   2026-07-21 西脇の板7R は競馬ブック4レース目と1頭だけ重なるが、板の中身は7レース目そのもの)
        if best != b["no"] and hit[best] >= 2:
            bad.append("板%dR の馬名は競馬ブックの %d レース目(一致 %d 頭)" % (b["no"], best, hit[best]))
    return " ・ ".join(bad) if bad else None


def collect_day(client, date, code, refresh=False):
    """1日ぶん。返り値 = (日の dict か None, 理由)"""
    path = "/chihou/nouken/%s%s" % (date, code)
    try:
        html = client.get(path, refresh=refresh)
    except Exception as e:
        return None, "取得失敗 (%s)" % e
    races = parse_nouken(html)
    if not races:
        return None, "レースの表が無い"
    iso = "%s-%s-%s" % (date[:4], date[4:6], date[6:8])
    boards = boards_of(iso)
    day = {"date": iso, "venue": TRACKS.get(code, code), "kb_id": date + code,
           "races": [dict(r, no=i + 1) for i, r in enumerate(races)]}
    if boards:
        day["boards"] = boards
    why = check_order(day["races"], boards)
    if why:
        day["mismatch"] = why
    return day, None


def month_days(client, ym, refresh=False):
    """/chihou/nouken/{YYYYMM} の一覧から (日付, 場コード) を拾う(園田・西脇だけ)。"""
    try:
        html = client.get("/chihou/nouken/%s" % ym, refresh=refresh)
    except Exception as e:
        log(f"{ym}: 月の一覧が取れない ({e})")
        return []
    out = []
    for s in sorted(set(re.findall(r'href="(\d{10})"', html))):
        if s[:6] == ym and s[8:] in TRACKS:
            out.append((s[:8], s[8:]))
    return out


def done_keys():
    if not DONE.exists():
        return set()
    return {line.split("\t")[0] + line.split("\t")[1]
            for line in DONE.read_text(encoding="utf-8").splitlines() if line.count("\t") >= 1}


def mark_done(date, code, races, rows, boards, secs):
    OUT.mkdir(parents=True, exist_ok=True)
    with DONE.open("a", encoding="utf-8") as f:
        f.write("%s\t%s\t%d\t%d\t%d\t%.0f\n" % (date, code, races, rows, boards, secs))


def seed_from_meta():
    """cloud(2026-09-30): 手元に hyogo_split.json が無いときは本番 nar_meta の今の値(正本)を種にする(読むだけ)。
    push は丸ごと差し替えなので、今月の分だけで送ると過去の日が消えるため。"""
    if SPLIT.exists() or not os.environ.get("SUPABASE_URL"):
        return
    import urllib.request
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    req = urllib.request.Request(base + "/rest/v1/nar_meta?select=value&key=eq.hyogo_noken_split",
                                 headers={"apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as res:
        got = json.loads(res.read().decode("utf-8"))
    if got and isinstance(got[0].get("value"), dict):
        write_json(SPLIT, got[0]["value"])
        days = got[0]["value"].get("days") or {}
        log(f"種= 本番 nar_meta の {len(days)} 日")


def main():
    ap = argparse.ArgumentParser(description="§117e 兵庫の能検をレース単位で取る(JSON に出すだけ)")
    ap.add_argument("--date", help="YYYYMMDD(1日だけ・園田と西脇の両方を見る)")
    ap.add_argument("--since", help="YYYYMMDD(この月から今月まで)")
    ap.add_argument("--no-login", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    ap.add_argument("--redo", action="store_true", help="done.tsv にある日もやり直す")
    a = ap.parse_args()
    if not a.date and not a.since:
        ap.error("--date か --since のどちらかが要ります")

    client, _ = make_client(a)
    targets = []
    if a.date:
        for code in TRACKS:
            targets.append((a.date, code))
    else:
        d = dt.datetime.strptime(a.since, "%Y%m%d").date().replace(day=1)
        end = dt.date.today()
        while d <= end:
            targets += month_days(client, d.strftime("%Y%m"), refresh=a.refresh)
            d = (d.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
    targets = sorted(set(targets))
    log("対象 %d 日(園田・西脇)" % len(targets))

    seed_from_meta()
    store = read_json(SPLIT, {"days": {}})
    already = set() if a.redo else done_keys()
    n_ok = n_mis = n_nob = 0
    for date, code in targets:
        if date + code in already:
            log(f"{date} {TRACKS[code]}: 済み(done.tsv)スキップ")
            continue
        t0 = time.time()
        day, why = collect_day(client, date, code, refresh=a.refresh)
        secs = time.time() - t0
        if day is None:
            log(f"{date} {TRACKS[code]}: {why}")
            continue
        rows = sum(len(r["rows"]) for r in day["races"])
        nb = len(day.get("boards") or [])
        # §117f 板(映像)が1枚も無い日は**出さない**= 並びを確かめる相手がいない
        #   (映像が読めていない日に提供データの通し番号をそのまま R にすると嘘になる。5/12・6/08 で実測)
        if not (day.get("boards") or []) and not NOKEN_OUT.exists():
            # cloud(2026-09-30): 板の出どころ(PC の映像の読み)がこの環境に無い= 判定できない。
            #   既存の日は消さず、済みにもしない(PC の「板が無い日は出さない」は板の出どころがある所でだけ)
            log(f"− {day['date']} {day['venue']}: 板の出どころが無い環境= 触らない(既存 {'あり' if day['date'] in store['days'] else 'なし'})")
            continue
        if not (day.get("boards") or []):
            store["days"].pop(day["date"], None)
            n_nob += 1
            log(f"− {day['date']} {day['venue']}: 板が1枚も無い= 出さない(no なしのまま)")
            mark_done(date, code, len(day["races"]), rows, 0, secs)
            continue
        # ずれる日も**出す**(板を添えたまま)。組み立て側が板の R を no にして組む
        store["days"][day["date"]] = day
        if day.get("mismatch"):
            n_mis += 1
            log(f"⚠ {day['date']} {day['venue']}: 板と並びがずれる(板の R で組む)/ {day['mismatch']}")
        else:
            n_ok += 1
        log("%s %s: %dレース %d行 板%d枚 %s (%.1f秒)" % (
            day["date"], day["venue"], len(day["races"]), rows, nb,
            "/".join(str(len(r["rows"])) for r in day["races"]), secs))
        mark_done(date, code, len(day["races"]), rows, nb, secs)
    write_json(SPLIT, store)
    log("おわり: そろった %d 日 / 板の R で組む(ずれ)%d 日 / 板が無くて出さない %d 日 → %s(全 %d 日)"
        % (n_ok, n_mis, n_nob, SPLIT.name, len(store["days"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

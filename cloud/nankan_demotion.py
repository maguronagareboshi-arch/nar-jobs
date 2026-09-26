# -*- coding: utf-8 -*-
"""§287 南関4場(大井・川崎・船橋・浦和)の「降級の目安」を表 nar_nankan_demotion へ書く(便 nankan-demotion.yml)。

  出どころ= 本番 DB の nar_nankan_points(主催者の馬ページの「格」「格付ポイント」「◯月◯日現在」= cloud/nankan_points.py)。
  線= 公式 Q&A「格付基準(令和6年1月1日適用)」https://www.nankankeiba.com/info/qanda/program.html
      (viewer js/pages/class.js NANKAN_TH の写し。⛔直すときは両方)
  式= nar-site/BACKTEST-demotion-nankan-20260926.md(拾い率 2026年1月 99.5%・7月 99.0%)をそのまま:
      予測「下がる」= 今の点 < 切替後の半期表(1月= 上半期・7月= 下半期)× 切替後の馬齢(年 − 馬コード先頭4桁)× 今の級 の線。
      Ｃ3(下の級が無い)と線が空欄の欄は出さない。8歳以上(切替前の馬齢)は上下半期で線が同じ= 出さない。
  どの切替に当てるか(割合でなく日付で決める):
      S0= 今日以前で最新の切替日(1/1 か 7/1)、S1= 今日より後の最初の切替日。
      馬の格付の基準日(asof)< S0 = まだ S0 の前の格= S0 に当てて pending(主催者の反映待ち)。
      asof >= S0 = S0 は反映済み= S1 に当てる。asof が S0 の一つ前の切替日より前(半年以上出ていない)の馬は出さない。
  ⛔新しい線の適用が 7/1 の日付か「7月に始まる開催」からかは未確認(BACKTEST の外れの型)。

  python cloud/nankan_demotion.py --dry-run [--out x.csv]   # DB を読む→CSV と場ごとの行数だけ(書かない)
  python cloud/nankan_demotion.py --apply                   # upsert→古い asof の行を消す→heartbeat 'nankan_demotion'
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(ドライランは読める鍵なら何でもよい)。終了コード: 0 正常 / 1 投入失敗 / 2 読み・計算の失敗
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

JST = dt.timezone(dt.timedelta(hours=9))
TABLE = "nar_nankan_demotion"
BEAT_JOB = "nankan_demotion"
SRC = "nar_nankan_points"
# 線(3歳, 4歳, 5歳, 6歳, 7歳, 8歳以上)。None= 空欄(0 扱い= 降級なし)。Ｃ3 は下が無いので持たない
KAMI = {"A1": [2800, 3400, 4300, 5000, 5500, 5900], "A2": [2000, 2200, 2500, 3200, 3700, 4100],
        "B1": [1500, 1700, 1900, 2200, 2700, 3000], "B2": [1100, 1200, 1400, 1700, 2000, 2200],
        "B3": [700, 800, 1000, 1300, 1600, 1800], "C1": [None, 500, 700, 1000, 1300, 1500],
        "C2": [None, 200, 400, 700, 1000, 1200]}
SHIMO = {"A1": [3000, 3600, 4400, 5200, 5700, 5900], "A2": [2200, 2300, 2600, 3400, 3900, 4100],
         "B1": [1700, 1800, 2000, 2500, 2900, 3000], "B2": [1200, 1300, 1500, 1800, 2100, 2200],
         "B3": [800, 900, 1100, 1400, 1700, 1800], "C1": [500, 600, 800, 1100, 1400, 1500],
         "C2": [200, 300, 500, 800, 1100, 1200]}
COLS = ["code", "horse_name", "track", "cls_now", "pts", "pts_asof", "age", "line", "short",
        "target", "target_label", "pending", "asof"]


def log(*a):
    print(*a, flush=True)


def switches(today):
    """(S_prevprev, S0, S1)= 今日以前の最新の切替の一つ前・最新・今日より後の最初。"""
    s0 = dt.date(today.year, 7, 1) if today >= dt.date(today.year, 7, 1) else dt.date(today.year, 1, 1)
    s1 = dt.date(s0.year + 1, 1, 1) if s0.month == 7 else dt.date(s0.year, 7, 1)
    sp = dt.date(s0.year, 1, 1) if s0.month == 7 else dt.date(s0.year - 1, 7, 1)
    return sp, s0, s1


def label(d, today):
    return (f"{d.year}年" if d.year != today.year else "") + f"{d.month}月"


def birth_year(r):
    c = str(r.get("code") or "")
    if len(c) >= 4 and c[:4].isdigit():
        return int(c[:4])
    b = r.get("birth_date")
    return int(str(b)[:4]) if b else None


def line_of(target, cls_, age):
    tbl = KAMI if target.month == 1 else SHIMO
    if cls_ not in tbl or age is None or age < 3:
        return None
    return tbl[cls_][min(age, 8) - 3]


def forecast(src, today):
    sp, s0, s1 = switches(today)
    out, why = [], collections.Counter()
    for r in src:
        k, P, a = (r.get("kaku") or "").strip().upper(), r.get("points"), r.get("asof")
        if not k or P is None or not a:
            why["格か点か基準日なし"] += 1
            continue
        ad = dt.date.fromisoformat(str(a)[:10])
        if ad < sp:
            why["半年以上出ていない"] += 1
            continue
        if k not in KAMI:
            why["Ｃ3・級名なし"] += 1
            continue
        pending = ad < s0
        tgt = s0 if pending else s1
        by = birth_year(r)
        if by is None:
            why["馬齢不明"] += 1
            continue
        age = tgt.year - by
        age_before = age if tgt.month == 7 else age - 1
        if age_before >= 8:
            why["8歳以上"] += 1
            continue
        L = line_of(tgt, k, age)
        if not L:
            why["線が空欄"] += 1
            continue
        if int(P) >= L:
            why["線の上"] += 1
            continue
        out.append(dict(code=str(r["code"]), horse_name=r.get("horse_name") or "", track=r.get("seen_track"),
                        cls_now=k, pts=int(P), pts_asof=ad.isoformat(), age=age, line=L, short=L - int(P),
                        target=tgt.isoformat(), target_label=label(tgt, today), pending=pending))
    return out, why, (sp, s0, s1)


# ---------- DB ----------
def sb_all(url, key, path, page=1000):
    out, off = [], 0
    while True:
        req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items",
            "Range": f"{off}-{off + page - 1}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read())
        out += got
        if len(got) < page:
            return out
        off += page


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLS})


def apply_rows(url, key, rows, asof):
    from load_nar_official import upsert
    for i in range(0, len(rows), 500):
        st, msg = upsert(url, key, TABLE, "code", rows[i:i + 500])
        if st >= 300:
            raise RuntimeError(f"upsert {st} {msg}")
    req = urllib.request.Request(f"{url}/rest/v1/{TABLE}?asof=lt.{urllib.parse.quote(asof)}", method="DELETE", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="CSV の出力先")
    ap.add_argument("--today", help="基準日(試し用 YYYY-MM-DD)")
    a = ap.parse_args()
    apply_ = a.apply and not a.dry_run
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()

    def say(ok, note):
        if apply_:
            import beat as B
            B.beat(BEAT_JOB, ok, note)
        log(f"heartbeat {BEAT_JOB} {'ok' if ok else 'fail'} {note}" + ("" if apply_ else "(ドライラン= 書かない)"))

    try:
        if not (url and key):
            raise ValueError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        src = sb_all(url, key, f"{SRC}?select=code,horse_name,kaku,points,asof,birth_date,seen_track&order=code")
        if not src:
            raise ValueError(f"{SRC} が 0 行")
        rows, why, (sp, s0, s1) = forecast(src, today)
    except Exception as e:
        log(f"::error::読み・計算に失敗: {type(e).__name__}: {e}")
        say(False, f"計算失敗 {str(e)[:80]}")
        return 2
    asof = dt.datetime.now(JST).isoformat(timespec="seconds")
    for r in rows:
        r["asof"] = asof
    log(f"読んだ馬 {len(src)}・切替 {s0}(反映待ちの当て先)/{s1}(次)・見込みの行 {len(rows)}")
    log("除いた数: " + " ".join(f"{k}={v}" for k, v in why.most_common()))
    by = collections.Counter((r["track"] or "不明", r["target_label"], r["pending"]) for r in rows)
    for (t, lb, pd), n in sorted(by.items(), key=lambda x: (str(x[0][0]), x[0][1])):
        log(f"  {t} {lb}{'(反映待ち)' if pd else ''}: {n}")
    out = a.out or f"nankan_demotion_{today.isoformat()}.csv"
    write_csv(out, rows)
    log(f"CSV= {out}")
    if not apply_:
        return 0
    if not rows:
        log("::error::見込みの行が 0= 表を消さずに止める")
        say(False, "見込み 0 行")
        return 2
    try:
        apply_rows(url, key, rows, asof)
    except Exception as e:
        log(f"::error::投入失敗: {e}")
        say(False, "投入失敗")
        return 1
    pend = sum(1 for r in rows if r["pending"])
    say(True, f"見込み {len(rows)}" + (f"(反映待ち {pend})" if pend else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""§54.5: オークション原本(cloud/data/auction/**)→ `auction_sales`(画面に出してよい事実だけ)。

原本= 楽天 rakuten_items/*.jsonl.gz(§54.4b・/api/item)+ SAT sat/items.jsonl(§54.4・ページ傍受)。
抽出= §54.4c。⛔散文からは抜かない。`※`(楽天)/`★`(SAT)で始まる公式開示行に**テンプレ一致**した第1層だけ tags に。
⛔「（模擬）」(#358)は入れない。⛔horse_name はカタカナだけの名前に限る(幼駒「〜の25」は null・display_name に残す)。

回次(第N回・楽天だけ)= 終了日の distinct を新しい順に並べ、今週(260903=第691回)から数え下ろす。
  ⛔数え下ろしは**公式Topicsの「第N回取引馬 ○○号」18組をオラクル**にして裏取りし、最古の一致より前は null にする。

  py -3.12 -X utf8 cloud/auction_load.py --env pipeline/.env.nar            # ドライラン(件数と内訳だけ)
  py -3.12 -X utf8 cloud/auction_load.py --env pipeline/.env.nar --apply    # 実弾(upsert・冪等)
  py -3.12 -X utf8 cloud/auction_load.py --env pipeline/.env.nar --check    # オラクル: 回次の裏取り+馬名ジョイン率
環境変数: SUPABASE_URL / SUPABASE_ANON_KEY(--check) / SUPABASE_SERVICE_KEY(--apply)
終了コード: 0 正常 / 1 一部失敗 / 2 前提失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env, upsert  # noqa: E402

DATA = HERE / "data" / "auction"
JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; nar-jobs/1.0)"
BATCH = 500
THIS_ROUND = ("2026-09-03", 691)     # 第691回=2026-09-03(木)。⛔更新するときは公式トップの「第N回」で

# ---------------------------------------------------------------- §54.4c 第1層(テンプレ一致だけ)
RULES = [
    ("南関東転入不可", re.compile(r"南関東[０-９0-9]*競馬場への転入はできません")),
    ("南関東転入可", re.compile(r"南関東[０-９0-9]*競馬場への転入が可能")),
    ("南関東へ特例転入可", re.compile(r"(川崎|船橋|浦和)[、・].*特例転入が可能")),
    ("タイムオーバー出走制限", re.compile(r"タイムオーバーによる出走制限")),
    ("成績による出走制限", re.compile(r"走成績による出走制限")),
    ("さく癖", re.compile(r"さく癖があります")),
    ("ゆう癖", re.compile(r"ゆう癖があります")),
    ("旋回癖", re.compile(r"旋回癖があります")),
    ("去勢済", re.compile(r"去勢手術を(実施|行っ)")),
]
# 楽天の共通定型文(全件同文)。開示行の数(other_n)に入れない
BOILER = ("サラブレッドオークションでの落札馬", "実馬を見学", "引き取り前に獣医検査", "落札馬の引き渡しにかかる",
          "自己入札", "在厩しており、預託料", "における預託料", "売買成立後の引き渡し", "預託料につきまして",
          "販売申込者", "消費税", "インボイス", "測尺")
DATE_RE = re.compile(r"([０-９0-9]{4})年\s*([０-９0-9]{1,2})月\s*([０-９0-9]{1,2})日")
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
KATA = re.compile(r"^[ァ-ヶー]{2,9}$")

# 公式Topics(2026-09-02 実測)= 「第N回取引馬 ○○号」。回次の数え下ろしを裏取りするオラクル(display_name で引く)。
# ⛔幼駒で売られた馬は**出品名が血統名**(ブレイブプラウド=メガミノキセキの24 等)なので、その名で引く。
# ⛔ガビーズシスター(第425回)は原本に出品名が見つからず(改名前の血統名が Topics に無い)= オラクルから外した
ANCHORS = {"スカンジナビア": 599, "メガミノキセキの24": 659, "ローザレイア": 637, "モズマーヴェリック": 667,
           "アースジャッジ": 653, "メイショウタイセツ": 514, "マンガン": 540, "ティアップエックス": 486,
           "カンパニョーラ": 384, "パワーブローキング": 496, "オボッチャマ": 468,
           "ヒロイックテイル": 492, "ガイフウカイセイ": 454, "シゲルスタールビーの22": 470, "アポロユッキーの21": 422,
           "ミニョン": 445, "モダスオペランディ": 433}


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def z(s):
    return str(s or "").translate(Z2H)


def to_date(m):
    if not m:
        return None
    try:
        return f"{int(z(m.group(1))):04d}-{int(z(m.group(2))):02d}-{int(z(m.group(3))):02d}"
    except ValueError:
        return None


def plain(s):
    return html.unescape(re.sub(r"<[^>]+>", "\n", s or ""))


def extract_tags(lines):
    """公式開示行 → (tags, other_n)。tags は自分の言葉に正規化した事実だけ"""
    tags, other = [], 0
    for line in lines:
        if any(b in line for b in BOILER):
            continue
        hit = False
        for name, rx in RULES:
            if rx.search(line):
                if name == "去勢済":
                    d = to_date(DATE_RE.search(line))
                    tags.append(f"去勢済({d})" if d else "去勢済")
                else:
                    tags.append(name)
                hit = True
        if not hit:
            other += 1
    if "南関東転入不可" in tags and "南関東転入可" in tags:      # 矛盾は出さない(⛔誤情報より無情報)
        tags = [t for t in tags if not t.startswith("南関東転入")]
    return sorted(set(tags)), other


# ---------------------------------------------------------------- 楽天

def read_jsonl_dir(d):
    recs = {}
    if not d.exists():
        return recs
    for f in sorted(list(d.glob("*xxx.jsonl.gz")) + list(d.glob("*xxx.jsonl")) + list(d.glob("items.jsonl"))):
        try:
            text = gzip.open(f, "rt", encoding="utf-8").read() if f.suffix == ".gz" else f.read_text(encoding="utf-8")
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
        for line in text.splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                recs[r["id"]] = r          # 後の行が勝つ(取り直し #353)
    return recs


def rakuten_row(r):
    it = r.get("item") or {}
    name = re.sub(r"[ \t　]+", " ", str(it.get("name") or "")).strip()
    if not name or "模擬" in name:
        return None
    head, _, tail = name.partition("※")
    toks = head.split(" ")
    display = toks[0]
    sex = next((c for c in ("牡", "牝", "セ") if re.search(rf"(^|\s){c}(\s|[０-９0-9])", head)), None)
    m = re.search(r"([０-９0-9]{1,2})歳", head)
    age = int(z(m.group(1))) if m else None
    desc = plain(it.get("description"))
    birth = to_date(re.search(r"([０-９0-9]{4})年\s*([０-９0-9]{1,2})月\s*([０-９0-9]{1,2})日生", desc))
    j = re.search(r"jbis\.or\.jp/horse/(\d{10})", str(it.get("description") or ""))
    star = [re.sub(r"[ \t　]+", " ", ln).strip() for ln in desc.split("\n")]
    star = [ln for ln in star if ln.startswith("※") and len(ln) < 300]
    tags, other = extract_tags(star)
    bids = len(it.get("bid_history") or [])
    price = int(it.get("current_price") or 0)
    end = str(it.get("end_datetime") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        return None
    return {
        "source": "rakuten", "item_id": int(r["id"]),
        "horse_name": display if KATA.match(display) else None,
        "display_name": display, "sex": sex, "age": age, "birth_date": birth,
        "category": re.sub(r"\s+", " ", tail).strip() or None,
        "auction_date": end, "round_no": None,
        "start_price": int(it.get("start_price") or 0) or None,
        "price": price if (price > 0 and bids > 0) else None,
        "bids": bids, "sold": bool(price > 0 and bids > 0),
        "seller": None,                                    # 楽天は事務局名しか無い(出品者は description 側)
        "tags": tags, "other_n": other,
        "jbis_id": j.group(1) if j else None,
        "url": f"https://auction.keiba.rakuten.co.jp/item/{int(r['id'])}",
        "fetched_at": r.get("fetched_at"),
    }


def assign_rounds(rows):
    """楽天の終了日 → 第N回。今週から数え下ろし、オラクルで裏取りできた最古の回より前は null"""
    dates = sorted({x["auction_date"] for x in rows if x["source"] == "rakuten"}, reverse=True)
    # §114(#487): 毎朝 /item を取るようになり、**次回(まだ終わっていない回)の終了日**が THIS_ROUND より新しく並ぶ。
    #   THIS_ROUND を基準に、新しい方へは +1 ずつ・古い方へは -1 ずつ数える(1 終了日= 1 回の前提は今までどおり)。
    #   ⛔THIS_ROUND の日付そのものが無いときだけ付けない(基準を失う)。
    if THIS_ROUND[0] not in dates:
        log(f"⚠ THIS_ROUND {THIS_ROUND[0]} の終了日が原本に無い→回次は付けない")
        return rows, {}
    base = dates.index(THIS_ROUND[0])
    rmap = {d: THIS_ROUND[1] + (base - i) for i, d in enumerate(dates)}
    if base:
        log(f"回次: THIS_ROUND より新しい終了日 {base} 件(次回以降)= 第{THIS_ROUND[1] + base}回まで付ける")
    by_name = {}
    for x in rows:
        if x["source"] == "rakuten":
            by_name.setdefault(x["display_name"], set()).add(rmap[x["auction_date"]])
    ok, ng, oldest_ok = 0, [], None
    for nm, want in ANCHORS.items():
        got = by_name.get(nm, set())
        if want in got:
            ok += 1
            d = next(d for d, n in rmap.items() if n == want)
            oldest_ok = d if oldest_ok is None or d < oldest_ok else oldest_ok
        else:
            ng.append(f"{nm}:期待{want}/実{sorted(got) or '-'}")
    log(f"回次オラクル: 一致 {ok}/{len(ANCHORS)}" + (f" ⚠不一致 {ng}" if ng else ""))
    if ok < len(ANCHORS) * 0.9:
        log("⚠ 回次の数え下ろしが信用できない→全部 null")
        return rows, {}
    for x in rows:
        if x["source"] == "rakuten" and x["auction_date"] >= oldest_ok:
            x["round_no"] = rmap[x["auction_date"]]
    log(f"回次を付けた範囲: {oldest_ok}(第{rmap[oldest_ok]}回)〜{dates[0]}(第{rmap[dates[0]]}回)。それより前は null")
    return rows, rmap


# ---------------------------------------------------------------- SAT

def sat_row(r):
    api = r.get("api") or {}
    bs = api.get("bid_status") or {}
    title = str(r.get("title") or "").strip()
    text = str(r.get("text") or "")
    lines = [re.sub(r"[ \t　]+", " ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    end = str(bs.get("end_datetime") or "")[:10]
    if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        return None
    sex = next((ln for ln in lines[:12] if ln in ("牡", "牝", "セ")), None)
    m = next((re.fullmatch(r"([0-9０-９]{1,2})歳", ln) for ln in lines[:12] if re.fullmatch(r"([0-9０-９]{1,2})歳", ln)), None)
    age = int(z(m.group(1))) if m else None
    cat = next((ln for ln in lines[:12] if re.search(r"在籍|抹消|未入厩|繁殖|育成|未出走", ln)), None)
    birth = to_date(re.search(r"([０-９0-9]{4})年\s*([０-９0-9]{1,2})月\s*([０-９0-9]{1,2})日生", text))
    sm = re.search(r"販売申込者\s*[:：]?\s*(.+)", text)
    seller = sm.group(1).strip()[:60] if sm else None
    # 開示は free_fields[].remarks の ★行(SAT の＜その他＞)+ 本文の ※行。テンプレ一致だけ
    cand = []
    for ff in api.get("free_fields") or []:
        for ln in str((ff or {}).get("remarks") or "").split("\n"):
            ln = re.sub(r"[ \t　]+", " ", ln).strip()
            if ln.startswith(("★", "※")):
                cand.append(ln)
    cand += [ln for ln in lines if ln.startswith(("★", "※"))]
    tags, _ = extract_tags(cand)
    hist = api.get("bid_histories") or []
    price = int(bs.get("current_price") or 0)
    sold = bool(price > 0 and hist and not bs.get("is_cancel"))
    return {
        "source": "sat", "item_id": int(r["id"]),
        "horse_name": title if KATA.match(title) else None,
        "display_name": title, "sex": sex, "age": age, "birth_date": birth, "category": cat,
        "auction_date": end, "round_no": None,
        "start_price": int(bs.get("lowest_bid_price") or 0) or None,
        "price": price if sold else None, "bids": len(hist), "sold": sold,
        "seller": seller, "tags": tags, "other_n": 0, "jbis_id": None,
        "url": f"https://www.sat-auction.jp/auction/{int(r['id'])}",
        "fetched_at": r.get("fetched_at"),
    }


# ---------------------------------------------------------------- 入り口

def build():
    rows = []
    rk = read_jsonl_dir(DATA / "rakuten_items")
    for i in sorted(rk):
        x = rakuten_row(rk[i])
        if x:
            rows.append(x)
    n_rk = len(rows)
    st = read_jsonl_dir(DATA / "sat")
    for i in sorted(st):
        x = sat_row(st[i])
        if x:
            rows.append(x)
    log(f"原本: 楽天 {len(rk):,}件→{n_rk:,}行(模擬・不正を除く) / SAT {len(st):,}件→{len(rows) - n_rk:,}行")
    rows, _ = assign_rounds(rows)
    return rows


def summarize(rows):
    c = Counter()
    for x in rows:
        c[(x["source"], "named" if x["horse_name"] else "unnamed")] += 1
        c[(x["source"], "sold")] += int(x["sold"])
        c[(x["source"], "birth")] += int(bool(x["birth_date"]))
        c[(x["source"], "jbis")] += int(bool(x["jbis_id"]))
        c[(x["source"], "tagged")] += int(bool(x["tags"]))
    for s in ("rakuten", "sat"):
        n = sum(1 for x in rows if x["source"] == s)
        log(f"  {s}: {n:,}行 / 馬名あり {c[(s, 'named')]:,} / 落札 {c[(s, 'sold')]:,} / 生年月日 {c[(s, 'birth')]:,}"
            f" / JBIS {c[(s, 'jbis')]:,} / 開示タグあり {c[(s, 'tagged')]:,}")
    tc = Counter(t.split("(")[0] for x in rows for t in x["tags"])
    log("  開示タグ: " + " ".join(f"{k}{v}" for k, v in tc.most_common()))


def sb_rows(base, key, path):
    req = urllib.request.Request(f"{base}/rest/v1/{path}", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept-Encoding": "gzip", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def check_join(rows, base, key):
    """オラクル: 落札から180日以上経った馬名つきの行を nar_runs と突合(落札後の出走が取れる率)"""
    today = dt.datetime.now(JST).date()
    cand = [x for x in rows if x["horse_name"] and x["sold"]
            and (today - dt.date.fromisoformat(x["auction_date"])).days >= 180
            and x["auction_date"] >= "2022-11-01"]           # nar_runs の下限(実測 2022-11-01)
    import random
    random.seed(20260902)
    sample = random.sample(cand, min(60, len(cand)))
    hit = 0
    for x in sample:
        q = (f"nar_runs?select=race_date&horse_name=eq.{urllib.parse.quote(x['horse_name'])}"
             f"&race_date=gt.{x['auction_date']}&limit=1")
        try:
            if sb_rows(base, key, q):
                hit += 1
        except Exception as e:
            log(f"  ⚠ {x['horse_name']}: {e}")
        time.sleep(0.15)
    log(f"ジョイン率(落札180日以上・2022-11以降・無作為{len(sample)}頭): 落札後の出走あり {hit}頭 = {hit * 100 // max(len(sample), 1)}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    service = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if a.apply and not (base and service):
        log("--apply には SUPABASE_URL / SUPABASE_SERVICE_KEY が要る"); return 2

    rows = build()
    summarize(rows)
    if a.check:
        if not (base and (anon or service)):
            log("--check には SUPABASE_URL / SUPABASE_ANON_KEY が要る"); return 2
        check_join(rows, base, anon or service)
    if not a.apply:
        log("(dry) 書いていません。--apply で upsert")
        return 0
    fails = 0
    for i in range(0, len(rows), BATCH):
        part = rows[i:i + BATCH]
        st, msg = upsert(base, service, "auction_sales", "source,item_id", part)
        if st not in (200, 201):
            log(f"⚠ upsert 失敗 {i}〜: {st} {str(msg)[:160]}"); fails += 1
    log(f"upsert 完了: {len(rows):,}行 / 失敗バッチ {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

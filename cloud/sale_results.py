# -*- coding: utf-8 -*-
"""本体 cloud: せり市場(セレクトセール=JRHA / 北海道市場=HBA)の取引結果を auction_sales に同居させる(DESIGN §54.6・2026-09-04)。

  出典(一次・ユーザーが許可を確認済み 2026-09-04):
    JRHA 取引馬データベース  POST https://www.jrha.or.jp/database/hpJRHASearch(上場年度ごとに 1 本・表 1 枚に全馬・**競走馬名あり**)
    HBA  市場取引結果検索    GET  https://www.hba.or.jp/result_list.php?page_data[unit]=100&page_data[now]=N(落札分のみ・2003 年〜・**競走馬名なし**)
  ⛔JBIS は使わない(利用規約 第8条・robots Crawl-delay 600)。

  行の形= auction_sales(source='jrha'|'hba', item_id= 年4桁+区分1桁+上場番号4桁, horse_name= 競走馬名(HBA は 父+母+生年月日 で当サイトの馬と突合),
    display_name= '母名の2025' 型, category= 'セレクトセール 当歳' / 'サマーセール 1歳', auction_date= 市場の日(⚠HBA/JRHA は**月まで**の近似=画面は年だけ出す),
    price= 円(JRHA は万円→円), sold= 落札, seller/買い手= 出典の字のまま, url= 出典の検索ページ)

  python cloud/sale_results.py --env pipeline/.env.nar                      # ドライラン(今年ぶん)
  python cloud/sale_results.py --apply --years 2025,2026                    # 日次(月次便): 直近 2 年ぶんを取り直して upsert
  python cloud/sale_results.py --apply --from-json jrha_all.json hba_all.json --ped nar_ped.csv   # 手元の全量 JSON から(初回)
終了コード: 0 正常 / 1 投入失敗 / 2 読み取り失敗
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import http.cookiejar
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
from load_nar_official import load_env, upsert            # noqa: E402
from odds import JST, log                                  # noqa: E402

UA = "nar-jobs/1.0"
SLEEP = 1.0
TABLE = "auction_sales"
JRHA_URL = "https://www.jrha.or.jp/database/hpJRHASearch"
HBA_URL = "https://www.hba.or.jp/result_list.php"
# 市場ごとの近似日(月まで)。⛔正確な開催日は年ごとに違うので、画面は「年」だけを出す(auction_date は並び順のためだけ)
HBA_MONTH = {"トレーニングセール": (5, 20), "セレクションセール": (7, 20), "サマーセール": (8, 20),
             "セプテンバーセール": (9, 15), "オータムセール": (10, 15), "サマープレミアムセール": (8, 25)}
HBA_CODE = {"トレーニングセール": 1, "セレクションセール": 2, "サマーセール": 3, "セプテンバーセール": 4, "オータムセール": 5,
            "サマープレミアムセール": 6}
AGE_N = {"当歳": 0, "１歳": 1, "1歳": 1, "２歳": 2, "2歳": 2}


def _txt(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()


def _rows(table_html):
    return [[_txt(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
            for tr in re.findall(r"<tr.*?</tr>", table_html, re.S)]


# ⛔HBA の一覧は**セッション**に表示件数(unit)を覚える= cookie を持ち回る。ページ番号は角括弧を %5B %5D にした形だけ効く(2026-09-04 実測)
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def http(url, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, **(headers or {})})
    with _OPENER.open(req, timeout=60) as r:
        raw = r.read()
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------- 出典

def fetch_jrha(year):
    h = http(JRHA_URL, {"bamei": "", "bmpos": "0", "titi": "", "tpos": "0", "haha": "", "hpos": "0", "hahatiti": "", "htpos": "0",
                        "hanbai": "", "hbpos": "0", "kounyu": "", "knpos": "0", "nendo": str(year), "kubun": "", "seibetu": "",
                        "kakaku1": "", "kakaku2": "", "hyoji": "0"})
    tabs = [_rows(t) for t in re.findall(r"<table.*?</table>", h, re.S)]
    big = max(tabs, key=len) if tabs else []
    # 列= 上場年度 | せり区分 | 上場番号 | 父 | 母 | 母の父 | 性 | 競走馬名 | 所属(美浦/栗東/地方) | 調教師 | 販売者 | 購買価格(万円) | 購買者 | 総獲得賞金
    #   ⚠見出しは「所属厩舎」1 語だが中身は 2 列(所属・調教師)= 2026-09-04 実測(13 列で読むと販売者と価格がずれる)
    keys = ["year", "kubun", "lot", "sire", "dam", "damsire", "sex", "name", "area", "trainer", "seller", "price_man", "buyer", "prize"]
    return [dict(zip(keys, r)) for r in big[1:] if len(r) >= 14]


def fetch_hba_pages(max_pages, stop_when_known=None):
    """1 ページ 100 行。stop_when_known(item_ids) が与えられたら、1 ページの全行が既知になったら止める。"""
    out = []
    keys = ["year", "sale", "breed", "age", "lot", "sire", "dam", "sex", "color", "bd", "seller", "result", "price", "buyer"]
    http("https://www.hba.or.jp/result.php")                       # セッション
    http(f"{HBA_URL}?page_data%5Bunit%5D=100")                    # 1 ページ 100 行をセッションに覚えさせる
    time.sleep(SLEEP)
    for page in range(1, max_pages + 1):
        h = http(f"{HBA_URL}?page_data%5Bnow%5D={page}")
        tabs = re.findall(r"<table.*?</table>", h, re.S)
        if not tabs:
            break
        rows = _rows(tabs[0])
        body = [dict(zip(keys, r)) for r in rows[1:] if len(r) == len(keys)]
        if not body:
            break
        out.extend(body)
        if stop_when_known and all(stop_when_known(hba_item_id(r)) for r in body):
            break
        time.sleep(SLEEP)
    return out


# ---------------------------------------------------------------- 行へ

def _int(s):
    s = re.sub(r"[^\d]", "", str(s or ""))
    return int(s) if s else None


def hba_item_id(r):
    code = HBA_CODE.get(r["sale"], 9)
    lot = _int(r["lot"]) or 0
    return int(f"{_int(r['year']):04d}{code}{lot:04d}")     # ⚠年は '2023年' と書かれた行がある


def jrha_item_id(r):
    k = 0 if "当" in r["kubun"] else 1
    return int(f"{_int(r['year']):04d}{k}{(_int(r['lot']) or 0):04d}")


def hba_row(r, ped):
    year = _int(r["year"])
    age = AGE_N.get(r["age"])
    sold = r["result"] == "落札"
    m, d = HBA_MONTH.get(r["sale"], (6, 30))
    bd = None
    if age is not None and re.fullmatch(r"\d{1,2}/\d{1,2}", r["bd"] or ""):
        mm, dd = r["bd"].split("/")
        bd = f"{year - age:04d}-{int(mm):02d}-{int(dd):02d}"
    name, birth = None, bd
    if ped is not None:
        # 父+母が同じ馬(全きょうだい)から生年月日で 1 頭に絞る。⛔生年が無い候補を「たぶんこれ」と当てない=
        #   生年月日が一致する候補が 1 頭だけのときと、全きょうだいが 1 頭しかいない(生年不明)ときだけ
        cands = ped.get((r["sire"], r["dam"]), [])
        exact = [c for c in cands if bd and c[1] == bd]
        if len(exact) == 1:
            name, birth = exact[0]
        elif not exact and len(cands) == 1 and not cands[0][1]:
            name, birth = cands[0][0], bd
    return {
        "source": "hba", "item_id": hba_item_id(r), "horse_name": name,
        "display_name": f"{r['dam']}の{year - age}" if age is not None else f"{r['dam']}の子",
        "sex": r["sex"] or None, "age": age, "birth_date": birth,
        "category": f"{r['sale']} {r['age']}", "auction_date": f"{year:04d}-{m:02d}-{d:02d}", "round_no": None,
        "start_price": None, "price": _int(r["price"]) if sold else None, "bids": 0, "sold": sold,
        "seller": r["seller"] or None, "tags": [], "other_n": 0, "jbis_id": None,
        "url": "https://www.hba.or.jp/result.php", "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sire": r["sire"] or None, "dam": r["dam"] or None, "buyer": r["buyer"] or None,
    }


def jrha_row(r):
    year = _int(r["year"])
    age = 0 if "当" in r["kubun"] else 1
    price_man = _int(r["price_man"])
    name = r["name"] if r["name"] and r["name"] != "-" else None
    return {
        "source": "jrha", "item_id": jrha_item_id(r), "horse_name": name,
        "display_name": name or f"{r['dam']}の{year - age}",
        "sex": r["sex"] or None, "age": age, "birth_date": None,
        "category": f"セレクトセール {'当歳' if age == 0 else '1歳'}", "auction_date": f"{year:04d}-07-{10 if age == 0 else 11:02d}",
        "round_no": None, "start_price": None, "price": price_man * 10000 if price_man else None, "bids": 0,
        "sold": bool(price_man), "seller": r["seller"] or None, "tags": [], "other_n": 0, "jbis_id": None,
        "url": "https://www.jrha.or.jp/database/index", "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sire": r["sire"] or None, "dam": r["dam"] or None, "buyer": r["buyer"] or None,
    }


def load_ped(path):
    ped = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            ped.setdefault((r["sire"], r["dam"]), []).append((r["horse_name"], r.get("birth_date") or None))
    return ped


def push(url, key, rows):
    for i in range(0, len(rows), 500):
        st, msg = upsert(url, key, TABLE, "source,item_id", rows[i:i + 500])
        if st >= 300 or st == 0:
            log(f"投入失敗 {TABLE} status={st} {msg}")
            return False
    log(f"投入 {len(rows)} 行 -> {TABLE}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--years", help="JRHA の上場年度(カンマ区切り・既定= 今年と去年)")
    ap.add_argument("--hba-pages", type=int, default=3, help="HBA を新しい順に読むページ数の上限(1 ページ 100 行)")
    ap.add_argument("--from-json", nargs="*", help="手元の JSON(jrha_all.json / hba_all.json)から(出典は読まない)")
    ap.add_argument("--ped", help="馬名の突合に使う CSV(horse_name,sire,dam,birth_date)。無ければ DB から読む")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = (os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    now = dt.datetime.now(JST)

    # 血統→馬名(HBA の突合)。DB(nar_horses+nar_runs)か CSV
    ped = None
    if args.ped:
        ped = load_ped(args.ped)
    elif url and key:
        try:
            ped = {}
            lo = 0
            while True:
                req = urllib.request.Request(f"{url}/rest/v1/nar_horses?select=horse_name,sire,dam&sire=not.is.null&dam=not.is.null",
                                             headers={"apikey": key, "Authorization": f"Bearer {key}", "Range": f"{lo}-{lo + 999}", "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    rows = json.loads(r.read().decode("utf-8"))
                for r in rows:
                    ped.setdefault((r["sire"], r["dam"]), []).append((r["horse_name"], None))
                if len(rows) < 1000:
                    break
                lo += 1000
        except Exception as e:
            log(f"血統の読み取りに失敗: {type(e).__name__}: {str(e)[:120]}(HBA の馬名突合なしで進む)")
            ped = None
    log(f"血統の鍵 {len(ped) if ped else 0} 組")

    rows = []
    if args.from_json:
        for f in args.from_json:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            if data and "kubun" in data[0]:
                rows += [jrha_row(r) for r in data]
            else:
                rows += [hba_row(r, ped) for r in data]
    else:
        years = [int(y) for y in args.years.split(",")] if args.years else [now.year - 1, now.year]
        for y in years:
            try:
                got = fetch_jrha(y)
            except Exception as e:
                log(f"JRHA {y}: 失敗 {type(e).__name__}: {str(e)[:120]}")
                return 2
            rows += [jrha_row(r) for r in got]
            log(f"JRHA {y}: {len(got)} 行")
            time.sleep(SLEEP)
        try:
            got = fetch_hba_pages(args.hba_pages)
        except Exception as e:
            log(f"HBA: 失敗 {type(e).__name__}: {str(e)[:120]}")
            return 2
        rows += [hba_row(r, ped) for r in got]
        log(f"HBA: {len(got)} 行(新しい順 {args.hba_pages} ページ)")
    # 同じ (source,item_id) は後勝ち
    uniq = {}
    for r in rows:
        uniq[(r["source"], r["item_id"])] = r
    rows = list(uniq.values())
    named = sum(1 for r in rows if r["horse_name"])
    sold = sum(1 for r in rows if r["sold"])
    log(f"行 {len(rows)} / 落札 {sold} / 馬名あり {named}(jrha {sum(1 for r in rows if r['source']=='jrha' and r['horse_name'])} / hba {sum(1 for r in rows if r['source']=='hba' and r['horse_name'])})")
    if not args.apply:
        log("dry-run: 書かない")
        return 0
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    return 0 if push(url, key, rows) else 1


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)

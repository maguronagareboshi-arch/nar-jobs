# -*- coding: utf-8 -*-
"""セール(市場取引)の上場記録 → 表 sale_listings(1 行= 上場 1 回・落札/主取り/欠場)。2026-09-26 枝 horse-sales。

  出典= JBIS-Search の市場取引(ユーザーが JBIS・HBA の掲載許可を取得済み 2026-09-26)。
    年の一覧  https://www.jbis.or.jp/seri/result/?year=<年>        → 市場コード・市場名・品種・年齢・開催日
    市場ごと  https://www.jbis.or.jp/seri/<年>/<コード>/sale/       → 上場番号・父・母・性・毛色・価格・購買者欄・販売申込者・JBIS の馬 id
    ⛔購買者名は持たない(購買者欄は「主取り」「欠場」の判定だけに使う)。
    総括表(コード末尾 !!)は除く。ばんえいは JBIS に無い(価格非公表)。JRA-VAN は使わない。
    HBA 5 市場・八戸・セレクト(JRHA・ユーザー許可済み)・千葉・九州・ブリーズアップ・ミックス・ジェイエス 等は全部この 1 つの形で取れる
    (市場ごとの差は一覧の名前だけ= 市場ごとの台本は要らない)。
  生年月日の補い= HBA の上場名簿 CSV(sale_detail.php の一括ダウンロード)を --catalog-dir に置くと、(年, 市場, 上場番号)で
    生年月日・上場日を足す。⛔生産者はどちらの出典にも無い(名簿は販売申込者・飼養者だけ)= breeder 列は空のまま(後で別の出典から)。無い市場は birth_date=null・birth_year= 開催年-年齢。

  ひも付け(horse_code= nar_horse_profiles.code)= 母名(NFKC・末尾の(国名)を外す)+生年+性(牡とセは同じ扱い)。
    生年月日が両方にあれば一致を必須。候補が 2 頭以上なら結ばない(link_method='multi')。
    ⛔生産者は鍵にしない(表記が 32% しか揃わない)。JBIS の馬 id は当サイトに無いので保存だけ(jbis_horse_id)。

  py -3.12 -X utf8 cloud/sale_listings.py fetch --raw <dir> --years 2003-2026      # 取得して保存だけ(1 回・4 秒間隔)
  py -3.12 -X utf8 cloud/sale_listings.py parse --raw <dir> --catalog-dir <dir> --out rows.csv
  py -3.12 -X utf8 cloud/sale_listings.py link  --rows rows.csv --profiles prof.csv --out linked.csv
  py -3.12 -X utf8 cloud/sale_listings.py load  --rows linked.csv [--apply]        # --apply で upsert(既定はドライラン)
  python cloud/sale_listings.py weekly [--apply]    # 便: 今年の一覧から終わって 60 日以内の市場を取り直す→ひも付け→upsert→未結びの再ひも付け→heartbeat
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply)/ SUPABASE_ANON_KEY(読むだけ)
終了コード: 0 正常 / 1 一部失敗 / 2 前提失敗
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; nar-jobs/1.0)"
BASE = "https://www.jbis.or.jp"
SLEEP = 4.0
TABLE = "sale_listings"
BEAT_JOB = "sale_listings"
EXCLUDE_NAMES = ("総括表",)
AGE = {"当歳": 0, "１歳": 1, "1歳": 1, "２歳": 2, "2歳": 2}
COLS = ["sale_year", "market_code", "hip_no", "market_name", "breed", "age_class", "sale_start", "sale_end", "sale_date",
        "horse_name", "dam", "dam_norm", "sire", "sex", "color", "birth_year", "birth_date", "breeder", "seller", "result",
        "price_yen_tax_incl", "jbis_horse_id", "horse_code", "link_method", "source_url"]


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 取得

def http(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            for enc in ("utf-8", "cp932"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    pass
            return raw.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            log(f"  retry {url}: {type(e).__name__} {str(e)[:80]}")
            time.sleep(SLEEP * 5)


def _txt(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()


def parse_index(h, year):
    """年の一覧 → [{code, title, start, end}]。行= 開催日のテキスト + <a href="/seri/<年>/<コード>/">タイトル</a>"""
    out = []
    for m in re.finditer(r'([0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\s*～\s*[0-9]{2}\.[0-9]{2})?)\s*(?:</[^>]+>\s*|<[^>]+>\s*)*'
                         r'<a href="/seri/' + str(year) + r'/([0-9A-Z!]{4})/"[^>]*>(.*?)</a>', h, re.S):
        d, code, title = m.group(1), m.group(2), _txt(m.group(3))
        s = re.match(r"(\d{4})\.(\d{2})\.(\d{2})(?:\s*～\s*(\d{2})\.(\d{2}))?", d)
        start = dt.date(int(s.group(1)), int(s.group(2)), int(s.group(3)))
        end = dt.date(start.year, int(s.group(4)), int(s.group(5))) if s.group(4) else start
        out.append({"code": code, "title": title, "start": start.isoformat(), "end": end.isoformat()})
    seen, uniq = set(), []
    for r in out:
        if r["code"] not in seen:
            seen.add(r["code"]); uniq.append(r)
    return uniq


def split_title(title, year):
    """'2025年北海道オータムセール サラブレッド １歳' → (市場名, 品種, 年齢区分)"""
    t = re.sub(r"^\d{4}年(度)?", "", title).strip()
    parts = t.split()
    name = parts[0] if parts else t
    breed = parts[1] if len(parts) > 1 else None
    age = " ".join(parts[2:]) if len(parts) > 2 else None
    return name, breed, age


def wanted(title):
    return not any(x in title for x in EXCLUDE_NAMES)


def fetch_year(year, raw: Path, force=False, only_recent_days=None, today=None):
    """一覧と市場ごとのページを raw/<年>/ に gzip で保存。既にあれば読まない(途中から再開できる)。"""
    d = raw / str(year)
    d.mkdir(parents=True, exist_ok=True)
    ip = d / "index.html.gz"
    if force or not ip.exists():
        h = http(f"{BASE}/seri/result/?year={year}&items=100")
        ip.write_bytes(gzip.compress(h.encode("utf-8")))
        time.sleep(SLEEP)
    idx = parse_index(gzip.decompress(ip.read_bytes()).decode("utf-8"), year)
    got = []
    for r in idx:
        if not wanted(r["title"]):
            continue
        if only_recent_days is not None:
            end = dt.date.fromisoformat(r["end"])
            if not (0 <= (today - end).days <= only_recent_days):
                continue
        p = d / f"{r['code'].replace('!', '_')}.html.gz"
        if force or not p.exists():
            h = http(f"{BASE}/seri/{year}/{r['code']}/sale/")
            p.write_bytes(gzip.compress(h.encode("utf-8")))
            time.sleep(SLEEP)
        got.append(r)
    return idx, got


# ---------------------------------------------------------------- 読み取り

LEAF = re.compile(r"<div(?: class=\"[^\"]*\")?>((?:(?!<div|</div>).)*?)</div>", re.S)


def parse_sale(h):
    """市場のページ → [{hip, jbis_id, name, birth_year, sire, dam, sex, color, price_txt, buyer_txt, seller}]。葉の div を列数ずつ読む。
    形は 2 つ: 子馬の市場(8 列: 上場番号・父・母・性・毛色・価格・購買者・販売申込者)
             繁殖牝馬の市場(9 列: 上場番号・繁殖牝馬名・生年・父・母・配合馬・価格・購買者・販売申込者)"""
    i = h.find("data-7__inner")
    j = h.find("to-top", i)
    region = h[i:j if j > 0 else len(h)]
    leaves = LEAF.findall(region)
    k = next((n for n in range(len(leaves)) if "上場番号" in _txt(leaves[n])), None)
    if k is None:
        return [], 0
    mare = "繁殖牝馬名" in _txt(leaves[k + 1]) if k + 1 < len(leaves) else False
    w = 9 if mare else 8
    rows, bad = [], 0
    n = k + w
    while n + w <= len(leaves):
        c = leaves[n:n + w]
        hip_m = re.search(r">\s*(\d+)\s*<", c[0]) or re.match(r"\s*(\d+)\s*$", _txt(c[0]))
        if mare:
            ok = hip_m and re.fullmatch(r"\d{4}", _txt(c[2]) or "")
            sex = "牝"
        else:
            sex = _txt(c[3])
            ok = hip_m and sex in ("牡", "牝", "セ", "騸")
        if not ok:
            bad += 1; n += 1
            if bad > 50:
                break
            continue
        jid = re.search(r'href="/horse/(\d+)/"', c[0])
        if mare:
            rows.append({"hip": int(hip_m.group(1)), "jbis_id": jid.group(1) if jid else None, "name": _txt(c[1]) or None,
                         "birth_year": int(_txt(c[2])), "sire": _txt(c[3]) or None, "dam": _txt(c[4]) or None, "sex": "牝",
                         "color": None, "price_txt": _txt(c[6]), "buyer_txt": _txt(c[7]), "seller": _txt(c[8]) or None})
        else:
            rows.append({"hip": int(hip_m.group(1)), "jbis_id": jid.group(1) if jid else None, "name": None, "birth_year": None,
                         "sire": _txt(c[1]) or None, "dam": _txt(c[2]) or None, "sex": "セ" if sex == "騸" else sex,
                         "color": _txt(c[4]) or None, "price_txt": _txt(c[5]), "buyer_txt": _txt(c[6]), "seller": _txt(c[7]) or None})
        n += w
    return rows, bad


def result_of(price_txt, buyer_txt):
    p = re.sub(r"[^\d]", "", price_txt or "")
    if "欠場" in buyer_txt:
        return "欠場", None
    if "主取" in buyer_txt:
        return "主取り", None
    if p and int(p) > 0:
        return "落札", int(p)
    return None, None


def norm_dam(s):
    if not s:
        return None
    t = unicodedata.normalize("NFKC", s).strip()
    t = re.sub(r"\s*\([A-Z]{2,4}\)\s*$", "", t)
    return t.replace(" ", "").replace("　", "") or None


def load_catalogs(cdir):
    """HBA 上場名簿 CSV(cp932)→ [(日付, 上場番号, 母, 性, 生年月日(月日), 生産者)] のファイルごとの一覧。見出しの揺れは位置で読む。"""
    out = {}
    if not cdir:
        return out
    for p in sorted(Path(cdir).glob("*.csv")):
        raw = p.read_bytes()
        try:
            txt = raw.decode("cp932")
        except UnicodeDecodeError:
            txt = raw.decode("utf-8", "replace")
        rd = list(csv.reader(txt.splitlines()))
        if not rd:
            continue
        head = [unicodedata.normalize("NFKC", h).replace("\n", "") for h in rd[0]]

        def col(*names):
            for nm in names:
                for i, h in enumerate(head):
                    if nm in h:
                        return i
            return None
        ci = {"day": col("日付", "上場日"), "hip": col("上場No", "上場番号"), "sex": col("性"), "bd": col("生年月日"),
              "dam": col("母") if col("母") != col("母の父") else None, "breeder": col("生産者")}
        # 「母」は「母の父」より前にある列
        ci["dam"] = next((i for i, h in enumerate(head) if h == "母"), ci["dam"])
        recs = []
        for r in rd[1:]:
            try:
                hip = int(unicodedata.normalize("NFKC", r[ci["hip"]]).strip())
            except (ValueError, TypeError, IndexError):
                continue
            recs.append({"hip": hip, "day": r[ci["day"]] if ci["day"] is not None else None,
                         "dam": r[ci["dam"]] if ci["dam"] is not None else None,
                         "bd": r[ci["bd"]] if ci["bd"] is not None else None,
                         "breeder": r[ci["breeder"]] if ci["breeder"] is not None else None})
        out[p.name] = recs
    return out


def _md(s):
    m = re.search(r"(\d{1,2})\s*[月/]\s*(\d{1,2})", unicodedata.normalize("NFKC", s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_all(raw: Path, years, cdir=None):
    rows, stats = [], Counter()
    for y in years:
        d = raw / str(y)
        ip = d / "index.html.gz"
        if not ip.exists():
            stats["no_index"] += 1
            continue
        for r in parse_index(gzip.decompress(ip.read_bytes()).decode("utf-8"), y):
            if not wanted(r["title"]):
                continue
            p = d / f"{r['code'].replace('!', '_')}.html.gz"
            if not p.exists():
                stats["missing_page"] += 1
                continue
            name, breed, age = split_title(r["title"], y)
            recs, bad = parse_sale(gzip.decompress(p.read_bytes()).decode("utf-8"))
            stats["bad_leaf"] += bad
            if not recs:
                stats["empty_sale"] += 1
                log(f"  空: {y} {r['code']} {r['title']}")
            ag = AGE.get((age or "").strip())
            for x in recs:
                res, price = result_of(x["price_txt"], x["buyer_txt"])
                if res is None:
                    stats["unknown_result"] += 1
                    log(f"  結果不明: {y} {r['code']} {x['hip']} {x['price_txt']!r} {x['buyer_txt'][:10]!r}")
                rows.append({"sale_year": y, "market_code": r["code"], "hip_no": x["hip"], "market_name": name, "breed": breed,
                             "age_class": age, "sale_start": r["start"], "sale_end": r["end"], "sale_date": None,
                             "dam": x["dam"], "dam_norm": norm_dam(x["dam"]), "sire": x["sire"], "sex": x["sex"], "color": x["color"],
                             "birth_year": x["birth_year"] or ((y - ag) if ag is not None else None), "horse_name": x["name"], "birth_date": None, "breeder": None,
                             "seller": x["seller"], "result": res, "price_yen_tax_incl": price, "jbis_horse_id": x["jbis_id"],
                             "horse_code": None, "link_method": None, "source_url": f"{BASE}/seri/{y}/{r['code']}/sale/"})
    # HBA 名簿で生年月日を補う: 名簿ごとに (上場番号, 母) の一致が最も多い市場に当てる
    cats = load_catalogs(cdir)
    by_sale = defaultdict(dict)
    for x in rows:
        by_sale[(x["sale_year"], x["market_code"])][x["hip_no"]] = x
    for fn, recs in cats.items():
        best, score = None, 0
        for key, hips in by_sale.items():
            s = sum(1 for c in recs if c["hip"] in hips and norm_dam(c["dam"]) == hips[c["hip"]]["dam_norm"])
            if s > score:
                best, score = key, s
        if not best or score < 0.8 * len(recs):
            log(f"  名簿 {fn}: 当てる市場が無い(最大一致 {score}/{len(recs)})")
            stats["catalog_unmatched"] += 1
            continue
        hips = by_sale[best]
        n = 0
        for c in recs:
            x = hips.get(c["hip"])
            if not x or norm_dam(c["dam"]) != x["dam_norm"]:
                continue
            md = _md(c["bd"])
            if md and x["birth_year"]:
                try:
                    x["birth_date"] = dt.date(x["birth_year"], *md).isoformat()
                except ValueError:
                    pass
            dm = _md(c["day"])
            if dm:
                x["sale_date"] = dt.date(best[0], *dm).isoformat()
            n += 1
        log(f"  名簿 {fn} → {best[0]} {best[1]} {hips[next(iter(hips))]['market_name']}: {n}/{len(recs)} 行に生年月日")
        stats["catalog_rows"] += n
    return rows, stats


# ---------------------------------------------------------------- ひも付け

def _sexkey(s):
    return "M" if s in ("牡", "セ") else ("F" if s == "牝" else None)


def link(rows, profiles):
    """profiles= [{code, horse_name, birth_date, sex, dam}]。rows を上書きで結ぶ。"""
    idx = defaultdict(list)
    for p in profiles:
        if not p.get("birth_date") or not p.get("dam"):
            continue
        idx[(norm_dam(p["dam"]), int(p["birth_date"][:4]), _sexkey(p.get("sex")))].append(p)
    c = Counter()
    for x in rows:
        x["horse_code"], x["link_method"] = None, None
        if not x["birth_year"] or not x["dam_norm"]:
            c["no_key"] += 1
            continue
        cand = idx.get((x["dam_norm"], x["birth_year"], _sexkey(x["sex"])), [])
        if x["birth_date"]:
            cand = [p for p in cand if p["birth_date"][:10] == x["birth_date"]]
            how = "dam+sex+birth_date"
        else:
            how = "dam+sex+birth_year"
        if len(cand) == 1:
            x["horse_code"], x["link_method"] = cand[0]["code"], how
            c[how] += 1
        elif len(cand) > 1:
            x["link_method"] = "multi"
            c["multi"] += 1
        else:
            c["none"] += 1
    return c


# ---------------------------------------------------------------- DB(読む/書く)

def rest_get(base, key, path):
    out, off = [], 0
    while True:
        req = urllib.request.Request(f"{base}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items", "Range": f"{off}-{off + 999}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            part = json.loads(r.read().decode("utf-8"))
        out += part
        if len(part) < 1000:
            return out
        off += 1000


def read_profiles(base, key, y_from, y_to):
    q = ("nar_horse_profiles?select=code,horse_name,birth_date,sex,dam,last_seen"
         f"&birth_date=gte.{y_from}-01-01&birth_date=lte.{y_to}-12-31&order=code.asc")
    return rest_get(base, key, q)


def upsert_rows(base, key, rows, batch=500):
    from load_nar_official import upsert  # noqa: E402
    bad = 0
    for i in range(0, len(rows), batch):
        part = [{k: (x.get(k) if x.get(k) != "" else None) for k in COLS} for x in rows[i:i + batch]]
        st, msg = upsert(base, key, TABLE, "sale_year,market_code,hip_no", part)
        if st >= 300:
            bad += 1
            log(f"  upsert 失敗 {i}: {st} {msg[:200]}")
    return bad


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for x in rows:
            w.writerow({k: x.get(k) for k in COLS})


def read_csv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for x in csv.DictReader(f):
            for k in ("sale_year", "hip_no", "birth_year", "price_yen_tax_incl"):
                x[k] = int(x[k]) if x.get(k) else None
            for k in COLS:
                if x.get(k) == "":
                    x[k] = None
            rows.append(x)
    return rows


def _years(s):
    a, _, b = s.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "parse", "link", "load", "weekly"])
    ap.add_argument("--raw", default=str(HERE / "data" / "sales" / "jbis"))
    ap.add_argument("--years", default=None)
    ap.add_argument("--catalog-dir")
    ap.add_argument("--rows")
    ap.add_argument("--profiles", help="CSV(code,horse_name,birth_date,sex,dam,last_seen)")
    ap.add_argument("--out")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=60, help="weekly: 終わってから何日以内の市場を取り直すか")
    a = ap.parse_args(argv)
    raw = Path(a.raw)
    today = dt.datetime.now(JST).date()
    years = _years(a.years) if a.years else [today.year]

    if a.cmd == "fetch":
        for y in years:
            idx, got = fetch_year(y, raw)
            log(f"{y}: 一覧 {len(idx)} 市場・取得 {len(got)}")
        return 0
    if a.cmd == "parse":
        rows, st = parse_all(raw, years, a.catalog_dir)
        write_csv(rows, a.out)
        log(f"行 {len(rows)} → {a.out}  {dict(st)}")
        return 0
    if a.cmd == "link":
        rows = read_csv(a.rows)
        with open(a.profiles, encoding="utf-8") as f:
            prof = list(csv.DictReader(f))
        c = link(rows, prof)
        write_csv(rows, a.out)
        log(f"ひも付け {dict(c)} → {a.out}")
        return 0

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    wkey = os.environ.get("SUPABASE_SERVICE_KEY", "")
    rkey = os.environ.get("SUPABASE_ANON_KEY", "") or wkey
    if a.cmd == "load":
        rows = read_csv(a.rows)
        log(f"投入対象 {len(rows)} 行" + ("" if a.apply else "(ドライラン= 書かない)"))
        if not a.apply:
            return 0
        if not (base and wkey):
            log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
        return 1 if upsert_rows(base, wkey, rows) else 0

    # weekly(便): 取り直し→ひも付け→upsert→heartbeat
    import beat as B
    if not base or not rkey:
        log("SUPABASE_URL / KEY が無い"); return 2
    try:
        idx, got = fetch_year(today.year, raw, force=True, only_recent_days=a.days, today=today)
        rows, st = parse_all(raw, [today.year], a.catalog_dir)
        keep = {r["code"] for r in got}
        rows = [x for x in rows if x["market_code"] in keep]
        ys = [x["birth_year"] for x in rows if x["birth_year"]]
        prof = read_profiles(base, rkey, min(ys), max(ys)) if ys else []
        c = link(rows, prof)
        log(f"今年の対象市場 {len(keep)}・行 {len(rows)}・ひも付け {dict(c)}")
        # 未結びの再ひも付け(競走馬登録は上場の後= 後から結べる)。直近 5 世代だけ
        old = rest_get(base, rkey, f"{TABLE}?select={','.join(COLS)}&horse_code=is.null&birth_year=gte.{today.year - 5}"
                                   "&order=sale_year.asc,market_code.asc,hip_no.asc")
        old = [x for x in old if (x["sale_year"], x["market_code"]) not in {(today.year, k) for k in keep}]
        prof2 = read_profiles(base, rkey, today.year - 5, today.year)
        c2 = link(old, prof2)
        newly = [x for x in old if x["horse_code"]]
        log(f"再ひも付け 対象 {len(old)}・新たに結べた {len(newly)}")
        if not a.apply:
            log("ドライラン= 書かない"); return 0
        bad = upsert_rows(base, wkey, rows + newly)
        B.beat(BEAT_JOB, bad == 0, f"市場{len(keep)} 行{len(rows)} 再結{len(newly)}")
        return 1 if bad else 0
    except Exception as e:  # noqa: BLE001
        log(f"失敗: {type(e).__name__}: {e}")
        if a.apply:
            B.beat(BEAT_JOB, False, f"{type(e).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

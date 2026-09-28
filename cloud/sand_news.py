# -*- coding: utf-8 -*-
"""本体 cloud: 各場の公式の「砂の補充・入れ替え・砂厚・路盤」の告知を毎朝拾って nar_meta へ入れる(/sand の毎朝の告知拾い便)。

  入口は nar-site/research/track-sand/gap-A.md・gap-B.md の「自動拾いの入口」(場ごと 1 行)のとおり。
  直近 30 日の題名を取り → 砂/砂厚/補充/入替/路盤/クッション の語で絞り → 本文を開いて
  日付・種別・短い text(場所・㎥/t・cm は数字そのまま。抜けなければ公式の題名)を抜く。

  出力 = nar_meta key='sand_news' の value:
    {"built":ISO, "sources":{源:{"ok":bool,"n":件数,"why"?}}, "skipped":{場:理由},
     "items":[{"v":"kanazawa","k":"YYYY-MM-DD","d":"YYYY/M/D","types":[..],"text":..,
               "src":[url],"swap":bool,"title":..}, …]}   ← 新しい順・最大 300
  前回の items を読み、(src の 1 本目, k) で重ねて足す(⛔消さない)。

  py -3 -X utf8 cloud/sand_news.py                     # ドライラン(既定)
  py -3 -X utf8 cloud/sand_news.py --site kanazawa     # 1 源だけ試す
  py -3 -X utf8 cloud/sand_news.py --apply             # 実弾(前回を読んで重ね、nar_meta へ upsert)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply と前回の読み込みでだけ使う)
終了コード: 0 正常 / 1 投入失敗 / 2 1 源も取れなかった

⛔決まりごと
 1. 入札・工期・金額・予定価格・落札・公告の記事は捨てる(/sand は作業の事実だけ)。
 2. 定例は拾わない= 高知の「馬場状態」・帯広の「散水」「走路整備」。
 3. 1 源が落ちても残りは出す。全部落ちたら exit 2。源と源の間は数秒空ける(金沢は一括走査で 403 にされた)。
 4. 大井(tokyocitykeiba.com)は 403= 対象外。笠松は公式サイトに出ない(X のみ)= 対象外。
 5. 名古屋の「開催初日前日砂厚測定」は同じ PDF 名(babasunaatu.pdf)を上書きで使う= 重ねる鍵は (src, k)。
    測定の値が前回の測定と同じなら足さない(毎開催同じ形の定型なので)。
"""

import argparse
import calendar
import datetime as dt
import html as _html
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
META_KEY = "sand_news"
MAX_ITEMS = 300
DAYS = 30
TIMEOUT = 25
GAP_SITE = 4.0        # 源と源の間(秒)
GAP_PAGE = 2.0        # 同じ源の中で次のページを開くまで(秒)
JST = dt.timezone(dt.timedelta(hours=9))

HIT = re.compile(r"砂|補充|入替|入れ替|入換|路盤|クッション")
DROP = re.compile(r"入札|工期|金額|予定価格|落札|公告|散水|馬場状態")
UNIT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:㎥|m3|ｍ3|m³|立方|立米|t(?![a-z])|ｔ|トン|cm|㎝|ｃｍ|センチ)")
WORK = re.compile(r"補充|投入|入替|入れ替|入換|砂厚|馬場厚|路盤|掻き出し|書き出し|クッション砂")

SKIPPED = {"ooi": "tokyocitykeiba.com が 403(自動取得を断っている)",
           "kasamatsu": "公式サイトに出ない(X のみ・数値は画像)"}


# ---------------------------------------------------------------- 小道具

def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def fetch(url):
    raw = fetch_bytes(url)
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def clean(s):
    s = re.sub(r"<[^>]*>", "", s or "")
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def page_text(html_text):
    """HTML → 行ごとの字(script/style は捨てる)"""
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", t)
    t = re.sub(r"<[^>]*>", " ", t)
    t = _html.unescape(t)
    lines = [re.sub(r"[ \t　]+", " ", x).strip() for x in t.split("\n")]
    return "\n".join(x for x in lines if x)


def norm_date(s):
    s = (s or "").strip()
    m = re.search(r"(\d{4})[./年-](\d{1,2})[./月-](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})(?:\s+(\d{1,2}):)?", s)
        if not m:
            return None
        mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        if m.group(2) not in mon:
            return None
        y, mo, d = int(m.group(3)), mon.index(m.group(2)) + 1, int(m.group(1))
        # RSS の pubDate は +0000 が多い= 15 時以降(UTC)は JST の翌日
        if m.group(4) and "+0000" in s and int(m.group(4)) >= 15:
            x = dt.date(y, mo, d) + dt.timedelta(days=1)
            y, mo, d = x.year, x.month, x.day
    try:
        dt.date(y, mo, d)
    except ValueError:
        return None
    return "%04d-%02d-%02d" % (y, mo, d)


def abs_url(base, u):
    u = _html.unescape((u or "").strip())
    return urllib.parse.urljoin(base, u)


def months_back(today, n=2):
    """今月と先月(直近 30 日を覆う)→ [(y, m), …]"""
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


# ---------------------------------------------------------------- 一覧の読み方(源ごと)

def rss_items(url):
    text = fetch(url)
    out = []
    for block in re.findall(r"<item[^>]*>(.*?)</item>", text, re.S | re.I):
        t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S | re.I)
        u = re.search(r"<link[^>]*>(.*?)</link>", block, re.S | re.I)
        d = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", block, re.S | re.I)
        c = re.search(r"<content:encoded[^>]*>(.*?)</content:encoded>", block, re.S | re.I)
        body = None
        if c:
            body = page_text(re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", c.group(1)))
        title, link = clean(t.group(1)) if t else "", clean(u.group(1)) if u else ""
        date = norm_date(d.group(1)) if d else None
        if title and link and date:
            out.append({"d": date, "t": title, "u": link, "body": body})
    return out


def html_items(url, item_re):
    flat = re.sub(r"\s+", " ", fetch(url))
    out = []
    for m in re.finditer(item_re, flat, re.S | re.I):
        g = m.groupdict()
        title, date = clean(g.get("t", "")), norm_date(g.get("d", ""))
        if title and date and g.get("u"):
            out.append({"d": date, "t": title, "u": abs_url(url, g["u"]), "body": None})
    return out


def paged(make_url, item_re, pages=5):
    """ページ送りの一覧= 新しい番号が出なくなるまで(最大 pages)"""
    out, seen = [], set()
    for p in range(1, pages + 1):
        rows = html_items(make_url(p), item_re)
        new = [r for r in rows if r["u"] not in seen]
        if not new:
            break
        for r in new:
            seen.add(r["u"])
        out += new
        time.sleep(GAP_PAGE)
    return out


def list_kanazawa(today):
    rows = rss_items("https://www.kanazawakeiba.com/?s=%E3%82%B3%E3%83%BC%E3%82%B9%E6%83%85%E5%A0%B1&feed=rss2")
    # /race/info-N と /news/info-N の両方に出る= info 番号で 1 本に
    out, seen = [], set()
    for r in rows:
        m = re.search(r"info-(\d+)", r["u"])
        key = m.group(1) if m else r["u"]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def list_iwate(today):
    return rss_items("https://www.iwatekeiba.or.jp/?s=%E8%B5%B0%E8%B7%AF%E7%8A%B6%E6%B3%81&feed=rss2")


def list_kochi(today):
    return rss_items("https://www.keiba.or.jp/?s=%E8%A3%9C%E5%85%85&feed=rss2")


def list_saga(today):
    return rss_items("https://www.sagakeiba.net/?s=%E7%A0%82&feed=rss2")


def list_funabashi(today):
    text = fetch("https://blog.f-keiba.com/info/atom.xml")
    out = []
    for block in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S)
        u = re.search(r'<link rel="alternate"[^>]*href="([^"]+)"', block)
        d = re.search(r"<published>(.*?)</published>", block)
        if t and u and d:
            out.append({"d": norm_date(d.group(1)), "t": clean(t.group(1)), "u": u.group(1), "body": None})
    return [r for r in out if r["d"]]


def list_kawasaki(today):
    js = json.loads(fetch("https://www.kawasaki-keiba.jp/api/api_news_list.html?output=json&category=all&page=1"))
    flat = re.sub(r"\s+", " ", js.get("html") or "")
    out = []
    for m in re.finditer(r'href="(?P<u>[^"]+)".*?<time[^>]*>(?P<d>[^<]+)</time>.*?'
                         r'm-topics-article__description[^>]*>(?P<t>.*?)</p>', flat):
        out.append({"d": norm_date(m.group("d")), "t": clean(m.group("t")),
                    "u": abs_url("https://www.kawasaki-keiba.jp/", m.group("u")), "body": None})
    return [r for r in out if r["d"] and r["t"]]


def list_monbetsu(today):
    out = []
    for y, m in months_back(today):
        out += html_items("https://www.hokkaidokeiba.net/topics/index.php?p_ym=%04d%02d" % (y, m),
                          r'<a href="(?P<u>/topics/main\.php\?[^"]+)"><span class="time[^"]*">(?P<d>[\d.]+)</span>'
                          r'.*?<span class="title">(?P<t>[^<]+)')
        time.sleep(GAP_PAGE)
    return out


def list_banei(today):
    out = []
    for y, m in months_back(today):
        wv = int(dt.datetime(y, m, 1, tzinfo=JST).timestamp())
        out += paged(lambda p, wv=wv: "https://banei-keiba.or.jp/tp_list.php?wt=mon&wv=%d&no=%d" % (wv, p),
                     r'<a href="(?P<u>tp_detail\.php\?id=\d+)">.*?<time>(?P<d>[\d-]+)</time>.*?<h1>(?P<t>[^<]+)</h1>')
    return out


def list_urawa(today):
    out = []
    for y, m in months_back(today):
        out += paged(lambda p, y=y, m=m: "https://www.urawa-keiba.jp/info/news/?page=%d&year=%d&month=%d&category=info" % (p, y, m),
                     r'<a href="(?P<u>[^"]*detail\.html\?did=\d+)"[^>]*>.*?p-newsList__date">(?P<d>[^<]+)</p>'
                     r'.*?<span class="textline">(?P<t>[^<]+)</span>')
    return out


def list_hyogo(today):
    out = []
    for y, m in months_back(today):
        out += html_items("https://www.sonoda-himeji.jp/news/1?d=%04d%02d" % (y, m),
                          r'<a href="(?P<u>[^"]+)">\s*<div class="news_time">(?P<d>[^<]+)</div>'
                          r'.*?<p class="news_txt">(?P<t>[^<]+)</p>')
        time.sleep(GAP_PAGE)
    return out


def list_nagoya(today):
    """整備状況表= 1 行が 1 件(掲載日/内容/区間/PDF)。区間の字を body にする"""
    url = "https://www.nagoyakeiba.com/info/race/dirt_course/index.html"
    flat = re.sub(r"\s+", " ", fetch(url))
    out = []
    for m in re.finditer(r'<tr data-href="(?P<u>[^"]+)"[^>]*>\s*<td>(?P<d>[^<]+)</td>\s*<td>(?P<t>[^<]*)</td>\s*'
                         r'<td class="pdf">(?P<s>[^<]*)</td>', flat):
        sec = unicodedata.normalize("NFKC", clean(m.group("s")))
        out.append({"d": norm_date(m.group("d")), "t": unicodedata.normalize("NFKC", clean(m.group("t"))),
                    "u": abs_url(url, m.group("u")), "body": ("区間 " + sec) if sec else "", "nagoya": True})
    return [r for r in out if r["d"]]


# ⛔ここが正本。venue= 固定の場 or 関数(題+本文 → 場)
def v_iwate(s):
    return "mizusawa" if "水沢" in s else "morioka" if "盛岡" in s else "iwate"


def v_hyogo(s):
    return "himeji" if "姫路" in s else "sonoda"


SITES = [
    {"id": "kanazawa", "venue": "kanazawa", "list": list_kanazawa},
    {"id": "iwate", "venue": v_iwate, "list": list_iwate, "topical": True},   # 題は「走路状況について」= 本文で絞る
    {"id": "nagoya", "venue": "nagoya", "list": list_nagoya, "topical": True},
    {"id": "hyogo", "venue": v_hyogo, "list": list_hyogo},
    {"id": "monbetsu", "venue": "monbetsu", "list": list_monbetsu},
    {"id": "banei", "venue": "obihiro", "list": list_banei},
    {"id": "urawa", "venue": "urawa", "list": list_urawa},
    {"id": "funabashi", "venue": "funabashi", "list": list_funabashi},
    {"id": "kawasaki", "venue": "kawasaki", "list": list_kawasaki},
    {"id": "kochi", "venue": "kochi", "list": list_kochi},
    {"id": "saga", "venue": "saga", "list": list_saga},
]


# ---------------------------------------------------------------- 本文 → 種別・text

def pick_text(body, title):
    """本文から作業の文を 1〜2 本(単位つきを優先)。無ければ ''"""
    if not body:
        return ""
    # 題の位置より後ろ(ナビの字を避ける)
    i = body.find(title[:12]) if title else -1
    txt = body[i + len(title[:12]):] if i >= 0 else body
    sents = [s.strip(" ・") for s in re.split(r"[。\n]", txt) if s.strip()]
    sents = [s for s in sents if len(s) <= 200 and not DROP.search(s)]
    withunit = [s for s in sents if UNIT.search(s) and (WORK.search(s) or "砂" in s or "内" in s)]
    work = [s for s in sents if WORK.search(s)]
    chosen = []
    for s in work[:1] + withunit[:2]:
        if s not in chosen:
            chosen.append(s)
    return "。".join(chosen[:2])[:180]


def classify(s):
    types = []
    if re.search(r"入替|入れ替|入換", s):
        types.append("一部入れ替え" if "一部" in s else "全部入れ替え")
    if re.search(r"補充|投入", s):
        types.append("砂の補充")
    if re.search(r"砂厚|馬場厚|クッション砂", s):
        types.append("砂厚の変更" if "変更" in s else "砂厚の調整")
    elif re.search(r"掻き出し|書き出し", s):
        types.append("砂厚の調整")
    if "路盤" in s:
        types.append("路盤整備")
    return types


def work_date(text, pub):
    """本文の「M月D日」(無ければ掲載日)"""
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text or "")
    if not m:
        return pub
    y = int(pub[:4])
    mo, d = int(m.group(1)), int(m.group(2))
    if mo - int(pub[5:7]) > 6:          # 1 月の記事で「12 月」= 前の年
        y -= 1
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return pub


def pdf_text(url):
    try:
        import pypdf
    except Exception:
        return ""
    try:
        r = pypdf.PdfReader(io.BytesIO(fetch_bytes(url)))
        return "\n".join((p.extract_text() or "") for p in r.pages)
    except Exception:
        return ""


def collect(site, today, prev_items=None):
    """1 源 → (items, err)。⛔落ちても例外を投げない"""
    try:
        rows = site["list"](today)
    except Exception as e:                       # noqa: BLE001
        return [], "%s: %s" % (type(e).__name__, e)
    if not rows:
        return [], "0 件(並びが変わった可能性)"
    cut = (today - dt.timedelta(days=DAYS)).isoformat()
    rows = [r for r in rows if r["d"] >= cut]
    out = []
    for r in rows:
        t = r["t"]
        if DROP.search(t):
            continue
        if not site.get("topical") and not HIT.search(t):
            continue
        body = r.get("body")
        if r.get("nagoya") and "測定" in t:
            continue                              # 砂厚測定は /sand の測定表(nar_sand_depth)に出ている= 拾わない
        if body is None:
            time.sleep(GAP_PAGE)
            try:
                u = r["u"]
                body = page_text(fetch(u)) if not u.lower().endswith(".pdf") else pdf_text(u)
            except Exception:                    # noqa: BLE001
                body = ""
        text = body if r.get("nagoya") else pick_text(body, t)
        if site.get("topical") and not r.get("nagoya") and not WORK.search(text or ""):
            continue                              # 岩手= 砂の話が無い走路状況は捨てる
        types = classify(t + " " + (text or ""))
        if not types:
            continue
        v = site["venue"](t + " " + (body or "")) if callable(site["venue"]) else site["venue"]
        k = work_date(text, r["d"]) if not r.get("nagoya") else r["d"]
        it = {"v": v, "k": k, "d": "%d/%d/%d" % tuple(int(x) for x in k.split("-")),
              "types": types, "text": (text or t).strip() or t, "src": [r["u"]],
              "swap": any("入れ替え" in x for x in types), "title": t}
        out.append(it)
    return out, None


def build(sites, prev, today):
    prev_items = list((prev or {}).get("items") or [])
    sources, new = {}, []
    for i, s in enumerate(sites):
        if i:
            time.sleep(GAP_SITE)
        rows, err = collect(s, today, prev_items)
        sources[s["id"]] = {"ok": False, "why": err} if err else {"ok": True, "n": len(rows)}
        new += rows
    have = {((x.get("src") or [""])[0], x.get("k")) for x in prev_items}
    added = [x for x in new if ((x["src"][0], x["k"]) not in have)]
    # 同じ回で重複したもの(同じ src・同じ日)も 1 本に
    seen, uniq = set(), []
    for x in added:
        key = (x["src"][0], x["k"])
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    items = sorted(prev_items + uniq, key=lambda x: (x.get("k") or ""), reverse=True)[:MAX_ITEMS]
    now = dt.datetime.now(JST).replace(microsecond=0).isoformat()
    return {"built": now, "sources": sources, "skipped": SKIPPED, "items": items}, uniq, new


# ---------------------------------------------------------------- 投入

def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def read_prev(base, key):
    req = urllib.request.Request(
        base.rstrip("/") + "/rest/v1/nar_meta?key=eq.%s&select=value" % META_KEY,
        headers={"apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        rows = json.loads(res.read() or b"[]")
    return rows[0]["value"] if rows else None


def upsert(base, key, value):
    body = json.dumps([{"key": META_KEY, "value": value}], ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/rest/v1/nar_meta?on_conflict=key", data=body, method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ書く(既定はドライラン)")
    ap.add_argument("--env", help="SUPABASE_URL / SUPABASE_SERVICE_KEY のある .env")
    ap.add_argument("--site", help="この id の源だけ試す")
    ap.add_argument("--today", help="YYYY-MM-DD(試験用)")
    a = ap.parse_args()

    sites = [s for s in SITES if not a.site or s["id"] == a.site]
    if not sites:
        print("そんな id はありません: %s" % a.site)
        return 2
    env = load_env(a.env) if a.env else os.environ
    base, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
    prev = None
    if base and key:
        try:
            prev = read_prev(base, key)
        except Exception as e:                   # noqa: BLE001
            print("前回の items を読めない(空から始める): %s" % e)
            if a.apply:
                # ⛔読めないまま書くと過去の items を消す= 書かずに落とす
                return 1
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    out, added, found = build(sites, prev, today)

    for k, v in out["sources"].items():
        print("  %-10s %s" % (k, ("ok n=%d" % v["n"]) if v["ok"] else ("NG " + str(v["why"]))))
    print("拾った %d 件(うち新規 %d)・items 計 %d  built %s"
          % (len(found), len(added), len(out["items"]), out["built"]))
    for x in found:
        print("  %s %-9s %s | %s | %s" % (x["k"], x["v"], "/".join(x["types"]), x["text"][:70], x["src"][0]))
    if not any(v["ok"] for v in out["sources"].values()):
        print("⛔1 源も取れませんでした= 空を書かずに失敗させます")
        return 2
    if not a.apply:
        print("(ドライラン。書くには --apply)")
        return 0
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY がありません")
        return 1
    try:
        st = upsert(base, key, out)
    except Exception as e:                       # noqa: BLE001
        print("投入に失敗: %s" % e)
        return 1
    print("nar_meta '%s' に入れました(HTTP %s)" % (META_KEY, st))
    return 0


if __name__ == "__main__":
    sys.exit(main())

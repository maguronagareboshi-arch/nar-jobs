# -*- coding: utf-8 -*-
"""本体 cloud: 各場の**主催者公式のお知らせ**を1か所に集めて nar_meta へ入れる(§139)。

読者が「どの場で何が告知されたか」を見逃さないための**索引**です。
⛔**本文は取りません。**集めるのは **見出し・日付・公式へのリンク・場**だけ。
   本文を写すと転載になり、§128 AdSense のポリシーにも当たります。読者は見出しで気づいて公式へ飛びます。

  出力 = nar_meta key='official_news' の value:
    {"built":"YYYY-MM-DDTHH:MM:SS+09:00",
     "sources":{"kochi":{"ok":true,"n":10},"hyogo":{"ok":false,"why":"..."} , …},
     "items":[{"v":["kochi"],"d":"2026-09-08","t":"見出し","u":"https://…"}, …]}   ← 新しい順・最大 200

  py -3 -X utf8 cloud/official_news.py                    # ドライラン(既定)。取れた中身を出すだけ
  py -3 -X utf8 cloud/official_news.py --site kochi       # 1 場だけ試す
  py -3 -X utf8 cloud/official_news.py --env pipeline/.env.nar --apply   # 実弾(nar_meta へ upsert)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply でだけ使う)
終了コード: 0 正常 / 1 投入失敗 / 2 **1 サイトも取れなかった**

⛔ 実地で分かったこと(2026-09-09 実測):
 1. **機械で読める配信(RSS)があるのは 3 サイトだけ**= 高知(?feed=rss2)・岩手(/feed/)・金沢(/feed/)。
    佐賀にも /feed/ はあるが**中身が 0 件**なので HTML から読む。
 2. **南関 4 場(浦和・船橋・大井・川崎)は対象外**。大井(tokyocitykeiba.com)は自動取得に **403** を返す=
    運営が明示的に断っている。⛔同じ運営の 4 場そろって取りに行かない。画面では公式へのリンクだけ出す。
 3. 1 サイトが落ちても**残りは出す**(fail-soft)。索引なので「全部か無か」にしない。
    ⚠ただし **1 サイトも取れなかったら exit 2**= 便が黙って空を書かない。
 4. 場と源は 1 対 1 ではない= 岩手(盛岡・水沢)と兵庫(園田・姫路)は 1 サイトで 2 場ぶん。
"""

import argparse
import datetime as dt
import html as _html
import json
import os
import re
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
META_KEY = "official_news"
MAX_ITEMS = 200          # 1 場あたりではなく全体。索引なのでこれ以上は要らない
PER_SITE = 20            # 1 サイトから取る上限(公式のトップに出ている件数ぶん)
TIMEOUT = 20
# ⛔これより古い告知は索引に入れない(§139 P1・2026-09-09 実測)。
#   岩手の RSS は**フィードは生きているのに中身が 4 年前で止まっていた**(最新 2022-09-20・ほかは 2017 年)。
#   日付で切らないと、古い記事が「取れた」顔をして新しい告知に混ざる= 索引としていちばん悪い壊れ方。
#   ⚠これは岩手固有の話ではない= どの源でも起こりうるので**日付で切る**のが正しい直し方。
MAX_AGE_DAYS = 120

# ---------------------------------------------------------------- 場の表(⛔ここが正本。足すのは 1 行)
# kind= 'rss'(<item> を読む) / 'html'(item_re で 1 件ずつ取る。名前つき group: u / d / t)
# venues= その源が受け持つ場の prefix(画面の場と同じ字)
SITES = [
    {"id": "kochi", "venues": ["kochi"], "kind": "rss",
     "url": "https://www.keiba.or.jp/?feed=rss2"},
    {"id": "iwate", "venues": ["morioka", "mizusawa"], "kind": "rss",
     "url": "https://www.iwatekeiba.or.jp/feed/"},
    {"id": "kanazawa", "venues": ["kanazawa"], "kind": "rss",
     "url": "https://www.kanazawakeiba.com/feed/"},
    {"id": "monbetsu", "venues": ["monbetsu"], "kind": "html",
     "url": "https://www.hokkaidokeiba.net/",
     "item_re": r'<li><a href="(?P<u>[^"]+)"><span class="time[^"]*">(?P<d>\d{4}\.\d{2}\.\d{2})</span>'
                r'.*?<span class="title">(?P<t>[^<]+)'},
    {"id": "nagoya", "venues": ["nagoya"], "kind": "html",
     "url": "https://www.nagoyakeiba.com/",
     "item_re": r'<a href="(?P<u>https://www\.nagoyakeiba\.com/news/[^"]+)">\s*<time>\s*'
                r'(?P<d>\d{4}\.\d{2}\.\d{2}).*?<p>(?P<t>[^<]+)</p>'},
    {"id": "banei", "venues": ["obihiro"], "kind": "html",
     "url": "https://banei-keiba.or.jp/",
     "item_re": r'<a href="(?P<u>[^"]+)"\s*><h1>(?P<t>[^<]+)</h1><time>(?P<d>\d{4}-\d{2}-\d{2})</time>'},
    {"id": "saga", "venues": ["saga"], "kind": "html",
     "url": "https://www.sagakeiba.net/",
     "item_re": r'<a class="p-newsCont__item[^"]*" href="(?P<u>[^"]+)">.*?'
                r'<span class="p-newsCont__date-num">(?P<d>\d{4}/\d{2}/\d{2}).*?'
                r'<p class="p-newsCont__text">(?P<t>[^<]+)</p>'},
    # 笠松だけ 'walk'= 一覧が JS なので**個別ページの番号を辿る**。⛔行儀のため 1 回の便で叩くのは
    # 前へ最大 FWD 個・後ろへ PER_SITE 個まで。存在しない番号は 200 で「404 Not Found」の題を返す。
    {"id": "kasamatsu", "venues": ["kasamatsu"], "kind": "walk",
     "url": "https://www.kasamatsu-keiba.com/news/detail/%d",
     "seed": 1480,      # 2026-09-09 実測で実在する番号。ここから前へ探して最新を見つける
     "miss": "404 Not Found",
     "title_re": r"<title>\s*(?P<t>.*?)\s*[|｜]\s*笠松けいば\s*</title>",
     "date_re": r"(?P<d>20\d{2}[./-]\d{1,2}[./-]\d{1,2})"},
]

# ⛔まだ取れない場(2026-09-09 実測)。⚠**中途半端に足さない**= 毎回失敗を報せる源は狼少年になる。
#   - 兵庫 園田/姫路(sonoda-himeji.jp)= 一覧も**個別ページも** JS 描画(番号を変えても題が変わらない)。
#   - 南関 4 場(浦和・船橋・大井・川崎)= 上の ⛔2 のとおり**取りに行かない**。
UNSUPPORTED = ["sonoda", "himeji", "urawa", "funabashi", "ooi", "kawasaki"]

# ---------------------------------------------------------------- 種別(⛔ここが正本。§138 の記事と同じ4つ)
# ユーザー(2026-09-09)「本当に利用価値があるものだけに絞りたい。騎手の限定騎乗とか馬の遠征とか」。
# 見出しの字だけで振り分けます(本文は取らないので)。⛔当たらないものは捨てずに kind=null で残し、
#   画面が「ほかに N 件」と数だけ出す= **情報を潰さない**(2026-07-24 の教訓)。
DROP = ["入札", "公告", "調達", "契約", "工事", "採用", "募集", "任免", "職員", "会計年度",
        "プレゼント", "贈呈", "フェア", "グルメ", "バス時刻", "時刻表", "駐車", "来場", "アンケート",
        # 毎回同じ形で出る定型= 索引に並べても読者の役に立たない(サイトが自前で持っている数字)
        "祭り", "ＤＡＹ", "DAY", "イベント", "リーディング", "本日の開催情報", "場外発売",
        "開催成績", "出来事", "ポイント"]
# ⚠**誰/何の話か**を先に見て、そのあと**何が起きたか**を見る。
#   こうしないと「近藤騎手 減量変更」が『変更』に引っかかって開催の話になる(2026-09-09 実測)。
KINDS = [
    ("person", ["期間限定騎乗", "騎手", "調教師", "厩務員", "騎乗停止", "免許", "負傷", "復帰",
                "引退", "デビュー", "減量"]),
    ("horse", ["遠征", "転入", "転出", "登録抹消", "出走予定馬", "能力検査", "能検", "繋養", "移籍",
               "出走表"]),
    ("venue", ["中止", "取り止め", "取りやめ", "順延", "馬場状態", "ナイター", "発走時刻",
               "開催日程", "薄暮", "代替", "変更"]),
    ("race", ["番組", "編成", "格付", "重賞", "優駿", "記念", "賞", "条件", "出馬",
              "シリーズ競走", "実施について"]),
]


def classify(title):
    """見出し → 'venue'|'person'|'horse'|'race' か None。⛔捨てる語が 1 つでもあれば None"""
    t = title or ""
    for w in DROP:
        if w in t:
            return None
    for kind, words in KINDS:
        for w in words:
            if w in t:
                return kind
    return None

# ---------------------------------------------------------------- 小道具


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        raw = res.read()
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def clean(s):
    """タグの中の字 → 画面に出す 1 行。⛔実体参照は戻すが、タグは作らない(画面側が escape する)"""
    s = re.sub(r"<[^>]*>", "", s or "")
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def norm_date(s):
    """'2026.09.08' / '2026-09-08' / '2026/09/08' / RSS の pubDate → 'YYYY-MM-DD'。読めなければ None"""
    s = (s or "").strip()
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        # RFC822(RSS の pubDate)= 'Mon, 08 Sep 2026 10:00:00 +0900'
        m = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})", s)
        if not m:
            return None
        mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        if m.group(2) not in mon:
            return None
        y, mo, d = int(m.group(3)), mon.index(m.group(2)) + 1, int(m.group(1))
    try:
        dt.date(y, mo, d)
    except ValueError:
        return None
    return "%04d-%02d-%02d" % (y, mo, d)


def abs_url(base, u):
    """相対 href を絶対に。⛔http は https に寄せない(公式の字のまま)"""
    u = (u or "").strip()
    if u.startswith("http"):
        return u
    if u.startswith("//"):
        return "https:" + u
    m = re.match(r"(https?://[^/]+)", base)
    root = m.group(1) if m else ""
    return root + (u if u.startswith("/") else "/" + u)


# ---------------------------------------------------------------- 取り出し


def parse_rss(text, base):
    out = []
    for block in re.findall(r"<item[^>]*>(.*?)</item>", text, re.S | re.I):
        t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S | re.I)
        u = re.search(r"<link[^>]*>(.*?)</link>", block, re.S | re.I)
        d = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", block, re.S | re.I)
        title = clean(t.group(1)) if t else ""
        link = clean(u.group(1)) if u else ""
        date = norm_date(d.group(1)) if d else None
        if title and link and date:
            out.append({"d": date, "t": title, "u": abs_url(base, link)})
    return out


def parse_html(text, base, item_re):
    out = []
    flat = re.sub(r"\s+", " ", text)
    for m in re.finditer(item_re, flat, re.S | re.I):
        g = m.groupdict()
        title, date = clean(g.get("t", "")), norm_date(g.get("d", ""))
        if title and date and g.get("u"):
            out.append({"d": date, "t": title, "u": abs_url(base, g["u"])})
    return out


FWD = 10          # walk: 種の番号から前へ探す上限(最新を見つけるため)


def parse_walk(site):
    """一覧が JS の場(笠松)= 個別ページの番号を辿る。⛔叩くのは前 FWD + 後ろ PER_SITE まで"""
    def one(n):
        try:
            t = fetch(site["url"] % n)
        except Exception:                        # noqa: BLE001
            return None
        if site["miss"] in t:
            return None
        flat = re.sub(r"\s+", " ", t)
        mt = re.search(site["title_re"], flat, re.S | re.I)
        md = re.search(site["date_re"], flat)
        title, date = clean(mt.group("t")) if mt else "", norm_date(md.group("d")) if md else None
        if not title or not date:
            return None
        return {"d": date, "t": title, "u": site["url"] % n}

    # ① 種から前へ= 最新の番号を見つける(2 回続けて空振りしたら打ち切り)
    top, miss = site["seed"], 0
    for n in range(site["seed"] + 1, site["seed"] + 1 + FWD):
        if one(n):
            top, miss = n, 0
        else:
            miss += 1
            if miss >= 2:
                break
    # ② そこから後ろへ= 新しい順に PER_SITE 件(欠番は飛ばす。空振りが続いたら打ち切り)
    out, miss = [], 0
    for n in range(top, max(0, top - PER_SITE * 2), -1):
        r = one(n)
        if r:
            out.append(r)
            miss = 0
            if len(out) >= PER_SITE:
                break
        else:
            miss += 1
            if miss >= 3:
                break
    return out


def collect(site):
    """1 サイト → (items, err)。⛔落ちても例外を投げない(索引は fail-soft)"""
    if site["kind"] == "walk":
        try:
            rows = parse_walk(site)
        except Exception as e:                   # noqa: BLE001
            return [], "walk: %s" % e
        return (rows, None) if rows else ([], "0 件(番号の並びが変わった可能性)")
    try:
        text = fetch(site["url"])
    except Exception as e:                       # noqa: BLE001
        return [], "%s: %s" % (type(e).__name__, e)
    try:
        rows = (parse_rss(text, site["url"]) if site["kind"] == "rss"
                else parse_html(text, site["url"], site["item_re"]))
    except Exception as e:                       # noqa: BLE001
        return [], "parse: %s" % e
    if not rows:
        return [], "0 件(並びが変わった可能性)"
    return rows[:PER_SITE], None


def build(sites, today=None):
    items, sources = [], {}
    seen = set()
    cut = ((dt.date.fromisoformat(today) if today else
            dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date())
           - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    for s in sites:
        rows, err = collect(s)
        if err:
            sources[s["id"]] = {"ok": False, "why": err}
            continue
        fresh = [r for r in rows if r["d"] >= cut]
        old = len(rows) - len(fresh)
        # ⛔全部が古い= その源は**更新が止まっている**。取れた顔をさせない(狼少年より悪い)
        sources[s["id"]] = ({"ok": True, "n": len(fresh), "old": old} if fresh else
                            {"ok": False, "why": "%d 件とも %d 日より古い(更新が止まっている可能性)"
                                                 % (old, MAX_AGE_DAYS)})
        for r in fresh:
            if r["u"] in seen:
                continue
            seen.add(r["u"])
            items.append({"v": s["venues"], "d": r["d"], "t": r["t"], "u": r["u"],
                          "k": classify(r["t"])})
    # 新しい順。同じ日は場の並び(表の順)のまま= ビルドごとに揺れない
    items.sort(key=lambda r: r["d"], reverse=True)
    # ⛔溢れるときは**種別の付いたものを先に残す**= ノイズが価値ある告知を押し出さない。
    #   捨てるのではなく順番の話なので、余りは kind=null のまま後ろに残る(情報を潰さない)
    keep = [r for r in items if r["k"]][:MAX_ITEMS]
    rest = [r for r in items if not r["k"]][:max(0, MAX_ITEMS - len(keep))]
    out = sorted(keep + rest, key=lambda r: r["d"], reverse=True)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    return {"built": now.replace(microsecond=0).isoformat(),
            "sources": sources, "items": out}


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
    ap.add_argument("--site", help="この id のサイトだけ試す")
    a = ap.parse_args()

    sites = [s for s in SITES if not a.site or s["id"] == a.site]
    if not sites:
        print("そんな id はありません: %s(あるのは %s)" % (a.site, "/".join(s["id"] for s in SITES)))
        return 2
    out = build(sites)

    ok = [k for k, v in out["sources"].items() if v.get("ok")]
    ng = [(k, v.get("why")) for k, v in out["sources"].items() if not v.get("ok")]
    for k, why in ng:
        print("⚠ %-9s 取れず: %s" % (k, why))
    kept = [r for r in out["items"] if r["k"]]
    print("取れた: %d/%d サイト・%d 件(うち種別あり %d・その他 %d)  built %s"
          % (len(ok), len(sites), len(out["items"]), len(kept),
             len(out["items"]) - len(kept), out["built"]))
    label = {"venue": "開催", "person": "騎手", "horse": "馬", "race": "レース"}
    print("--- 種別の付いたもの(画面に出す) ---")
    for r in kept[:24]:
        print("  %s %-4s %-10s %s" % (r["d"], label[r["k"]], "/".join(r["v"]), r["t"][:44]))
    print("--- その他(既定では出さない・数だけ見せる) ---")
    for r in [x for x in out["items"] if not x["k"]][:8]:
        print("  %s      %-10s %s" % (r["d"], "/".join(r["v"]), r["t"][:44]))
    if not ok:
        print("⛔1 サイトも取れませんでした= 空を書かずに失敗させます")
        return 2

    if not a.apply:
        print("(ドライラン。書くには --env pipeline/.env.nar --apply)")
        return 0

    env = load_env(a.env) if a.env else os.environ
    base, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
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

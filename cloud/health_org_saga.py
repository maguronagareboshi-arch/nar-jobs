# -*- coding: utf-8 -*-
"""統合ビューア cloud: 主催者公式の「出来事」— 佐賀(§110)。

入口= 公式の RSS(`/news/feed/?s=今日の出来事`)。1 item = 1 開催日で、`content:encoded` は
節ごとの `<p>` に分かれ、節見出しだけが `<span style="border: 1px solid;">…</span>` で囲まれている:

    <p><span …>出走取消</span> 1R / 5番 ムーンパスフラワー(◯◯騎手) / 感冒のため</p>
    <p><span …>競走中止</span> 4R / 11番 トントゥ(◯◯騎手) / 疾病を発症したため、3コーナーで競走を中止 /
       馬:右第一指骨骨折 / 騎手:異状なし</p>

⛔記事ページは取りに行かない(本文が RSS に丸ごと入っている)。
⛔**節見出しの allowlist で読む**= 番組除外(制限タイムオーバー)・制裁・騎手変更・再検査には触らない。
⛔騎手名は残さない= 馬名の後ろの「(◯◯騎手)」と「騎手:…」の行は detail に入れない(人の情報)。
⛔理由の文言は公式のまま。読めない行は捨てて数えるだけ。

実測(2026-09-05・RSS 8 頁 80 件・2026 は 76 件): 節は 番組除外40 競走中疾病35 競走中止34 制裁29
競走除外24 出走取消21 騎手変更20 再検査10 …。「本日の掲載事項はございません」の日もある。
"""
import hashlib
import html as html_mod
import re
import unicodedata
import urllib.parse

SLUG = "saga"
TRACK = "佐賀"
SOURCE_KIND = "saga_official"      # ⛔器の allowlist(private.nar_health_race_kind_ok)の語
PARSER_VERSION = "org-saga-1.0"

FEED = "https://www.sagakeiba.net/news/feed/?s=" + urllib.parse.quote("今日の出来事")
MAX_PAGES = 8                      # 1 頁 10 件。実測でこれだけあれば 2026 は全部入る(76 件)
MAX_RACE_NO = 12

# 節見出し → status。None = 競走後の診断(競走中疾病)。⛔ここに無い節は読まない
SECTIONS = {
    "出走取消": "出走取消",
    "競走除外": "競走除外",
    "競走中止": "競走中止",
    "競走中疾病": None,
}

_ITEM = re.compile(r"(?is)<item\b.*?</item\s*>")
_CDATA = re.compile(r"(?s)^\s*<!\[CDATA\[(.*?)\]\]>\s*$")
_BLOCK = re.compile(r"(?is)<p\b[^>]*>(.*?)</p\s*>")
_SPAN = re.compile(r"(?is)<span\b[^>]*>(.*?)</span\s*>")
# 題「今日の出来事　9月3日(木)」
_TITLE_MD = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_RACE_LINE = re.compile(r"^(\d{1,2})\s*R$")
# 「5番 ムーンパスフラワー(◯◯騎手)」。⛔括弧の中は騎手= 取らない
_IDENT = re.compile(r"^(\d{1,2})\s*番\s*([^\s()（）]{1,40})")
_RIDER_LINE = re.compile(r"^騎手\s*[:：]")

MONTHS = {name: i + 1 for i, name in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_PUB = re.compile(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})")


def _tag(name, s):
    m = re.search(r"(?is)<%s[^>]*>(.*?)</%s\s*>" % (name, name), s or "")
    return _CDATA.sub(r"\1", m.group(1)) if m else ""


def _plain(value):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", str(value or ""))
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|td|th|strong|span)\s*>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = unicodedata.normalize("NFKC", html_mod.unescape(s))
    lines = (re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n"))
    return "\n".join(x for x in lines if x)


def _doc_hash(text):
    packed = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _iso(y, m, d):
    try:
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def _valid(iso):
    if not iso:
        return False
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31
    except ValueError:
        return False


def _pub_date(value):
    m = _PUB.search(str(value or ""))
    if not m or m.group(2) not in MONTHS:
        return None
    iso = _iso(m.group(3), MONTHS[m.group(2)], m.group(1))
    return iso if _valid(iso) else None


def _race_date(title, posted):
    """題の「9月3日」を開催日に。年は掲載日から(年をまたぐ号は 1 年戻す)。"""
    m = _TITLE_MD.search(unicodedata.normalize("NFKC", title or ""))
    if not m or not posted:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    py, pm, pd = (int(x) for x in posted.split("-"))
    iso = _iso(py, month, day)
    if not _valid(iso):
        return None
    if (month, day) > (pm, pd):
        iso = _iso(py - 1, month, day)
    return iso if _valid(iso) else None


def _page(fetch, url):
    """一覧の 1 頁。⛔一時的に取れないことがあるので **1 回だけ引き直す**(2026-09-05 実測)。"""
    return fetch(url) or fetch(url)


# ---------------------------------------------------------------- 一覧

def list_documents(fetch, since, until):
    """RSS を頁送りして [(開催日, 記事の URL, 本文)] を返す。⛔本文を同梱= 記事ページは取りに行かない。"""
    out = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        body = _page(fetch, FEED + ("&paged=%d" % page if page > 1 else ""))
        if not body:
            continue        # ⛔1 頁の一時的な失敗で窓を黙って縮めない(古い頁は残っている)
        items = _ITEM.findall(body)
        if not items:
            break
        oldest = None
        for item in items:
            title = _plain(_tag("title", item)).strip()
            link = _plain(_tag("link", item)).strip()
            posted = _pub_date(_tag("pubDate", item))
            if "出来事" not in title:
                continue
            race_date = _race_date(title, posted)
            if not race_date:
                continue
            if oldest is None or race_date < oldest:
                oldest = race_date
            if link in seen or not (since <= race_date <= until):
                continue
            seen.add(link)
            out.append((race_date, link, _tag("content:encoded", item) or _tag("description", item)))
        if oldest is not None and oldest < since:
            break
    out.sort()
    return out


# ---------------------------------------------------------------- 本文

def parse(html):
    """本文 1 件 → {'rows': [...], 'doc_hash': …, 'skipped': N}。節ごとの <p> を 1 つずつ読む。"""
    raw = str(html or "")
    blocks = _BLOCK.findall(raw) or [raw]
    rows = []
    skipped = 0
    for block in blocks:
        span = _SPAN.search(block)
        if not span:
            continue                                   # 題の塊(今日の出来事 / 第◯回…)
        name = _plain(span.group(1)).strip()
        if name not in SECTIONS:
            continue                                   # ⛔番組除外・制裁・騎手変更などには触らない
        status = SECTIONS[name]
        rest, n = _walk(_plain(_SPAN.sub(" ", block, count=1)), status)
        rows.extend(rest)
        skipped += n
    return {"rows": rows, "doc_hash": _doc_hash(_plain(raw)), "skipped": skipped}


def _walk(text, status):
    """節 1 つぶんの行を読む。⛔R は行「1R」で切り替わる・理由は次の馬まで。"""
    rows = []
    skipped = 0
    race_no = None
    cur = None
    for line in text.split("\n"):
        m = _RACE_LINE.match(line)
        if m:
            cur = _close(cur, rows)
            race_no = int(m.group(1))
            continue
        ident = _IDENT.match(line)
        if ident:
            cur = _close(cur, rows)
            if race_no is None or not (1 <= race_no <= MAX_RACE_NO):
                skipped += 1
                continue
            cur = {"race_no": race_no, "umaban": int(ident.group(1)),
                   "horse_name": unicodedata.normalize("NFKC", ident.group(2)).strip(),
                   "horse_code": None, "status": status, "detail": "", "reported_date": None}
            continue
        if cur is not None and not _RIDER_LINE.match(line):     # ⛔「騎手:…」は人の情報
            cur["detail"] = (cur["detail"] + ("。" if cur["detail"] else "") + line).strip()
    _close(cur, rows)
    kept = [r for r in rows if r["detail"]]
    return kept, skipped + (len(rows) - len(kept))


def _close(cur, rows):
    if cur is not None:
        rows.append(cur)
    return None

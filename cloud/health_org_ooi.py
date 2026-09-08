# -*- coding: utf-8 -*-
"""統合ビューア cloud: 主催者公式の「出来事」— 大井(§110)。

入口= 公式の RSS(`/news/feed/?s=出来事`)。1 item = 1 開催日で、`content:encoded` の本文がこの形:

    ≪出走取消≫
    第7競走 8号馬 グロワールスカイ
    疾病(左前挫跖)
    ≪競走中止≫
    第8競走 10号馬 リコーファルコン
    10号馬リコーファルコン号は、第4コーナーにおいて馬体に故障を生じたので、競走を中止しました。(右前肢跛行)

⛔記事ページは取りに行かない(本文が RSS に丸ごと入っている)= 通信は一覧の頁数だけ。
⛔理由の文言は公式のまま(切らない・言い換えない)。⛔読めない行は捨てて数えるだけ。
⛔**節見出しの allowlist で読む**= 知らない節(騎手の処分・お知らせ)には触らない。

実測(2026-09-05・RSS 8 頁 80 件): 節は ≪出走取消≫44 ≪出走制限≫35 ≪騎手変更≫31 ≪競走除外≫29
≪競走中止≫29 ≪戒告≫23 ≪騎乗停止≫6 ≪出走停止≫4 …。⛔騎手の節は**人の名前**なので読まない
(識別行が「第1競走 ◯◯騎手」で「号馬」が無いため、正規表現でも当たらない)。
"""
import hashlib
import html as html_mod
import re
import unicodedata
import urllib.parse

SLUG = "ooi"
TRACK = "大井"
SOURCE_KIND = "ooi_official"       # ⛔器の allowlist(private.nar_health_race_kind_ok)の語
PARSER_VERSION = "org-ooi-1.0"

FEED = "https://www.tokyocitykeiba.com/news/feed/?s=" + urllib.parse.quote("出来事")
MAX_PAGES = 8                      # 1 頁 10 件。実測でこれだけあれば 2026 は全部入る(67 件)
MAX_RACE_NO = 12

# ≪節≫ → status。None = 競走後の診断(出走制限)。⛔ここに無い節は読まない
SECTIONS = {
    "出走取消": "出走取消",
    "競走除外": "競走除外",
    "競走中止": "競走中止",
    "出走制限": None,
}

_ITEM = re.compile(r"(?is)<item\b.*?</item\s*>")
_CDATA = re.compile(r"(?s)^\s*<!\[CDATA\[(.*?)\]\]>\s*$")
# 題「第8回開催5日目(9/4)の出来事」
_TITLE_MD = re.compile(r"[(（]\s*(\d{1,2})\s*/\s*(\d{1,2})\s*[)）]")
_HEAD = re.compile(r"^[《≪<]{1,2}(.+?)[》≫>]{1,2}$")
# 「第7競走 8号馬 グロワールスカイ」。⛔「号馬」が要る= 騎手の行(第1競走 ◯◯騎手)は当たらない。
# ⚠空白は**あてにしない**= 実測に「第2競走7号馬 ジョテイ」(2026-07-01)があり、\s+ だと 1 頭落ちる
_IDENT = re.compile(r"^第\s*(\d{1,2})\s*競走\s*(\d{1,2})\s*号馬\s*(\S.*)$")
# 長い書き方の頭「10号馬リコーファルコン号は、」= 馬名と馬番なので detail から外す
_LEAD = re.compile(r"^\s*\d{1,2}号馬.{1,40}?号は[、,]\s*")
_SKIP_LINE = re.compile(r"^(詳細はこちら|本日は、.*ございませんでした。?)$")

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
    """RFC822 の pubDate → 'YYYY-MM-DD'。⛔標準ライブラリの email に頼らず数字だけ読む。"""
    m = _PUB.search(str(value or ""))
    if not m or m.group(2) not in MONTHS:
        return None
    iso = _iso(m.group(3), MONTHS[m.group(2)], m.group(1))
    return iso if _valid(iso) else None


def _race_date(title, posted):
    """題の「(9/4)」を開催日に。年は掲載日から(年をまたぐ号は 1 年戻す)。"""
    m = _TITLE_MD.search(unicodedata.normalize("NFKC", title or ""))
    if not m or not posted:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    py, pm, pd = (int(x) for x in posted.split("-"))
    iso = _iso(py, month, day)
    if not _valid(iso):
        return None
    if (month, day) > (pm, pd):                 # 1/1 に載る 12/31 の号
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
        body = _page(fetch, FEED + "&paged=%d" % page)
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
            if "出来事" not in title:            # 同じ検索に別のお知らせが混ざる(実測 80 件中 2 件)
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
            break                                # RSS は新しい順= これ以上は範囲外
    out.sort()
    return out


# ---------------------------------------------------------------- 本文

def parse(html):
    """本文 1 件 → {'rows': [...], 'doc_hash': …, 'skipped': N}。"""
    text = _plain(html)
    rows = []
    skipped = 0
    status = False                                # False = まだ節の外 / None も値なので区別する
    cur = None
    for line in text.split("\n"):
        head = _HEAD.match(line)
        if head:
            name = head.group(1).strip()
            cur = _close(cur, rows)
            status = SECTIONS[name] if name in SECTIONS else False
            continue
        ident = _IDENT.match(line)
        if ident:
            cur = _close(cur, rows)
            if status is False:
                continue                          # 知らない節の中= 触らない
            race_no = int(ident.group(1))
            if not (1 <= race_no <= MAX_RACE_NO):
                skipped += 1
                continue
            cur = {"race_no": race_no, "umaban": int(ident.group(2)),
                   "horse_name": unicodedata.normalize("NFKC", ident.group(3)).strip(),
                   "horse_code": None, "status": status, "detail": "", "reported_date": None}
            continue
        if cur is not None and not _SKIP_LINE.match(line):
            cur["detail"] = (cur["detail"] + _LEAD.sub("", line)).strip()
    _close(cur, rows)
    kept = [r for r in rows if r["detail"]]
    skipped += len(rows) - len(kept)              # 理由の行が無かった馬は書かない
    return {"rows": kept, "doc_hash": _doc_hash(text), "skipped": skipped}


def _close(cur, rows):
    if cur is not None:
        rows.append(cur)
    return None

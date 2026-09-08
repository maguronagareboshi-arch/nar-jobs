# -*- coding: utf-8 -*-
"""統合ビューア cloud: 主催者公式の「出来事」— 高知(§109)。

入口= 高知けいば公式の「除外・取消」カテゴリ(`?cat=33`)。1 記事 = 1 開催日で、本文はこの形:

    令和8年度 第6回 第6日
    第3競走 11番 パウラメロディーア(右前跛行)
    第4競走 5番 キョウエイシュバル(右前肢跛行)
    は、疾病のため出走取消となりました。

⛔理由の文言は公式のまま(切らない・言い換えない)。⛔読めない行は捨てて数えるだけ(例外にしない)。
⛔原本は保存しない。⛔記事の下の「関連記事」は**別の記事の本文**なので本体から外す(年をまたいで混ざる)。

実測(2026-09-05・580 記事): 題は「〈年〉月日の出走取消 / 競走除外(2〜4)」の 2 種類だけ。
締めは「は、〈理由〉のため〈出走取消|競走除外〉となりました」で、理由は 疾病・馬体故障・能力影響・
監視区域外逸走・枠入不能・騎手負傷・事故・公正確保 など 20 通り以上ある= **理由では絞らない**。
⚠このカテゴリに **競走中止と競走後の診断は無い**(実測 0 件)。status の対応だけ用意してある。
"""
import hashlib
import html as html_mod
import re
import unicodedata

SLUG = "kochi"
TRACK = "高知"
SOURCE_KIND = "kochi_official"     # ⛔器の allowlist(private.nar_health_race_kind_ok・Codex 9/5 適用済み)の語に合わせる
PARSER_VERSION = "org-kochi-1.0"

BASE = "https://www.keiba.or.jp/"
CATEGORY = BASE + "?cat=33"
MAX_PAGES = 20                     # 頁送りの上限(1 頁 29 記事)
MAX_RACE_NO = 12                   # 器の制約(race_no は 1〜12)

_CARD = re.compile(r"(?is)<article\b.*?</article\s*>")
_PERMALINK = re.compile(r'(?i)href="(https?://www\.keiba\.or\.jp/\?p=(\d+))"')
_SLASH_DATE = re.compile(r"(20\d{2})/(\d{1,2})/(\d{1,2})")
# 題「2026年8月2日の出走取消」/「10月16日の出走取消」(年が無い題が実在する)
_TITLE_DATE = re.compile(r"(?:(20\d{2})年)?\s*(\d{1,2})月\s*(\d{1,2})日の(?:出走取消|競走除外|競走中止)")
# 「第3競走 11番 パウラメロディーア(右前跛行)」。⛔馬名に空白・括弧・読点は入らない
_IDENT = re.compile(
    r"第\s*(\d{1,2})\s*競走\s*(\d{1,2})\s*番\s*"
    r"([^\s()、,。\n]{1,40})"
    r"(?:\s*\(([^)\n]{1,120})\))?")
# 締めの一文。理由の言い回しは多いので「〜となりました」までを丸ごと取る
_CLAUSE = re.compile(
    r"(?:は[、,]?\s*)?([^。\n]{1,100}?(出走取消|競走除外|競走中止)となりました)")
# 公式が馬名に張っている主催者リンク(k_lineageLoginCode= 血統登録番号 11 桁)
_LINEAGE = re.compile(
    r"(?is)<a\b[^>]*k_lineageLoginCode=(\d{11})[^>]*>(.*?)</a\s*>")
# 本文の切れ目。⛔「関連記事」より下は別の記事
_CONTENT_START = 'id="the-content"'
_CONTENT_END = ("widget-under-article", "under-entry-body", "related-entries", "<footer")


def _plain(value):
    """タグを落として 1 行 1 文にする。⛔<br> と </p> は改行にする(行が繋がると読めない)。"""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", str(value or ""))
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|td|th|article|section)\s*>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = unicodedata.normalize("NFKC", html_mod.unescape(s))
    lines = (re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n"))
    return "\n".join(x for x in lines if x)


def _content(html):
    """記事本文だけを切り出す。見つからなければ渡されたものをそのまま使う(断片の test 用)。"""
    s = str(html or "")
    i = s.find(_CONTENT_START)
    if i < 0:
        return s
    end = len(s)
    for mark in _CONTENT_END:
        j = s.find(mark, i)
        if 0 <= j < end:
            end = j
    return s[i:end]


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


def _race_date(title, posted):
    """題の「◯月◯日」を開催日に。年が無い題は記事の年から(年をまたぐ号は 1 年戻す)。"""
    m = _TITLE_DATE.search(unicodedata.normalize("NFKC", title or ""))
    if not m:
        return None
    year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    if year:
        return _iso(year, month, day) if _valid(_iso(year, month, day)) else None
    if not posted:
        return None
    py, pm, pd = (int(x) for x in posted.split("-"))
    iso = _iso(py, month, day)
    if not _valid(iso):
        return None
    # 記事より**先の日付**になったら前年の記事(1/2 に 12/31 の号が出る)
    if (month, day) > (pm, pd):
        iso = _iso(py - 1, month, day)
    return iso if _valid(iso) else None


def _posted_date(text):
    """記事の掲載日(本文の「2026/8/2」)。見つからなければ None。"""
    m = _SLASH_DATE.search(text or "")
    if not m:
        return None
    iso = _iso(m.group(1), m.group(2), m.group(3))
    return iso if _valid(iso) else None


# ---------------------------------------------------------------- 一覧

def list_documents(fetch, since, until):
    """`?cat=33` を頁送りして [(開催日, 記事の URL)] を返す。⛔since より古い頁まで進まない。"""
    out = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        url = CATEGORY + ("&paged=%d" % page if page > 1 else "")
        body = fetch(url)
        if not body:
            break
        cards = _CARD.findall(body)
        if not cards:
            break
        oldest = None
        found = 0
        for card in cards:
            link = _PERMALINK.search(card)
            if not link:
                continue
            found += 1
            text = _plain(card)
            posted = _posted_date(text)
            title = text.split("\n")[0] if text else ""
            race_date = _race_date(title, posted)
            if not race_date:
                continue
            if oldest is None or race_date < oldest:
                oldest = race_date
            if link.group(1) in seen:
                continue
            if since <= race_date <= until:
                seen.add(link.group(1))
                out.append((race_date, link.group(1)))
        if not found or (oldest is not None and oldest < since):
            break                       # 一覧は新しい順= これ以上さかのぼっても範囲外
    out.sort()
    return out


# ---------------------------------------------------------------- 記事

def parse(html):
    """記事 1 枚 → {'rows': [...], 'doc_hash': …, 'skipped': N}。

    rows の 1 件 = {race_no, umaban, horse_name, horse_code, status, detail, reported_date}
    """
    body = _content(html)
    text = _plain(body)
    posted = _posted_date(_plain(html))
    codes = _lineage_codes(body)

    idents = list(_IDENT.finditer(text))
    clauses = [(m.start(), m.group(1).strip(), m.group(2)) for m in _CLAUSE.finditer(text)]
    rows = []
    skipped = 0
    for m in idents:
        race_no = int(m.group(1))
        umaban = int(m.group(2))
        name = unicodedata.normalize("NFKC", m.group(3)).strip()
        paren = (m.group(4) or "").strip()
        clause = next((c for c in clauses if c[0] >= m.end()), None)
        if clause is None or not name or not (1 <= race_no <= MAX_RACE_NO):
            skipped += 1
            continue
        detail = ("(%s)は、%s。" % (paren, clause[1])) if paren else ("%s。" % clause[1])
        rows.append({
            "race_no": race_no,
            "umaban": umaban,
            "horse_name": name,
            "horse_code": codes.get("".join(name.split())),
            "status": clause[2],
            "detail": detail,
            "reported_date": posted,
        })
    return {"rows": rows, "doc_hash": _doc_hash(text), "skipped": skipped}


def _lineage_codes(body):
    """公式が馬名に張っているリンクから 血統登録番号(11 桁)を拾う。

    ⛔同じ記事で同じ名前に別の番号が付いていたら**捨てる**(取り違えない)。
    """
    out = {}
    bad = set()
    for m in _LINEAGE.finditer(str(body or "")):
        name = "".join(unicodedata.normalize("NFKC", _plain(m.group(2))).split())
        code = m.group(1)
        if not name:
            continue
        if name in out and out[name] != code:
            bad.add(name)
        out[name] = code
    for name in bad:
        out.pop(name, None)
    return out

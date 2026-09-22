# -*- coding: utf-8 -*-
"""本体 cloud: 主催者公式の「出来事」— 大井(§110)。

入口= **表 `nar_fetch_raw`**(§195c)。先方の RSS を取るのは Cloudflare の Worker
(nar-jobs `workers/fetch-relay`)の役で、ここは置かれた生の本文を読むだけ(⛔先方へは 1 本も行かない)。
1 item = 1 開催日で、`content:encoded` の本文がこの形:

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
import datetime as dt
import hashlib
import html as html_mod
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request

SLUG = "ooi"
TRACK = "大井"
SOURCE_KIND = "ooi_official"       # ⛔器の allowlist(private.nar_health_race_kind_ok)の語
PARSER_VERSION = "org-ooi-1.0"

# §195c 入口= **表 `nar_fetch_raw`**(先方へは行かない)。
# 取るのは Cloudflare の Worker(nar-jobs `workers/fetch-relay`)の役= 06:00 JST に 8 頁を取って
# 生のまま (source, key) = ('ooi_official', 'paged=N') で置く。便はその本文を読むだけ。
# なぜ分けるのか(§195 段 1)= **GitHub ランナーの IP は先方に 403**(UA を替えても・curl でも・HTML でも)。
# Cloudflare 側からは便と同じ名乗りのままで 200。⛔UA は偽らない・⛔関門には触らない。
# ⛔読み解き(parse)は便に残す= 直すときはいつもこちら側。
RAW_TABLE = "nar_fetch_raw"
RAW_FRESH_DAYS = 3                 # これより古い頁は「取れず」に数える(Worker が止まった合図)
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


def log(msg):
    """⛔置き場は書かない(health_org.py の log と同じ出し方)。"""
    print(msg, flush=True)


def _utc(value):
    """PostgREST の timestamptz → aware な datetime / 読めなければ None(純関数)。"""
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        got = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=dt.timezone.utc)


def fresh_pages(rows, now=None, fresh_days=RAW_FRESH_DAYS):
    """表の行 → ({'paged=N': 本文}, [捨てた理由])(純関数)。

    ⛔採るのは **status 200 かつ本文があり、fetched_at が fresh_days 日以内**の頁だけ。
    ⛔理由に URL は入れない(置き場を書かない)。
    """
    at = now or dt.datetime.now(dt.timezone.utc)
    pages, dropped = {}, []
    for row in rows or []:
        key = str((row or {}).get("key") or "")
        if not key:
            continue
        status = row.get("status")
        got = _utc(row.get("fetched_at"))
        age = None if got is None else (at - got).total_seconds() / 86400.0
        if status != 200 or not row.get("body"):
            dropped.append("%s status=%s" % (key, status))
        elif age is None:
            dropped.append("%s 取った時刻が読めない" % key)
        elif age > fresh_days:
            dropped.append("%s %.1f 日前(古い)" % (key, age))
        else:
            pages[key] = row["body"]
    return pages, sorted(dropped)


def read_raw(source=SOURCE_KIND):
    """表 `nar_fetch_raw` の その出どころの行を 1 本で。⛔service key が要る(anon では読めない)。"""
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not base or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無いので %s を読めません" % RAW_TABLE)
    path = ("%s/rest/v1/%s?select=key,status,body,fetched_at&source=eq.%s&limit=100"
            % (base, RAW_TABLE, urllib.parse.quote(str(source), safe="")))
    req = urllib.request.Request(path, headers={
        "apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as res:
        body = res.read().decode("utf-8")
    return json.loads(body) if body else []


# ---------------------------------------------------------------- 一覧

def list_documents(fetch, since, until, rows=None):
    """表に置かれた RSS 8 頁を読んで [(開催日, 記事の URL, 本文)] を返す。

    ⛔**先方へは 1 本も行かない**(取るのは Worker の役)= 引数 `fetch` は使わない(呼び出し側の形をそのまま受ける)。
    ⛔1 頁も使えないときだけ例外= 便の段が赤くなる(0 件で緑のまま気づかなかった §195 の反省)。
    """
    got = read_raw() if rows is None else rows
    pages, dropped = fresh_pages(got)
    for why in dropped:
        log("  ⚠ 使えない頁 %s" % why)
    if not pages:
        # ⛔「取れなかった」であって「壊れた」ではない= 呼び出し側が exit 0 にできるよう印を付ける
        #   (先方は GitHub ランナーの IP に 403・取るのは Worker の役。§195/§195c)
        err = RuntimeError("%s に使える頁がありません(先方 403 / Worker が止まっている疑い)" % RAW_TABLE)
        err.source_unavailable = True
        raise err
    out = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        body = pages.get("paged=%d" % page)
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

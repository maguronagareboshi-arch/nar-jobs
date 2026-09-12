# -*- coding: utf-8 -*-
"""本体 cloud: 制裁(戒告・過怠金・騎乗停止)を成績 PDF から読む(§111)。

§89(cloud/horse_health.py)は**馬**の疾病だけを読み、騎手の行は落としている(`_rider_only`)。
こちらは同じ PDF から**人**(騎手・調教師)への制裁だけを読む。⛔horse_health.py は触らず、
PDF の取り方(`download_pdf` / `pdf_pages` / `pdf_url` / `NAR_PDF` / `UA` / `HostLimiter`)と
レース番号の割り出し(`_segments`)を **import して使う**(2 か所目を作らない・§5.4)。

  py -3.12 -X utf8 cloud/penalties.py --start 2026-08-20 --end 2026-09-04 --env pipeline/.env.nar
  py -3.12 -X utf8 cloud/penalties.py --apply          # 既定= 直近 14 日
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--env が無ければ環境変数だけで動く)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔原本(PDF)は保存しない。⛔読めない行は数えるだけで止めない。⛔期間は**書いてある形だけ**読む(推測しない)。
⛔`suspension_from/through` は「停止期間」= **騎乗停止も賞典停止も**入る(調教師の戒告に付く
  「令和N年M月D日から…まで賞典を停止」もここに入る)。⛔騎乗停止だけの列ではない(§111b #5)。
⛔価値判断はしない= 数えるのは件数だけで、人ごとの多い少ないは出さない(並べ替えは日付順)。

実測(2026-09-05・15 場ぶん 1 日ずつ)で分かった書き方:
  川崎  制裁【制裁】調教師◯◯は…戒告され、令和8年8月21日から令和8年9月7日までの実効2日間賞典を停止された。
  船橋  制裁「騎手◯◯は、…扶助操作に適切を欠いた(…)ため、令和8年9月1日、2日の2日間騎乗停止した。」
  園田  制裁11番◯◯号は、競走中鼻出血を発症したため出走制限となった。  ← **馬**の話= 読まない
  名古屋 制裁(タイムオーバー)3号馬◯◯号は、令和8年9月18日まで出走できない。 ← 同上
  笠松  制裁(発走調教再審査)第2号馬◯◯号は、… ← 同上
⛔PDF の字は 1 字ずつ空白で割れる= **空白を全部落としてから**読む。
⛔「制裁」の行は 売得金 と コーナー通過順 の間にあり、次の見出しまで**折り返して続く**。
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from horse_health import (                                          # noqa: E402
    NAR_PDF, UA, HostLimiter, _segments, download_pdf, pdf_pages, pdf_url,
)

PARSER_VERSION = "penalties-1.2"      # §111c 馬名(本文の馬番 → 名簿の馬名)を足した
JST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_DAYS = 14
UPSERT_CHUNK = 500
DETAIL_MAX = 200

# 「制裁」の行から、次のこの見出しまでが 1 かたまり(⛔見出しの語は実物から)
# §111b #4 「変更後の騎乗変更」以下を追加。⛔行頭でだけ止める(文の中に出ても止めない)
_ROW_HEAD = re.compile(
    r"^(コーナー通過順|ハロンタイム|上がり|通過順|払戻金|売得金|発売票数|返還票数|差引票数|"
    r"事故|備考|レコード|単勝式|複勝式|枠連|馬連|拡馬複|三連|レース|天候|走破|区分|"
    r"変更後の騎乗変更|騎乗変更|出走取消|競走除外|競走中止|\d+/\s*\d+$)")
_PENALTY_HEAD = re.compile(r"^制裁")
# §111b #3 頁の飾り。⛔**行全体**がこれのときだけ落とす(本文の中の日付は落とさない)。
#   実測(高知 2026-01-11・名古屋 2026-03-26・佐賀 2026-04-05/04-26・名古屋 2026-05-19 の 5 件):
#   頁の頭が「2026/01/12 09:30作成」「40/ 40」の 2 行で、その次の行に前の頁の**続き**が
#   「制裁」のラベルつきで来る= ここで切ると文が途中で終わる。
#   ⛔頁番号だけの行は今までどおりかたまりを閉じる(_ROW_HEAD)= 落とすのは**脚注の直後**だけ。
_FOOTNOTE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}\s*作成$")
_PAGE_NO = re.compile(r"^\d+/\s*\d+$")
# §111b #1 公式の飾り。先頭の【制裁】「」と、末尾の」を落とす。⛔(…)は公式の文言なので落とさない
_LEAD_MARK = re.compile(r"^(?:【制裁】|「|」)+")
_TAIL_BACK = re.compile(r"^((?:\([^()]*\))+)」「")
# 人の役。⛔名前は正規表現で切らない= その日の名簿(nar_runs の略称)を本文から探す。
#   実測で語順が 3 通り(騎手◯◯は / ◯◯号の騎手◯◯は / ◯◯調教師は)あり、
#   さらに「騎手が落馬」のような**人名でない**ところに当たるため(名古屋 2026-08-21)。
_ROLE = {"jockey": "騎手", "trainer": "調教師"}
_ROLE_NEAR = 4                      # 名前の前後この字数に役の語があれば「役つき」とみなす
NAME_GAP = 4                        # 略称の「苗字」と「名の1字」の間に許す字数(実測は 2 まで)
# 期間は**書いてある形だけ**。⛔「9月1日、2日の2日間」のような並びは読まない(推測しない)
_RANGE = re.compile(r"令和(\d{1,2})年(\d{1,2})月(\d{1,2})日から令和(\d{1,2})年(\d{1,2})月(\d{1,2})日まで")
# 種類。⛔上から順に見る(「戒告され…賞典を停止された」は戒告)
# §111b #2 「◯日間騎乗を停止された」も騎乗停止。⛔「賞典を停止」は別物= 戒告のまま
_KINDS = ((re.compile(r"騎乗停止|騎乗を停止"), "騎乗停止"), (re.compile(r"過怠金"), "過怠金"),
          (re.compile(r"戒告"), "戒告"), (re.compile(r"注意"), "注意"))

# 本文から**その制裁が指している馬の馬番**。⛔書いてある形だけを読む(推測しない)。
# 実測(2026-09-12・347 行)で出てくる形は 3 通り=
#   「騎手◯◯は7番テスト号に騎乗したところ…」   → 7
#   「2番テスト号の騎手◯◯…」                   → 2
#   「(調教師処分)◯◯は第1号馬テスト号を…」    → 1(「1号馬」も同じ)
# ⛔番号のうしろが「番」か「号馬」のときだけ読む= 「2日間」「令和8年9月6日」には当たらない。
# ⛔1 つの文に番号が 2 つ出る行は 0 件(実測)なので**最初の 1 つ**を使う。
# ⛔全角数字も読む(いまの器には 0 件だが、原本は主催者の書き方しだいなので受ける)。
_UMABAN = re.compile(r"(?:第)?([0-9０-９]+)\s*(?:番|号馬)")
_ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def umaban_of(detail):
    """制裁の本文 → 馬番(1〜18)。読めなければ None。⛔通信なしの純関数。"""
    m = _UMABAN.search(str(detail or ""))
    if not m:
        return None
    try:
        no = int(m.group(1).translate(_ZEN))
    except ValueError:
        return None
    return no if 1 <= no <= 18 else None


N_REQ = [0]


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def today_jst():
    return dt.datetime.now(JST).date()


def sha256_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def tight(value):
    """PDF の字は 1 字ずつ空白で割れる。NFKC にして**空白を全部落とす**。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


# ---------------------------------------------------------------- DB(REST)

class Client:
    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.key = key

    def _headers(self, extra=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key,
             "User-Agent": UA, "Content-Type": "application/json"}
        if extra:
            h.update(extra)
        return h

    def get(self, path):
        N_REQ[0] += 1
        req = urllib.request.Request(self.url + "/rest/v1/" + path, headers=self._headers())
        with urllib.request.urlopen(req, timeout=90) as res:
            body = res.read().decode("utf-8")
        return json.loads(body) if body else []

    def post(self, path, rows, prefer):
        N_REQ[0] += 1
        data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url + "/rest/v1/" + path, data=data, method="POST",
                                     headers=self._headers({"Prefer": prefer}))
        try:
            with urllib.request.urlopen(req, timeout=180) as res:
                return res.status
        except urllib.error.HTTPError as e:              # ⛔制約違反は本文を見ないと分からない
            raise RuntimeError("upsert HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:1200]))


def q(value):
    return urllib.parse.quote(str(value), safe="")


def race_days(client, start, end):
    """対象の (場, 開催日, その日のレース番号)。⛔§89 の venue_days と同じ引き方を 1 日 1 本で。"""
    out = []
    day = start
    while day <= end:
        iso = day.isoformat()
        rows = client.get("nar_races?select=track,race_no&race_date=eq.%s"
                          "&order=track.asc,race_no.asc&limit=1000" % iso)
        grouped = {}
        for row in rows:
            track = str(row.get("track") or "")
            try:
                no = int(row.get("race_no"))
            except (TypeError, ValueError):
                continue
            if track in NAR_PDF and 1 <= no <= 12:
                grouped.setdefault(track, set()).add(no)
        out.extend((track, iso, grouped[track]) for track in sorted(grouped))
        day += dt.timedelta(days=1)
    return out


def roster(client, track, race_date):
    """その日その場の 騎手・調教師の**公式の略称**(nar_runs の表記)。名前を当てるのに使う。

    §111c 「馬」も同じ 1 本で受け取る= (レース番号, 馬番) → 馬名。制裁の本文の「N番◯◯号」から
    馬番を読んで、**主催者の名簿の側の馬名**を入れる(⛔本文の字から馬名を切り出さない=
    原本の書き方が変わっても取り違えない)。⛔列を足すだけなので通信は増えない(1 本のまま)。
    """
    rows = client.get("nar_runs?select=jockey,trainer,race_no,runner_number,horse_name"
                      "&track=eq.%s&race_date=eq.%s&limit=1000" % (q(track), q(race_date)))
    jockeys, trainers, horses = set(), set(), {}
    for r in rows:
        if r.get("jockey"):
            jockeys.add(tight(r["jockey"]))
        if r.get("trainer"):
            trainers.add(tight(r["trainer"]))
        try:
            key = (int(r["race_no"]), int(r["runner_number"]))
        except (TypeError, ValueError, KeyError):
            continue
        name = tight(r.get("horse_name"))
        if name:
            horses[key] = name
    return {"jockey": jockeys, "trainer": trainers, "horse": horses}


# ---------------------------------------------------------------- 読み取り(純関数)

def penalty_blocks(text):
    """1 レースぶんの本文 → 「制裁」のかたまり(文字列)の一覧。⛔次の見出しまでが 1 つ。

    §111b #3 頁またぎ: 頁の飾り(作成日時・頁番号)の行は**落とすだけ**でかたまりを閉じない。
    その直後の「制裁」は前の頁の**続き**(ラベルの再掲)なので、新しいかたまりにしない。
    ⛔行は文で切り直す(sentences)ので、続きでない所を繋いでも 1 行 1 文のままになる。
    """
    lines = [tight(x) for x in str(text or "").split("\n")]
    out = []
    cur = None
    broke = False                       # 直前に頁の飾りを落とした= 次の行は頁の続き
    for line in lines:
        if not line:
            continue
        if _FOOTNOTE.match(line):
            broke = True                # 頁の終わり= この後に頁番号と前の頁の続きが来る
            continue
        if broke and _PAGE_NO.match(line):
            continue                    # 脚注の直後の頁番号だけ飾りとして落とす
        if _PENALTY_HEAD.match(line):
            rest = line[len("制裁"):]
            if cur is not None and broke:
                cur += rest             # 頁またぎ= ラベルだけ再掲されて本文は続き
            else:
                if cur is not None:
                    out.append(cur)
                cur = rest
            broke = False
            continue
        broke = False
        if cur is None:
            continue
        if _ROW_HEAD.match(line):
            out.append(cur)
            cur = None
            continue
        cur += line
    if cur is not None:
        out.append(cur)
    return [x for x in (y.strip() for y in out) if x]


def sentences(block):
    """かたまり → 1 文ずつ(「。」の後ろで切る)。⛔長さで切らない= 長い一文の**頭**
    (役と名前がある所)を落とさないため。

    §111b #1 文に分けた**後**で公式の飾りを落とす: 先頭の【制裁】「」と末尾の」。
    ⛔`(…)」「` で始まる文の `(…)` は**前の文の括弧書き**なので、前の文の末尾に戻す(捨てない)。
    ⛔`(…)` そのものは公式の文言なので落とさない。
    """
    out = []
    for raw in re.split(r"(?<=。)", str(block or "")):
        s = raw.strip()
        if not s:
            continue
        m = _TAIL_BACK.match(s)
        if m:
            if out:
                out[-1] += m.group(1)   # 前の文へ戻す
                s = s[m.end():]
            else:
                s = m.group(1) + s[m.end():]   # 戻す先が無ければその場に残す
        s = _LEAD_MARK.sub("", s).strip()
        while s.endswith("」"):
            s = s[:-1].strip()
        if s:
            out.append(s)
    return out


def kind_of(sentence):
    for rx, label in _KINDS:
        if rx.search(sentence):
            return label
    return "その他"


def era_date(year, month, day):
    """令和 N 年 → 西暦(令和元年 = 2019)。"""
    try:
        return dt.date(2018 + int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def suspension(sentence):
    """「令和8年8月21日から令和8年9月7日まで」だけを読む。⛔他の形は null(推測しない)。"""
    m = _RANGE.search(sentence)
    if not m:
        return None, None
    a = era_date(m.group(1), m.group(2), m.group(3))
    b = era_date(m.group(4), m.group(5), m.group(6))
    if a and b and a <= b:
        return a, b
    return None, None


def occurrences(sentence, name):
    """名簿の略称が本文のどこに現れるか → [(始まり, 長さ)]。

    ⛔略称は本名の**連続した一部とは限らない**(実測 2026-08-20〜09-04):
      田野豊三 → 田野豊(そのまま出る) / 佐々木功 → 佐々功 / 渋谷信博 → 渋谷博 /
      九日俊光 → 九日光 / 佐藤裕太 → 佐藤太(**間に字がある**)
    そこで ①そのまま出る形 を先に見て、無ければ ②苗字(先頭 L-1 字)の直後 NAME_GAP 字以内に
    最後の 1 字がある形 を見る。⛔それ以上ゆるめない(別人に当たる)。
    """
    out = []
    at = sentence.find(name)
    while at >= 0:
        out.append((at, len(name)))
        at = sentence.find(name, at + 1)
    if out or len(name) < 2:
        return out
    head, tail = name[:-1], name[-1]
    at = sentence.find(head)
    while at >= 0:
        window = sentence[at + len(head):at + len(head) + NAME_GAP]
        pos = window.find(tail)
        if pos >= 0:
            out.append((at, len(head) + pos + 1))
        at = sentence.find(head, at + 1)
    return out


def find_person(sentence, names):
    """本文から **その日の名簿にある人**を 1 人だけ見つける。返り= (person_kind, 略称) か None。

    ⛔役の語(騎手/調教師)が名前のすぐ前後にあるものを優先する。2 人以上に絞れなければ返さない
      (取り違えるより出さない)。
    """
    hits = []
    for kind in ("jockey", "trainer"):
        role = _ROLE[kind]
        for name in names.get(kind, ()):
            if not name or len(name) < 2:
                continue
            for at, length in occurrences(sentence, name):
                near = (role in sentence[max(0, at - _ROLE_NEAR):at]
                        or role in sentence[at + length:at + length + _ROLE_NEAR])
                hits.append((0 if near else 1, at, kind, name))
    if not hits:
        return None
    hits.sort()
    best = [h for h in hits if h[0] == hits[0][0]]
    # 同じ人が何度も出るのは 1 人扱い。別人が並ぶときは決められないので出さない
    people = {(h[2], h[3]) for h in best}
    if len(people) != 1:
        return None
    return best[0][2], best[0][3]


def read_penalties(track, race_date, segments, names, source_url, source_hash):
    """(レース番号, 本文)の一覧 → 制裁の行。⛔人(騎手・調教師)の文だけを取る。"""
    rows = []
    stats = {"blocks": 0, "sentences": 0, "no_person": 0, "name_unmatched": 0, "horse_named": 0}
    for race_no, text in segments:
        for block in penalty_blocks(text):
            stats["blocks"] += 1
            for sentence in sentences(block):
                stats["sentences"] += 1
                if not any(role in sentence for role in _ROLE.values()):
                    stats["no_person"] += 1        # 馬の話(◯番◯◯号は…)= 数えるだけ
                    continue
                found = find_person(sentence, names)
                if found is None:
                    stats["name_unmatched"] += 1   # 役の語はあるが名簿の人に絞れない= 出さない
                    continue
                person_kind, name = found
                detail = sentence[:DETAIL_MAX]
                kind = kind_of(sentence)
                since, through = suspension(sentence)
                no = race_no if isinstance(race_no, int) and 1 <= race_no <= 12 else None
                # §111c その制裁が指している馬。⛔馬番が読めない行・名簿に居ない馬番は None のまま
                #   (⛔埋めない)。⛔penalty_id の材料には入れない= 既にある行の id を動かさない
                umaban = umaban_of(detail)
                horse = names.get("horse", {}).get((no, umaban)) if (no and umaban) else None
                if horse:
                    stats["horse_named"] = stats.get("horse_named", 0) + 1
                rows.append({
                    "penalty_id": sha256_text("|".join([
                        track, race_date, str(no), person_kind, name, kind, detail])),
                    "track": track, "race_date": race_date, "race_no": no,
                    "person_kind": person_kind, "person_name": name,
                    "horse_name": horse,
                    "kind": kind, "detail": detail,
                    "suspension_from": since, "suspension_through": through,
                    "source_url": source_url, "source_hash": source_hash,
                    "parser_version": PARSER_VERSION,
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                })
    return rows, stats


# ---------------------------------------------------------------- 本体

def upsert(client, rows):
    done = 0
    for i in range(0, len(rows), UPSERT_CHUNK):
        part = rows[i:i + UPSERT_CHUNK]
        client.post("nar_penalties?on_conflict=penalty_id", part,
                    "resolution=merge-duplicates,return=minimal")
        done += len(part)
    return done


def known_sources(client, start, end):
    """読み済みの記録(nar_penalty_sources): (場, 日) → (PDF の sha256, 読み手の版)。
    #528: 1 本 12 秒かかる PDF 解析を、**取り直した PDF の sha256 と読み手の版が前回と同じ**ときだけ飛ばす。
    取り直しはする(公式が差し替えれば sha256 が変わって読み直す)。読み手の版が上がっても読み直す。"""
    out = {}
    for row in client.get("nar_penalty_sources?select=track,race_date,source_hash,parser_version"
                          "&race_date=gte.%s&race_date=lte.%s&limit=1000" % (start.isoformat(), end.isoformat())):
        out[(str(row.get("track")), str(row.get("race_date")))] = (row.get("source_hash"), row.get("parser_version"))
    return out


def run(client, start, end, apply, show=0):
    limiter = HostLimiter()
    n = {"sources": 0, "pdf_missing": 0, "rows": 0, "unparsed": 0, "name_unmatched": 0,
         "horse_named": 0, "upserted": 0, "errors": 0, "unchanged": 0}
    by_kind, by_person = {}, {}
    rows = []
    known = known_sources(client, start, end) if apply else {}   # ドライランは全部読む(検品用)
    parsed = []                                                   # 今回読んだ PDF の記録
    for track, race_date, expected in race_days(client, start, end):
        url, _ref = pdf_url(track, race_date)
        try:
            res = download_pdf(url, limiter, None)
        except Exception as err:
            n["errors"] += 1
            log("  ⚠ 取れず %s %s (%s)" % (track, race_date, str(err)[:60]))
            continue
        if res.code != 200:
            n["pdf_missing"] += 1
            continue
        digest = hashlib.sha256(res.body).hexdigest()
        if known.get((track, race_date)) == (digest, PARSER_VERSION):
            n["unchanged"] += 1                                  # 同じ PDF・同じ読み手= 前回の行がそのまま
            continue
        try:
            pages = pdf_pages(res.body, res.content_type)
        except Exception as err:
            n["errors"] += 1
            log("  ⚠ 読めず %s %s (%s)" % (track, race_date, str(err)[:60]))
            continue
        n["sources"] += 1
        segments, _seen, _invalid = _segments(pages, expected)
        got, stats = read_penalties(track, race_date, segments, roster(client, track, race_date),
                                    url, digest)
        parsed.append({"track": track, "race_date": race_date, "source_hash": digest,
                       "parser_version": PARSER_VERSION, "rows": len(got),
                       "parsed_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        n["unparsed"] += stats["no_person"]
        n["name_unmatched"] += stats["name_unmatched"]
        n["horse_named"] += stats.get("horse_named", 0)
        for row in got:
            by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
            by_person[row["person_kind"]] = by_person.get(row["person_kind"], 0) + 1
        rows.extend(got)
        if show and got:
            for row in got[:show]:
                log("   %s %s %sR %s %s %s | %s" % (
                    row["race_date"], row["track"], row["race_no"], row["person_kind"],
                    row["person_name"], row["kind"], row["detail"][:56]))
    uniq = {}
    for row in rows:
        uniq[row["penalty_id"]] = row
    rows = list(uniq.values())
    n["rows"] = len(rows)
    if apply and rows:
        n["upserted"] = upsert(client, rows)
    if apply and parsed:                                           # 行の upsert が通ってから記録(途中で落ちたら次回また読む)
        for i in range(0, len(parsed), UPSERT_CHUNK):
            client.post("nar_penalty_sources?on_conflict=track,race_date", parsed[i:i + UPSERT_CHUNK],
                        "resolution=merge-duplicates,return=minimal")
    log("sources=%d unchanged=%d pdf_missing=%d rows=%d by_kind=%s by_person_kind=%s unparsed=%d "
        "name_unmatched=%d horse_named=%d upserted=%d errors=%d"
        % (n["sources"], n["unchanged"], n["pdf_missing"], n["rows"], json.dumps(by_kind, ensure_ascii=False),
           json.dumps(by_person, ensure_ascii=False), n["unparsed"], n["name_unmatched"],
           n["horse_named"], n["upserted"], n["errors"]))
    return rows, n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="開催日の下限(既定= 今日-%d日)" % DEFAULT_DAYS)
    ap.add_argument("--end", default=None, help="開催日の上限(既定= 今日)")
    ap.add_argument("--apply", action="store_true", help="DB へ upsert する(既定はドライラン)")
    ap.add_argument("--show", type=int, default=0, help="読めた行を場ごとに N 件だけ出す(検品用)")
    ap.add_argument("--env", default=None)
    args = ap.parse_args(argv)

    if args.env:
        load_env(args.env)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    today = today_jst()
    try:
        start = dt.date.fromisoformat(args.start) if args.start else today - dt.timedelta(days=DEFAULT_DAYS)
        end = dt.date.fromisoformat(args.end) if args.end else today
    except ValueError:
        log("日付の形が違う(YYYY-MM-DD)")
        return 2
    if start > end:
        log("--start が --end より後")
        return 2

    rows, n = run(Client(url, key), start, end, args.apply, show=args.show)
    log("REST 要求 %d 本" % N_REQ[0])
    return 0 if rows is not None else 1


if __name__ == "__main__":
    sys.exit(main())

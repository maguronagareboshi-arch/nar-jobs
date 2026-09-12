# -*- coding: utf-8 -*-
"""§120 高知のレース後コメント(主催者公式)を取って `nar_race_comments` に入れる。

出どころ= 高知県競馬組合の公式サイト `https://www.keiba.or.jp/?postracecomment=YYYYMMDDRR`(2024年3月から)。
記事は「騎手のコメントを元騎手の妹尾将充が聴き取り書き起こしたもの」= **公式の結果ではない**ので
`nar_runs` には混ぜず、専用の表に 1 頭 1 行で入れる(pipeline/sql/nar_race_comments_20260907.sql)。

⛔安全の要:
- **推定しない**= 記事の「N番 馬名 ○○騎手」の N と馬名が、その走の `nar_runs`(馬番・馬名)と
  **両方そろって一致した行だけ**入れる。合わない行は数えてログに出すだけで**入れない**。
- **未掲載(本文が空)は「無い」として記録しない**= 掲載が遅れる日があるので次の便でまた見る
  (ただし 30 日より前の未掲載は諦めた旨をログに出すだけ)。
- 記事末尾の「この記事は、…」の 1 文は行に入れない(画面が固定の断りとして出す)。
- 既に行のある(日, R)は**開かない**= 公式サイトへの通信を増やさない。

使い方:
  py -3.12 -X utf8 cloud/kochi_comments.py --env pipeline/.env.nar                  # 対象の検出+取得+件数(書かない)
  py -3.12 -X utf8 cloud/kochi_comments.py --env pipeline/.env.nar --apply          # 投入
  py -3.12 -X utf8 cloud/kochi_comments.py --env pipeline/.env.nar --since 2026-01-01 --apply
  py -3.12 -X utf8 cloud/kochi_comments.py --since 2026-09-01 --show 3              # 目で見る(鍵なしでも読める)
環境変数: SUPABASE_URL / SUPABASE_ANON_KEY(読み・無ければ公開 anon を使う)/ SUPABASE_SERVICE_KEY(--apply)
終了コード: 0 正常(対象なし含む)/ 1 投入の失敗 / 2 前提の読み取り失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html as H
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; nar-jobs/1.0)"
TRACK = "高知"
PAGE = "https://www.keiba.or.jp/?postracecomment={ymd}{rr:02d}"
SLEEP = 0.7                                # 公式への間合い(1 レース 1 GET)
DEFAULT_DAYS = 14                          # 既定の窓(今日から何日前まで見るか)
GIVE_UP_DAYS = 30                          # これより前の未掲載は諦める(ログだけ)
DISCLAIMER = "この記事は、騎手のコメント"   # 末尾の 1 文(行に入れない)

# 公開の anon(js/data.js の NAR_KEY と同じ= **読むだけ**。⛔service キーはここに書かない)
NAR_URL = "https://qgsnsdjvzzeazbazjlwa.supabase.co"
NAR_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFnc25zZGp2enplYXpiYXpqbHdhIiwi"
            "cm9sZSI6ImFub24iLCJpYXQiOjE3ODc0MTg0NDIsImV4cCI6MjEwMjk5NDQ0Mn0."
            "a4pjf8WKgcVGL3d8ZBdP4dJDpnDkM2EnKofnXdHE2I8")


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_last = [0.0]


def http_get(url, headers=None, tries=3, timeout=45):
    """SLEEP の間合いを守って GET。5xx と通信断だけ間を置いて取り直す(404 等は取り直さない)。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
    last = None
    for n in range(tries):
        wait = SLEEP - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            last = e
        except Exception as e:
            last = e
        finally:
            _last[0] = time.monotonic()
        if n < tries - 1:
            time.sleep(2.0 * (n + 1))
    raise RuntimeError(f"GET {url[:90]} 失敗: {type(last).__name__}: {str(last)[:120]}")


def sb_rows(base, key, path):
    raw = http_get(f"{base}/rest/v1/{path}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    return json.loads(raw.decode("utf-8"))


def sb_rows_all(base, key, path, page=1000):
    """PostgREST の max-rows(このプロジェクトは 1000)を越えて全部読む。⛔path の order= は一意であること。"""
    out, off = [], 0
    while True:
        part = sb_rows(base, key, f"{path}&limit={page}&offset={off}")
        out += part
        if len(part) < page:
            return out
        off += page


def sb_upsert(base, key, path, rows):
    """PostgREST の upsert。返り値= (status, 本文の頭)"""
    req = urllib.request.Request(
        f"{base}/rest/v1/{path}", method="POST",
        data=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf-8", "replace")


# ---------------------------------------------------------------- 記事のパース

CONTENT_RE = re.compile(r'<div[^>]+id="the-content"[^>]*>(.*?)</div>', re.S)
# 「1番　ナインスマイル　新庄騎手」。数字は半角/全角の両方・区切りは全角空白のことが多い
HEAD_RE = re.compile(r"^([0-9０-９]{1,2})\s*番\s+(\S.*?)\s+(\S+?)\s*騎手$")
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def _text(fragment):
    """タグを外して 1 行に(全角空白は空白に寄せる。⛔字そのものは言い換えない)。"""
    s = H.unescape(re.sub(r"<[^>]+>", "", fragment))
    return re.sub(r"[ \t　\xa0]+", " ", s).strip()


def parse_comments(page):
    """記事のページ → [{umaban, horse_name, jockey, comment}]。読めなければ []。

    ⚠形は回によって違う(2026-09-07 実測): 1 頭だけの `<p>` と、`<br><br>` で 7 頭並ぶ `<p>` が同居する。
    ⛔段落をまたいで本文をつなげない= 末尾の断り書きの `<p>` が最後の馬の本文に混ざらないようにする。
    ⛔「N番 … 騎手」の形でない行は、馬の頭とみなさない(先頭のレース成績表リンクなどはここで落ちる)。
    """
    m = CONTENT_RE.search(page)
    if not m:
        return []
    out = []
    for para in re.split(r"</p\s*>", m.group(1), flags=re.I):
        cur = None                                   # 段落が変われば「今の馬」は終わり
        for line in re.split(r"<br\s*/?>", para, flags=re.I):
            text = _text(line)
            if not text or text.startswith(DISCLAIMER):
                continue                             # 末尾の 1 文は行に入れない
            hm = HEAD_RE.match(text)
            if hm:
                cur = {"umaban": int(hm.group(1).translate(ZEN)),
                       "horse_name": hm.group(2).strip(),
                       "jockey": hm.group(3).strip(),
                       "comment": ""}
                out.append(cur)
            elif cur is not None:
                cur["comment"] = (cur["comment"] + " " + text).strip() if cur["comment"] else text
    return [x for x in out if x["comment"]]           # ⛔本文の無い行は入れない


# ---------------------------------------------------------------- 本体

def race_targets(base, key, since, until):
    """(日付 → {R})。⛔開催のあった日だけ= nar_races から取る(1 レース 1 行で軽い)。"""
    rows = sb_rows_all(base, key,
                       f"nar_races?select=race_date,race_no&track=eq.{urllib.parse.quote(TRACK)}"
                       f"&race_date=gte.{since}&race_date=lte.{until}"
                       "&order=race_date.asc,race_no.asc")
    days = {}
    for r in rows:
        days.setdefault(str(r["race_date"]), set()).add(int(r["race_no"]))
    return days


def already(base, key, since, until):
    """もう行のある (日, R)。表がまだ無ければ None(ドライランは続ける・--apply は止める)。"""
    try:
        rows = sb_rows_all(base, key,
                           f"nar_race_comments?select=race_date,race_no,umaban&track=eq.{urllib.parse.quote(TRACK)}"
                           f"&race_date=gte.{since}&race_date=lte.{until}"
                           "&order=race_date.asc,race_no.asc,umaban.asc")
    except Exception as e:
        log(f"⚠ nar_race_comments が読めない({type(e).__name__}: {str(e)[:80]})")
        return None
    return {(str(r["race_date"]), int(r["race_no"])) for r in rows}


def day_runs(base, key, date):
    """その日の結果(1 日 1 本)。返り値= ({R: {馬番: 馬名}}, 結果の出ている R の集合)。"""
    rows = sb_rows(base, key,
                   "nar_runs?select=race_no,runner_number,horse_name,finish,finish_note"
                   f"&track=eq.{urllib.parse.quote(TRACK)}&race_date=eq.{date}&limit=3000")
    by, done = {}, set()
    for r in rows:
        if r.get("race_no") is None or r.get("runner_number") is None:
            continue
        no, uma = int(r["race_no"]), int(r["runner_number"])
        by.setdefault(no, {})[uma] = str(r.get("horse_name") or "").strip()
        if r.get("finish") is not None or str(r.get("finish_note") or "").strip():
            done.add(no)
    return by, done


def rows_of(date, no, parsed, runs, url, stats, show):
    """記事の行 → 表の行。⛔馬番と馬名が nar_runs と**両方**一致した行だけ返す(推定しない)。"""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    for c in parsed:
        want = runs.get(c["umaban"])
        if want is None:
            stats["no_run"] += 1
            log(f"  ⚠ {date} {no}R {c['umaban']}番「{c['horse_name']}」= その馬番が結果に無い(入れない)")
            continue
        if want != c["horse_name"]:
            stats["name_ng"] += 1
            log(f"  ⚠ {date} {no}R {c['umaban']}番 記事「{c['horse_name']}」/ 結果「{want}」"
                "= 名前が合わない(入れない)")
            continue
        out.append({"track": TRACK, "race_date": date, "race_no": no, "umaban": c["umaban"],
                    "horse_name": c["horse_name"], "jockey": c["jockey"] or None,
                    "comment": c["comment"], "source_url": url, "fetched_at": now})
        if show > 0 and stats["shown"] < show:
            stats["shown"] += 1
            log(f"  ・{date} {no}R {c['umaban']}番 {c['horse_name']}({c['jockey']}) {c['comment']}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help=f"この日から見る(既定= 今日-{DEFAULT_DAYS}日)")
    ap.add_argument("--until", default=None, help="この日まで見る(既定= 今日)")
    ap.add_argument("--apply", action="store_true", help="DB へ入れる(既定はドライラン)")
    ap.add_argument("--show", type=int, default=0, help="読めた行を N 件だけ出す(目で見る用)")
    ap.add_argument("--out", default=None, help="読めた行を JSON に書き出す(投入とは別)")
    ap.add_argument("--env", default=None)
    a = ap.parse_args(argv)
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/") or NAR_URL
    read_key = os.environ.get("SUPABASE_ANON_KEY", "") or NAR_ANON
    write_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if a.apply and not write_key:
        log("--apply には SUPABASE_SERVICE_KEY が要る(--env pipeline/.env.nar)")
        return 2

    today = dt.datetime.now(JST).date()
    until = a.until or today.isoformat()
    since = a.since or (today - dt.timedelta(days=DEFAULT_DAYS)).isoformat()
    try:
        days = race_targets(base, read_key, since, until)
    except Exception as e:
        log(f"nar_races が読めない {type(e).__name__}: {str(e)[:120]}")
        return 2
    have = already(base, read_key, since, until)
    if have is None:
        if a.apply:
            log("表がまだ無い(pipeline/sql/nar_race_comments_20260907.sql を先に流す)")
            return 2
        have = set()
    log(f"高知 {since}〜{until}: 開催 {len(days)}日 / 既にコメントのある (日,R) {len(have)}")

    stats = {"races": 0, "empty": 0, "gave_up": 0, "no_run": 0, "name_ng": 0, "rows": 0,
             "errors": 0, "shown": 0}
    all_rows, fails = [], 0
    for date in sorted(days):
        todo = sorted(no for no in days[date] if (date, no) not in have)
        if not todo:
            continue
        try:
            by_race, done = day_runs(base, read_key, date)
        except Exception as e:
            log(f"⚠ {date} 結果が読めない {type(e).__name__}: {str(e)[:80]}")
            stats["errors"] += 1
            continue
        old = (today - dt.date.fromisoformat(date)).days > GIVE_UP_DAYS
        for no in todo:
            if no not in done:
                continue                                  # 結果がまだ= 触らない(⛔先取りしない)
            url = PAGE.format(ymd=date.replace("-", ""), rr=no)
            try:
                page = http_get(url).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    stats["empty"] += 1                   # 未掲載= 「無い」として記録しない
                    continue
                stats["errors"] += 1
                log(f"⚠ {date} {no}R HTTP {e.code}")
                continue
            except Exception as e:
                stats["errors"] += 1
                log(f"⚠ {date} {no}R 取得失敗 {type(e).__name__}: {str(e)[:80]}")
                continue
            stats["races"] += 1
            parsed = parse_comments(page)
            if not parsed:
                stats["empty"] += 1
                if old:
                    stats["gave_up"] += 1
                    log(f"  {date} {no}R 未掲載(30日より前)= 諦める")
                continue
            got = rows_of(date, no, parsed, by_race.get(no, {}), url, stats, a.show)
            stats["rows"] += len(got)
            all_rows += got
            log(f"  {date} {no}R: 記事 {len(parsed)}頭 → 入れる {len(got)}行")

    log(f"まとめ: 開いたレース {stats['races']} / 行 {stats['rows']} / 未掲載 {stats['empty']}"
        f"(うち諦め {stats['gave_up']}) / 馬番が結果に無い {stats['no_run']} /"
        f" 名前が合わない {stats['name_ng']} / 取得失敗 {stats['errors']}")
    if a.out and all_rows:
        io.open(a.out, "w", encoding="utf-8").write(json.dumps(all_rows, ensure_ascii=False, indent=1))
        log(f"{a.out} に {len(all_rows)}行 書き出し")
    if not a.apply:
        log("(ドライラン= DB には書いていません。入れるなら --apply)")
        return 1 if stats["errors"] else 0
    for i in range(0, len(all_rows), 500):
        part = all_rows[i:i + 500]
        status, msg = sb_upsert(base, write_key,
                                "nar_race_comments?on_conflict=track,race_date,race_no,umaban", part)
        if status not in (200, 201, 204):
            log(f"投入失敗 {status} {msg}")
            fails += 1
        else:
            log(f"投入 {len(part)}行 OK")
    return 1 if (fails or stats["errors"]) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

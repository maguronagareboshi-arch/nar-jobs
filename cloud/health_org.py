# -*- coding: utf-8 -*-
"""本体 cloud: 主催者公式の「出来事」を読む core(§92b / §109)。

各主催者の adapter(cloud/health_org_<slug>.py)から
  list_documents(fetch, since, until) -> [(開催日 'YYYY-MM-DD', 記事の URL), …]
  parse(html) -> {'rows': [{race_no, umaban, horse_name, status, detail, reported_date}], 'doc_hash': …, 'skipped': N}
を受け取り、`nar_runs` と突き合わせて `nar_horse_health_events` の行にする。

  py -3.12 -X utf8 cloud/health_org.py --adapter kochi                      # ドライラン(数だけ)
  py -3.12 -X utf8 cloud/health_org.py --adapter kochi --since 2026-01-01   # 期間を指定
  py -3.12 -X utf8 cloud/health_org.py --adapter kochi --apply              # upsert する
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--env が無ければ環境変数だけで動く・#465)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔原本(HTML)は保存しない(§92b の約束)。残すのは抽出した行だけ。
⛔同じ host には HOST_INTERVAL 秒あける・UA は固定・2MB / 30秒で打ち切る。
⛔読めない文書・当たらない馬で**止めない**= 数えてログに出すだけ(§92b 原則5)。
⛔病名の分類(condition_group)は cloud/horse_health.py の `_groups()`(§89)を import して使う。
  2 か所目を作らない(§5.4)。
"""
import argparse
import datetime as dt
import hashlib
import importlib
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# ⛔語表(骨・腱= musculoskeletal / 鼻出血= epistaxis …)は §89 の 1 か所だけ
from horse_health import _groups                                  # noqa: E402

UA = "nar-jobs-health/1.0"
JST = dt.timezone(dt.timedelta(hours=9))
HOST_INTERVAL = 2.0             # 同じ host にこれ以上あける(秒)
MAX_BYTES = 2 * 1024 * 1024     # 原本の上限
TIMEOUT = 30                    # 取得のタイムアウト(秒)
DEFAULT_DAYS = 14               # --since が無いときの窓
UPSERT_CHUNK = 500              # 1 回に送る行数
DETAIL_MAX = 1000               # 器の制約(detail は 1〜1000 字)

# 状態 → (stage, event_type, race_status)。⛔器の check 制約と同じ語だけ
STATUS_MAP = {
    "出走取消": ("pre_race", "withdrawal", "出走取消"),
    "競走除外": ("pre_race", "exclusion", "競走除外"),
    "競走中止": ("in_race", "did_not_finish", "競走中止"),
    None: ("post_race", "post_race_condition", None),      # 競走後の診断
}

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


def nfkc(value):
    return unicodedata.normalize("NFKC", str(value or ""))


def norm_name(value):
    """馬名の照合用。NFKC + 空白を全部落とす(公式は全角空白が入ることがある)。"""
    return "".join(nfkc(value).split())


# ---------------------------------------------------------------- 取得(公式サイト)

class Limiter:
    """host ごとに最後の取得時刻を覚えて、HOST_INTERVAL 秒あける。"""

    def __init__(self, interval=HOST_INTERVAL):
        self.interval = float(interval)
        self.last = {}
        self.errors = 0

    def wait(self, host):
        rest = self.interval - (time.time() - self.last.get(host, 0.0))
        if rest > 0:
            time.sleep(rest)

    def done(self, host):
        self.last[host] = time.time()


def fetch(url, *, limiter):
    """公式ページを 1 枚取る。⛔失敗は例外にせず None(呼び出し側が数える)。"""
    host = urllib.parse.urlsplit(url).netloc
    limiter.wait(host)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read(MAX_BYTES)
            charset = (res.headers.get_content_charset() or "utf-8")
    except Exception as err:                                  # HTTP も通信断も同じ扱い
        limiter.done(host)
        limiter.errors += 1
        log("  ⚠ 取れず %s (%s)" % (url, str(err)[:70]))
        return None
    limiter.done(host)
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


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
        except urllib.error.HTTPError as e:            # ⛔本文を見ないと制約違反の理由が分からない(2026-09-05 実測)
            body = e.read().decode("utf-8", "replace")[:1500]
            raise RuntimeError(f"upsert HTTP {e.code}: {body}") from None


def q(value):
    return urllib.parse.quote(str(value), safe="")


_RUNS_CACHE = {}


def nar_runs_for(client, track, race_date):
    """その開催日その場の出走を 1 本で。⛔同じ日は 1 回だけ引く(記事が複数あっても増やさない)。"""
    key = (track, race_date)
    if key in _RUNS_CACHE:
        return _RUNS_CACHE[key]
    rows = []
    if client is not None:
        try:
            rows = client.get(
                "nar_runs?select=race_no,runner_number,horse_name,finish,finish_note,birth_date"
                "&track=eq.%s&race_date=eq.%s&limit=1000" % (q(track), q(race_date)))
        except Exception as err:
            log("  ⚠ nar_runs を引けず %s %s (%s)" % (track, race_date, str(err)[:60]))
            rows = []
    _RUNS_CACHE[key] = rows
    return rows


def match(runs, race_no, horse_name, umaban=None):
    """track+race_date+R+馬名 で **ちょうど 1 行**なら返す。0 行 / 2 行以上 / 馬番違いは None。"""
    want = norm_name(horse_name)
    if not want or race_no is None:
        return None
    hit = [r for r in (runs or [])
           if _int(r.get("race_no")) == race_no and norm_name(r.get("horse_name")) == want]
    if len(hit) != 1:
        return None
    run = hit[0]
    if umaban is not None and _int(run.get("runner_number")) != umaban:
        return None            # 原本に馬番があって食い違う= 書かない(§92b 3)
    return run


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 行の組み立て

def build_event(adapter, track, race_date, doc_url, doc_hash, rec, run):
    """1 頭 1 出来事 → `nar_horse_health_events` の 1 行。⛔詳細は公式の文言そのまま。"""
    status = rec.get("status")
    if status not in STATUS_MAP:
        return None
    stage, event_type, race_status = STATUS_MAP[status]
    detail = nfkc(rec.get("detail") or "").strip()[:DETAIL_MAX]
    if not detail:
        return None
    horse_name = nfkc(rec.get("horse_name") or "").strip()
    race_no = _int(rec.get("race_no"))
    groups = _groups(detail)
    condition_group = groups[0] if groups else "unspecified"
    code = str(rec.get("horse_code") or "")
    ref = "%s/%s" % (adapter.SLUG, race_date.replace("-", ""))
    reported = rec.get("reported_date") or race_date
    note = nfkc(run.get("finish_note") or "").strip()
    finish = _int(run.get("finish"))
    # ⛔画面に出すのは公式の結果と食い違わない行だけ(§92b 3)
    if race_status is not None:
        displayable = (note == race_status)
    else:
        displayable = (finish is not None and finish > 0)
    return {
        "event_id": sha256_text("|".join([
            adapter.SOURCE_KIND, track, race_date, str(race_no), horse_name, event_type, detail])),
        "horse_name": horse_name,
        "birth_date": run.get("birth_date") or None,
        # 公式が馬名に張ったリンクから拾えた血統登録番号(11桁)だけ。⛔形が違えば入れない
        "horse_code": code if re.fullmatch(r"[0-9]{11}", str(rec.get("horse_code") or "")) else None,
        "jbis_id": None,
        "track": track,
        "race_date": race_date,
        "race_no": race_no,
        "runner_number": _int(run.get("runner_number")),
        "event_date": race_date,
        "reported_date": reported,
        "stage": stage,
        "event_type": event_type,
        "condition_group": condition_group,
        "race_status": race_status,
        "detail": detail,
        "restriction_from": None,
        "restriction_through": None,
        "source_kind": adapter.SOURCE_KIND,
        "source_ref": ref,
        # ⛔器の displayable 制約(Codex 9/5 適用)は競走 event に event_key を要求する。式は DB の
        #   private.nar_health_event_key と同じ= "race-v1" と各値を NUL(0x00) でつないだ sha256(race_status は無ければ空)
        "event_key": hashlib.sha256(bytes([0]).join(str(x).encode("utf-8") for x in [
            "race-v1", track, race_date, race_no, run["runner_number"], horse_name, event_type, race_status or "",
            adapter.SOURCE_KIND])).hexdigest(),
        # ⛔末尾に source_kind を足して NAR 成績 PDF(§89)の行と鍵を分ける= event_key には一意索引があり、同じ取消を
        #   NAR と主催者の両方が書くと衝突する(2026-09-05 実測)。画面側で同じ競走・同じ馬の行は NAR を優先して 1 つにする
        "source_url": doc_url,
        "source_hash": doc_hash,
        "source_line_hash": sha256_text(detail),
        "match_method": "race_key_name",
        "displayable": displayable,
        "parser_version": adapter.PARSER_VERSION,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def upsert(client, rows):
    """event_id で冪等に。⛔UPSERT_CHUNK 行ずつ(1 回の本文を大きくしない)。"""
    done = 0
    for i in range(0, len(rows), UPSERT_CHUNK):
        part = rows[i:i + UPSERT_CHUNK]
        client.post("nar_horse_health_events?on_conflict=event_id", part,
                    "resolution=merge-duplicates,return=minimal")
        done += len(part)
    return done


# ---------------------------------------------------------------- 本体

def run(adapter, *, since, until, apply, client):
    limiter = Limiter()
    n = {"documents": 0, "parsed_rows": 0, "matched": 0, "unmatched": 0,
         "not_displayable": 0, "upserted": 0, "errors": 0, "skipped_lines": 0}
    unmatched_examples = []
    rows = []
    try:
        docs = adapter.list_documents(lambda u: fetch(u, limiter=limiter), since, until)
    except Exception as err:
        log("一覧を読めませんでした: %s" % str(err)[:120])
        return None, n
    log("対象の文書 %d 件(%s〜%s)" % (len(docs), since, until))

    for doc in docs:
        # §110 adapter が本文を同梱していれば取りに行かない(RSS に全文が入る主催者= 大井・佐賀)
        race_date, url = doc[0], doc[1]
        text = doc[2] if len(doc) > 2 and doc[2] else fetch(url, limiter=limiter)
        if text is None:
            continue                                  # limiter.errors が数えている
        try:
            parsed = adapter.parse(text)
        except Exception as err:                      # ⛔1 文書の様式違いで止めない
            n["errors"] += 1
            log("  ⚠ 読めず %s (%s)" % (url, str(err)[:70]))
            continue
        n["documents"] += 1
        recs = parsed.get("rows") or []
        n["skipped_lines"] += int(parsed.get("skipped") or 0)
        n["parsed_rows"] += len(recs)
        doc_hash = parsed.get("doc_hash") or sha256_text(url)
        runs = nar_runs_for(client, adapter.TRACK, race_date)
        for rec in recs:
            hit = match(runs, _int(rec.get("race_no")), rec.get("horse_name"), _int(rec.get("umaban")))
            if hit is None:
                n["unmatched"] += 1
                if len(unmatched_examples) < 3:
                    unmatched_examples.append("%s %sR %s (%s)" % (
                        race_date, rec.get("race_no"), rec.get("horse_name"),
                        "その日の出走に無い" if runs else "その日の出走を引けていない"))
                continue
            row = build_event(adapter, adapter.TRACK, race_date, url, doc_hash, rec, hit)
            if row is None:
                n["errors"] += 1
                continue
            n["matched"] += 1
            if not row["displayable"]:
                n["not_displayable"] += 1
            rows.append(row)

    # ⛔同じ出来事が 2 記事に出ることがある(競走除外2 など)= event_id で 1 行にまとめる
    uniq = {}
    for row in rows:
        uniq[row["event_id"]] = row
    rows = list(uniq.values())

    if apply and rows:
        if client is None:
            log("⛔SUPABASE_URL / SUPABASE_SERVICE_KEY が無いので --apply できません")
            return None, n
        n["upserted"] = upsert(client, rows)
    n["errors"] += limiter.errors
    log("documents=%d parsed_rows=%d matched=%d unmatched=%d not_displayable=%d upserted=%d errors=%d"
        % (n["documents"], n["parsed_rows"], n["matched"], n["unmatched"],
           n["not_displayable"], n["upserted"], n["errors"]))
    if unmatched_examples:
        log("当たらなかった例: " + " / ".join(unmatched_examples))
    return rows, n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, help="主催者(例 kochi)")
    ap.add_argument("--since", default=None, help="開催日の下限 YYYY-MM-DD(既定= 今日-%d日)" % DEFAULT_DAYS)
    ap.add_argument("--until", default=None, help="開催日の上限 YYYY-MM-DD(既定= 今日)")
    ap.add_argument("--apply", action="store_true", help="DB へ upsert する(既定はドライラン)")
    ap.add_argument("--env", default=None, help="ローカルだけ: 環境変数のファイル")
    args = ap.parse_args(argv)

    if args.env:
        load_env(args.env)
    try:
        adapter = importlib.import_module("health_org_" + args.adapter)
    except Exception as err:
        log("その主催者はありません: %s (%s)" % (args.adapter, str(err)[:80]))
        return 2

    today = today_jst()
    since = args.since or str(today - dt.timedelta(days=DEFAULT_DAYS))
    until = args.until or str(today)

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    client = Client(url, key) if (url and key) else None
    if client is None:
        log("⚠ SUPABASE_URL / SUPABASE_SERVICE_KEY が無いので、照合なしで様式だけ見ます")
        if args.apply:
            return 2

    rows, n = run(adapter, since=since, until=until, apply=args.apply, client=client)
    log("REST 要求 %d 本" % N_REQ[0])
    if rows is None:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

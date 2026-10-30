# -*- coding: utf-8 -*-
"""通信量 F3(2026-10-30): 今日・明日の AI の印の日ごとの一覧を、公開バケット cond-stats の marks/v1/<日>/<model>/ に上げる。

サイト(nar-viewer js/data.js の getDayMarks・getDayMarksDetail・tajoRows)が DB に投げている日ごとの読みの応答そのもの(model ごと 1 本)。
  {v, date, model, built, ver, q, rows: nar_ai_marks の行}
⛔版 = rpc/marks_ver(sql/marks_ver.sql・model ごとの [computed_at の最大, 行数, xmin の最大])。置き場の名前に版を入れる
   = <行数>-<xmin>-<computed_at の数字>.json。同じ名前の中身は変わらない= サイトは DB の今の版から名前を作って読むので、
   古い束は読みようがない。直前の便は数分おき・数十秒おきに書くが、書く便が重なっても同じ版なら同じ中身
   (読みの前後で版が同じときだけ上げる)= 上書きの取り合いが起きない。
⛔q はサイトの select と同じ文字(違えばサイトは束を使わない)。行は全部入れる(サイトは自分の limit 以上なら DB)。
⛔Cache-Control は max-age=86400(名前ごとに中身が変わらない)。古い版は新しい KEEP 本を残して消す・今日より前の日は消す。
⛔上げる前に置き場の一覧を見て、同じ名前があれば読まない(版が変わった model だけ DB から読む= 便の通信も増やさない)。
   上げた後の取り直し(F1 の day_bundle.upload)はしない: 書くたびに束の大きさ分の通信になるため。上げ損ねても、
   サイトは名前の無い束を読めず DB に戻るだけ。

  python cloud/marks_bundle.py                              # 今日と明日(JST)・版が変わった model だけ上げる・古い日を消す
  python cloud/marks_bundle.py --watch 60 --until 21:30     # 60 秒ごとに版だけ見て、変わった model を上げる(直前の便の裏で回す)
  python cloud/marks_bundle.py --date 2026-10-30 --out DIR  # 上げずに DIR へ書く(試し)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(service_role)。終了コード 0 成功(marks_ver が無ければ上げずに 0)/ 1 失敗
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
from pathlib import Path

import day_bundle as dbn

BUCKET = dbn.BUCKET
ROOT = "marks/v1/"
CACHE = "public, max-age=86400"
V = 1
KEEP = 2   # 1 つの model で残す版の数(版を読んだ直後の閲覧のため 1 つ前も残す)
# ⛔サイト js/data.js の MARK_META_KEYS(mm_<項目>:meta->項目)・getDayMarksDetail・tajoRows の select と同じ文字。変えるときは両方
MM = ",".join("mm_%s:meta-%%3E%s" % (k, k) for k in ["runners", "factors", "p", "p_win", "p3", "n", "cal"])
SEL_DAY = "track,race_no,timing,marks,%s,computed_at" % MM
SEL_TAJO = "track,race_date,race_no,timing,marks,%s,computed_at,tj_sc:meta-%%3Escratched,tj_dr:meta-%%3Edirect" % MM
MODELS = {"base-v1": SEL_DAY, "v3-9": SEL_DAY, "v3n-1": SEL_TAJO}
log = dbn.log


def marks_ver(rest, d):
    try:
        return json.loads(rest.rpc("marks_ver", {"p_date": d}))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None   # まだ sql/marks_ver.sql を流していない
        raise


def name_of(v):
    # ⛔サイトの marksBundleName と同じ: <行数>-<xmin>-<computed_at の最大の数字だけ>.json
    mx, n, xm = v
    return "%s-%s-%s.json" % (n, xm, re.sub(r"\D", "", "" if mx is None else str(mx)))


def age_of(name):
    # 新しさ(computed_at の数字・xmin)。読めない名前は一番古い扱い
    m = re.match(r"^\d+-(\d+)-(\d*)\.json$", name)
    return (int(m.group(2) or 0), int(m.group(1))) if m else (-1, -1)


def build(rest, d, model, v):
    """版 v の束。読んだ後に版が変わっていれば None(次の回に任せる)"""
    rows = rest.get("nar_ai_marks?model=eq.%s&race_date=eq.%s&select=%s&limit=2000" % (model, d, MODELS[model]))
    rows.sort(key=lambda r: (str(r.get("track")), int(r.get("race_no") or 0), str(r.get("timing"))))
    now = marks_ver(rest, d) or {}
    if now.get(model) != v or len(rows) != v[1]:
        return None
    return {"v": V, "date": d, "model": model, "built": dt.datetime.now(dbn.JST).isoformat(timespec="seconds"),
            "ver": v, "q": MODELS[model], "rows": rows}


def listed(rest, prefix):
    body = json.dumps({"prefix": prefix, "limit": 1000}).encode()
    items = json.loads(rest.req("/storage/v1/object/list/" + BUCKET, "POST", body, {"Content-Type": "application/json"}))
    return [x["name"] for x in items if x.get("name")]


def remove(rest, paths):
    if paths:
        rest.req("/storage/v1/object/" + BUCKET, "DELETE", json.dumps({"prefixes": paths}).encode(),
                 {"Content-Type": "application/json"})


def ensure(rest, d, model, v, out=None):
    """版 v の束が置き場に無ければ作って上げ、古い版を消す。返り値 'up'(上げた)/ 'have'(あった)/ 'moved'(読む間に書かれた)"""
    folder = "%s%s/%s/" % (ROOT, d, model)
    name = name_of(v)
    if out:
        doc = build(rest, d, model, v)
        if doc is None:
            return "moved"
        p = Path(out) / d / model / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(dbn.dump(doc))
        log("書いた %s(%d 行)" % (p, len(doc["rows"])))
        return "up"
    have = listed(rest, folder)
    got = "have"
    if name not in have:
        doc = build(rest, d, model, v)
        if doc is None:
            log("%s %s: 読んでいる間に印が書かれた= 次の回に上げる" % (d, model))
            return "moved"
        data = dbn.dump(doc)
        rest.req("/storage/v1/object/%s/%s%s" % (BUCKET, folder, name), "POST", data,
                 {"Content-Type": "application/json; charset=utf-8", "x-upsert": "true", "Cache-Control": CACHE})
        log("上げた %s/%s%s(%d bytes・%d 行)" % (BUCKET, folder, name, len(data), len(doc["rows"])))
        have.append(name)
        got = "up"
    old = sorted(have, key=age_of)[:-KEEP]
    if old:
        remove(rest, [folder + x for x in old])
        log("消した %s の古い版 %d 本" % (folder, len(old)))
    return got


def once(rest, dates, out=None, seen=None):
    """1 回分。marks_ver が無ければ None。seen = {(日, model): 版}(--watch で前の回と同じ版なら置き場も見ない)"""
    for d in dates:
        ver = marks_ver(rest, d)
        if ver is None:
            return None
        for model in MODELS:
            v = ver.get(model)
            if v is None or (seen is not None and seen.get((d, model)) == v):
                continue   # 行が無い(サイトは束も DB も読まない)・前の回と同じ版
            if ensure(rest, d, model, v, out) != "moved" and seen is not None:
                seen[(d, model)] = v
    return True


def prune_days(rest, keep_from):
    """marks/v1/ の下の日付フォルダのうち keep_from より前を消す"""
    for d in sorted(x for x in listed(rest, ROOT) if len(x) == 10 and x < keep_from):
        n = 0
        for m in listed(rest, ROOT + d + "/"):
            names = listed(rest, "%s%s/%s/" % (ROOT, d, m))
            remove(rest, ["%s%s/%s/%s" % (ROOT, d, m, x) for x in names])
            n += len(names)
        log("消した %s%s(%d 本)" % (ROOT, d, n))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", help="作る日(既定は JST の今日と明日)")
    ap.add_argument("--out", help="上げずにこのフォルダへ書く(試し)")
    ap.add_argument("--watch", type=int, default=0, help="この秒ごとに版を見て、変わった model を上げる(既定 0 = 1 回だけ)")
    ap.add_argument("--until", help="--watch を止める JST の時刻 HH:MM(既定 21:45)")
    a = ap.parse_args(argv)
    if a.watch and a.out:
        log("--watch と --out は一緒に使えない")
        return 1
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 1
    rest = dbn.Rest(base, key)

    def dates():   # --watch は 0 時を越えても回るので毎回作り直す
        today = dt.datetime.now(dbn.JST).date()
        return a.date or [today.isoformat(), (today + dt.timedelta(days=1)).isoformat()]

    if not a.watch:
        try:
            if once(rest, dates(), a.out) is None:
                log("rpc/marks_ver が無い(sql/marks_ver.sql を流す前)= 上げない")
                return 0
            if not a.out:
                prune_days(rest, dt.datetime.now(dbn.JST).date().isoformat())
        except Exception as e:  # noqa: BLE001
            log("作れない %s %s" % (type(e).__name__, str(e)[:200]))
            return 1
        return 0
    hh, mm = (int(x) for x in (a.until or "21:45").split(":"))
    end = dt.datetime.now(dbn.JST).replace(hour=hh, minute=mm, second=0, microsecond=0)
    seen, rc = {}, 0
    log("見張り: %d 秒ごと・%s まで" % (a.watch, end.strftime("%H:%M")))
    while True:
        try:
            if once(rest, dates(), None, seen) is None:
                log("rpc/marks_ver が無い(sql/marks_ver.sql を流す前)= 見張らない")
                return 0
            rc = 0
        except Exception as e:  # noqa: BLE001
            log("回せない %s %s(次の回も試す)" % (type(e).__name__, str(e)[:200]))
            rc = 1
        if dt.datetime.now(dbn.JST) >= end:
            return rc
        time.sleep(a.watch)


if __name__ == "__main__":
    sys.exit(main())

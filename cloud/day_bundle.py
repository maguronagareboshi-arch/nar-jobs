# -*- coding: utf-8 -*-
"""通信量 F1(2026-10-30): 今日・明日の一覧と結果の束を、公開バケット cond-stats の day/v1/<日>/ に上げる。

サイト(nar-viewer js/data.js の narDay・getDayResults)が DB に投げている読みの応答そのものを、日ごとに 2 本へ束ねる。
  list.json = {v, date, built, ver, q, tracks, races: nar_races の行, fin: 着順の CSV}
  res.json  = {v, date, built, ver, q, tracks, top3: 3 着内の CSV, pay: 払戻の行}
⛔ver = rpc/day_ver(sql/day_ver.sql・3 表の更新時刻と行数)を読みの前と後に取り、同じときだけ上げる。
   サイトは DB の今の ver と束の ver が同じときだけ束を使う= 書く便の漏れで束が古くても、画面は DB に戻るだけ。
⛔q はサイトの select と同じ文字(違えばサイトは束を使わない)。場はその日の nar_races の全場(サイトの場はその内側)。
   着順・3 着内はサイトと同じ CSV(select は abc 順)。読みは service_role(表は誰でも全行読める・窓口の回数に数えない)。
⛔Cache-Control は max-age=60。置き場は ?v= を見ない(10/30 実測)= サイトは毎回「変わったか」だけ尋ねる(304)。
⛔今日より前の day/v1/<日>/ は消す(サイトは今日・明日しか使わない・過去の結果をファイルで丸ごと取れないように= 持ち出し対策を弱めない)。

  python cloud/day_bundle.py                                # 今日と明日(JST)を作って上げる・古い日を消す
  python cloud/day_bundle.py --date 2026-10-29 --out DIR    # 上げずに DIR へ書く(試し)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(service_role)。終了コード 0 成功(day_ver が無ければ上げずに 0)/ 1 失敗
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUCKET = "cond-stats"
ROOT = "day/v1/"
CACHE = "public, max-age=60"
UA = "nar-jobs day_bundle (+https://yukochi.com/)"
JST = dt.timezone(dt.timedelta(hours=9))
V = 1
# ⛔サイト js/data.js と同じ文字(NAR_RACE_COLS・DAY_FIN_SEL・DAY_TOP3_Q・DAY_PAY_SEL)。変えるときは両方
RACE_COLS = ("track,race_date,race_no,post_time,race_name,surface,distance_m,weather,going,field_size,condition,"
             "race_last3f,furlongs,race_kind,cancelled,cancel_note")
FIN_SEL = "track,race_no,finish,finish_note,margin"
TOP3_Q = "select=*&finish=lte.3"
PAY_SEL = "track,race_no,payouts"


def log(msg):
    print(dt.datetime.now(JST).strftime("%H:%M:%S"), msg, flush=True)


class Rest:
    def __init__(self, base, key):
        self.base, self.key = base.rstrip("/"), key

    def req(self, path, method="GET", body=None, headers=None, timeout=60):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA}
        if headers:
            h.update(headers)
        for i in range(3):
            try:
                r = urllib.request.Request(self.base + path, method=method, data=body, headers=h)
                with urllib.request.urlopen(r, timeout=timeout) as x:
                    return x.read()
            except urllib.error.HTTPError as e:
                if e.code < 500 or i == 2:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if i == 2:
                    raise
            time.sleep(3 * (i + 1))

    def get(self, q):
        return json.loads(self.req("/rest/v1/" + q, headers={"Accept": "application/json"}) or b"[]")

    def rpc(self, name, args, query="", accept="application/json"):
        return self.req("/rest/v1/rpc/%s%s" % (name, "?" + query if query else ""), "POST",
                        json.dumps(args, ensure_ascii=False).encode("utf-8"),
                        {"Content-Type": "application/json", "Accept": accept})


def csv_query(q):
    # サイトの runsCsvQuery と同じ: select の列を abc 順に(* はそのまま)
    head, _, rest = q.partition("&") if q.startswith("select=") else (q, "", "")
    cols = head[len("select="):].split(",")
    sel = "select=" + ",".join(cols if "*" in cols else sorted(cols))
    return sel + ("&" + rest if rest else "")


def day_ver(rest, d):
    try:
        return json.loads(rest.rpc("day_ver", {"p_date": d}))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None   # まだ sql/day_ver.sql を流していない
        raise


def build(rest, d):
    """(list, res) の dict。読みの前後で版が変われば 1 回だけ読み直す(それでも変われば None)"""
    for attempt in range(2):
        ver = day_ver(rest, d)
        races = rest.get("nar_races?select=%s&race_date=eq.%s&order=track.asc,race_no.asc" % (RACE_COLS, d))
        tracks = list(dict.fromkeys(r["track"] for r in races if r.get("track")))
        fin = top3 = ""
        pay = []
        if tracks:
            args = {"p_tracks": tracks, "p_date": d}
            fin = rest.rpc("runs_day", args, csv_query("select=" + FIN_SEL), "text/csv").decode("utf-8")
            top3 = rest.rpc("runs_day", args, csv_query(TOP3_Q), "text/csv").decode("utf-8")
            tin = urllib.parse.quote("in.(%s)" % ",".join('"%s"' % t for t in tracks))
            pay = rest.get("nar_race_payouts?select=%s&track=%s&race_date=eq.%s" % (PAY_SEL, tin, d))
        if ver is None or day_ver(rest, d) == ver:
            built = dt.datetime.now(JST).isoformat(timespec="seconds")
            head = {"v": V, "date": d, "built": built, "ver": ver}
            return ({**head, "q": {"races": RACE_COLS, "fin": FIN_SEL}, "tracks": tracks, "races": races, "fin": fin},
                    {**head, "q": {"top3": TOP3_Q, "pay": PAY_SEL}, "tracks": tracks, "top3": top3, "pay": pay})
        log("%s: 読んでいる間に DB が書かれた(%d 回目)= 読み直す" % (d, attempt + 1))
    return None


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def upload(rest, path, data):
    rest.req("/storage/v1/object/%s/%s" % (BUCKET, path), "POST", data,
             {"Content-Type": "application/json; charset=utf-8", "x-upsert": "true", "Cache-Control": CACHE})
    want = hashlib.sha256(data).hexdigest()
    for i in range(4):   # 取り直しは認証つきの口+毎回違う ?t=(cond_stats.py と同じ)
        back = rest.req("/storage/v1/object/authenticated/%s/%s?t=%d" % (BUCKET, path, time.time_ns()))
        if hashlib.sha256(back).hexdigest() == want:
            return
        time.sleep(5 * (i + 1))
    raise RuntimeError("取り直した中身が違う: %s/%s" % (BUCKET, path))


def prune(rest, keep_from):
    """day/v1/ の下の日付フォルダのうち keep_from より前を消す"""
    body = json.dumps({"prefix": ROOT, "limit": 1000}).encode()
    items = json.loads(rest.req("/storage/v1/object/list/" + BUCKET, "POST", body, {"Content-Type": "application/json"}))
    old = sorted(x["name"] for x in items if len(x.get("name", "")) == 10 and x["name"] < keep_from)
    for d in old:
        body = json.dumps({"prefix": ROOT + d + "/", "limit": 100}).encode()
        files = json.loads(rest.req("/storage/v1/object/list/" + BUCKET, "POST", body, {"Content-Type": "application/json"}))
        names = [ROOT + d + "/" + f["name"] for f in files if f.get("name")]
        if names:
            rest.req("/storage/v1/object/" + BUCKET, "DELETE", json.dumps({"prefixes": names}).encode(),
                     {"Content-Type": "application/json"})
        log("消した %s(%d 本)" % (ROOT + d, len(names)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", help="作る日(既定は JST の今日と明日)")
    ap.add_argument("--out", help="上げずにこのフォルダへ書く(試し)")
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 1
    rest = Rest(base, key)
    today = dt.datetime.now(JST).date()
    dates = a.date or [today.isoformat(), (today + dt.timedelta(days=1)).isoformat()]
    rc = 0
    for d in dates:
        try:
            got = build(rest, d)
        except Exception as e:  # noqa: BLE001
            log("%s: 作れない %s %s" % (d, type(e).__name__, str(e)[:200]))
            rc = 1
            continue
        if got is None:
            log("%s: 2 回とも読んでいる間に書かれた= 上げない(サイトは DB を読む)" % d)
            continue
        if got[0]["ver"] is None and not a.out:
            log("rpc/day_ver が無い(sql/day_ver.sql を流す前)= 上げない")
            return 0
        for part, doc in zip(("list", "res"), got):
            data = dump(doc)
            if a.out:
                p = Path(a.out) / d / (part + ".json")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                log("書いた %s(%d bytes・場 %d)" % (p, len(data), len(doc["tracks"])))
            else:
                upload(rest, ROOT + d + "/" + part + ".json", data)
                log("上げた %s/%s%s/%s.json(%d bytes・場 %d)" % (BUCKET, ROOT, d, part, len(data), len(doc["tracks"])))
    if not a.out:
        try:
            prune(rest, today.isoformat())
        except Exception as e:  # noqa: BLE001
            log("古い日を消せない %s %s" % (type(e).__name__, str(e)[:200]))
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())

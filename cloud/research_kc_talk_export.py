"""研究用(11/1): 騎手の話は当たっているか — 入力の書き出し(research/kc-talk-check-20261101/SPEC.md)。
⛔本番 DB は REST の単純 select だけ・書き込みなし。出力は KC_TALK_DATA(既定 /tmp/kc_talk)= repo に入れない(公開)。
  runs.csv  = 2023-09-01〜2026-10-30 の全場の走
  talks.csv = 高知のレース後コメントの分類 2024-03-01〜2026-10-30
列の対応: waku= nar_runs.gate・popularity= nar_runs.popularity・going= nar_races.going の頭 1 字(良/稍/重/不・数値の含水率は空)
          status= nar_runs.finish_note(空= ok・取消= torikeshi・除外= jogai・中止= chushi・ほか other)
          field_size= その走の行のうち取消・除外を除いた数(nar_races.field_size は使わない)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "nar-jobs research-kc-talk"
RUN_FROM, RUN_TO = dt.date(2023, 9, 1), dt.date(2026, 10, 30)
TALK_FROM, TALK_TO = dt.date(2024, 3, 1), dt.date(2026, 10, 30)


class Rest:
    def __init__(self, base, key):
        self.base, self.key, self.nreq = base.rstrip("/"), key, 0

    def req(self, path, timeout=120):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA,
             "Accept": "application/json"}
        for i in range(3):
            self.nreq += 1
            try:
                r = urllib.request.Request(self.base + path, headers=h)
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
        return json.loads(self.req("/rest/v1/" + q) or b"[]")

    def paged(self, q, order):
        # ⛔offset には一意の並び
        rows, off = [], 0
        while True:
            part = self.get(f"{q}&order={order}&limit=1000&offset={off}")
            rows += part
            if len(part) < 1000:
                return rows
            off += 1000


def enc(v):
    return urllib.parse.quote(str(v), safe="")


def months(d_from, d_to):
    d = d_from.replace(day=1)
    while d <= d_to:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield max(d, d_from), min(nxt - dt.timedelta(days=1), d_to)
        d = nxt


def status_of(note):
    n = note or ""
    if not n.strip():
        return "ok"
    if "取消" in n:
        return "torikeshi"
    if "除外" in n:
        return "jogai"
    if "中止" in n:
        return "chushi"
    return "other"


def going1(g):
    g = (g or "").strip()
    return g[0] if g[:1] in ("良", "稍", "重", "不") else ""


def s(v):
    return "" if v is None else str(v)


def main():
    base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    out = os.environ.get("KC_TALK_DATA", "/tmp/kc_talk")
    os.makedirs(out, exist_ok=True)
    rest = Rest(base, key)

    races, runs = {}, []
    for a, b in months(RUN_FROM, RUN_TO):
        rng = f"&race_date=gte.{a.isoformat()}&race_date=lte.{b.isoformat()}"
        for r in rest.paged("nar_races?select=track,race_date,race_no,distance_m,going" + rng,
                            "race_date,track,race_no"):
            races[(r["track"], r["race_date"], r["race_no"])] = r
        runs += rest.paged("nar_runs?select=track,race_date,race_no,runner_number,gate,horse_name,birth_date,"
                           "finish,finish_note,popularity" + rng, "race_date,track,race_no,runner_number")
        print(f"  {a:%Y-%m} races={len(races)} runs={len(runs)} req={rest.nreq}", flush=True)

    field = {}
    for x in runs:
        if status_of(x["finish_note"]) not in ("torikeshi", "jogai"):
            k = (x["track"], x["race_date"], x["race_no"])
            field[k] = field.get(k, 0) + 1

    cols = ["horse_key", "track", "race_date", "race_no", "umaban", "waku", "distance_m", "going",
            "finish", "popularity", "field_size", "status"]
    run_ix = {}
    with open(os.path.join(out, "runs.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        rows_out = []
        for x in runs:
            k = (x["track"], x["race_date"], x["race_no"])
            rc = races.get(k) or {}
            hk = (x["horse_name"] or "") + "|" + s(x["birth_date"])
            st = status_of(x["finish_note"])
            row = [hk, x["track"], x["race_date"], x["race_no"], x["runner_number"], s(x["gate"]),
                   s(rc.get("distance_m")), going1(rc.get("going")), s(x["finish"]), s(x["popularity"]),
                   field.get(k, 0), st]
            w.writerow(row)
            rows_out.append(row)
            if x["track"] == "高知":
                run_ix[(x["race_date"], x["race_no"], x["runner_number"], x["horse_name"])] = (hk, st, rc)

    rng = f"&track=eq.{enc('高知')}&race_date=gte.{TALK_FROM.isoformat()}&race_date=lte.{TALK_TO.isoformat()}"
    talks = rest.paged("nar_race_comments_lab?select=race_date,race_no,umaban,horse_name,labels" + rng,
                       "race_date,race_no,umaban,horse_name")
    n_talk, n_nomatch, n_scratch, n_badlab = 0, 0, 0, 0
    with open(os.path.join(out, "talks.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["horse_key", "race_date", "race_no", "distance_m", "labels"])
        for c in talks:
            if not isinstance(c.get("labels"), list):
                n_badlab += 1
                continue
            m = run_ix.get((c["race_date"], c["race_no"], c["umaban"], c["horse_name"]))
            if not m:
                n_nomatch += 1
                continue
            hk, st, rc = m
            if st in ("torikeshi", "jogai"):   # kc_today_traits と同じ= 取消・除外の走のコメントは使わない
                n_scratch += 1
                continue
            w.writerow([hk, c["race_date"], c["race_no"], s(rc.get("distance_m")),
                        json.dumps(c["labels"], ensure_ascii=False)])
            n_talk += 1

    print(f"runs.csv {len(rows_out)} 行 {min(r[2] for r in rows_out)}〜{max(r[2] for r in rows_out)}")
    for i, c in enumerate(cols):
        e = sum(1 for r in rows_out if s(r[i]) == "")
        print(f"  空欄 {c}: {e / max(len(rows_out), 1):.3%}")
    kc = [r for r in rows_out if r[1] == "高知"]
    print(f"  高知 {len(kc)} 行・status: " + ", ".join(
        f"{k}={sum(1 for r in rows_out if r[11] == k)}" for k in ("ok", "torikeshi", "jogai", "chushi", "other")))
    print(f"talks.csv {n_talk} 行 (取得 {len(talks)}・走と合わない {n_nomatch}・取消除外 {n_scratch}・labels 非配列 {n_badlab})"
          + (f" {min(c['race_date'] for c in talks)}〜{max(c['race_date'] for c in talks)}" if talks else ""))
    print(f"REST 要求 {rest.nreq} 回")


if __name__ == "__main__":
    sys.exit(main())

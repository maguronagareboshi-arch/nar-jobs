# -*- coding: utf-8 -*-
"""§291 チェック馬のお知らせ(web push)を送る。nar-refresh.yml の refresh の後に 1 回。

  python cloud/push_notify.py            … 既定= --dry-run(対象を数えて出すだけ・書かない・送らない)
  python cloud/push_notify.py --apply    … nar_push_sent に先に入れ、入った分だけ送る
  python cloud/push_notify.py --fixture F.json … DB の代わりに {"subs":[],"horses":[],"runs":[]} を読む(手元の確認用)

種類:
  A= 出走が決まった(未来のレースの出走が取り込まれた)。⛔初回の洪水よけ= その出走の取り込み時刻(updated_at)が購読の作成より後
  C= 結果が出た(その馬の着順が入った)。⛔確定(updated_at)が購読の作成より後 かつ 直近 3 時間
突き合わせ: nar_push_subs.device_id × nar_viewer_horses(device_id, horse_id)。horse_id は nar:/name:(馬名)・
  nary:<生年>:(馬名+生年)・narb:<生年月日>:(馬名+生年月日)。kochi:/kb: は馬名が無いので送らない。
二重送信防止: nar_push_sent (device,horse,race,kind) に**先に** insert(重複は無視)→ 返ってきた行だけ送る。
失敗: 404/410= 購読を消す・その他= fail_count+1(5 回で消す)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / NAR_VAPID_PRIVATE(無ければ --apply でも送らず exit 0)/ NAR_VAPID_SUBJECT(mailto:…)
heartbeat: nar_job_heartbeat の 'push_notify'(--apply のときだけ)。
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

JST = dt.timezone(dt.timedelta(hours=9))
TITLE = "地方競馬ウォッチ"                 # 見出しは sw.js が固定で出す(ここは payload の控え)
C_WINDOW = dt.timedelta(hours=3)
PER_DEVICE_MAX = 10                        # 1 回の実行で 1 端末に送る上限(残りは次の回)
FAIL_MAX = 5
SENT_KEEP_DAYS = 60
UA = "nar-jobs push_notify (+https://nar.yukochi.com/)"

# サイトの URL 表記(share_image.py の TRACK_PREFIX と同じ)
TRACK_PREFIX = {
    "帯広": "obihiro", "帯広ば": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa",
    "浦和": "urawa", "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
    "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
}
SHOW_TRACK = {"帯広ば": "帯広"}
NO_RUN_NOTES = ("取消", "除外")


def log(*a):
    print(*a, flush=True)


def parse_ts(s):
    if not s:
        return None
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def parse_horse_id(hid):
    """→ (馬名, 生年 or None, 生年月日 or None)。馬名が取れない id は None。"""
    s = str(hid or "")
    for p in ("nar:", "name:"):
        if s.startswith(p) and len(s) > len(p):
            return (s[len(p):], None, None)
    if s.startswith("nary:"):
        y, _, n = s[5:].partition(":")
        if len(y) == 4 and y.isdigit() and n:
            return (n, int(y), None)
    if s.startswith("narb:"):
        b, _, n = s[5:].partition(":")
        if len(b) == 10 and n:
            return (n, None, b)
    return None


def run_matches(run, key):
    name, year, birth = key
    if run.get("horse_name") != name:
        return False
    bd = str(run.get("birth_date") or "")
    if year is not None and bd and bd[:4] != str(year):
        return False
    if birth is not None and bd and bd[:10] != birth:
        return False
    return True


def race_id(run):
    pre = TRACK_PREFIX.get(run.get("track"))
    if not pre:
        return None
    return "%s/%s/%d" % (pre, str(run["race_date"])[:10], int(run["race_no"]))


def pick(subs, horses, runs, now):
    """対象を出す(DB 不要・純粋関数)。→ [{device_id, horse_id, race_id, kind, name, track, race_date, race_no, finish}]
    1 端末に複数の購読があっても対象は device 単位で 1 つ(送るときに購読ぶん配る)。"""
    today = now.astimezone(JST).date().isoformat()
    by_dev = {}
    for s in subs:
        d = by_dev.setdefault(s["device_id"], {"a": None, "c": None})
        ca = parse_ts(s.get("created_at"))
        # 同じ端末に購読が複数= いちばん古い作成時刻を基準にする(want はどれか 1 つでも入っていれば)
        if s.get("want_a"):
            d["a"] = ca if d["a"] is None or ca < d["a"] else d["a"]
        if s.get("want_c"):
            d["c"] = ca if d["c"] is None or ca < d["c"] else d["c"]
    out, seen = [], set()
    for h in horses:
        dev = h["device_id"]
        if dev not in by_dev:
            continue
        key = parse_horse_id(h.get("horse_id"))
        if not key:
            continue
        base = by_dev[dev]
        for r in runs:
            if not run_matches(r, key):
                continue
            rid = race_id(r)
            if not rid:
                continue
            up = parse_ts(r.get("updated_at"))
            note = str(r.get("finish_note") or "")
            rdate = str(r["race_date"])[:10]
            kind = None
            if r.get("finish") is None:
                if base["a"] and rdate >= today and up and up > base["a"] and not any(x in note for x in NO_RUN_NOTES):
                    kind = "A"
            elif base["c"] and up and up > base["c"] and now - up <= C_WINDOW:
                kind = "C"
            if not kind or (dev, h["horse_id"], rid, kind) in seen:
                continue
            seen.add((dev, h["horse_id"], rid, kind))
            out.append({"device_id": dev, "horse_id": h["horse_id"], "race_id": rid, "kind": kind,
                        "name": key[0], "track": r["track"], "race_date": rdate, "race_no": int(r["race_no"]),
                        "finish": r.get("finish")})
    out.sort(key=lambda x: (x["device_id"], x["race_date"], x["track"], x["race_no"], x["kind"], x["horse_id"]))
    capped, n = [], {}
    for x in out:
        n[x["device_id"]] = n.get(x["device_id"], 0) + 1
        if n[x["device_id"]] <= PER_DEVICE_MAX:
            capped.append(x)
    return capped


def message(x):
    tr = SHOW_TRACK.get(x["track"], x["track"])
    md = "%d/%d" % (int(x["race_date"][5:7]), int(x["race_date"][8:10]))
    if x["kind"] == "A":
        body = "%s が %s %s %dR に出走します" % (x["name"], md, tr, x["race_no"])
    else:
        body = "%s の %s %s %dR の結果: %s着" % (x["name"], md, tr, x["race_no"], x["finish"])
    return {"title": TITLE, "body": body, "url": "/race/" + x["race_id"],
            "tag": "%s:%s:%s" % (x["kind"], x["horse_id"], x["race_id"])}


# ---------------------------------------------------------------- DB(REST・service_role)
class Rest:
    def __init__(self):
        self.base = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_KEY"]

    def req(self, path, method="GET", body=None, prefer=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA,
             "Content-Type": "application/json"}
        if prefer:
            h["Prefer"] = prefer
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        r = urllib.request.Request(self.base + "/rest/v1/" + path, method=method, data=data, headers=h)
        with urllib.request.urlopen(r, timeout=60) as x:
            raw = x.read()
        return json.loads(raw) if raw else None

    def get(self, table, **q):
        qs = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe=".,()*:\"")) for k, v in q.items())
        return self.req("%s?%s" % (table, qs)) or []


def pg_in(vals):
    return "in.(" + ",".join('"%s"' % str(v).replace('"', '') for v in vals) + ")"


def load(rest, now):
    subs = rest.get("nar_push_subs", select="endpoint,device_id,p256dh,auth,want_a,want_c,created_at,fail_count",
                    **{"or": "(want_a.is.true,want_c.is.true)"})
    if not subs:
        return subs, [], []
    devs = sorted({s["device_id"] for s in subs})
    horses = []
    for i in range(0, len(devs), 50):
        horses += rest.get("nar_viewer_horses", select="device_id,horse_id", device_id=pg_in(devs[i:i + 50]))
    names = sorted({k[0] for k in (parse_horse_id(h["horse_id"]) for h in horses) if k})
    since = (now.astimezone(JST).date() - dt.timedelta(days=1)).isoformat()   # ⛔区画を絞る(昨日以降だけ)
    runs = []
    for i in range(0, len(names), 40):
        runs += rest.get("nar_runs", select="track,race_date,race_no,horse_name,birth_date,finish,finish_note,updated_at",
                         horse_name=pg_in(names[i:i + 40]), race_date="gte." + since)
    return subs, horses, runs


def claim(rest, x):
    """nar_push_sent に先に入れる。入った(=初めて)なら True。重複は無視される(返りが空)。"""
    got = rest.req("nar_push_sent?on_conflict=device_id,horse_id,race_id,kind", "POST",
                   [{k: x[k] for k in ("device_id", "horse_id", "race_id", "kind")}],
                   prefer="resolution=ignore-duplicates,return=representation")
    return bool(got)


def send_all(rest, subs, targets, vapid_private, vapid_sub):
    from pywebpush import webpush, WebPushException   # --apply のときだけ要る
    by_dev = {}
    for s in subs:
        by_dev.setdefault(s["device_id"], []).append(s)
    sent = skipped = failed = gone = 0
    dead = set()
    for x in targets:
        if not claim(rest, x):
            skipped += 1
            continue
        payload = json.dumps(message(x), ensure_ascii=False)
        for s in by_dev.get(x["device_id"], []):
            if s["endpoint"] in dead or not s.get("want_a" if x["kind"] == "A" else "want_c"):
                continue
            ep = urllib.parse.quote(s["endpoint"], safe="")
            try:
                webpush(subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                        data=payload, vapid_private_key=vapid_private, vapid_claims={"sub": vapid_sub}, ttl=6 * 3600)
                sent += 1
                if s.get("fail_count"):
                    rest.req("nar_push_subs?endpoint=eq." + ep, "PATCH", {"fail_count": 0}, prefer="return=minimal")
                    s["fail_count"] = 0
            except WebPushException as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                failed += 1
                fc = int(s.get("fail_count") or 0) + 1
                if code in (404, 410) or fc >= FAIL_MAX:
                    rest.req("nar_push_subs?endpoint=eq." + ep, "DELETE", prefer="return=minimal")
                    dead.add(s["endpoint"]); gone += 1
                else:
                    rest.req("nar_push_subs?endpoint=eq." + ep, "PATCH", {"fail_count": fc}, prefer="return=minimal")
                    s["fail_count"] = fc
                log("  失敗 %s %s: %s" % (code, x["kind"], str(e)[:120]))
    return sent, skipped, failed, gone


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="記録して送る")
    g.add_argument("--dry-run", action="store_true", help="数えて出すだけ(既定)")
    ap.add_argument("--fixture", help="DB の代わりに読む JSON(dry-run 専用)")
    ap.add_argument("--now", help="ISO 時刻(fixture の確認用)")
    a = ap.parse_args()
    now = parse_ts(a.now) if a.now else dt.datetime.now(dt.timezone.utc)

    if a.fixture:
        with open(a.fixture, encoding="utf-8") as f:
            fx = json.load(f)
        subs, horses, runs = fx.get("subs", []), fx.get("horses", []), fx.get("runs", [])
        a.apply = False
        rest = None
    else:
        vapid = os.environ.get("NAR_VAPID_PRIVATE", "").strip()
        if a.apply and not vapid:
            log("NAR_VAPID_PRIVATE が無い= 送らずに終わる"); return 0
        if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
            log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 1
        rest = Rest()
        try:
            subs, horses, runs = load(rest, now)
        except urllib.error.HTTPError as e:
            if e.code == 404:                                   # 表がまだ無い(migration 前)= 静かに抜ける
                log("nar_push_subs が無い(migration 前)= 何もしない"); return 0
            raise

    targets = pick(subs, horses, runs, now)
    na = sum(1 for x in targets if x["kind"] == "A")
    log("購読 %d・端末 %d・馬 %d・出走 %d → 対象 A=%d C=%d" % (
        len(subs), len({s["device_id"] for s in subs}), len(horses), len(runs), na, len(targets) - na))
    for x in targets[:20]:
        log("  %s %s" % (x["kind"], message(x)["body"]))
    if not a.apply:
        log("(dry-run: 書かない・送らない)")
        return 0

    import beat
    try:
        sent, skipped, failed, gone = send_all(rest, subs, targets, vapid,
                                               os.environ.get("NAR_VAPID_SUBJECT", "").strip() or "https://nar.yukochi.com")   # ⛔末尾の / があると py_vapid が弾く(§291 通し試験)
        cut = (now - dt.timedelta(days=SENT_KEEP_DAYS)).isoformat()
        rest.req("nar_push_sent?sent_at=lt." + urllib.parse.quote(cut), "DELETE", prefer="return=minimal")
    except Exception as e:                                       # noqa: BLE001
        beat.beat("push_notify", False, "%s: %s" % (type(e).__name__, str(e)[:80]))
        raise
    log("送った %d・送信済みで飛ばした %d・失敗 %d・消した購読 %d" % (sent, skipped, failed, gone))
    beat.beat("push_notify", True, "送信 %d・失敗 %d" % (sent, failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

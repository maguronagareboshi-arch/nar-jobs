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
heartbeat: nar_job_heartbeat の 'push_notify'(夜便 --slot night は 'push_night')(--apply のときだけ)。

B2(10/17 案B)☆の騎手・調教師と重賞の日(各 1 端末 1 日 1 通・まとめ文):
  P= 明日の☆の人の出番(JST 20 時台の回)・R= 今日の☆の人の結果(夜便 push-night.yml 22:37)・
  G= 今日の地方重賞(JST 9 時台の回・want_g の人だけ)。P/R は want_p。
  --slot auto(既定)= 時刻で P/G を足す・night= R と C だけ・p/r/g= その種類を必ず足す(手元の確認用)。
  照合= 画面と同じ: 名前一致 かつ(any_venue か venues 空か venues に場の prefix)。nar_runs.jockey/trainer と
  ☆の name(短い公式表記・nar_persons.name_short)は同じ表記(10/17 本物で照合)。
  二重送りよけ= nar_push_sent に horse_id `p:<日付>`/`r:<日付>`/`g:<日付>`・race_id=日付・kind P/R/G を先に insert。
  ⛔表 nar_viewer_people・列 want_p/want_g が本番に無い(400/404)ときは P/R/G を飛ばし、今までの A/C だけ送る。
"""
import argparse
import datetime as dt
import json
import re
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
PUSH_TIMEOUT = 10   # 秒。送信先 1 件の待ち上限(pywebpush 2.x の webpush(timeout=))
SENT_KEEP_DAYS = 60
UA = "nar-jobs push_notify (+https://yukochi.com/)"

# サイトの URL 表記(share_image.py の TRACK_PREFIX と同じ)
TRACK_PREFIX = {
    "帯広": "obihiro", "帯広ば": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa",
    "浦和": "urawa", "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
    "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
}
SHOW_TRACK = {"帯広ば": "帯広"}
NO_RUN_NOTES = ("取消", "除外")
GRADED_KINDS = ("重賞", "準重賞")
SLOT_P_HOUR = 20                           # JST 20 時台の回で P(30 分おきの 2 回とも当たるが nar_push_sent の鍵で 1 日 1 通)
SLOT_G_HOUR = 9                            # JST 9 時台の回で G
WANT_COL = {"A": "want_a", "C": "want_c", "P": "want_p", "R": "want_p", "G": "want_g"}


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


def latest_per_device(subs):
    """同じ device_id に送り先(endpoint)が複数ある= created_at が一番新しい 1 本だけ残す(DB 不要・純粋関数)。
    同時刻(または created_at なし同士)は endpoint の文字順で最後の 1 本。住所の引っ越しで旧住所と新住所の
    購読が同じ端末に並ぶと同じ通知が 2 回届くのを防ぐ。古い行は消さない(送らないだけ)。入力の順は保つ。"""
    best = {}
    for s in subs:
        key = (parse_ts(s.get("created_at")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc), s.get("endpoint") or "")
        cur = best.get(s["device_id"])
        if cur is None or key > cur[0]:
            best[s["device_id"]] = (key, s)
    keep = {id(v[1]) for v in best.values()}
    return [s for s in subs if id(s) in keep]


def pick(subs, horses, runs, now):
    """対象を出す(DB 不要・純粋関数)。→ [{device_id, horse_id, race_id, kind, name, track, race_date, race_no, finish}]
    1 端末に複数の購読があっても一番新しい 1 本(latest_per_device)だけで want と基準時刻を決める。"""
    today = now.astimezone(JST).date().isoformat()
    by_dev = {}
    for s in latest_per_device(subs):
        d = by_dev.setdefault(s["device_id"], {"a": None, "c": None})
        ca = parse_ts(s.get("created_at"))
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
    if x["kind"] in ("P", "R", "G"):
        return {"title": TITLE, "body": x["body"], "url": x["url"], "tag": "%s:%s" % (x["kind"], x["race_id"])}
    tr = SHOW_TRACK.get(x["track"], x["track"])
    md = "%d/%d" % (int(x["race_date"][5:7]), int(x["race_date"][8:10]))
    if x["kind"] == "A":
        body = "%s が %s %s %dR に出走します" % (x["name"], md, tr, x["race_no"])
    else:
        body = "%s の %s %s %dR の結果: %s着" % (x["name"], md, tr, x["race_no"], x["finish"])
    return {"title": TITLE, "body": body, "url": "/race/" + x["race_id"],
            "tag": "%s:%s:%s" % (x["kind"], x["horse_id"], x["race_id"])}


# ---------------------------------------------------------------- B2 ☆の人・重賞の日(純粋関数)
def slot_kinds(slot, now):
    """→ (この回で足すまとめ通知の種類 P/R/G の集合, 馬の通知のうち送る種類)。"""
    h = now.astimezone(JST).hour
    if slot == "night":
        return {"R"}, {"C"}
    if slot in ("p", "r", "g"):
        return {slot.upper()}, {"A", "C"}
    extra = set()
    if h == SLOT_P_HOUR:
        extra.add("P")
    if h == SLOT_G_HOUR:
        extra.add("G")
    return extra, {"A", "C"}


def person_hit(p, run):
    """画面の starPersonHit と同じ: 名前一致 かつ(any_venue か venues 空か venues に場の prefix)。"""
    if run.get(p.get("kind")) != p.get("name"):
        return False
    if p.get("any_venue"):
        return True
    vs = p.get("venues") or []
    return not vs or TRACK_PREFIX.get(run.get("track")) in vs


def is_scratch(run):
    note = str(run.get("finish_note") or "")
    return any(x in note for x in NO_RUN_NOTES)


def people_stats(people, runs, date):
    """☆の人ごとに date の鞍(取消・除外を除く)を数える。→ [{name, kind, tracks, n, done, places}](鞍 0 の人は除く)。"""
    out = []
    for p in people:
        rows, seen = [], set()
        for r in runs:
            if str(r.get("race_date"))[:10] != date or is_scratch(r) or not person_hit(p, r):
                continue
            k = (r.get("track"), int(r["race_no"]), r.get("runner_number"), r.get("horse_name"))
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
        if not rows:
            continue
        tracks = []
        for r in sorted(rows, key=lambda r: int(r["race_no"])):
            t = SHOW_TRACK.get(r["track"], r["track"])
            if t not in tracks:
                tracks.append(t)
        places, done = {1: 0, 2: 0, 3: 0}, 0
        for r in rows:
            f = r.get("finish")
            if f is None:
                continue
            done += 1
            try:
                fi = int(f)
            except (TypeError, ValueError):
                continue
            if fi in places:
                places[fi] += 1
        out.append({"name": p["name"], "kind": p.get("kind"), "tracks": tracks, "n": len(rows), "done": done, "places": places})
    return out


def body_p(stats):
    return "明日の出番: " + "・".join("%s(%s)%d鞍" % (x["name"], "・".join(x["tracks"]), x["n"]) for x in stats)


def body_r(stats):
    parts = []
    for x in stats:
        pl = "・".join("%d着%d回" % (k, x["places"][k]) for k in (1, 2, 3) if x["places"][k])
        if not pl:
            pl = "3着以内なし" if x["done"] else "未確定"
        cnt = "%d鞍" % x["n"] if x["done"] >= x["n"] else "確定%d/%d鞍" % (x["done"], x["n"])
        parts.append("%s %s(%s)" % (x["name"], pl, cnt))
    return "今日の結果: " + "・".join(parts)


def graded_name(n):
    return re.sub(r"^第[0-9０-９]+回\s*", "", str(n or "")).strip()


def body_g(races):
    rs = sorted(races, key=lambda r: (str(r.get("post_time") or "9999"), r.get("track") or "", int(r.get("race_no") or 0)))
    parts = []
    for r in rs:
        pt = str(r.get("post_time") or "")
        hm = " %s:%s" % (pt[:2], pt[2:4]) if len(pt) == 4 and pt.isdigit() else ""
        parts.append("%s %s%s" % (SHOW_TRACK.get(r["track"], r["track"]), graded_name(r.get("race_name")), hm))
    return "今日の重賞: " + "・".join(parts)


def pick_people(subs, people, runs, graded, now, kinds):
    """P/R/G のまとめ通知(1 端末 1 種類 1 通)。people=None は表が無い= P/R を出さない・graded が空/None は G を出さない。"""
    if not kinds:
        return []
    jd = now.astimezone(JST).date()
    today, tomorrow = jd.isoformat(), (jd + dt.timedelta(days=1)).isoformat()
    by_dev = {}
    for p in people or []:
        by_dev.setdefault(p["device_id"], []).append(p)
    out = []
    for s in latest_per_device(subs):
        dev = s["device_id"]
        for kind in ("P", "R", "G"):
            if kind not in kinds or not s.get(WANT_COL[kind]):
                continue
            if kind == "G":
                if not graded:
                    continue
                date, body, url = today, body_g(graded), "/graded/week"
            else:
                if people is None or not by_dev.get(dev):
                    continue
                date = tomorrow if kind == "P" else today
                st = people_stats(by_dev[dev], runs, date)
                if not st:
                    continue
                body = body_p(st) if kind == "P" else body_r(st)
                url = "/mymarks"
            out.append({"device_id": dev, "horse_id": "%s:%s" % (kind.lower(), date), "race_id": date, "kind": kind,
                        "body": body, "url": url})
    return out


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


def load_subs(rest):
    """→ subs。want_p/want_g の列がまだ無い(400)ときは今までの形で読み直す(☆の人・重賞は飛ぶ)。"""
    try:
        return rest.get("nar_push_subs", select="endpoint,device_id,p256dh,auth,want_a,want_c,want_p,want_g,created_at,fail_count",
                        **{"or": "(want_a.is.true,want_c.is.true,want_p.is.true,want_g.is.true)"})
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        log("nar_push_subs に want_p/want_g が無い= ☆の人・重賞は飛ばす")
    return rest.get("nar_push_subs", select="endpoint,device_id,p256dh,auth,want_a,want_c,created_at,fail_count",
                    **{"or": "(want_a.is.true,want_c.is.true)"})


def load_people(rest, subs, now, kinds):
    """→ (people or None, runs, graded or None)。表・列が無い(400/404)は None= その種類を飛ばす。"""
    people, pruns, graded = None, [], None
    jd = now.astimezone(JST).date()
    devs = sorted({s["device_id"] for s in subs if s.get("want_p")})
    if devs and kinds & {"P", "R"}:
        try:
            people = []
            for i in range(0, len(devs), 50):
                people += rest.get("nar_viewer_people", select="device_id,kind,name,venues,any_venue,added_at",
                                   device_id=pg_in(devs[i:i + 50]), order="device_id,added_at,name")
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404):
                raise
            log("nar_viewer_people が無い(%d)= ☆の人は飛ばす" % e.code)
            people = None
        if people:
            date = (jd + dt.timedelta(days=1)).isoformat() if "P" in kinds else jd.isoformat()
            for col in ("jockey", "trainer"):
                names = sorted({p["name"] for p in people if p.get("kind") == col})
                for i in range(0, len(names), 40):
                    pruns += rest.get("nar_runs", select="track,race_date,race_no,runner_number,horse_name,jockey,trainer,finish,finish_note",
                                      **{col: pg_in(names[i:i + 40]), "race_date": "eq." + date})
    if "G" in kinds and any(s.get("want_g") for s in subs):
        graded = rest.get("nar_races", select="track,race_date,race_no,race_name,race_kind,post_time",
                          race_date="eq." + jd.isoformat(), race_kind=pg_in(GRADED_KINDS))
    return people, pruns, graded


def load(rest, now):
    subs = load_subs(rest)
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
    """nar_push_sent に先に入れる。入った(=初めて)なら True。重複は無視される(返りが空)。
    P/R/G で 400(kind の check がまだ A/C だけ)は送らない= False。"""
    try:
        got = rest.req("nar_push_sent?on_conflict=device_id,horse_id,race_id,kind", "POST",
                       [{k: x[k] for k in ("device_id", "horse_id", "race_id", "kind")}],
                       prefer="resolution=ignore-duplicates,return=representation")
    except urllib.error.HTTPError as e:
        if e.code != 400 or x["kind"] not in ("P", "R", "G"):
            raise
        log("  nar_push_sent が %s を受け付けない(check 前)= 送らない" % x["kind"])
        return False
    return bool(got)


def send_all(rest, subs, targets, vapid_private, vapid_sub):
    from pywebpush import webpush, WebPushException   # --apply のときだけ要る
    by_dev = {}
    for s in latest_per_device(subs):                  # 同じ端末へは一番新しい送り先 1 本だけ(二重送信よけ)
        by_dev.setdefault(s["device_id"], []).append(s)
    sent = skipped = failed = gone = 0
    dead = set()
    for x in targets:
        if not claim(rest, x):
            skipped += 1
            continue
        payload = json.dumps(message(x), ensure_ascii=False)
        for s in by_dev.get(x["device_id"], []):
            if s["endpoint"] in dead or not s.get(WANT_COL[x["kind"]]):
                continue
            ep = urllib.parse.quote(s["endpoint"], safe="")
            try:
                webpush(subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                        data=payload, vapid_private_key=vapid_private, vapid_claims={"sub": vapid_sub}, ttl=6 * 3600,
                        timeout=PUSH_TIMEOUT)
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
            except Exception as e:                               # noqa: BLE001  壊れた鍵(ValueError 等)・通信の時間切れ
                failed += 1                                      # 1 件の異常で残りの送信先を止めない。⛔鍵の中身は出さない
                log("  失敗 %s %s(送信前の異常・購読は触らない)" % (type(e).__name__, x["kind"]))
            else:
                sent += 1
                if s.get("fail_count"):
                    rest.req("nar_push_subs?endpoint=eq." + ep, "PATCH", {"fail_count": 0}, prefer="return=minimal")
                    s["fail_count"] = 0
    return sent, skipped, failed, gone


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="記録して送る")
    g.add_argument("--dry-run", action="store_true", help="数えて出すだけ(既定)")
    ap.add_argument("--fixture", help="DB の代わりに読む JSON(dry-run 専用)")
    ap.add_argument("--now", help="ISO 時刻(fixture の確認用)")
    ap.add_argument("--slot", default="auto", choices=["auto", "night", "p", "r", "g"],
                    help="auto= 時刻で P(20 時台)/G(9 時台)を足す・night= 夜便(R と C)")
    a = ap.parse_args()
    now = parse_ts(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    extra, horse_kinds = slot_kinds(a.slot, now)
    hb = "push_night" if a.slot == "night" else "push_notify"

    if a.fixture:
        with open(a.fixture, encoding="utf-8") as f:
            fx = json.load(f)
        subs, horses, runs = fx.get("subs", []), fx.get("horses", []), fx.get("runs", [])
        people, pruns, graded = fx.get("people"), fx.get("runs", []), fx.get("graded")
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
            people, pruns, graded = load_people(rest, subs, now, extra) if subs else (None, [], None)
        except urllib.error.HTTPError as e:
            if e.code == 404:                                   # 表がまだ無い(migration 前)= 静かに抜ける
                log("nar_push_subs が無い(migration 前)= 何もしない"); return 0
            raise

    targets = [x for x in pick(subs, horses, runs, now) if x["kind"] in horse_kinds]
    targets += pick_people(subs, people, pruns, graded, now, extra)
    cnt = {k: sum(1 for x in targets if x["kind"] == k) for k in "ACPRG"}
    log("購読 %d・端末 %d・馬 %d・出走 %d・slot %s(足す %s)→ 対象 %s" % (
        len(subs), len({s["device_id"] for s in subs}), len(horses), len(runs), a.slot, "".join(sorted(extra)) or "-",
        " ".join("%s=%d" % kv for kv in cnt.items())))
    for x in targets[:20]:
        log("  %s %s" % (x["kind"], message(x)["body"]))
    if not a.apply:
        log("(dry-run: 書かない・送らない)")
        return 0

    import beat
    try:
        sent, skipped, failed, gone = send_all(rest, subs, targets, vapid,
                                               os.environ.get("NAR_VAPID_SUBJECT", "").strip() or "https://yukochi.com")   # ⛔末尾の / があると py_vapid が弾く(§291 通し試験)
        cut = (now - dt.timedelta(days=SENT_KEEP_DAYS)).isoformat()
        rest.req("nar_push_sent?sent_at=lt." + urllib.parse.quote(cut), "DELETE", prefer="return=minimal")
    except Exception as e:                                       # noqa: BLE001
        beat.beat(hb, False, "%s: %s" % (type(e).__name__, str(e)[:80]))
        raise
    log("送った %d・送信済みで飛ばした %d・失敗 %d・消した購読 %d" % (sent, skipped, failed, gone))
    beat.beat(hb, True, "送信 %d・失敗 %d" % (sent, failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

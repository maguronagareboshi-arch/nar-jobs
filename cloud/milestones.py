# -*- coding: utf-8 -*-
"""B3 区切りの勝利(騎手だけ・2026-10-17)。毎朝、現役の地方騎手の公式個票 RiderMark から
「生涯成績 地方競馬」の 1 着と合計を読み、公開バケット cond-stats の v1/milestones.json に書く。

出所= nar-site research/site-boost-20261017/b3-source.md(公式個票は前日分まで入る・10/17 実測)。
  騎手= nar_persons(kind=jockey・現役・area が JRA でない)のうち nar_person_stats(all/all)の最後の騎乗が 1 年以内
  あと= 次の区切り(100 刻み)− 公式の地方通算勝
  最近の達成(60 日)= 公式通算 N・区切り M=N//100*100 → nar_runs の 1 着を新しい順に並べた (N−M+1) 番目のレース
     何戦目= 公式の合計 − そのレースより後の騎乗数(取消・除外は数えない)
  ⛔免許番号⇔走りの略称は nar_persons の略称で決めない= 公式の今年の勝ち数と nar_runs の今年の勝ち数が
    一致する候補 1 つ(map_shorts)。一致しない・1 対 1 でない騎手は 達成の特定も今日の騎乗もしない(あとだけ)
  ⛔本番 DB は REST の単純 select だけ(書くのは Storage の cond-stats/v1/milestones.json だけ)

  python3 cloud/milestones.py --apply                       # 本番(REST+個票+上げる)
  python3 cloud/milestones.py --dry-run --out DIR           # 上げずに DIR/milestones.json
  py -3 -X utf8 cloud/milestones.py --local ...             # 手元(DB 鍵なし)。下の --local-* を参照
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

JST = dt.timezone(dt.timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MARK = "https://www.keiba.go.jp/KeibaWeb/DataRoom/RiderMark?k_riderLicenseNo="
WAIT = 1.5                       # ⛔1 本ずつ+間隔(persons.py の 1.2 より控えめ)
STEP = 100
RECENT_DAYS = 60
NAME = "milestones.json"
EXCL = ("取消", "除外")


def log(msg):
    print(msg, flush=True)


# ---------- 公式個票 ----------
def text_lines(html):
    h = re.sub(r"(?s)<(script|style).*?</\1>", " ", html)
    return [x.strip() for x in re.sub(r"<[^>]+>", "\n", h).split("\n") if x.strip()]


def split_name(raw):
    """飾りの空白を落として '姓 名'。⛔2 つ以上の空白が切れ目・1 つは字間(persons.py と同じ)。"""
    parts = [re.sub(r"[\s　]", "", p) for p in re.split(r"[\s　]{2,}", raw)]
    parts = [p for p in parts if p]
    return " ".join(parts[:1] + ["".join(parts[1:])]) if len(parts) >= 2 else "".join(parts)


def parse_mark(html):
    """→ {name, area, wins, starts} 。読めなければ wins=None。"""
    t = text_lines(html)
    out = {"name": None, "area": None, "wins": None, "starts": None}
    for i, x in enumerate(t):
        if x == "所属" and i + 1 < len(t) and out["area"] is None:
            out["area"] = t[i + 1][:20]
        if x.startswith("（") and i > 0 and out["name"] is None:      # 氏名の次の行が（カナ）
            out["name"] = split_name(t[i - 1])
        if x == "生涯成績" and i + 8 < len(t) and t[i + 1] == "地方競馬":
            nums = t[i + 2:i + 9]
            if all(re.fullmatch(r"\d+", n) for n in nums):
                out["wins"], out["starts"] = int(nums[0]), int(nums[6])
    # 「2026年 地方競馬成績」などの表の「合計」行= その年の 1 着と合計(当年と前 2 年)
    out["years"] = {}
    for i, x in enumerate(t):
        m = re.fullmatch(r"(\d{4})年 ?地方競馬成績", x)
        if not m:
            continue
        for j in range(i + 1, min(i + 120, len(t) - 7)):
            if re.fullmatch(r"\d{4}年 ?地方競馬成績", t[j]):
                break
            if t[j] == "合計":
                nums = t[j + 1:j + 8]
                if all(re.fullmatch(r"\d+", n) for n in nums):
                    out["years"][m.group(1)] = [int(nums[0]), int(nums[6])]
                break
    return out


def fetch_mark(lic):
    r = urllib.request.Request(MARK + urllib.parse.quote(str(lic)), headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=40) as x:
        return parse_mark(x.read().decode("utf-8", errors="replace"))


def fetch_marks(lics, cache=None):
    """1 本ずつ。cache(dict・JSON ファイル)にあれば読まない。失敗は 1 回だけ引き直す。"""
    out = dict(cache or {})
    for n, lic in enumerate(lics):
        if lic in out and out[lic].get("wins") is not None:
            continue
        for i in range(2):
            try:
                out[lic] = fetch_mark(lic)
                break
            except Exception as e:                   # noqa: BLE001
                log("⚠個票 %s: %s" % (lic, e))
                out[lic] = {"wins": None}
                time.sleep(5)
        time.sleep(WAIT)
        if n % 50 == 49:
            log("個票 %d/%d" % (n + 1, len(lics)))
    return out


# ---------- 組み立て(純関数) ----------
def next_mark(wins):
    return (wins // STEP + 1) * STEP


def run_key(x):
    return (x["race_date"], int(x["race_no"]))


def counts_as_start(x):
    note = x.get("finish_note") or ""
    if any(w in note for w in EXCL):
        return False
    return x.get("finish") is not None or bool(note)


def kth_from_wins(wins, k):
    """wins= その騎手の 1 着(期間内)。新しい順の k 番目(1 始まり)。無ければ None。"""
    w = sorted(wins, key=run_key, reverse=True)
    return w[k - 1] if 1 <= k <= len(w) else None


def name_candidates(name, name_short):
    """公式の氏名「姓 名」から、走り(nar_runs.jockey)に出うる略称の候補。⛔決めるのは今年の勝ち数の一致(map_shorts)。
    例 山本聡紀→山本紀・藤田凌駕→藤田駕・本田正重→本田重・所 蛍→所　蛍・ゴンサルベス→ゴンサ"""
    out = []
    if name_short:
        out.append(name_short)
    parts = (name or "").split(" ", 1)
    sei, mei = (parts + [""])[:2]
    full = sei + mei
    if sei:
        s2 = sei[:2]
        out += [(s2 + mei[:max(0, 3 - len(s2))])[:3], s2 + mei[-1:], sei[:1] + mei[:2], full[:3], sei[:3]]
        if len(full) <= 3:
            out += [full, sei + "　" + mei]
        out.append(re.sub(r"^[Ａ-ＺA-Z][．.]\s*", "", full)[:3])     # 外国の騎手 Ｆ．ゴンサルベス→ゴンサ
    seen, res = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            res.append(c)
    return res


def map_shorts(people, marks, year_wins, year):
    """免許番号 → 走りの略称。⛔nar_persons の略称では決めない= 候補のうち「nar_runs で数えた今年の勝ち数」が
    「公式の今年の勝ち数(地方競馬成績の合計行)」と一致する 1 つ。⛔1 対 1 でなければ(候補が 2 つ・2 人が同じ略称)決めない。
    → (map, why) why= {lic: 'nomatch'|'zero'|'shared'|'many'}"""
    got, why = {}, {}
    for p in people:
        m = marks.get(p["lic"]) or {}
        yw = ((m.get("years") or {}).get(str(year)) or [None])[0]
        if yw is None or yw == 0:
            why[p["lic"]] = "zero"             # 今年 0 勝= 確かめられない(達成もありえない)
            continue
        hit = [c for c in name_candidates(m.get("name"), p.get("short")) if year_wins.get(c) == yw]
        if len(hit) == 1:
            got[p["lic"]] = hit[0]
        else:
            why[p["lic"]] = "many" if hit else "nomatch"
    cnt = {}
    for v in got.values():
        cnt[v] = cnt.get(v, 0) + 1
    for lic, v in list(got.items()):
        if cnt[v] > 1:
            del got[lic]
            why[lic] = "shared"
    return got, why


def build_doc(today, people, marks, rides, find_kth, starts_after, year_wins=None, made=None):
    """people= [{lic, short(名簿の略称), area}]・marks= {lic: parse_mark}・rides= {走りの略称: [{t,r,h,post}]}
    year_wins= {走りの略称: 今年(前日まで)の 1 着数}。照合できた騎手(ok)だけ 今日の騎乗と達成を出す。
    find_kth(short, k)→ {race_date,track,race_no,horse_name} か None・starts_after(short, run)→ その後の騎乗数"""
    since = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    mp, why = map_shorts(people, marks, year_wins or {}, today.year)
    js, recent, miss = [], [], []
    for p in people:
        m = marks.get(p["lic"]) or {}
        if m.get("wins") is None:
            miss.append(p["lic"])
            continue
        w = m["wins"]
        nx = next_mark(w)
        run_short = mp.get(p["lic"])
        ok = run_short is not None
        short = run_short or p["short"]
        yw = ((m.get("years") or {}).get(str(today.year)) or [None])[0]
        js.append({"lic": p["lic"], "name": m.get("name") or p["short"], "short": short,
                   "area": m.get("area") or p.get("area") or "", "wins": w, "starts": m.get("starts"),
                   "next": nx, "rem": nx - w, "dup": not ok, "why": why.get(p["lic"]),
                   "yw": [yw, (year_wins or {}).get(short)], "today": rides.get(short, []) if ok else []})
        if not ok or w < STEP:
            continue
        ms = w // STEP * STEP
        hit = find_kth(short, w - ms + 1)
        if not hit or hit["race_date"] < since:
            continue
        nth = None
        if m.get("starts") is not None:
            nth = m["starts"] - starts_after(short, hit)
        recent.append({"lic": p["lic"], "name": m.get("name") or short, "short": short,
                       "area": m.get("area") or "", "m": ms, "date": hit["race_date"], "t": hit["track"],
                       "r": int(hit["race_no"]), "h": hit.get("horse_name") or "", "nth": nth})
    js.sort(key=lambda x: (x["rem"], -x["wins"]))
    recent.sort(key=lambda x: (x["date"], x["r"]), reverse=True)
    doc = {"v": 2, "date": today.isoformat(), "asof": (today - dt.timedelta(days=1)).isoformat(),
           "made": made or dt.datetime.now(JST).isoformat(timespec="seconds"), "step": STEP,
           "recent_days": RECENT_DAYS, "jockeys": js, "recent": recent}
    return doc, miss


def active_recent(m, year):
    """公式の当年か前年に地方で騎乗がある(≒ 最近 1 年に乗った)。"""
    ys = m.get("years") or {}
    return any((ys.get(str(y)) or [0, 0])[1] > 0 for y in (year, year - 1))


def rides_from_rows(runs, races):
    post = {(x["track"], int(x["race_no"])): x.get("post_time") for x in races}
    out = {}
    for x in sorted(runs, key=lambda x: (x["track"], int(x["race_no"]))):
        if not x.get("jockey") or not counts_as_start({"finish": 1, "finish_note": x.get("finish_note")}):
            continue
        out.setdefault(x["jockey"], []).append({"t": x["track"], "r": int(x["race_no"]), "h": x.get("horse_name") or "",
                                                "post": post.get((x["track"], int(x["race_no"])))})
    return out


# ---------- 本番の読み(REST の単純 select だけ) ----------
def enc(v):
    return urllib.parse.quote(str(v), safe="")


def rest_people(rest):
    """現役の地方騎手(nar_persons・area が JRA でない)。最近 1 年の絞りは公式個票の当年・前年の騎乗で(active_recent)。"""
    rows = rest.get("nar_persons?select=license_no,name_short,area&kind=eq.jockey&active=is.true")
    out = [{"lic": r["license_no"], "short": r.get("name_short") or "", "area": r.get("area")}
           for r in rows if (r.get("area") or "") != "JRA"]
    return sorted(out, key=lambda x: x["lic"])


def rest_sources(rest, today):
    d60 = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    y0 = dt.date(today.year, 1, 1).isoformat()
    d0 = min(d60, y0)
    td = today.isoformat()
    wins = rest.paged("nar_runs?select=race_date,track,race_no,runner_number,horse_name,jockey&finish=eq.1"
                      "&race_date=gte.%s&race_date=lt.%s" % (d0, td), "race_date,track,race_no,runner_number")
    by, year_wins = {}, {}
    for w in wins:
        if w["race_date"] >= d60:
            by.setdefault(w["jockey"], []).append(w)
        if w["race_date"] >= y0 and w.get("jockey"):
            year_wins[w["jockey"]] = year_wins.get(w["jockey"], 0) + 1

    def find_kth(short, k):
        return kth_from_wins(by.get(short, []), k)

    def starts_after(short, hit):
        rows = rest.paged("nar_runs?select=race_date,track,race_no,runner_number,finish,finish_note&jockey=eq.%s"
                          "&race_date=gte.%s&race_date=lt.%s" % (enc(short), hit["race_date"], td),
                          "race_date,track,race_no,runner_number")
        return sum(1 for x in rows if run_key(x) > run_key(hit) and counts_as_start(x))

    runs = rest.paged("nar_runs?select=track,race_no,runner_number,horse_name,jockey,finish_note&race_date=eq.%s" % td,
                      "track,race_no,runner_number")
    races = rest.get("nar_races?select=track,race_no,post_time&race_date=eq.%s" % td)
    return find_kth, starts_after, rides_from_rows(runs, races), year_wins


def dumps(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="cond-stats/v1/milestones.json へ上げる")
    g.add_argument("--dry-run", action="store_true", help="上げずに --out へ書く")
    g.add_argument("--local", action="store_true", help="手元: DB を読まず --local-* の JSON から作る")
    ap.add_argument("--out", default="milestones_out")
    ap.add_argument("--today", default="", help="JST の当日(既定= 今日)")
    ap.add_argument("--marks-cache", default="", help="個票の控え JSON(あれば読み直さない・終わったら書く)")
    ap.add_argument("--marks-only", action="store_true", help="--local: 個票だけ取って控えに書く")
    ap.add_argument("--local-people", default="", help="--local: 'lic:略称[*]' のカンマ区切り(* は略称の重なり)")
    ap.add_argument("--local-ach", default="", help="--local: {略称: {race_date,track,race_no,horse_name,after}}")
    ap.add_argument("--local-rides", default="", help="--local: {略称: [{t,r,h,post}]}")
    ap.add_argument("--local-yearwins", default="", help="--local: {走りの略称: 今年(前日まで)の 1 着数}")
    ap.add_argument("--print-k", action="store_true", help="--local: 照合できた騎手の (略称, k) を出す")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    cache = {}
    if a.marks_cache and os.path.exists(a.marks_cache):
        cache = json.load(open(a.marks_cache, encoding="utf-8"))

    if a.local:
        people = []
        for tok in open(a.local_people, encoding="utf-8").read().replace("\n", ",").split(","):
            tok = tok.strip()
            if ":" in tok:
                lic, sh = tok.split(":", 1)
                people.append({"lic": lic, "short": sh.rstrip("*"), "area": None})
        marks = fetch_marks([p["lic"] for p in people], cache)
        if a.marks_cache:
            json.dump(marks, open(a.marks_cache, "w", encoding="utf-8"), ensure_ascii=False)
        people = [p for p in people if active_recent(marks.get(p["lic"]) or {}, today.year)]
        if a.marks_only:
            log("個票 %d 人(読めない %d)" % (len(marks), sum(1 for v in marks.values() if v.get("wins") is None)))
            return 0
        year_wins = json.load(open(a.local_yearwins, encoding="utf-8")) if a.local_yearwins else {}
        if a.print_k:                                # 手元: 達成を探す SQL に渡す (走りの略称, k)
            mp, why = map_shorts(people, marks, year_wins, today.year)
            ks = []
            for p in people:
                w = (marks.get(p["lic"]) or {}).get("wins")
                if p["lic"] in mp and w and w >= STEP:
                    ks.append("('%s',%d)" % (mp[p["lic"]], w - w // STEP * STEP + 1))
            print(",".join(ks))
            log("照合 OK %d・外れ %s" % (len(mp), {k: sum(1 for v in why.values() if v == k) for k in set(why.values())}))
            return 0
        ach = json.load(open(a.local_ach, encoding="utf-8")) if a.local_ach else {}
        rides = json.load(open(a.local_rides, encoding="utf-8")) if a.local_rides else {}
        doc, miss = build_doc(today, people, marks, rides, lambda s, k: ach.get(s),
                              lambda s, hit: (ach.get(s) or {}).get("after", 0), year_wins)
    else:
        from cond_stats import Rest, ensure_bucket, upload
        base = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not base or not key:
            raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        rest = Rest(base, key)
        people = rest_people(rest)
        marks = fetch_marks([p["lic"] for p in people], cache)
        people = [p for p in people if active_recent(marks.get(p["lic"]) or {}, today.year)]
        log("騎手 %d 人(当年か前年に騎乗)" % len(people))
        find_kth, starts_after, rides, year_wins = rest_sources(rest, today)
        doc, miss = build_doc(today, people, marks, rides, find_kth, starts_after, year_wins)
    log("載せた %d 人・読めない %d・あと10以内 %d・最近の達成 %d・照合できない %d(%s)" % (
        len(doc["jockeys"]), len(miss), sum(1 for j in doc["jockeys"] if j["rem"] <= 10), len(doc["recent"]),
        sum(1 for j in doc["jockeys"] if j["dup"]),
        ",".join("%s=%d" % (k, sum(1 for j in doc["jockeys"] if j["why"] == k)) for k in ("nomatch", "zero", "shared", "many"))))
    if len(miss) > max(10, len(people) // 5):
        log("⚠個票が読めない人が多すぎる= 上げない: %s" % miss[:20])
        return 1
    data = dumps(doc)
    if a.apply:
        ensure_bucket(rest)
        upload(rest, NAME, data)
        return 0
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, NAME), "wb") as f:
        f.write(data)
    log("書いた %s(%d bytes)" % (os.path.join(a.out, NAME), len(data)))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                            # noqa: BLE001
            pass
    sys.exit(main())

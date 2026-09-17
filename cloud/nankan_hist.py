# -*- coding: utf-8 -*-
"""本体 cloud: 南関 4 場の格付ポイントの履歴を「開催の最終日」単位で表 nar_nankan_point_hist に積む(DESIGN §196b 第 2 段)。

  python cloud/nankan_hist.py --env pipeline/.env.nar                    # ドライラン(直近 3 日に走った馬)
  python cloud/nankan_hist.py --apply --days 3                           # 日次(朝の便・nankan_points の直後)
  python cloud/nankan_hist.py --apply --all [--shard i/n]                # 初回の埋め(2024-01-01 以降に走った全頭・手押し)
  python cloud/nankan_hist.py --all --from-csv data/recon --out hist.csv # 手元の \\copy CSV から(DB に触らない)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

式(第 1 段 docs/s196b_recon.md・規則の原文 docs/s196b_rules.md):
  ・反映= 「開催最終日の全レース終了後」(L227)= 走った開催の最終日 < 基準日(asof)の走が、いまの値に入っている
  ・開催 m の直後の値= いまの値 − (反映済みで m より後の走の着内ポイント)+(未反映で m までの走)
    既にある official の行(主催者の値)があれば、m より後でいちばん近いその行から引く(逆算のずれはそこで止まる)
  ・着内ポイント= nar_races.nankan.pts(主催者の結果ページ)があればそれ・無ければ レース名 × 公式の表(同着は等分)
    遠征= 賞金 ÷ 1 万(原文に丸めの規則が無い= 足し引きは端数のまま・表の列が整数なので書くときだけ四捨五入)
  ・⛔決められない走(S 格で pts なし・着順の欠け・遠征先の地方交流重賞)より古い開催は points=null(推定で埋めない)
  ・kaku_ran= その開催で走ったレースの条件の格。単一クラス→ race / 混合・選抜・選定・オープン・重賞・格なし→ 前の開催から carry
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

NK = {"大井": "20", "船橋": "19", "川崎": "21", "浦和": "18"}
START = "2024-01-01"                     # 格付ポイント制の開始(原文 L218)
GAP_IN_MEETING = 4                       # 同じ開催と見なす開催日の間(日)。第 1 段で raceid と突き合わせて決めた
TABLE = "nar_nankan_point_hist"
CLASSES = ["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3"]
Z2H = str.maketrans("ＡＢＣＳＩ１２３４５６７８９０", "ABCSI1234567890")

# ---- 公式の着内ポイント表(原文 L235〜L486・着順 1〜5)
T_SPECIAL = {"A1": (600, 240, 150, 90, 60), "A2": (500, 200, 125, 75, 50), "B1": (320, 128, 80, 48, 32),
             "B2": (280, 112, 70, 42, 28), "B3": (240, 96, 60, 36, 24), "C1": (200, 80, 50, 30, 20),
             "C2": (180, 72, 45, 27, 18), "C3": (140, 56, 35, 21, 14), "3歳": (280, 112, 70, 42, 28),
             "2歳": (320, 128, 80, 48, 32)}
T_NORMAL = {"A2": (320, 128, 80, 48, 32), "B1": (280, 112, 70, 42, 28), "B2": (240, 96, 60, 36, 24),
            "B3": (200, 80, 50, 30, 20), "C1": (150, 60, 38, 23, 15), "C2": (100, 40, 25, 15, 10),
            "C3": (80, 32, 20, 12, 8), "3歳前": (220, 88, 55, 33, 22), "3歳後": (160, 64, 40, 24, 16),
            "2歳": (250, 100, 63, 38, 25), "新馬": (280, 112, 70, 42, 28)}
T_JUN = {"格付": (700, 252, 154, 91, 63), "若": (600, 216, 132, 78, 54)}
T_JPN = {("2歳", "1"): (2000, 700, 400, 200, 100), ("2歳", "2"): (1500, 525, 300, 150, 75), ("2歳", "3"): (1200, 420, 240, 120, 60),
         ("3歳", "1"): (2400, 840, 480, 240, 120), ("3歳", "2"): (1800, 630, 360, 180, 90), ("3歳", "3"): (1400, 490, 280, 140, 70),
         ("古馬", "1"): (5000, 1750, 1000, 500, 250), ("古馬", "2"): (3100, 1085, 620, 310, 155), ("古馬", "3"): (2600, 910, 520, 260, 130)}


def log(msg):
    print(dt.datetime.now().strftime("%H:%M:%S"), msg, flush=True)


def half(d):
    return "上" if int(d[5:7]) <= 6 else "下"


def race_classes(name):
    s = str(name or "").translate(Z2H)
    return sorted(set(re.findall(r"([ABC][123])", s)), key=CLASSES.index)


def ages_of(name, cond):
    s = (str(name or "") + " " + str(cond or "")).translate(Z2H)
    if re.search(r"2歳", s):
        return "2歳"
    if re.search(r"3歳(?!以上|上)", s) and not re.search(r"3上|3歳以上|一般", s):
        return "3歳"
    return "古馬"


def earned_table(race, mixed="upper"):
    """レース名 × 公式の表 → (5 着ぶんの点, src)。決まらなければ (None, 理由)。第 1 段で公式ページと 889/893 走一致"""
    kind, name, cond = race.get("race_kind") or "", race.get("race_name") or "", race.get("condition") or ""
    cls, ag = race_classes(name), ages_of(name, cond)
    if kind == "重賞":
        m = re.search(r"Jpn\s*([ⅠⅡⅢ]|I{1,3}|Ｉ{1,3})", name)
        if not m:
            return None, "S格の重賞(pts なし)"
        g = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3"}.get(m.group(1), str(len(m.group(1))))
        return T_JPN[(ag, g)], "ok"
    if kind == "準重賞":
        return (T_JUN["若"] if ag in ("2歳", "3歳") else T_JUN["格付"]), "ok"
    if kind not in ("普通", "特別"):
        return None, "競走種類が無い"
    tab = T_SPECIAL if kind == "特別" else T_NORMAL
    if not cls:
        if "新馬" in name and ag == "2歳":           # 「３歳新馬」は 3 歳の表(公式ページで確認)
            return (T_NORMAL["新馬"], "ok") if kind == "普通" else (None, "新馬の特別")
        if ag == "2歳":
            return tab["2歳"], "ok"
        if ag == "3歳":
            return (tab["3歳"] if kind == "特別" else tab["3歳前" if half(race["race_date"]) == "上" else "3歳後"]), "ok"
        if "オープン" in name and kind == "特別":    # 「◯◯オープン」の特別は A1 の表(公式ページで確認)
            return tab["A1"], "open=A1"
        return None, "格が名前に無い"
    k = cls[0] if (len(cls) == 1 or mixed == "upper") else cls[-1]   # 混合は上のクラスの表(公式ページで不一致 0)
    return (tab[k], "ok" if len(cls) == 1 else "mixed") if k in tab else (None, "表に無い格(%s)" % k)


def meetings(dates_by_track):
    """{track: {date}} → {(track, date): (最終日, 初日, 年度内の回, 日)}。休みの日を挟む開催(間 4 日以内)・回は 4 月始まり"""
    idx = {}
    for tr, ds in dates_by_track.items():
        ds = sorted(ds)
        if not ds:
            continue
        blocks, cur = [], [ds[0]]
        for d in ds[1:]:
            a, b = dt.date.fromisoformat(cur[-1]), dt.date.fromisoformat(d)
            if (b - a).days <= GAP_IN_MEETING and not (b.month == 4 and a.month == 3):
                cur.append(d)
            else:
                blocks.append(cur)
                cur = [d]
        blocks.append(cur)
        kai = collections.Counter()
        for bl in blocks:
            s = dt.date.fromisoformat(bl[0])
            fy = s.year if s.month >= 4 else s.year - 1
            kai[fy] += 1
            for j, d in enumerate(bl):
                idx[(tr, d)] = (bl[-1], bl[0], kai[fy], j + 1)
    return idx


def kaku_of_race(name, kind):
    """条件の格(単一クラスで、選抜・選定・オープン・重賞でない)→ 'C3' など / それ以外は None(= carry)"""
    cls = race_classes(name)
    if len(cls) != 1 or kind in ("重賞", "準重賞") or re.search(r"選抜|選定|オープン", str(name or "")):
        return None
    return cls[0]


def run_points(r, race, tie, mixed="upper"):
    """1 走の着内ポイント → (点 or None, src)。nankan.pts(公式)があれば優先"""
    fin, note = r.get("fin"), r.get("note") or ""
    if fin is None:
        if re.search("取消|除外", note):
            return 0, "取消除外"
        if "中止" in note:
            return 0, "中止=0"
        if re.search("失格|降着", note):
            return 0, "失格=0"                          # 原文 ④ L234= 失格は着内ポイントなし
        if not note and str((race or {}).get("cancelled") or "").strip() not in ("", "null", "[]", "{}"):
            return 0, "取り止め"                        # §196b 工事 B= 取り止めになったレース(走っていない)
        return None, "着順なし"
    if fin > 5:
        return 0, "ok"
    nk = (race or {}).get("nankan") or {}
    tab, src = (tuple(nk["pts"]), "公式") if isinstance(nk.get("pts"), list) and len(nk["pts"]) == 5 else \
        (earned_table(race, mixed) if race else (None, "レースが表に無い"))
    if tab is None:
        return None, src
    tie = max(1, tie or 1)
    return sum(tab[fin - 1:min(5, fin - 1 + tie)]) / tie, src + ("+同着" if tie > 1 else "")


def hist_rows(code, now_pts, asof, items, anchors=None, since=START):
    """1 頭ぶんの開催ごとの行。items= [{d, mend, remote, pts, kaku, no}](pts None= 決められない)。
    anchors= {meet_end: points} 既にある official の行(書き直さない・起点に使う)"""
    anchors = dict(anchors or {})
    items = [x for x in items if x["d"] >= since]
    nk = sorted([x for x in items if not x["remote"]], key=lambda x: (x["d"], x["no"] or 0))
    meets = sorted({x["mend"] for x in nk})
    refl = [x for x in items if x["mend"] < asof]
    unrefl = [x for x in items if x["mend"] >= asof]
    last_refl = max([x["mend"] for x in refl] or [""])

    def total(xs):
        return None if any(x["pts"] is None for x in xs) else sum(x["pts"] for x in xs)

    rows, carry = [], None
    for m in meets:
        in_m = [x for x in nk if x["mend"] == m]
        k = next((x["kaku"] for x in reversed(in_m) if x["kaku"]), None)
        kaku, ksrc = (k, "race") if k else ((carry, "carry") if carry else (None, None))
        carry = kaku or carry
        row = {"code": code, "meet_end": m, "kaku_ran": kaku, "kaku_src": ksrc, "last_run": in_m[-1]["d"]}
        later = sorted(a for a in anchors if a >= m)
        if m in anchors:
            continue                                   # 主催者の値の行は書き直さない
        if now_pts is None:
            pts, src = None, "recon"
        elif m >= asof:                                # まだ反映されていない開催= いまの値に足す
            s = total([x for x in unrefl if x["mend"] <= m])
            pts, src = (None if s is None else now_pts + s), "recon"
        elif later:                                    # いちばん近い後ろの official の行から引く
            a = later[0]
            s = total([x for x in items if m < x["mend"] <= a])
            pts, src = (None if s is None or anchors[a] is None else anchors[a] - s), "recon"
        else:
            after = [x for x in refl if x["mend"] > m]
            s = total(after)
            pts = None if s is None else now_pts - s
            src = "official" if (m == last_refl and not after) else "recon"
        row.update(points=None if pts is None else int(round(pts)), src=src)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 材料(REST か 手元の CSV)

def sb_all(url, key, path, page=1000):
    out, lo = [], 0
    while True:
        req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json", "Range": f"{lo}-{lo + page - 1}"})
        with urllib.request.urlopen(req, timeout=90) as r:
            rows = json.loads(r.read().decode("utf-8"))
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def q(v):
    return urllib.parse.quote(",".join('"%s"' % str(x).replace('"', '') for x in v))


def load_rest(url, key, args, today):
    tracks = q(NK)
    lo = START
    races = []
    y, mth = 2024, 1
    while (y, mth) <= (today.year, today.month):   # ⛔深い offset を避けて月ごとに(order は主キーで一意)
        a = f"{y}-{mth:02d}-01"
        y2, m2 = (y + 1, 1) if mth == 12 else (y, mth + 1)
        races += sb_all(url, key, f"nar_races?select=track,race_date,race_no,race_name,race_kind,condition,nankan,cancelled"
                                  f"&track=in.({tracks})&race_date=gte.{a}&race_date=lt.{y2}-{m2:02d}-01&order=track,race_date,race_no")
        y, mth = y2, m2
    if args.all:
        pts = sb_all(url, key, "nar_nankan_points?select=code,horse_name,points,asof,birth_date&order=code")
        names = None
    else:
        since = (today - dt.timedelta(days=args.days)).isoformat()
        recent = sb_all(url, key, f"nar_runs?select=horse_name&track=in.({tracks})&race_date=gte.{since}"
                                  "&order=race_date,track,race_no,runner_number")
        names = sorted({r["horse_name"] for r in recent})
        pts = []
        for i in range(0, len(names), 40):
            pts += sb_all(url, key, f"nar_nankan_points?select=code,horse_name,points,asof,birth_date&horse_name=in.({q(names[i:i + 40])})&order=code")
    want = sorted({p["horse_name"] for p in pts})
    runs, prize, anchors = [], [], []
    for i in range(0, len(want), 40):
        ch = q(want[i:i + 40])
        runs += sb_all(url, key, f"nar_runs?select=track,race_date,race_no,runner_number,horse_name,finish,finish_note,birth_date"
                                 f"&track=in.({tracks})&race_date=gte.{lo}&horse_name=in.({ch})&order=race_date,track,race_no,runner_number")
        prize += sb_all(url, key, f"nar_horse_prize?select=code,horse_name,runs&horse_name=in.({ch})&order=code")
    codes = sorted({p["code"] for p in pts})
    for i in range(0, len(codes), 80):
        anchors += sb_all(url, key, f"{TABLE}?select=code,meet_end,points&src=eq.official&code=in.({q(codes[i:i + 80])})&order=code,meet_end")
    # 同着= 同じレース・同じ着順の頭数(対象の馬が 5 着以内の レースだけ引く)
    need = sorted({(r["track"], r["race_date"], r["race_no"]) for r in runs if r["finish"] is not None and int(r["finish"]) <= 5})
    tie = collections.Counter()
    by_day = collections.defaultdict(set)
    for tr, d, _ in need:
        by_day[tr].add(d)
    for tr, ds in by_day.items():
        ds = sorted(ds)
        for i in range(0, len(ds), 60):
            for r in sb_all(url, key, f"nar_runs?select=race_date,race_no,finish,runner_number&track=eq.{urllib.parse.quote(tr)}"
                                      f"&race_date=in.({','.join(ds[i:i + 60])})&finish=lte.5&order=race_date,race_no,runner_number"):
                tie[(tr, r["race_date"], int(r["race_no"]), int(r["finish"]))] += 1
    return pts, runs, races, prize, anchors, tie


def load_csv(d):
    def rd(n):
        with open(Path(d) / n, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    csv.field_size_limit(10 ** 9)
    pts = rd("points.csv")
    runs = [r for r in rd("runs.csv") if r["race_date"] >= START]
    races = rd("races.csv")
    for r in races:
        r["nankan"] = json.loads(r["nankan"]) if r.get("nankan") else None
    prize = rd("prize.csv")
    tie = collections.Counter((r["track"], r["race_date"], int(r["race_no"]), int(r["finish"])) for r in runs if r["finish"])
    for p in pts:
        p["points"] = int(p["points"]) if p["points"] not in ("", None) else None
    return pts, runs, races, prize, [], tie


def num(v):
    return int(v) if v not in (None, "") else None


def build(pts, runs, races, prize, anchors, tie, args, today):
    rmap = {(r["track"], r["race_date"], int(r["race_no"])): r for r in races}
    dates = collections.defaultdict(set)
    for (tr, d, _) in rmap:
        dates[tr].add(d)
    idx = meetings(dates)
    runs_by = collections.defaultdict(list)
    for r in runs:
        runs_by[r["horse_name"]].append(r)
    prize_by = collections.defaultdict(list)
    for p in prize:
        prize_by[p["horse_name"]].append(p)
    anc = collections.defaultdict(dict)
    for a in anchors:
        anc[a["code"]][a["meet_end"]] = a["points"]
    names = collections.Counter(p["horse_name"] for p in pts)
    shard_i, shard_n = (int(x) for x in args.shard.split("/")) if args.shard else (0, 1)
    out, why = [], collections.Counter()
    for p in pts:
        if args.shard and int(p["code"]) % shard_n != shard_i:
            continue
        if p["points"] in (None, "") or not p.get("asof"):
            continue                                   # 抹消など(いまの値が無い)はやらない
        items = []
        for r in runs_by.get(p["horse_name"], []):
            if p.get("birth_date") and r.get("birth_date") and r["birth_date"] != p["birth_date"]:
                continue
            fin, note = num(r["finish"]), r.get("finish_note") or ""
            if fin is None and not note and r["race_date"] >= today.isoformat():
                continue                               # まだ走っていない(出馬表だけ)
            key = (r["track"], r["race_date"], int(r["race_no"]))
            race = dict(rmap.get(key) or {}, race_date=r["race_date"]) if key in rmap else None
            pt, src = run_points({"fin": fin, "note": note}, race, tie[key + (fin,)] if fin else 1, args.mixed)
            if pt is None:
                why[src] += 1
            v = idx.get((r["track"], r["race_date"]))
            items.append({"d": r["race_date"], "mend": v[0] if v else r["race_date"], "remote": False, "pts": pt,
                          "no": int(r["race_no"]), "kaku": kaku_of_race((race or {}).get("race_name"), (race or {}).get("race_kind"))})
        if not items:
            continue
        first = min(x["d"] for x in items)
        cands = prize_by.get(p["horse_name"], [])
        if len(cands) == 1 and names[p["horse_name"]] == 1:
            rr = cands[0]["runs"]
            for r in (json.loads(rr) if isinstance(rr, str) else rr) or []:
                d = r.get("d") or ""
                if d < first or d < START or (r.get("tr") in NK and not r.get("jra")):
                    continue                           # 転入前の走・南関の走は数えない
                fin = r.get("fin")
                if isinstance(fin, int) and fin <= 5:
                    if re.search(r"Jpn|ＪＰＮ", r.get("name") or "") and not r.get("jra"):
                        pt = None
                        why["遠征先の地方交流重賞"] += 1
                    else:
                        pt = (r.get("prize") or 0) / 10000
                else:
                    pt = 0
                items.append({"d": d, "mend": d, "remote": True, "pts": pt, "no": r.get("no"), "kaku": None})
        out += hist_rows(p["code"], p["points"], p["asof"], items, anc.get(p["code"]))
    return out, why


def upsert(url, key, rows):
    from load_nar_official import upsert as up
    for i in range(0, len(rows), 500):
        st, msg = up(url, key, TABLE, "code,meet_end", rows[i:i + 500])
        if st >= 300 or st == 0:
            log(f"投入失敗 {TABLE} status={st} {msg}")
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true", help="表へ書く(無ければドライラン)")
    ap.add_argument("--days", type=int, default=3, help="直近この日数に南関で走った馬")
    ap.add_argument("--all", action="store_true", help="2024-01-01 以降に走った全頭(初回の埋め)")
    ap.add_argument("--shard", help="'i/n'= 馬コード %% n == i の馬だけ")
    ap.add_argument("--from-csv", help="REST の代わりに tools/nankan_recon_dump.sh の CSV を読む(DB に触らない)")
    ap.add_argument("--out", help="行を CSV にも書く(検算用)")
    ap.add_argument("--mixed", default="upper", choices=["upper", "lower"])
    ap.add_argument("--today", help="YYYY-MM-DD(--from-csv の CSV を取った日に合わせる= その日以降の着順の無い走は まだ走っていない)")
    args = ap.parse_args()
    if args.env:
        from load_nar_official import load_env
        load_env(args.env)
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    today = dt.date.fromisoformat(args.today) if args.today else (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()
    try:
        if args.from_csv:
            data = load_csv(args.from_csv)
        else:
            if not url or not key:
                log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
                return 2
            data = load_rest(url, key, args, today)
    except Exception as e:
        log(f"材料の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2
    pts, runs, races, prize, anchors, tie = data
    log(f"馬 {len(pts)} / 走 {len(runs)} / レース {len(races)} / official の行 {len(anchors)}")
    rows, why = build(*data, args, today)
    nn = sum(1 for r in rows if r["points"] is None)
    log(f"行 {len(rows)}(馬 {len({r['code'] for r in rows})}・points null {nn}・official {sum(r['src'] == 'official' for r in rows)}"
        f"・負 {sum(1 for r in rows if (r['points'] or 0) < 0)})・決められない走 {dict(why)}")
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["code", "meet_end", "points", "src", "kaku_ran", "kaku_src", "last_run"])
            w.writeheader()
            w.writerows(rows)
    if not args.apply:
        log("dry-run: 書かない")
        return 0
    if args.from_csv:
        log("⛔--from-csv の行を表へ書くときは --apply に加えて環境変数が要る")
        if not url or not key:
            return 2
    ok = upsert(url, key, [dict(r, updated_at=dt.datetime.now(dt.timezone.utc).isoformat()) for r in rows])
    log(f"投入 {len(rows)} 行 -> {TABLE}" if ok else "投入失敗")
    return 0 if ok else 1


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)

# -*- coding: utf-8 -*-
"""§196b 南関 格付ポイントの過去復元(下調べ・手元だけ・⛔DB に書かない)。

入力= tools/nankan_recon_dump.sh が本番から 1 回だけ \\copy した data/recon/{points,runs,races,prize}.csv。

  py -3.12 -X utf8 tools/nankan_recon.py all                 # 全頭を逆算 → data/recon/recon_all.csv と集計
  py -3.12 -X utf8 tools/nankan_recon.py sample --n 50       # 50 頭を nankankeiba の結果ページと突き合わせ
                                                              #   → data/recon/sample_*.csv と docs 用の集計

逆算の式(設計書 opus_s196b):
  ある日 D の直前のポイント= いまの値(基準日 asof)− [D, asof) に稼いだ着内ポイントの合計
  (asof は「最後に走った日の翌日」= asof より前の走はいまの値に入っている)。asof 以降の走は足す。
着内ポイント= 公式の格付ポイント表(docs/s196b_rules.md)× 競走種類 × レースの格 × 着順 1〜5(同着は等分)。
  遠征(南関 4 場以外・JRA)= 賞金 ÷ 1 万(原文 「獲得賞金額を１万で除したもの」)。
  ⛔推定で埋めない= 表のどの行か決まらない走(格が名前に無い重賞・混合クラス等)は src に理由を書き、
  その走をまたぐ日は「復元不可」に数える(sample では公式ページの値で答え合わせする)。
格の規則は原文に無い部分があるので、4 通り(R1/R2 × A/B)を並べて一致率で比べる(⛔合わせに行かない):
  R1= 直前の全走のポイント / R2= 前々開催(南関 4 場の開催日割)の終わりまでのポイント
  A = 基準で上下とも毎回決める / B = 下がるのは半期の切替(1/1・7/1)だけ
"""
import argparse
import collections
import csv
import datetime as dt
import json
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "recon"
sys.path.insert(0, str(HERE))
csv.field_size_limit(10 ** 9)

NK = {"大井": "20", "船橋": "19", "川崎": "21", "浦和": "18"}
START = "2024-01-01"                      # 格付ポイント制の開始(原文 「令和６年１月１日より」)
DUMP_DAY = "2026-09-17"                   # \copy した日= この日以降で着順の無い走は「まだ走っていない」
GAP_IN_MEETING = 4                        # 同じ開催と見なす開催日の間(日)。馬ページの raceid と突き合わせて決めた
CLASSES = ["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3"]
Z2H = str.maketrans("ＡＢＣ１２３４５６７８９０", "ABC1234567890")

# ---- 公式の表(docs/s196b_rules.md に原文を写した。着順 1〜5)
T_SPECIAL = {"A1": (600, 240, 150, 90, 60), "A2": (500, 200, 125, 75, 50), "B1": (320, 128, 80, 48, 32),
             "B2": (280, 112, 70, 42, 28), "B3": (240, 96, 60, 36, 24), "C1": (200, 80, 50, 30, 20),
             "C2": (180, 72, 45, 27, 18), "C3": (140, 56, 35, 21, 14), "3歳": (280, 112, 70, 42, 28),
             "2歳": (320, 128, 80, 48, 32)}
T_NORMAL = {"A2": (320, 128, 80, 48, 32), "B1": (280, 112, 70, 42, 28), "B2": (240, 96, 60, 36, 24),
            "B3": (200, 80, 50, 30, 20), "C1": (150, 60, 38, 23, 15), "C2": (100, 40, 25, 15, 10),
            "C3": (80, 32, 20, 12, 8), "3歳前": (220, 88, 55, 33, 22), "3歳後": (160, 64, 40, 24, 16),
            "2歳": (250, 100, 63, 38, 25), "新馬": (280, 112, 70, 42, 28)}
T_JUN = {"格付": (700, 252, 154, 91, 63), "若": (600, 216, 132, 78, 54)}
T_JPN = {  # 重賞は名前に Jpn の格があるものだけ(S の格は名前に無い= 決めない)
    ("2歳", "1"): (2000, 700, 400, 200, 100), ("2歳", "2"): (1500, 525, 300, 150, 75), ("2歳", "3"): (1200, 420, 240, 120, 60),
    ("3歳", "1"): (2400, 840, 480, 240, 120), ("3歳", "2"): (1800, 630, 360, 180, 90), ("3歳", "3"): (1400, 490, 280, 140, 70),
    ("古馬", "1"): (5000, 1750, 1000, 500, 250), ("古馬", "2"): (3100, 1085, 620, 310, 155), ("古馬", "3"): (2600, 910, 520, 260, 130)}
# 格付基準(半期 × 馬齢 3〜8+)。None= 表が「－」
TH = {
    "上": {"A1": (2800, 3400, 4300, 5000, 5500, 5900), "A2": (2000, 2200, 2500, 3200, 3700, 4100),
          "B1": (1500, 1700, 1900, 2200, 2700, 3000), "B2": (1100, 1200, 1400, 1700, 2000, 2200),
          "B3": (700, 800, 1000, 1300, 1600, 1800), "C1": (None, 500, 700, 1000, 1300, 1500),
          "C2": (None, 200, 400, 700, 1000, 1200)},
    "下": {"A1": (3000, 3600, 4400, 5200, 5700, 5900), "A2": (2200, 2300, 2600, 3400, 3900, 4100),
          "B1": (1700, 1800, 2000, 2500, 2900, 3000), "B2": (1200, 1300, 1500, 1800, 2100, 2200),
          "B3": (800, 900, 1100, 1400, 1700, 1800), "C1": (500, 600, 800, 1100, 1400, 1500),
          "C2": (200, 300, 500, 800, 1100, 1200)},
}


def half(d):
    return "上" if int(d[5:7]) <= 6 else "下"


def grade(pts, age, d):
    """その日の基準で決まる格(⛔3 歳の格付時期・C3 の下限は見ない= 格付馬として比べる)。"""
    if pts is None or age is None or age < 3:
        return None
    col = min(age, 8) - 3
    for k in CLASSES[:-1]:
        thr = TH[half(d)][k][col]
        if thr is not None and pts >= thr:
            return k
    return "C3"


def race_classes(name):
    """レース名 → そこに書かれた格の集合(Ａ２Ｂ１→{A2,B1}・Ｃ３→{C3})。"""
    s = str(name or "").translate(Z2H)
    return sorted(set(re.findall(r"([ABC][123])", s)), key=CLASSES.index)


def ages_of(name, cond):
    s = str(name or "") + " " + str(cond or "")
    s = s.translate(Z2H)
    if re.search(r"2歳|２歳", s):
        return "2歳"
    if re.search(r"3歳(?!以上|上)|３歳(?!以上|上)", s) and not re.search(r"3上|3歳以上|一般", s):
        return "3歳"
    return "古馬"


def earned_table(race, mixed="upper"):
    """→ (5 着ぶんの点, src)。src= 'ok' / 'mixed' / 理由(⛔決まらないときは点 None)。"""
    kind = race.get("race_kind") or ""
    name = race.get("race_name") or ""
    cond = race.get("condition") or ""
    cls = race_classes(name)
    ag = ages_of(name, cond)
    if kind == "重賞":
        m = re.search(r"Jpn\s*([ⅠⅡⅢ]|I{1,3}|Ｉ{1,3})", name)
        if not m:
            return None, "重賞の格が名前に無い"
        g = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3"}.get(m.group(1), str(len(m.group(1))))
        return T_JPN[(ag, g)], "ok"
    if kind == "準重賞":
        return (T_JUN["若"] if ag in ("2歳", "3歳") else T_JUN["格付"]), "ok"
    if kind not in ("普通", "特別"):
        return None, "競走種類が無い"
    tab = T_SPECIAL if kind == "特別" else T_NORMAL
    if not cls:
        # 検算 50 頭(公式ページの番組ポイント)で確かめた= 「３歳新馬」は 3 歳の表・新馬の表は 2 歳だけ
        if "新馬" in name and ag == "2歳":
            return (T_NORMAL["新馬"] if kind == "普通" else None), ("ok" if kind == "普通" else "新馬の特別")
        if ag == "2歳":
            return tab["2歳"], "ok"
        if ag == "3歳":
            if kind == "特別":
                return tab["3歳"], "ok"
            return tab["3歳前" if half(race["race_date"]) == "上" else "3歳後"], "ok"
        # 同= 「◯◯オープン」の特別は A1 の表(公式 2 着 240P・4 着 90P)
        if "オープン" in name and kind == "特別":
            return tab["A1"], "open=A1"
        return None, "格が名前に無い"
    if len(cls) > 1:
        k = cls[0] if mixed == "upper" else cls[-1]
        v = tab.get(k)
        return (v, "mixed") if v else (None, "混合の表が無い")
    v = tab.get(cls[0])
    return (v, "ok") if v else (None, "表に無い格(%s)" % cls[0])


def ymd(s):
    return dt.date.fromisoformat(s)


def load():
    def rd(n):
        with open(DATA / n, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    pts = rd("points.csv")
    runs = rd("runs.csv")
    races = {(r["track"], r["race_date"], int(r["race_no"])): r for r in rd("races.csv")}
    prize = collections.defaultdict(list)
    for p in rd("prize.csv"):
        prize[p["horse_name"]].append(p)
    return pts, runs, races, prize


def meetings(races):
    """南関 4 場の開催(同じ場の連続した開催日)→ [(start, end, track)] 日付順・{(track, date): (idx, kai, nichi)}"""
    by = collections.defaultdict(set)
    for (tr, d, _), r in races.items():
        if r.get("cancelled") not in ("", None) and False:
            continue
        by[tr].add(d)
    out, idx = [], {}
    for tr, ds in by.items():
        ds = sorted(ds)
        blocks, cur = [], [ds[0]]
        for d in ds[1:]:
            # 開催の途中に休みの日を挟む(実測 川崎 2025-08-21,22,25,26 が 1 開催= 26 日が 4 日目)。次の開催は 1 週間以上あく
            fy_break = ymd(d).month == 4 and ymd(cur[-1]).month == 3    # 回は 4 月始まりの年度で数え直す
            if (ymd(d) - ymd(cur[-1])).days <= GAP_IN_MEETING and not fy_break:
                cur.append(d)
            else:
                blocks.append(cur)
                cur = [d]
        blocks.append(cur)
        kai_by_fy = collections.Counter()
        for b in blocks:
            s = ymd(b[0])
            fy = s.year if s.month >= 4 else s.year - 1
            kai_by_fy[fy] += 1
            for j, d in enumerate(b):
                idx[(tr, d)] = [None, kai_by_fy[fy], j + 1, b[0], b[-1]]
            out.append((b[0], b[-1], tr))
    out.sort()
    pos = {(tr, s): i for i, (s, e, tr) in enumerate(out)}
    for (tr, d), v in idx.items():
        v[0] = pos[(tr, v[3])]
    return out, idx


def raceid(track, d, rno, idx):
    v = idx.get((track, d))
    if not v:
        return None
    return "%s%s%02d%02d%02d" % (d.replace("-", ""), NK[track], v[1], v[2], int(rno))


def horse_runs(p, runs_by, races, prize_by, mixed, official=None):
    """1 頭ぶんの走(南関+遠征)を日付順に。各走= dict(d, track, no, fin, note, pts(着内), src)"""
    name, birth = p["horse_name"], p["birth_date"]
    rs = []
    for r in runs_by.get(name, []):
        if birth and r["birth_date"] and r["birth_date"] != birth:
            continue
        rs.append(r)
    out = []
    # 同着= 同じレースで同じ着順の頭数(DB の着順から数える)
    for r in rs:
        key = (r["track"], r["race_date"], int(r["race_no"]))
        race = races.get(key, {})
        fin = int(r["finish"]) if (r["finish"] or "").isdigit() else None
        note = r["finish_note"] or ""
        item = {"d": r["race_date"], "track": r["track"], "no": int(r["race_no"]), "fin": fin, "note": note,
                "name": race.get("race_name", ""), "kind": race.get("race_kind", ""), "remote": False}
        if fin is None and not note and r["race_date"] >= DUMP_DAY:
            continue                         # まだ走っていない(出馬表だけ)
        if fin is None and not note and official and key in official:
            fin = 99                         # DB に着順が無いが公式の結果ページはある= 6 着以下として 0(公式の点で確かめる)
        if fin is None or fin > 5:
            if fin:
                src = "ok"
            elif re.search("取消|除外", note):
                src = "取消除外"
            elif "中止" in note:
                src = "中止=0"               # 原文「１着から５着までの着内ポイントの合計」= 着内でない
            else:
                src = "結果の欠け" + (":" + note if note else "")
            item["pts"] = None if src.startswith("結果の欠け") else 0
            item["src"] = src
        else:
            tab, src = earned_table(dict(race, race_date=r["race_date"]), mixed) if race else (None, "レースが表に無い")
            if official and key in official:
                tab, src = official[key], "公式"
            if tab is None:
                item["pts"], item["src"] = None, src
            else:
                tie = r.get("_tie", 1)
                item["pts"] = sum(tab[fin - 1:fin - 1 + tie]) / tie if fin - 1 + tie <= 5 else sum(tab[fin - 1:5]) / tie
                item["src"] = src if tie == 1 else src + "+同着"
        out.append(item)
    nk_dates = {x["d"] for x in out}
    first_nk = min(nk_dates) if nk_dates else None
    cands = prize_by.get(name, [])
    if len(cands) == 1:
        for r in json.loads(cands[0]["runs"] or "[]"):
            d = r.get("d") or ""
            if not first_nk or d < first_nk or r.get("tr") in NK and not r.get("jra"):
                continue                     # 転入前の走・南関の走(DB 側で数える)は除く
            fin = r.get("fin")
            pr = r.get("prize")
            it = {"d": d, "track": r.get("tr"), "no": r.get("no"), "fin": fin, "note": r.get("note") or "",
                  "name": r.get("name") or "", "kind": "遠征", "remote": True}
            if isinstance(fin, int) and fin <= 5:
                if re.search(r"Jpn|ＪＰＮ|ｊｐｎ", it["name"]) and not r.get("jra"):
                    it["pts"], it["src"] = None, "遠征の地方交流重賞(表で数える)"
                elif pr is None:
                    it["pts"], it["src"] = None, "遠征の賞金が無い"
                else:
                    it["pts"], it["src"] = pr / 10000, "遠征"
            else:
                it["pts"], it["src"] = 0, "遠征"
            out.append(it)
    elif len(cands) > 1:
        for it in out:
            it.setdefault("flag", "同名馬で遠征を見られない")
    out.sort(key=lambda x: (x["d"], x["remote"]))
    return out


def reconstruct(p, hr, idx=None):
    """各走の直前/直後のポイント。いまの値から逆に引く(⛔足りない走は None を伝える)。
    いまの値に入っている走= 原文 L227「反映は、開催最終日の全レース終了後」= その走の開催の最終日 < asof。
    (⚠最初は「走った日 < asof」で数え、新馬の初走が ちょうど 1 走ぶんマイナスになる馬が多かった)"""
    if p["points"] in ("", None) or not p["asof"]:
        return None
    now, asof = int(p["points"]), p["asof"]

    def reflected(x):
        if x["remote"] or idx is None:
            return x["d"] < asof
        v = idx.get((x["track"], x["d"]))
        return (v[4] if v else x["d"]) < asof
    before = [x for x in hr if reflected(x)]
    after = [x for x in hr if not reflected(x)]
    cur, known = float(now), True
    for x in reversed(before):
        x["after"] = cur if known else None
        if x["pts"] is None:
            known = False
        if known:
            cur -= x["pts"]
        x["before"] = cur if known else None
    cur, known = float(now), True
    for x in after:
        x["before"] = cur if known else None
        if x["pts"] is None:
            known = False
        if known:
            cur += x["pts"]
        x["after"] = cur if known else None
    return hr


def age_at(birth, d):
    return int(d[:4]) - int(birth[:4]) if birth else None


def kaku_rules(p, hr, idx, mtg):
    """4 通りの規則で各南関走の格(kaku_R1A 等)を付ける。"""
    birth = p["birth_date"]
    nk = [x for x in hr if not x["remote"]]
    # R2 用= 前々開催の終わりまでのポイント(その時点より後で最初の走の before)
    for x in nk:
        v = idx.get((x["track"], x["d"]))
        cut = mtg[v[0] - 2][1] if v and v[0] >= 2 else None
        p2 = None
        if cut is not None:
            later = [y for y in hr if y["d"] > cut]
            if later:
                p2 = later[0].get("before")
            else:
                p2 = x.get("before")
        x["pts_R2"] = p2
    for rule in ("R1", "R2"):
        prevA = prevB = None
        prev_half = None
        for x in nk:
            pts = x.get("before") if rule == "R1" else x.get("pts_R2")
            g = grade(pts, age_at(birth, x["d"]), x["d"])
            x["kaku_%sA" % rule] = g
            hkey = (x["d"][:4], half(x["d"]))
            if g is None:
                x["kaku_%sB" % rule] = None
            elif prevB is None or hkey != prev_half:
                x["kaku_%sB" % rule] = g
            else:
                x["kaku_%sB" % rule] = g if CLASSES.index(g) < CLASSES.index(prevB) else prevB
            prevB = x["kaku_%sB" % rule]
            prev_half = hkey
    return hr


def run_all(args):
    pts, runs, races, prize_by = load()
    mtg, idx = meetings(races)
    runs_by = collections.defaultdict(list)
    for r in runs:
        runs_by[r["horse_name"]].append(r)
    # 同着= 同じレース・同じ着順
    tie = collections.Counter((r["track"], r["race_date"], r["race_no"], r["finish"]) for r in runs if r["finish"])
    for r in runs:
        r["_tie"] = tie[(r["track"], r["race_date"], r["race_no"], r["finish"])] if r["finish"] else 1
    stat = collections.Counter()
    stoppers = collections.Counter()
    part = collections.Counter()
    neg = []
    srcs = collections.Counter()
    rows = []
    for p in pts:
        stat["頭"] += 1
        if p["points"] in ("", None):
            stat["いまの値が無い(抹消等)"] += 1
            continue
        hr = horse_runs(p, runs_by, races, prize_by, args.mixed)
        if not hr:
            stat["南関の走が DB に無い"] += 1
            continue
        reconstruct(p, hr, None if args.day_rule else idx)
        kaku_rules(p, hr, idx, mtg)
        win = [x for x in hr if x["d"] >= START]
        first_nk = min(x["d"] for x in hr if not x["remote"])
        for x in win:
            if x["src"] not in ("ok", "遠征", "mixed", "取消除外", "中止=0", "open=A1") and not x["src"].startswith(("ok+", "open=A1+")):
                srcs[x["src"]] += 1
        target = [x for x in win if not x["remote"]]
        if not target:
            stat["2024-01-01 以降に南関の走が無い"] += 1
            continue
        stat["対象"] += 1
        full = all(x.get("before") is not None for x in target)
        stat["全走で復元できた" if full else "途中から復元できない"] += 1
        if not full:
            stop = [x for x in hr if x["pts"] is None and x["d"] >= min(y["d"] for y in target)]
            stoppers[stop[-1]["src"] if stop else "?"] += 1
            reach = [x for x in target if x.get("before") is not None]
            part[round(100 * len(reach) / len(target) / 10) * 10] += 1
        if any(x.get("flag") for x in hr):
            stat["同名馬(遠征を見られない)"] += 1
        if first_nk > START:
            stat["2024-01-01 より後に南関へ(転入・新馬)"] += 1
        bad = [x for x in target if x.get("before") is not None and x["before"] < -0.5]   # ⛔制度の前(旧賞金の換算)は数えない
        if bad:
            why = "遠征あり" if any(x["remote"] for x in hr if x["d"] >= bad[0]["d"]) else (
                "同着あり" if any("同着" in x["src"] for x in hr if x["d"] >= bad[0]["d"]) else (
                    "混合クラスあり" if any(x["src"].startswith("mixed") for x in hr if x["d"] >= bad[0]["d"]) else "その他"))
            neg.append((p["horse_name"], p["code"], bad[0]["d"], round(bad[0]["before"], 1), why))
        for x in target:
            rows.append({"code": p["code"], "horse": p["horse_name"], "d": x["d"], "track": x["track"], "no": x["no"],
                         "fin": x["fin"], "race": x["name"], "kind": x["kind"], "earned": x["pts"], "src": x["src"],
                         "points_before": x.get("before"), "points_after": x.get("after"),
                         "kaku_R1A": x.get("kaku_R1A"), "kaku_R1B": x.get("kaku_R1B"),
                         "kaku_R2A": x.get("kaku_R2A"), "kaku_R2B": x.get("kaku_R2B"),
                         "race_cls": "/".join(race_classes(x["name"]))})
    with open(DATA / "recon_all.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("== 全頭(2024-01-01 以降・mixed=%s・反映=%s)" % (args.mixed, "走った日" if args.day_rule else "開催最終日"))
    for k, v in stat.items():
        print("  %-36s %d" % (k, v))
    print("  points_before < 0 の馬: %d" % len(neg))
    for n in neg[:15]:
        print("    ", n)
    print("  止めた理由(復元できない馬ごと・いちばん新しい止め)= %s" % dict(stoppers.most_common()))
    print("  復元できない馬が遡れた割合(%%)= %s" % dict(sorted(part.items())))
    print("  マイナスの理由= %s" % dict(collections.Counter(n[4] for n in neg)))
    print("  点が決まらない走(理由別・2024-01-01 以降):")
    for k, v in srcs.most_common():
        print("    %-30s %d" % (k, v))
    # 格の規則の一致(単一クラスのレースだけ・DB の名前から)
    agree = collections.Counter()
    n1 = 0
    for r in rows:
        rc = r["race_cls"].split("/") if r["race_cls"] else []
        if not rc:
            continue
        n1 += 1
        for k in ("kaku_R1A", "kaku_R1B", "kaku_R2A", "kaku_R2B"):
            if r[k] and r[k] in rc:
                agree[k] += 1
    print("  格の一致(レース名の格に含まれる・%d 走):" % n1, {k: "%.1f%%" % (100 * v / max(n1, 1)) for k, v in agree.items()})
    json.dump({"stat": stat, "neg": neg, "srcs": srcs, "agree": agree, "n_cls_runs": n1, "stoppers": stoppers, "part": part},
              open(DATA / "recon_all_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 検算 50 頭

def parse_result(h):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ")
    t = re.sub(r"\s+", " ", t)
    head = re.search(r"発走時刻 \d{1,2}:\d{2} (.+?) 詳細 (.+?) （(.+?)競走）", t)
    pm = re.search(r"番組ポイント ポイント 1着([\d,]+)P 2着([\d,]+)P 3着([\d,]+)P 4着([\d,]+)P 5着([\d,]+)P", t)
    return {"title": head.group(1) if head else None, "cond": head.group(2) if head else None,
            "kind": head.group(3) if head else None,
            "pts": tuple(int(x.replace(",", "")) for x in pm.groups()) if pm else None,
            "classes": race_classes(head.group(1)) if head else []}


def run_sample(args):
    import nankan_http as H
    pts, runs, races, prize_by = load()
    mtg, idx = meetings(races)
    runs_by = collections.defaultdict(list)
    for r in runs:
        runs_by[r["horse_name"]].append(r)
    tie = collections.Counter((r["track"], r["race_date"], r["race_no"], r["finish"]) for r in runs if r["finish"])
    for r in runs:
        r["_tie"] = tie[(r["track"], r["race_date"], r["race_no"], r["finish"])] if r["finish"] else 1
    lo = args.recent_from
    recent = {r["horse_name"] for r in runs if r["race_date"] >= lo}
    byname = collections.Counter(p["horse_name"] for p in pts)
    pool = [p for p in pts if p["horse_name"] in recent and p["points"] not in ("", None) and byname[p["horse_name"]] == 1]
    old = [p for p in pool if any(r["race_date"] < START for r in runs_by[p["horse_name"]])]
    new = [p for p in pool if p not in old]
    rnd = random.Random(args.seed)
    pick = rnd.sample(old, args.n_old) + rnd.sample(new, args.n - args.n_old)
    print("母集団 %d 頭(うち 2024 年より前から走る %d)→ %d 頭" % (len(pool), len(old), len(pick)))
    t0 = time.time()
    # ① 馬ページの結果リンク= raceid の答え(回日の作り方を確かめる)
    link_ok = link_ng = 0
    ng_ex = []
    for p in pick:
        h = H.get("/uma_info/%s.do" % p["code"])
        for rid in set(re.findall(r"/result/(\d{16})\.do", h)):
            d = "%s-%s-%s" % (rid[:4], rid[4:6], rid[6:8])
            tr = {v: k for k, v in NK.items()}.get(rid[8:10])
            mine = raceid(tr, d, int(rid[14:16]), idx) if tr else None
            if mine == rid:
                link_ok += 1
            else:
                link_ng += 1
                ng_ex.append((rid, mine))
    print("raceid の作り方(DB の日程から)= 一致 %d / 不一致 %d %s" % (link_ok, link_ng, ng_ex[:5]))
    # 本物の raceid(馬ページのリンク)を先に使う。DB の日程から組んだ raceid は船橋で 1 回ずれることがある
    inv = {v: k for k, v in NK.items()}
    real = {}
    for p in pick:
        for rid in re.findall(r"/result/(\d{16})\.do", H.get("/uma_info/%s.do" % p["code"])):
            if rid[8:10] in inv:
                real[(inv[rid[8:10]], "%s-%s-%s" % (rid[:4], rid[4:6], rid[6:8]), int(rid[14:16]))] = rid
    out = []
    for i, p in enumerate(pick, 1):
        official = {}
        for r in runs_by[p["horse_name"]]:
            if r["race_date"] < START:
                continue
            k = (r["track"], r["race_date"], int(r["race_no"]))
            rid = real.get(k) or raceid(*k, idx)
            res = parse_result(H.get("/result/%s.do" % rid)) if rid else {}
            if res.get("pts"):
                official[k] = res["pts"]
        ho = horse_runs(p, runs_by, races, prize_by, args.mixed, official)
        reconstruct(p, ho, idx)
        kaku_rules(p, ho, idx, mtg)
        off_by = {(y["track"], y["d"], y["no"]): y for y in ho if not y["remote"]}
        hr = horse_runs(p, runs_by, races, prize_by, args.mixed)
        reconstruct(p, hr, None if args.day_rule else idx)
        kaku_rules(p, hr, idx, mtg)
        first_nk = min((x["d"] for x in hr if not x["remote"]), default=None)
        for x in hr:
            if x["remote"] or x["d"] < START:
                continue
            rid = real.get((x["track"], x["d"], x["no"])) or raceid(x["track"], x["d"], x["no"], idx)
            res = parse_result(H.get("/result/%s.do" % rid)) if rid else {}
            off = res.get("pts")
            mine = None
            if off and x["fin"] and x["fin"] <= 5:
                tieN = next((r["_tie"] for r in runs_by[p["horse_name"]] if r["race_date"] == x["d"] and int(r["race_no"]) == x["no"]), 1)
                mine = sum(off[x["fin"] - 1:x["fin"] - 1 + tieN]) / tieN
            elif off:
                mine = 0
            remote_between = any(y["remote"] and y["d"] >= x["d"] and y["d"] < p["asof"] for y in hr)
            out.append({"code": p["code"], "horse": p["horse_name"], "d": x["d"], "track": x["track"], "no": x["no"],
                        "rid": rid, "fin": x["fin"], "note": x["note"], "db_race": x["name"], "kind": x["kind"],
                        "off_title": res.get("title"), "off_kind": res.get("kind"), "off_cls": "/".join(res.get("classes") or []),
                        "earned_calc": x["pts"], "src": x["src"], "earned_off": mine,
                        "points_before": x.get("before"), "points_after": x.get("after"),
                        "kaku_R1A": x.get("kaku_R1A"), "kaku_R1B": x.get("kaku_R1B"),
                        "kaku_R2A": x.get("kaku_R2A"), "kaku_R2B": x.get("kaku_R2B"),
                        "o_before": (off_by.get((x["track"], x["d"], x["no"])) or {}).get("before"),
                        "o_R1": (off_by.get((x["track"], x["d"], x["no"])) or {}).get("kaku_R1A"),
                        "o_R2": (off_by.get((x["track"], x["d"], x["no"])) or {}).get("kaku_R2A"),
                        "age": age_at(p["birth_date"], x["d"]), "first_nk": first_nk, "asof": p["asof"],
                        "now_points": p["points"], "now_kaku": p["kaku"], "remote_between": remote_between,
                        "tie": x["src"].endswith("同着")})
        print("  %2d/%d %s %d 走 取得 %d 本 %.0f 秒" % (i, len(pick), p["horse_name"], len(hr), H.STATS["requests"], time.time() - t0), flush=True)
    with open(DATA / "sample_runs.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    json.dump({"stats": H.STATS, "link_ok": link_ok, "link_ng": link_ng, "ng_ex": ng_ex[:20], "pick": [p["code"] for p in pick],
               "n_old": args.n_old, "elapsed": time.time() - t0},
              open(DATA / "sample_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("取得", H.STATS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["all", "sample"])
    ap.add_argument("--mixed", default="upper", choices=["upper", "lower"])
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--n-old", type=int, default=25)
    ap.add_argument("--seed", type=int, default=196)
    ap.add_argument("--recent-from", default="2026-09-03")
    ap.add_argument("--day-rule", action="store_true", help="比較用= 反映を「走った日 < asof」で数える(最初の版)")
    a = ap.parse_args()
    (run_all if a.mode == "all" else run_sample)(a)


if __name__ == "__main__":
    main()

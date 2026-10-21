# 2026-10-21 笠松の番組賞金の仕組みの照合(手元・書き込みなし)。入力の台帳= 一時便(ks_dump.py・コミット 32a4679)の artifact tokai_dump.json.gz・
# 一覧= fetch_lists(笠松 /raceprogram の 21 回+名古屋 2025-15〜2026-16)→ ks_lists_pages.py で開催日ごとに。パス S は手元の作業場所
"""笠松の番組賞金の仕組みの照合(手元・書き込みなし)。
A= 前の一覧の公式の値から次の一覧を当てる・B= tokai_state の計算値と各一覧。名古屋は B の形で前後を数える。
引数: 候補の名前(カンマ区切り)。候補は環境変数 KS_RULES に入れて class_calc に効かせる。"""
import datetime as dt, gzip, json, os, sys, unicodedata, re
from collections import Counter, defaultdict
S = r"C:\Users\kouki\AppData\Local\Temp\claude\C--Users-kouki-nar-site\6ec6fe4f-561d-4388-87fe-dbb7d57d3fea\scratchpad"
sys.path.insert(0, r"C:\Users\kouki\wt\nar-jobs-ks-mech\cloud")
import class_calc as C  # noqa: E402

D = json.load(gzip.open(S + r"\dl\tokai_dump.json.gz", "rt", encoding="utf-8"))
L = json.load(open(S + r"\lists.json", encoding="utf-8"))
races = {(t, d, int(n)): {"race_name": rn, "race_kind": rk} for t, d, n, rn, rk in D["races"]}
C.TOKAI_ADJ.update(C.tokai_adj_dates(races))
births = D["births"]
byname = defaultdict(list)
for r in D["rows"]:
    byname[r["horse_name"]].append(r)
LAG = C.TOKAI_LAG
KS_ADJ = C.TOKAI_ADJ.get("笠松", [])


def pick(name, tracks):
    rs = [r for r in byname.get(name, []) if any(x.get("tr") in tracks for x in r["runs"]) and C._date(births.get(r["code"]))]
    return rs[0] if len(rs) == 1 else None


# 笠松の一覧= 連続する開催日の塊。間が 4 日以内で値の食い違いが無い塊はまとめる
ks = []
for b in L["ksb"]:
    f = dt.date.fromisoformat(b["first"])
    if ks and (f - ks[-1]["last"]).days <= 5 and not any(ks[-1]["off"].get(n, p) != p for n, p in b["off"].items()):
        ks[-1]["off"].update(b["off"]); ks[-1]["last"] = dt.date.fromisoformat(b["days"][-1]); continue
    ks.append({"first": f, "last": dt.date.fromisoformat(b["days"][-1]), "off": dict(b["off"])})


def runs_of(r):
    return r["runs"]


def state(r, asof, track="笠松", seed=None):
    b = C._date(births[r["code"]])
    return C.tokai_state(runs_of(r), b, asof, LAG, races, track=track, seed=seed)


def label(x):
    if x.get("tr") in C.TOKAI_TRACKS:
        return C.tokai_rate_resident(x, races.get((x.get("tr"),) + C._rkey(x)), x.get("tr"))
    return C.tokai_rate_away(x)


def classify(r, lo, hi, off0, off1, pred):
    """lo 以上 hi 未満の走・調整で外れの種類を決める"""
    b = C._date(births[r["code"]])
    w = [x for x in r["runs"] if (d := C._date(x.get("d"))) and lo <= d < hi]
    adj = [e for e in KS_ADJ if lo < e <= hi]
    hen = [e for e in C.TOKAI_HEN.values() if lo < e <= hi]
    s = str(off1)
    if len(s) >= 4 and s[0] in "12" and int(s[1:]) * 1000 == pred:
        return "PDFの読み(頭に1桁)"
    if any(x.get("ta") and x.get("ta") not in ("笠松", "岐阜") for x in w):
        return "所属替え・転入"
    if any(C._is_jra(x) for x in w):
        return "遠征(中央)"
    if any(x.get("tr") not in C.TOKAI_TRACKS for x in w):
        return "遠征(他地区)"
    labs = {label(x)[1] for x in w} - {"東海"}
    if labs:
        return "率=" + "/".join(sorted(labs))
    a = hi.year - b.year
    gain = sum(int(x.get("prize") or 0) for x in w) // 1000
    if hen and a == 3:
        return "3歳の一斉編入"
    line = 4500 if a == 2 else 4400
    if a in (2, 3) and off0 < line <= off0 + gain:
        return "2・3歳の線越え"
    if adj:
        won = any(x.get("fin") == 1 and x.get("tr") in C.TOKAI_TRACKS for x in w)
        return "見直し(" + ("勝ちあり" if won else "勝ちなし") + "・" + ("計算が多い" if pred > off1 * 1000 else "計算が少ない") + ")"
    if not w:
        return "走らずに変化"
    if abs(pred - off1 * 1000) <= 3000:
        return "端数(3千以内)"
    if any(x.get("fin") is None for x in w):
        return "着順なし(取消/除外?)"
    return "一般の収得(100%)"


def run_ks(tag, detail=False):
    resA, resB, catsA, catsB, sampA = [], [], Counter(), Counter(), defaultdict(list)
    bmat = {}
    for j, li in enumerate(ks):
        cut = C.tokai_cutoff(li["first"], LAG, "笠松")
        n = e = 0
        for name, k in li["off"].items():
            r = pick(name, ("笠松",))
            if not r:
                continue
            v = state(r, li["first"])[0]
            n += 1; e += v == k * 1000
            bmat.setdefault(name, []).append((j, v == k * 1000, v, k))
        resB.append((li["first"], n, e))
        if j == 0:
            continue
        p = ks[j - 1]
        cut0 = C.tokai_cutoff(p["first"], LAG, "笠松")
        adjw = any(cut0 < x <= cut for x in KS_ADJ)
        n = e = 0
        for name, k in li["off"].items():
            if name not in p["off"]:
                continue
            r = pick(name, ("笠松",))
            if not r:
                continue
            k0 = p["off"][name]
            pred = state(r, li["first"], seed=(cut0, k0 * 1000))[0]
            n += 1
            if pred == k * 1000:
                e += 1
                continue
            c = classify(r, cut0, cut, k0, k, pred)
            catsA[c] += 1
            sampA[c].append(f"{name} {p['first']:%m/%d}→{li['first']:%m/%d} {k0}→{k} 計算{pred // 1000}")
            if os.environ.get("DUMPCAT") and (os.environ["DUMPCAT"] in c or os.environ["DUMPCAT"] == "all"):
                w = [x for x in r["runs"] if (dd := C._date(x.get("d"))) and cut0 <= dd < cut]
                print("  ×", name, r["runs"] and C._date(births[r["code"]]).year, f"{p['first']:%m/%d}→{li['first']:%m/%d}", k0, "→", k, "計算", pred // 1000,
                      "|", "; ".join(f"{x.get('d')} {x.get('tr')} {x.get('ta')} {x.get('name')} {x.get('fin')} {int(x.get('prize') or 0)//1000} {label(x)[1]}" for x in w))
        resA.append((p["first"], li["first"], adjw, n, e))
    for name, xs in bmat.items():
        bad = [t for t in xs if not t[1]]
        if not bad:
            catsB["(全部合う)"] += 1
            continue
        j = bad[0][0]
        prev = [t for t in xs if t[0] < j]
        r = pick(name, ("笠松",))
        if not prev:
            st = state(r, ks[j]["first"])
            catsB["初めて載った回(" + ("一覧の先頭" if j == 0 else st[2]) + ")"] += 1
            continue
        pj = prev[-1][0]
        c = classify(r, C.tokai_cutoff(ks[pj]["first"], LAG, "笠松"), C.tokai_cutoff(ks[j]["first"], LAG, "笠松"),
                     prev[-1][3], bad[0][3], bad[0][2])
        catsB[c] += 1
    last = resB[-1]
    print(f"== {tag}: A 差0 {sum(x[4] for x in resA)}/{sum(x[3] for x in resA)}・B 最後の回 {last[0]} {last[2]}/{last[1]}"
          f"・B 全回 {sum(x[2] for x in resB)}/{sum(x[1] for x in resB)}")
    if detail:
        print("A 回の組: 前→次 見直しをまたぐ 頭数 差0 率")
        for a, b, w, n, e in resA:
            print(f"  {a} → {b} {'見直し' if w else '      '} {n:4} {e:4} {e / max(n, 1):.1%}")
        print("A 外れの種類:")
        for c, n in catsA.most_common():
            print(f"  {n:4} {c} 例: {' / '.join(sampA[c][:3])}")
        print("B 回ごと: 一覧 頭数 差0")
        for f, n, e in resB:
            print(f"  {f} {n:4} {e:4}")
        print("B 馬ごとに最初にずれる回の種類:")
        for c, n in catsB.most_common():
            print(f"  {n:4} {c}")
    return resA, resB


# 名古屋: 公式の編成馬一覧(年-回-日)。日の日付= 載った馬の名古屋の走の日の最頻値・その回の朝= 日の最小
ng_cyc = defaultdict(dict)
for x in L["ng"]:
    ds = Counter()
    for name, age, prize in x["off"]:
        for r in byname.get(name, []):
            for y in r["runs"]:
                if y.get("tr") == "名古屋" and str(y.get("d", ""))[:4] in ("2025", "2026"):
                    ds[str(y["d"])[:10]] += 1
    if ds:
        ng_cyc[(x["y"], x["c"])][x["d"]] = (dt.date.fromisoformat(ds.most_common(1)[0][0]), x["off"])


def run_ng(tag):
    n = e = 0
    for (y, c), days in sorted(ng_cyc.items()):
        first = min(v[0] for v in days.values())
        seen = {}
        for _d, (_dd, off) in days.items():
            for name, age, prize in off:
                seen[name] = prize
        for name, prize in seen.items():
            r = pick(name, ("名古屋",))
            if not r:
                continue
            v = state(r, first, track="名古屋")[0]
            n += 1; e += v == prize * 1000
    print(f"== {tag}: 名古屋 差0 {e}/{n}")
    return e, n


if __name__ == "__main__":
    print("笠松の一覧", len(ks), [f"{x['first']:%m/%d}" for x in ks])
    print("笠松の見直しの日", [x.isoformat() for x in KS_ADJ if x.year >= 2025], "一斉編入", {k: v.isoformat() for k, v in C.TOKAI_HEN.items()})
    for tag in (sys.argv[1].split(",") if len(sys.argv) > 1 else ["今"]):
        ts = set() if tag == "今" else set(tag.split("+"))
        C.TOKAI_KS_BLOCKLAG = next((int(t[3:]) for t in ts if t.startswith("blk")), 0)
        C.TOKAI_KS_HEN_OWN = "hen" in ts
        C.TOKAI_KS_CARRY = "carry" in ts
        C.TOKAI_KS_ENT = "ent" in ts
        C.TOKAI_KS_SP60 = "sp60" in ts
        C.TOKAI_KS_MOVE = "move" in ts
        C.TOKAI_KS_OLD.clear(); C.TOKAI_KS_OLD.update({"jadd", "cut15", "cut60", "ceil"} | {t for t in ts if t in ("cap200",)})
        if any(t.startswith("lag") for t in ts):
            LAG = int(next(t for t in ts if t.startswith("lag"))[3:])
        run_ks(tag, detail=(len(sys.argv) <= 2))
        if os.environ.get("NG", "1") == "1":
            run_ng(tag)

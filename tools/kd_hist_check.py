# 2026-10-21 研究(手元・DB に書かない): KDSCOPE の古い経歴(kd_hist_build.py の出力)を足す前/後で、計算だけの照合 B を出す。
# 出発点なし(TOKAI_KS_SEED=0・TOKAI_OFFICIAL=0)・決まりは class_calc の既定のまま。笠松= lists.json の各回・名古屋= vals.csv の各回。
import csv, datetime as dt, gzip, importlib.util, json, os, sys
from collections import Counter, defaultdict
os.environ["TOKAI_KS_SEED"] = "0"
os.environ["TOKAI_OFFICIAL"] = "0"
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "cloud"))
import class_calc as C  # noqa: E402
spec = importlib.util.spec_from_file_location("m", os.path.join(here, "ks_mech_check.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
H = json.load(gzip.open(m.S + r"\kd_hist.json.gz", "rt", encoding="utf-8"))
VALS = os.environ.get("NG_VALS", r"C:\Users\kouki\nar-site\research\tokai-prize\prog\vals.csv")

orig = {r["code"]: r["runs"] for r in m.D["rows"]}
races0 = dict(m.races)
races_kd = dict(races0)
for t, d, n, rn, rk in H["races"]:
    races_kd[(t, d, int(n))] = {"race_name": rn, "race_kind": rk}


def runs_kd(code):
    fill = H["fill_ta"].get(code, {})
    out = []
    for x in orig[code]:
        k = f"{x.get('d')}|{x.get('tr')}|{x.get('no')}"
        out.append(dict(x, ta=fill[k]) if k in fill and not x.get("ta") else x)
    return H["add"].get(code, []) + out


kdruns = {c: runs_kd(c) for c in orig}


def setup(use_runs, use_races):
    for r in m.D["rows"]:
        r["runs"] = kdruns[r["code"]] if use_runs else orig[r["code"]]
    m.races = races_kd if use_races else races0
    C.TOKAI_ADJ.clear()
    C.TOKAI_ADJ.update(C.tokai_adj_dates(m.races))
    m.KS_ADJ = C.TOKAI_ADJ.get("笠松", [])


# 名古屋の回= vals.csv の日を 4 日以内の空きでまとめる・朝= 回の最初の日
ngd = defaultdict(dict)
for d, name, age, prize in csv.reader(open(VALS, encoding="utf-8-sig")):
    ngd[dt.date.fromisoformat(d)][name] = int(prize)
ng = []
for d in sorted(ngd):
    if ng and (d - ng[-1]["last"]).days <= 4:
        ng[-1]["off"].update(ngd[d]); ng[-1]["last"] = d
    else:
        ng.append({"first": d, "last": d, "off": dict(ngd[d])})


def first_kind(r, asof, track):
    """最初に載った回でずれた馬の種類(締めより前の走で決める)"""
    cut = C.tokai_cutoff(asof, m.LAG, track)
    rs = [x for x in r["runs"] if (d := C._date(x.get("d"))) and d < cut]
    if r["code"] not in H["link"]:
        return "経歴がまだ足りない(KD と結べない)"
    b = C._date(m.births[r["code"]])
    loc = sorted(C._date(x["d"]) for x in rs)
    if loc and loc[0].year - b.year >= 4:
        return "経歴がまだ足りない(初めの走が 4 歳以上)"
    if any(C._is_jra(x) for x in rs):
        return "中央の走"
    if any(x.get("tr") not in C.TOKAI_TRACKS or (x.get("ta") and x.get("ta") not in ("愛知", "笠松", "岐阜")) for x in rs):
        return "転入の換算"
    return "決まり(東海だけの経歴)"


def run(lists, track, tag):
    tot = e0 = e3 = 0
    per = defaultdict(list)
    for j, li in enumerate(lists):
        for name, k in li["off"].items():
            r = m.pick(name, (track,))
            if not r:
                continue
            v = C.tokai_state(r["runs"], C._date(m.births[r["code"]]), li["first"], m.LAG, m.races, track=track)[0]
            tot += 1; e0 += v == k * 1000; e3 += abs(v - k * 1000) <= 3000
            per[name].append((j, v == k * 1000, v, k))
    cats, kinds = Counter(), Counter()
    for name, xs in per.items():
        bad = [t for t in xs if not t[1]]
        if not bad:
            cats["全部合う"] += 1
            continue
        r = m.pick(name, (track,))
        j = bad[0][0]
        if j == xs[0][0]:
            cats["最初に載った回で既にずれ"] += 1
            kinds["最初: " + first_kind(r, lists[j]["first"], track)] += 1
        else:
            cats["途中からずれ"] += 1
            pj = max(t for t in xs if t[0] < j)
            if track == "笠松":
                lo, hi = C.tokai_cutoff(lists[pj[0]]["first"], m.LAG, track), C.tokai_cutoff(lists[j]["first"], m.LAG, track)
                kinds["途中: " + m.classify(r, lo, hi, pj[3], bad[0][3], bad[0][2])] += 1
            else:
                kinds["途中"] += 1
    print(f"== {tag} {track}: 回 {len(lists)}・件 {tot}・差0 {e0} ({e0 / max(tot, 1):.1%})・3千以内 {e3} ({e3 / max(tot, 1):.1%})・馬 {len(per)} {dict(cats)}")
    for c, n in kinds.most_common():
        print(f"     {n:4} {c}")
    return per


res = {}
for tag, ur, uc in (("前", False, False), ("所属だけ", True, False), ("レースだけ", False, True), ("後(両方)", True, True)):
    setup(ur, uc)
    res[tag] = (run(m.ks, "笠松", tag), run(ng, "名古屋", tag))
# 足す行数= 2026-07-01 以降に東海で走った馬
act = {r["code"] for r in m.D["rows"] if any(x.get("tr") in C.TOKAI_TRACKS and str(x.get("d")) >= "2026-07-01" for x in orig[r["code"]])}
print(f"重なりの照らし合わせ {H['cmp']}")
print(f"足す行: 走り {sum(len(H['add'].get(c, [])) for c in act)}(全体 {sum(len(v) for v in H['add'].values())})"
      f"・所属を埋める走り {sum(len(H['fill_ta'].get(c, {})) for c in act)}(全体 {sum(len(v) for v in H['fill_ta'].values())})"
      f"・東海の古いレース {len(H['races'])}・今走る馬 {len(act)}")

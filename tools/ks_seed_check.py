# 2026-10-21 笠松の出発点(全部の回の出走投票準備一覧)を入れた tokai_state の照合(手元・書き込みなし)。
# 入力= ks_mech_check.py と同じ台帳(一時便の artifact)と lists.json(名古屋)・笠松の一覧は tokai_official.fetch_kasamatsu_all で取る。
# 引数: 降級の見込みの CSV(tokai_demotion.py --dry-run --out)
import datetime as dt
import json
import os
import sys
from collections import Counter
sys.argv = [sys.argv[0], "今", "x"] + sys.argv[1:]
os.environ["NG"] = "0"
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "cloud"))
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("m", os.path.join(here, "ks_mech_check.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
C = m.C
import tokai_official as T  # noqa: E402

cache = os.path.join(m.S, "ks_all.json")
if os.path.exists(cache):
    lists = [(c, set(dt.date.fromisoformat(x) for x in ds), dt.date.fromisoformat(cut), off)
             for c, ds, cut, off in json.load(open(cache, encoding="utf-8"))]
else:
    lists = T.fetch_kasamatsu_all(lambda d: C.tokai_cutoff(d, 0, "笠松"))
    json.dump([(c, sorted(x.isoformat() for x in ds), cut.isoformat(), off) for c, ds, cut, off in lists],
              open(cache, "w", encoding="utf-8"), ensure_ascii=False)
print("一覧", len(lists), [f"{c}:{min(ds):%m/%d}:{cut:%m/%d}:{len(off)}" for c, ds, cut, off in lists])


def seeds_of(name, upto=None):
    return [(cut, k * 1000) for j, (_c, _ds, cut, off) in enumerate(lists) if name in off and (upto is None or j < upto)
            for k in [off[name]]]


def st(r, asof, track="笠松", seed=None):
    return C.tokai_state(r["runs"], C._date(m.births[r["code"]]), asof, m.LAG, m.races, track=track, seed=seed)


# (a) 第12回= 最後の一覧
c, ds, cut, off = lists[-1]
first = min(ds)
for tag, use in (("前", False), ("後", True)):
    n = e = 0
    for name, k in off.items():
        r = m.pick(name, ("笠松",))
        if not r:
            continue
        n += 1
        e += st(r, first, seed=seeds_of(name) if use else None)[0] == k * 1000
    print(f"(a) 第{c}回 {first} {tag}: {e}/{n}")
# (b) 各回= その 1 つ前の回までの一覧を出発点に
tot = Counter()
for j in range(1, len(lists)):
    c, ds, cut, off = lists[j]
    first = min(ds)
    n = e0 = e1 = 0
    for name, k in off.items():
        r = m.pick(name, ("笠松",))
        if not r:
            continue
        n += 1
        e0 += st(r, first)[0] == k * 1000
        e1 += st(r, first, seed=seeds_of(name, j))[0] == k * 1000
    tot["n"] += n; tot["e0"] += e0; tot["e1"] += e1
    print(f"(b) 第{c}回 {first}: {n} 頭 前 {e0} 後 {e1}")
print(f"(b) 計: {tot['n']} 前 {tot['e0']} ({tot['e0'] / tot['n']:.1%}) 後 {tot['e1']} ({tot['e1'] / tot['n']:.1%})")
# (c) 名古屋
for tag, use in (("前", False), ("後", True)):
    n = e = 0
    for (y, cy), days in sorted(m.ng_cyc.items()):
        f = min(v[0] for v in days.values())
        seen = {}
        for _d, (_dd, o) in days.items():
            for name, age, prize in o:
                seen[name] = prize
        for name, prize in seen.items():
            r = m.pick(name, ("名古屋",))
            if not r:
                continue
            n += 1
            e += st(r, f, track="名古屋", seed=seeds_of(name) if use else None)[0] == prize * 1000
    print(f"(c) 名古屋 {tag}: {e}/{n}")
# 5. 降級の見込み(tokai_demotion の p1)と tokai_state の 12 月末の見込み(1/1 に見直しを足す・その後の走なし)
if len(sys.argv) > 3:
    import csv
    rows = [x for x in csv.DictReader(open(sys.argv[3], encoding="utf-8-sig")) if x.get("venue") in ("笠松", "kasamatsu")]
    adj = dt.date(2027, 1, 1)
    C.TOKAI_ADJ.setdefault("笠松", []).append(adj)
    same, diff = 0, []
    extra = json.load(open(os.environ["EXTRA"], encoding="utf-8")) if os.environ.get("EXTRA") else {}   # 台帳にまだ無い走(きょうの走)
    for x in rows:
        name = x["horse_name"]
        r = m.pick(name, ("笠松",))
        if not r:
            continue
        v = C.tokai_state(r["runs"] + extra.get(name, []), C._date(m.births[r["code"]]), dt.date(2027, 1, 2), 1, m.races, track=None,
                          seed=seeds_of(name))[0] // 1000
        p1 = int(float(x["p1"]))
        if v == p1:
            same += 1
        else:
            diff.append(f"{name} 見込み {p1} 計算 {v}(今 {x.get('p_now')}・収得 {x.get('earn')}・勝ち {x.get('won')})")
    print(f"(5) 笠松の見込みの行 {len(rows)}・同じ {same}・違う {len(diff)}")
    for d in diff[:int(os.environ.get("NDIFF", "5"))]:
        print("   ", d)

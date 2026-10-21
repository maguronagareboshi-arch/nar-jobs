"""一時: 笠松の計算値と公式の出走投票準備一覧の一致数を、令和7年度の決まりの組み合わせごとに出す(書き込みなし)"""
import datetime as dt
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import class_calc as C  # noqa: E402
import tokai_official as T  # noqa: E402

consts = C.load_consts(None)
system = next(s for s in consts["SYSTEMS"] if s["id"] == "nagoya")
lines = C.tokai_lines(system)
url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
rows, births, entered, races = C.fetch_tokai(url, key, dt.date(2026, 4, 1))
C.TOKAI_ADJ.update(C.tokai_adj_dates(races))
off, cyc = T.fetch_kasamatsu()
print(f"KS 第{cyc}回 一覧 {len(off)} 頭")
today = dt.datetime.now(C.JST).date()
targets = []
for r in rows:
    runs = r.get("runs") or []
    local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
    last_tr = local[0].get("tr") if local else None
    b = C._date(births.get(r["code"]))
    if last_tr == "笠松" and b and r.get("horse_name") in off:
        targets.append((r["horse_name"], runs, b))
print(f"KS 照合の対象 {len(targets)} 頭")


def run(rules, show=False):
    C.TOKAI_KS_OLD.clear()
    C.TOKAI_KS_OLD.update(rules)
    e = n3 = n = 0
    diffs = []
    for name, runs, b in targets:
        c = C.tokai_calc(lines, runs, today, C.TOKAI_LAG, b, (lambda d, b=b: d.year - b.year), races, "kasamatsu")
        if not c:
            continue
        n += 1
        dv = (c.get("value") or 0) - off[name] * 1000
        e += dv == 0
        n3 += abs(dv) <= 3000
        diffs.append((abs(dv), name, c.get("value"), off[name] * 1000))
    print(f"KS {'+'.join(sorted(rules)) or 'なし'}: 計算 {n} 頭・差0 {e}・差3千以内 {n3}")
    if show:
        for d, name, v, o in sorted(diffs, reverse=True)[:8]:
            print(f"KS   差 {name} 計算 {v:,} 公式 {o:,}")
    return e


base = run(set(), True)
j = run({"jadd"}, True)
good = {"jadd"} if j >= base else set()
for x in ("cut15", "cut60", "ceil", "cap200"):
    if run(good | {x}) > run(good):
        good = good | {x}
run(good, True)

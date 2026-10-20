# -*- coding: utf-8 -*-
"""研究用・1 回きり: 実際に決まった 3連単の組に、締め切り直前に票が集まっていたか。
便 .github/workflows/trifecta-winner-late.yml(workflow_dispatch のみ)から走らせ、docs/trifecta-winner-late/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得は late_money.py の部品)。集計は全部ここ。書き込みなし。
票数そのものは記録に無い。倍率から作る売れ方 s=(1/倍率)÷全組の合計 を使い、比 s_確定/s_早 で「その組が直前に増えたか」を見る。
  確定= 3連単の f=true の最大 id の行。早= 確定の W 分前(W=10/5/2)以前で最も新しい f=false の行(W〜W+5 分前に収まるものだけ)。
  比 r=s_確定/s_早。1 を超えるほど、その組は直前に全体より多く買われた。全体の増減(総額の伸び)は比で消える。
  基準= 同じレース・同じ早のオッズ帯の、決まった組以外の全組の log r の平均。差= log r(決まった組)-基準。
  着順は nar_runs の finish。1・2・3 着が 1 頭ずつに決まらないレース/確定行なし/早の行なし/確定行に決まった組なしは除外。
"""
import datetime as dt
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import req, rows_by_id, rows_offset, rkey, num, ts, JST, log, COMBO_CHUNK  # noqa: E402
import urllib.parse  # noqa: E402

D_FROM, D_TO = dt.date(2026, 9, 8), dt.date(2026, 10, 19)
WINS = (10, 5, 2)
BANDS = ((0, 50, "〜50 倍"), (50, 200, "50〜200 倍"), (200, 1000, "200〜1000 倍"), (1000, 1e18, "1000 倍〜"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "trifecta-winner-late", "result.md")


def fetch(base, key, day):
    d = urllib.parse.quote(day)
    runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,finish"
                       "&race_date=eq.%s&order=track.asc,race_no.asc,runner_number.asc" % d)
    full = rows_by_id(base, key, "/rest/v1/nar_odds_full_ticks?select=id,track,race_date,race_no,kind,observed_at,f,h"
                      "&race_date=eq.%s&kind=eq.sanrentan" % d)
    return runs, full


def get_combos(base, key, ids):
    out, ids = {}, sorted(set(ids))
    for i in range(0, len(ids), COMBO_CHUNK):
        for r in req(base, key, "/rest/v1/nar_odds_full_ticks?select=id,combos&id=in.(%s)"
                     % ",".join(str(x) for x in ids[i:i + COMBO_CHUNK])):
            out[r["id"]] = r["combos"]
    return out


def top3(runs):
    by = {}
    for r in runs:
        by.setdefault(rkey(r), []).append(r)
    out = {}
    for k, rs in by.items():
        pos = {}
        for r in rs:
            try:
                f = int(r["finish"])
            except (TypeError, ValueError):
                continue
            pos.setdefault(f, []).append(int(r["runner_number"]))
        if all(len(pos.get(i, [])) == 1 for i in (1, 2, 3)):
            out[k] = tuple(pos[i][0] for i in (1, 2, 3))
    return out


def pick(full):
    """レース → (確定 id, {W: 早 id})。"""
    by = {}
    for r in full:
        by.setdefault(rkey(r), []).append(r)
    out = {}
    for k, rows in by.items():
        fins = [r for r in rows if r.get("f")]
        if not fins:
            continue
        fin = max(fins, key=lambda r: r["id"])
        ft = ts(fin["observed_at"])
        if ft is None:
            continue
        ws = {}
        for w in WINS:
            hi, lo = ft - dt.timedelta(minutes=w), ft - dt.timedelta(minutes=w + 5)
            cand = [r for r in rows if not r.get("f") and r["id"] < fin["id"]
                    and ts(r["observed_at"]) is not None and lo <= ts(r["observed_at"]) <= hi]
            if cand:
                ws[w] = max(cand, key=lambda r: ts(r["observed_at"]))["id"]
        if ws:
            out[k] = (fin["id"], ws)
    return out


def shares(combos):
    """{(a,b,c): (倍率, 売れ方)}。"""
    o = {}
    for c in combos or []:
        if not isinstance(c, (list, tuple)) or len(c) < 4:
            continue
        v = num(c[3])
        if v is not None:
            o[(int(c[0]), int(c[1]), int(c[2]))] = v
    tot = sum(1.0 / v for v in o.values())
    return {k: (v, (1.0 / v) / tot) for k, v in o.items()} if tot > 0 else {}


def band(o):
    for lo, hi, lab in BANDS:
        if lo <= o < hi:
            return lab
    return BANDS[-1][2]


def cell():
    return {"n": 0, "d": [], "up": 0, "wr": []}


def main():
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    C = {w: {b[2]: cell() for b in BANDS} for w in WINS}
    A = {w: cell() for w in WINS}
    ex = {"days": 0, "races": 0, "x_fin": 0, "x_nofull": 0, "x_hit": 0}
    day = D_FROM
    while day <= D_TO:
        ds = day.isoformat()
        day += dt.timedelta(days=1)
        runs, full = fetch(base, key, ds)
        if not full:
            continue
        ex["days"] += 1
        t3, pk = top3(runs), pick(full)
        need = set()
        for k, (fid, ws) in pk.items():
            if k in t3:
                need.add(fid)
                need.update(ws.values())
        cb = get_combos(base, key, need)
        for k, (fid, ws) in pk.items():
            ex["races"] += 1
            if k not in t3:
                ex["x_fin"] += 1
                continue
            fs = shares(cb.get(fid))
            win = t3[k]
            if win not in fs:
                ex["x_hit"] += 1
                continue
            for w, eid in ws.items():
                es = shares(cb.get(eid))
                if win not in es:
                    continue
                keys = [c for c in fs if c in es]
                st = sum(fs[c][1] for c in keys)
                se = sum(es[c][1] for c in keys)
                if st <= 0 or se <= 0:
                    continue
                lr = {c: math.log((fs[c][1] / st) / (es[c][1] / se)) for c in keys}
                wb = band(es[win][0])
                base_l = [lr[c] for c in keys if c != win and band(es[c][0]) == wb]
                if len(base_l) < 10:
                    continue
                diff = lr[win] - sum(base_l) / len(base_l)
                for cc in (C[w][wb], A[w]):
                    cc["n"] += 1
                    cc["d"].append(diff)
                    cc["up"] += 1 if diff > 0 else 0
                    cc["wr"].append(math.exp(lr[win]))
        log("  %s 済み(レース %d)" % (ds, ex["races"]))
    write(C, A, ex)


def stat(c):
    n = c["n"]
    if not n:
        return "| 0 | - | - | - | - |"
    m = sum(c["d"]) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in c["d"]) / (n - 1)) if n > 1 else 0.0
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    med = sorted(c["wr"])[n // 2]
    return "| %d | %.3f | %.1f%% | %+.1f | %.2f |" % (n, math.exp(m), c["up"] / n * 100, t, med)


def write(C, A, ex):
    L = ["# 決まった 3連単の組に、締め切り直前に票は集まっていたか(研究・1 回きり)", "",
         "期間 %s〜%s。作成 %s。" % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "- 記録のある日 %d・レース %d・除外 着順が 1 頭ずつでない %d・確定行に決まった組なし %d" % (ex["days"], ex["races"], ex["x_fin"], ex["x_hit"]), "",
         "読み方: 「直前の増え方」= 決まった組の (確定÷早) の売れ方の比 ÷ 同じレース・同じ早オッズ帯の他の組の平均比(幾何平均)。"
         "1.00 より大きいと、決まった組は他の組より直前に多く買われた。上昇した割合は 50% が基準。t は差の平均÷標準誤差(約 ±2 を超えれば偶然でない目安)。"
         "票数や金額は記録に無いので、円には換算していない。", ""]
    for w in WINS:
        L += ["## 確定の %d 分前 → 確定" % w, "",
              "| 早のオッズ帯 | レース数 | 直前の増え方 | 他より増えた割合 | t | 比の中央値 |", "|---|---:|---:|---:|---:|---:|"]
        for _, _, lab in BANDS:
            L.append("| %s %s" % (lab, stat(C[w][lab])))
        L.append("| 全体 %s" % stat(A[w]))
        L.append("")
    L += ["> 1 か月半・約 1,800 レース。これだけでは買う根拠にならない(決まってから見た事後の分析)。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

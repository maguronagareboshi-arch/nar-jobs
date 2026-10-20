# -*- coding: utf-8 -*-
"""研究用・1 回きり: 締め切り前に見える「直前の伸び」が大きい 3連単の組を買うと回収はどうか。
便 .github/workflows/trifecta-surge-return.yml(workflow_dispatch のみ)から走らせ、docs/trifecta-surge-return/result.md を書く。

⛔本番 DB では REST の単純 select だけ。集計は全部ここ。書き込みなし。取得・部品は trifecta_winner_late.py と同じ。
時点(確定= f=true の最大 id の行の observed_at を ft):
  買う時点 D= ft-2 分以前で最も新しい f=false の行(ft-7〜ft-2 分に収まるものだけ)。
  比べる時点 E= D の 8 分前以前で最も新しい f=false の行(D の 8〜13 分前に収まるものだけ)。
  伸び r=(s_D/s_E)。s=(1/倍率)÷その行の全組の合計(D と E の両方に倍率がある組だけで正規化し直す)。
買い方= D の時点で r の区分に入る組を 1 組 1 単位ずつ。払戻= 当たれば 確定行の倍率(確定の 3連単の倍率)、外れは 0。回収率= 払戻の和÷組数。
  ※D の時点で見えるのは D の倍率だけ。払戻は確定の倍率なので、D 以後に入る票の影響は払戻側に正しく入る。
着順は nar_runs の finish。1・2・3 着が 1 頭ずつに決まらないレース/確定行なし/D または E の行なし は除外。
区分= r の6つ × D の倍率帯の4つ。前半(9/8〜9/27)・後半(9/28〜10/19)にも分ける。
"""
import datetime as dt
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import rkey, ts, JST, log  # noqa: E402
from trifecta_winner_late import fetch, get_combos, top3, shares, BANDS, band  # noqa: E402

D_FROM, D_TO, D_SPLIT = dt.date(2026, 9, 8), dt.date(2026, 10, 19), dt.date(2026, 9, 28)
RB = ((0, 0.8, "0.8 未満"), (0.8, 1.0, "0.8〜1.0"), (1.0, 1.2, "1.0〜1.2"), (1.2, 1.5, "1.2〜1.5"),
      (1.5, 2.0, "1.5〜2.0"), (2.0, 1e18, "2.0 以上"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "trifecta-surge-return", "result.md")


def pick(full):
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
        pre = [r for r in rows if not r.get("f") and r["id"] < fin["id"] and ts(r["observed_at"]) is not None]
        d = [r for r in pre if ft - dt.timedelta(minutes=7) <= ts(r["observed_at"]) <= ft - dt.timedelta(minutes=2)]
        if not d:
            continue
        drow = max(d, key=lambda r: ts(r["observed_at"]))
        dt_ = ts(drow["observed_at"])
        e = [r for r in pre if dt_ - dt.timedelta(minutes=13) <= ts(r["observed_at"]) <= dt_ - dt.timedelta(minutes=8)]
        if not e:
            continue
        out[k] = (fin["id"], drow["id"], max(e, key=lambda r: ts(r["observed_at"]))["id"])
    return out


def cell():
    return [0, 0, 0.0]  # 組数, 的中, 払戻の和


def rband(r):
    for lo, hi, lab in RB:
        if lo <= r < hi:
            return lab
    return RB[-1][2]


def main():
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    G = {}   # (半期, 伸び区分, 倍率帯) → cell
    ex = {"days": 0, "races": 0, "used": 0, "x_fin": 0, "x_hit": 0}
    day = D_FROM
    while day <= D_TO:
        ds = day.isoformat()
        half = "前半" if day < D_SPLIT else "後半"
        day += dt.timedelta(days=1)
        runs, full = fetch(base, key, ds)
        if not full:
            continue
        ex["days"] += 1
        t3, pk = top3(runs), pick(full)
        need = set()
        for k, ids in pk.items():
            if k in t3:
                need.update(ids)
        cb = get_combos(base, key, need)
        for k, (fid, did, eid) in pk.items():
            ex["races"] += 1
            if k not in t3:
                ex["x_fin"] += 1
                continue
            fs, ds_, es = shares(cb.get(fid)), shares(cb.get(did)), shares(cb.get(eid))
            win = t3[k]
            if win not in fs:
                ex["x_hit"] += 1
                continue
            keys = [c for c in ds_ if c in es]
            sd = sum(ds_[c][1] for c in keys)
            se = sum(es[c][1] for c in keys)
            if not keys or sd <= 0 or se <= 0:
                continue
            ex["used"] += 1
            for c in keys:
                r = (ds_[c][1] / sd) / (es[c][1] / se)
                cells = (G.setdefault((half, rband(r), band(ds_[c][0])), cell()),
                         G.setdefault(("全期間", rband(r), band(ds_[c][0])), cell()))
                for cc in cells:
                    cc[0] += 1
                    if c == win:
                        cc[1] += 1
                        cc[2] += fs[win][0]
        log("  %s 済み(使えたレース %d)" % (ds, ex["used"]))
    write(G, ex)


def fmt(c):
    if not c or not c[0]:
        return "-"
    return "%.1f%%(%d/%s)" % (c[2] / c[0] * 100, c[1], "{:,}".format(c[0]))


def write(G, ex):
    L = ["# 締め切り前に見える「直前の伸び」が大きい 3連単の組を買うと(研究・1 回きり)", "",
         "期間 %s〜%s。作成 %s。" % (D_FROM, D_TO, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "- 記録のある日 %d・レース %d・使えたレース %d・除外 着順が 1 頭ずつでない %d・確定行に当たり組なし %d" % (ex["days"], ex["races"], ex["used"], ex["x_fin"], ex["x_hit"]), "",
         "買う時点= 確定の 2 分前以前の最後の記録。伸び= その時点の売れ方 ÷ そこから 8 分前の売れ方(比)。"
         "回収率= 当たった組の確定倍率の和 ÷ 買った組数(1 組 1 単位)。かっこ内= 的中数/買った組数。"
         "控除があるので、全部を均等に買うと 100% より下に落ちる(下の「全区分」が目安)。", ""]
    for half in ("全期間", "前半", "後半"):
        L += ["## %s" % half, "", "| 伸びの区分 | " + " | ".join(b[2] for b in BANDS) + " | 全倍率 |",
              "|---|" + "---:|" * (len(BANDS) + 1)]
        for _, _, rl in RB:
            row, tot = [], cell()
            for _, _, bl in BANDS:
                c = G.get((half, rl, bl))
                row.append(fmt(c))
                if c:
                    tot = [tot[0] + c[0], tot[1] + c[1], tot[2] + c[2]]
            L.append("| %s | %s | %s |" % (rl, " | ".join(row), fmt(tot)))
        allr = cell()
        bandtot = []
        for _, _, bl in BANDS:
            t = cell()
            for _, _, rl in RB:
                c = G.get((half, rl, bl))
                if c:
                    t = [t[0] + c[0], t[1] + c[1], t[2] + c[2]]
            bandtot.append(t)
            allr = [allr[0] + t[0], allr[1] + t[1], allr[2] + t[2]]
        L.append("| 全区分 | %s | %s |" % (" | ".join(fmt(t) for t in bandtot), fmt(allr)))
        L.append("")
    L += ["> 1 か月半。長い穴の組は的中数が少なく、回収率は 1 回の大当たりで大きく動く。的中数が 30 未満の欄は読まない。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

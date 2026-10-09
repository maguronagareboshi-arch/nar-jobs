# -*- coding: utf-8 -*-
"""研究用・1 回きり: 締め切り前に「見える」票の動きで、最後に売れた馬の回収率を見る。
便 .github/workflows/late-money-preclose.yml(workflow_dispatch のみ)から走らせ、docs/late-money-preclose/result.md を書く。

⛔本番 DB では REST の単純 select だけ(取得関数は late_money.py を流用)。集計は全部ここ。書き込みなし。
定義:
  fm= 単勝の確定行(f=true の最大 id)の t(分)。発走 ±10 分のレースだけ。
  V= asof(無ければ t)が fm-2 分以下の最後の途中行。B= asof が V-5〜V-3 分の最後の途中行。無いレースは除外。
  信号= V の正規化確率 ÷ B の正規化確率 >= 閾値(1/倍率をレース内で合計 1・確定/V/B の 3 つに数値がある馬だけ)。
  3連単(9/8〜)= observed_at で V(fm-2 分以下の最後)・B(V の 5〜3 分前の最後)を取り、その馬が 1 着の組の和で同様。
  見込み= 確定オッズの正規化確率の和。回収率= 単勝 100 円ずつ・確定単勝倍率で。
  参考(締め切り後)= late_money と同じ(V= 確定直前の途中行・gap<=4・3連単は pick_full)。
"""
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from late_money import (req, rows_by_id, rows_offset, hm, ts, num, rkey, pick_full, first_share,  # noqa: E402
                        COMBO_CHUNK, JST, log)
import urllib.parse  # noqa: E402

D_FROM, D_TO, D3_FROM = dt.date(2026, 9, 2), dt.date(2026, 9, 30), dt.date(2026, 9, 8)
THS = (1.2, 1.3, 1.5)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "late-money-preclose", "result.md")


def fetch(base, key, day, with3):
    d = urllib.parse.quote(day)
    races = rows_offset(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,post_time"
                        "&race_date=eq.%s&order=track.asc,race_no.asc" % d)
    runs = rows_offset(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,finish"
                       "&race_date=eq.%s&order=track.asc,race_no.asc,runner_number.asc" % d)
    win = rows_by_id(base, key, "/rest/v1/nar_odds_ticks?select=id,track,race_date,race_no,t,asof,f,w"
                     "&race_date=eq.%s" % d)
    full = []
    if with3:
        full = rows_by_id(base, key, "/rest/v1/nar_odds_full_ticks?select=id,track,race_date,race_no,kind,observed_at,f,h"
                          "&race_date=eq.%s&kind=eq.sanrentan" % d)
    return races, runs, win, full


def get_combos(base, key, ids, cache):
    ids = sorted(set(i for i in ids if i not in cache))
    for i in range(0, len(ids), COMBO_CHUNK):
        part = ids[i:i + COMBO_CHUNK]
        for r in req(base, key, "/rest/v1/nar_odds_full_ticks?select=id,combos&id=in.(%s)"
                     % ",".join(str(x) for x in part)):
            cache[r["id"]] = r["combos"]


def amin(r):
    return hm(r.get("asof")) if r.get("asof") else hm(r.get("t"))


def norm(w, hs):
    s = sum(1.0 / num(w[h]) for h in hs)
    return {h: (1.0 / num(w[h])) / s for h in hs}


def cell():
    return {"n": 0, "win": 0, "exp": 0.0, "ret": 0.0, "races": set()}


def add(c, v, rid):
    c["n"] += 1
    c["win"] += v["won"]
    c["exp"] += v["pf"]
    c["ret"] += v["won"] * v["fo"] * 100
    c["races"].add(rid)


def pick3_pre(rows, fm_dt):
    """3連単の (V id, B id)。無ければ None。"""
    mids = []
    for r in rows:
        if r.get("f"):
            continue
        t = ts(r["observed_at"])
        if t is not None:
            mids.append((t, r["id"]))
    v = [x for x in mids if x[0] < fm_dt - dt.timedelta(minutes=1)]
    if not v:
        return None
    vt, vid = max(v)
    b = [x for x in mids if vt - dt.timedelta(minutes=5) <= x[0] <= vt - dt.timedelta(minutes=3)]
    if not b:
        return None
    return vid, max(b)[1]


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    pre = {th: {k: cell() for k in ("sig", "sig7", "both", "ctrl", "all")} for th in THS}
    post = {th: {k: cell() for k in ("sig", "both")} for th in THS}
    ex = {"races_ok": 0, "noV": 0, "noB": 0, "used": 0, "r3_used": 0, "r3_none": 0, "post_used": 0}
    d = D_FROM
    while d <= D_TO:
        day = d.isoformat()
        with3 = d >= D3_FROM
        races, runs, win, full = fetch(base, key, day, with3)
        post_t = {rkey(r): hm(r.get("post_time")) for r in races}
        fin_of = {}
        for r in runs:
            try:
                fin_of.setdefault(rkey(r), {})[str(r["runner_number"])] = int(str(r.get("finish")).strip())
            except (TypeError, ValueError):
                continue
        wins, f3 = {}, {}
        for r in win:
            wins.setdefault(rkey(r), []).append(r)
        for r in full:
            f3.setdefault(rkey(r), []).append(r)
        pf_pick = pick_full(full) if with3 else {}
        cache, todo = {}, []
        n_before = ex["used"]
        for rk_, rows in sorted(wins.items()):
            fins = [r for r in rows if r.get("f")]
            if not fins or rk_ not in fin_of:
                continue
            fin = max(fins, key=lambda r: r["id"])
            fm, pm = hm(fin.get("t")), post_t.get(rk_)
            if fm is None or pm is None or abs(fm - pm) > 10:
                continue
            ex["races_ok"] += 1
            fw = fin.get("w") or {}
            fo = fin_of[rk_]
            rid = "%s|%s|%d" % rk_
            mids = [r for r in rows if not r.get("f") and amin(r) is not None]
            # ---- 締め切り前に見える定義
            vs = [r for r in mids if amin(r) <= fm - 2]
            item = None
            if not vs:
                ex["noV"] += 1
            else:
                V = max(vs, key=lambda r: (amin(r), r["id"]))
                va = amin(V)
                bs = [r for r in mids if va - 5 <= amin(r) <= va - 3]
                if not bs:
                    ex["noB"] += 1
                else:
                    B = max(bs, key=lambda r: (amin(r), r["id"]))
                    vw, bw = V.get("w") or {}, B.get("w") or {}
                    hs = [h for h in fw if num(fw[h]) and num(vw.get(h)) and num(bw.get(h))]
                    if hs:
                        pf, pv, pb = norm(fw, hs), norm(vw, hs), norm(bw, hs)
                        vod = {h: num(vw[h]) for h in hs}
                        hz = {}
                        for h in hs:
                            if h not in fo:
                                continue
                            hz[h] = {"pf": pf[h], "r": pv[h] / pb[h], "fo": num(fw[h]), "won": 1 if fo[h] == 1 else 0,
                                     "rk": 1 + sum(1 for x in hs if vod[x] < vod[h])}
                        if hz:
                            ex["used"] += 1
                            fm_dt = dt.datetime(d.year, d.month, d.day, fm // 60, fm % 60, tzinfo=JST)
                            p3 = pick3_pre(f3.get(rk_, []), fm_dt) if with3 else None
                            item = (rid, hz, p3)
            # ---- 参考: 締め切り後(late_money と同じ)
            pitem = None
            pm_ = [r for r in rows if not r.get("f") and (r.get("w") or {}) != fw]
            if pm_:
                mid = max(pm_, key=lambda r: r["id"])
                am = amin(mid)
                if am is not None and fm - am <= 4:
                    lw = mid.get("w") or {}
                    hs = [h for h in fw if num(fw[h]) and num(lw.get(h))]
                    if hs:
                        pf, pl = norm(fw, hs), norm(lw, hs)
                        hz = {h: {"pf": pf[h], "r": pf[h] / pl[h], "fo": num(fw[h]), "won": 1 if fo[h] == 1 else 0}
                              for h in hs if h in fo}
                        if hz:
                            ex["post_used"] += 1
                            pitem = (rid, hz, pf_pick.get(rk_ + ("sanrentan",)))
            if item:
                todo.append(("pre", item))
                if item[2]:
                    get_combos(base, key, item[2], cache)
            if pitem:
                todo.append(("post", pitem))
                if pitem[2]:
                    get_combos(base, key, pitem[2], cache)
        for kind, (rid, hz, p3) in todo:
            sh = None
            if p3 and p3[0] in cache and p3[1] in cache:
                sh = (first_share(cache[p3[0]]), first_share(cache[p3[1]]))
            if kind == "pre":
                if with3:
                    ex["r3_used" if sh else "r3_none"] += 1
                for th in THS:
                    c = pre[th]
                    for h, v in hz.items():
                        add(c["all"], v, rid)
                        s = v["r"] >= th
                        add(c["sig" if s else "ctrl"], v, rid)
                        if s and v["rk"] >= 7:
                            add(c["sig7"], v, rid)
                        if s and sh:
                            a, b = sh[0].get(h, 0.0), sh[1].get(h, 0.0)
                            if a > 0 and b > 0 and a / b >= th:
                                add(c["both"], v, rid)
            else:
                # 参考は late_money と同じく 3 連単は 確定/途中(pick_full の順)
                for th in THS:
                    c = post[th]
                    for h, v in hz.items():
                        if v["r"] >= th:
                            add(c["sig"], v, rid)
                            if sh:
                                a, b = sh[0].get(h, 0.0), sh[1].get(h, 0.0)
                                if a > 0 and b > 0 and a / b >= th:
                                    add(c["both"], v, rid)
        log("%s 単勝 %d 行・3連単 %d 行・組 %d 件 → %d レース" % (day, len(win), len(full), len(cache), ex["used"] - n_before))
        d += dt.timedelta(days=1)
    write(pre, post, ex)


def row(lab, c):
    r = "%.2f" % (c["win"] / c["exp"]) if c["exp"] > 0 else "-"
    roi = "%.1f%%" % (c["ret"] / c["n"]) if c["n"] else "-"
    return "| %s | %d | %d | %.1f | %s | %s | %d |" % (lab, c["n"], c["win"], c["exp"], r, roi, len(c["races"]))


HEAD = "| 区分 | 頭数 | 1着数 | 見込み | 実際÷見込み | 単勝回収率 | レース数 |\n|---|---:|---:|---:|---:|---:|---:|"


def write(pre, post, ex):
    L = ["# 締め切り前に見える票の動き(研究・1 回きり)", "",
         "期間 %s〜%s(3連単は %s〜)。作成 %s。" % (D_FROM, D_TO, D3_FROM, dt.datetime.now(JST).isoformat(timespec="seconds")), "",
         "- 対象レース(発走 ±10 分)%d・使えた %d・除外 V なし %d・B なし %d" % (ex["races_ok"], ex["used"], ex["noV"], ex["noB"]),
         "- 3連単(9/8〜)V・B あり %d レース・なし %d レース" % (ex["r3_used"], ex["r3_none"]),
         "- 参考(締め切り後の定義)使えた %d レース" % ex["post_used"], "",
         "## 締め切り前(閾値 1.3)", "", HEAD]
    c = pre[1.3]
    for k, lab in (("sig", "単勝信号あり"), ("sig7", "うち 7 番人気以下(V の順位)"), ("both", "単勝×3連単 両方"),
                   ("ctrl", "対照= 信号なし"), ("all", "全馬一律")):
        L.append(row(lab, c[k]))
    L += ["", "## 閾値を変えた場合(締め切り前)", "", HEAD]
    for th in (1.2, 1.5):
        L.append(row("%.1f 単勝信号あり" % th, pre[th]["sig"]))
        L.append(row("%.1f 両方" % th, pre[th]["both"]))
    L += ["", "## 参考= 締め切り後の定義(late_money と同じ・V= 確定直前の途中行)", "", HEAD]
    for th in THS:
        L.append(row("%.1f 単勝信号あり" % th, post[th]["sig"]))
        L.append(row("%.1f 両方" % th, post[th]["both"]))
    L += ["", "> 見込み= 確定オッズの正規化確率の和。回収率= 単勝 100 円ずつ・確定単勝倍率。1 か月だけなので結論にしない。", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

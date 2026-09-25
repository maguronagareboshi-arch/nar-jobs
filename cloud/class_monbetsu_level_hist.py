# -*- coding: utf-8 -*-
"""§285-F 門別の過去レース(令和8年度)に「発走前の番組賞金と級」を出す(表 nar_monbetsu_level_hist)。

  各レース日 D: asof < D の最新の公式回 K を起点(馬ごとに第1〜K回で最後に載った回)にし、
  その回の締めより後〜D の前日の走を class_monbetsu_calc の加算(要領 第7)で足す。
  照合: 回 N(2〜13)の締め直後の門別開催日で、起点 N-1 回+加算を公式 N 回と全頭照合する(check.json)。

  python cloud/class_monbetsu.py --env <path> --backfill --out <kais>           # 第1〜最新回の JSON(書かない)
  python cloud/class_monbetsu_level_hist.py --env <path> --kais <kais> --out <dir>           # 読むだけ・CSV
  python cloud/class_monbetsu_level_hist.py --env <path> --kais <kais> --out <dir> --apply   # 表へ upsert
⛔本番 DB は PostgREST の軽い SELECT だけ(--apply 以外は書かない)。DDL= pipeline/sql/monbetsu_level_hist_20260925.sql
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import class_monbetsu as CM          # noqa: E402
import class_monbetsu_calc as CC     # noqa: E402

TABLE = "nar_monbetsu_level_hist"
TRACK = "門別"
MAN = CC.MAN
COLS = ["race_date", "race_no", "horse_name", "prize_yen", "kaku", "kai", "calc"]


def kais_of(official, hist):
    """→ {回: {"asof","asof_by","horses"}}(hist + 最新回)"""
    ks = {}
    if hist and hist.get("fy") == official["fy"]:
        for k, v in (hist.get("kais") or {}).items():
            ks[int(k)] = v
    ks[int(official["kai"])] = {"asof": official["asof"], "asof_by": official.get("asof_by") or {},
                               "horses": official.get("horses") or {}}
    return dict(sorted(ks.items()))


def bases_by_kai(kais):
    """→ {回: その回までの起点}(馬ごとに最後に載った回)"""
    out, bases = {}, {}
    for k, v in kais.items():
        CC.overlay(bases, v.get("horses") or {}, k, v["asof"][:4])
        out[k] = dict(bases)
    return out


def prev_day(d):
    return str(CC.D(d) - dt.timedelta(days=1))


def level(nm, b, cuts, upto, nar_by_name, jra_by_name, races, runners, fy):
    runs = CC.horse_runs(nm, b["by"], nar_by_name, jra_by_name)
    acc = CC.calc_one(b, cuts[b["kai"]], upto, runs, races, runners)
    prize = acc.val * MAN
    kaku = None
    cls = b.get("cls")
    if fy == CM.KAKUZUKE_FY and b["age"] not in (None, 2) and cls and CM.in_label("Ｃ４", cls) is not None:
        kaku = CM.kaku_of(prize)
    return prize, kaku, bool(acc.det)


def build(official, hist, mon_runs, nar, jra, races, date_from, date_to):
    """通信なしの本体 → (行, 照合)"""
    fy = official["fy"]
    kais = kais_of(official, hist)
    cuts = {k: CC.ipan_cut(fy, k, v["asof"], v.get("asof_by")) for k, v in kais.items()}
    bk = bases_by_kai(kais)
    nar_by_name = defaultdict(list)
    for r in nar:
        nar_by_name[r["horse_name"]].append(r)
    runners = CC.runners_of(nar)
    rows, seen = [], set()
    for r in mon_runs:
        d = r["race_date"]
        if not (date_from <= d <= date_to):
            continue
        ok = [k for k, v in kais.items() if v["asof"] < d]
        if not ok:
            continue
        b = bk[max(ok)].get(r["horse_name"])
        if not b:
            continue
        if r.get("birth_date") and int(r["birth_date"][:4]) != b["by"]:
            continue
        key = (d, r["race_no"], r["horse_name"])
        if key in seen:
            continue
        seen.add(key)
        prize, kaku, calc = level(r["horse_name"], b, cuts, prev_day(d), nar_by_name, jra, races, runners, fy)
        rows.append({"race_date": d, "race_no": r["race_no"], "horse_name": r["horse_name"],
                     "prize_yen": prize, "kaku": kaku, "kai": b["kai"], "calc": calc})
    mon_days = sorted({r["race_date"] for r in mon_runs})
    check = []
    for n in sorted(kais):
        if n - 1 not in bk:
            continue
        # 締め直後の門別開催日(範囲の外= 最新回なら締めの翌日で見る)
        d = next((x for x in mon_days if x > cuts[n]), None) or str(CC.D(cuts[n]) + dt.timedelta(days=1))
        tot = hit = 0
        miss = []
        for nm, h in sorted(kais[n]["horses"].items()):
            b = bk[n - 1].get(nm)
            if h.get("prize") is None or not b:
                continue
            p, _, _ = level(nm, b, cuts, prev_day(d), nar_by_name, jra, races, runners, fy)
            tot += 1
            if p == int(h["prize"]):
                hit += 1
            else:
                miss.append([nm, p, int(h["prize"])])
        check.append({"kai": n, "day": d, "n": tot, "match": hit, "n_miss": len(miss), "miss": miss[:5]})
    return rows, check


def load_kais(d):
    """kaiNN.json → hist の形 {"fy","kais":{回:{asof,asof_by,horses}}}"""
    kais, fy = {}, None
    for f in sorted(Path(d).glob("kai[0-9][0-9].json")):
        v = json.loads(f.read_text(encoding="utf-8"))
        fy = v["fy"]
        kais[str(v["kai"])] = {"asof": v["asof"], "asof_by": v.get("asof_by") or {}, "horses": v["horses"]}
    return {"fy": fy, "kais": kais}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--out", required=True, help="CSV と check.json の書き出し先")
    ap.add_argument("--from", dest="dfrom", default="2026-04-01")
    ap.add_argument("--to", dest="dto", default="2026-09-24")
    ap.add_argument("--kais", help="過去回の JSON(class_monbetsu.py --backfill --out の kaiNN.json)の置き場。"
                    f"無ければ nar_meta/{CM.HIST_KEY}")
    ap.add_argument("--apply", action="store_true", help=f"{TABLE} へ upsert(既定はドライラン)")
    a = ap.parse_args()
    if a.env:
        CM.load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        CM.log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    official = CM.sb_get_meta(base, key, CM.META_KEY)
    hist = load_kais(a.kais) if a.kais else CM.sb_get_meta(base, key, CM.HIST_KEY)
    if not official or not official.get("horses"):
        CM.log(f"{CM.META_KEY} が読めない")
        return 2
    mon = CC._get(base, key, "nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date"
                  f"&track=eq.{urllib.parse.quote(TRACK)}&race_date=gte.{a.dfrom}&race_date=lte.{a.dto}"
                  "&order=race_date,race_no,runner_number,horse_name")
    kais = kais_of(official, hist)
    names = {r["horse_name"] for r in mon}
    for v in kais.values():
        names |= {n for n, h in (v.get("horses") or {}).items() if h.get("prize") is not None}
    cut_min = min(CC.ipan_cut(official["fy"], k, v["asof"], v.get("asof_by")) for k, v in kais.items())
    nar, races, jra = CC.fetch(base, key, names, f"{official['fy']}-04-01", cut_min)
    rows, check = build(official, hist, mon, nar, jra, races, a.dfrom, a.dto)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{TABLE}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    (out / "check.json").write_text(json.dumps(check, ensure_ascii=False, indent=1), encoding="utf-8")
    tn = sum(c["n"] for c in check)
    tm = sum(c["match"] for c in check)
    CM.log(f"回 {list(kais)} / 門別の走 {len(mon)} / 行 {len(rows)} / 照合 {tm}/{tn} "
           + " ".join(f"第{c['kai']}回{c['match']}/{c['n']}" for c in check))
    if not a.apply:
        CM.log("ドライラン(書かない)")
        return 0
    for i in range(0, len(rows), 500):
        status, msg = CM.upsert(base, key, TABLE, "race_date,race_no,horse_name", rows[i:i + 500])
        if status not in (200, 201):
            CM.log(f"投入失敗 {status} {str(msg)[:150]}")
            return 1
    CM.log(f"{TABLE} へ {len(rows)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# 研究用・1 回きり(2026-11-04)。この日の時計の「組の差」表を本物のデータで出し、手元 SQL の値と照合する。
# ⛔読み取りだけ。DB にも公開バケットにも書かない。結果は artifact。
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baba  # noqa: E402


def table_for(rows_by_tr, ms):
    lo = (ms - dt.timedelta(days=baba.GRP_YEARS_DAYS)).isoformat()
    return {tr: baba.group_table(xs, lo, ms.isoformat()) for tr, xs in rows_by_tr.items()}


def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    out = sys.argv[1] if len(sys.argv) > 1 else "out/RESULT_grp_check.md"
    ms = dt.date(2026, 11, 1)
    since = (ms - dt.timedelta(days=baba.GRP_YEARS_DAYS)).isoformat()
    t0 = time.time()
    wins = baba.rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec"
                                    f"&finish=eq.1&time_sec=not.is.null&finish_note=is.null&race_date=gte.{since}"
                                    "&order=race_date.asc,track.asc,race_no.asc,finish.asc,runner_number.asc")
    races = baba.rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m,race_name,race_kind"
                                     f"&race_date=gte.{since}&order=race_date.asc,track.asc,race_no.asc")
    best = {}
    for w in wins:
        kk = (w["track"], w["race_date"], w["race_no"], 1)
        if kk not in best or float(w["time_sec"]) < float(best[kk]["time_sec"]):
            best[kk] = w
    meta = {(r["track"], r["race_date"], r["race_no"]): r for r in races}
    L = [f"# 組の差の表(本物・{ms} 月の表= {since}〜{ms} の前日)", "",
         f"1 着 {len(wins)} 行・レース {len(races)} 行・読み {time.time() - t0:.0f} 秒", ""]
    res = {}
    for ks in (False, True):
        baba.KISHA_SEPARATE = ks
        by_tr = {}
        for tr, d, _r, dist, c, b, t, _f in baba.race_rows_of(best, meta, []):
            if b and t is not None:
                by_tr.setdefault(tr, []).append((d, dist, c, b, t))
        res[ks] = table_for(by_tr, ms)
    tb = res[False]
    L += ["## 場ごと: 出る箱の数(レース数 15 以上・丸めて 0 でない)", "", "| 場 | 箱 | 出る箱 |", "|---|---:|---:|"]
    for tr in baba.TRACK2PREFIX:
        t = tb.get(tr, {})
        shown = [b for b, (v, n) in t.items() if n >= baba.GRP_MIN and round(v, 1) != 0]
        L.append(f"| {tr} | {len(t)} | {len(shown)} |")
    for tr in sorted(tb):
        L += ["", f"## {tr}", "", "| 級 | 箱 | 差(秒) | レース数 |", "|---|---|---:|---:|"]
        for (c, b), (v, n) in sorted(tb[tr].items(), key=lambda kv: (kv[0][0], kv[0][1])):
            L.append(f"| {c} | {b} | {v:+.2f} | {n} |")
    L += ["", "## 記者選抜を分けた場合(KISHA_SEPARATE=True)の選抜・記者選抜", "", "| 場 | 級 | 箱 | 差 | 数 |", "|---|---|---|---:|---:|"]
    for tr in sorted(res[True]):
        for (c, b), (v, n) in sorted(res[True][tr].items()):
            if b in ("選抜", "記者選抜"):
                L.append(f"| {tr} | {c} | {b} | {v:+.2f} | {n} |")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()

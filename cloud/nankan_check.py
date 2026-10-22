# -*- coding: utf-8 -*-
"""本体 cloud: 南関 4 場の出走予定馬の「格」「格付ポイント」の見張り(2026-10-23 浦和 7R の事故の再発防止)。

  python cloud/nankan_check.py --env pipeline/.env.nar     # 照合して結果を出すだけ
  python cloud/nankan_check.py --beat                      # 結果を nar_job_heartbeat(job= nankan_check)へ
見るもの(きょう〜--ahead 日先の南関の出馬表の全馬):
  ① 古さ= 表 nar_nankan_points の asof(主催者の「◯日現在」)が、レース日より前の最後の開催最終日(きょうより前に限る)より前。
     反映は開催最終日の全レース終了後= その翌朝の便(nankan_points ③b)で読み直しているはずの馬
  ② 抜け= 表に無い・格も点も無い(3 歳の未格付・転入直後もここ。数えるだけで赤にしない)
  ③ 級= 条件が単一の級のレース(選抜・特選を含む。選定・混合・重賞・準重賞・オープンは除く= nankan_hist.kaku_of_race)で、
     当サイトの規則(算定日= 前々開催の最終日の点 × 格付基準表・nankan_hist.kaku_by_points)で出した級 ≠ レースの級。
     算定日の点= 主催者の点 − 算定日より後〜asof までに反映された南関の走の着内ポイント(nankan_hist.run_points)。
     その間に南関の外の走(遠征)がある馬・着内ポイントが決まらない馬は数えない(推定しない)
  赤(fail)= ③のずれ 1 頭以上 / ①の古さが 2 日以上続いている(主催者が前日の最終日の反映をまだ出していないだけの朝は黄= 補足に書くだけ)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常(ずれがあっても)/ 2 読み取り失敗
"""
import argparse
import collections
import datetime as dt
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
import nankan_hist as NH                                    # noqa: E402
from nankan_hist import q, sb_all                           # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
JOB = "nankan_check"


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--ahead", type=int, default=3, help="きょう〜この日数先の出馬表を見る")
    ap.add_argument("--beat", action="store_true", help="結果を nar_job_heartbeat へ書く")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    today = dt.datetime.now(JST).date()
    today_s = today.isoformat()
    hi = (today + dt.timedelta(days=args.ahead)).isoformat()
    tracks = q(NH.NK)
    try:
        ents = sb_all(url, key, f"nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date"
                                f"&track=in.({tracks})&race_date=gte.{today_s}&race_date=lte.{hi}"
                                "&order=race_date,track,race_no,runner_number")
        races = {(r["track"], r["race_date"], int(r["race_no"])): r for r in sb_all(
            url, key, f"nar_races?select=track,race_date,race_no,race_name,race_kind,condition"
                      f"&track=in.({tracks})&race_date=gte.{today_s}&race_date=lte.{hi}&order=track,race_date,race_no")}
        lo = (today - dt.timedelta(days=150)).isoformat()
        dates = collections.defaultdict(set)
        for r in sb_all(url, key, f"nar_races?select=track,race_date&race_no=eq.1&track=in.({tracks})"
                                  f"&race_date=gte.{lo}&order=track,race_date"):
            dates[r["track"]].add(r["race_date"])
        idx = NH.meetings(dates)
        santei = NH.santei_index(idx)
        names = sorted({e["horse_name"] for e in ents})
        pts = collections.defaultdict(list)
        hist_runs = collections.defaultdict(list)
        since = (today - dt.timedelta(days=90)).isoformat()
        for ch in chunks(names, 40):
            for p in sb_all(url, key, f"nar_nankan_points?select=code,horse_name,kaku,points,asof,birth_date"
                                      f"&horse_name=in.({q(ch)})&order=code"):
                pts[p["horse_name"]].append(p)
            # 全場(遠征を見分けるため)。南関の走は着内ポイントを引く
            for r in sb_all(url, key, f"nar_runs?select=track,race_date,race_no,horse_name,birth_date,finish,finish_note"
                                      f"&horse_name=in.({q(ch)})&race_date=gte.{since}&race_date=lt.{today_s}"
                                      "&order=race_date,track,race_no,runner_number"):
                hist_runs[(r["horse_name"], r.get("birth_date"))].append(r)
        need = sorted({(r["track"], r["race_date"], int(r["race_no"])) for rs in hist_runs.values() for r in rs
                       if r["track"] in NH.NK and r["finish"] is not None and int(r["finish"]) <= 5})
        by_day = collections.defaultdict(set)
        for tr, d, _ in need:
            by_day[tr].add(d)
        past, tie = {}, collections.Counter()
        for tr, ds in by_day.items():
            for ch in chunks(sorted(ds), 60):
                for r in sb_all(url, key, f"nar_races?select=track,race_date,race_no,race_name,race_kind,condition,nankan,cancelled"
                                          f"&track=eq.{urllib.parse.quote(tr)}&race_date=in.({','.join(ch)})&order=race_date,race_no"):
                    past[(r["track"], r["race_date"], int(r["race_no"]))] = r
                for r in sb_all(url, key, f"nar_runs?select=race_date,race_no,finish&track=eq.{urllib.parse.quote(tr)}"
                                          f"&race_date=in.({','.join(ch)})&finish=lte.5&order=race_date,race_no,runner_number"):
                    tie[(tr, r["race_date"], int(r["race_no"]), int(r["finish"]))] += 1
    except Exception as e:
        log(f"DB の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2

    ends = sorted({v[0] for v in idx.values()})

    def last_end_before(d):
        return max((x for x in ends if x < d and x < today_s), default=None)

    yday = (today - dt.timedelta(days=1)).isoformat()
    n = stale = stale_old = missing = ambiguous = checked = ok = skipped = 0
    ng, stale_list = [], []
    for e in ents:
        n += 1
        tr, d, no = e["track"], e["race_date"], int(e["race_no"])
        cand = [p for p in pts.get(e["horse_name"], []) if not e.get("birth_date") or p.get("birth_date") in (None, e["birth_date"])]
        if len(cand) > 1:
            ambiguous += 1
            continue
        p = cand[0] if cand else None
        if not p or (p.get("points") is None and not p.get("kaku")):
            missing += 1
            continue
        need_end = last_end_before(d)
        if need_end and (p.get("asof") or "") < need_end:
            stale += 1
            stale_old += need_end < yday               # 前日の最終日より前の反映が入っていない= 読み直しの段が回っていない
            stale_list.append(f"{d} {tr}{no}R {e['horse_name']} {p.get('asof')}現在(要 {need_end} 以後)")
            continue
        race = races.get((tr, d, no)) or {}
        want = NH.kaku_of_race(race.get("race_name"), race.get("race_kind"))
        st, meet = santei.get((tr, d)), (idx.get((tr, d)) or (None, None))[1]
        if not want or not st or p.get("points") is None or not p.get("birth_date"):
            continue
        # 算定日より後〜asof までに反映された走を引く(反映= その走の開催の最終日)
        sub, unsure = 0.0, None
        for r in hist_runs.get((e["horse_name"], e.get("birth_date")), []):
            if r["track"] not in NH.NK:
                if st < r["race_date"] <= p["asof"]:
                    unsure = "遠征"
                continue
            refl = (idx.get((r["track"], r["race_date"])) or (None,))[0]
            if not refl or not (st < refl <= p["asof"]):
                continue
            fin = r["finish"]
            v, src = NH.run_points({"fin": int(fin) if fin is not None else None, "note": r.get("finish_note")},
                                   past.get((r["track"], r["race_date"], int(r["race_no"]))),
                                   tie.get((r["track"], r["race_date"], int(r["race_no"]), int(fin))) if fin is not None else 1)
            if v is None:
                unsure = src
                continue
            sub += v
        if unsure:
            skipped += 1
            continue
        got = NH.kaku_by_points(p["points"] - sub, st, int(p["birth_date"][:4]), meet)
        checked += 1
        if got == want:
            ok += 1
        else:
            ng.append(f"{d} {tr}{no}R {e['horse_name']} レース {want} / 当サイトの規則 {got}"
                      f"(主催者 {p.get('kaku')} {p['points']}点 {p['asof']}現在・算定日 {st} の点 {p['points'] - sub:g})")

    log(f"出走予定 {n} 頭(〜{hi})・古い {stale}(うち 2 日以上 {stale_old})・抜け {missing}・同名で決められない {ambiguous}")
    log(f"級の照合 {ok}/{checked} 一致・数えない(遠征・点が決まらない) {skipped}")
    for s in stale_list[:30]:
        log("  古い: " + s)
    for s in ng[:30]:
        log("  級のずれ: " + s)
    bad = bool(ng) or stale_old > 0
    note = (f"出走予定{n}頭・古い{stale}" + (f"(2日以上{stale_old})" if stale_old else "") +
            f"・級{ok}/{checked}一致" + (f"・ずれ{len(ng)}" if ng else ""))
    if args.beat:
        subprocess.run([sys.executable, str(HERE / "beat.py"), JOB, "fail" if bad else "ok", note], check=False)
    log(("✗ " if bad else "✓ ") + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())

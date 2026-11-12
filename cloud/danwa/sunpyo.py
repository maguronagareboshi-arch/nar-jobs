# -*- coding: utf-8 -*-
"""寸評の本番(2026-11-12)。nar_danwa_note の sunpyo / sunpyo_status / sunpyo_at だけを書く。

  python cloud/danwa/sunpyo.py [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--redo] [--dry-run] [--limit N]

中身は試し cloud/danwa/sunpyo_trial.py(a0351d6)の「low」(output_config.effort=low・adaptive)をそのまま使う
(指示文・入力の作り方・着順は nar_runs の finish・写し検査・禁止語/見込みの言葉の検査と作り直し 1 回)。
対象= 期間内で para がある行のうち、sunpyo が空の行(--redo なら全部)。
当日の話が無い・前の話が 2 件未満(horse_id 無しを含む)は sunpyo_status='skip'。作れなかったら 'failed'(sunpyo は空)。
送る列は race_id・umaban・sunpyo・sunpyo_status・sunpyo_at だけ(para・tags・status・updated_at は送らない)。
⛔公開 repo= ログには件数と状態だけ(文・原文を出さない)。
例外で落ちても exit 0(取得の便全体を赤にしない)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / ANTHROPIC_API_KEY
"""
import argparse
import collections
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import threading
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import danwa_para as D                           # noqa: E402
import sunpyo_trial as S                         # noqa: E402  指示文・検査・着順の付け方は試しと同じ

MODE = "low"
KW = S.MODES[MODE]
WORKERS = 4


def q(v):
    return S.q(v)


def skip_reason(today, past):
    """skip の条件 → 理由(None= 作る)。当日の話が無い・前の話が 2 件未満。"""
    if not today or not (today.get("para") or "").strip():
        return "当日の話なし"
    if len(past) < S.MIN_TALKS:
        return "前の話不足"
    return None


def out_row(r, sunpyo, status, now):
    """書く行(寸評の列だけ)。"""
    return {"race_id": r["race_id"], "umaban": int(r["umaban"]),
            "sunpyo": sunpyo or None, "sunpyo_status": status, "sunpyo_at": now}


def one(db, cl, r, src, st, lock):
    """1 頭分 → 書く行。"""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    date = r["race_date"]
    hid = r.get("horse_id")
    past = []
    if hid:
        rows = db.get(f"{D.DST}?select=race_id,umaban,race_date,para,tags&horse_id=eq.{q(hid)}"
                      f"&race_date=lt.{date}&para=not.is.null"
                      f"&order=race_date.desc,race_id.desc&limit={S.MAX_TALKS + 3}")
        past = [t for t in rows if (t.get("para") or "").strip()][:S.MAX_TALKS]
    why = skip_reason(r, past)
    if why:
        with lock:
            st["skip"] += 1
            st["skip_" + why] += 1
        return out_row(r, None, "skip", now)
    ids = sorted({t["race_id"] for t in past + [r]})
    cm, trk = {}, {}
    for x in db.get(f"{D.SRC}?select=race_id,umaban,track,comment&race_id=in.({','.join(q(i) for i in ids)})&limit=1000"):
        cm[(x["race_id"], int(x["umaban"]))] = x.get("comment") or ""
        trk.setdefault(x["race_id"], {"track": x.get("track")})
    comments = [cm.get((t["race_id"], int(t["umaban"])), "") for t in past + [r]]
    comments = [c for c in comments if c.strip()]
    name = (src.get((r["race_id"], int(r["umaban"]))) or {}).get("horse_name")
    S.attach_finish(db, name, date, past, trk)
    loc = collections.Counter()
    s, status, _rt, _hi, _ho = S.make(cl, KW, past, r, comments, loc, MODE, f"{r['race_id']}-{r['umaban']}")
    with lock:
        st.update(loc)
        st["fin_known"] += sum(1 for t in past if t.get("fin") and t["fin"] != "不明")
        st["fin_all"] += len(past)
    return out_row(r, s if status == "ok" else None, status, now)


def run(a, env, cl=None, db=None):
    today = dt.datetime.now(D.JST).date()
    d0 = dt.date.fromisoformat(a.date_from) if a.date_from else today - dt.timedelta(days=1)
    d1 = dt.date.fromisoformat(a.date_to) if a.date_to else today + dt.timedelta(days=1)
    db = db or D.Rest(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])
    if cl is None:
        import anthropic
        cl = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
    st = collections.Counter()
    lock = threading.Lock()
    for m0, m1 in D.months(d0, d1):
        rows = db.get_all(D.DST, "race_id,umaban,race_date,horse_id,para,sunpyo", m0, m1, "&para=not.is.null")
        tg = [r for r in rows if (r.get("para") or "").strip() and (a.redo or not (r.get("sunpyo") or "").strip())]
        if a.limit:
            tg = tg[:max(0, a.limit - st["target"])]
        st["target"] += len(tg)
        if not tg:
            print(f"{m0}〜{m1}: para {len(rows)}・対象 0", flush=True)
            continue
        src = {}
        for x in db.get_all(D.SRC, "race_id,umaban,horse_name", m0, m1):
            src[(x["race_id"], int(x["umaban"]))] = x
        out = []
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            for f in [ex.submit(one, db, cl, r, src, st, lock) for r in tg]:
                try:
                    out.append(f.result())
                except Exception as e:           # noqa: BLE001  1 頭の DB 読み失敗は飛ばす(次の便で作り直す)
                    st["error"] += 1
                    print(f"  ⚠読み {type(e).__name__}", flush=True)
        if out and not a.dry_run:
            db.upsert(D.DST, out, "race_id,umaban")
            st["written"] += len(out)
        c = collections.Counter(o["sunpyo_status"] for o in out)
        print(f"{m0}〜{m1}: 対象 {len(tg)}・ok {c['ok']}・failed {c['failed']}・skip {c['skip']}"
              f"・書き {0 if a.dry_run else len(out)}", flush=True)
    return st


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", help="YYYY-MM-DD(既定= 今日-1)")
    ap.add_argument("--to", dest="date_to", help="YYYY-MM-DD(既定= 今日+1)")
    ap.add_argument("--redo", action="store_true", help="sunpyo がある行も作り直す")
    ap.add_argument("--dry-run", action="store_true", help="書かない(API は呼ぶ)")
    ap.add_argument("--limit", type=int, help="対象の行をここまで")
    ap.add_argument("--env", help="SUPABASE_* / ANTHROPIC_API_KEY のある .env")
    a = ap.parse_args(argv)
    env = D.load_env(a.env)
    try:
        st = run(a, env)
    except Exception:                            # noqa: BLE001
        traceback.print_exc()
        return 0                                 # ⛔取得の便全体を赤にしない
    print(f"集計 対象 {st['target']}・ok {st[MODE + '_ok']}・failed {st[MODE + '_failed']}・skip {st['skip']}"
          f"(当日の話なし {st['skip_当日の話なし']}・前の話不足 {st['skip_前の話不足']})"
          f"・作り直し {st[MODE + '_retry']}・読み失敗 {st['error']}・書き {st['written']}"
          f"・着順あり {st['fin_known']}/{st['fin_all']}", flush=True)
    print(f"トークン 入力 {st[MODE + '_in']}・出力 {st[MODE + '_out']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

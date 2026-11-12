# -*- coding: utf-8 -*-
"""厩舎の話の札: 今の語句ルール(tags.py)と Haiku の選択を 200 頭前後で比べる材料(2026-11-12・試し・書き込みなし)。

  python cloud/danwa/tag_trial.py [--n 200] [--seed 20261112]
  python cloud/danwa/tag_trial.py --ids cloud/danwa/trial_ids_20261112.txt
    (各行 race_id-umaban。レースごとに全頭を 1 回の呼び出しに入れ、ids の頭だけ
     race_id<TAB>umaban<TAB>今の札(nar_danwa_note)<TAB>新しい札(merge_tags・病気込み) を出す)

nar_kb_danwa(2025-11-10〜2026-11-11)から日をランダムに選び、その日の 1 レースの全頭(comment あり)を
1 回の呼び出しに入れる(danwa_para と同じ形)。200 頭前後になるまでレースを足す。
⛔公開 repo= 原文はログに出さない。出すのは
  race_id<TAB>umaban<TAB>今の札(・区切り)<TAB>Haiku の札(・区切り)
の行と、最後の合計トークン数だけ。DB には書かない(読むだけ)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / ANTHROPIC_API_KEY
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tags as T                                 # noqa: E402
import danwa_para as D                           # noqa: E402

D0, D1 = dt.date(2025, 11, 10), dt.date(2026, 11, 11)

# 札の短い定義・一覧・決まりは tags.py に移した(11/12・毎日の便と同じものを使う)
DEF = T.HK_DEF
LIST = T.HK_LIST

SYSTEM = D.TAG_SYSTEM


def user_prompt(horses):
    body = [{"umaban": h["umaban"], "comment": h["comment"]} for h in horses]
    return "次の各馬の談話に札を付けてください。\n" + json.dumps(body, ensure_ascii=False)


def parse_tags(text):
    """返事 → {umaban: [札, ...]}(一覧の順・一覧に無い札は捨てる)。読めなければ {}。"""
    return {u: t for u, t in D.tags_from(D.parse_obj(text)).items()}


def call_race(cl, hs):
    """1 レース分を 1 回の呼び出しで → ({umaban: [札]}, 入力, 出力)。"""
    try:
        res = cl.messages.create(model=D.MODEL, max_tokens=D.MAX_TOKENS, system=SYSTEM,
                                 messages=[{"role": "user", "content": user_prompt(hs)}])
        tin = getattr(res.usage, "input_tokens", 0) or 0
        tout = getattr(res.usage, "output_tokens", 0) or 0
        if res.stop_reason != "end_turn":
            print(f"  ⚠stop={res.stop_reason}", flush=True)
        return parse_tags("".join(getattr(b, "text", "") for b in res.content)), tin, tout
    except Exception as e:                       # noqa: BLE001
        print(f"  ⚠API {type(e).__name__}", flush=True)
        return {}, 0, 0


def read_ids(path):
    """ファイルの各行 race_id-umaban → {race_id: [umaban, ...]}(行の順・重なりなし)。"""
    want = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rid, u = line.rsplit("-", 1)
        if int(u) not in want.setdefault(rid, []):
            want[rid].append(int(u))
    return want


def run_ids(a, db, cl):
    want = read_ids(a.ids)
    tin = tout = n = races = 0
    for rid, us in want.items():
        q = urllib.parse.quote(rid, safe="")
        rows = db.get(f"{D.SRC}?select=race_id,umaban,comment&race_id=eq.{q}"
                      f"&comment=not.is.null&order=umaban.asc&limit=100")
        hs = [dict(r, umaban=int(r["umaban"])) for r in rows if (r.get("comment") or "").strip()]
        have = {int(h["umaban"]): (h.get("tags") or [])
                for h in db.get(f"{D.DST}?select=umaban,tags&race_id=eq.{q}&limit=100")}
        if not hs:
            for u in us:
                print(f"{rid}	{u}	{'・'.join(have.get(u, []))}	(原文なし)", flush=True)
                n += 1
            continue
        got, i, o = call_race(cl, hs)
        tin += i
        tout += o
        races += 1
        by = {h["umaban"]: h for h in hs}
        for u in us:
            old = '・'.join(have.get(u, []))
            if u not in by:
                new = "(原文なし)"
            elif u not in got:
                new = "(返事なし)"
            else:
                new = '・'.join(T.merge_tags(got[u], by[u]["comment"]))
            print(f"{rid}	{u}	{old}	{new}", flush=True)
            n += 1
    print(f"合計 頭数 {n}・レース {races}・入力トークン {tin}・出力トークン {tout}", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261112)
    ap.add_argument("--ids", default="")
    a = ap.parse_args()
    env = os.environ
    db = D.Rest(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])
    import anthropic
    cl = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
    if a.ids:
        return run_ids(a, db, cl)
    rnd = random.Random(a.seed)
    days = [D0 + dt.timedelta(days=i) for i in range((D1 - D0).days + 1)]
    rnd.shuffle(days)
    tin = tout = n = races = 0
    for d in days:
        if n >= a.n:
            break
        rows = db.get(f"{D.SRC}?select=race_id,umaban,comment&race_date=eq.{d.isoformat()}"
                      f"&comment=not.is.null&order=race_id.asc,umaban.asc&limit=1000")
        by = {}
        for r in rows:
            if (r.get("comment") or "").strip():
                by.setdefault(r["race_id"], []).append(dict(r, umaban=int(r["umaban"])))
        if not by:
            continue
        rid = rnd.choice(sorted(by))
        hs = by[rid]
        try:
            res = cl.messages.create(model=D.MODEL, max_tokens=D.MAX_TOKENS, system=SYSTEM,
                                     messages=[{"role": "user", "content": user_prompt(hs)}])
            tin += getattr(res.usage, "input_tokens", 0) or 0
            tout += getattr(res.usage, "output_tokens", 0) or 0
            if res.stop_reason != "end_turn":
                print(f"  ⚠stop={res.stop_reason}", flush=True)
            got = parse_tags("".join(getattr(b, "text", "") for b in res.content))
        except Exception as e:                   # noqa: BLE001
            print(f"  ⚠API {type(e).__name__}", flush=True)
            got = {}
        races += 1
        for h in hs:
            u = h["umaban"]
            now = T.note_tags(h["comment"])
            hk = got.get(u)
            print(f"{rid}\t{u}\t{'・'.join(now)}\t{'・'.join(hk) if hk is not None else '(返事なし)'}", flush=True)
            n += 1
    print(f"合計 頭数 {n}・レース {races}・入力トークン {tin}・出力トークン {tout}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

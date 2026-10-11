# -*- coding: utf-8 -*-
"""fetch.py --push の送り口(クラウド版・2026-10-11)。PC の 他場/scraper/supabase_push.push_race の
調教(nar_kb_works)と厩舎の話(nar_kb_danwa)の 2 表だけを写した(行の形は PC と同じ)。

なぜ: 調教・談話を DB に入れるのが PC のタスクだけで、PC が眠った 10/05〜08 は南関 AI v3 の前日版が
調教なしになった(束 t14 は見張りで止まり、束 f10k も足さない)。クラウドの kb-daily からも入れる。
⛔鍵は nar_push.creds()(環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY)。印字しない。
"""
from fetch_kb_all import KB_TRACK
from nar_push import upsert as nar_upsert
from parsers import race_id_parts

COUNT = {"nar_kb_works": 0, "nar_kb_danwa": 0}


def _kb_base(parsed):
    rid = str(parsed.get("race_id") or "")
    try:
        p = race_id_parts(rid)
    except Exception:
        return None
    track = KB_TRACK.get(rid[6:8])
    d = str(p.get("date") or "")
    if not track or len(d) != 8 or not p.get("race_no"):
        return None
    return {"track": track, "race_date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
            "race_no": int(p["race_no"]), "race_id": rid}


def push_race(out):
    if "cyokyo" in out:
        parsed = out["cyokyo"]
        base = _kb_base(parsed)
        rows = [dict(base, umaban=h["umaban"], horse_name=h["horse_name"], tanpyo=h["tanpyo"],
                     arrow=h["arrow"], works=h["works"])
                for h in parsed["horses"] if base is not None and h.get("umaban") not in (None, "")]
        if rows and not nar_upsert("nar_kb_works", rows, "track,race_date,race_no,umaban"):
            raise RuntimeError("追切: 本体の鍵が無いので送れない")
        COUNT["nar_kb_works"] += len(rows)
    if "danwa" in out:
        parsed = out["danwa"]
        base = _kb_base(parsed)
        rows = [dict(base, umaban=h["umaban"], horse_id=h["horse_id"], horse_name=h["horse_name"],
                     headline=h["headline"], trainer=h["trainer"], comment=h["comment"], raw=h["raw"])
                for h in parsed["horses"] if base is not None and h.get("umaban") not in (None, "")]
        if rows and not nar_upsert("nar_kb_danwa", rows, "track,race_date,race_no,umaban"):
            raise RuntimeError("厩舎の話: 本体の鍵が無いので送れない")
        COUNT["nar_kb_danwa"] += len(rows)

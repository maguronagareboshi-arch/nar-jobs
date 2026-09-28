# -*- coding: utf-8 -*-
"""他場/scraper/backfill_cyokyo.py の COLUMNS と flatten_race(+ 使う小さな関数)だけの写し(中身は変えない)。
第 8 版の毎日の前日版が追い切りを平らにするのに使う。bs4・競馬ブックの取得部は持ち込まない。"""

# 平らな CSV の列。⛔ここ 1 か所= 旧 DB(export_db_cyokyo)も書庫(convert_archive_cyokyo)も同じ並びで書く。
# ⚠設計の is_final は kind に置き換え(final=☆ / mid=日付のある☆無し)。
#   source= その行がどこから来たか(kb=競馬ブック取り直し / db=旧DB / archive=旧ビューアの年別ファイル)。
COLUMNS = [
    "race_id", "race_date", "track", "race_no", "umaban", "horse_name", "horse_id",
    "arrow", "horse_tanpyo", "mark", "kind", "rider", "work_date", "youbi", "course",
    "is_hanro", "baba", "t_1mile", "t_7f", "t_6f", "t_5f", "t_half", "t_3f", "t_1f",
    "position", "ashiiro", "work_tanpyo", "movie", "source",
]


def is_hanro(course):
    """坂路かどうか。⛔読み方は 1 か所= course に「坂」が入っていれば坂路(parsers と同じ流儀)。"""
    return 1 if course and "坂" in str(course) else 0


def work_kind(work):
    """CSV に入れる種別。日付が無い行(■ 持ち時計 / ◇ 前走時の参考行)は None= 入れない。"""
    if not (work or {}).get("date"):
        return None
    return "final" if "☆" in str((work or {}).get("mark") or "") else "mid"


def race_date_of(race_id, fallback=None):
    if fallback:
        return fallback
    return f"{race_id[0:4]}-{race_id[12:14]}-{race_id[14:16]}"


def flatten_race(parsed, track, source="kb"):
    """parse_cyokyo の返り 1 レース → CSV の行(日付のある本だけ)。"""
    rid = str(parsed.get("race_id") or "")
    if len(rid) != 16:
        return []
    race_date = race_date_of(rid, parsed.get("race_date"))
    race_no = int(rid[10:12])
    rows = []
    for h in parsed.get("horses") or []:
        for w in h.get("works") or []:
            kind = work_kind(w)
            if not kind:
                continue
            t = w.get("times") or {}
            rows.append({
                "race_id": rid, "race_date": race_date, "track": track, "race_no": race_no,
                "umaban": h.get("umaban"), "horse_name": h.get("horse_name"),
                "horse_id": h.get("horse_id"), "arrow": h.get("arrow"),
                "horse_tanpyo": h.get("tanpyo"), "mark": w.get("mark"), "kind": kind,
                "rider": w.get("rider"), "work_date": w.get("date"), "youbi": w.get("youbi"),
                "course": w.get("course"), "is_hanro": is_hanro(w.get("course")),
                "baba": w.get("baba"),
                "t_1mile": t.get("t_1mile"), "t_7f": t.get("t_7f"), "t_6f": t.get("t_6f"),
                "t_5f": t.get("t_5f"), "t_half": t.get("t_half"), "t_3f": t.get("t_3f"),
                "t_1f": t.get("t_1f"),
                "position": w.get("position"), "ashiiro": w.get("ashiiro"),
                "work_tanpyo": w.get("tanpyo"), "movie": w.get("movie"),
                "source": source,
            })
    return rows


# ---------------------------------------------------------------- CSV(年ごと・出どころを混ぜる)

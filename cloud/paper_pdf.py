# -*- coding: utf-8 -*-
r"""紙面 PDF の過去走の枠 1 つ(文字認識の結果= 字と位置)→ 過去走 1 行(純関数・ネット/DB 不要)。

紙面の枠は上から 9 行= ①日付・馬場・場 ②クラス ③頭数・馬番・人気 ④着順・距離の記号・走破時計 ⑤馬場差・タイム差
⑥斤量・騎手・馬体重 ⑦通過 ⑧「前半 Ⓢ/Ⓜ/Ⓗ 上がり」 ⑨相手の馬(名前の後ろの B/P/S= その馬自身の馬具)。
- ⑧の 2 つの数は**横の位置**で分ける(左= 前半・右= 上がり)。文字認識の行の順は当てにしない(実測で入れ替わる)。
- 前半が空欄の走は右の 1 つだけ= 上がりだけ入れ、前半は None(⛔推測で埋めない)。
- 信頼度が低い字(score < MIN_SCORE)の値は欠損(None)にする。
- 距離の記号(専用の字形)は読めない= 距離は出さない(照合側で公式の表から引く)。
- ⛔紙面の段組の順や仮のレース番号は鍵にしない(出どころの位置は呼ぶ側が持つ)。
"""
import re
import unicodedata

MIN_SCORE = 0.8
VENUE_SHORT = {"盛": "盛岡", "水": "水沢"}   # 岩手の 2 場は略字(「4盛4」= 4 回盛岡 4 日目)
VENUE_FULL = ("名古屋", "高知", "金沢", "大井", "門別", "船橋", "川崎", "浦和", "園田", "姫路", "笠松", "佐賀", "帯広",
              "中山", "東京", "中京", "京都", "阪神", "札幌", "函館", "福島", "新潟", "小倉")
NUM3F = re.compile(r"(\d{2}\.\d)")
GEAR_TAIL = re.compile(r"[^\x00-\x7f]\s*([BPS](?:\s*[BPS]){0,2})$")   # 名前(日本語の字)の直後・末尾に 1〜3 字の B/P/S


def _band(lines, height, lo, hi):
    return [d for d in lines if lo * height <= float(d["cy"]) < hi * height]


def parse_date_venue(text, race_date):
    """'7.19良 4 盛4' → ('2026-07-19', '盛岡')。年は紙面の日付より後の月日なら前年"""
    s = str(text or "").replace("．", ".")
    m = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})", s)
    date = None
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        ry, rm, rd = (int(x) for x in race_date.split("-"))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            date = "%04d-%02d-%02d" % (ry if (mo, da) <= (rm, rd) else ry - 1, mo, da)
    venue = next((v for v in VENUE_FULL if v in s), None)
    if venue is None:
        m2 = re.search(r"\d\s*([盛水])\s*\d", s)
        venue = VENUE_SHORT.get(m2.group(1)) if m2 else None
    return date, venue


def parse_finish_time(text):
    """'7壬1163' → (7, 76.3)。末尾 4 桁= 分・秒 2 桁・10 分の 1。先頭の数= 着順(記号が落ちても末尾 4 桁で分ける)"""
    s = re.sub(r"\s", "", str(text or ""))
    m = re.match(r"^(\d{1,2})\D{0,2}(\d)(\d{2})(\d)$", s)
    if not m:
        return None, None
    fin, mi, ss, t = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if not (1 <= fin <= 18) or ss >= 60:
        return None, None
    return fin, round(mi * 60 + ss + t / 10, 1)


def _same_run(run, d):
    """紙面の 1 走と公式の 1 行が (場, 日付, 着順, 走破 time_sec) で同じか"""
    try:
        return (d.get("track") == run["venue"] and str(d.get("race_date")) == run["date"]
                and d.get("finish") is not None and int(d["finish"]) == run["finish"]
                and d.get("time_sec") is not None and abs(float(d["time_sec"]) - run["time_sec"]) < 0.05)
    except (TypeError, ValueError):
        return False


def identify_horse(runs, db_rows):
    """馬の特定(⛔馬名は読まない)。1 頭の枠の過去走 → (馬名 or None, 理由, {走の番号: 公式の行})。
    取消など着順/時計の無い走は数えない。1 走が 2 頭に当たる(同着)ときはその走を数えない。
    **2 走以上が同じ馬名を指し、違う馬名を指す走が 0** のときだけ特定"""
    votes, hits, notes, split = {}, {}, [], {}
    for i, run in enumerate(runs or []):
        if not run or run.get("finish") is None or run.get("time_sec") is None or not run.get("date") or not run.get("venue"):
            continue
        cand = [d for d in (db_rows or []) if _same_run(run, d)]
        names = {d.get("horse_name") for d in cand}
        if len(cand) == 1:
            nm = cand[0].get("horse_name")
            votes[nm] = votes.get(nm, 0) + 1
            hits[i] = cand[0]
        elif len(names) > 1:
            # 同じ日・場・着順・走破時計の馬が 2 頭以上(別のレースの同じ着順・同じ時計 or 同着)= この走は数えない
            notes.append("場・日・着順・時計が同じ %d 頭" % len(cand))
            split[i] = cand
    if len(votes) > 1:
        return None, "名が割れる(%s)" % "・".join("%s %d 走" % kv for kv in sorted(votes.items())), {}
    if not votes:
        return None, "一致 0 走" + ("(%s)" % "・".join(notes) if notes else ""), {}
    name, n = next(iter(votes.items()))
    if n < 2:
        return None, "一致 1 走" + ("(%s)" % "・".join(notes) if notes else ""), {}
    # 特定できた後だけ= 数えなかった走も、候補のうちその馬名の行がちょうど 1 つならその走の行とする(⛔特定の票には足さない)
    for i, cand in split.items():
        mine = [d for d in cand if d.get("horse_name") == name]
        if len(mine) == 1:
            hits[i] = mine[0]
    return name, "特定(%d 走一致)" % n, hits


def gear_marks(text):
    """⑨相手の馬の行 → その走のその馬の馬具の字('B'・'P'・'S' を B→P→S の順に '+' でつなぐ)。無ければ None。
    名前の直後に 1〜3 字の B/P/S が**末尾**に並ぶときだけ(全角も受ける・間の空白は問わない)。
    ⛔1 字でも B/P/S 以外の字が末尾に混じれば None(推定しない)"""
    s = unicodedata.normalize("NFKC", str(text or "")).strip()
    m = GEAR_TAIL.search(s)
    if not m:
        return None
    got = set(re.sub(r"\s", "", m.group(1)))
    return "+".join(c for c in "BPS" if c in got)


def gear_from_band(band):
    """⑨の帯の認識(左→右に並べたもの)→ (馬具の字 or None, 信頼度が足りず読まなかったか)。
    ① 右端から続く箱が B/P/S だけ(合わせて 1〜3 字)= 印の箱。**その箱の信頼度だけ**で決める。
       2026-09-15 10R の実測= 文字認識はカタカナの馬名をほとんど拾わず(拾っても 0.5〜0.7)、印は別の箱で 0.8〜1.0 で返る。
    ② 印の箱が無い(名前と印が 1 つの箱)= 全部の信頼度が足りるときだけ gear_marks。
    ⛔印の箱の信頼度が低い・崩れた字(例 'SA(EXYIHYE')は読まない(推定しない)"""
    band = list(band or [])
    if not band:
        return None, False
    marks = []
    for d in reversed(band):
        t = re.sub(r"\s", "", unicodedata.normalize("NFKC", str(d.get("text") or "")))
        if not re.fullmatch(r"[BPS]+", t):
            break
        marks.append((t, float(d["score"])))
    if marks and len("".join(t for t, _ in marks)) <= 3:
        if any(s < MIN_SCORE for _, s in marks):
            return None, True
        got = set("".join(t for t, _ in marks))
        return "+".join(c for c in "BPS" if c in got), False
    if any(float(d["score"]) < MIN_SCORE for d in band):
        return None, True
    return gear_marks(" ".join(str(d.get("text") or "") for d in band)), False


def rows_to_write(name, runs, hits, distances, src):
    """特定できた馬の、紙面に前半の値がある走だけ → nar_paper_runs の行。
    distances= {(track, date, race_no): distance_m}・src= {ref(ファイル名だけ), page, col}。
    馬具の字がある走だけ gear を足す(無い走の行には gear の鍵を持たせない)。
    距離 ≥1200 → first3f / <1200 → first2f(⛔3F に入れない)"""
    out = []
    for i, run in enumerate(runs or []):
        d = hits.get(i)
        if d is None or run.get("first3f") is None:
            continue
        dist = distances.get((d["track"], str(d["race_date"]), int(d["race_no"])))
        if dist is None:
            continue
        big = int(dist) >= 1200
        out.append({"track": d["track"], "race_date": str(d["race_date"]), "race_no": int(d["race_no"]),
                    "umaban": int(d["runner_number"]), "horse_name": name,
                    "first3f": run["first3f"] if big else None, "first2f": None if big else run["first3f"],
                    "src_ref": src["ref"], "src_page": src["page"], "src_pos": "右から%d列 上から%d段" % (src["col"], i + 1)})
        if run.get("gear"):                                  # ⛔None は書かない= 既存の行の gear を null で潰さない
            out[-1]["gear"] = run["gear"]
    return out


def parse_block(lines, width, height, race_date):
    """lines= [{text, score, cx, cy}](枠の左上が 0,0)→ 1 行。値の無い所は None"""
    lines = list(lines or [])
    row = {"date": None, "venue": None, "finish": None, "time_sec": None, "first3f": None, "last3f": None,
           "gear": None, "note": None, "low_score": []}
    top = sorted(_band(lines, height, 0, 0.13), key=lambda d: float(d["cx"]))
    row["date"], row["venue"] = parse_date_venue(" ".join(d["text"] for d in top), race_date)
    body = " ".join(d["text"] for d in lines)
    if "取消" in body or "除外" in body:
        row["note"] = "出走取消" if "取消" in body else "競走除外"
    for d in _band(lines, height, 0.25, 0.47):
        fin, sec = parse_finish_time(d["text"])
        if sec is not None:
            if float(d["score"]) < MIN_SCORE:
                row["low_score"].append("time")
            else:
                row["finish"], row["time_sec"] = fin, sec
            break
    toks = []
    for d in _band(lines, height, 0.68, 0.91):
        for m in NUM3F.finditer(d["text"]):
            v = float(m.group(1))
            if 25 <= v <= 60:
                # 1 つの認識の中に 2 つあれば字の位置で左右を分ける(位置= 認識の中心 ± 字の幅)
                n = max(len(d["text"]), 1)
                off = (m.start() + len(m.group(1)) / 2 - n / 2) / n * width * 0.6
                toks.append((float(d["cx"]) + off, v, float(d["score"])))
    toks.sort()
    if len(toks) == 2:
        (_, a, sa), (_, b, sb) = toks
        row["first3f"] = a if sa >= MIN_SCORE else None
        row["last3f"] = b if sb >= MIN_SCORE else None
        if sa < MIN_SCORE:
            row["low_score"].append("first3f")
        if sb < MIN_SCORE:
            row["low_score"].append("last3f")
    elif len(toks) == 1:
        x, v, sc = toks[0]
        key = "last3f" if x > width * 0.5 else "first3f"
        if sc >= MIN_SCORE:
            row[key] = v
        else:
            row["low_score"].append(key)
    elif len(toks) > 2:
        row["low_score"].append("3f_many")
    # ⑨相手の馬(最下段)の末尾の B/P/S= その走のその馬の馬具(読み方は gear_from_band)
    gear, low = gear_from_band(sorted(_band(lines, height, 0.9, 1.01), key=lambda d: float(d["cx"])))
    row["gear"] = gear
    if low:
        row["low_score"].append("gear")
    return row

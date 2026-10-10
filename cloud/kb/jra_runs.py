# -*- coding: utf-8 -*-
"""競馬ブック 馬の頁(/db/uma/{ID}/kanzen)から中央(JRA 10 場)の走だけを取り出す。

定義書: nankan-ai docs/research/69_jra_runs_intake_spec.md
- 1 走 = div.kanzendata_race 1 塊。地方・海外の走は返さない(二重を作らない)。
- 着差はタイムの括弧内("1.38.8(3/4)" の "3/4")。1 着は括弧なし= None。
"""

import re
import unicodedata

from bs4 import BeautifulSoup

JRA_PLACES = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")

_RE_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\(([^・)]*)・?([^)]*)\))?")
_RE_PLACE = re.compile(r"^(?:(\d+)回)?(.+?)(?:(\d+)日目)?(\d+)R\((.*?)\s*(\d+)m\)")
_RE_TIME = re.compile(r"^(\d+(?:\.\d+)*)(?:\((.+)\))?$")


def _t(el, sep=" "):
    return el.get_text(sep, strip=True) if el is not None else ""


def _num(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def time_to_sec(s):
    """'1.38.8' → 98.8 / '58.9' → 58.9"""
    if not s:
        return None
    parts = s.split(".")
    try:
        if len(parts) == 3:
            return round(int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 10, 1)
        if len(parts) == 2:
            return round(float(s), 1)
    except ValueError:
        return None
    return None


def _circled_to_int(s):
    s = s.strip()
    if not s:
        return None
    if re.fullmatch(r"[0-9]+", s):
        return int(s)
    try:
        return int(unicodedata.numeric(s)) if len(s) == 1 else None
    except (TypeError, ValueError):
        return None


def parse_horse_header(soup):
    """title 'ムーンリットビーチ(2023) - ...' → 馬名・生年。生年月日は本文 '2023.4.2 生'。"""
    title = _t(soup.find("title"))
    name, birth_year, birth_date = None, None, None
    m = re.match(r"^\s*(.+?)\((\d{4})\)", title)
    if m:
        name, birth_year = m.group(1).strip(), int(m.group(2))
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*生", soup.get_text(" ", strip=True))
    if m:
        birth_date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if birth_year is None:
            birth_year = int(m.group(1))
    return {"horse_name": name, "birth_year": birth_year, "birth_date": birth_date}


def _parse_block(block, kb_horse_id):
    rm = block.select_one("tr.time td.racemei")
    if rm is None:
        return None
    ps = [_t(p) for p in rm.find_all("p")]
    link = rm.find("a", href=True)
    href = link["href"] if link else ""
    if len(ps) < 2:
        return None
    md = _RE_DATE.search(ps[0])
    mp = _RE_PLACE.search(ps[1])
    if not md or not mp:
        return None
    place = mp.group(2).strip()
    if place not in JRA_PLACES or "/cyuou/" not in href:
        return None  # 地方・海外は返さない
    cond = mp.group(5) or ""
    course, _, direction = cond.partition("・")
    if course.startswith("芝"):
        surface = "芝"
    elif course.startswith("ダ"):
        surface = "ダ"
    elif course.startswith("障"):
        surface = "障"
    else:
        surface = course or None
    # 障害戦は頁のコース欄が「芝」「ダ」のことがある→ レース名で見分ける
    if len(ps) > 2 and ps[2] and ("障害" in ps[2] or "ジャンプ" in ps[2]):
        surface = "障"
    row = {
        "kb_horse_id": kb_horse_id,
        "race_date": f"{int(md.group(1)):04d}-{int(md.group(2)):02d}-{int(md.group(3)):02d}",
        "place": place,
        "race_no": int(mp.group(4)),
        "kai": int(mp.group(1)) if mp.group(1) else None,
        "nichi": int(mp.group(3)) if mp.group(3) else None,
        "kb_race_id": href.rstrip("/").rsplit("/", 1)[-1] or None,
        "race_name": ps[2] if len(ps) > 2 else None,
        "race_cond": ps[3] if len(ps) > 3 and ps[3] else None,
        "surface": surface,
        "course": course[1:] if surface in ("芝", "ダ") and course[:1] == "芝" else None,
        "direction": direction or None,
        "distance": int(mp.group(6)),
        "weather": (md.group(4) or None),
        "going": (md.group(5) or None),
    }
    # タイム・着差(本馬の列 = td.active)
    act = block.select_one("tr.time td.active")
    tt = _t(act, "")
    mt = _RE_TIME.match(tt)
    row["time_raw"] = mt.group(1) if mt else (tt or None)
    row["time_sec"] = time_to_sec(mt.group(1)) if mt else None
    row["margin"] = mt.group(2) if mt and mt.group(2) else None
    # 詳細(頭数・枠・体重・オッズ・人気・前後半・ペース・上り・通過・着順)
    det = block.select_one("td.detail")
    dtext = det.get_text("", strip=True) if det is not None else ""
    m = re.search(r"(\d+)頭(\d+)(?:ｹﾞｰﾄ|ゲート)", dtext)
    row["field_size"] = int(m.group(1)) if m else None
    row["gate"] = int(m.group(2)) if m else None
    m = re.search(r"(\d{3})K", dtext)
    row["body_weight"] = int(m.group(1)) if m else None
    m = re.search(r"(\d+(?:\.\d+)?)\((\d+)人気\)", dtext)
    row["win_odds"] = _num(m.group(1)) if m else None
    row["popularity"] = int(m.group(2)) if m else None
    # H1(2026-09-29): 「前X-後Y」は その馬の前半3F・上り3F(後= 馬の上り。公式の上3F と一致)。
    # 「上りA-B」は レースの上り4F-3F(同じレースの馬で同じ値)。元は last3f と race_last3f が逆だった。
    m = re.search(r"前(\d+\.\d)?-後(\d+\.\d)?", dtext)
    row["first3f"] = _num(m.group(1)) if m else None
    row["last3f"] = _num(m.group(2)) if m else None
    m = re.search(r"([SMH])ペース", dtext)
    row["pace"] = m.group(1) if m else None
    m = re.search(r"上り(\d+\.\d)-(\d+\.\d)", dtext)
    row["last4f"] = _num(m.group(1)) if m else None      # レースの上り4F(列名は据え置き)
    row["race_last3f"] = _num(m.group(2)) if m else None
    corners = []
    if det is not None:
        for li in det.select("ul.tuka li"):
            if "kara" in (li.get("class") or []):
                continue
            v = _circled_to_int(_t(li, ""))
            if v is not None:
                corners.append(str(v))
    row["passing"] = "-".join(corners) or None
    fin = det.select_one("span.k_datacyaku") if det is not None else None
    ftxt = _t(fin, "")
    m = re.match(r"^(\d+)着$", ftxt)
    row["finish"] = int(m.group(1)) if m else None
    row["finish_note"] = None if m else (ftxt or None)
    # 騎手・斤量(本馬の列)
    kb = block.select_one("tr.kbamei td.active dd")
    ja = kb.find("a") if kb is not None else None
    row["jockey"] = _t(ja, "") or None
    m = re.search(r"(\d+(?:\.\d)?)\s*$", _t(kb))
    row["carried_weight"] = _num(m.group(1)) if m else None
    return row


# ---- 読み違いの番人(2026-10-10 監査 中 #11)。ラベル付きの正規表現で読むが範囲を見ていなかった
#   (9/29 に last3f と race_last3f が逆だった実例)。外れの走は runs に入れない(書かない)。
#   前後 3F は 30〜50 秒(障害は後 3F だけ 30〜60 秒)・レースの上り 4F と 3F の差は 1 ハロン(9〜16 秒)・
#   馬体重 300〜650kg・斤量 40〜70kg。
JR_3F = (30.0, 50.0)
JR_3F_JUMP = (30.0, 60.0)
JR_4F_MINUS_3F = (9.0, 16.0)
JR_BODY = (300, 650)
JR_CARRIED = (40.0, 70.0)
JRA_GUARD = []           # 外した走の理由(呼び側が数える)


def front_range(lo, hi, dist):
    """前半の範囲。前半= 距離 − 600m(上がり)なので、1000m 戦の前半は 400m(本番 2,743 走が 21.7〜28.2 秒)。
    前半が 600m に満たない距離は範囲をその割合で縮める・600m 以下は見ない(None)。"""
    if not dist:
        return lo, hi
    front = dist - 600
    if front <= 0:
        return None
    k = min(front / 600, 1.0)
    return lo * k, hi * k


def jra_run_bad(r):
    """中央の 1 走の外れ → 理由(空= 通す)。"""
    jump = r.get("surface") == "障"
    for key in ("first3f", "last3f"):
        v = r.get(key)
        if v is None or (jump and key == "first3f"):
            continue
        lo, hi = JR_3F_JUMP if jump else JR_3F
        if key == "first3f":
            rg = front_range(lo, hi, r.get("distance"))
            if rg is None:
                continue
            lo, hi = rg
        if not (lo <= v <= hi):
            return f"{key} {v}"
    a, b = r.get("last4f"), r.get("race_last3f")
    if a is not None and b is not None and not (JR_4F_MINUS_3F[0] <= a - b <= JR_4F_MINUS_3F[1]):
        return f"レースの上り 4F {a}・3F {b}"
    w = r.get("body_weight")
    if w is not None and not (JR_BODY[0] <= w <= JR_BODY[1]):
        return f"馬体重 {w}"
    c = r.get("carried_weight")
    if c is not None and not (JR_CARRIED[0] <= c <= JR_CARRIED[1]):
        return f"斤量 {c}"
    return ""


def parse_kanzen(html, kb_horse_id):
    """馬の頁 → {'horse': {...}, 'runs': [中央の走だけ], 'n_blocks': 頁の全走}。値の外れの走は runs に入れない。"""
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select("div.kanzendata_race")
    runs = []
    for b in blocks:
        r = _parse_block(b, kb_horse_id)
        if r is not None:
            bad = jra_run_bad(r)
            if bad:
                JRA_GUARD.append(f"{kb_horse_id} {r.get('race_date')} {r.get('place')} {r.get('race_no')}R {bad}")
                print(f"::warning::中央の走 書かない {JRA_GUARD[-1]}", flush=True)
                continue
            runs.append(r)
    horse = parse_horse_header(soup)
    horse["kb_horse_id"] = kb_horse_id
    horse["jra_runs"] = len(runs)
    horse["last_jra_date"] = max((r["race_date"] for r in runs), default=None)
    return {"horse": horse, "runs": runs, "n_blocks": len(blocks)}

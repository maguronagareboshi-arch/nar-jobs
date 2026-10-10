# -*- coding: utf-8 -*-
"""競馬ブックWeb 地方版のHTMLパーサ。

対象ページ:
  /chihou/nittei/YYYYMMDD   ... 開催日程（場ごとのレース一覧）
  /chihou/seiseki/{raceId}  ... 成績（前半3F・通過順位などは会員限定）
  /chihou/syutuba/{raceId}  ... 出馬表（トラックマン印は会員限定）

レースID（16桁）: YYYY + 回(2) + 場コード(2) + 日次(2) + レース番号(2) + 月日(4)
  例 2026064205010701 = 2026年 第6回 門別(42) 5日目 1R 7月1日
非会員ページでは会員限定の値が「*」「****」で伏せられるので None にする。

§119a: 成績の行に gear(馬装具)・start_note(発走状況他)・kimete(決め手)・pace・avg_f を、
出馬表の行に blinker を足した。⛔レース単位の文字列を馬番/着順で割って載せているだけで、推定はしない。
"""

import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

try:  # package import in tests / script-style import from fetch.py
    from .nouryoku_semantics import is_trial_event_text
except ImportError:  # pragma: no cover - exercised by the daily script entrypoint
    from nouryoku_semantics import is_trial_event_text

MASK_RE = re.compile(r"^[\*＊※]+$")
_CIRCLED_INTEGERS = {chr(0x2460 + index): index + 1 for index in range(20)}


def _text(el):
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text()).strip()


def _clean(s):
    """伏せ字・空文字は None"""
    s = (s or "").strip()
    if not s or MASK_RE.match(s):
        return None
    return s


def _num(s):
    s = _clean(s)
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace("＋", "+").replace("－", "-"))
    return float(m.group(0)) if m else None


def _int(s):
    v = _num(s)
    return int(v) if v is not None else None


def _corner_int(s):
    """Parse ordinary or circled NAR corner positions (① through ⑳)."""
    text = str(s or "").strip()
    for char in text:
        if char in _CIRCLED_INTEGERS:
            return _CIRCLED_INTEGERS[char]
    return _int(text)


def time_to_sec(s):
    """'1.02.4' → 62.4 / '59.8' → 59.8"""
    s = _clean(s)
    if s is None:
        return None
    m = re.match(r"^(?:(\d+)\.)?(\d{1,2})\.(\d)$", s)
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    seconds = int(m.group(2))
    # ``9.99.9`` is a source sentinel/malformed token, not 639.9 seconds.
    if seconds >= 60:
        return None
    return mins * 60 + seconds + int(m.group(3)) / 10


def race_id_parts(race_id):
    """16桁レースIDを分解する"""
    return {
        "year": int(race_id[0:4]),
        "kai": int(race_id[4:6]),
        "track_code": race_id[6:8],
        "nichi": int(race_id[8:10]),
        "race_no": int(race_id[10:12]),
        "date": race_id[0:4] + race_id[12:16],  # YYYYMMDD
    }


def _db_id(cell, kind):
    """セル内の /db/uma/ 等のリンクからIDを取り出す"""
    a = cell.find("a", href=re.compile(rf"/db/{kind}/"))
    if not a:
        return None
    return unquote(a["href"].rsplit("/", 1)[-1]) or None


# ---------------------------------------------------------------- nittei

def parse_nittei(html):
    """開催日程ページ → [{track, races: [{race_id, race_no, name, course}]}]"""
    soup = BeautifulSoup(html, "lxml")
    meets = []
    for table in soup.select("table.kaisai"):
        track = _text(table.select_one("th.midasi"))
        if not track:
            continue
        races = []
        seen = set()
        for tr in table.find_all("tr"):
            a = tr.find("a", href=re.compile(r"/chihou/(?:syutuba|seiseki)/\d{16}"))
            if not a:
                continue
            race_id = re.search(r"(\d{16})", a["href"]).group(1)
            if race_id in seen:
                continue
            seen.add(race_id)
            tds = tr.find_all("td")
            name = course = None
            if len(tds) >= 2:
                ps = [_text(p) for p in tds[1].find_all("p")]
                ps = [p for p in ps if p]
                if ps:
                    name = ps[0]
                for p in ps[1:]:
                    if re.search(r"\d{3,4}m", p):
                        course = p
            races.append({
                "race_id": race_id,
                "race_no": race_id_parts(race_id)["race_no"],
                "name": name,
                "course": course,
            })
        meets.append({"track": track, "races": races})
    return meets


# ---------------------------------------------------------------- 共通: レースヘッダ

def _parse_race_header(soup, race_id):
    parts = race_id_parts(race_id) if race_id else {}
    race = {
        "race_id": race_id,
        "date": None,
        "track": None,
        "race_no": parts.get("race_no"),
        "hasso_time": None,
        "klass": None,
        "name": None,
        "distance_m": None,
        "surface": None,
        "direction": None,
        "weather": None,
        "going": None,
    }
    if parts.get("date"):
        d = parts["date"]
        race["date"] = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"

    rn = soup.select_one("div.racename")
    if rn:
        race["track"] = _text(rn.select_one("h2")) or None
        race["hasso_time"] = _clean(_text(rn.select_one(".hassotime")))
        h1b = rn.select_one(".h1block")
        if h1b:
            race["klass"] = _clean(_text(h1b.find("h1")))
            ps = [_text(p) for p in h1b.find_all("p")]
            ps = [p for p in ps if p]
            if ps:
                race["name"] = ps[0]
        if race["date"] is None:
            m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", _text(rn))
            if m:
                race["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if race["race_no"] is None:
            race["race_no"] = _int(_text(rn.select_one(".raceno")))

    right = soup.select_one("div.racenameright")
    if right:
        t = _text(right)
        m = re.search(r"(\d{3,4})m", t)
        if m:
            race["distance_m"] = int(m.group(1))
        m = re.search(r"[（(]([^・）)]+)・([^）)]+)[）)]", t)
        if m:
            race["surface"] = m.group(1)
            race["direction"] = m.group(2)
        m = re.search(r"(晴|曇|雨|小雨|雪|小雪)\s*・\s*(良|稍重|重|不良)", t)
        if m:
            race["weather"] = m.group(1)
            race["going"] = m.group(2)
    return race


# ---------------------------------------------------------------- seiseki

# ヘッダ名 → 出力キー。列構成はログイン状態で変わる（ログイン時は4角位置・寸評が増える）
# ため、位置固定ではなくヘッダ名で対応付ける。
# §119a 成績ページの「馬装具」「発走状況他」「決め手」「平均ハロン」「ペース」は
#   **行の列ではなく table.seiseki-etc(レース単位)の1つの文字列**(2026-09-06 実測)。
#   例: 馬装具「(2)(6)(9)(11)ブリンカー着用 (4)シャドーロール着用」/ 発走状況他「(7)(8)出遅れ」
#       決め手「１着馬:三角先 ２着馬:好位伸」/ 平均ハロン「12.13」/ ペース「ハイ」
#   ⛔括弧の中は**馬番**、決め手だけは**着順**。ここで割ってから各馬の行に載せる(無い場は None)。
_UMABAN_GROUP_RE = re.compile(r"((?:[（(]\s*\d+\s*[）)]\s*)+)([^（(]+)")
_KIMETE_RE = re.compile(r"(\d+)\s*着\s*馬\s*[:：]\s*([^\s　]+)")
_Z2H = str.maketrans("０１２３４５６７８９", "0123456789")


def _by_umaban(text):
    """「(2)(6)ブリンカー着用 (4)シャドーロール着用」→ {2:"ブリンカー着用", 4:"シャドーロール着用", 6:…}
    ⚠同じ馬が2つの札を持つことがある(ブリンカー+シャドーロール)ので空白で繋ぐ。"""
    out = {}
    for m in _UMABAN_GROUP_RE.finditer((_clean(text) or "").translate(_Z2H)):
        label = m.group(2).strip()
        if not label:
            continue
        for n in re.findall(r"\d+", m.group(1)):
            out.setdefault(int(n), []).append(label)
    return {k: " ".join(v) for k, v in out.items()}


def _by_finish(text):
    """「１着馬:三角先 ２着馬:好位伸」→ {1: "三角先", 2: "好位伸"}(鍵は**着順**)"""
    out = {}
    for m in _KIMETE_RE.finditer((_clean(text) or "").translate(_Z2H)):
        out[int(m.group(1))] = m.group(2)
    return out


_SEISEKI_HEADER_MAP = {
    "着順": "finish",
    "My印": "my_mark",
    "本紙": "honshi_mark",
    "枠番": "waku",
    "馬番": "umaban",
    "馬名": "horse_name",
    "性齢": "sex_age",
    "重量": "kinryo",
    "騎手": "jockey",
    "タイム": "time_str",
    "着差": "margin",
    "通過順位": "passing",
    "4角位置": "corner4_pos",
    "寸評": "comment",
    "前半3F": "first3f",
    "上り3F": "last3f",
    "単人気": "pop",
    "単勝オッズ": "win_odds",
    "馬体重": "body_weight",
    "増減": "weight_diff",
    "厩舎": "trainer",
}


def parse_seiseki(html, race_id=None):
    """成績ページ → {race: {...}, results: [...]}"""
    soup = BeautifulSoup(html, "lxml")
    race = _parse_race_header(soup, race_id)

    results = []
    table = soup.select_one("table.seiseki")
    if table:
        header_tr = table.find("tr")
        headers = [_text(th) for th in header_tr.find_all(["th", "td"])] if header_tr else []
        jockey_idx = headers.index("騎手") if "騎手" in headers else None
        name_idx = headers.index("馬名") if "馬名" in headers else None

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < len(headers):
                continue
            cells = [_text(td) for td in tds]
            aligned_tds = list(tds)
            genryo = None
            # データ行はヘッダより1セル多く、騎手の直前に減量記号セルが挿入される
            if len(cells) == len(headers) + 1 and jockey_idx is not None:
                genryo = _clean(cells.pop(jockey_idx))
                aligned_tds.pop(jockey_idx)
            row = {}
            for i, h in enumerate(headers):
                key = _SEISEKI_HEADER_MAP.get(h)
                if key:
                    row[key] = cells[i]

            # ``_text(td)`` removes the ``li`` boundary and used to turn
            # 11 -> 11 -> 11 into the ambiguous string "111111".  Keep the
            # positions explicitly delimited while remaining compatible with
            # the existing text column in JSON/Supabase.
            passing = _clean(row.get("passing"))
            passing_positions = []
            passing_idx = headers.index("通過順位") if "通過順位" in headers else None
            if passing_idx is not None and passing_idx < len(aligned_tds):
                passing_positions = [
                    _corner_int(_text(li))
                    for li in aligned_tds[passing_idx].select("ul.tuka li")
                    if "kara" not in (li.get("class") or [])
                ]
                passing_positions = [
                    position for position in passing_positions if position is not None
                ]
                if passing_positions:
                    passing = "-".join(str(position) for position in passing_positions)

            finish_raw = _clean(row.get("finish", ""))
            r = {
                "finish": _int(finish_raw),
                "finish_note": finish_raw if finish_raw and not finish_raw.isdigit() else None,
                "waku": _int(row.get("waku")),
                "umaban": _int(row.get("umaban")),
                "horse_id": _db_id(tds[name_idx], "uma") if name_idx is not None else _db_id(tr, "uma"),
                "horse_name": _clean(re.sub(r"[★☆]", "", row.get("horse_name", ""))),
                "sex_age": _clean(row.get("sex_age")),
                "kinryo": _num(row.get("kinryo")),
                "genryo": genryo,
                "jockey_id": _db_id(tr, "kisyu"),
                "jockey": _clean(row.get("jockey")),
                "time_str": _clean(row.get("time_str")),
                "time_sec": time_to_sec(row.get("time_str")),
                "margin": _clean(row.get("margin")),
                "passing": passing,
                "passing_positions": passing_positions or None,
                "corner4_pos": _clean(row.get("corner4_pos")),
                "comment": _clean(row.get("comment")),
                "first3f": _num(row.get("first3f")),
                "last3f": _num(row.get("last3f")),
                "pop": _int(row.get("pop")),
                "win_odds": _num(row.get("win_odds")),
                "body_weight": _int(row.get("body_weight")),
                "weight_diff": _int(row.get("weight_diff")),
                "trainer_id": _db_id(tr, "kyusya"),
                "trainer": _clean(row.get("trainer")),
                "honshi_mark": _clean(row.get("honshi_mark")),
            }
            if r["umaban"] is None:
                continue
            results.append(r)

    # レース全体の会員限定データ（平均ハロン・ペース・決め手など）
    extra = {}
    for t in soup.select("table.seiseki-etc"):
        ths = [_text(th) for th in t.find_all("th")]
        tds = [_text(td) for td in t.find_all("td")]
        if ths and len(ths) == len(tds):
            for k, v in zip(ths, tds):
                if _clean(k):
                    extra[k] = _clean(v)
        else:
            # ハロンタイム等の変則テーブルは生テキストで保持
            extra.setdefault("_raw", []).append(_text(t))
    race["extra"] = extra
    race["pace"] = extra.get("ペース")
    race["avg_furlong"] = _num(extra.get("平均ハロン") or "")

    # §119a レース単位の値を各馬の行にも載せる(⛔既存の鍵は触らない= 足すだけ)。
    # 馬装具・発走状況他は馬番で、決め手は着順で引く。その馬の分が無ければ None。
    gear_by = _by_umaban(extra.get("馬装具"))
    start_by = _by_umaban(extra.get("発走状況他"))
    kimete_by = _by_finish(extra.get("決め手"))
    for r in results:
        r["gear"] = gear_by.get(r["umaban"])
        r["start_note"] = start_by.get(r["umaban"])
        r["kimete"] = kimete_by.get(r["finish"]) if r["finish"] else None
        r["pace"] = race["pace"]
        r["avg_f"] = race["avg_furlong"]

    # ラップタイム（南関等は区間ラップを掲載＝門別の平均ハロンより細かい展開情報）。
    # 例 "6.9-10.8-12.0-13.2-13.3"（各区間の秒・合計＝勝ちタイム）→ [6.9,10.8,...]
    race["laps"] = None
    for t in soup.select("table.seiseki-tuka"):
        cap = _text(t.find("caption"))
        if "ラップ" in (cap or ""):
            txt = _text(t.find("td"))
            nums = re.findall(r"\d+\.\d", txt or "")
            if nums:
                race["laps"] = [float(x) for x in nums]
            break

    return {"race": race, "results": results}


def seiseki_is_masked(parsed):
    """会員限定の前半3Fが伏せられたままか（ログイン確認用）。
    完走馬（着順あり）だけで判定する（取消のみのレース＝不成立を誤判定しない）"""
    rs = [r for r in parsed["results"] if r["finish"] is not None]
    return bool(rs) and all(r["first3f"] is None for r in rs)


# ---------------------------------------------------------------- cyokyo（調教）

# 調教履歴行の17列（コースが坂路のときは括弧内の意味になる: 6F(坂路), 半哩(3F) 等）
_CYOKYO_COLS = [
    "mark", "rider", "date_raw", "harrow", "course", "baba",
    "t_1mile", "t_7f", "t_6f", "t_5f", "t_half", "t_3f", "t_1f",
    "position", "ashiiro", "tanpyo", "movie",
]
_YOUBI_RE = re.compile(r"(\d{1,2})/(\d{1,2})\(([月火水木金土日])\)")


def _cyokyo_date(raw, race_date):
    """'6/29(月)' → (ISO日付, 曜日)。年はレース日から推定（レース日より未来なら前年）"""
    m = _YOUBI_RE.search(raw or "")
    if not m or not race_date:
        return None, None
    mm, dd, youbi = int(m.group(1)), int(m.group(2)), m.group(3)
    year = int(race_date[0:4])
    iso = f"{year}-{mm:02d}-{dd:02d}"
    if iso > race_date:  # レース日より未来はあり得ない → 前年の調教
        iso = f"{year - 1}-{mm:02d}-{dd:02d}"
    return iso, youbi


def parse_cyokyo(html, race_id=None):
    """調教ページ → {race_id, horses: [{umaban, horse_name, tanpyo, arrow, works: [...]}]}"""
    soup = BeautifulSoup(html, "lxml")
    parts = race_id_parts(race_id) if race_id else {}
    race_date = None
    if parts.get("date"):
        d = parts["date"]
        race_date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"

    horses = []
    for t in soup.select("table.cyokyo"):
        # 馬情報行: 枠番, 馬番, 馬名, 追い切り短評, 矢印（入れ子のcyokyodata行は除く）
        info = None
        for tr in t.find_all("tr"):
            if tr.find_parent("table", class_="cyokyodata") is not None:
                continue
            tds = tr.find_all("td", recursive=False)
            if len(tds) >= 3 and _int(_text(tds[1])) is not None:
                info = tds
                break
        if info is None:
            continue
        horse = {
            "umaban": _int(_text(info[1])),
            "horse_name": _clean(re.sub(r"[★☆]", "", _text(info[2]))),
            "tanpyo": _clean(_text(info[3])) if len(info) > 3 else None,
            "arrow": _clean(_text(info[4])) if len(info) > 4 else None,
            "works": [],
        }
        for tr in t.select("table.cyokyodata tr"):
            tds = tr.find_all("td")
            if len(tds) != len(_CYOKYO_COLS):
                continue
            cells = [_text(td) for td in tds]
            w = dict(zip(_CYOKYO_COLS, cells))
            date_iso, youbi = _cyokyo_date(w["date_raw"], race_date)
            work = {
                "mark": _clean(w["mark"]),          # ☆=併せ馬など
                "rider": _clean(w["rider"]),
                "date": date_iso,
                "youbi": youbi,
                "course": _clean(w["course"]),      # 門別坂 等（「坂」を含めば坂路）
                "baba": _clean(w["baba"]),
                "times": {k: _num(w[k]) for k in
                          ["t_1mile", "t_7f", "t_6f", "t_5f", "t_half", "t_3f", "t_1f"]},
                "position": _clean(w["position"]),
                "ashiiro": _clean(w["ashiiro"]),    # 脚色（一杯/馬なり等）
                "tanpyo": _clean(w["tanpyo"]),
            }
            if work["date"] or any(v is not None for v in work["times"].values()):
                horse["works"].append(work)
        if horse["umaban"] is not None:
            horses.append(horse)
    return {"race_id": race_id, "race_date": race_date, "horses": horses}


def parse_danwa(html, race_id=None):
    """厩舎の話ページ → {race_id, horses: [{umaban, horse_id, horse_name, headline, trainer, comment, raw}]}
    コメント本文には新旧2種の書式が混在する（同じ日でも記者により異なる）:
      新: "○馬名(見出し) 　調教師名師――コメント本文。"
      旧: "○馬名【調教師名師】コメント本文。"（見出し無し）"""
    soup = BeautifulSoup(html, "lxml")
    horses = []
    table = soup.select_one("table.danwa")
    if table is None:
        return {"race_id": race_id, "horses": horses}
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        umaban = _int(_text(tds[1]))
        name_a = tds[2].find("a")
        horse_id = name_a.get("umacd") if name_a else None
        horse_name = _clean(_text(tds[2]))
        p = tds[5].find("p")
        raw = _clean(_text(p) if p else _text(tds[5]))
        headline = None
        trainer = None
        comment = raw
        if raw:
            m = re.search(r"([^\s　]+師)\s*――\s*(.+)", raw)  # 新書式
            if m:
                trainer = m.group(1)
                comment = m.group(2).strip()
                m2 = re.search(r"[（(]([^）)]+)[）)]", raw)
                if m2:
                    headline = m2.group(1)
            else:
                m3 = re.search(r"[【\[]([^】\]]+)[】\]]\s*(.+)", raw)  # 旧書式（見出し無し）
                if m3:
                    trainer = m3.group(1)
                    comment = m3.group(2).strip()
        if umaban is None:
            continue
        horses.append({
            "umaban": umaban, "horse_id": horse_id, "horse_name": horse_name,
            "headline": headline, "trainer": trainer, "comment": comment, "raw": raw,
        })
    return {"race_id": race_id, "horses": horses}


# ---------------------------------------------------------------- nouryoku（能力表）

# 過去5走の頭トークン: 回+場+日次。日次の装飾が馬場状態（○囲み=良・素数字=稍重・黒丸=重）
_C_WHITE = {chr(0x2460 + i) for i in range(20)}   # ①〜⑳
_C_BLACK = {chr(0x2776 + i) for i in range(10)} | {chr(0x24EB + i) for i in range(10)}  # ❶〜❿⓫〜⓴


def _parse_nouryoku_run(text):
    """過去1走分のテキストを構造化（例:
    '1福① 4.11 未勝 16頭 16 2000芝2.03.5 大久保友 54 M 36.1-38.2 8 8 8 11 メイショウハ 3.5 486 16枠16人'）"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or len(text) < 10:
        return None
    run = {
        "raw": text,
        # A structured eligibility flag is persisted so downstream feature
        # code never has to inspect free text.  The shared classifier includes
        # 能力・調教・再調教・総合調教・ゲート試験 and 発走検査.
        "is_trial": is_trial_event_text(text),
    }
    toks = text.split(" ")
    m = re.match(r"^(\d{0,2})([^\d\s]+?)([①-⑳❶-❿⓫-⓴\d]{0,2})$", toks[0])
    if m:
        run["track"] = m.group(2)
        day = m.group(3)
        if day:
            ch = day[0]
            run["going"] = "良" if ch in _C_WHITE else "重" if ch in _C_BLACK else "稍重" if ch.isdigit() else None
    m = re.search(r"(?:^|\s)(\d{1,2})\.(\d{1,2})(?:\s|$)", text)
    if m:
        # The ability table contains no year.  Month/day are display facts;
        # an exact date is attached later only by the official-result linker.
        run["provisional_mm"], run["provisional_dd"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)頭\s+(\S+)", text)
    if m:
        run["heads"] = int(m.group(1))
        fin = m.group(2)
        run["fin"] = int(fin) if fin.isdigit() else None
        if not fin.isdigit():
            run["fin_note"] = fin
    m = re.search(r"(\d{3,4})(ダ|芝)(?:\((.)\))?((?:\d\.)?\d{1,2}\.\d)", text)
    if m:
        run["dist"] = int(m.group(1))
        run["surface"] = m.group(2)
        if m.group(3):
            run["going"] = {"良": "良", "稍": "稍重", "重": "重", "不": "不良"}.get(m.group(3), m.group(3))
        run["time"] = m.group(4)
        run["tsec"] = time_to_sec(m.group(4))
    m = re.search(r"\s(\d{2}(?:\.\d)?)\s+([SMH])\s+(\d{2}\.\d)-(\d{2}\.\d)", text)
    if m:
        run["kin"] = float(m.group(1))
        run["pace"] = m.group(2)
        run["f3"] = float(m.group(3))
        run["l3"] = float(m.group(4))
    m = re.search(r"(\d{3})\s+(\d{1,2})枠(\d{1,2}|-)人", text)
    if m:
        run["weight"] = int(m.group(1))
        run["waku"] = int(m.group(2))
        run["pop"] = int(m.group(3)) if m.group(3).isdigit() else None
    return run


# ---- 読み違いの番人(2026-10-10 監査 中 #10)。能力表は列を位置(cells[0..11])で読む。
#   ① 列のずれ= 馬名の印(span.kbamei の馬リンク)が 5 列目(cells[4])に無く、ほかの列にある行
#   ② 過去走の値の範囲= 斤量 40〜70kg・前後 3F 30〜60 秒(外れの走は runs に入れない)
#   ①が 1 行でもある・②の外れが NR_GUARD_N 走以上で、かつ NR_GUARD_HORSES 頭以上にまたがるか走の NR_GUARD_SHARE 以上の頁は
#   NouryokuGuard(呼び側が頁ごとに捨てる= 書かない)。1〜2 頭に固まる外れはその走だけ捨てる
#   (10/10 13:17 便= 1 頭の 1000m 戦の前半 22〜25 秒で 10/11 の 4 頁を丸ごと捨て、ほかの馬の過去走まで落とした)。
NR_KIN = (40.0, 70.0)
NR_3F = (30.0, 60.0)
NR_GUARD_N = 3
NR_GUARD_HORSES = 3
NR_GUARD_SHARE = 0.3


class NouryokuGuard(ValueError):
    """能力表の頁の様式が想定と違う(列のずれ・値の外れ)。"""


NOURYOKU_GUARD = []      # 番人が捨てた頁(呼び側が最後に数えて終了コード 1)


def nouryoku_run_bad(run):
    """過去 1 走の外れ → 理由(空= 通す)。"""
    k = run.get("kin")
    if k is not None and not (NR_KIN[0] <= k <= NR_KIN[1]):
        return f"斤量 {k}"
    for key in ("f3", "l3"):
        v = run.get(key)
        if v is not None and not (NR_3F[0] <= v <= NR_3F[1]):
            return f"{'前' if key == 'f3' else '後'}3F {v}"
    return ""


def parse_nouryoku(html, race_id=None):
    """能力表ページ → {race, horses: [{umaban, name, pedigree, stable, seiseki, runs}]}
    ※RT/CPU/展開予想列は現状 display:none で空（取れる時に備えて拾う）
    列のずれ・値の外れが多い頁は NouryokuGuard。"""
    soup = BeautifulSoup(html, "lxml")
    race = _parse_race_header(soup, race_id)
    horses = []
    shifted, bad_runs, bad_horses, n_runs = [], [], set(), 0
    table = soup.select_one("table.nouryoku_html_table")
    if table:
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 12:
                continue
            cells = [_text(td) for td in tds]
            umaban = _int(cells[1])
            if umaban is None:
                continue
            ped = cells[4].split(" ")
            ped_cell = tds[4]
            horse_anchor = ped_cell.select_one("span.kbamei a[href*='/db/uma/']")
            if horse_anchor is None and any(td.select_one("span.kbamei a[href*='/db/uma/']") for td in tds):
                shifted.append(umaban)
            horse_name = _clean(_text(horse_anchor))
            horse_id = None
            if horse_anchor is not None:
                match = re.search(r"/db/uma/([^/?#]+)", horse_anchor.get("href") or "")
                if match:
                    horse_id = unquote(match.group(1)) or None
            father_span = ped_cell.select_one("span.tkbamei")
            mother_span = ped_cell.select_one("span.hkbamei")
            bms_span = ped_cell.select_one("span.htkbamei")
            mother_dl = mother_span.find_parent("dl") if mother_span is not None else None
            color = _clean(_text(mother_dl.find("dd"))) if mother_dl is not None else None
            jk = re.search(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", cells[3])
            stable_toks = cells[5].split(" ")
            packs = cells[6].split(" ")
            runs = []
            for slot, cell_index in enumerate(range(7, 12)):
                run = _parse_nouryoku_run(cells[cell_index])
                bad = nouryoku_run_bad(run) if run else ""
                n_runs += 1 if run else 0
                if bad:
                    bad_runs.append(f"{umaban}番 {slot + 1}列目 {bad}")
                    bad_horses.add(umaban)
                    continue
                if run:
                    # Preserve the physical five-run display slot, including
                    # gaps; it is never used to invent a calendar year.
                    run["provisional_order"] = slot
                    runs.append(run)
            horses.append({
                "umaban": umaban,
                "waku": _int(cells[0]),
                "rt": _num(cells[2]),                        # 現状は常にNone
                "horse_id": horse_id,
                # Semantic markup is authoritative.  The split-text fallback
                # is retained only for old/minimal pages without those spans.
                "name": horse_name or (ped[2] if len(ped) > 2 else None),
                "pedigree": {
                    "father": _clean(_text(father_span)) or (ped[0] if ped else None),
                    "mother": _clean(_text(mother_span)) or (ped[3] if len(ped) > 3 else None),
                    "color": color or (ped[4] if len(ped) > 4 else None),
                    "bms": _clean(_text(bms_span)) or (ped[5] if len(ped) > 5 else None),
                },
                "jockey_stats": ".".join(jk.groups()) if jk else None,
                "stable": {"name": stable_toks[0] if stable_toks else None,
                           "zenseki": stable_toks[1] if len(stable_toks) > 1 else None,
                           "rentai_kyaku": stable_toks[2] if len(stable_toks) > 2 else None},
                "seiseki": {"tougai": packs[0] if packs else None,
                            "chihou": packs[1] if len(packs) > 1 else None,
                            "chuo": packs[2] if len(packs) > 2 else None},
                "runs": runs,   # 5走前→前走（他場・中央・能力試験含む、テン/上がり付き）
            })
    why = ""
    if shifted:
        why = f"能力表 {race_id} 列のずれ(馬名が5列目に無い) {len(shifted)} 頭: {shifted[:5]}"
    elif len(bad_runs) >= NR_GUARD_N and (len(bad_horses) >= NR_GUARD_HORSES
                                          or len(bad_runs) >= NR_GUARD_SHARE * max(n_runs, 1)):
        why = f"能力表 {race_id} 値の外れ {len(bad_runs)} 走: " + " / ".join(bad_runs[:5])
    if why:
        NOURYOKU_GUARD.append(why)
        raise NouryokuGuard(why)
    for b in bad_runs:
        print(f"::warning::能力表 {race_id} 書かない走 {b}", flush=True)
    return {"race_id": race_id, "race": race, "horses": horses}


# ---------------------------------------------------------------- syutuba

def parse_syutuba(html, race_id=None):
    """出馬表ページ → {race: {...}, entries: [...]}"""
    soup = BeautifulSoup(html, "lxml")
    race = _parse_race_header(soup, race_id)

    entries = []
    table = soup.select_one("table.syutuba")
    if table:
        header_tr = table.find("tr")
        headers = [_text(th) for th in header_tr.find_all(["th", "td"])] if header_tr else []
        # My印〜本紙の間はトラックマン名の予想印列
        try:
            mark_from = headers.index("My印") + 1
            mark_to = headers.index("本紙") + 1
        except ValueError:
            mark_from = mark_to = -1

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) != len(headers) or not headers:
                continue
            cells = [_text(td) for td in tds]
            row = dict(zip(headers, cells))
            umaban = _int(row.get("馬番"))
            if umaban is None:
                continue
            name_idx = headers.index("馬名") if "馬名" in headers else None
            marks = {}
            if mark_from > 0:
                for i in range(mark_from, mark_to):
                    marks[headers[i] or f"col{i}"] = _clean(cells[i])
            # ブリンカー列（本紙と馬名の間の「ブリンカ」列・値="B"）を拾う。当日の初ブリンカー判定用。
            blk = _clean(row.get("ブリンカ"))
            if blk:
                marks["blinker"] = blk
            row_text = _text(tr)
            row_classes = set(tr.get("class") or [])
            status = (
                "取消"
                if "torikesi" in row_classes
                else next((marker for marker in ("取消", "除外") if marker in row_text), None)
            )
            entries.append({
                "umaban": umaban,
                "waku": _int(row.get("枠番")),
                "horse_id": _db_id(tds[name_idx], "uma") if name_idx is not None else _db_id(tr, "uma"),
                "horse_name": _clean(re.sub(r"[★☆]", "", row.get("馬名", ""))),
                "sex_age": _clean(row.get("性齢")),
                "genryo": _clean(row.get("減量")),
                "jockey": _clean(row.get("騎手")),
                "kinryo": _num(row.get("斤量")),
                "trainer": _clean(row.get("厩舎")),
                "body_weight": _int(row.get("馬体重(kg)")),
                "weight_diff": _int(row.get("増減")),
                "win_odds": _num(row.get("単勝")),
                "pop": _int(row.get("人気")),
                "marks": marks,
                # §119a 馬具の履歴用。marks の中と同じ値を**行の鍵**にも出す(⛔marks は触らない)
                "blinker": marks.get("blinker"),
                "status": status,
            })
    return {"race": race, "entries": entries}

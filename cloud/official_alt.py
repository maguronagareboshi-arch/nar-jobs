#!/usr/bin/env python3
"""公式の日次ZIPの保険(2026-10-14 夕方 ZIP が 1 時間半止まり、戻った後も 30 分は中身が古く、体重・着順・払戻が入らなかった直し)。
保険はこのファイル 1 つだけ。正はいつも ZIP で、ここは「ZIP の後でまだ空の欄」を画面から読んで埋めるだけ(ZIP が戻れば ZIP の行に置き換わる)。

  体重・馬場: 出馬表の画面を 公式 → 南関の公式(南関 4 場だけ)→ 楽天競馬 の順に。次へ進むのは読めない時だけ(落ちている・形が違う)
  着順・払戻: 公式の成績の画面(RaceMarkTable)

  使う所(3 つの便とも、呼ぶのはここだけ):
    refresh.py        after_zip(url, key, today, zip_down)  … ZIP の投入の後に毎回。空の体重・着順・払戻を埋め、見張り official_zip を書く
    v29_gap.py        alt_today(day, [(場, R)])              … 当日版の印に要るレースの体重が ZIP にも DB にも無い時
    ai_last_today.py  alt_today(day, [(場, R)])              … 他の場の直前便。待ちのレースの体重が ZIP に無い時

⛔負荷: 読むのは「体重が 1 頭も無い・発走 60 分前〜」「着順が 1 頭も無い・発走 5 分後〜3 時間」のレースだけ。1 枚ごとに 1 秒あける。
   正しく読めて「まだ発表前・まだ確定前」ならそこで止める(他の所も同じなので見に行かない)。
⛔書く: 空の欄だけ(体重が空の走・着順も注記も空の走・払戻の行の無いレース)。値のある行は上書きしない。上がり 3F は ZIP に無い列なので書かない。
場コードは rakuten_sales.BABA と同じ(keiba.go.jp と楽天は同じ番号・南関の公式も 18〜21 が同じ)。
"""
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "pipeline"):  # kochi_results・nar_official_csv(cloud)と load_nar_official(pipeline)
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BABA = {
    "帯広ば": "3", "門別": "36", "盛岡": "10", "水沢": "11", "浦和": "18", "船橋": "19",
    "大井": "20", "川崎": "21", "金沢": "22", "笠松": "23", "名古屋": "24",
    "園田": "27", "姫路": "28", "高知": "31", "佐賀": "32",
}
NANKAN = {"浦和", "船橋", "大井", "川崎"}
GAP_S, TIMEOUT = 1.0, 20
WEIGHT_AHEAD_MIN = 60                     # 体重はふつう発走 50 分前ごろに出る
RESULT_FROM_MIN, RESULT_TO_MIN = 5, 180   # 着順は発走 5 分後〜3 時間
STALE_MIN = 40                            # ZIP が取れたのに発走 40 分後でも着順が無い= ZIP の中身が古い
OFFICIAL = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/"
PAGE_TICKETS = {"単勝": "win", "複勝": "place", "馬連複": "quinella", "馬連単": "exacta", "枠連複": "wakuren",
                "枠連単": "wakutan", "ワイド": "wide", "三連複": "trio", "三連単": "trifecta"}


def _get(url, enc="utf-8"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode(enc, "replace")


def _official_url(page, day, track, rno):
    return (OFFICIAL + page + "?k_raceDate=" + urllib.parse.quote(dt.date.fromisoformat(day).strftime("%Y/%m/%d"), safe="")
            + f"&k_raceNo={rno}&k_babaCode={BABA[track]}")


# ================================================================ 体重・馬場(出馬表の画面)

def _weight(cell):
    """'406 <br>(-2)'・'406<br /> -2'・'503<br> ±0' → (406, -2)。発表前('' や '-')・読めない → None"""
    t = re.sub(r"<[^>]+>", " ", cell or "").replace("＋", "+").replace("－", "-").replace("−", "-").replace("±", "")
    m = re.search(r"\b(\d{3})\b\s*\(?\s*([+-]?\s*\d{1,3})?\s*\)?", t)
    if not m or not 250 <= int(m.group(1)) <= 750:
        return None
    ch = m.group(2)
    return int(m.group(1)), (int(ch.replace(" ", "")) if ch not in (None, "") else None)


def _rows(html, num_pat, cell_pat):
    """馬番の印 num_pat で区切り、各区切りの最初の体重の欄 cell_pat を読む → {馬番: (体重, 増減)}"""
    parts = re.split(num_pat, html)
    if len(parts) < 3:  # 馬番の印が 1 つも無い= 出馬表の形でない(障害の画面・様式替え)。「発表前」と区別して次の所へ
        raise ValueError("出馬表の形でない")
    out = {}
    for i in range(1, len(parts) - 1, 2):
        m = re.search(cell_pat, parts[i + 1], re.S)
        w = _weight(m.group(1)) if m else None
        if w:
            out[int(parts[i])] = w
    return out


def _going(html, pat):
    m = re.search(pat, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))
    return m.group(1) if m else None


def from_official_page(day, track, rno):
    h = _get(_official_url("DebaTable", day, track, rno))
    return (_rows(h, r'class="horseNum">\s*(\d+)\s*</td>', r'class="odds_weight">(.*?)</td>'),
            _going(h, r"馬場：\s*(稍重|不良|良|重)"))


_NK_PROG = {}


def _nk_program(day, track):
    """南関の公式の開催の 14 桁(日付 8・場 2・回 2・日 2)。カレンダーの今の月 → その月の順に探す(1 日 1 回)"""
    if (day, track) not in _NK_PROG:
        ds, found = day.replace("-", ""), None
        for path in ("/calendar/000000.do", f"/calendar/{ds[:6]}.do"):
            try:
                h = _get("https://www.nankankeiba.com" + path, enc="cp932")
            except Exception:  # noqa: BLE001
                continue
            ids = sorted({x for x in re.findall(r"/program/(\d{14})\.do", h) if x[:8] == ds and x[8:10] == BABA[track]})
            if ids:
                found = ids[0]
                break
            time.sleep(GAP_S)
        _NK_PROG[(day, track)] = found
    return _NK_PROG[(day, track)]


def from_nankankeiba(day, track, rno):
    if track not in NANKAN:
        raise LookupError("南関の場でない")
    p = _nk_program(day, track)
    if not p:
        raise LookupError("南関の公式に開催が見つからない")
    time.sleep(GAP_S)
    h = _get(f"https://www.nankankeiba.com/uma_shosai/{p}{int(rno):02d}.do", enc="cp932")
    return _rows(h, r"writeOdds\((\d+)\)", r'nk23_c-table23__txt2">(.*?)</td>'), None


def from_rakuten(day, track, rno):
    h = _get(f"https://keiba.rakuten.co.jp/race_card/list/RACEID/{day.replace('-', '')}{int(BABA[track]):02d}000000{int(rno):02d}")
    return (_rows(h, r'class="number">\s*(\d+)\s*</td>', r'class="weightDistance">(.*?)</td>'),
            _going(h, r"(?:ダ|芝)：\s*(稍重|不良|良|重)"))


SOURCES = (("公式の出馬表", from_official_page), ("南関の公式", from_nankankeiba), ("楽天競馬", from_rakuten))


def alt_today(day, need, log=print):
    """need= [(場, R)] → (wt, go, src)= ({(場, R): {馬番: (体重, 増減)}}, {(場, R): 馬場}, {(場, R): 読めた所})。
    読めない・発表前のレースは返さない(呼ぶ側は今までどおりの値のまま)"""
    wt, go, src = {}, {}, {}
    for track, rno in sorted({(t, int(r)) for t, r in need if t in BABA}):
        tried = []
        for name, fn in SOURCES:
            try:
                w, g = fn(day, track, rno)
            except Exception as e:  # noqa: BLE001  読めない時だけ次の所へ
                tried.append(f"{name}×{type(e).__name__}")
                time.sleep(GAP_S)
                continue
            if g:
                go.setdefault((track, rno), g)
            if w:
                wt[(track, rno)], src[(track, rno)] = w, name
            else:
                tried.append(f"{name} 発表前")
            break
        log(f"[保険] {track}{rno}R 体重: " + (f"{src[(track, rno)]} から {len(wt[(track, rno)])} 頭" if (track, rno) in src
                                             else "無し") + (f"({'・'.join(tried)})" if tried else ""))
        time.sleep(GAP_S)
    return wt, go, src


# ================================================================ 着順・払戻(成績の画面)

def page_payouts(html):
    """成績の画面の払戻の表 → [{t, c, y, p}](load_nar_official.group_payouts と同じ形・同じ並び。川崎 5R で ZIP と 11 件一致)。
    券種名の無い行は前の券種の続き(複勝・ワイド)"""
    import kochi_results
    from nar_official_csv import canonical_combination
    p = kochi_results._Tables()
    p.feed(html)
    out, cur = [], None
    for t in p.tables:
        for row in t:
            cells = [c.strip() for c in row]
            if cells and cells[0] in PAGE_TICKETS:
                cur, cells = PAGE_TICKETS[cells[0]], cells[1:]
            if not cur or len(cells) < 2 or not re.fullmatch(r"\d+(?:-\d+)*", cells[0]):
                continue
            y, pop = re.sub(r"[^\d]", "", cells[1]), re.sub(r"[^\d]", "", cells[2]) if len(cells) > 2 else ""
            if not y:
                continue
            try:
                c = canonical_combination(cur, cells[0].split("-"))
            except (TypeError, ValueError):
                continue
            out.append({"t": cur, "c": c, "y": int(y), "p": int(pop) if pop else None})
    return sorted(out, key=lambda x: (x["t"], x["c"]))


def read_result(day, track, rno):
    """成績の画面 → (走の更新 {馬番: 列}, 払戻)。確定前(画面なし・速報で上位 3 頭だけ・タイム空)は None"""
    import kochi_results
    from load_nar_official import time_to_sec
    html = _get(_official_url("RaceMarkTable", day, track, rno))
    parsed = kochi_results.parse_mark_table(html)
    if not parsed:
        return None
    placed = [h for h in parsed["horses"] if (h.get("chakujun") or "").strip().isdigit()]
    if len(placed) < 4 or any(not re.sub(r"[^\d]", "", h.get("time") or "") for h in placed):
        return None  # 速報= 確定の全頭が出てから(途中で書くと残りが二度と埋まらない)
    runs = {}
    for h in parsed["horses"]:
        ch = (h.get("chakujun") or "").strip()
        ok = ch.isdigit()
        raw = re.sub(r"[^\d]", "", h.get("time") or "").lstrip("0") or None
        diff = (h.get("diff") or "").strip() or None
        note = None if ok else (ch or None)
        if diff and re.search(r"(取消|除外|中止|失格|降着)", diff):
            note, diff = note or diff, None
        pop = (h.get("ninki") or "").strip()
        runs[int(h["uma_ban"])] = {"finish": int(ch) if ok else None, "finish_note": note,
                                   "time_raw": raw if ok else None, "time_sec": time_to_sec(raw) if ok else None,
                                   "margin": diff, "popularity": int(pop) if pop.isdigit() else None}
    return runs, page_payouts(html)


# ================================================================ refresh から: ZIP の後に空の欄を埋め、見張りを書く

def _rest(url, key, path, method="GET", body=None):
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode("utf-8"),
                                 headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None


def _post_at(today, pt):
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})", str(pt or "").strip())
    return dt.datetime.combine(today, dt.time(int(m.group(1)), int(m.group(2))), JST) if m else None


def after_zip(url, key, today, zip_down, log=print):
    """ZIP の投入の後に毎回呼ぶ。開催の無い日は何も読まない。
    見張り official_zip: ZIP が取れない(JST 10 時以降)か、取れても中身が古い(発走 40 分後でも着順が無かった)→ fail、それ以外 ok"""
    import beat
    d = today.isoformat()
    races = [r for r in _rest(url, key, f"nar_races?race_date=eq.{d}&select=track,race_no,post_time,going,cancelled")
             if not str(r.get("cancelled") or "").strip() and r["track"] in BABA]
    if not races:
        beat.beat("official_zip", True, "開催なし")
        return
    runs = _rest(url, key, f"nar_runs?race_date=eq.{d}&select=track,race_no,runner_number,body_weight,finish,finish_note")
    has_w = {(r["track"], int(r["race_no"])) for r in runs if r.get("body_weight") is not None}
    has_f = {(r["track"], int(r["race_no"])) for r in runs if r.get("finish") is not None}  # ⛔取消の注記は出馬表の段で入るので数えない
    has_p = {(r["track"], int(r["race_no"])) for r in _rest(url, key, f"nar_race_payouts?race_date=eq.{d}&select=track,race_no")}
    now = dt.datetime.now(JST)
    w_need, r_need, mins = [], [], {}
    for r in races:
        k, at = (r["track"], int(r["race_no"])), _post_at(today, r.get("post_time"))
        if at is None:
            continue
        mins[k] = (now - at).total_seconds() / 60  # 発走から何分(前は負)
        if k not in has_w and -WEIGHT_AHEAD_MIN <= mins[k] <= RESULT_TO_MIN:
            w_need.append(k)
        if k not in has_f and RESULT_FROM_MIN <= mins[k] <= RESULT_TO_MIN:
            r_need.append(k)
    q = urllib.parse.quote
    # 体重: 1 頭も無いレースだけ(取消の馬が空のままのレースは読まない)・空の走にだけ書く・馬場は空のレースだけ
    try:
        wt, go, _ = alt_today(d, w_need, log=log) if w_need else ({}, {}, {})
        empty_go = {(r["track"], int(r["race_no"])) for r in races if not str(r.get("going") or "").strip()}
        for (t, rno), v in wt.items():
            for num, (bw, ch) in v.items():
                _rest(url, key, f"nar_runs?race_date=eq.{d}&track=eq.{q(t)}&race_no=eq.{rno}&runner_number=eq.{num}&body_weight=is.null",
                      "PATCH", {"body_weight": bw, "body_weight_change": ch})
        for (t, rno), g in go.items():
            if (t, rno) in empty_go:
                _rest(url, key, f"nar_races?race_date=eq.{d}&track=eq.{q(t)}&race_no=eq.{rno}", "PATCH", {"going": g})
    except Exception as e:  # noqa: BLE001  埋められなくても便は止めない
        log(f"[保険] 体重: 失敗({type(e).__name__}: {str(e)[:160]})")
    # 着順・払戻: 着順が 1 頭も無いレースだけ・着順も注記も空の走にだけ・払戻は行の無いレースだけ
    late = []
    for t, rno in sorted(r_need):
        time.sleep(GAP_S)
        try:
            got = read_result(d, t, rno)
            if not got:
                continue
            for num, body in got[0].items():
                _rest(url, key, f"nar_runs?race_date=eq.{d}&track=eq.{q(t)}&race_no=eq.{rno}&runner_number=eq.{num}"
                      "&finish=is.null&finish_note=is.null", "PATCH", body)
            if (t, rno) not in has_p and got[1]:
                _rest(url, key, "nar_race_payouts?on_conflict=track,race_date,race_no", "POST",
                      [{"track": t, "race_date": d, "race_no": rno, "payouts": got[1], "source_snapshot_hash": "racemarktable-html",
                        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
            log(f"[保険] {t}{rno}R 着順: 成績の画面から {len(got[0])} 頭・払戻 {'足した' if (t, rno) not in has_p and got[1] else 'そのまま'}")
            if mins[(t, rno)] >= STALE_MIN:
                late.append(f"{t}{rno}R")
        except Exception as e:  # noqa: BLE001  1 レース落ちても次へ
            log(f"[保険] {t}{rno}R 着順: 読めない({type(e).__name__}: {str(e)[:100]})")
    if zip_down and now.hour >= 10:
        beat.beat("official_zip", False, f"{d} 開催ありなのに日次ZIPが取れない(画面から埋めた)")
    elif not zip_down and late:
        beat.beat("official_zip", False, f"{d} 日次ZIPの中身が古い({' '.join(late)} の着順が無く、画面から埋めた)")
    elif not zip_down:
        beat.beat("official_zip", True)


if __name__ == "__main__":  # 手で試す(読むだけ): python cloud/official_alt.py 2026-10-14 川崎 7 [--each]
    import sys
    day, track, rno = sys.argv[1], sys.argv[2], int(sys.argv[3])
    if "--each" in sys.argv:
        for name, fn in SOURCES:
            try:
                w, g = fn(day, track, rno)
                print(name, len(w), "頭", "馬場", g, sorted(w.items()))
            except Exception as e:  # noqa: BLE001
                print(name, "失敗", type(e).__name__, e)
            time.sleep(GAP_S)
    else:
        print(alt_today(day, [(track, rno)]))
        got = read_result(day, track, rno)
        print("着順", None if not got else sorted((n, b["finish"]) for n, b in got[0].items()), "払戻", None if not got else len(got[1]))

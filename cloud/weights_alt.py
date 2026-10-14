#!/usr/bin/env python3
"""当日の馬体重・馬場の代わりの道(2026-10-14 公式の当日 ZIP が 17 時前から全日付で「ファイルをダウンロードできませんでした」
になり、川崎 7R から直前版の印が出なかった直し)。公式の当日 ZIP が取れないときだけ、要るレースの出馬表の画面を 1 枚ずつ読む。

  順番(レースごとに、体重が 1 頭でも読めた所で止める):
    1. 公式の出馬表の画面  keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable(ZIP と同じ運営だが別の入口・10/14 は画面は生きていた)
    2. 南関の公式          nankankeiba.com/uma_shosai/{開催 14 桁}{R}.do(南関 4 場だけ・別の運営)
    3. 楽天競馬            keiba.rakuten.co.jp/race_card/list/RACEID/{日付}{場}000000{R}(全場・別の運営)

  from weights_alt import alt_today
  wt, go, src = alt_today('2026-10-14', [('川崎', 7)])
  → wt= {(場, R): {馬番: (体重, 増減)}}・go= {(場, R): 馬場}・src= {(場, R): 読めた所の名前}

⛔読むだけ(どこにも書かない)。⛔要るレースだけ・1 枚ごとに 1 秒あける(相手に負荷をかけない)。
⛔読めない・体重がまだ(発表前は空や「-」)のレースは返さない= 呼ぶ側は今までどおり DB の値か前の値のまま。
⛔次の所へ進むのは読めなかった時(落ちている・出馬表の形でない)だけ。正しく読めて発表前なら、そこで止める。
場コードは rakuten_sales.BABA と同じ(keiba.go.jp と楽天は同じ番号・南関の公式も 18〜21 が同じ)。
"""
import datetime as dt
import re
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BABA = {
    "帯広ば": "3", "門別": "36", "盛岡": "10", "水沢": "11", "浦和": "18", "船橋": "19",
    "大井": "20", "川崎": "21", "金沢": "22", "笠松": "23", "名古屋": "24",
    "園田": "27", "姫路": "28", "高知": "31", "佐賀": "32",
}
NANKAN = {"浦和", "船橋", "大井", "川崎"}
GOINGS = ("稍重", "不良", "良", "重")  # 稍重・不良を先に(「重」が先に当たらないように)
GAP_S = 1.0
TIMEOUT = 20


def _get(url, enc="utf-8"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode(enc, "replace")


def _weight(cell):
    """'406 <br>(-2)'・'406<br /> -2'・'503<br> ±0' → (406, -2)。発表前('' や '-')・読めない → None"""
    t = re.sub(r"<[^>]+>", " ", cell or "").replace("＋", "+").replace("－", "-").replace("−", "-").replace("±", "")
    m = re.search(r"\b(\d{3})\b\s*\(?\s*([+-]?\s*\d{1,3})?\s*\)?", t)
    if not m:
        return None
    bw = int(m.group(1))
    if not 250 <= bw <= 750:
        return None
    ch = m.group(2)
    return bw, (int(ch.replace(" ", "")) if ch not in (None, "") else None)


def _rows(html, num_pat, cell_pat):
    """馬番の印 num_pat で区切り、各区切りの最初の体重の欄 cell_pat を読む → {馬番: (体重, 増減)}"""
    out = {}
    parts = re.split(num_pat, html)
    if len(parts) < 3:  # 馬番の印が 1 つも無い= 出馬表の形でない(障害の画面・様式替え)。「発表前」と区別して次の所へ
        raise ValueError("出馬表の形でない")
    for i in range(1, len(parts) - 1, 2):
        m = re.search(cell_pat, parts[i + 1], re.S)
        w = _weight(m.group(1)) if m else None
        if w:
            out[int(parts[i])] = w
    return out


def _going(text, pat):
    m = re.search(pat, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    return m.group(1) if m else None


def from_official_page(day, track, rno):
    d = dt.date.fromisoformat(day)
    url = ("https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate="
           + urllib.parse.quote(f"{d:%Y/%m/%d}", safe="") + f"&k_raceNo={rno}&k_babaCode={BABA[track]}")
    h = _get(url)
    w = _rows(h, r'class="horseNum">\s*(\d+)\s*</td>', r'class="odds_weight">(.*?)</td>')
    return w, _going(h, r"馬場：\s*(稍重|不良|良|重)")


_NK_PROG = {}


def _nk_program(day, track):
    """南関の公式の開催の 14 桁(日付 8・場 2・回 2・日 2)。カレンダーの今の月 → その月の順に探す"""
    key = (day, track)
    if key not in _NK_PROG:
        ds, code = day.replace("-", ""), BABA[track]
        found = None
        for path in ("/calendar/000000.do", f"/calendar/{ds[:6]}.do"):
            try:
                h = _get("https://www.nankankeiba.com" + path, enc="cp932")
            except Exception:  # noqa: BLE001
                continue
            ids = sorted({x for x in re.findall(r"/program/(\d{14})\.do", h) if x[:8] == ds and x[8:10] == code})
            if ids:
                found = ids[0]
                break
            time.sleep(GAP_S)
        _NK_PROG[key] = found
    return _NK_PROG[key]


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
    rid = f"{day.replace('-', '')}{int(BABA[track]):02d}000000{int(rno):02d}"
    h = _get(f"https://keiba.rakuten.co.jp/race_card/list/RACEID/{rid}")
    return (_rows(h, r'class="number">\s*(\d+)\s*</td>', r'class="weightDistance">(.*?)</td>'),
            _going(h, r"(?:ダ|芝)：\s*(稍重|不良|良|重)"))


SOURCES = (("公式の出馬表", from_official_page), ("南関の公式", from_nankankeiba), ("楽天競馬", from_rakuten))


def alt_today(day, need, log=print):
    """need= [(場, R)] → (wt, go, src)。場コードの無い場・どこも読めないレースは返さない"""
    wt, go, src = {}, {}, {}
    for track, rno in sorted(set((t, int(r)) for t, r in need)):
        if track not in BABA:
            continue
        tried = []
        for name, fn in SOURCES:
            try:
                w, g = fn(day, track, rno)
            except Exception as e:  # noqa: BLE001  1 か所が落ちても次へ
                tried.append(f"{name}×{type(e).__name__}")
                time.sleep(GAP_S)
                continue
            if g and (track, rno) not in go:
                go[(track, rno)] = g
            if w:
                wt[(track, rno)] = w
                src[(track, rno)] = name
                break
            # 2026-10-14 夜: 出馬表が正しく読めて体重が空= まだ発表前。他の所も同じなので見に行かない(毎回の便で読むので負荷を抑える)
            tried.append(f"{name} 発表前")
            break
        log(f"[代わりの道] {track}{rno}R: " + (f"{src[(track, rno)]} から {len(wt[(track, rno)])} 頭" if (track, rno) in src
                                                 else "どこも体重なし") + (f"({'・'.join(tried)})" if tried else ""))
        time.sleep(GAP_S)
    return wt, go, src


if __name__ == "__main__":  # 手で試す: python cloud/weights_alt.py 2026-10-14 川崎 7 [--each]
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

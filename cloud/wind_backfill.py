# -*- coding: utf-8 -*-
"""風の過去分の取り込み: 気象庁「過去の気象データ」の 10 分値ページから、過去の開催日の風を nar_wind_obs へ足す。

  python3 cloud/wind_backfill.py --month YYYY-MM [--venue kochi|高知 ...] [--sleep 2] [--dry]

毎晩の便(wind_store.py)は 10 日前までしか取れないので、それより前はこちら。
開催日と窓(1R − 30 分 〜 最終 R)は wind_store の races_of / window_of と同じ。行の形・衝突キー(venue,obs_at)も同じ。
取り元= https://www.data.jma.go.jp/stats/etrn/view/10min_{s|a}1.php(1 地点 1 日 1 ページ・同じ地点の場は 1 回で共有)。
時刻は「その 10 分の終わり」(24:00 は翌日 0:00 なので、その日の分には入れない= 毎晩の便と同じ)。
風向は 16 方位の漢字 → 1〜16(北北東=1 … 北=16)。「静穏」と欠測・品質記号付きの値は null(毎晩の便は品質 0 だけ採用)。
降水量(precip・10 分間 mm)は見出し「降水量」の列。数字だけの値を採用・「--」(降水なし)は 0・品質記号付き・///・× は null。
取得の間隔は --sleep 秒(既定 2)。429/503/接続失敗は 5→15→45 秒待って 3 回まで取り直す。取れなかった日は最後に一覧で出す。
手動便なので heartbeat は呼ばない。⛔標準ライブラリだけ。
"""
import argparse
import calendar
import html as htmllib
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wind_store import venue_of, rest, races_of, window_of, in_window, log, _env, UA  # noqa: E402

ETRN = "https://www.data.jma.go.jp/stats/etrn/view/10min_{kind}1.php?prec_no={prec}&block_no={block}" \
       "&year={y}&month={m}&day={d}&view="
# アメダスの地点 ID(wind_store.VENUES の 3 列目) → (種別 s=気象台/a=アメダス, prec_no, block_no, 地点名)
ETRN_POINT = {
    "20432": ("s", "20", "47417", "帯広"),
    "22141": ("a", "22", "0136", "日高門別"),
    "33431": ("s", "33", "47584", "盛岡"),
    "33781": ("a", "33", "0236", "江刺"),
    "43241": ("a", "43", "0363", "さいたま"),
    "45106": ("a", "45", "1236", "船橋"),
    "44166": ("a", "44", "0371", "羽田"),
    "56227": ("s", "56", "47605", "金沢"),
    "52586": ("s", "52", "47632", "岐阜"),
    "53041": ("a", "53", "0500", "桑名"),
    "62051": ("a", "62", "0602", "豊中"),
    "63383": ("s", "63", "47769", "姫路"),
    "74182": ("s", "74", "47893", "高知"),
    "82306": ("a", "82", "0790", "久留米"),
}
DIRS16 = ["北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南",
          "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西", "北"]
DIR_CODE = {k: i + 1 for i, k in enumerate(DIRS16)}
WAIT = 2.0
RETRY_WAITS = (5, 15, 45)   # 429/503/接続失敗のときの待ち(秒)。最初の 1 回+取り直し 3 回

_TR = re.compile(r'<tr class="mtx"[^>]*>(.*?)</tr>', re.S)
_CELL = re.compile(r'<(t[hd])\b([^>]*)>(.*?)</t[hd]>', re.S)


def _text(s):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", s)).replace("　", " ").strip()


def _span(attrs, name):
    m = re.search(name + r'="(\d+)"', attrs)
    return int(m.group(1)) if m else 1


def _num(s):
    s = s.strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def _columns(head_rows):
    """見出しの行(rowspan/colspan 込み)→ 列ごとの見出しの道 [(上段, …, 下段), ...]。"""
    grid = {}
    for r, cells in enumerate(head_rows):
        c = 0
        for _, attrs, txt in cells:
            while (r, c) in grid:
                c += 1
            rs, cs = _span(attrs, "rowspan"), _span(attrs, "colspan")
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r + dr, c + dc)] = _text(txt)
            c += cs
    ncol = max(c for _, c in grid) + 1
    out = []
    for c in range(ncol):
        path = []
        for r in range(len(head_rows)):
            t = grid.get((r, c))
            if t is not None and (not path or path[-1] != t):
                path.append(t)
        out.append(tuple(path))
    return out


def _pick(cols):
    """列の番号 (時刻, 気温, 平均風速, 平均風向, 降水量)。s1 と a1 で並びが違うので見出しの名前で引く。"""
    def first(pred, start=0):
        for i in range(start, len(cols)):
            if pred(cols[i]):
                return i
        raise ValueError(f"列が見つからない: {cols}")
    wind = lambda p: any(x.startswith("風向・風速") for x in p)   # noqa: E731
    i_t = first(lambda p: p[-1] == "時分")
    i_temp = first(lambda p: p[-1].startswith("気温"))
    i_sp = first(lambda p: wind(p) and "平均" in p)
    i_dir = first(lambda p: wind(p) and p[-1] == "風向", i_sp + 1)
    i_pr = first(lambda p: p[0].startswith("降水量"))
    return i_t, i_temp, i_sp, i_dir, i_pr


def _precip(s):
    """降水量のセル → mm。「--」(降水なし)は 0・数字だけなら値・品質記号付き・///・× などは None。"""
    s = s.strip()
    if s == "--":
        return 0.0
    v = _num(s)
    return v if v is not None and v >= 0 else None


def parse_page(page):
    """過去データ 10 分値のページ → [{t, dir, speed, temp, precip}](t は HH:MM・24:00 は翌日なので落とす)。"""
    rows = [_CELL.findall(m) for m in _TR.findall(page)]
    head = [r for r in rows if r and all(tag == "th" for tag, _, _ in r)]
    body = [r for r in rows if r and any(tag == "td" for tag, _, _ in r)]
    if not head or not body:
        raise ValueError("表が無い")
    i_t, i_temp, i_sp, i_dir, i_pr = _pick(_columns(head))
    out = []
    for r in body:
        v = [_text(x[2]) for x in r]
        t = v[i_t]
        if not re.fullmatch(r"\d{2}:\d{2}", t) or t >= "24:00":
            continue
        sp = _num(v[i_sp])
        out.append({"t": t, "dir": DIR_CODE.get(v[i_dir]), "speed": sp if sp is not None and sp >= 0 else None,
                    "temp": _num(v[i_temp]), "precip": _precip(v[i_pr])})
    return out


def page_url(station, date):
    kind, prec, block, _ = ETRN_POINT[station]
    y, m, d = (int(x) for x in date.split("-"))
    return ETRN.format(kind=kind, prec=prec, block=block, y=y, m=m, d=d)


def _retryable(e):
    """取り直す失敗= 429/503・接続の失敗(時間切れ含む)。それ以外の HTTP の失敗(404 等)は取り直さない。"""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in (429, 503)
    return isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError, OSError))


def fetch_page(station, date, sleeper=time.sleep):
    url = page_url(station, date)
    for k in range(len(RETRY_WAITS) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:                            # noqa: BLE001
            if k >= len(RETRY_WAITS) or not _retryable(e):
                raise
            log(f"…{date} {station} {type(e).__name__}: {str(e)[:60]} → {RETRY_WAITS[k]} 秒待って取り直し")
            sleeper(RETRY_WAITS[k])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--venue", default="")
    ap.add_argument("--sleep", type=float, default=WAIT)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    if not a.sleep >= 0:
        log("要判断: --sleep は 0 以上の秒数")
        return 2
    if not re.fullmatch(r"\d{4}-\d{2}", a.month):
        log("要判断: --month は YYYY-MM")
        return 2
    want = None
    if a.venue.strip():
        v = venue_of(a.venue.strip())
        if v is None:
            log(f"要判断: 場が分からない {a.venue}")
            return 2
        want = v[0]
    url, key = _env()
    if not url or not key:
        log("要判断: SUPABASE_URL / SUPABASE_SERVICE_KEY が無い(nar_races が読めない)")
        return 2
    y, m = (int(x) for x in a.month.split("-"))
    dates = [f"{y:04d}-{m:02d}-{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)]
    n_fetch, n_rows, n_vd, failed, last = 0, 0, 0, [], 0.0
    for date in dates:
        races = races_of(date)
        bad = [t for t in races if t and venue_of(t) is None]
        if bad:
            log(f"要判断: 場の表に無い track {bad}")
            return 2
        cache = {}
        for track, times in races.items():
            prefix, name, station = venue_of(track)
            if want and prefix != want:
                continue
            if station not in ETRN_POINT:
                log(f"要判断: 過去データの地点が無い {name} {station}")
                return 2
            lo, hi = window_of(times)
            if station not in cache:
                wait = a.sleep - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
                try:
                    cache[station] = parse_page(fetch_page(station, date))
                except Exception as e:                    # noqa: BLE001
                    cache[station] = None
                    log(f"⚠{date} {name} 取れない: {type(e).__name__}: {str(e)[:80]}")
                last = time.monotonic()
                n_fetch += 1
            pts = cache[station]
            if pts is None:
                failed.append(f"{date} {name}")
                continue
            rows = [{"venue": prefix, "obs_at": f"{date}T{p['t']}:00+09:00",
                     "dir": p["dir"], "speed": p["speed"], "temp": p["temp"], "precip": p["precip"]}
                    for p in in_window(pts, lo, hi)]
            if rows and not a.dry:
                for i in range(0, len(rows), 60):
                    rest("nar_wind_obs?on_conflict=venue,obs_at", rows[i:i + 60])
            log(f"{date} {name}({prefix}) 窓 {lo}〜{hi} 行 {len(rows)}" + (" (dry)" if a.dry else ""))
            if rows:
                n_vd += 1
                n_rows += len(rows)
            else:
                failed.append(f"{date} {name}")
    ok = not failed
    log(("ok " if ok else "fail ") + f"{a.month} 取得 {n_fetch} 回 場日 {n_vd} 行 {n_rows}"
        + ("" if ok else f" 取れない {len(failed)} 件"))
    if failed:
        log("取れなかった場日の一覧:")
        for f in failed:
            log("  " + f)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

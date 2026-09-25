# -*- coding: utf-8 -*-
"""§286 兵庫(園田・姫路)の主催者の名簿「番組・馬連名簿」を週ごとに表 nar_hyogo_roster へ残す。

  出どころ= https://www.sonoda-himeji.jp/race/program/(1 ページに全区分・「令和8年度 兵庫県競馬組合営 9月4週※自場馬」)
  python cloud/hyogo_roster.py --dry-run [--out x.csv]     # 取得→解析→(DB が読めれば)code に結ぶ→CSV だけ
  python cloud/hyogo_roster.py --apply                     # 便(hyogo-roster.yml)。upsert→同じ週の古い行を消す→heartbeat
  python cloud/hyogo_roster.py --html saved.html --dry-run # 保存した HTML から(通信しない)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 取得・解析の失敗

週を当てる規則(week_start / roster_for_race):
  ① 「M月N週」は月曜はじまりの週で、その月の 1 日を含む週を 1 週と数える(2026-09: 8/31〜9/6 が 1 週 → 9月4週= 9/21〜9/27)。
  ② 発走前の値として、レース日 d には「week_start <= d の週のうち最も新しい週」の名簿を当てる(その週の月曜〜日曜のレースに効く)。
  ③ 年度は 4 月はじまり(令和8年度の 1〜3 月は 2027 年)。月末と月初にまたがる週は両方の呼び名がありうるが、どちらも同じ月曜になる。
"""
import argparse
import csv
import json
import datetime as dt
import html as htmlmod
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

URL = "https://www.sonoda-himeji.jp/race/program/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TABLE = "nar_hyogo_roster"
BEAT_JOB = "hyogo_roster"
TRACKS = ("園田", "姫路")
JST = dt.timezone(dt.timedelta(hours=9))
Z2H = str.maketrans("ＡＢＣ０１２３４５６７８９", "ABC0123456789")
COLS = ["week_label", "week_start", "fetched_at", "section", "horse_name", "code", "sex", "age",
        "points", "prize_yen", "cls", "trainer", "note", "home_mark"]


def log(*a):
    print(*a, flush=True)


# ---------- 週の規則 ----------
def week_start(fy_reiwa, month, nth):
    """令和 fy_reiwa 年度・month 月・第 nth 週 → その週の月曜(date)。規則は冒頭の①③。"""
    year = 2018 + int(fy_reiwa) + (1 if int(month) <= 3 else 0)
    first = dt.date(year, int(month), 1)
    return first - dt.timedelta(days=first.weekday()) + dt.timedelta(days=7 * (int(nth) - 1))


def roster_for_race(race_date, weeks):
    """規則②: weeks= [(week_label, week_start), ...] のうち race_date に当てる週の label(無ければ None)。"""
    got = [w for w in weeks if w[1] <= race_date]
    return max(got, key=lambda w: w[1])[0] if got else None


# ---------- 取得・解析 ----------
def fetch(url=URL):
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"取得できない: {type(last).__name__}: {str(last)[:160]}")


def _txt(s):
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", s)).replace("　", " ").strip()


def _int(s):
    s = re.sub(r"[,\s円点]", "", (s or "").translate(Z2H))
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def norm_section(t):
    t = t.translate(Z2H).replace(" ", "")
    if t.startswith("2歳"):
        return "2歳"
    m = re.search(r"([ABC]\d)$", t)
    return m.group(1) if m else t


def parse(h):
    m = re.search(r"令和\s*(\d+)\s*年度[^<]*?(\d+)\s*月\s*(\d+)\s*週", h.translate(Z2H))
    if not m:
        raise ValueError("週の表示(令和◯年度 ◯月◯週)が見つからない")
    fy, mo, nth = (int(x) for x in m.groups())
    label = f"R{fy} {mo}月{nth}週"
    ws = week_start(fy, mo, nth)
    rows, section, seen = [], None, set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, flags=re.S):
        th = re.findall(r"<th[^>]*>(.*?)</th>", tr, flags=re.S)
        if th:
            section = norm_section(_txt(th[0]))
            continue
        td = [_txt(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
        if len(td) < 8 or td[1] == "馬名" or not td[1] or section is None:
            continue
        mark, name, sex, age, val, cls, trainer, note = td[:8]
        k = (section, name, trainer)
        if k in seen:
            continue
        seen.add(k)
        v = _int(val)
        rows.append({"week_label": label, "week_start": ws.isoformat(), "section": section,
                     "horse_name": name, "code": None, "sex": sex or None, "age": _int(age),
                     "points": None if section == "2歳" else v, "prize_yen": v if section == "2歳" else None,
                     "cls": cls or None, "trainer": trainer, "note": note or None, "home_mark": mark == "※"})
    if not rows:
        raise ValueError("名簿の行が 0")
    return label, ws, rows


# ---------- code に結ぶ ----------
def sb_all(url, key, path, page=1000):
    out, off = [], 0
    while True:
        req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items",
            "Range": f"{off}-{off + page - 1}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read())
        out += got
        if len(got) < page:
            return out
        off += page


def _tn(s):
    return re.sub(r"[\s・.]", "", s or "")


def link_codes(url, key, rows, ws):
    """馬名+調教師(園田・姫路の出走)→生年→nar_horse_codes。同名は生年(= 年 − 齢)で絞る。戻り値= 結べた頭数。"""
    q = urllib.parse.quote
    since = (ws - dt.timedelta(days=730)).isoformat()
    names = sorted({r["horse_name"] for r in rows})
    runs, codes = [], []
    for i in range(0, len(names), 80):
        inq = q(",".join('"' + n + '"' for n in names[i:i + 80]))
        runs += sb_all(url, key, f"nar_runs?select=horse_name,birth_date,trainer,track,race_date,race_no,runner_number"
                                 f"&horse_name=in.({inq})&track=in.({q(','.join(TRACKS))})&race_date=gte.{since}"
                                 f"&order=race_date,track,race_no,runner_number")
        codes += sb_all(url, key, f"nar_horse_codes?select=code,horse_name,birth_date&horse_name=in.({inq})&order=code")
    by_run, by_code = {}, {}
    for r in runs:
        by_run.setdefault(r["horse_name"], set()).add((str(r.get("birth_date") or "")[:10], _tn(r.get("trainer"))))
    for c in codes:
        by_code.setdefault((c["horse_name"], str(c.get("birth_date") or "")[:10]), set()).add(c["code"])
    n = 0
    for r in rows:
        byear = ws.year - r["age"] if r["age"] else None
        t = _tn(r["trainer"])
        cand = {b for b, tt in by_run.get(r["horse_name"], ()) if b and t and (tt.startswith(t) or t.startswith(tt))}
        if not cand:   # 未出走(2歳など)= 馬名+生年だけで 1 つに決まるとき
            cand = {b for (nm, b) in by_code if nm == r["horse_name"] and b}
        if byear:
            cand = {b for b in cand if b[:4] == str(byear)}
        cs = set().union(*(by_code.get((r["horse_name"], b), set()) for b in cand)) if cand else set()
        if len(cs) == 1:
            r["code"] = cs.pop()
            n += 1
    return n


# ---------- 書く ----------
def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLS})


def apply_rows(url, key, label, rows):
    from load_nar_official import upsert
    for i in range(0, len(rows), 500):
        st, msg = upsert(url, key, TABLE, "week_label,section,horse_name,trainer", rows[i:i + 500])
        if st >= 300:
            raise RuntimeError(f"upsert {st} {msg}")
    # 同じ週を取り直したとき、今回の名簿から消えた馬の行を消す(今回の fetched_at より古いもの)
    fa = rows[0]["fetched_at"]
    path = (f"{TABLE}?week_label=eq.{urllib.parse.quote(label)}"
            f"&fetched_at=lt.{urllib.parse.quote(fa)}")
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method="DELETE", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="表へ書く(無ければドライラン)")
    ap.add_argument("--dry-run", action="store_true", help="CSV だけ(既定)")
    ap.add_argument("--out", help="CSV の出力先(既定= hyogo_roster_<週>.csv を今のフォルダーへ)")
    ap.add_argument("--html", help="保存した HTML を読む(通信しない)")
    a = ap.parse_args()
    apply_ = a.apply and not a.dry_run
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    import beat as B

    def say(ok, note):
        if apply_:
            B.beat(BEAT_JOB, ok, note)
        log(f"heartbeat {BEAT_JOB} {'ok' if ok else 'fail'} {note}" + ("" if apply_ else "(ドライラン= 書かない)"))

    try:
        h = open(a.html, encoding="utf-8").read() if a.html else fetch()
        label, ws, rows = parse(h)
    except Exception as e:
        log(f"::error::兵庫の名簿を取得・解析できない: {e}")
        say(False, f"取得失敗 {str(e)[:80]}")
        return 2
    fa = dt.datetime.now(JST).isoformat(timespec="seconds")
    for r in rows:
        r["fetched_at"] = fa
    secs = {}
    for r in rows:
        secs[r["section"]] = secs.get(r["section"], 0) + 1
    log(f"週= {label}(月曜 {ws})・{len(rows)} 頭・区分 {secs}")
    linked = None
    if url and key:
        try:
            linked = link_codes(url, key, rows, ws)
            log(f"code に結べた= {linked}/{len(rows)}")
        except Exception as e:
            log(f"::warning::code に結べない(code は空のまま): {type(e).__name__}: {str(e)[:160]}")
    else:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い= code は結ばない")
    out = a.out or f"hyogo_roster_{ws.isoformat()}.csv"
    write_csv(out, rows)
    log(f"CSV= {out}")
    if not apply_:
        return 0
    try:
        apply_rows(url, key, label, rows)
    except Exception as e:
        log(f"::error::投入失敗: {e}")
        say(False, f"投入失敗 週={label}")
        return 1
    say(True, f"週={label} n={len(rows)} code={linked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

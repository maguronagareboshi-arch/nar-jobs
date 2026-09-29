# -*- coding: utf-8 -*-
r"""§121(2026-09-07) 福ちゃん競馬新聞(高知)の最新号を保管し、陣営談話を読む。

  py -3.12 -u scraper/fetch_fukuchan.py                  # 公開ページを1回だけ見て、名前が変わっていれば PDF を落とす
  py -3.12 -u scraper/fetch_fukuchan.py --parse <pdf>    # 1本読んで data/fukuchan/{日付}.json
  py -3.12 -u scraper/fetch_fukuchan.py --parse-all      # data/fukuchan/ の PDF ぜんぶ(買った過去号もここに置く)
  py -3.12 -u scraper/fetch_fukuchan.py --parse-all --no-match   # 公式との突き合わせをしない(通信 0)

- 出どころ= 無料公開のバックナンバー頁 http://fukuchan.net/publics/index/176/ に**最新号 1 本だけ**。
  ⛔ページへの GET は 1 回/実行。⛔PDF を落とすのは**名前が変わったときだけ**(済み鍵= data/fukuchan/done.tsv)。
- 号の日付= 1 ページ目の「YYYY 年 M 月 / D / 日」の並び(D は頁で一番大きい数字)。読めなければ
  ファイル名の時刻の日付−1 日を仮に置き、JSON に date_assumed=true を残す(⛔仮であることを隠さない)。
- 談話= レース頁ごとに、馬名の行(左端の大きい字)で**行グリッド**を作り、その帯の中の
  **談話欄の x の幅だけ**を切って読む。⛔extract_text() は段組みが混ざるので使わない。
  ⛔読めない枠は talk=null で残す(推定しない)。
- 馬番= 紙面の並び順(馬柱は馬番順)。**公式(nar_runs)の 日付+R+馬番+馬名 が 4 つとも合った行だけ**
  matched=true。合わなければ matched=false のまま残す(⛔こちらの都合で番号を作らない)。
  ⚠§157 6-3(2026-09-12): 置き場(nar_paper_talks)に `matched` の列は無くなったので、
  この印は **JSON とこの便のログの中だけ**で使う(画面は公式の出馬表と突き合わせて数え直す)。
  ⛔それでも付け続ける= 読み違いをここで見つけるための印なので消さない。

⛔私的利用。⛔閲覧者には 1 字も出さない(1 ページ目に「本誌からの複製・転載を禁ず」)。
⛔PDF も JSON も git には入れない(data/ は git 外)。⛔本文をリポジトリに置かない。
⚠pdfplumber が要る。この PC では `py -3.12` に入っている(`py -3`= 3.13-32 には**無い**)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ["KB_DATA_DIR"]) if os.environ.get("KB_DATA_DIR") else HERE.parent / "data"   # cloud
OUT = DATA / "fukuchan"
DONE = OUT / "done.tsv"

PAGE = "http://fukuchan.net/publics/index/176/"
UA = "Mozilla/5.0 (personal archive)"
TIMEOUT = 60

# 公式(nar-official)の公開 anon= **読むだけ**。⛔書き込みの鍵はここには置かない
NAR_URL = "https://qgsnsdjvzzeazbazjlwa.supabase.co"
NAR_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFnc25zZGp2enplYXpiYXpqbHdhIiwi"
            "cm9sZSI6ImFub24iLCJpYXQiOjE3ODc0MTg0NDIsImV4cCI6MjEwMjk5NDQ0Mn0"
            ".a4pjf8WKgcVGL3d8ZBdP4dJDpnDkM2EnKofnXdHE2I8")
TRACK = "高知"

# 版面の当たり(2026-09-05 号で実測)。⚠毎回**頁から測り直し**、測れないときだけこの値を使う
NAME_X = (64.0, 71.0)          # 馬名の左端(この幅に始まる大きい字が馬名の行)
NAME_X1 = 300.0                # 馬名の右端
NAME_SIZE = 14.0               # 馬名の字の大きさの下限
FALLBACK_ROW_H = 58.2          # 1頭ぶんの高さ
FALLBACK_TALK_X = (955.0, 1066.0)
TALK_OFFSET = -17.9            # 馬名の行 → 談話の1行目(上へ 17.9)
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def log(msg):
    print(msg, flush=True)


def pdf_lib():
    """pdfplumber は**ここでだけ** import する(入っていない環境でも --help は動く)。"""
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber が要ります: py -3.12 -m pip install pdfplumber")
    return pdfplumber


def get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


# ---------------------------------------------------------------- 公開ページ → PDF

def latest_pdf(html):
    """バックナンバー頁から**最新号 1 本**の (URL, 元のファイル名)。無ければ (None, None)。

    ⛔最新号だけが無料公開= リンクは 1 種類しか出ない。2 種類以上出たら**選ばない**(推定しない)。
    """
    # 頁の上の飾り(古い固定 PDF)を除く= /files/libs/<大きい番号>/ にある新しいものだけ
    hits = []
    for m in re.finditer(r"(/files/libs/(\d+)/(\d+\.pdf))", html):
        hits.append((int(m.group(2)), m.group(1), m.group(3)))
    if not hits:
        return None, None
    top = max(h[0] for h in hits)
    latest = sorted({(h[1], h[2]) for h in hits if h[0] == top})
    if len(latest) != 1:
        log(f"⚠ PDF のリンクが {len(latest)} 種類ありました= 選ばずに止めます: {[x[1] for x in latest]}")
        return None, None
    path, name = latest[0]
    return "http://fukuchan.net" + path, name


def read_done():
    if not DONE.exists():
        return {}
    out = {}
    for line in DONE.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out[parts[0]] = parts[1]
    return out


def add_done(name, saved_as):
    OUT.mkdir(parents=True, exist_ok=True)
    with DONE.open("a", encoding="utf-8") as f:
        f.write(f"{name}\t{saved_as}\t{dt.datetime.now().isoformat(timespec='seconds')}\n")


def date_from_name(name):
    """ファイル名(アップロード時刻+乱数4桁)→ その日付−1 日。読めなければ None。"""
    # 実測= YYYYMMDDHHMMSS(14 桁)+ 乱数 4 桁 = 18 桁
    m = re.match(r"^(20\d{2})(\d{2})(\d{2})\d{10}\.pdf$", name)
    if not m:
        return None
    try:
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return (d - dt.timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- 号の日付

def issue_date(pdf):
    """1 ページ目から 'YYYY-MM-DD'。読めなければ None。

    並び(実測)= 「2026」「年」「9」「月」…「5」(頁で一番大きい数字)…「日」。
    """
    pg = pdf.pages[0]
    ws = [w for w in pg.extract_words(extra_attrs=["size"]) if w["top"] < 130 and w["x0"] > 250]
    if not ws:
        return None
    ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
    line = "".join(w["text"] for w in ws).translate(ZEN)
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月", line)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    # 日= 年・月の数字を除いた「数字だけの語」で一番大きい字のもの
    used = {m.group(1), m.group(2)}
    cands = [w for w in ws if re.fullmatch(r"[0-9０-９]{1,2}", w["text"])
             and w["text"].translate(ZEN) not in used]
    if not cands:
        return None
    day = int(max(cands, key=lambda w: w.get("size", 0))["text"].translate(ZEN))
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def date_agreement(pdf, date):
    """レース頁の見出しの「M月D日」が号の日付と合う頁の数 / 見出しが読めた頁の数。"""
    if not date:
        return 0, 0
    want = (int(date[5:7]), int(date[8:10]))
    ok = seen = 0
    for pg in pdf.pages[1:]:
        head = " ".join(w["text"] for w in pg.extract_words()
                        if w["top"] < 40 and w["x0"] < 200).translate(ZEN)
        # ⚠「9月 走時 5日」のように語が入り混じる頁があるので、月と日は**別々に**拾う
        mm = re.search(r"(\d{1,2})月", head)
        dd = re.search(r"(\d{1,2})日", head)
        if not mm or not dd:
            continue
        seen += 1
        if (int(mm.group(1)), int(dd.group(1))) == want:
            ok += 1
    return ok, seen


# ---------------------------------------------------------------- レース頁 → 枠

def joined(chars, gap=3.0):
    """chars を行(top が近いもの)にまとめ、x 順につないだ文字列にする。"""
    lines = []
    for c in sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"])):
        if lines and abs(c["top"] - lines[-1][0]) <= gap:
            lines[-1][1].append(c)
        else:
            lines.append([c["top"], [c]])
    return "".join("".join(x["text"] for x in sorted(cs, key=lambda c: c["x0"]))
                   for _, cs in lines)


def race_no_of(words):
    for w in words:
        if w["top"] < 40 and w["x0"] < 100:
            m = re.match(r"^([0-9０-９]{1,2})[ＲR]$", w["text"])
            if m:
                return int(m.group(1).translate(ZEN))
    return None


def name_rows(chars):
    """馬名の行(top)を上から。⛔等間隔に並んだところだけを馬の行として採る
    (頁の下のほうにある大きい字を馬に数えない)。"""
    tops = sorted({round(c["top"], 1) for c in chars
                   if NAME_X[0] <= c["x0"] <= NAME_X[1] and c["size"] >= NAME_SIZE})
    if len(tops) < 2:
        return [], None
    diffs = sorted(round(b - a, 1) for a, b in zip(tops, tops[1:]))
    step = diffs[len(diffs) // 2]
    if not (FALLBACK_ROW_H - 6 < step < FALLBACK_ROW_H + 6):
        return [], None
    # ⚠見出しにも大きい字があるので、**等間隔に一番長く続くところ**を馬の行として採る
    best = []
    for i, t0 in enumerate(tops):
        chain = [t0]
        for t in tops[i + 1:]:
            if abs(t - (chain[-1] + step)) <= 2.5:
                chain.append(t)
        if len(chain) > len(best):
            best = chain
    return (best, step) if len(best) >= 2 else ([], None)


def talk_bounds(pg, words):
    """談話欄の x の幅を頁から測る。左=「【談話】」の x0・右=「【総評】」の 【 の x0。"""
    left = [w["x0"] for w in words if w["text"].startswith("【談話】")]
    right = [c["x0"] for c in pg.chars if c["text"] == "【" and left and c["x0"] > min(left) + 40]
    if not left or not right:
        return FALLBACK_TALK_X, False
    return (min(left) - 6.0, min(right) - 2.0), True


def parse_page(pg):
    """1 頁 → {race_no, rows:[{umaban, name, talk}]}。読めない頁は None。"""
    words = pg.extract_words()
    rno = race_no_of(words)
    if rno is None:
        return None
    rows, step = name_rows(pg.chars)
    if not rows:
        return None
    (tx0, tx1), measured = talk_bounds(pg, words)
    out = []
    for i, top in enumerate(rows):
        name = joined([c for c in pg.chars if c["size"] >= NAME_SIZE
                       and abs(c["top"] - top) <= 2.5 and NAME_X[0] <= c["x0"] <= NAME_X1]).strip()
        t0 = top + TALK_OFFSET
        talk = joined([c for c in pg.chars if tx0 <= c["x0"] < tx1
                       and t0 - 4 <= c["top"] < t0 + step - 4]).strip()
        talk = re.sub(r"^【談話】", "", talk).strip()
        out.append({
            "umaban": i + 1,          # 紙面の並び順。公式と突き合わせて matched を付ける
            "name": name or None,
            "talk": talk or None,     # ⛔読めない枠は null(推定しない)
            "matched": False,
        })
    return {"race_no": rno, "talk_x_measured": measured, "rows": out}


def parse_pdf(path):
    pdfplumber = pdf_lib()
    with pdfplumber.open(path) as pdf:
        date = issue_date(pdf)
        assumed = False
        if not date:
            date = date_from_name(path.name.split("_")[-1]) or date_from_name(path.name)
            assumed = bool(date)
        agree, seen = date_agreement(pdf, date)
        races = []
        for pg in pdf.pages[1:]:
            r = parse_page(pg)
            if r:
                races.append(r)
    races.sort(key=lambda r: r["race_no"])
    return {
        "date": date,
        "date_assumed": assumed,
        "date_agree": f"{agree}/{seen}",     # レース頁の見出しと合った頁 / 見出しが読めた頁
        "source_file": path.name,
        "races": races,
    }


# ---------------------------------------------------------------- 公式との突き合わせ

def official_runs(date):
    """nar_runs(公開 anon・読むだけ)→ {(R, 馬番): 馬名}。取れなければ None。"""
    q = (f"{NAR_URL}/rest/v1/nar_runs?track=eq.{urllib.parse.quote(TRACK)}"
         f"&race_date=eq.{date}&select=race_no,runner_number,horse_name&limit=1000")
    req = urllib.request.Request(q, headers={
        "apikey": NAR_ANON, "Authorization": f"Bearer {NAR_ANON}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            rows = json.loads(res.read())
    except Exception as e:
        log(f"⚠ 公式(nar_runs)を読めませんでした: {e.__class__.__name__}")
        return None
    out = {}
    for r in rows:
        if r.get("race_no") is not None and r.get("runner_number") is not None:
            out[(int(r["race_no"]), int(r["runner_number"]))] = str(r.get("horse_name") or "")
    return out


def mark_matched(doc, runs):
    """日付+R+馬番+馬名 の 4 つが合った枠だけ matched=true。⛔合わない枠も残す。"""
    ok = ng = 0
    for race in doc["races"]:
        for row in race["rows"]:
            want = runs.get((race["race_no"], row["umaban"]))
            hit = bool(want) and want == row["name"]
            row["matched"] = hit
            ok += hit
            ng += not hit
    return ok, ng


# ---------------------------------------------------------------- 出口

def write_json(doc):
    OUT.mkdir(parents=True, exist_ok=True)
    name = (doc["date"] or Path(doc["source_file"]).stem) + ".json"
    path = OUT / name
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def summarize(doc):
    races = doc["races"]
    slots = sum(len(r["rows"]) for r in races)
    talks = sum(1 for r in races for x in r["rows"] if x["talk"])
    matched = sum(1 for r in races for x in r["rows"] if x["matched"])
    return slots, talks, matched


def do_parse(path, match=True):
    doc = parse_pdf(path)
    if not doc["races"]:
        log(f"✗ {path.name}: レース頁を読めませんでした")
        return 1
    if match and doc["date"]:
        runs = official_runs(doc["date"])
        if runs is not None:
            mark_matched(doc, runs)
    slots, talks, matched = summarize(doc)
    out = write_json(doc)
    note = "(⚠日付は仮)" if doc["date_assumed"] else ""
    log(f"{path.name}: {doc['date']}{note} {len(doc['races'])}レース {slots}枠 "
        f"談話 {talks}/{slots} 突合 {matched}/{slots} 見出しの日付 {doc['date_agree']} → {out.name}")
    return 0


def do_fetch():
    OUT.mkdir(parents=True, exist_ok=True)
    html = get(PAGE).decode("utf-8", "replace")          # ⛔ページへの GET はこの 1 回だけ
    url, name = latest_pdf(html)
    if not url:
        log("✗ 公開ページに PDF のリンクが見つかりませんでした")
        return 1
    done = read_done()
    if name in done:
        log(f"変わりなし: {name}(済み= {done[name]})")
        return 0
    data = get(url, timeout=180)
    if not data.startswith(b"%PDF"):
        log(f"✗ PDF ではないものが返りました({len(data)} バイト)")
        return 1
    tmp = OUT / ("_tmp_" + name)
    tmp.write_bytes(data)
    pdfplumber = pdf_lib()
    with pdfplumber.open(tmp) as pdf:
        date = issue_date(pdf)
    if not date:
        date = date_from_name(name) or "unknown"
        log(f"⚠ 号の日付を 1 ページ目から読めませんでした= ファイル名から {date}(仮)")
    saved = OUT / f"{date}_{name}"
    tmp.replace(saved)
    add_done(name, saved.name)
    log(f"新しい号: {name} → {saved.name}({len(data)} バイト)")
    return do_parse(saved)


def main():
    ap = argparse.ArgumentParser(description="§121 福ちゃん競馬新聞(高知)の保管と陣営談話の読み取り")
    ap.add_argument("--parse", metavar="PDF", help="この PDF を 1 本だけ読む")
    ap.add_argument("--parse-all", action="store_true", help="data/fukuchan/ の PDF ぜんぶ")
    ap.add_argument("--no-match", action="store_true", help="公式(nar_runs)と突き合わせない(通信 0)")
    args = ap.parse_args()
    if args.parse:
        p = Path(args.parse)
        if not p.exists():
            p = OUT / args.parse
        if not p.exists():
            log(f"✗ ファイルが見つかりません: {args.parse}")
            return 1
        return do_parse(p, match=not args.no_match)
    if args.parse_all:
        files = sorted(f for f in OUT.glob("*.pdf") if not f.name.startswith("_tmp_"))
        if not files:
            log(f"PDF がありません: {OUT}")
            return 0
        rc = 0
        for f in files:
            rc |= do_parse(f, match=not args.no_match)
        return rc
    return do_fetch()


if __name__ == "__main__":
    sys.exit(main())

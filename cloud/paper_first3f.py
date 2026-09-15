# -*- coding: utf-8 -*-
"""紙面 PDF の各馬の前半3F → nar_paper_runs(毎朝の便・手元でも同じ命令)。

  python -X utf8 cloud/paper_first3f.py                                   # 今日-1〜+7 日(JST)の PDF のうち表にまだ無いもの
  python -X utf8 cloud/paper_first3f.py --dates 2026-09-14 --force --dry-run
環境変数: PAPER_BASE_URL(一覧と PDF の置き場・末尾 /)/ SUPABASE_URL / SUPABASE_SERVICE_KEY
          (--dry-run は読むだけなので SUPABASE_ANON_KEY でも動く)
終了コード: 0 正常 / 1 一部失敗 / 2 前提が無い

- 馬名は読まない(縦書き)= 枠の過去走を公式 nar_runs に当てて特定(paper_pdf.identify_horse)。
- 距離(nar_races)≥1200 → first3f・<1200 → first2f。出どころは src_ref(ファイル名だけ)・src_page・src_pos。
- 同じ PDF の行が表に 1 行でもあれば飛ばす(--force で取り直し= PK で merge)。
- ⛔ログに出すのは 日付・レース番号・件数・保留の理由・HTTP の status 番号だけ(URL・ファイル名・例外の文は出さない)。
- PDF は作業フォルダ(RUNNER_TEMP)に置き、読み終えたら消す(⛔保存しない・上げない)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paper_pdf as pp  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']*?(\d{4})(\d{2})(\d{2})_(\d{1,2})R(a4)?\.pdf)["']""", re.I)
TAIL_RE = re.compile(r"R(a4)?\.pdf$", re.I)
DATES_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(,\d{4}-\d{2}-\d{2})*$")
PK = ("track", "race_date", "race_no", "umaban")
UA = "Mozilla/5.0"
DPI = 300
CHUNK = 500
_ENG = None


class Quiet(Exception):
    """ログに出してよい字(status 番号・例外の種類名)だけを持つ失敗"""


def log(msg):
    print(msg, flush=True)


def http_get(url, headers=None, timeout=90):
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise Quiet("HTTP %d" % e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise Quiet("通信失敗(%s)" % type(e).__name__) from None


# ---------------------------------------------------------------- 公式の表
def sb_key():
    return os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or ""


def sb(path, body=None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = sb_key()
    headers = {"apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    req = urllib.request.Request(base + "/rest/v1/" + path, data=body, method="POST" if body is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise Quiet("DB HTTP %d" % e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise Quiet("DB 通信失敗(%s)" % type(e).__name__) from None


def q_in(values):
    return "in.(" + ",".join(urllib.parse.quote('"%s"' % v) for v in values) + ")"


def official_runs(runs):
    """紙面の過去走に出てくる (場, 日付, 走破) だけに絞って nar_runs を読む(⛔全量を引かない)"""
    tracks = sorted({r["venue"] for r in runs})
    dates = sorted({r["date"] for r in runs})
    times = sorted({"%.1f" % r["time_sec"] for r in runs})
    if not (tracks and dates and times):
        return []
    base = ("nar_runs?select=track,race_date,race_no,runner_number,horse_name,finish,time_sec"
            "&track=" + q_in(tracks) + "&race_date=in.(" + ",".join(dates) + ")&time_sec=in.(" + ",".join(times) + ")"
            "&order=track,race_date,race_no,runner_number&limit=1000")
    out, offset = [], 0
    while True:
        part = sb(base + "&offset=%d" % offset) or []
        out += part
        if len(part) < 1000:
            return out
        offset += 1000


def distances(keys):
    out = {}
    keys = sorted(keys)
    for i in range(0, len(keys), 80):
        cond = ",".join("and(track.eq.%s,race_date.eq.%s,race_no.eq.%d)" % (urllib.parse.quote(t), d, n) for t, d, n in keys[i:i + 80])
        for r in sb("nar_races?select=track,race_date,race_no,distance_m&or=(" + cond + ")&limit=1000") or []:
            if r.get("distance_m") is not None:
                out[(r["track"], str(r["race_date"]), int(r["race_no"]))] = int(r["distance_m"])
    return out


def sibling(name):
    """同じ (日付, R) のもう一方の名前(a4 ⇔ 無印)"""
    return TAIL_RE.sub(lambda m: "R.pdf" if m.group(1) else "Ra4.pdf", name)


def done_refs(names):
    """表に行がある PDF の名前。(日付, R) で見る= a4 名で入った日の無印も「済み」にする"""
    got = set()
    names = sorted({x for n in names for x in (n, sibling(n))})
    for i in range(0, len(names), 50):
        for r in sb("nar_paper_runs?select=src_ref&src_ref=" + q_in(names[i:i + 50])) or []:
            got.add(r.get("src_ref"))
    return got | {sibling(n) for n in got if n}


# ---------------------------------------------------------------- 一覧と PDF
def pick_pdfs(html):
    """一覧の HTML → {ファイル名: (日付, レース番号, 置き場からの相対)}。
    同じ (日付, R) に a4 と無印の両方があれば a4(A4 2 枚の方が文字が大きい= 読み取りが安定)・無印だけならそれ"""
    best = {}
    for m in HREF_RE.finditer(html):
        href, y, mo, d, no, a4 = m.groups()
        key = ("%s-%s-%s" % (y, mo, d), int(no))
        if key not in best or (a4 and not best[key][0]):
            best[key] = (bool(a4), href)
    return {os.path.basename(href): (key[0], key[1], href) for key, (_, href) in best.items()}


def list_pdfs(base):
    """一覧 → {ファイル名: (日付, レース番号, 置き場からの相対)}"""
    return pick_pdfs(http_get(base + "index.html").decode("cp932", "replace"))


def _runs(vals, thr):
    out, start = [], None
    for i, v in enumerate(list(vals) + [0]):
        if v >= thr and start is None:
            start = i
        elif v < thr and start is not None:
            out.append((start + i - 1) // 2)
            start = None
    return out


def grid(img):
    """罫線= 過去走の帯(ページの高さの 53〜85%)で黒 90% 以上の縦線・右端の列の中で黒 85% 以上の横線。
    ⛔ページの大きさや列の数は決め打ちしない"""
    import numpy as np
    dark = np.asarray(img.convert("L")) < 120
    H = dark.shape[0]
    vl = _runs(dark[int(H * 0.527):int(H * 0.855):2].mean(axis=0), 0.9)
    if len(vl) < 2:
        return [], []
    hl = _runs(dark[:, vl[-2] + 5:vl[-1] - 5].mean(axis=1), 0.85)
    return vl, [y for y in hl if H * 0.513 <= y <= H * 0.87]


def ocr_lines(img, scale=2):
    global _ENG
    if _ENG is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENG = RapidOCR()
    from PIL import Image
    res, _ = _ENG(img.resize((img.width * scale, img.height * scale), Image.LANCZOS))
    out = [{"text": text, "score": float(score), "cy": sum(p[1] for p in box) / 4 / scale, "cx": sum(p[0] for p in box) / 4 / scale}
           for box, text, score in (res or [])]
    return sorted(out, key=lambda d: (d["cy"], d["cx"]))


def pdf_columns(path, race_date):
    """PDF の各ページの馬の列 → [{page, col(そのページの右から), runs:[parse_block の行]}]"""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    cols = []
    try:
        for pno in range(len(doc)):
            img = doc[pno].render(scale=DPI / 72).to_pil().convert("RGB")
            vl, ys = grid(img)
            for ci, (x0, x1) in enumerate(reversed(list(zip(vl[:-1], vl[1:]))), start=1):
                if not 120 <= x1 - x0 <= 220 or len(ys) < 2:        # 馬の列の幅(300dpi で 165px 前後)でない枠は飛ばす
                    continue
                runs = [pp.parse_block(ocr_lines(img.crop((x0 + 2, y0 + 2, x1 - 2, y1 - 2))), x1 - x0 - 4, y1 - y0 - 4, race_date)
                        for y0, y1 in zip(ys[:-1], ys[1:])]
                cols.append({"page": pno + 1, "col": ci, "runs": runs})
    finally:
        doc.close()
    return cols


def one_pdf(base, name, race_date, href, work):
    path = os.path.join(work, "paper_%s" % re.sub(r"[^0-9A-Za-z_.]", "", name))
    with open(path, "wb") as f:
        f.write(http_get(urllib.parse.urljoin(base, href), timeout=120))
    try:
        cols = pdf_columns(path, race_date)
    finally:
        os.remove(path)
    usable = [r for c in cols for r in c["runs"] if r.get("finish") is not None and r.get("time_sec") is not None
              and r.get("date") and r.get("venue")]
    db = official_runs(usable)
    found, held = [], []
    for c in cols:
        horse, why, hits = pp.identify_horse(c["runs"], db)
        if horse:
            found.append((horse, c, hits))
        else:
            held.append((c["page"], c["col"], why))
    need = {(h["track"], str(h["race_date"]), int(h["race_no"])) for _, c, hits in found
            for i, h in hits.items() if c["runs"][i].get("first3f") is not None}
    dist = distances(need)
    rows = []
    for horse, c, hits in found:
        rows += pp.rows_to_write(horse, c["runs"], hits, dist, {"ref": name, "page": c["page"], "col": c["col"]})
    return rows, len(cols), held, len(db)


def upsert(rows):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for i in range(0, len(rows), CHUNK):
        sb("nar_paper_runs?on_conflict=" + ",".join(PK),
           json.dumps([dict(r, updated_at=now) for r in rows[i:i + CHUNK]], ensure_ascii=False).encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="紙面 PDF の前半3F → nar_paper_runs")
    ap.add_argument("--dates", default="", help="YYYY-MM-DD をカンマ区切り(既定= 今日-1〜+7 日・JST)")
    ap.add_argument("--force", action="store_true", help="表に行がある PDF も取り直す")
    ap.add_argument("--dry-run", action="store_true", help="読むだけで表に書かない")
    ap.add_argument("--out", help="書く行を JSON で保存(手元の答え合わせ用)")
    a = ap.parse_args(argv)
    base = os.environ.get("PAPER_BASE_URL", "").strip()
    if not base:
        log("PAPER_BASE_URL が無い"); return 2
    base = base if base.endswith("/") else base + "/"
    if not os.environ.get("SUPABASE_URL") or not sb_key() or (not a.dry_run and not os.environ.get("SUPABASE_SERVICE_KEY")):
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    if a.dates and not DATES_RE.match(a.dates):
        log("--dates の形が違う(YYYY-MM-DD をカンマ区切り)"); return 2
    today = dt.datetime.now(JST).date()
    want = set(a.dates.split(",")) if a.dates else {(today + dt.timedelta(days=k)).isoformat() for k in range(-1, 8)}
    try:
        pdfs = {n: v for n, v in list_pdfs(base).items() if v[0] in want}
        skip = set() if a.force else done_refs(pdfs)
    except Quiet as q:
        log("一覧の読み取りに失敗 %s" % q); return 1
    todo = sorted((v[0], v[1], n) for n, v in pdfs.items() if n not in skip)
    log("対象の日の PDF %d 本・読む %d 本(表に行がある %d 本は飛ばす)" % (len(pdfs), len(todo), len(pdfs) - len(todo)))
    work = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    table, fails = {}, 0
    for race_date, no, name in todo:
        label = "%s %dR" % (race_date, no)
        try:
            rows, ncol, held, ndb = one_pdf(base, name, race_date, pdfs[name][2], work)
        except Quiet as q:
            log("%s 失敗 %s" % (label, q)); fails += 1; continue
        except Exception as e:  # ⛔例外の文には URL やパスが入りうる= 種類名だけ
            log("%s 失敗(%s)" % (label, type(e).__name__)); fails += 1; continue
        n3 = sum(1 for r in rows if r["first3f"] is not None)
        log("%s 馬の列 %d・特定 %d・保留 %d・公式の行 %d・書く行 %d(first3f %d・first2f %d)" % (
            label, ncol, ncol - len(held), len(held), ndb, len(rows), n3, len(rows) - n3))
        for page, col, why in held:
            log("  %s p%d 右から%d列 保留 %s" % (label, page, col, why))
        for r in rows:
            k = tuple(r[c] for c in PK)
            if k in table and table[k]["src_ref"] != r["src_ref"]:
                log("  %s 別の PDF と同じ走(後の PDF の値を使う)" % label)
            table[k] = r
    rows = sorted(table.values(), key=lambda r: tuple(r[c] for c in PK))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=0)
    n3 = sum(1 for r in rows if r["first3f"] is not None)
    log("書く行 %d(first3f %d・first2f %d)・失敗 %d 本" % (len(rows), n3, len(rows) - n3, fails))
    if a.dry_run:
        log("--dry-run= 表に書かずに終了"); return 1 if fails else 0
    if rows:
        try:
            upsert(rows)
        except Quiet as q:
            log("表への書き込みに失敗 %s" % q); return 1
        log("表へ書いた %d 行" % len(rows))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

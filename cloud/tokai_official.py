"""名古屋の番組賞金額= 公式の編成馬一覧(次開催番組)の値を正にする(2026-10-20 方針)。

公式 https://www.nagoyakeiba.com/info/program/file/{年}-{回}-{日}.pdf は 千円単位・開催の日ごと(1〜5)。
自前の計算(class_calc.tokai_calc)は 旧年度(2025-19 回より前)の起点にズレが残り 直せないので、
公式の一覧に載っている馬は公式の値をそのまま使い、載っていない馬と途中経過だけ計算に任せる。
読み取りは pymupdf(pdfplumber は日本語のフォントが化ける)。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds import http_get  # noqa: E402

BASE = "https://www.nagoyakeiba.com/info/program"
LINK = re.compile(r"/file/(\d{4})-(\d+)-(\d)\.pdf")
MARK = re.compile(r"^(（１２R）|〇|○|希|補[１２３])+")


def latest_cycle():
    """次開催番組のページに載っている最新の (年, 回)。無ければ None"""
    html = http_get(f"{BASE}/next_program/index.html").decode("utf-8", "ignore")
    cs = {(int(y), int(c)) for y, c, _d in LINK.findall(html)}
    return max(cs, key=lambda t: (t[0], t[1])) if cs else None


def parse_pdf(data):
    """PDF のバイト列 → [(馬名, 馬齢, 番組賞金額[千円])]。性別(牡・牝・セ)の語を目印に同じ行から読む"""
    try:
        import pymupdf
    except ImportError:                                 # 古い名前
        import fitz as pymupdf
    out = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    for page in doc:
        ws = page.get_text("words")
        for w in ws:
            if w[4] not in ("牡", "牝", "セ"):
                continue
            y = (w[1] + w[3]) / 2
            near = sorted([v for v in ws if abs((v[1] + v[3]) / 2 - y) < 2.6], key=lambda v: v[0])
            left = [v for v in near if v[2] <= w[0] + 0.1 and v[0] > w[0] - 130]
            name = ""
            for v in reversed(left):
                t = MARK.sub("", v[4])
                if t:
                    name = t
                    break
            rest = [v[4] for v in near if v[0] > w[0] + 0.1]
            if not name or len(rest) < 2:
                continue
            age, prize = rest[0], rest[1].replace(",", "")
            if age.isdigit() and prize.isdigit():
                out.append((name, int(age), int(prize)))
    return out


def fetch_official(year=None, cyc=None, days=(1, 2, 3, 4, 5)):
    """最新(または指定)の回の一覧を取る → ({(馬名, 馬齢): 番組賞金額[千円]}, (年, 回))。
    同じ (馬名, 馬齢) で値が食い違うもの(同名の別馬)は外す"""
    if year is None or cyc is None:
        lc = latest_cycle()
        if not lc:
            return {}, None
        year, cyc = lc
    seen, bad = {}, set()
    for d in days:
        try:
            data = http_get(f"{BASE}/file/{year}-{cyc}-{d}.pdf")
        except Exception:                               # その日の PDF が無い(開催が 4 日など)
            continue
        for name, age, prize in parse_pdf(data):
            k = (name, age)
            if k in seen and seen[k] != prize:
                bad.add(k)
            seen[k] = prize
    for k in bad:
        seen.pop(k, None)
    return seen, (year, cyc)


def apply_official(c, prize_k, lines, classify, next_line, tag=""):
    """計算結果 c の値を公式の値に差し替える(級・次の線も作り直す)。c は書き換えずに新しい辞書を返す"""
    out = dict(c)
    value = int(prize_k) * 1000
    out["value"] = value
    out["src"] = "official"
    if c.get("cls") in ("２歳", "３歳"):                  # 2歳格・3歳格は計算側の判定(格の線は別)を残す。gap だけ公式の値で引き直す
        need = (c.get("next") or {}).get("need")
        if need:
            out["next"] = {**c["next"], "gap": need - value}
    else:
        cls = classify(lines, value)
        out["cls"] = cls
        nx = next_line(lines, cls)
        out["next"] = {"cls": nx[0], "need": nx[1], "gap": nx[1] - value} if nx else None
    out["note"] = f"公式の番組賞金額{tag}"
    if "calc_value" not in out:
        out["calc_value"] = c.get("value")             # 自前計算の値(ずれの監視用)
    return out

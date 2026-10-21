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


KS_BASE = "https://www.kasamatsu-keiba.com"
KS_CYC = re.compile(r'class="l_number">\s*第\s*(\d+)\s*回')
KS_LINK = re.compile(r'href="(/resources/pdfs/raceprogram/[^"]+\.pdf)"[^>]*>\s*<p[^>]*>\s*出走投票準備一覧')
KS_PRIZE = re.compile(r"^(?:\d{1,2}R)?\s*(?:補欠)?(?:希望)?\s*[①-⑳]?\s*(\d{1,5})(\s+\D.*)?$")
KS_NAME = re.compile(r"[゠-ヿ]{2,9}")


def ks_parse_pdf(data):
    """笠松の出走投票準備一覧 PDF → [(馬名, 番組賞金[千円])]。馬名の行の次の行の頭の数字
    (「9R補欠①1930 藤田正」「12R ①4559 伊藤好56」のように頭に希望・補欠の印が付くことがある)"""
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    out = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    for page in doc:
        ls = [x.strip() for x in page.get_text().splitlines()]
        for i in range(1, len(ls)):
            m = KS_PRIZE.match(ls[i])
            if not m or (not m.group(2) and len(m.group(1)) < 3):
                continue
            if KS_NAME.fullmatch(ls[i - 1]):
                out.append((ls[i - 1], int(m.group(1))))
    return out


def fetch_kasamatsu():
    """笠松 /raceprogram の最新の回(ページの先頭)の出走投票準備一覧 → ({馬名: 千円}, 回)。同名で値が違うものは外す"""
    html = http_get(f"{KS_BASE}/raceprogram").decode("utf-8", "ignore")
    mc = KS_CYC.search(html)
    if not mc:
        return {}, None
    ml = KS_LINK.search(html, mc.end())
    if not ml:
        return {}, None
    seen, bad = {}, set()
    for name, prize in ks_parse_pdf(http_get(KS_BASE + ml.group(1))):
        if name in seen and seen[name] != prize:
            bad.add(name)
        seen[name] = prize
    for k in bad:
        seen.pop(k, None)
    return seen, int(mc.group(1))


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

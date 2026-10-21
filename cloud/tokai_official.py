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


def ks_dates(text, today):
    """回の見出し「【１２回前半】１０月２１日、２２日、２３日」「４月１４～１７日」→ 開催日の集合。
    年= きょうの年(きょうより 6 か月以上先の月は前の年)・「令和８年」があればそれ"""
    import datetime as dt
    import unicodedata
    t = re.sub(r"【[^】]*】", " ", unicodedata.normalize("NFKC", text))
    out, year, month = set(), None, None
    for m in re.finditer(r"令和(\d+)年|(\d+)月|(\d+)日(?:\s*[~〜-]\s*(\d+)日)?|(\d+)\s*[~〜-]\s*(\d+)日", t):
        if m.group(1):
            year = 2018 + int(m.group(1))
        elif m.group(2):
            month = int(m.group(2))
        elif month:
            a, b = (int(m.group(3)), int(m.group(4) or m.group(3))) if m.group(3) else (int(m.group(5)), int(m.group(6)))
            y = year or (today.year - 1 if month - today.month > 6 else today.year)
            for d in range(a, b + 1):
                try:
                    out.add(dt.date(y, month, d))
                except ValueError:
                    pass
    return out


def fetch_kasamatsu(today=None):
    """笠松 /raceprogram の最新の回(ページの先頭)の出走投票準備一覧 → ({馬名: 千円}, 回, 開催日の集合)。同名で値が違うものは外す"""
    import datetime as dt
    html = http_get(f"{KS_BASE}/raceprogram").decode("utf-8", "ignore")
    mc = KS_CYC.search(html)
    if not mc:
        return {}, None, set()
    head = re.match(r"\s*</span>([^<]*)", html[mc.end():])
    days = ks_dates(head.group(1) if head else "", today or dt.date.today())
    ml = KS_LINK.search(html, mc.end())
    if not ml:
        return {}, None, set()
    seen, bad = {}, set()
    for name, prize in ks_parse_pdf(http_get(KS_BASE + ml.group(1))):
        if name in seen and seen[name] != prize:
            bad.add(name)
        seen[name] = prize
    for k in bad:
        seen.pop(k, None)
    return seen, int(mc.group(1)), days


KS_PAGE_DAY = re.compile(r"第\s*\d+\s*日目\s*(\d+)月\s*(\d+)日")


def ks_pages(data):
    """出走投票準備一覧 PDF → {開催日: {馬名: 千円}}。1 ページ= 1 開催日(「第4日目 7月 8日(水)」「令和8年度」から日付)。
    前半・後半を 1 つの PDF に入れた回(第1・4・5回)は ページごとに値が違う(後半は見直し後)ので日ごとに分ける"""
    import datetime as dt
    import unicodedata
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    out = {}
    for page in pymupdf.open(stream=data, filetype="pdf"):
        raw = page.get_text()
        t = unicodedata.normalize("NFKC", raw)
        fy, md = re.search(r"令和(\d+)年度", t), KS_PAGE_DAY.search(t)
        if not fy or not md:
            continue
        m, d = int(md.group(1)), int(md.group(2))
        try:
            day = dt.date(2018 + int(fy.group(1)) + (1 if m < 4 else 0), m, d)
        except ValueError:
            continue
        got = out.setdefault(day, {})
        ls = [x.strip() for x in raw.splitlines()]
        for i in range(1, len(ls)):
            mm = KS_PRIZE.match(ls[i])
            if not mm or (not mm.group(2) and len(mm.group(1)) < 3):
                continue
            if KS_NAME.fullmatch(ls[i - 1]):
                got.setdefault(ls[i - 1], set()).add(int(mm.group(1)))
    return out


def fetch_kasamatsu_all(cut_of=None):
    """笠松 /raceprogram に載っている全部の回の出走投票準備一覧 → [(回, 開催日の集合, 締めの日, {馬名: 千円})](古い順)。
    続けて開いた日(空き 5 日以内)で値の食い違いが無いものを 1 つの一覧にまとめる(12/26 と 12/29〜31 は同じ値)。
    締めの日= cut_of(初日)(class_calc の tokai_cutoff= 初日の 3 日以上前に終わった直近の笠松の開催の最終日+1)。
    同じ一覧の中で同名で値の違う馬は外す"""
    html = http_get(f"{KS_BASE}/raceprogram").decode("utf-8", "ignore")
    ms = list(KS_CYC.finditer(html))
    days = {}
    for i, mc in enumerate(ms):
        seg = html[mc.end(): ms[i + 1].start() if i + 1 < len(ms) else len(html)]
        ml = KS_LINK.search(seg)
        if not ml:
            continue
        for d, v in ks_pages(http_get(KS_BASE + ml.group(1))).items():
            cur = days.setdefault(d, (int(mc.group(1)), {}))[1]
            for n, ps in v.items():
                cur.setdefault(n, set()).update(ps)
    blocks = []
    for d in sorted(days):
        cyc, v = days[d]
        one = {n: next(iter(ps)) for n, ps in v.items() if len(ps) == 1}
        bad = {n for n, ps in v.items() if len(ps) > 1}
        if blocks and (d - blocks[-1]["last"]).days <= 5 and                 not any(n in blocks[-1]["off"] and blocks[-1]["off"][n] != p for n, p in one.items()):
            b = blocks[-1]
        else:
            b = {"cyc": cyc, "days": set(), "off": {}, "bad": set(), "last": d}
            blocks.append(b)
        b["days"].add(d)
        b["last"] = d
        b["bad"] |= bad
        b["off"].update(one)
    out = []
    for b in blocks:
        off = {n: p for n, p in b["off"].items() if n not in b["bad"]}
        first = min(b["days"])
        out.append((b["cyc"], b["days"], cut_of(first) if cut_of else first, off))
    return out


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

# -*- coding: utf-8 -*-
"""cloud: 高知・名古屋・笠松の**走路の砂厚**を写して溜める(§146)。

なぜ集めるか= 3 場とも「この日に内柵から何 cm だったか」の表を出すが、**古い表は消える**
  (名古屋= 一覧に 1〜3 本・笠松= 最新 1 本だけ・旧記事は 404)。毎回写して溜めたものが、そのまま履歴になる。

  出力 = nar_sand_depth へ **insert だけ**(書き換えない)。1 行= 場 × 日 × 種類 × 地点。
  py -3.12 -X utf8 cloud/sand_depth.py                        # ドライラン(既定)。取れた中身を出すだけ
  py -3.12 -X utf8 cloud/sand_depth.py --site kochi --limit 3 # 1 場だけ・記事 3 本まで
  py -3.12 -X utf8 cloud/sand_depth.py --env pipeline/.env.nar --apply
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply でだけ使う)・ANTHROPIC_API_KEY(予備の読み手)
終了コード: 0 正常 / 1 投入失敗 / 2 **1 場も取れなかった**

⛔この道具の決まりごと(実地で決めたもの)
 1. **原本(PDF・HTML)は保存しない**。読んだら捨てる。残すのは数字と公式への link だけ。
 2. **読めないものは数えて飛ばす**。止めない・推測で埋めない。
 3. 名古屋の PDF は **6 断面のうち 1 つ(ゴール前直線)が貼り込んだ画像**で、文字が 1 字も入っていない。
    そこだけ**文字認識**で読む(本命= Tesseract・予備= AI)。⛔**検算に通ったものだけ**入れる(check_ocr)。
 4. 名古屋の PDF には**断面の名前が印字されていない**。名前はコース図の中心から見た向きで当サイトが付ける
    (NAGOYA_NAMES・画面に「当サイトの呼び名」と注記する)。
 5. 名古屋の 5 断面は**文字の回し方(matrix の角度)**で分かれる。⛔紙の上の位置で決め打ちしない
    (同じ様式でも刷りごとに縮尺がずれる)。内と外は**コース図の中心からの距離**で決める。
    ⛔「内がいちばん厚い」を前提にしない(実測で外れる断面があった)。
 6. 笠松の PDF は ①コースの絵の中に**見えない白い字**が埋まっている(色で捨てる)②天気と馬場は字ではなく
    **丸で囲って**示す(曲線の中にある字を採る)③`extract_words` の既定では印と数字がくっつく(x_tolerance=1.5)。
 7. 平均は**公式に印字されたものだけ**(笠松)。無ければ null= 画面側で計算する(公式と当サイトの計算を混ぜない)。
"""

import argparse
import datetime as dt
import html as _html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                  # noqa: BLE001
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 30
SLEEP = 1.0                                        # 公式への間隔(⛔詰めない)
TABLE = "nar_sand_depth"
SINCE_DEFAULT = "2026-01-01"                       # #120 まず今年ぶん。遡りは成功してから
KNOWN_SRC_LIMIT = 300                              # 既に入っている src を先に引く本数

JST = dt.timezone(dt.timedelta(hours=9), "JST")
COND_WORDS = ("不良", "稍重", "重", "良")           # ⛔長いものから見る(「稍重」が「重」に食われないように)
WEATHER_WORDS = ("曇り", "晴れ", "晴", "曇", "雨", "雪", "小雨")

# ---------------------------------------------------------------- 名古屋の断面の呼び名(⛔ここ 1 か所)
# 公式の PDF は**無記名**。図は 右回り・ゴール前直線が下(下の直線のハロン棒が左へ小さくなる=
#   右→左に走る= ゴールは下の直線の左端)。そこから、コース図の中心から見た向きで名前を付ける。
NAGOYA_NAMES = {
    "up": "向正面",
    "down": "ゴール前直線",       # ⚠ここは画像= 文字認識で読む断面
    "upper_right": "3コーナー",
    "upper_left": "2コーナー",
    "lower_left": "1コーナー",
    "lower_right": "4コーナー",
}

# 画面に出る順= 馬が走る順(ゴール前直線 → 1 → 2 → 向正面 → 3 → 4)。⛔器は入れた順に返すので、ここで並べる
NAGOYA_ORDER = ["ゴール前直線", "1コーナー", "2コーナー", "向正面", "3コーナー", "4コーナー"]
# 笠松の地点の順(公式の印の順)。⛔紙の上での見つかり順で入れると画面がばらばらになる
KASAMATSU_ORDER = ["ゴール"] + list("①②③④⑤⑥⑦⑧⑨⑩")

# 文字認識の検算(§8①)。⛔1 つでも外れたらその断面は入れない
OCR_MIN_N, OCR_MAX_N = 10, 20                      # 個数(実測は 14〜15)
OCR_LO, OCR_HI = 5.0, 20.0                         # cm の range
OCR_MAX_STEP = 3.0                                 # 隣との差
OCR_QUANT = 0.5                                    # 刻み


# ================================================================ 小道具(通信あり)

def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        raw = res.read()
    if binary:
        return raw
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ================================================================ 読み手(純関数・通信なし)
# ⛔ここから下は通信も pdfplumber も使わない= テストはここだけを試す

def clean(s):
    """タグの中の字 → 1 行。⛔実体参照は戻すが、タグは作らない"""
    s = re.sub(r"<[^>]*>", " ", s or "")
    return re.sub(r"[\s\u3000]+", " ", _html.unescape(s)).strip()


def zen2han(s):
    """全角の数字と記号を半角に(公式は年度によって混ざる)"""
    return (s or "").translate(str.maketrans(
        "０１２３４５６７８９．：〜～－―ｔ", "0123456789.:~~--t"))


def norm_date(s):
    """'2026年9月10日' / '令和8年9月7日' / '2026.09.11' / '2026/09/07' → 'YYYY-MM-DD'。読めなければ None"""
    t = zen2han(s or "")
    m = re.search(r"令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", t)
    if m:
        y, mo, d = 2018 + int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})", t)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def pick_word(text, words):
    """その字が入っていれば返す(⛔長いものから= 「稍重」を「重」と読まない)"""
    t = text or ""
    for w in words:
        if w in t:
            return w
    return None


def row(track, d, kind, **kw):
    """1 行の形。⛔器の列と同じ名前(nar_sand_depth)"""
    r = {"track": track, "d": d, "kind": kind, "section": None, "offsets": None, "vals": None,
         "avg": None, "cond": None, "weather": None, "t": None, "note": None, "amount_t": None,
         "title": None, "src": None}
    r.update(kw)
    return r


def num_list(text):
    """'14.5-14-12.5' → [14.5, 14.0, 12.5]。読めない欠片は捨てる(⛔推測で埋めない)"""
    out = []
    for part in re.split(r"[-–—‐]", zen2han(text or "")):
        part = part.strip()
        if re.fullmatch(r"\d{1,2}(?:\.\d)?", part):
            out.append(float(part))
    return out


# ---------------------------------------------------------------- 高知(HTML の記事)

def kochi_rows(paras, title, url):
    """記事の段落 → 行。paras= <p> の中身(<br> は改行のまま)。

    ⛔「馬場状態の変更」の記事は拾わない(砂とは無関係)。⚠15 個でない行は**ある分だけ**入れる。
    """
    title = clean(title)
    if "馬場状態の変更" in title:
        return []
    flat = " ".join(clean(p.replace("\n", " ")) for p in paras)
    d = norm_date(title) or norm_date(flat)
    if not d:
        return []
    out = []
    # ③ 補充(「〇ｔ のクッション砂を補充しました」)
    if "補充" in flat and ("クッション砂" in flat or "砂" in flat):
        m = re.search(r"(\d+(?:\.\d+)?)\s*t\s*の(?:クッション)?砂", zen2han(flat))
        if m:
            body = next((clean(p) for p in paras if "補充" in p), flat)
            out.append(row("高知", norm_date(body) or d, "refill", note=body,
                           amount_t=float(m.group(1)), title=title, src=url))
    # ①② 測定(地点名 + 「-」区切りの値)
    t = None
    mt = re.search(r"(\d{1,2})\s*時\s*(\d{1,2})\s*分", zen2han(flat))
    if mt:
        t = "%d時%d分" % (int(mt.group(1)), int(mt.group(2)))
    cond = None
    mc = re.search(r"馬場状態[\s\u3000]*(\S+)", flat)
    if mc:
        cond = pick_word(mc.group(1), COND_WORDS)
    for p in paras:
        lines = [clean(x) for x in p.split("\n")]
        lines = [x for x in lines if x]
        if len(lines) < 2:
            continue
        name, vals = lines[0], num_list(lines[1])
        if not vals or not name or "砂" in name:
            continue
        out.append(row("高知", d, "measure", section=name,
                       offsets=[float(i + 1) for i in range(len(vals))], vals=vals,
                       cond=cond, t=t, title=title, src=url))
    return out


def kochi_list_items(html, base="https://www.keiba.or.jp/"):
    """一覧 → [(記事の url, 見出し)]。⛔「馬場状態」の記事だけ(変更のお知らせは kochi_rows が落とす)"""
    out, seen = [], set()
    for m in re.finditer(r'<article id="post-(\d+)"(.*?)</article>', html or "", re.S):
        pid, body = m.group(1), m.group(2)
        t = re.search(r'class="entry-title entry-title-link"[^>]*>([^<]+)', body)
        if not t or pid in seen:
            continue
        seen.add(pid)
        out.append((base + "?p=" + pid, clean(t.group(1))))
    return out


def kochi_paras(html):
    """記事 → <p> の中身(<br> は改行に)。⛔本文の外は見ない"""
    m = re.search(r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>', html or "", re.S)
    body = m.group(1) if m else ""
    return [re.sub(r"<br\s*/?>", "\n", p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]


# ---------------------------------------------------------------- 名古屋(PDF の文字)

def char_angle(ch):
    """文字の回し方(度)。0= そのまま。放射状に置いた数字はここで分かれる"""
    a, b = ch["matrix"][0], ch["matrix"][1]
    return round(math.degrees(math.atan2(b, a)), 1)


def _rot(ch, deg):
    """その角度の「横書き」に戻したときの (u=進む向き, v=行の位置)"""
    r = math.radians(-deg)
    cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["y0"] + ch["y1"]) / 2
    return cx * math.cos(r) - cy * math.sin(r), cx * math.sin(r) + cy * math.cos(r)


def nagoya_cells(chars, deg, gap=5.0):
    """同じ回し方の数字を v の隙間で 1 つずつに切る → [(値, 紙の x, 紙の top)]"""
    put = sorted((( _rot(c, deg), c) for c in chars), key=lambda t: -t[0][1])
    groups, cur = [], []
    for uv, c in put:
        if cur and abs(cur[-1][0][1] - uv[1]) > gap:
            groups.append(cur)
            cur = []
        cur.append((uv, c))
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        text = "".join(c["text"] for _, c in sorted(g, key=lambda t: t[0][0]))
        if not re.fullmatch(r"\d{1,2}(?:\.\d)?", text):
            continue
        out.append({"v": float(text),
                    "u": sum(uv[0] for uv, _ in g) / len(g),
                    "x": sum((c["x0"] + c["x1"]) / 2 for _, c in g) / len(g),
                    "top": sum((c["top"] + c["bottom"]) / 2 for _, c in g) / len(g)})
    return out


def same_column(cells, tol=5.0):
    """1 本の断面= u(横切る向きの位置)が同じマスの並び。⚠見出しの数字が同じ角度に混ざるので、
    いちばん大きなかたまりだけを残す(実測: 「第 16 回」の 16 が向正面の列に紛れた)。"""
    best = []
    for anchor in cells:
        got = [c for c in cells if abs(c["u"] - anchor["u"]) <= tol]
        if len(got) > len(best):
            best = got
    return best


def nagoya_name(dx, dy):
    """コース図の中心から見た向き → 断面の呼び名(⛔当サイトの呼び名・NAGOYA_NAMES が正本)"""
    if abs(dx) < abs(dy) / 2:
        return NAGOYA_NAMES["up"] if dy < 0 else NAGOYA_NAMES["down"]
    if dy < 0:
        return NAGOYA_NAMES["upper_right"] if dx > 0 else NAGOYA_NAMES["upper_left"]
    return NAGOYA_NAMES["lower_right"] if dx > 0 else NAGOYA_NAMES["lower_left"]


def nagoya_sections(chars, center, min_cells=8):
    """文字 → 断面ごとの値(内→外)。center= コース図の中心 (x, top)。

    ⛔紙の上の位置で分けない= **回し方で分ける**。内と外は中心からの距離の昇順(近い方が内柵)。
    """
    cx, cy = center
    by_ang = {}
    for c in chars:
        if c["text"] in "0123456789.":
            by_ang.setdefault(char_angle(c), []).append(c)
    out = []
    for ang, chs in by_ang.items():
        cells = same_column(nagoya_cells(chs, ang))
        if len(cells) < min_cells:
            continue                                  # 見出しの数字(令和 8 年度…)はここで落ちる
        cells.sort(key=lambda c: math.hypot(c["x"] - cx, c["top"] - cy))
        mx = sum(c["x"] for c in cells) / len(cells) - cx
        my = sum(c["top"] for c in cells) / len(cells) - cy
        out.append({"angle": ang, "name": nagoya_name(mx, my),
                    "vals": [c["v"] for c in cells]})
    out.sort(key=lambda s: NAGOYA_ORDER.index(s["name"]) if s["name"] in NAGOYA_ORDER else 99)
    return out


def rows_by_y(words, tol=4.0):
    """語 → 行(y が近いものをまとめ、x の順に並べる)"""
    lines = {}
    for w in words:
        lines.setdefault(round(((w["top"] + w["bottom"]) / 2) / tol), []).append(w)
    out = []
    for key in sorted(lines):
        got = sorted(lines[key], key=lambda w: w["x0"])
        out.append("".join(w["text"] for w in got))
    return out


def nagoya_header(words):
    """見出しの 5 項目。⛔様式が 2 通りある(全角/半角・分かち書き)ので字を寄せてから読む"""
    got = {"d": None, "t": None, "weather": None, "cond": None, "title": None}
    for line in rows_by_y(words):
        flat = zen2han(line).replace(" ", "")
        if "測定年月日" in flat:
            got["d"] = norm_date(flat.split("測定年月日", 1)[1])
        elif "測定時間" in flat:
            m = re.search(r"(\d{1,2}:\d{2})\s*[~]\s*(\d{1,2}:\d{2})", flat)
            if m:
                got["t"] = m.group(1) + "～" + m.group(2)
        elif "馬場状態" in flat:
            got["cond"] = pick_word(flat.split("馬場状態", 1)[1], COND_WORDS)
        elif "候" in flat and len(flat) < 12:
            got["weather"] = pick_word(flat.split("候", 1)[1], WEATHER_WORDS)
        elif "開" in flat and "催" in flat and "令和" in flat:
            got["title"] = re.sub(r"^.*?催", "", line).strip()
    return got


def check_ocr(vals):
    """文字認識の検算(§8①)。⛔1 つでも外れたら False= その断面は入れない"""
    if not vals or not (OCR_MIN_N <= len(vals) <= OCR_MAX_N):
        return False
    for v in vals:
        if not (OCR_LO <= v <= OCR_HI):
            return False
        if abs(round(v / OCR_QUANT) * OCR_QUANT - v) > 1e-9:
            return False
    for a, b in zip(vals, vals[1:]):
        if abs(a - b) > OCR_MAX_STEP:
            return False
    return True


def ocr_value(text):
    """文字認識の 1 マス → cm。名古屋は**必ず小数 1 桁**で刷る(実測 75 値)ので、
    数字だけ取って 10 で割る(「85」→ 8.5・点は小さくて落ちることがある)。⛔3 桁を超えたら読めなかった扱い。"""
    d = re.sub(r"[^0-9]", "", text or "")
    if not (2 <= len(d) <= 3):
        return None
    return int(d) / 10


# ---------------------------------------------------------------- 笠松(PDF の文字)

def kasamatsu_points(words, curves, line_tol=10.0):
    """語と曲線 → 11 地点 × 4 値 + 印字の平均。

    ⛔白い字は呼ぶ前に捨てておく(コースの絵の中に見えない数字が埋まっている)。
    規則は 2 つだけ= ①地点の印(ゴール・①〜⑩)は内柵の上= 印と同じ縦線/横線に並ぶ数字がその地点の値・
    印に近い順に 1㍍ 3㍍ 5㍍ 7㍍ ②5 つめは間が空く= それが □ の平均。
    """
    num_re = re.compile(r"^\d{1,2}(?:\.\d)?$")        # ⚠"⑦".isdigit() は True= 丸数字を弾く
    nums = [w for w in words if num_re.match(w["text"])]
    marks = []
    for w in words:
        t = w["text"]
        if len(t) == 1 and t in "①②③④⑤⑥⑦⑧⑨⑩➉":
            marks.append({"t": "⑩" if t == "➉" else t, "x": _cx(w), "y": _cy(w)})
        elif t.startswith("ゴール"):
            marks.append({"t": "ゴール", "x": _cx(w), "y": _cy(w)})
    out = []
    for m in marks:
        col = [w for w in nums if abs(_cx(w) - m["x"]) <= line_tol]
        rowv = [w for w in nums if abs(_cy(w) - m["y"]) <= line_tol]
        line = col if len(col) >= len(rowv) else rowv
        if len(line) < 5:
            continue
        seq = sorted(line, key=lambda w: (_cx(w) - m["x"]) ** 2 + (_cy(w) - m["y"]) ** 2)
        vals = [float(w["text"]) for w in seq[:4]]
        out.append({"section": m["t"], "offsets": [1.0, 3.0, 5.0, 7.0], "vals": vals,
                    "avg": float(seq[4]["text"])})
    out.sort(key=lambda p: KASAMATSU_ORDER.index(p["section"])
             if p["section"] in KASAMATSU_ORDER else 99)
    return out


def circled(words, curves, candidates, max_width=60.0):
    """丸(楕円)の中にある字を返す。⛔笠松の天気と馬場は字ではなく丸で示す"""
    small = [c for c in curves if (c["x1"] - c["x0"]) <= max_width]
    for w in words:
        if w["text"] not in candidates:
            continue
        for c in small:
            if c["x0"] <= _cx(w) <= c["x1"] and c["top"] <= _cy(w) <= c["bottom"]:
                return w["text"]
    return None


def is_white(color):
    """紙と同じ色= 見えない字。⛔色の形は PDF によって (1.0,) だったり [1,1,1] だったりする"""
    try:
        vals = [float(v) for v in (color or ())]
    except (TypeError, ValueError):
        return False
    return bool(vals) and all(abs(v - 1.0) < 1e-6 for v in vals)


def drop_white(words):
    """見えない白い字を捨てる。⛔笠松はコースの絵の中に白い数字が 12 字埋まっていて、
    残すと隣の地点の値に紛れる(実測: ⑧ の 4 値が 1 つずれた)。"""
    return [w for w in words if not is_white(w.get("non_stroking_color"))]


def _cx(o):
    return (o["x0"] + o["x1"]) / 2


def _cy(o):
    return (o["top"] + o["bottom"]) / 2


# ================================================================ PDF を開くところ(pdfplumber)

def pdf_page(raw):
    """PDF のバイト列 → 1 ページ目。⛔原本は残さない(呼び出し側で with)"""
    import io
    import pdfplumber
    return pdfplumber.open(io.BytesIO(raw))


def page_chars(page):
    keys = ("text", "x0", "x1", "y0", "y1", "top", "bottom", "size", "matrix", "non_stroking_color")
    return [{k: c.get(k) for k in keys} for c in page.chars]


def page_words(page, x_tolerance=1.5, white=False):
    got = page.extract_words(x_tolerance=x_tolerance, extra_attrs=["non_stroking_color"])
    if not white:
        got = drop_white(got)
    keys = ("text", "x0", "x1", "top", "bottom")
    return [{k: w.get(k) for k in keys} for w in got]


def page_curves(page):
    return [{k: c.get(k) for k in ("x0", "x1", "top", "bottom")} for c in page.curves]


# ================================================================ 文字認識(本命 Tesseract・予備 AI)

TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _cells_of(img, dark=140, min_ratio=0.02):
    """マス目(横線で区切られた帯)に切る。戻り= [(上, 下)]"""
    from PIL import Image
    # 1 行ぶんの明るさ= 幅 1 に縮めて平均を取る(⛔行ごとに数えると遅い)
    rows = list(img.resize((1, img.height), Image.BOX).convert("L").tobytes())
    out, start = [], None
    for y, v in enumerate(rows + [0]):
        if v >= dark and start is None:
            start = y
        elif v < dark and start is not None:
            if y - start > img.height * min_ratio:
                out.append((start, y))
            start = None
    return out


def column_image(page, dpi=400):
    """文字の無い断面(縦長の画像)を切り出し、**上下逆さま**を直した白黒画像にする。

    ⚠その断面の数字は 180 度回して刷ってある(目には 12.0 が 0.21 に見える)。
    """
    tall = [im for im in page.images if (im["bottom"] - im["top"]) > 2 * (im["x1"] - im["x0"])]
    if not tall:
        return None
    im = min(tall, key=lambda i: (i["x1"] - i["x0"]))
    box = (max(im["x0"] - 1, 0), max(im["top"] - 1, 0),
           min(im["x1"] + 1, page.width), min(im["bottom"] + 1, page.height))
    pil = page.crop(box).to_image(resolution=dpi).original
    return pil.rotate(180).convert("L")


def ocr_tesseract(img):
    """本命。1 マスずつ読む(マスの外に白い縁を足す= Tesseract は縁が無いと外す)。
    戻り= 内→外 の値の list(読めなかったマスは None)。"""
    from PIL import Image, ImageOps
    import pytesseract
    if not getattr(pytesseract.pytesseract, "tesseract_cmd", None) or \
            not os.path.exists(pytesseract.pytesseract.tesseract_cmd):
        for cand in TESSERACT_CANDIDATES:
            if os.path.exists(cand):
                pytesseract.pytesseract.tesseract_cmd = cand
                break
    got = []
    pad = int(img.width * 0.10)
    for a, b in _cells_of(img):
        cell = img.crop((pad, a, img.width - pad, b))
        cell = cell.resize((cell.width * 3, cell.height * 3), Image.LANCZOS)
        cell = ImageOps.expand(cell, border=40, fill=255)
        txt = pytesseract.image_to_string(
            cell, config="--psm 8 -c tessedit_char_whitelist=0123456789.")
        got.append(ocr_value(txt))
    got.reverse()                                     # 180 度回してあるので、読んだ順は 外→内
    return got


def ocr_ai(img, key, model="claude-sonnet-5"):
    """予備。本命が検算で落ちた日だけ。⛔鍵が無ければ何もしない(便は止めない)"""
    import base64
    import io
    import anthropic
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    msg = anthropic.Anthropic(api_key=key).messages.create(
        model=model, max_tokens=300,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": "この表のマスに入っている数字を上から順に、JSON の配列だけで返してください。"
                                     "例: [12.0, 11.0, 10.5]。数字以外は書かないでください。"}]}])
    text = "".join(getattr(b, "text", "") for b in msg.content)
    m = re.search(r"\[[^\]]*\]", text)
    if not m:
        return []
    try:
        got = [float(x) for x in json.loads(m.group(0))]
    except (ValueError, TypeError):
        return []
    got.reverse()
    return got


def read_image_section(page, ai_key=None):
    """画像の断面 → (値の list, どうやって読んだか)。検算に落ちたら ([], 理由)"""
    try:
        img = column_image(page)
    except Exception as e:                             # noqa: BLE001
        return [], "画像を切り出せない(%s)" % type(e).__name__
    if img is None:
        return [], "縦長の画像が無い"
    try:
        vals = ocr_tesseract(img)
    except Exception as e:                             # noqa: BLE001
        vals = []
        print("   ⚠Tesseract が使えません(%s: %s)" % (type(e).__name__, str(e)[:60]))
    if vals and all(v is not None for v in vals) and check_ocr(vals):
        return vals, "文字認識(Tesseract)"
    if ai_key:
        try:
            vals = ocr_ai(img, ai_key)
        except Exception as e:                         # noqa: BLE001
            print("   ⚠予備の読み手も駄目(%s)" % type(e).__name__)
            vals = []
        if vals and check_ocr(vals):
            return vals, "文字認識(予備)"
    return [], "検算に通らない"


# ================================================================ 場ごとの取り込み

def take_kochi(cfg, known):
    """高知= 一覧(?cat=36)→ 記事。⛔既に入っている src は開かない"""
    rows, skipped, ng = [], 0, 0
    for page_no in range(1, cfg["pages"] + 1):
        url = "https://www.keiba.or.jp/?cat=36" + ("&paged=%d" % page_no if page_no > 1 else "")
        items = kochi_list_items(fetch(url))
        print("  一覧 %s → 記事 %d 本" % (url, len(items)))
        for art, title in items:
            d = norm_date(title)
            if d and d < cfg["since"]:
                skipped += 1
                continue
            if art in known:
                skipped += 1
                continue
            if cfg["limit"] <= 0:
                break
            time.sleep(SLEEP)
            try:
                got = kochi_rows(kochi_paras(fetch(art)), title, art)
            except Exception as e:                     # noqa: BLE001
                ng += 1
                print("   ⚠読めない %s (%s)" % (art, type(e).__name__))
                continue
            if not got:
                skipped += 1
                continue
            rows += got
            cfg["limit"] -= 1
            if cfg["limit"] <= 0:
                break
        if cfg["limit"] <= 0:
            break
    return rows, skipped, ng


def nagoya_news_pdfs(html):
    """ニュース一覧 → [(pdf の url, 掲載日, 見出し)]。⛔見出しに「砂厚測定」が入るものだけ"""
    out = []
    for m in re.finditer(r'<li>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', html or "", re.S):
        u, body = m.group(1), m.group(2)
        d = re.search(r"<time>\s*(\d{4})\.(\d{2})\.(\d{2})", body)
        t = re.search(r"<p>(.*?)</p>", body, re.S)
        if not (d and t):
            continue
        title = clean(t.group(1))
        if "砂厚測定" not in title or not u.lower().endswith(".pdf"):
            continue
        out.append((u, "%s-%s-%s" % d.groups(), title))
    return out


def nagoya_maintenance(html, src):
    """馬場整備状況の表 → maintenance 行。⚠器は 1 日 1 行なので、同じ日は 1 行にまとめる"""
    by_day = {}
    for m in re.finditer(r'<tr data-href="([^"]+)"[^>]*>(.*?)</tr>', html or "", re.S):
        td = [clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", m.group(2), re.S)]
        if len(td) < 2:
            continue
        d = norm_date(td[0])
        if not d or "砂厚測定" in td[1]:
            continue                                   # 測定は PDF から入れる(二重にしない)
        note = td[1] + ("(%s)" % td[2] if len(td) > 2 and td[2] else "")
        by_day.setdefault(d, []).append(note)
    return [row("名古屋", d, "maintenance", note="／".join(notes), title=notes[0], src=src)
            for d, notes in sorted(by_day.items())]


def take_nagoya(cfg, known):
    """名古屋= ①ニュース一覧の「砂厚測定」PDF ②馬場整備状況の表"""
    rows, skipped, ng = [], 0, 0
    dirt = "https://www.nagoyakeiba.com/info/race/dirt_course/index.html"
    news = nagoya_news_pdfs(fetch("https://www.nagoyakeiba.com/news/cat/"))
    print("  ニュース一覧 → 砂厚測定の PDF %d 本" % len(news))
    for u, posted, title in news:
        if u in known or (posted < cfg["since"]):
            skipped += 1
            continue
        if cfg["limit"] <= 0:
            break
        time.sleep(SLEEP)
        try:
            got = read_nagoya_pdf(fetch(u, binary=True), u, title, cfg)
        except Exception as e:                         # noqa: BLE001
            ng += 1
            print("   ⚠読めない %s (%s: %s)" % (u, type(e).__name__, str(e)[:60]))
            continue
        rows += got
        cfg["limit"] -= 1
    time.sleep(SLEEP)
    got = [r for r in nagoya_maintenance(fetch(dirt), dirt) if r["d"] >= cfg["since"]]
    print("  馬場整備状況 → %d 日ぶん" % len(got))
    rows += got
    return rows, skipped, ng


def read_nagoya_pdf(raw, url, title, cfg):
    """名古屋の PDF 1 本 → measure 行。5 断面は文字・1 断面(ゴール前直線)は文字認識"""
    with pdf_page(raw) as pdf:
        page = pdf.pages[0]
        head = nagoya_header(page_words(page, x_tolerance=3.0, white=True))
        chars = page_chars(page)
        big = max(page.images, key=lambda i: (i["x1"] - i["x0"]) * (i["bottom"] - i["top"])) \
            if page.images else None
        center = (((big["x0"] + big["x1"]) / 2, (big["top"] + big["bottom"]) / 2) if big
                  else (page.width / 2, page.height / 2))
        secs = nagoya_sections(chars, center)
        img_vals, how = ([], "画像を読まない") if cfg["no_ocr"] else read_image_section(page, cfg["ai_key"])
    d = head["d"] or norm_date(title)
    if not d:
        return []
    out = []
    for s in secs:
        out.append(row("名古屋", d, "measure", section=s["name"],
                       offsets=[float(i + 1) for i in range(len(s["vals"]))], vals=s["vals"],
                       cond=head["cond"], weather=head["weather"], t=head["t"],
                       title=title, src=url))
    if img_vals:
        out.append(row("名古屋", d, "measure", section=NAGOYA_NAMES["down"],
                       offsets=[float(i + 1) for i in range(len(img_vals))], vals=img_vals,
                       cond=head["cond"], weather=head["weather"], t=head["t"],
                       note=how, title=title, src=url))
    else:
        print("   ⚠%s の %s は入れません(%s)" % (d, NAGOYA_NAMES["down"], how))
    out.sort(key=lambda r: NAGOYA_ORDER.index(r["section"]) if r["section"] in NAGOYA_ORDER else 99)
    return out


def kasamatsu_news_items(html, base="https://www.kasamatsu-keiba.com"):
    """お知らせ一覧 → [(記事の url, 掲載日, 見出し)]。⛔「砂厚測定」か「砂の補充」だけ"""
    out = []
    for m in re.finditer(r"<li>(.*?)</li>", html or "", re.S):
        body = m.group(1)
        d = re.search(r"<time>\s*(\d{4})/(\d{2})/(\d{2})", body)
        a = re.search(r'<a href="(/news/detail/\d+)"[^>]*>(.*?)</a>', body, re.S)
        if not (d and a):
            continue
        title = clean(a.group(2))
        if "砂厚" not in title and "砂の補充" not in title:
            continue
        out.append((base + a.group(1), "%s-%s-%s" % d.groups(), title))
    return out


def take_kasamatsu(cfg, known):
    rows, skipped, ng = [], 0, 0
    base = "https://www.kasamatsu-keiba.com"
    items = kasamatsu_news_items(fetch(base + "/news"))
    print("  お知らせ一覧 → 砂厚の記事 %d 本" % len(items))
    for url, posted, title in items:
        if cfg["limit"] <= 0:
            break
        if url in known or posted < cfg["since"]:
            skipped += 1
            continue
        time.sleep(SLEEP)
        try:
            html = fetch(url)
            pdfs = re.findall(r'href="([^"]+\.pdf)"', html)
            if not pdfs:
                skipped += 1
                continue
            pdf_url = pdfs[0] if pdfs[0].startswith("http") else base + pdfs[0]
            time.sleep(SLEEP)
            got = read_kasamatsu_pdf(fetch(pdf_url, binary=True), url, title, posted)
        except Exception as e:                         # noqa: BLE001
            ng += 1
            print("   ⚠読めない %s (%s: %s)" % (url, type(e).__name__, str(e)[:60]))
            continue
        rows += got
        cfg["limit"] -= 1
    return rows, skipped, ng


def read_kasamatsu_pdf(raw, url, title, posted):
    with pdf_page(raw) as pdf:
        page = pdf.pages[0]
        words = page_words(page)                       # ⛔白い字は落としてある
        curves = page_curves(page)
    d = None
    for line in rows_by_y(words):
        d = d or norm_date(line) if ("年" in line and "月" in line) else d
    d = d or norm_date(title) or posted
    weather = circled(words, curves, set(WEATHER_WORDS))
    cond = circled(words, curves, set(COND_WORDS))
    out = []
    for p in kasamatsu_points(words, curves):
        out.append(row("笠松", d, "measure", section=p["section"], offsets=p["offsets"],
                       vals=p["vals"], avg=p["avg"], cond=cond, weather=weather,
                       title=title, src=url))
    return out


# ================================================================ 投入

def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def known_src(base, key, tracks):
    """既に入っている src。⛔同じ記事を二度開かないため(通信を増やさない)"""
    got = set()
    for track in tracks:
        path = ("%s/rest/v1/%s?select=src&track=eq.%s&order=d.desc&limit=%d"
                % (base.rstrip("/"), TABLE, urllib.request.quote(track), KNOWN_SRC_LIMIT))
        req = urllib.request.Request(path, headers={"apikey": key, "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                for r in json.loads(res.read().decode("utf-8")):
                    if r.get("src"):
                        got.add(r["src"])
        except Exception as e:                         # noqa: BLE001
            print("⚠既にある行を引けませんでした(%s)= 全部見に行きます" % type(e).__name__)
            return set()
    return got


def _post(base, key, rows, on_conflict=True):
    url = "%s/rest/v1/%s" % (base.rstrip("/"), TABLE)
    if on_conflict:
        url += "?on_conflict=track,d,kind,section"
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    head = {"apikey": key, "Authorization": "Bearer " + key,
            "Content-Type": "application/json", "Prefer": "return=minimal"}
    if on_conflict:
        head["Prefer"] += ",resolution=ignore-duplicates"
    req = urllib.request.Request(url, data=body, method="POST", headers=head)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.status


def insert_rows(base, key, rows):
    """入れる。⚠器の一意は式(coalesce(section,''))なので on_conflict が合わないことがある=
    そのときは 1 行ずつ入れ、二重(409)は「もうある」として飛ばす(⛔止めない)。"""
    if not rows:
        return 0, 0
    try:
        _post(base, key, rows)
        return len(rows), 0
    except urllib.error.HTTPError as e:
        why = e.read().decode("utf-8", "replace")[:160]
        print("⚠まとめて入れられません(HTTP %s: %s)= 1 行ずつにします" % (e.code, why))
    ok = dup = 0
    for r in rows:
        try:
            _post(base, key, [r], on_conflict=False)
            ok += 1
        except urllib.error.HTTPError as e:
            if e.code == 409:
                dup += 1
            else:
                print("⚠入れられません %s %s %s (HTTP %s)" % (r["track"], r["d"], r["section"], e.code))
    return ok, dup


# ================================================================ main

SITES = {"kochi": ("高知", take_kochi), "nagoya": ("名古屋", take_nagoya),
         "kasamatsu": ("笠松", take_kasamatsu)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_sand_depth へ入れる(既定はドライラン)")
    ap.add_argument("--env", help="SUPABASE_URL / SUPABASE_SERVICE_KEY のある .env")
    ap.add_argument("--site", choices=sorted(SITES), help="この場だけ")
    ap.add_argument("--since", default=SINCE_DEFAULT, help="この日より前は入れない(既定 %s)" % SINCE_DEFAULT)
    ap.add_argument("--pages", type=int, default=1, help="高知の一覧を何ページ読むか(既定 1)")
    ap.add_argument("--limit", type=int, default=40, help="1 回に新しく開く記事の数(既定 40)")
    ap.add_argument("--no-ocr", action="store_true", help="画像の断面を読まない(手元で速く試すとき)")
    a = ap.parse_args()

    env = load_env(a.env) if a.env else os.environ
    base, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
    sites = [a.site] if a.site else sorted(SITES)
    tracks = [SITES[s][0] for s in sites]
    known = known_src(base, key, tracks) if (base and key) else set()
    if known:
        print("既に入っている src %d 本は開きません" % len(known))

    rows, ok_sites = [], 0
    for site in sites:
        track, take = SITES[site]
        print("---- %s ----" % track)
        # ⛔--limit は**場ごと**に数える(1 場が使い切って次が空にならないように)
        cfg = {"since": a.since, "pages": a.pages, "limit": a.limit, "no_ocr": a.no_ocr,
               "ai_key": env.get("ANTHROPIC_API_KEY")}
        try:
            got, skipped, ng = take(cfg, known)
        except Exception as e:                         # noqa: BLE001
            print("⚠%s は取れませんでした(%s: %s)" % (track, type(e).__name__, str(e)[:80]))
            continue
        ok_sites += 1
        rows += got
        print("  → %d 行(飛ばした %d・読めなかった %d)" % (len(got), skipped, ng))

    print("== 合わせて %d 行 ==" % len(rows))
    for r in rows[:12]:
        vals = r["vals"]
        body = ("%s %s" % (r["section"], " ".join("%g" % v for v in vals))) if vals else (r["note"] or "")
        print("  %s %s %-11s %s%s" % (r["track"], r["d"], r["kind"], body[:72],
                                      ("  平均 %g" % r["avg"]) if r["avg"] is not None else ""))
    if len(rows) > 12:
        print("  …ほか %d 行" % (len(rows) - 12))
    if not ok_sites:
        print("⛔1 場も取れませんでした= 空を書かずに失敗させます")
        return 2
    if not a.apply:
        print("(ドライラン。入れるには --env pipeline/.env.nar --apply)")
        return 0
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY がありません")
        return 1
    try:
        ok, dup = insert_rows(base, key, rows)
    except Exception as e:                             # noqa: BLE001
        print("投入に失敗: %s" % e)
        return 1
    print("%s に %d 行入れました(もうあった %d)" % (TABLE, ok, dup))
    return 0


if __name__ == "__main__":
    sys.exit(main())

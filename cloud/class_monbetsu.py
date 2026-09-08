# -*- coding: utf-8 -*-
"""統合ビューア cloud: 門別の級別表PDFを読んで nar_meta へ入れる(DESIGN §38 1-E)。

ホッカイドウ競馬は**馬ごとの「級」と「番組賞金」を公式PDFで丸ごと配っている**——15場で唯一。
うちで計算した値ではなく**主催者の発表そのもの**なので、§38 のなかで最も正確な一枚になる。
1開催回につきPDF 2本(3歳以上=`monN-ipan.pdf` / 2歳=`monN-2sai.pdf`)しかないので通信も安い。

  出力 = nar_meta key='monbetsu_class' の value:
    {"built":"YYYY-MM-DD", "src":"official", "fy":2026, "kai":10, "asof":"2026-08-14",
     "asof_by":{"ipan":"2026-08-14","2sai":"2026-08-14"},
     "horses":{"シャンアリーズ":{"cls":"Ｃ４－３","prize":380000,"age":5,"tr":"桧森邦"}, …},
     "kais":[{"kai":1,"asof":"2026-04-10","n":548}, …]}
    cls   = **PDFの見出しそのまま**。単独(「Ｃ４－３」)・並記(「Ｃ３－２ Ｃ４－１」)・範囲
            (「Ｂ１～Ｂ３－１」)・語(「オープン」「新馬」「未勝利」)・条件(「３歳２００万円以下」)がある。
            **範囲を1クラスに決めつけない**(§38「推定と公式を混ぜない」)。主催者が級を刷っていない組は
            **null** にして、代わりに枠の題を grp に入れる(例「ＪＲＡ認定アタックチャレンジ競走」)。
    prize = 番組賞金。**PDFは万円・ここでは円**(×10000)。他所属馬は賞金が刷られず from に「ＪＲＡ」等。
    ほかに age(馬齢)・tr(調教師)・sex(2歳の牝)・born(2歳の早い回だけ載る生年月日 月/日)・
    mark(馬名の左の印。「補欠」「補１」「♦」「△」等。意味は発表されていない)。
    horses は**最新回だけ**(馬柱が見たいのは今の級)。過去回は --archive で 'monbetsu_class_hist' へ。
    kais = どの回まで取れたかの索引(差分更新の判断に使う。馬のデータは持たない)。

  py -3.12 -X utf8 cloud/class_monbetsu.py                    # ドライラン(既定)。scratchpad へ書くだけ
  py -3.12 -X utf8 cloud/class_monbetsu.py --backfill         # 今年度の第1回から全部
  py -3.12 -X utf8 cloud/class_monbetsu.py --kai 10 --verify  # 1回だけ+検品(頭数・級の分布・捨てた行)
  py -3.12 -X utf8 cloud/class_monbetsu.py --env pipeline/.env.nar --apply   # 実弾(nar_meta へ upsert)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply の書き込みだけ。読みは要らない)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗
⚠ローカル実行は **py -3.12 -X utf8**(py 単体は py.ini で 3.13-32 に解決され pdfplumber が無い)。

⛔ 実地で分かったこと(2026-08-27 調査。すべて実際に1敗してから書いている):
 1. **URL に年度が入っていない**。`mon11-ipan.pdf` 〜 `mon16-ipan.pdf` は**前年度(令和7年度)の残骸**が
    そのまま 200 で返る(Last-Modified 2025年)。→ **PDFの見出し「令和８年度 第１０回…」から年度を読み、
    狙った年度と違う回は捨てる**。URL や回次だけで年度を決めてはいけない。
 2. **一覧ページ(bangumi_dl.php)には最新の1回しか出ない**。過去回は URL 規則で総当たりするしかない。
    つまり**遡れるのは今年度のうち、まだ上書きされていない回まで**(2026-08-27 現在= 第1〜10回)。
 3. **組(級のまとまり)は長方形とは限らない**。馬が列から列へ流れ込むので「1列目は全高・2列目は上だけ」
    という階段形になる。「縦罫線の間 × 横罫線で区切り」で枠を作ると組が割れて級が付け違う
    (実測 mon5-ipan p3 の Ｃ４‐２=115頭)。→ 罫線が**その区間を実際に覆っているか**で繋ぐ(cells_of)。
 4. **2歳のPDFは行の形が違う**。3歳以上=「馬名 番組賞金 ⃝馬齢 調教師」/ 2歳=「馬名 番組賞金 [牝] 調教師」
    (馬齢は全部2歳なので無い・牝馬だけ印がつく)。**新馬の欄は番組賞金の列ごと無い**。
 5. **見出しは範囲のことがある**(「Ｂ１～Ｂ３－１」「Ｃ３－２ Ｃ４－１」)。1頭のクラスを1つに決められない。
    **級が1文字も刷られていない組もある**(ＪＲＡ認定アタックチャレンジ競走・発走調教検査必要馬)。
 6. **級別表は「その開催回に出られる馬の一覧」**。同じ馬が2度出ることは無い(10回×全ページで重複0)。
    紙面は距離区分でページが分かれるが、馬はどれか1つの組にだけ載る。
 7. **ハイフンが2種類**。PDF=「Ｃ３‐２」(U+2010)・DBの race_name=「Ｃ３－２」(U+FF0D)。→ 全角ハイフンに寄せる。
    さらに**PDFに打ち間違いがある**(「オ－プン」= 長音符のはずが U+FF0D。mon4-ipan p2)。
 8. 番組賞金の単位は**万円**(番組編成要領 第5 格付区分の但し書き「（番組賞金：単位 万円）」で確認)。
 9. **行を `round(y/4)` のような固定の升で切ると1語だけ別の行に飛ぶ**(同じ行でも y が 0.4pt ずれる)。
    実測 mon7-ipan p1 で「補１」だけ落ちて頭数が1頭ずれた。→ 隙間で切る(rows_of)。
10. **列の間隔は「馬名の並びの間隔の中央値」で取ってはいけない**。2頭しかいない列は並びとして拾えず
    間隔が飛ぶ。実測 mon8-ipan p4 で 100頭の組を 49頭 しか読めなかった。→ **いちばん狭い間隔**を使う。
11. **飾りの短い下線を横罫線と見なすと表が刻まれて馬が落ちる**(2歳の「※…」の下線 20pt)。
    → 組の区切りは最低でも馬の列1本ぶんの幅がある、で弾く。
12. **薄い帯(12pt)にも馬の行が乗っている**(組の切れ目が列でずれている紙面)。小さいからと捨てない。
13. **補欠(「補欠」「補１」)はPDFの頭数に入らない**(「ＪＲＡ所属馬（補欠除く）４頭」)。
    データとしては拾い、検品では外して数える。
14. **頭数の書き方が2通り**。内訳だけ(「ＪＲＡ所属馬 ５頭/他地区 １頭/北海道 ８頭」)と、
    そこに合計が付く形(「４頭 １頭 ７頭 １２頭」)。素直に足すと合計を二重に数える。

検品(2026-08-27 実施・令和8年度 第1〜10回 = PDF 20本):
 ・**組ごとの頭数 203組すべてPDFの記載と一致**(不一致 0)。
 ・**番組編成要領 第5「格付区分」との噛み合い 4,781行で矛盾 0**(賞金から出る級が見出しの範囲に入る)。
 ・**第10回1ページ目の50頭を画像から手で書き写して突合= 50/50 一致**(級/賞金/馬齢/調教師/所属)。
 ・**nar_races との粗い突合**= 令和8年度の門別 5,900走で**級と条件クラスの矛盾 0**
   (食い違いはすべて 重賞・オープン出走 と 格上挑戦、および ＪＲＡ交流競走の呼び方違い)。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env, upsert  # noqa: E402

UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"
SLEEP = 0.7
JST = dt.timezone(dt.timedelta(hours=9))
META_KEY = "monbetsu_class"
HIST_KEY = "monbetsu_class_hist"

SITE = "https://www.hokkaidokeiba.net"
INDEX = SITE + "/raceinfo/bangumi_dl.php"
PDF_DIR = SITE + "/hkj/bangumi/"
# 1開催回に2本。3歳以上(一般)と2歳で紙面の作りが違う(⛔4)
KINDS = ("ipan", "2sai")
KAI_MAX = 20            # 門別は年度16回前後。3回続けて空振りしたら打ち切る
KAI_BLANK_STOP = 3
MAN = 10000             # 番組賞金は万円(⛔8)


def log(msg):
    print(f"[{dt.datetime.now(JST):%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 取得

_last = [0.0]


def _wait():
    w = SLEEP - (time.monotonic() - _last[0])
    if w > 0:
        time.sleep(w)


def get(url, tries=2):
    """HTML。ホッカイドウ競馬のページは cp932(2026-08-27 実測)。"""
    for n in range(tries):
        _wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            raw = urllib.request.urlopen(req, timeout=25).read()
            for enc in ("cp932", "utf-8"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("cp932", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or n == tries - 1:
                raise
            time.sleep(2.0 * (n + 1))
        finally:
            _last[0] = time.monotonic()


def get_bin(url, tries=2):
    """PDF。中身と Last-Modified を返す(PDF内の作成日時が読めなかったときの控え)。"""
    for n in range(tries):
        _wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            res = urllib.request.urlopen(req, timeout=60)
            return res.read(), res.headers.get("Last-Modified")
        except urllib.error.HTTPError as e:
            if e.code < 500 or n == tries - 1:
                raise
            time.sleep(2.0 * (n + 1))
        finally:
            _last[0] = time.monotonic()


_PDFLIB = []


def pdf_lib():
    """pdfplumber は無い環境もある(cloud/requirements.txt)。ここでだけ import する。"""
    if not _PDFLIB:
        try:
            import pdfplumber
            _PDFLIB.append(pdfplumber)
        except Exception:
            _PDFLIB.append(None)
    return _PDFLIB[0]


# ---------------------------------------------------------------- 文字の正規化

def norm(text):
    """全角を半角へ寄せる。照合の前に必ず通す(§32c と同じ流儀)。"""
    return unicodedata.normalize("NFKC", str(text))


# NFKC が触らないハイフン類(⛔7)と波ダッシュ類。先に ASCII へ潰してから全角へ広げ直す
DASH_RE = re.compile(r"[‐‑‒–—―−－\-]")
WAVE_RE = re.compile(r"[〜～~〜]")
SPACE_RE = re.compile(r"[\s　]+")


def widen(text):
    """ASCII の英数記号を全角へ戻す。発表の見た目(Ｃ４－３)に合わせるため(§26.4)。"""
    out = []
    for ch in text:
        if "0" <= ch <= "9" or "A" <= ch <= "Z" or "a" <= ch <= "z":
            out.append(chr(ord(ch) + 0xFEE0))
        elif ch == "-":
            out.append("－")
        elif ch == "~":
            out.append("～")
        else:
            out.append(ch)
    return "".join(out)


def canon_cls(text):
    """見出しを1つの書き方に寄せる。「C３‐２」も「Ｃ３－２」も「Ｃ３－２」になる。
    ⚠ nar_races.race_name は全角ハイフン(U+FF0D)なので、そちらに合わせる(⛔7)。"""
    s = WAVE_RE.sub("~", DASH_RE.sub("-", norm(text)))
    return widen(SPACE_RE.sub("", s))


# 「Ａ１」「Ｃ４‐３」「Ｂ１～Ｂ３‐１」。範囲はそのまま持つ(⛔5)
ONE_RE = r"[ABCD]\d(?:-\d)?"
CLS_RE = re.compile(rf"^{ONE_RE}(?:~{ONE_RE})?$")
# クラスに当たる語のうち、記号で書かれないもの(級別表の見出しで実見したもの)
CLS_WORDS = {"オープン", "牝馬オープン", "新馬", "未勝利"}
# 3歳条件などは記号でなく**条件そのもの**を見出しにしている(実測「３歳200万円以下」「800万円以下」)。
# 主催者が刷った通りに持つ(これも公式の見出し)。
JOKEN_RE = re.compile(r"^(?:\d+歳)?[\d,]+万円以下$")
# ⛔PDF に**長音符の打ち間違い**がある(実測 mon4-ipan p2 の「オ－プン」= U+FF0D)。
# カタカナに挟まれたハイフン類は長音符として読む。
KATA_DASH_RE = re.compile(r"(?<=[ァ-ヴ])[‐‑‒–—―−－\-](?=[ァ-ヴ])")
# 2歳の新馬欄は年度の早い回だけ**番組賞金でなく生年月日**が入る(実測「4/20」)。捨てずに持つ。
BORN_RE = re.compile(r"^\d{1,2}/\d{1,2}$")
# ⚠**級ではない**区分の語。番組編成要領 第5 の3本立て(2歳/3歳条件/一般馬)と性別の断り。
# これだけの行を級の見出しと取ると嘘になる(実測: 「発走調教検査必要馬 / 一般馬」の枠。
# あれは検査が要る馬の一覧で、その馬の級ではない)。
SECTION_WORDS = {"一般馬", "３歳", "３歳条件", "２歳", "牝馬", "３歳以上", "牡馬", "２歳馬"}
# 「５頭」「２８頭」= その組の頭数。検品にそのまま使う
COUNT_RE = re.compile(r"^(\d+)頭$")
# 「〔ＪＲＡ〕」「〔川崎〕」= 他所属馬。番組賞金の欄に代わりに入る
FROM_RE = re.compile(r"^[〔\[(（]([^〕\])）]+)[〕\])）]$")
PRIZE_RE = re.compile(r"^[\d,]+$")
# 馬名。カタカナ(と長音・中黒)だけ。3歳以上/2歳とも実測でこれに収まる
NAME_RE = re.compile(r"^[ァ-ヶーヽヾ・ｦ-ﾟヴ]{2,}$")
# 馬名と番組賞金が1語にくっついたとき用(pdfplumber が隙間を詰めることがある)
NAME_NUM_RE = re.compile(r"^([ァ-ヶー・ヴ]{2,})([\d,]+)$")
# 調教師。漢字2〜5文字(門別は3文字表記。「佐々国」「五十冬」など)
TRAINER_RE = re.compile(r"^[一-鿿々]{2,5}$")
SEX_RE = re.compile(r"^[牝牡セせん騸]$")
# 丸数字 ①〜⑳ = 馬齢
CIRCLE = {chr(0x2460 + i): i + 1 for i in range(20)}
# 「令和８年度 第１０回門別競馬級別表」
TITLE_RE = re.compile(r"(令和|平成)\s*(元|\d+)\s*年度.*?第\s*(\d+)\s*回")
ERA = {"令和": 2018, "平成": 1988}


# 馬名の左の「補欠」「補１」「補２」= 予備登録。⚠PDF の頭数(「ＪＲＡ所属馬（補欠除く）４頭」)には
# 入っていないので、検品では外して数える。データとしては拾って mark に残す。
SUB_RE = re.compile(r"^補(?:欠|\d+)?$")


def is_mark(text):
    """馬名の左に付く小さな印(「・」「♦」「△」…)。意味は発表されていないので拾って持つだけ。
    ⛔決め打ちの集合にすると新しい印で行ごと落ちる(2026-08-27 に ♦ と △ で 29頭 落とした)ので、
    記号かどうかで見る。"""
    return 1 <= len(text) <= 2 and all(
        unicodedata.category(c)[0] in "SP" for c in text)


def fy_of(era, num):
    return ERA[era] + (1 if num == "元" else int(num))


# ---------------------------------------------------------------- 一覧ページ

# <li><a href='…/mon10-ipan.pdf' …>３歳以上</a></li> と 「第１０回　門別競馬（８月１８日〜…）」
KYU_BLOCK_RE = re.compile(r"級別表.*?</dl>", re.S)
PDF_HREF_RE = re.compile(r"href=['\"]([^'\"]*?/hkj/bangumi/mon(\d+)-(ipan|2sai)\.pdf)['\"]", re.I)
FY_HEAD_RE = re.compile(r"<h2>\s*(令和|平成)\s*([元０-９\d]+)\s*年度")
KAI_LABEL_RE = re.compile(r"第([０-９\d]+)回\s*門別競馬\s*[（(]([^）)]*)[）)]")


def index_head():
    """一覧ページから (年度, 最新の回, その回の開催期間) を読む。
    ⛔ここに出るのは**最新の1回だけ**。過去回は URL 規則で総当たりする(⛔2)。"""
    page = get(INDEX)
    m = FY_HEAD_RE.search(page)
    if not m:
        raise SystemExit("一覧ページの年度見出し(<h2>令和…年度)が読めない。紙面が変わった可能性")
    fy = fy_of(m.group(1), norm(m.group(2)))
    kai, period = None, None
    blk = KYU_BLOCK_RE.search(page)
    if blk:
        hits = PDF_HREF_RE.findall(blk.group(0))
        if hits:
            kai = max(int(h[1]) for h in hits)
    if kai is None:                       # 級別表のブロックが見つからないときは全リンクから
        hits = PDF_HREF_RE.findall(page)
        if not hits:
            raise SystemExit("一覧ページに級別表PDFのリンクが1本も無い")
        kai = max(int(h[1]) for h in hits)
    for num, span in KAI_LABEL_RE.findall(page):
        if int(norm(num)) == kai:
            period = norm(span).replace(" ", "")
            break
    return fy, kai, period


def pdf_url(kai, kind):
    return f"{PDF_DIR}mon{kai}-{kind}.pdf"


# ---------------------------------------------------------------- PDF の読み方
# 紙面は「1ページ=1つの距離区分」。**罫線で仕切られた枠=1つの組(級)**で、見出しはその枠の真ん中に出る。
# ⛔枠の中に馬の列が1〜3本入る(1枠1列と思い込むと 439頭 が見出し無しで落ちる=2026-08-27 の1敗)。
# 枠 = 縦罫線どうしの間 × その幅いっぱいに引かれた横罫線での区切り。列の間隔は馬名の x0 から出す。

def rules(page):
    """縦罫線の x と、横罫線の (y, x0, x1)。line と rect の両方から拾う(PDFで作り方が違う)。"""
    vs, hs = [], []
    for o in list(page.lines) + list(page.rects):
        x0, x1, t, b = o["x0"], o["x1"], o["top"], o["bottom"]
        if abs(x1 - x0) < 2 and b - t > 5:
            vs.append((round((x0 + x1) / 2, 1), t, b))
        elif abs(b - t) < 2 and x1 - x0 > 5:
            hs.append((round((t + b) / 2, 1), x0, x1))
    return vs, hs


def dedupe(xs, tol=3.0):
    out = []
    for x in sorted(xs):
        if not out or x - out[-1] > tol:
            out.append(x)
        else:
            out[-1] = (out[-1] + x) / 2
    return out


def name_anchors(words):
    """馬名らしい語の x0 を寄せ集めて、列の左端の候補を返す。"""
    xs = [w["x0"] for w in words
          if NAME_RE.match(w["text"]) or NAME_NUM_RE.match(w["text"])]
    groups, cur = [], []
    for x in sorted(xs):
        if cur and x - cur[-1] > 4:
            groups.append(cur)
            cur = []
        cur.append(x)
    if cur:
        groups.append(cur)
    return [(sum(g) / len(g), len(g)) for g in groups if len(g) >= 3]


def axis(items, tol=3.0):
    """[(座標, 端a, 端b)] → {代表座標: [覆っている区間(重なりは畳む)]}。罫線は同じ線が
    2本(内側と外側)引かれていたり、途中で切れていたりする。"""
    keys = dedupe([c for c, _, _ in items], tol)
    out = defaultdict(list)
    for c, a, b in items:
        out[min(keys, key=lambda k: abs(k - c))].append((min(a, b), max(a, b)))
    for k, spans in out.items():
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 2:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out[k] = [tuple(m) for m in merged]
    return dict(out)


def covered(spans, a, b, eps=3.0):
    return any(t <= a + eps and bo >= b - eps for t, bo in spans)


NOMINAL_PITCH = 240.0                      # 実測 220〜240。列が1本しか見つからない紙面の当て


def pitch_of(words, left, right, drop):
    """馬の列の間隔。紙面はページ全体で等間隔(実測 220〜240pt)。
    ⛔**間隔の中央値を使ってはいけない**。馬が2頭しかいない列は馬名の並びとして拾えず、
      その分だけ間隔が飛ぶ(実測 mon8-ipan p4 で 234 と 468 が並び、中央値 468 → 列を 5本 でなく
      2本と見て 100頭の組を 49頭 しか読めなかった)。**いちばん狭い間隔**が本当の列の間隔。"""
    anchors = name_anchors(words)
    if not anchors:
        return None
    diffs = [b - a for (a, _), (b, _) in zip(anchors, anchors[1:])]
    base = min(diffs) if diffs else NOMINAL_PITCH
    ncol = max(1, round((right - left) / base))
    pitch = (right - left) / ncol
    # 馬名の並びが格子に乗らなければ列の割り方が違う=黙って進まない
    off = anchors[0][0] - left - round((anchors[0][0] - left) / pitch) * pitch
    for x, n in anchors:
        if abs((x - left - off) / pitch - round((x - left - off) / pitch)) * pitch > 12:
            drop.append(f"馬名の並び x={x:.0f}({n}語)が列の格子({ncol}列・間隔{pitch:.0f})に乗らない")
    return pitch


def cells_of(page, words, drop):
    """このページの組を返す。組は**罫線で囲まれたひとつながりの領域**で、
    [(x0,x1,y0,y1), …] の小さな長方形の集まりとして返す(左端 と 列の間隔 も返す)。

    ⛔組は長方形とは限らない。門別の紙面は**馬が列から列へ流れ込む**ので、
      「1列目は全高・2列目は上だけ」のような階段形の組になる(実測 mon5-ipan p3 の Ｃ４‐２=115頭)。
      枠を「縦罫線の間×横罫線での区切り」と単純に取ると、この組が2つに割れて級が付け違う。
      → 罫線が**その区間を実際に覆っているか**を見て、覆っていない所は同じ組として繋ぐ。"""
    vs, hs = rules(page)
    # ⛔飾りの短い線を罫線と見なすと表が刻まれて馬が落ちる(2026-08-27: 2歳の紙面の「※…」の
    #   下線 20pt/36pt を横罫線に取り、その高さの行ごと 2頭ずつ消えた)。組の区切りは
    #   最低でも馬の列1本ぶんの幅がある。
    vs = [v for v in vs if v[2] - v[1] >= 30]
    if not vs or not hs:
        drop.append("罫線が読めないページ(組に分けられない)")
        return [], None, None
    V = axis([(x, t, b) for x, t, b in vs])
    xs = sorted(V)
    if len(xs) < 2:
        drop.append("縦罫線が2本に満たない")
        return [], None, None
    left, right = xs[0], xs[-1]
    pitch = pitch_of(words, left, right, drop)
    if not pitch:
        return [], None, None
    H = axis([(y, a, b) for y, a, b in hs if b - a >= pitch * 0.5])
    ys = sorted(H)
    if len(ys) < 2:
        drop.append("横罫線が2本に満たない")
        return [], None, None
    nx, ny = len(xs) - 1, len(ys) - 1
    parent = list(range(nx * ny))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b

    for i in range(1, nx):                 # 縦の境目: その高さを覆う縦罫線が無ければ繋ぐ
        for j in range(ny):
            if not covered(V[xs[i]], ys[j], ys[j + 1]):
                union((i - 1) * ny + j, i * ny + j)
    for j in range(1, ny):                 # 横の境目: その幅を覆う横罫線が無ければ繋ぐ
        for i in range(nx):
            if not covered(H[ys[j]], xs[i], xs[i + 1]):
                union(i * ny + j - 1, i * ny + j)
    groups = defaultdict(list)
    for i in range(nx):
        for j in range(ny):
            # ⛔薄い帯を「小さいから」と捨ててはいけない。組の切れ目が列によってずれている紙面では
            #   帯そのものに馬の行が乗っている(実測 mon7-ipan p1: y=386 と y=398.5 に別々の
            #   区切り線があり、その隙間の 12.5pt に「ツキヨザクラ 42」が1頭いた)。
            #   帯は上下どちらかと必ず繋がるので、繋げ方は下の union に任せる。
            if ys[j + 1] - ys[j] > 2 and xs[i + 1] - xs[i] > 15:
                groups[find(i * ny + j)].append((xs[i], xs[i + 1], ys[j], ys[j + 1]))
    out = sorted(groups.values(), key=lambda g: (min(r[0] for r in g), min(r[2] for r in g)))
    for x, n in name_anchors(words):
        if not any(a - 14 <= x < b for g in out for a, b, _, _ in g):
            drop.append(f"馬名の並び x={x:.0f}({n}語)がどの組にも入らない")
    return out, pitch, left


ROW_GAP = 5.0                              # 行の間隔は 12pt。同じ行の語の y のばらつきは 1pt 未満


def rows_of(page, x_tol=2.0):
    """語を y でまとめて行にする。
    ⛔`round(y/4)` のような固定の升で切ってはいけない。同じ行でも y が 0.4pt ずれることがあり、
      升の境目にかかると1語だけ別の行に飛ぶ(実測 mon7-ipan p1: 「補１」top=261.7 と
      「メイショウノヴァス」top=262.1 が別の行になり、補欠の印が落ちて頭数が1頭ずれた)。"""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False, x_tolerance=x_tol)
    out, cur = [], []
    for w in sorted(words, key=lambda w: w["top"]):
        if cur and w["top"] - cur[0]["top"] > ROW_GAP:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return words, [(g[0]["top"], sorted(g, key=lambda w: w["x0"])) for g in out]


def parse_cell(cell, drop, where):
    """1頭ぶんの語の並び → dict。読めなければ None(理由は drop へ)。
      3歳以上: 馬名 [番組賞金|〔ＪＲＡ〕] ⃝馬齢 調教師
      2歳    : 馬名 [番組賞金] [牝] 調教師     (新馬の欄は賞金ごと無い)
    """
    ws = list(cell)
    mark = None
    while ws and (is_mark(ws[0]["text"]) or SUB_RE.match(norm(ws[0]["text"]))):
        mark = norm(ws.pop(0)["text"])
    if len(ws) < 2:
        return None
    first, last = ws[0]["text"], ws[-1]["text"]
    if not TRAINER_RE.match(last):
        return None
    name, extra = first, None
    if not NAME_RE.match(name):
        m = NAME_NUM_RE.match(name)        # 馬名と賞金がくっついた語
        if not m:
            return None
        name, extra = m.group(1), m.group(2)
    row = {"name": unicodedata.normalize("NFKC", name), "tr": last}
    if mark:
        row["mark"] = mark
    mids = [w["text"] for w in ws[1:-1]]
    if extra:
        mids.insert(0, extra)
    for t in mids:
        if PRIZE_RE.match(t):
            row["prize"] = int(t.replace(",", "")) * MAN
        elif BORN_RE.match(norm(t)):
            row["born"] = norm(t)          # 生年月日(月/日)。年は書いていないので足さない
        elif t in CIRCLE:
            row["age"] = CIRCLE[t]
        elif SEX_RE.match(t):
            row["sex"] = t
        elif FROM_RE.match(t):
            row["from"] = FROM_RE.match(t).group(1)   # 発表のまま(「ＪＲＡ」「川崎」「兵庫」)
        else:
            drop.append(f"{where} {row['name']}: 読めない語 {t!r}(捨てる)")
    return row


CLS_WORDS_A = {SPACE_RE.sub("", norm(w)) for w in CLS_WORDS}
SECTION_A = {SPACE_RE.sub("", norm(w)) for w in SECTION_WORDS}
HEAD_VOCAB = sorted(CLS_WORDS_A | SECTION_A, key=len, reverse=True)
HEAD_TOKEN_RE = re.compile(rf"^{ONE_RE}(?:~{ONE_RE})?")


def head_of_line(joined):
    """1行ぶんの文字列が**級の見出しだけ**でできていれば見出しとして返す。そうでなければ None。
    ⚠語の切れ方が主催者まかせ(「新　馬」は2語・「Ｃ３‐２ Ｃ４‐１」も2語)なので、行ごと繋げてから読む。
    ⚠クラス記号は**競走名の中にも出る**(「グランシャリオドリーム５１Ｃ３－２Ｃ４－１」)。
      題が混ざる行はここで弾かれる=見出しと題を取り違えない。"""
    s = KATA_DASH_RE.sub("ー", norm(joined))
    s = WAVE_RE.sub("~", DASH_RE.sub("-", s))
    s = SPACE_RE.sub("", s)
    s = re.sub(r"^(?:及び|及)", "", s)      # 「及び　未勝利」= 競走名の続きに見えるが級の行(2歳の紙面)
    if JOKEN_RE.match(s):                  # 「３歳200万円以下」= そのまま見出し
        return widen(s)
    out = []
    while s:
        m = HEAD_TOKEN_RE.match(s)
        if m:
            out.append(m.group(0))
            s = s[m.end():]
            continue
        for w in HEAD_VOCAB:
            if s.startswith(w):
                out.append(w)
                s = s[len(w):]
                break
        else:
            return None
    if not out or all(t in SECTION_A for t in out):
        return None                        # 区分だけの行(「一般馬」)は級の見出しではない
    return " ".join(widen(t) for t in out)


def head_label(lines):
    """組の中で**いちばん下にある「級だけの行」**を見出しにする。lines の鍵は行の y。
    ⛔「馬の1行目より上」で絞ってはいけない: 枠が紙面いっぱいのページでは 見出しの右に
      もう馬が並んでいて、1行目の y が見出しより上になる(2026-08-27 に 261頭 を level 無しで落とした)。
    ⚠クラス記号は競走名の行にも混ざるが、その行は題ごと繋がって tokenize に失敗する。
      それでも混ざったときは**下にあるほうが本物の見出し**(紙面はいつも「題 → 級 → 馬」の順)。"""
    for y in sorted(lines, reverse=True):
        got = head_of_line("".join(t for _, t in sorted(lines[y])))
        if got:
            return got, y
    return None, None


def parse_page(page, page_no, section, where, drop):
    """1ページ → 組の並び。組ごとに 見出し・馬・頭数。"""
    words, rws = rows_of(page)
    cells, pitch, left = cells_of(page, words, drop)
    if not cells:
        return []
    out = []
    for ci, rects in enumerate(cells):
        x0 = min(r[0] for r in rects)
        horses, said = [], []
        lines = defaultdict(list)
        for rx0, rx1, top, bottom in rects:
            nsub = max(1, round((rx1 - rx0) / pitch))
            sub = (rx1 - rx0) / nsub
            base = round((rx0 - left) / pitch)   # 紙面ぜんぶで通した列の番号(読み順に使う)
            for y, ws in rws:
                if not (top <= y < bottom):   # 半開区間=帯の境目でも二重に数えない
                    continue
                for k in range(nsub):
                    lo, hi = rx0 + k * sub, rx0 + (k + 1) * sub
                    cell = [w for w in ws if lo - 14 <= w["x0"] < hi - 14]
                    if not cell:
                        continue
                    row = parse_cell(cell, drop, f"{where} 組x{x0:.0f} y={y:.0f}")
                    if row:
                        horses.append((base + k, y, row))
                        continue
                    for w in cell:
                        plain = SPACE_RE.sub("", norm(w["text"]))
                        if COUNT_RE.match(plain):
                            said.append(int(COUNT_RE.match(plain).group(1)))
                        else:
                            lines[y].append((w["x0"], w["text"]))
        if not horses:
            continue                       # 説明書きだけの枠(「①３歳条件馬 ②番組賞金…」)は組ではない
        a, b = x0, max(r[1] for r in rects)
        label, hy = head_label(lines)
        # 級が刷られていない枠がある(実測 2歳の「ＪＲＡ認定アタックチャレンジ競走」= 43頭)。
        # ⚠ここで race_name から未勝利だと**決めない**(§38「推定と公式を混ぜない」)。cls は null。
        stop = hy if hy is not None else min(y for _, y, _ in horses)
        parts = []
        for y in sorted(y for y in lines if y < stop):
            t = SPACE_RE.sub(" ", " ".join(x for _, x in sorted(lines[y]))).strip()
            if t:
                parts.append(t)
        title = " ".join(parts[-2:])[:80] or None
        if label is None and horses:
            drop.append(f"{where} 枠x{a:.0f}-{b:.0f}: 級の見出しが刷られていない"
                        f"({len(horses)}頭・枠の題= {title!r})→ cls は null にした")
        # 読み順= 左のサブ列から上から下へ
        rows = [r for _, _, r in sorted(horses, key=lambda h: (h[0], h[1]))]
        out.append({"page": page_no, "sec": section, "col": ci + 1, "cls": label,
                    "title": title, "rows": rows, "said": said})
    return out


def pdf_created(pdf, last_modified):
    """基準日。PDF の作成日時(D:20260814113528+09'00')が一番確か。無ければ Last-Modified。"""
    raw = (pdf.metadata or {}).get("CreationDate") or ""
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", str(raw))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if last_modified:
        try:
            import email.utils
            t = email.utils.parsedate_to_datetime(last_modified).astimezone(JST)
            return f"{t:%Y-%m-%d}"
        except Exception:
            pass
    return None


def read_pdf(data, last_modified, kind, kai, want_fy, drop):
    """1本の級別表PDF → {"fy","kai","asof","blocks"}。年度は**中身から**読む(⛔1)。
    狙った年度と違えば中身は読まずに返す(前年度の残骸を無駄に解析しない)。"""
    pdfplumber = pdf_lib()
    blocks, fy, kai_in = [], None, None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        asof = pdf_created(pdf, last_modified)
        for i, page in enumerate(pdf.pages):
            words = page.extract_words()
            head = SPACE_RE.sub(" ", norm(" ".join(w["text"] for w in words[:8])))
            m = TITLE_RE.search(head)
            if m and fy is None:
                fy, kai_in = fy_of(m.group(1), m.group(2)), int(m.group(3))
                if fy != want_fy:
                    return {"fy": fy, "kai_in": kai_in, "asof": asof, "blocks": []}
            section = ""
            for w in words:
                t = norm(w["text"])
                if t.startswith("サラブレッド系") or t.startswith("アラブ系"):
                    section = SPACE_RE.sub("", t)
                    break
            where = f"mon{kai}-{kind} p{i+1}"
            got = parse_page(page, i + 1, section, where, drop)
            if not got:
                drop.append(f"{where}: 馬も見出しも取れない(白紙?)")
                continue
            blocks += got
    return {"fy": fy, "kai_in": kai_in, "asof": asof, "blocks": blocks}


# ---------------------------------------------------------------- 1開催回

def collect_kai(fy, kai, drop, cache=None):
    """1開催回(PDF 2本)→ {"kai","asof","fy","horses","blocks","files"}。
    年度違い(前年度の残骸)は None を返す(⛔1)。"""
    horses, blocks, files, asofs = {}, [], [], {}
    for kind in KINDS:
        url = pdf_url(kai, kind)
        try:
            if cache and (cache / f"mon{kai}-{kind}.pdf").exists():
                data, lm = (cache / f"mon{kai}-{kind}.pdf").read_bytes(), None
            else:
                data, lm = get_bin(url)
                if cache:
                    cache.mkdir(parents=True, exist_ok=True)
                    (cache / f"mon{kai}-{kind}.pdf").write_bytes(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                 # その回はまだ出ていない
            log(f"  第{kai}回 {kind}: HTTP {e.code}(飛ばす)")
            continue
        except Exception as e:
            log(f"  第{kai}回 {kind}: 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        try:
            got = read_pdf(data, lm, kind, kai, fy, drop)
        except Exception as e:
            drop.append(f"第{kai}回 {kind}: PDF が読めない {type(e).__name__}: {str(e)[:120]}")
            continue
        if got["fy"] != fy:
            log(f"  第{kai}回 {kind}: 令和{got['fy'] - 2018 if got['fy'] else '?'}年度のPDF"
                f"(狙いは令和{fy - 2018}年度)=前年度の残骸なので捨てる")
            return None
        if got["kai_in"] and got["kai_in"] != kai:
            drop.append(f"第{kai}回 {kind}: PDF の見出しは第{got['kai_in']}回(URLと違う)")
        files.append(url)
        if got["asof"]:
            asofs[kind] = got["asof"]
        blocks += got["blocks"]
        for b in got["blocks"]:
            for r in b["rows"]:
                put_horse(horses, r, b, drop)
    if not files:
        return None
    # ⚠同じ回でも2本の PDF の作成日が違うことがある(実測 第8回= 一般 7/17・2歳 7/23)。
    # asof は**遅いほう**(表がそろった日)。内訳も残す。
    return {"kai": kai, "fy": fy, "asof": max(asofs.values()) if asofs else None,
            "asof_by": asofs, "horses": horses, "blocks": blocks, "files": files}


def put_horse(horses, row, block, drop):
    """同じ馬が複数ページに出る(距離区分ごと・⛔6)。賞金が食い違えば言う。
    級は**より狭い見出し**を採る(「Ｂ１～Ｂ３－１」より「Ｃ４－３」)。範囲を1クラスに縮めはしない(⛔5)。"""
    key = row["name"]
    new = {k: v for k, v in row.items() if k != "name"}
    new["cls"] = block["cls"]              # 級が刷られていない枠は None(⚠推定しない)
    if block["cls"] is None and block.get("title"):
        new["grp"] = block["title"]        # 代わりに枠の題(競走名)を持つ
    old = horses.get(key)
    if old is None:
        horses[key] = new
        return
    if old.get("prize") != new.get("prize"):
        drop.append(f"{key}: 番組賞金が紙面で食い違う {old.get('prize')} と {new.get('prize')}"
                    f"(先に読んだ方を残す)")
    olds, news = old.get("cls"), new["cls"]
    if olds != news:
        if olds is None:
            old["cls"] = news
        elif news is not None:
            old["cls"] = news if cls_width(news) < cls_width(olds) else olds
            old.setdefault("cls_all", [olds])
            if news not in old["cls_all"]:
                old["cls_all"].append(news)
    for k, v in new.items():
        if v is not None:
            old.setdefault(k, v)


def cls_width(label):
    """見出しの狭さ。単独クラス=1・「Ｃ３－２ Ｃ４－１」=2・「Ｂ１～Ｂ３－１」は間の級の数。
    小さいほど狭い=そちらを採る。クラス記号でない見出し(オープン・新馬)は 1(そのまま採る)。"""
    total = 0
    for p in norm(label).replace("－", "-").replace("～", "~").split():
        if "~" in p:
            a, b = (cls_rank(x) for x in p.split("~", 1))
            total += 1 if (a is None or b is None) else max(1, abs(b - a) // 100 + 1)
        else:
            total += 1
    return total or 99


def cls_rank(label):
    """Ａ１－１ → 並び順の数(強い順に小さい)。Ａ１=1100・Ａ１－２=1102・Ｃ４=4400。
    ⚠狭さを測るためと検品のためだけ。出力の級の判定には使わない。"""
    m = re.match(r"([ABCD])(\d)(?:-(\d))?", norm(label).replace("－", "-").replace("‐", "-"))
    if not m:
        return None
    return ("ABCD".index(m.group(1)) + 1) * 1000 + int(m.group(2)) * 100 + int(m.group(3) or 0)


# ---------------------------------------------------------------- 検品

# 番組編成要領 第5「格付区分」(令和8年度・単位 万円)。⚠**年度で変わる**(§2.5)ので
# **出力には使わない**。抽出した賞金と見出しが噛み合っているかを見るためだけの物差し。
KAKUZUKE_2026 = [("Ａ１", 800, None), ("Ａ２", 600, 800), ("Ａ３", 500, 600), ("Ａ４", 400, 500),
                 ("Ｂ１", 350, 400), ("Ｂ２", 300, 350), ("Ｂ３", 250, 300), ("Ｂ４", 200, 250),
                 ("Ｃ１", 160, 200), ("Ｃ２", 120, 160), ("Ｃ３", 80, 120), ("Ｃ４", None, 80)]


def kaku_of(prize_yen):
    """番組賞金(円)→ 令和8年度の格付区分。**検品専用**。"""
    if prize_yen is None:
        return None
    man = prize_yen / MAN
    for name, lo, hi in KAKUZUKE_2026:
        if (lo is None or man > lo) and (hi is None or man <= hi):
            return name
    return None


def in_label(kaku, label):
    """その格付(Ａ１〜Ｃ４)が見出し(単独/並記/範囲)に収まるか。収まる True / 外 False /
    物差しの効かない見出し(オープン・新馬など)は None。"""
    r = cls_rank(kaku) if kaku else None
    if r is None:
        return None
    for p in norm(label).replace("－", "-").replace("～", "~").split():
        if not re.match(rf"^{ONE_RE}(?:~{ONE_RE})?$", p):
            return None                    # オープン・新馬などは物差しの外
    for p in norm(label).replace("－", "-").replace("～", "~").split():
        if "~" in p:
            a, b = (cls_rank(x) for x in p.split("~", 1))
            lo, hi = min(a, b), max(a, b)
            # 見出しの端は枝番つき(Ｂ３－１)なので、級そのもの(Ｂ３=b3*100)の幅で見る
            if lo - lo % 100 <= r <= hi:
                return True
        elif cls_rank(p) is not None and cls_rank(p) - cls_rank(p) % 100 == r:
            return True
    return False


def said_total(said):
    """PDF が刷っている頭数。「ＪＲＡ所属馬 ５頭 / 他地区 １頭 / 北海道 ８頭」のような内訳だけの組と、
    そこに**合計**が付く組(「４頭 １頭 ７頭 １２頭」)がある。⛔素直に足すと合計を二重に数える。
    いちばん大きい数が残りの合計と等しければ、それが合計。"""
    if not said:
        return None
    top = max(said)
    return top if len(said) > 1 and top == sum(said) - top else sum(said)


def verify(kai_data, drop):
    """検品: ①頭数がPDFの記載と合うか ②級の分布 ③賞金と見出しが噛み合うか。"""
    print()
    log(f"===== 検品 第{kai_data['kai']}回(令和{kai_data['fy'] - 2018}年度・基準日 {kai_data['asof']}) =====")
    bad = 0
    print("  -- ①組ごとの頭数(PDFの「◯頭」との突合。⚠補欠はPDFの数に入らないので外す) --")
    for b in kai_data["blocks"]:
        got = sum(1 for r in b["rows"] if not SUB_RE.match(r.get("mark") or ""))
        said = said_total(b["said"])
        ok = "OK " if said is not None and said == got else ("?? " if said is None else "NG ")
        if ok == "NG ":
            bad += 1
        cls = b["cls"] or f"(級なし){(b.get('title') or '')[:12]}"
        print(f"  {ok}p{b['page']} 枠{b['col']} {b['sec'][:22]:<24} {cls:<20}"
              f" 抽出 {got:>4} / 記載 {said if said is not None else '-':>4}"
              f"{'  ' + '+'.join(map(str, b['said'])) if b['said'] and len(b['said']) > 1 else ''}")
    total_got = sum(1 for b in kai_data["blocks"] for r in b["rows"]
                    if not SUB_RE.match(r.get("mark") or ""))
    total_said = sum(said_total(b["said"]) or 0 for b in kai_data["blocks"])
    subs = sum(1 for b in kai_data["blocks"] for r in b["rows"] if SUB_RE.match(r.get("mark") or ""))
    print(f"  合計 抽出 {total_got}頭(ほかに補欠 {subs}頭) / 記載 {total_said}頭 / 不一致の組 {bad}")

    print("  -- ②級の分布(実頭数。重複を畳んだあと) --")
    for cls, n in Counter(h.get("cls") or "(主催者が級を刷っていない枠)"
                          for h in kai_data["horses"].values()).most_common():
        print(f"     {cls:<24} {n:>4}頭")
    print(f"     ---- 実馬 {len(kai_data['horses'])}頭(延べ {total_got}行)")

    print("  -- ③番組賞金と見出しの噛み合い(番組編成要領 第5 格付区分・令和8年度の物差し) --")
    ok = ng = skip = 0
    ngs = []
    for b in kai_data["blocks"]:
        for r in b["rows"]:
            hit = in_label(kaku_of(r.get("prize")), b["cls"])
            if hit is None:
                skip += 1
            elif hit:
                ok += 1
            else:
                ng += 1
                ngs.append(f"{r['name']} {r.get('prize', 0)//MAN}万 → {kaku_of(r.get('prize'))}"
                           f" だが見出しは {b['cls']}")
    print(f"     合う {ok} / 合わない {ng} / 物差しの外(オープン・新馬・他所属など) {skip}")
    for line in ngs[:20]:
        print(f"     ⚠ {line}")
    if len(ngs) > 20:
        print(f"     …ほか {len(ngs) - 20} 件")
    if drop:
        print(f"  -- ④捨てた/気になった行 {len(drop)}件 --")
        for line in drop[:40]:
            print("     " + line)
        if len(drop) > 40:
            print(f"     …ほか {len(drop) - 40} 件")


# ---------------------------------------------------------------- まとめ

def sb_get_meta(base, key, meta_key):
    """既に入っている value(差分更新の判断に使う)。読めなければ None。"""
    if not base or not key:
        return None
    url = f"{base}/rest/v1/nar_meta?select=value&key=eq.{meta_key}"
    req = urllib.request.Request(url, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            rows = json.loads(r.read().decode("utf-8"))
        return rows[0]["value"] if rows else None
    except Exception as e:
        log(f"  既存 {meta_key} が読めない {type(e).__name__}: {str(e)[:80]}(新規として続ける)")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kai", type=int, help="この開催回だけ(既定=一覧に出ている最新回)")
    ap.add_argument("--backfill", action="store_true", help="今年度の第1回から全部")
    ap.add_argument("--fy", type=int, help="年度を指定(既定=一覧ページの見出し)")
    ap.add_argument("--verify", action="store_true", help="検品を出す(頭数・級の分布・噛み合い)")
    ap.add_argument("--archive", action="store_true",
                    help=f"過去回も nar_meta/{HIST_KEY} へ入れる(--apply と併用)")
    ap.add_argument("--apply", action="store_true", help="実際に nar_meta へ入れる(既定はドライラン)")
    ap.add_argument("--out", help="書き出し先(既定=scratchpad/class_monbetsu/)")
    ap.add_argument("--cache", help="PDF をここに貯めて2度目は取りに行かない(検品の反復用)")
    ap.add_argument("--env")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    if not pdf_lib():
        log("pdfplumber が入っていない(cloud/requirements.txt)。py -3.12 -X utf8 で動かすこと")
        return 2

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if args.apply and (not base or not key):
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い(--apply には要る)")
        return 2

    try:
        fy_idx, latest, period = index_head()
    except Exception as e:
        log(f"一覧ページが読めない {type(e).__name__}: {str(e)[:150]}")
        return 2
    fy = args.fy or fy_idx
    log(f"一覧: 令和{fy_idx - 2018}年度 / 最新の級別表 = 第{latest}回"
        f"{'(' + period + ')' if period else ''}")

    stored = sb_get_meta(base, key, META_KEY) if (base and key) else None
    done = {int(k["kai"]) for k in (stored or {}).get("kais", [])
            if (stored or {}).get("fy") == fy}
    if args.kai:
        todo = [args.kai]
    elif args.backfill:
        todo = list(range(1, max(latest, KAI_MAX) + 1))
    else:
        # 差分= まだ持っていない回 + 最新回(更正番組は出走前に作り直されるので毎回取り直す)
        todo = sorted(set(range(1, latest + 1)) - done | {latest})
    log(f"取りに行く回: {todo}" + (f" / 既にある回: {sorted(done)}" if done else ""))

    cache = Path(args.cache) if args.cache else None
    kais, drop, blank = {}, [], 0
    for kai in todo:
        got = collect_kai(fy, kai, drop, cache)
        if not got:
            blank += 1
            log(f"  第{kai}回: 今年度のPDFは無い")
            if blank >= KAI_BLANK_STOP and kai > latest:
                break
            continue
        blank = 0
        kais[kai] = got
        log(f"  第{kai}回 基準日 {got['asof']} / {len(got['horses'])}頭 /"
            f" 組 {len(got['blocks'])} / PDF {len(got['files'])}本")

    if not kais:
        log("1回も取れなかった")
        return 2

    newest = max(kais)
    head = kais[newest]
    index = [{"kai": k, "asof": v["asof"], "n": len(v["horses"])} for k, v in sorted(kais.items())]
    for k in (stored or {}).get("kais", []):        # 今回取りに行かなかった回も索引に残す
        if (stored or {}).get("fy") == fy and not any(i["kai"] == k["kai"] for i in index):
            index.append(k)
    index.sort(key=lambda x: x["kai"])
    value = {"built": f"{dt.datetime.now(JST):%Y-%m-%d}", "src": "official", "fy": fy,
             "kai": newest, "asof": head["asof"], "asof_by": head.get("asof_by") or {},
             "horses": head["horses"], "kais": index}

    out = Path(args.out) if args.out else (
        Path(os.environ.get("TEMP", ".")) / "claude" /
        "C--Users-kouki-OneDrive------------------3-" /
        "00251272-f978-4486-9290-c582ff9c03b7" / "scratchpad" / "class_monbetsu")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{META_KEY}.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{out / (META_KEY + '.json')} に書き出し(最新 第{newest}回 {len(head['horses'])}頭)")
    for kai, v in sorted(kais.items()):
        (out / f"kai{kai:02d}.json").write_text(json.dumps(
            {"kai": kai, "fy": v["fy"], "asof": v["asof"],
             "asof_by": v.get("asof_by") or {}, "src": "official",
             "files": v["files"], "horses": v["horses"],
             "blocks": [{k: b[k] for k in ("page", "sec", "col", "cls", "said")} |
                        {"n": len(b["rows"])} for b in v["blocks"]]},
            ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{out} に 回ごとの JSON {len(kais)}本")

    if args.verify:
        for kai in sorted(kais):
            verify(kais[kai], drop if kai == newest else [])
    elif drop:
        log(f"捨てた/気になった行 {len(drop)}件(--verify で全部出る)")
        for line in drop[:10]:
            log("  " + line)

    if not args.apply:
        log("ドライラン(--apply で nar_meta へ入る)")
        return 0
    # ⚠古い回で今の行を上書きしない。最新回のPDFがまだ出ていない日に流すと、差分の todo が
    # 古い回だけになり得る(同じ年度のときだけ見る。年度が変われば当然入れ替える)
    if (stored or {}).get("fy") == fy and newest < (stored or {}).get("kai", 0):
        log(f"入っているのは第{stored['kai']}回・今回取れたのは第{newest}回まで=古いので入れない")
        return 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = [{"key": META_KEY, "value": value, "updated_at": now}]
    if args.archive:
        old = sb_get_meta(base, key, HIST_KEY) or {}
        hist = old.get("kais", {}) if old.get("fy") == fy else {}   # 年度が変われば畳み直す
        for kai, v in kais.items():
            hist[str(kai)] = {"asof": v["asof"], "horses": v["horses"]}
        rows.append({"key": HIST_KEY, "updated_at": now,
                     "value": {"built": value["built"], "fy": fy, "src": "official",
                               "kais": hist}})
    status, msg = upsert(base, key, "nar_meta", "key", rows)
    if status not in (200, 201):
        log(f"投入失敗 {status} {msg}")
        return 1
    log(f"nar_meta/{META_KEY}{' と ' + HIST_KEY if args.archive else ''} 更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())

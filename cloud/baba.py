# -*- coding: utf-8 -*-
"""本体 cloud: 馬場差の全15場一括計算(DESIGN §48 K-1b)。

公式の走破時計(nar_runs.time_sec)を「場×距離×クラス帯の**直近1年(going 既定・[d-365,d))**中央値」と比べ、
**日×場の中央値**を馬場差(秒)として nar_meta `baba_diff` に入れる。マイナス=速い馬場。

  ⛔2026-09-28 T5(1〜5着)方式(going 版の d/g。RESULT_baba_top5_20260928.md「4 方式の比較」で
    奇数R/偶数R の日の値の相関 r が 勝ち時計だけ 0.884 → 0.908)
    各走 = 1〜5着それぞれの時計 − 同じ場×距離×帯×**着順**の基準の中央値(窓・3 段退避・8 本条件は今までと同じ)
    レース差 = その差の中央値(最低 MIN_HORSES=3 頭)/ 日×場 = レース差の中央値(MIN_RACES=4 R 未満は出さない)
    "n"/"ng" は**レース数**(頭数ではない)。同着は (レース, 着順) ごとに速い方の時計 1 本だけ使う。
    ⛔定義が変わったので切替の初回だけ --apply --rebuild-all(base は "going" のままなので自動では組み直さない)
    取得量: nar_runs を finish<=5 で読むので勝ち時計だけの約 5 倍= 窓 485 日ぶんで約 10 万行・
    REST 1000 行ページで約 100 ページ(1 ページ 0.5〜1 秒として 1〜2 分)。
    season/365/1095(旧版)は従来どおり勝ち時計(finish=1)だけで組む。

  出力 = {"built":"YYYY-MM-DD", "base":"going"|"season"|"365"|"1095",
          "days": {"2026-08-28": {"ooi": {"d": -0.8, "n": 9}, …}, …}}   # 直近90日+当日
          # まだ終わっていない日(=当日)は {"d":…,"n":…,"p":true}= 暫定。翌朝の便で確定して p が消える

  ⛔2026-10-26 距離の直し(going/classfirst のセルに "d1"/"g1" を足す・d/g は今のまま)
    d1/g1 = 1000m あたりの秒(小数 2 桁)= レース差を距離で割った日の中央値。
    補正タイムは 時計 − d1 × その走の距離 / 1000 × 場ごとの倍率(画面)。
    今までの d を距離によらず引くと 〜1200m で約 2 倍の引きすぎだった(docs/research-baba-distance/result.md)。
    ⛔南関 4 場は予想 AI の日の値(nar_meta nankan_d5= SI5 と同じ D5)にそろえる(overlay_ai・"s":"ai")。
    ⛔切替の初回だけ baba-rebuild 便(--rebuild-all)で確定済みの日にも d1/g1 を付ける。

  ⛔2026-11-04 開催日ページ「この日の時計」用に going/classfirst のセルへ "r" を足す= {"R番号": 1 着の基準の秒(小数 1 桁)}。
    基準= d(良馬場比)の計算が使う、同じ場×距離×クラス帯(→退避の段)×going=良×着順=1 の中央値そのもの(day_cell_going の med_of)。
    基準が無いレース(帯なし= classfirst では外す・標本不足)は入れない。セルの d が出たときだけ付ける。
    blend_proj/overlay_ai は d/d1 だけを書き換える= "r" は動かない(画面の「ふだん」は南関も同じ基準)。
    ⛔確定済みの日に "r" を付けるには baba-rebuild 便(--rebuild-all)が要る。
  ⛔2026-11-04 同じセルへ "rg"(組の差)と "pc"(前半)を足す(add_grp_front・d/g/d1/g1/r は変えない)。
    "rg" = {"R番号": 秒(小数 1 桁)}= 組の箱の差。級と組= cloud/class_parts.py(サイトの raceClassParts の写し・全場)・
      付帯に「選抜」「選定」= 級ごとに「選抜」の箱(KISHA_SEPARATE で記者選抜を分ける)。重賞・準重賞・級の混ざったレースは外す。
      箱= 組番号 1〜7 はそのまま・8-11・12-15・16-19・20+(11/4 全場へ広げたとき C3 の 1-3・4-7 の束ねをやめた)。
      表= その場の、その月の 1 日より前 3 年の 1 着の時計 t。res = t − 同じ級×距離の中央値。
      日の速さ(res − 箱の差 の日の平均)と箱の差(res − 日の速さ の平均)を 20 回交互に求め、
      級の全レース(選抜も含む)の重み付き平均を引く= "r"(級の帯の中央値)からのずれ。15 R 未満の箱・0.0 は入れない。
      表は場×月ごとに 1 回だけ組む(group_table)。
    "pc" = {"R番号": 秒(小数 2 桁)}= 前半。最初のコーナーで 1 番手(1 頭だけ)の馬の (走破 − 上がり3F) ÷ (距離 − 600) × 200
      − 上がり3F/3 から、同じ場×距離の その日より前 1 年の中央値(8 本以上)を引く。先頭が分からない・上がりなし・≤800m は入れない。
      ⛔鍵を "p" にしないのは "p":true(暫定)と重なるため(FRONT_KEY)。

  ⛔as-of(§17 監査 2026-09-22 で「as-of でない」と判定された点の直し)
    日 d の標準は **race_date < d**= その日も、その日より後も標準に入れない。
    さらに **一度確定した日の値は二度と上書きしない**。組み直すのは
      (1) blob にまだ無い日  (2) 前回 "p":true(暫定)で置いた日  (3) 当日
    だけ。--rebuild-all のときだけ全部作り直す(定義を変えたときの作り直し用)。
    昔は標準の窓に上限が無く毎朝 90 日をまるごと組み直していたので、過去の日の値があとから動いていた。

  ⛔当日の値は「その日の**終わったレース**(時計のある走)だけ」から出した暫定値。
    "p":true が付き、画面は「途中まで」と断って出す(js/ui.js babaWord/babaLabel)。

  標準の窓は --baseline で切替。**既定は projhalf(2026-11-04)**。going(9/28)→classfirst(10/25)→projhalf(11/2 本番・11/4 既定)。
    going  : 2 本の物差しを1セルに入れる。窓は [d-365, d)(前日までの直近1年・d 未満。2026-09-28 ユーザー決定で 1095→365)
             d = 良馬場比: 同じ場×距離×クラス帯×着順の going=良 の時計(1〜5着)の中央値との差
             g = 同じ馬場状態比: 同じ場×距離×クラス帯×着順×その走の going の中央値との差
             セル = {"d","g","n"(d に使ったレース数),"ng"(g に使ったレース数),"k"(その日の主な going),"p"?}
             ⛔標本 8 本未満のセルはそのレースを除外(退避しない)。d/g はそれぞれ MIN_RACES 本以上のときだけ載せる
             ⛔2026-09-28 までの "d" は「馬場状態を混ぜた標準」との差。going 版の "d" は良馬場比に意味が変わる
    season : 同じ場の「同じ暦の前後45日」×過去3年(すべて d 未満)。季節の波を標準に入れるので
             「例年のこの時期と比べて」の値になる(既定)
    365    : [d-365, d)  前日までの直近1年。場の常時オフセットの大半が消えるが季節の波は残る
    1095   : 旧§104(3年ぶん一括)

  ⛔season の退避(標本が薄いセル): 改修直後・新しい距離・開催の並びなどで season の窓から
    MIN_SEASON(8)本ぶんの偏差が取れないセルは、その1セルだけ **365 の窓で組み直す**。
    退避したセルには **"b":"365"** を付ける(blob の印。トップの "base" は "season" のまま)。
  - ⚠その日の対象レースが4本未満の場は出さない(小サンプルから言わない)
  - ⚠帯広ばは対象外(#111: ばんえいは馬場の型が違う。水分率が公式にある)
  - クラス帯は race_name の粗い抽出(Ａ/Ｂ/Ｃ+数字・2歳/3歳・重賞/準重賞/オープン=OP・複数級=AB 等)。抽出できない走は場×距離の全体中央値に落とす
    (帯を捏造しない)。帯の基準は標本8本以上のときだけ使う

  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar            # ドライラン(集計と検証だけ)
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --verify   # +公式の馬場状態(going)との相関
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --apply    # nar_meta へ upsert(確定済みの日は据え置き)
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --baseline 365      # 1年版で試す
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --apply --rebuild-all  # 全部作り直す
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ(#8): 全取得はページングで回す。⛔updated_at を必ず送る(#155)。
"""
import argparse
import bisect
import datetime as dt
from zoneinfo import ZoneInfo
import io
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from class_parts import race_class_parts  # noqa: E402  ⛔サイトの js/class-parts.js と同じ読み方

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = "nar-jobs/1.0"
META_KEY = "baba_diff"
BANEI = "帯広ば"
TRACK2PREFIX = {"門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa",
                "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
                "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji",
                "高知": "kochi", "佐賀": "saga"}
MIN_BAND = 8            # 帯の基準に要る標本数
MIN_RACES = 4           # 日×場の馬場差を出す最少レース数
MIN_SEASON = 8          # season 版: これ未満の標本しか取れないセルは 365 版に退避("b":"365")
WINDOW_DAYS = 90        # blob に載せる日数(⛔§104 でも変えない= 出す日数と標準の窓は別物)
# 標準(場×距離×クラス帯の中央値)を作る窓。⛔2026-09-05 ユーザーFB「1年では弱い」で 365→1095 日にしたが、
# §17 監査(2026-09-22)で「3年フラットだと場の常時オフセットと季節の波をその日の馬場として出してしまう」と
# 分かったので、既定を **前日までの直近365日** に戻した(1095 は STD_DAYS_LEGACY として残す)。
# ⛔標準に**馬場状態を入れない**= 馬場差は「その日の馬場でどれだけ速かったか」を測るものなので、
#   良/不良で標準を分けると測りたいものが消える(不良の日が不良の標準と比べられて 0 になる)。
STD_DAYS = 365
STD_DAYS_LEGACY = 1095   # 旧版(§104)。--baseline 1095 で使える
SEASON_YEARS = 3         # season 版: 何年ぶん遡るか
SEASON_PAD = 45          # season 版: 同じ暦日の前後 何日
BASELINES = ("365", "1095", "season", "going", "classfirst", "projhalf")
# going 版の退避の段(段= (層, 窓の日数))。層 b= 細かい帯・c= 字だけの帯・d= 場×距離
GOING_STAGES = (("b", STD_DAYS), ("c", STD_DAYS), ("d", STD_DAYS))
# classfirst(2026-10-25 研究用・既定ではない)= クラスを先に守る 5 段。帯の窓だけ 3 年まで延ばす
CLASSFIRST_STAGES = (("b", STD_DAYS), ("b", STD_DAYS_LEGACY), ("c", STD_DAYS), ("c", STD_DAYS_LEGACY),
                     ("d", STD_DAYS))
GOING_LIKE = ("going", "classfirst")
# 帯が読めない走(band_of が None)の扱い: "dist"= 場×距離の基準へ落とす(going の今まで)/"drop"= その日の値から外す
NONE_BAND_DEFAULT = {"going": "dist", "classfirst": "drop"}
# ⛔2026-10-25 ユーザー決定で既定を classfirst へ(本番データの研究便 docs/research-baba-classfirst: クラスの片寄り 0.93→0.39 秒・
#   オープン −2.17→−0.85・次走の当たり d 同等/g +0.20 点)。baba_hist.py もこれを使う
# ⛔2026-11-02 本番を projhalf(classfirst の d1 と出走馬の力の見積もりの半々)へ・11/4 既定もそろえた(引数を書き忘れても古い値を出さない)
DEFAULT_BASELINE = "projhalf"
GOING_BASE = "良"          # going 版の d の物差し
TOP_N = 5                # going 版(T5)で使う着順の上限(1〜5着)
MIN_HORSES = 3           # going 版(T5): レース差を出す最少頭数
# ⛔2026-10-26 距離の直し(ユーザー決定)。d/g(その日の秒)は今のまま残し(札・言葉・閾値はこれ)、
#   補正タイム用に d1/g1(1000m あたりの秒・小数 2 桁)を足す。画面は 時計 − d1 × その走の距離/1000 × 場ごとの倍率。
#   研究(全 14 場・2025-09〜2026-08・docs/research-baba-distance): 今の画面(d × 倍率)に近い「d × 0.75」に対し、
#   距離の直しの上積みは全体 +0.13 点・〜1200m +0.45 点(監査で確かめた)。ふだんへ寄せる案 (c) は上積み 0 だったので入れない
# ⛔南関 4 場は予想 AI の日の値にそろえる(2026-10-26 ユーザー決定)= 便 nar-ai-v3 の si5_store が書く nar_meta nankan_d5
#   ({"days": {日: {prefix: D5}}}・1000m あたり・走破指数 SI5 の計算に使う値そのもの)
AI_META_KEY = "nankan_d5"
AI_TRACKS = ("浦和", "船橋", "大井", "川崎")
# ⛔2026-11-01 試し(既定ではない・wip/baba-projection-20261101)= --baseline projhalf
#   classfirst の値と「出走馬の力の見積もりからの日の値(②・1000m あたり)」の半々。南関 4 場は当てない(AI で上書き)。
#     d1/g1 = (classfirst + ②) / 2(小数 2 桁)。d/g = (classfirst + ② × その日のその場のレースの平均距離 / 1000) / 2(小数 1 桁)
#     = d と d1 の関係(d ≒ d1 × 平均距離 / 1000)は overlay_ai と同じ考え方で保つ。②が出ない日(4 R 未満)は classfirst のまま。
#   ②: 各走 x =(時計 − 場×芝ダ×距離の 1〜5着の中央値(月初めより前の 365 日・8 本以上))÷ 距離 × 1000(±8 で切る)。
#       馬(馬名+生年月日)の力= 前日までの近 5 走のうち直近 365 日(3 走未満なら 730 日)の x − その日の②の値 の重み付き平均
#       (新しい順に 1, 0.8, 0.64, 0.51, 0.41・3 走以上)。レースの値= 力の分かった馬 3 頭以上の x − 力 の中央値、日の値= 4 R 以上の中央値。
#       古い日から順に積み上げる。積み上げの始め= 出したい日の月初めの 730 日前(月ごとに積み直す= 読む量を 3 年強に抑える)。
#   研究: nar-site の RESULT_baba_projection_window_20261101.md
PROJ_BASE = "projhalf"
PROJ_ANCHOR = 730
PROJ_WINS = (365, 730)
PROJ_WT = (1.0, 0.8, 0.64, 0.51, 0.41)
PROJ_CLIP = 8.0
PROJ_PAR_DAYS = 365
PROJ_PAR_MIN = 8
PROJ_MIN_H = 3

Z = str.maketrans("ＡＢＣ０１２３４５６７８９", "ABC0123456789")


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None):
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(r, timeout=90) as x:
        return x.status, x.read().decode("utf-8")


def rows_all(base, key, path, tries=3, wait=5):
    """全ページを引く。⛔ページごとに最大 tries 回(間 wait 秒・2 回目以降は倍々)引き直す(監査 2d・9/5 に baba_trend で 500 実測)"""
    out, off = [], 0
    while True:
        for k in range(tries):
            try:
                _, body = req(base, key, f"{path}&limit=1000&offset={off}")
                break
            except Exception as e:  # noqa: BLE001  5xx・時間切れ・接続切れ
                if k == tries - 1:
                    raise
                log(f"  取得の再試行 {k + 1}/{tries - 1}(offset={off}): {e}")
                time.sleep(wait * (2 ** k))
        c = json.loads(body)
        out.extend(c)
        if len(c) < 1000:
            return out
        off += 1000


# §104 2026-09-05(Fable・要判断①=a): 名古屋・笠松の公式クラスは Ａ級/Ｂ級/Ｃ級の3つだけで、レース名の数字は
# 「組」(Ｃ１５組=Ｃ級15組)。数字まで拾うと帯が 17 行に割れ「Ｃ１５」が Ｃ1 に化けるので、東海2場は字だけに丸める
LETTER_ONLY_TRACKS = {"名古屋", "笠松"}


OP_KINDS = {"重賞", "準重賞"}
KANJI_NUM = {"一": "1", "二": "2", "三": "3"}


def band_of(race_name, track=None, race_kind=None):
    """クラス帯の粗い抽出。取れなければ None(=場×距離の全体基準に落ちる)。track が東海2場なら字だけ。
    2026-09-28 帯の直し(ユーザー了承):
      ① race_kind が 重賞/準重賞、または名前に「オープン」→ "OP"(2歳・3歳・A 級の標準に混ぜない)
      ② 「3歳以上・3上・4歳以上」は 3y にしない(中の A/B/C 級で分け、級が無ければ None)
      ③ 級の漢数字 一二三 は 1〜3 に揃える(A一=A1)
      ④ 「ＡＢ混合」「Ｂ・Ｃ級」のような複数級は専用帯("AB"・"BC")"""
    t = str(race_name or "").translate(Z)
    if str(race_kind or "") in OP_KINDS or "オープン" in t:
        # ⑤(9/28)若馬の OP は "OPy"(2歳・3歳。ただし 3歳以上・3上 は古馬)= 古馬 OP と標準を混ぜない
        if re.search(r"[23]歳", t) and not re.search(r"[34]歳以上|[34]歳上|[34]上", t):
            return "OPy"
        return "OP"
    mm = re.search(r"(?<![A-Za-zＡ-Ｚａ-ｚ])([ABC])・?([ABC])(?=混合|級)", t)
    if mm and mm.group(1) != mm.group(2):
        return "".join(sorted(mm.group(1) + mm.group(2)))
    # ⛔前後に英字(全角含む=Z はＡＢＣしか半角化しない)が続く A/B/C は級ではない
    #   (「ＪＲＡ認定」「ＪＢＣ」「ＢＡＯＯ」等の英字を拾って2歳戦がA級に混ざる)。
    #   数字が続けば級(「Ａ１Ａ２」は従来どおり A1)・続かなければ直後も英字でないこと
    m = re.search(r"(?<![A-Za-zＡ-Ｚａ-ｚ])([ABC])(?:\s?([0-9一二三])|(?![A-Za-zＡ-Ｚａ-ｚ]))", t)
    if m:
        num = m.group(2) or ""
        return m.group(1) if track in LETTER_ONLY_TRACKS else m.group(1) + KANJI_NUM.get(num, num)
    if re.search(r"2歳|２歳", t):
        return "2y"
    if re.search(r"[34]歳以上|[34]歳上|[34]上", t):
        return None
    if re.search(r"3歳|３歳", t):
        return "3y"
    return None


# ─── as-of の標準づくり ────────────────────────────────────────────────
# ⛔ここから下は「日 d の標準は d より前のレースだけ」を守るための道具。手元の写しでも同じ関数を呼べるよう
#   DB に触らない純関数にしてある(検証= tools/verify_baba_asof.py)。

def coarse_key(band):
    """going 版の退避 2 段目= 字だけの粗い帯(A1/A/…→ "*A")。OP・OPy・2y・3y・AB/BC は None(粗い段なし)"""
    return "*" + band[0] if band and re.fullmatch(r"[ABC][0-9]?", band) else None


def fetch_days(baseline):
    """標準を作るのに何日ぶんの時計を読めばよいか(表示する90日ぶんの一番古い日から見た遡り)"""
    if baseline == "season":
        return 365 * SEASON_YEARS + SEASON_PAD + 30
    if baseline == "classfirst":                      # 帯の 3 年の段のぶん(going 版の読み方は変えない)
        return max(sp for _, sp in CLASSFIRST_STAGES) + 30
    if baseline == PROJ_BASE:                         # 積み上げの始め(月初め − 730)+ その基準の 365 日
        return max(max(sp for _, sp in CLASSFIRST_STAGES) + 30, PROJ_ANCHOR + PROJ_PAR_DAYS + 31)
    return (STD_DAYS_LEGACY if baseline == "1095" else STD_DAYS) + 30


def baseline_ranges(d, baseline):
    """日 d の標準に使う期間を [lo, hi) の文字列で返す。⛔hi は必ず d 以下(その日と未来を入れない)"""
    if baseline == "season":
        out = []
        for y in range(1, SEASON_YEARS + 1):
            try:
                anniv = d.replace(year=d.year - y)
            except ValueError:          # 2/29
                anniv = d.replace(year=d.year - y, month=2, day=28)
            lo = anniv - dt.timedelta(days=SEASON_PAD)
            hi = anniv + dt.timedelta(days=SEASON_PAD + 1)
            if hi > d:
                hi = d
            if lo < hi:
                out.append((lo.isoformat(), hi.isoformat()))
        return out
    span = STD_DAYS_LEGACY if baseline == "1095" else STD_DAYS   # going も 365(9/28 決定)
    return [((d - dt.timedelta(days=span)).isoformat(), d.isoformat())]


def _vals_in(seq, ranges):
    """seq= (日付文字列, 時計) を日付昇順に並べた列。ranges の [lo,hi) に入る時計だけ集める"""
    out = []
    for lo, hi in ranges:
        i = bisect.bisect_left(seq, (lo,))
        j = bisect.bisect_left(seq, (hi,))
        out.extend(v for _, v in seq[i:j])
    return out


def index_samples(samples):
    """samples= (track, date, dist, band, time, going) → 帯つき/場×距離ごとの日付昇順の列"""
    by_band, by_dist = {}, {}
    for track, date, dist, band, t, _g in sorted(samples, key=lambda s: s[1]):
        by_dist.setdefault((track, dist), []).append((date, t))
        if band:
            by_band.setdefault((track, dist, band), []).append((date, t))
    return by_band, by_dist


def day_cell(day_rows, by_band, by_dist, d, baseline):
    """1つの日×場ぶん。day_rows= [(dist, band, time)]。戻り= (馬場差, 本数, 偏差の列) / 本数不足なら None"""
    ranges = baseline_ranges(d, baseline)
    cache, devs = {}, []
    for dist, band, t in day_rows:
        med = None
        if band:
            k = ("b", dist, band)
            med = cache.get(k, "?")
            if med == "?":
                v = _vals_in(by_band.get(k[1:], []), ranges)
                med = statistics.median(v) if len(v) >= MIN_BAND else None
                cache[k] = med
        if med is None:
            k2 = ("d", dist)
            med = cache.get(k2, "?")
            if med == "?":
                v = _vals_in(by_dist.get((dist,), []), ranges)
                med = statistics.median(v) if len(v) >= MIN_BAND else None
                cache[k2] = med
        if med is None:
            continue
        devs.append(t - med)
    if len(devs) < MIN_RACES:
        return None
    return round(statistics.median(devs), 1), len(devs), devs


def day_cell_going(day_rows, by_band_g, by_dist_g, d, stages=None, none_band="dist", info=None):
    """going 版(T5)の1つの日×場。day_rows= [(dist, band, time, going, race_no, finish)]。
    by_band_g[(dist, band, going, finish)] / by_dist_g[(dist, going, finish)] = 日付昇順の (date, time)。
    退避は 3 段(9/28)= 細かい帯(C1)→ 粗い帯(字だけ・by_band_g[(dist, "*C", going, finish)])→ 場×距離。
    going を良に固定(d)/その走の going(g)にして、各段とも同じ going・同じ着順で引く。
    レース差= そのレースの 1〜5着の差の中央値(MIN_HORSES 頭以上)。日×場= レース差の中央値。
    戻り= {"d","n","g","ng","devs"} のうち出せたものだけ(MIN_RACES R 未満は載せない。n/ng はレース数)
    stages   : 退避の段 ((層, 窓の日数), …)。None= GOING_STAGES(今の本番)
    none_band: 帯なしの走を "dist"= 場×距離へ落とす(今の本番)/"drop"= 外す
    info     : dict を渡すと研究用の内訳を入れる(本番は渡さない)=
               reach_d/reach_g= 段ごとの時計の本数(最後の要素= 基準なし)・drop= 外した時計の本数・
               race_d/race_g= {R: レース差}・stage_d/stage_g= {R: [使った段の番号…]}"""
    stages = stages or GOING_STAGES
    rng_of = {sp: [((d - dt.timedelta(days=sp)).isoformat(), d.isoformat())] for _, sp in stages}
    cache = {}

    def med_of(dist, band, going, fin):
        cb = coarse_key(band)
        for i, (lv, sp) in enumerate(stages):
            if lv == "b":
                k, src, kk = ("b", dist, band, going, fin, sp), by_band_g, (dist, band, going, fin)
            elif lv == "c":
                k, src, kk = ("c", dist, cb, going, fin, sp), by_band_g, (dist, cb, going, fin)
            else:
                k, src, kk = ("d", dist, going, fin, sp), by_dist_g, (dist, going, fin)
            if lv != "d" and not k[2]:
                continue
            m = cache.get(k, "?")
            if m == "?":
                v = _vals_in(src.get(kk, []), rng_of[sp])
                m = statistics.median(v) if len(v) >= MIN_BAND else None
                cache[k] = m
            if m is not None:
                return m, i
        return None, -1

    if info is not None:
        for nm in ("d", "g"):
            info["reach_" + nm] = [0] * (len(stages) + 1)
            info["race_" + nm], info["stage_" + nm] = {}, {}
        info["drop"] = 0
    per_d, per_g, st_d, st_g, dist_r, par1 = {}, {}, {}, {}, {}, {}
    for dist, band, t, going, rno, fin in day_rows:
        if not fin or fin > TOP_N:
            continue
        dist_r[rno] = dist
        if band is None and none_band == "drop":
            if info is not None:
                info["drop"] += 1
            continue
        m, i = med_of(dist, band, GOING_BASE, fin)
        if info is not None:
            info["reach_d"][i] += 1
        if m is not None and fin == 1 and rno is not None:
            par1[str(rno)] = round(m, 1)       # 11/4 開催日ページ「この日の時計」のふだん= d に使った 1 着の基準そのもの
        if m is not None:
            per_d.setdefault(rno, []).append(t - m)
            st_d.setdefault(rno, []).append(i)
        if going:
            m, i = med_of(dist, band, going, fin)
            if info is not None:
                info["reach_g"][i] += 1
            if m is not None:
                per_g.setdefault(rno, []).append(t - m)
                st_g.setdefault(rno, []).append(i)
    if info is not None:
        for nm, per, st in (("d", per_d, st_d), ("g", per_g, st_g)):
            for r_, v in per.items():
                if len(v) >= MIN_HORSES:
                    info["race_" + nm][r_] = statistics.median(v)
                    info["stage_" + nm][r_] = st[r_]
    dr = [(r_, statistics.median(v)) for r_, v in sorted(per_d.items(), key=lambda kv: str(kv[0]))
          if len(v) >= MIN_HORSES]
    gr = [(r_, statistics.median(v)) for r_, v in sorted(per_g.items(), key=lambda kv: str(kv[0]))
          if len(v) >= MIN_HORSES]
    dv, gv = [v for _, v in dr], [v for _, v in gr]
    out = {}
    # d1/g1(2026-10-26 距離の直し)= レース差を 1000m あたりに直した中央値(小数 2 桁)
    if len(dv) >= MIN_RACES:
        out["d"], out["n"], out["devs"] = round(statistics.median(dv), 1), len(dv), dv
        out["d1"] = round(statistics.median([v * 1000.0 / dist_r[r_] for r_, v in dr]), 2)
        if par1:
            out["r"] = dict(sorted(par1.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999))
    if len(gv) >= MIN_RACES:
        out["g"], out["ng"] = round(statistics.median(gv), 1), len(gv)
        out["g1"] = round(statistics.median([v * 1000.0 / dist_r[r_] for r_, v in gr]), 2)
    return out


# ─── 11/4 開催日ページ「この日の時計」の rg(組の差)と前半(FRONT_KEY)────────────────────
# ⛔前半の鍵は "p" にしない= "p":true は既に「暫定(当日)」の印。FRONT_KEY を変えれば鍵名だけ変わる
FRONT_KEY = "pc"
GRP_KEYS = ("rg", FRONT_KEY)
GRP_YEARS_DAYS = 1095        # 組の表= その月の 1 日より前 3 年
GRP_ITERS = 20               # 「日の速さ」と「箱の差」を交互に求める回数(⛔4 回は未収束= 高知 C3 20+ が 0.57→0.67・10 回で収束・11/4 研究便)
GRP_MIN = 15                 # 箱のレース数がこれ未満は出さない
KISHA_SEPARATE = False       # 「記者選抜」を選抜と別の箱にするか(⛔高知の本物で差 0.2 秒以上なら True= 未測定)
FRONT_DAYS = 365             # 前半の基準= 同じ場×距離の その日より前 1 年の中央値
FRONT_MIN = MIN_BAND
_CLS_OK = re.compile(r"^([A-D][0-9]?|[2-4]歳)$")            # 字 1 つ(+1 桁)か 馬齢= 級の箱を作るもの
_MIX_RE = re.compile(r"[A-DＡ-Ｄ][0-9０-９]")                # 付帯に別の級(C3-2C4-1・A2B1 選定馬)= 混ざったレース


def group_box(race_name, race_kind=None, track=None):
    """レース名 → (級, 箱) / None。級と組の読み方= cloud/class_parts.py(サイトの js/class-parts.js と同じ・全場)。
    箱= 組番号 1〜7 はそのまま・8-11・12-15・16-19・20+(組がいくつ並ぶ「八 九」は先頭)。
    2歳・3歳限定は級の前に付ける(3歳C2)。付帯に「選抜」「選定」= 級ごとに "選抜"(KISHA_SEPARATE なら「記者選抜」は "記者選抜")。
    ⛔外す= 重賞・準重賞・級の混ざったレース(付帯に別の級 C4-1・B1 など/級字 2 つ AB)・級が語(新馬・未勝利)・組の無いレース"""
    if str(race_kind or "") in OP_KINDS:
        return None
    pt = race_class_parts(race_name, race_kind, track)
    if not pt or not pt["cls"] or not _CLS_OK.match(pt["cls"]):
        return None
    cls, ex = pt["cls"], pt["extra"] or ""
    if pt["age"] in ("2歳", "3歳") and not cls.endswith("歳"):
        cls = pt["age"] + cls                                  # 3歳C2五組(岩手)= 古馬の C2 と分ける
    if _MIX_RE.search(ex):
        return None
    if "選抜" in ex or "選定" in ex:
        return cls, ("記者選抜" if KISHA_SEPARATE and "記者選抜" in ex else "選抜")
    if not pt["grp"]:
        return None
    m = re.match(r"([0-9]+)", pt["grp"])
    n = int(m.group(1)) if m else 0
    if n <= 0:
        return None
    if n <= 7:
        return cls, str(n)
    for hi, lab in ((11, "8-11"), (15, "12-15"), (19, "16-19")):
        if n <= hi:
            return cls, lab
    return cls, "20+"


def group_table(rows, lo, hi):
    """1 場ぶんの組の差の表。rows= [(date, dist, 級, 箱, 1 着の時計)]・期間 [lo, hi)。
    res = 時計 − 同じ級×距離の中央値 → 日の速さ(res − 箱の差 の日ごとの平均)と箱の差(res − 日の速さ の平均)を
    GRP_ITERS 回交互に → 級ごとに「その級の全レースの重み付き平均」を引く。戻り= {(級, 箱): (差, レース数)}"""
    xs = [r for r in rows if lo <= r[0] < hi]
    if not xs:
        return {}
    by_cd = {}
    for date, dist, cls, box, t in xs:
        by_cd.setdefault((cls, dist), []).append(t)
    med = {k: statistics.median(v) for k, v in by_cd.items()}
    res = [(date, (cls, box), t - med[(cls, dist)]) for date, dist, cls, box, t in xs]
    box_d = {b: 0.0 for _, b, _ in res}
    for _ in range(GRP_ITERS):
        acc = {}
        for date, b, v in res:
            acc.setdefault(date, []).append(v - box_d[b])
        day_d = {k: sum(v) / len(v) for k, v in acc.items()}
        acc = {}
        for date, b, v in res:
            acc.setdefault(b, []).append(v - day_d[date])
        box_d = {k: sum(v) / len(v) for k, v in acc.items()}
    cnt = {}
    for _, b, _ in res:
        cnt[b] = cnt.get(b, 0) + 1
    ctr = {}
    for b, v in box_d.items():
        s_ = ctr.setdefault(b[0], [0.0, 0])
        s_[0] += v * cnt[b]
        s_[1] += cnt[b]
    return {b: (v - ctr[b[0]][0] / ctr[b[0]][1], cnt[b]) for b, v in box_d.items()}


def front_value(dist, t, l3f):
    """前半= (走破 − 上がり3F) を (距離 − 600) で割って 200m あたり − 上がり3F/3。距離 ≤ 800m・欠けは None"""
    try:
        dist, t, l3f = int(dist), float(t), float(l3f)
    except (TypeError, ValueError):
        return None
    if dist <= 800 or t <= 0 or l3f <= 0 or t <= l3f:
        return None
    return (t - l3f) / (dist - 600) * 200.0 - l3f / 3.0


def _first_corner(corners):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from pipeline.facts import first_corner      # ⛔通過順の読み方は pipeline/facts.py の 1 か所だけ
    return first_corner(corners)


def race_rows_of(best, meta, runs):
    """組の差・前半に使うレースごとの行。best= {(場, 日, R, 着順): REST の行}(同着は速い方)・
    meta= {(場, 日, R): nar_races の行(race_name・race_kind・distance_m・corners)}・
    runs= last3f 付きの nar_runs の行(全着順。先頭の馬を探すだけ)。
    戻り= [(場, 日, R, 距離, 級, 箱 or None, 1 着の時計 or None, 前半 or None)]"""
    by_no = {}
    for w in runs or []:
        if w.get("runner_number") is not None:
            by_no[(w["track"], w["race_date"], w["race_no"], int(w["runner_number"]))] = w
    out = []
    for kk, m in meta.items():
        track, date, rno = kk
        if track == BANEI or track not in TRACK2PREFIX or not m.get("distance_m"):
            continue
        dist = int(m["distance_m"])
        gb = group_box(m.get("race_name"), m.get("race_kind"), track)
        w1 = best.get((track, date, rno, 1))
        t1 = float(w1["time_sec"]) if w1 and w1.get("time_sec") is not None else None
        fv = None
        fc = _first_corner(m.get("corners")) if m.get("corners") else None
        lead = [n for n, r in (fc or {}).items() if r == 1]
        if len(lead) == 1:
            w = by_no.get((track, date, rno, int(lead[0])))
            if w and w.get("time_sec") is not None and w.get("last3f") is not None:
                fv = front_value(dist, w["time_sec"], w["last3f"])
        if gb is None and fv is None:
            continue
        out.append((track, date, rno, dist, gb[0] if gb else None, gb[1] if gb else None, t1, fv))
    return out


def add_grp_front(days, frozen, rrows, rebuild_all=False):
    """組み直したセル(d のあるもの)に "rg"={R: 秒(小数 1 桁)}・FRONT_KEY={R: 秒(小数 2 桁)}を足す。
    据え置きのセル(frozen と同じ物)は触らない。d・g・d1・g1・r は変えない。戻り= 足した場日の数"""
    frozen = frozen or {}
    by_tr = {}
    for row in rrows or []:
        by_tr.setdefault(row[0], []).append(row)
    grp_rows, fr_rows, day_rows = {}, {}, {}
    for track, xs in by_tr.items():
        grp_rows[track] = [(d, dist, c, b, t) for _tr, d, _r, dist, c, b, t, _f in xs if b and t is not None]
        fr = {}
        for _tr, d, _r, dist, _c, _b, _t, f in sorted(xs, key=lambda r: r[1]):
            if f is not None:
                fr.setdefault(dist, []).append((d, f))
        fr_rows[track] = fr
        for row in xs:
            day_rows.setdefault((track, row[1]), []).append(row)
    tables, n = {}, 0
    for date, cells in days.items():
        for track, pf in TRACK2PREFIX.items():
            c = cells.get(pf)
            if not c or "d" not in c:
                continue
            if not rebuild_all and c is (frozen.get(date) or {}).get(pf):
                continue
            rows = day_rows.get((track, date))
            if not rows:
                continue
            d0 = dt.date.fromisoformat(date)
            ms = d0.replace(day=1)
            tk = (track, ms)
            if tk not in tables:
                tables[tk] = group_table(grp_rows.get(track, []),
                                         (ms - dt.timedelta(days=GRP_YEARS_DAYS)).isoformat(), ms.isoformat())
            tb = tables[tk]
            rg, fv = {}, {}
            lo1 = (d0 - dt.timedelta(days=FRONT_DAYS)).isoformat()
            for _tr, _d, rno, dist, cls, box, _t, f in rows:
                if rno is None:
                    continue
                if box:
                    v = tb.get((cls, box))
                    if v and v[1] >= GRP_MIN and round(v[0], 1) != 0:
                        rg[str(rno)] = round(v[0], 1)
                if f is not None:
                    seq = fr_rows.get(track, {}).get(dist, [])
                    vals = _vals_in(seq, [(lo1, date)])
                    if len(vals) >= FRONT_MIN:
                        fv[str(rno)] = round(f - statistics.median(vals), 2)
            srt = lambda dd: dict(sorted(dd.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999))  # noqa: E731
            if rg:
                c["rg"] = srt(rg)
            if fv:
                c[FRONT_KEY] = srt(fv)
            if rg or fv:
                n += 1
    return n


def _main_going(rows):
    gs = [r[3] for r in rows if r[3]]
    return statistics.mode(gs) if gs else None


def _today_jst():
    """⛔GitHub の runner は UTC。日の境目は日本時間で決める(JST 00:00〜08:59 に UTC 日付を使うと前日が「途中まで」のまま残る)"""
    return dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _norm(samples):
    """samples を (track, date, dist, band, time, going, race_no, finish) に揃える。
    6 要素(旧形= 勝ち時計だけ)は race_no=None・finish=1 とみなす"""
    return [tuple(s_[:8]) if len(s_) >= 8 else tuple(s_[:6]) + (None, 1) for s_ in samples]


def build_days(samples, targets, baseline, today=None, frozen=None, rebuild_all=False, none_band=None,
               info_of=None):
    """as-of の馬場差を組む。
      samples  : [(track, date, dist, band, time, going, race_no, finish)]  1〜5着の時計(標準の窓ぶん全部)
                 going 版は 1〜5着(T5)で組む。旧版(season/365/1095)は finish=1 だけ。6 要素なら勝ち時計とみなす
      targets  : 出したい日(date 文字列)の集合
      frozen   : 前回の blob の days(確定済みは据え置く)
      戻り     : ({日: {場prefix: {d,n[,p]}}}, 組み直した場日の数, {(日,場): 偏差列})
    ⛔p=true(暫定)= その日がまだ終わっていない(=当日)。終わったレースだけから出した途中の値。
      none_band: going/classfirst の帯なしの走の扱い("dist"/"drop")。None= NONE_BAND_DEFAULT(going は今まで通り "dist")
      info_of  : dict を渡すと {(日, 場): day_cell_going の内訳} を入れる(研究用)
    """
    today = today or _today_jst()
    frozen = frozen or {}
    samples = _norm(samples)
    if baseline not in GOING_LIKE:
        samples = [s_ for s_ in samples if s_[7] == 1]
    stages = CLASSFIRST_STAGES if baseline == "classfirst" else GOING_STAGES
    none_band = none_band or NONE_BAND_DEFAULT.get(baseline, "dist")
    by_band_all, by_dist_all = {}, {}
    for track, date, dist, band, t, _g, _rno, _fin in sorted(samples, key=lambda s: s[1]):
        by_dist_all.setdefault(track, {}).setdefault((dist,), []).append((date, t))
        if band:
            by_band_all.setdefault(track, {}).setdefault((dist, band), []).append((date, t))
    per_day = {}
    for track, date, dist, band, t, _g, rno, fin in samples:
        if date in targets:
            per_day.setdefault((date, track), []).append((dist, band, t, _g, rno, fin))
    if baseline in GOING_LIKE:
        by_band_gg, by_dist_gg = {}, {}
        for track, date, dist, band, t, _g, _rno, fin in sorted(samples, key=lambda s: s[1]):
            if not _g or not fin or fin > TOP_N:
                continue
            by_dist_gg.setdefault(track, {}).setdefault((dist, _g, fin), []).append((date, t))
            if band:
                by_band_gg.setdefault(track, {}).setdefault((dist, band, _g, fin), []).append((date, t))
                if coarse_key(band):        # 退避 2 段目(字だけの粗い帯)
                    by_band_gg[track].setdefault((dist, coarse_key(band), _g, fin), []).append((date, t))

    out, rebuilt, devs_of = {}, 0, {}
    tstr = today.isoformat()
    for date in sorted(targets):
        for track in TRACK2PREFIX:
            prefix = TRACK2PREFIX[track]
            old = (frozen.get(date) or {}).get(prefix)
            # ⛔確定済み(p が無い・過去の日)は触らない= 過去の馬場差はあとから動かない
            if old and not rebuild_all and not old.get("p") and date < tstr:
                out.setdefault(date, {})[prefix] = old
                continue
            rows = per_day.get((date, track))
            if not rows:
                if old and not rebuild_all:
                    out.setdefault(date, {})[prefix] = old
                continue
            dd = dt.date.fromisoformat(date)
            if baseline in GOING_LIKE:
                inf = {} if info_of is not None else None
                c = day_cell_going(rows, by_band_gg.get(track, {}), by_dist_gg.get(track, {}), dd,
                                   stages=stages, none_band=none_band, info=inf)
                if inf is not None:
                    info_of[(date, track)] = inf
                if "d" not in c and "g" not in c:
                    continue
                cell = {k: c[k] for k in ("d", "g", "n", "ng", "d1", "g1", "r") if k in c}
                k = _main_going(rows)
                if k:
                    cell["k"] = k
                if date >= tstr:
                    cell["p"] = True
                out.setdefault(date, {})[prefix] = cell
                if "devs" in c:
                    devs_of[(date, track)] = c["devs"]
                rebuilt += 1
                continue
            rows = [r_[:3] for r_ in rows]
            r = day_cell(rows, by_band_all.get(track, {}), by_dist_all.get(track, {}),
                         dd, baseline)
            fallback = False
            # ⛔season で標本が薄いセル(改修直後など)は 365 の窓に退避して "b":"365" を付ける
            if baseline == "season" and (not r or r[1] < MIN_SEASON):
                r2 = day_cell(rows, by_band_all.get(track, {}), by_dist_all.get(track, {}),
                              dd, "365")
                if r2 and (not r or r2[1] > r[1]):
                    r, fallback = r2, True
            if not r:
                continue
            cell = {"d": r[0], "n": r[1]}
            if fallback:
                cell["b"] = "365"       # 退避= このセルだけ1年版の標準で出した
            if date >= tstr:
                cell["p"] = True        # 当日= 暫定(終わったレースだけ)
            out.setdefault(date, {})[prefix] = cell
            devs_of[(date, track)] = r[2]
            rebuilt += 1
    return out, rebuilt, devs_of


def overlay_ai(days, samples, ai):
    """南関 4 場の日の値を予想 AI の D5(1000m あたり)にそろえる。days= {日: {prefix: セル}}(その場で書き換える)。
    ai= {日: {prefix: D5}}。d1 = D5・d = D5 × その日のその場のレースの平均距離 / 1000(小数 1 桁)・"s":"ai" を付ける。
    g/g1(同じ馬場状態比)は予想 AI に無いので今のまま。暫定(p)の日・AI の値が無い日・サイトのセルが無い日は触らない。
    ⛔確定済みの日も毎回かぶせ直す(AI の値は確定すると動かない= 便より後に AI の値が届いた日も次の回で直る)。
    戻り= かぶせた場日の数"""
    dist_of = {}
    for track, date, dist, _b, _t, _g, rno, _fin in _norm(samples):
        if track in AI_TRACKS:
            dist_of.setdefault((date, track), {})[rno] = dist
    n = 0
    for date, cells in days.items():
        for track in AI_TRACKS:
            pf = TRACK2PREFIX[track]
            v = (ai.get(date) or {}).get(pf)
            c = cells.get(pf)
            ds = dist_of.get((date, track))
            if v is None or not c or c.get("p") or not ds:
                continue
            c["d1"] = round(float(v), 2)
            c["d"] = round(float(v) * statistics.mean(ds.values()) / 1000.0, 1)
            c["s"] = "ai"
            n += 1
    return n


def _ms(d):
    return d.replace(day=1)


def proj_pars(top5, months):
    """top5= [(track, date, surf, dist, time)](1〜5着・同着は速い方 1 本)。months= 月初めの集合
    → {(月初め, track, surf, dist): 月初めより前の 365 日の中央値(8 本以上)}"""
    by = {}
    for track, d, surf, dist, t in sorted(top5, key=lambda r: r[1]):
        k = (track, surf, dist)
        if k not in by:
            by[k] = ([], [])
        by[k][0].append(d)
        by[k][1].append(t)
    out = {}
    for ms in months:
        lo = ms - dt.timedelta(days=PROJ_PAR_DAYS)
        for k, (ds, ts) in by.items():
            i, j = bisect.bisect_left(ds, lo), bisect.bisect_left(ds, ms)
            if j - i >= PROJ_PAR_MIN:
                out[(ms,) + k] = statistics.median(ts[i:j])
    return out


def proj_run(xs, start, end):
    """xs= [(date, track, race_no, horse, x)]。start〜end を古い日から積み上げる
    → (日の値 {(track, date): v}, レースの値 {(track, date): {race_no: v}})"""
    by_date = {}
    for r in xs:
        if start <= r[0] <= end:
            by_date.setdefault(r[0], []).append(r)
    hist, day, rv = {}, {}, {}
    for d in sorted(by_date):
        lo1 = d - dt.timedelta(days=PROJ_WINS[0])
        lo2 = d - dt.timedelta(days=PROJ_WINS[1])
        per = {}
        for _d, track, rno, h, x in by_date[d]:
            hh = hist.get(h) if h is not None else None
            if not hh:
                continue
            last = hh[-5:]
            prev = [(dk, xp) for dp, dk, xp in last if dp >= lo1]
            if len(prev) < 3:
                prev = [(dk, xp) for dp, dk, xp in last if dp >= lo2]
            if len(prev) < 3:
                continue
            f = []
            for dk, xp in reversed(prev):
                if dk in day:
                    b = day[dk]
                elif rv.get(dk):
                    b = statistics.median(list(rv[dk].values()))
                else:
                    b = 0.0
                f.append(xp - b)
            wt = PROJ_WT[:len(f)]
            a = sum(w * v for w, v in zip(wt, f)) / sum(wt)
            per.setdefault((track, rno), []).append(x - a)
        for (track, rno), es in per.items():
            if len(es) >= PROJ_MIN_H:
                rv.setdefault((track, d), {})[rno] = statistics.median(es)
        for track in {r[1] for r in by_date[d]}:
            dd = rv.get((track, d))
            if dd and len(dd) >= MIN_RACES:
                day[(track, d)] = statistics.median(list(dd.values()))
        for _d, track, _rno, h, x in by_date[d]:
            if h is not None:
                hist.setdefault(h, []).append((d, (track, d), x))
    return day, rv


def proj_days(runs, targets):
    """②の日の値(1000m あたり)。runs= [(track, date, race_no, horse, dist, surf, finish, time)]
    (注記なしの全着順・時計あり。date は dt.date か 'YYYY-MM-DD')。targets= 出したい日の集合。
    戻り {('YYYY-MM-DD', track): v}。出したい日の月ごとに、月初めの 730 日前から積み直す(その日より後の走は入らない)"""
    rr = []
    for track, d, rno, h, dist, surf, fin, t in runs:
        if not dist or t is None or track == BANEI:
            continue
        d = d if isinstance(d, dt.date) else dt.date.fromisoformat(d)
        rr.append((track, d, rno, h, int(dist), surf, int(fin), float(t)))
    best = {}
    for r in rr:
        if 1 <= r[6] <= TOP_N:
            k = (r[0], r[1], r[2], r[6])
            if k not in best or r[7] < best[k][7]:
                best[k] = r
    top5 = [(r[0], r[1], r[5], r[4], r[7]) for r in best.values()]
    tds = sorted(t if isinstance(t, dt.date) else dt.date.fromisoformat(t) for t in targets)
    by_m = {}
    for t in tds:
        by_m.setdefault(_ms(t), []).append(t)
    need = set()
    for ms, ts in by_m.items():
        m = _ms(ms - dt.timedelta(days=PROJ_ANCHOR))
        while m <= ts[-1]:
            need.add(m)
            m = (m + dt.timedelta(days=32)).replace(day=1)
    par = proj_pars(top5, need)
    xs = []
    for track, d, rno, h, dist, surf, _fin, t in rr:
        p = par.get((_ms(d), track, surf, dist))
        if p is None:
            continue
        x = max(-PROJ_CLIP, min(PROJ_CLIP, (t - p) / dist * 1000.0))
        xs.append((d, track, rno, h, x))
    out = {}
    for ms, ts in sorted(by_m.items()):
        day, _ = proj_run(xs, ms - dt.timedelta(days=PROJ_ANCHOR), ts[-1])
        tset = set(ts)
        for (track, d), v in day.items():
            if d in tset:
                out[(d.isoformat(), track)] = v
    return out


def blend_proj(days, frozen, proj, rebuild_all=False, samples=None):
    """組み直したセルを classfirst と②の半々にする(d1/g1= 1000m あたりの半々・d/g= ② × 平均距離 / 1000 との半々)。
    南関 4 場・据え置きのセル・②の無い日は触らない。samples= 1〜5着の samples(平均距離用)。戻り= 当てた場日の数"""
    dist_of = {}
    for track, date, dist, _b, _t, _g, rno, _fin in _norm(samples or []):
        dist_of.setdefault((date, track), {})[rno] = dist
    n = 0
    for date, cells in days.items():
        for track, pf in TRACK2PREFIX.items():
            if track in AI_TRACKS:
                continue
            c = cells.get(pf)
            if not c or ("d1" not in c and "g1" not in c):
                continue
            if not rebuild_all and c is (frozen.get(date) or {}).get(pf):
                continue
            v = proj.get((date, track))
            if v is None:
                continue
            ds = dist_of.get((date, track))
            vs = v * statistics.mean(ds.values()) / 1000.0 if ds else None
            for k1, k0 in (("d1", "d"), ("g1", "g")):
                if k1 in c:
                    c[k1] = round(0.5 * float(c[k1]) + 0.5 * v, 2)
                    if k0 in c and vs is not None:
                        c[k0] = round(0.5 * float(c[k0]) + 0.5 * vs, 1)
            n += 1
    return n


def proj_runs_of(allruns, meta):
    """REST の行(全着順)→ proj_days の runs。馬= (馬名, 生年月日)・芝ダ= nar_races.surface・ばんえいは捨てる"""
    runs = []
    for w in allruns:
        if w["track"] == BANEI or w["track"] not in TRACK2PREFIX:   # 南関の走も馬の力には使う(半々は当てない)
            continue
        m = meta.get((w["track"], w["race_date"], w["race_no"]))
        if not m or not m.get("distance_m") or not w.get("horse_name"):
            continue
        runs.append((w["track"], w["race_date"], w["race_no"], (w["horse_name"], w.get("birth_date")),
                     int(m["distance_m"]), m.get("surface"), int(w["finish"]), float(w["time_sec"])))
    return runs


def read_ai(base, key):
    """nar_meta nankan_d5 の days。読めなければ {}(南関もサイトの計算のまま)"""
    try:
        _, body = req(base, key, f"/rest/v1/nar_meta?select=value&key=eq.{AI_META_KEY}")
        rows = json.loads(body)
        v = rows[0].get("value") if rows else None
        return (v or {}).get("days") or {}
    except Exception as e:                      # noqa: BLE001
        log(f"⚠{AI_META_KEY} を読めない({e})= 南関もサイトの計算のまま")
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="公式の馬場状態(going)との相関を出す")
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--baseline", choices=BASELINES, default=DEFAULT_BASELINE,
                    help="標準の窓。projhalf=classfirst と出走馬の力の見積もりの半々(11/1)/ classfirst=クラス優先 5 段・帯なしは外す(既定・10/25)/ going=良馬場比 d+同じ馬場状態比 g(直近1年) / season=同じ暦±45日×3年 / 365=前日までの直近1年 / 1095=旧§104")
    ap.add_argument("--rebuild-all", action="store_true",
                    help="⛔確定済みの日も作り直す(定義を変えたときだけ。ふだんは付けない)")
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    today = _today_jst()
    # ⛔表示する一番古い日(today-90)から見て、その日の標準ぶんまで遡って読む(as-of なので日ごとに窓が動く)
    since = (today - dt.timedelta(days=WINDOW_DAYS + fetch_days(a.baseline))).isoformat()
    # ⛔T5= 1〜5着を読む(約 10 万行・100 ページ前後・1〜2 分)。旧版の窓でも読み方は同じで build_days が finish=1 に絞る。
    #   order は一意になるよう runner_number まで(PostgREST offset は order= 一意)
    #   ⛔finish_note=is.null= 降着・失格等の注記がある馬を除く(検証 baba_4way の ijo==0 と同じ・監査 1f)
    proj = a.baseline == PROJ_BASE
    bl = "classfirst" if proj else a.baseline     # projhalf は classfirst を組んでから d1 を半々にする
    if proj:
        # ⛔projhalf だけ全着順を読む(馬の見分け= 馬名+生年月日)。1〜5着は同じ行から取る
        allruns = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec,"
                                      "horse_name,birth_date,last3f"
                                      f"&finish=gte.1&time_sec=not.is.null&finish_note=is.null&race_date=gte.{since}"
                                      "&order=race_date.asc,track.asc,race_no.asc,finish.asc,runner_number.asc")
        wins = [w for w in allruns if int(w["finish"]) <= TOP_N]
        lead_runs = allruns
    else:
        wins = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec,last3f"
                                   f"&finish=gte.1&finish=lte.{TOP_N}&time_sec=not.is.null&finish_note=is.null&race_date=gte.{since}"
                                   "&order=race_date.asc,track.asc,race_no.asc,finish.asc,runner_number.asc")
        # 前半(FRONT_KEY)の先頭の馬は 6 着以下もある= 前半の窓(表示 90 日+基準 1 年)ぶんだけ 6 着以下も読む
        since_f = max(since, (today - dt.timedelta(days=WINDOW_DAYS + FRONT_DAYS + 1)).isoformat())
        lead_runs = wins + rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,finish,runner_number,time_sec,last3f"
                                    f"&finish=gte.{TOP_N + 1}&time_sec=not.is.null&last3f=not.is.null&finish_note=is.null"
                                    f"&race_date=gte.{since_f}"
                                    "&order=race_date.asc,track.asc,race_no.asc,finish.asc,runner_number.asc")
    races = rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m,race_name,going,race_kind,corners"
                                + (",surface" if proj else "") +
                                f"&race_date=gte.{since}&order=race_date.asc,track.asc,race_no.asc")
    meta = {(r["track"], r["race_date"], r["race_no"]): r for r in races}
    log(f"1〜{TOP_N}着の時計 {len(wins)}行 / レース {len(races)}行({since}〜・標準={a.baseline})")

    # 同着= (レース, 着順) ごとに速い方の時計 1 本だけ
    best = {}
    for w in wins:
        kk = (w["track"], w["race_date"], w["race_no"], int(w["finish"]))
        if kk not in best or float(w["time_sec"]) < float(best[kk]["time_sec"]):
            best[kk] = w
    samples = []           # (track, date, dist, band, time, going, race_no, finish)
    for w in best.values():
        if w["track"] == BANEI or w["track"] not in TRACK2PREFIX:
            continue
        m = meta.get((w["track"], w["race_date"], w["race_no"]))
        if not m or not m.get("distance_m"):
            continue
        b = band_of(m.get("race_name"), w["track"], m.get("race_kind"))
        samples.append((w["track"], w["race_date"], int(m["distance_m"]), b,
                        float(w["time_sec"]), str(m.get("going") or ""), w["race_no"], int(w["finish"])))

    # 前回の blob(確定済みの日を据え置くため)。読めなければ空から組む
    frozen, prev_base = {}, None
    try:
        _, body = req(base, key, f"/rest/v1/nar_meta?select=value&key=eq.{META_KEY}")
        rows = json.loads(body)
        if rows and isinstance(rows[0].get("value"), dict):
            frozen = rows[0]["value"].get("days") or {}
            prev_base = rows[0]["value"].get("base")
    except Exception as e:                      # noqa: BLE001
        log(f"⚠前回の {META_KEY} を読めなかった({e})= 全部組み直す")
        a.rebuild_all = True
    if prev_base and prev_base != a.baseline:
        log(f"⚠標準の窓が {prev_base} → {a.baseline} に変わった= 全部組み直す")
        a.rebuild_all = True

    lo = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    targets = {s[1] for s in samples if lo <= s[1] <= today.isoformat()}
    # 前回の blob に居る日も候補に入れる(確定済みを取りこぼして消してしまわない)
    targets |= {d for d in frozen if lo <= d <= today.isoformat()}
    days, rebuilt, devs = build_days(samples, targets, bl, today=today,
                                     frozen=frozen, rebuild_all=a.rebuild_all)
    days = {d: v for d, v in days.items() if d >= lo}      # 90日の窓から出た日は落とす
    if bl in GOING_LIKE:
        n_gf = add_grp_front(days, frozen, race_rows_of(best, meta, lead_runs), a.rebuild_all)
        log(f"組の差 rg・前半 {FRONT_KEY} を足した: {n_gf} 場日")
    if proj:
        todo = {d for d, cells in days.items()
                for pf, c in cells.items() if a.rebuild_all or c is not (frozen.get(d) or {}).get(pf)}
        runs = proj_runs_of(allruns, meta)
        t1 = time.time()
        pv = proj_days(runs, todo) if todo else {}
        log(f"②(力の見積もり)と半々: {blend_proj(days, frozen, pv, a.rebuild_all, samples)} 場日"
            f"(全着順 {len(runs)}行・組んだ日 {len(todo)}・{time.time() - t1:.0f}秒)")
    if bl in GOING_LIKE:
        log(f"南関 4 場を予想 AI の日の値にそろえた: {overlay_ai(days, samples, read_ai(base, key))} 場日")
    n_cells = sum(len(v) for v in days.values())
    n_prov = sum(1 for v in days.values() for c in v.values() if c.get("p"))
    n_fb = sum(1 for v in days.values() for c in v.values() if c.get("b"))
    log(f"馬場差: {len(days)}日 / {n_cells}場日(組み直し {rebuilt}・暫定 {n_prov}・"
        f"365へ退避 {n_fb}・"
        f"確定済みは据え置き・レース{MIN_RACES}本未満の場日は出さない)")

    if a.verify:
        # 自然妥当性: 公式の馬場状態別に馬場差の平均を見る(ダートは湿ると速い=重・不良が負側なら健全)
        going_of = {}
        for track, date, _d, _b, _t, going, *_rest in samples:
            if date in targets and going:
                going_of.setdefault((date, track), []).append(going)
        buckets = {}
        for (date, track), xs in devs.items():
            gs = going_of.get((date, track)) or []
            if not gs:
                continue
            buckets.setdefault(statistics.mode(gs), []).append(statistics.median(xs))
        for g in ("良", "稍重", "重", "不良"):
            if g in buckets:
                v = buckets[g]
                log(f"  going={g}: 平均 {statistics.mean(v):+.2f}秒 (場日 {len(v)})")

    if not a.apply:
        sample_day = sorted(days)[-1] if days else None
        log(f"ドライラン(--apply なし)。例 {sample_day}: "
            f"{json.dumps(days.get(sample_day, {}), ensure_ascii=False)}")
        return 0

    value = {"built": today.isoformat(), "base": a.baseline, "days": days}
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": META_KEY, "value": value,
                             "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]).encode("utf-8"))
    log(f"nar_meta/{META_KEY} 更新 {st}({len(days)}日 {n_cells}場日・暫定 {n_prov}・退避 {n_fb})")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())

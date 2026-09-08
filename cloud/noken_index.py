# -*- coding: utf-8 -*-
"""統合ビューア cloud: 能検13地区を1つの索引にまとめる(DESIGN §37.4-①)。

/shinba(新馬戦ゾーン)は出走馬に「能検 51.6(7/31)▶」のバッジを出す。v1 は**地区ごとの JSON を読んで**
照合していたので、13地区ぜんぶだと 11本 383KB(gzip)——しかも地区の JSON は7〜15年ぶんの全履歴で、
新馬戦に要るのは直近ぶんだけ、というほぼ無駄な通信だった。そこで**馬名 → 直近3年の受検記録**だけを
先に1枚へ畳んでおく。/shinba はこれ1本で初期表示から全馬にバッジを出せる。

  出力 = nar_meta key='noken_index' の value:
    {"built": "YYYY-MM-DD",
     "horses": {"ゴールドモナコ": [{"d":"kawasaki","date":"2026-07-31","time":"51.6","ok":"合",
                                    "v":"https://youtu.be/gZCBvwp1rvQ","s":0,
                                    "r":1,"n":3,"tr":1,"a":38.2,"ar":1,"t1":13.4}], …}}
    d=地区prefix / time=表示用の文字列 / ok=合・否・null / v=映像URL / s=頭出しの秒(川崎・浦和だけ)
    p=場名(1地区に2場ある岩手・兵庫だけ。「8/1 水沢」と出すため)
    同名馬・再受検は配列に複数入る(日付の新しい順)。使う側は「同名の能検記録が複数」と断ること

  §37.7-1 で足したキー(**値の無いものはキーごと省略**する。持っている地区が違うため):
    r  = 第NR(そのレースのレース番号)
    n  = そのレースの頭数(**発表の表に載っている行数**。タイムの無い馬も1頭として数える)
    tr = レース内のタイム順位(**タイムのある馬だけで**付ける=欠測の馬は分母に入れない・同タイムは同順位)
    a  = 上がり3F(競馬ブック由来の5場だけが持つ)
    ar = レース内の上がり順位(a のある馬だけで・tr と同じ付け方)
    t1 = テン1F(= 走破 − 上がり3F)。**800m(4F)の検査にだけ成り立つ**ので他の距離には出さない
         (門別1000m・川崎900m・大井1200m の検査もある)。js/data.js の nokenOf と同じ規則=画面と食い違わない
    ⚠ n は「頭数」で、tr の分母(タイムのある頭数)とは別物。地区によっては大きく食い違う
      (実測 ばんえい 2,148行中タイムのあるのは 1,245行)。画面で「N頭中M位」と書くときは、この違いを承知で使うこと

  §50 #187/#188 で足したキー(2026-08-28):
    ran = 1 … その馬名が公式の出走記録(nar_runs)に1行でもある(=デビュー済み)。
          ⛔**無いことは何も意味しない**(このビルドの後にデビューした・照会が取り切れなかった、の両方がありうる)。
          画面(getNokenRan)は ran=1 を「確かに走った」の枝刈りにだけ使い、残りは従来どおり生で照会する
          =索引が古くても「走ったのにデビュー待ち」の誤りは出ない(ran は一度付いたら戻らない向きだけの旗)
    dm  … 距離を発表しない日でも、その日の base_dists の値が**1種類だけ**ならそれで埋める(名古屋900m など。
          js/data.js fillDist と同じ規則=画面と食い違わない)
    dr/dn … 距離の読めない検査(ばんえい等)も **(日, 距離なし, 齢帯)** の池で順位を付ける
          (/noken の画面が「距離の発表なし」の池でその場計算しているのと同じ寄せ方=/shinba との差を無くす #188)

読むのは meta の行だけ(13地区 + 川崎浦和の頭出し2行 = 15本)。**旧DB(chihou_meta)と新DB(nar_meta)の
2か所にまたがる**ので、chihou 側は公開 anon キーで読む(js/data.js が同じキーでブラウザから読んでいる)。

  py -3.12 -X utf8 cloud/noken_index.py                      # ドライラン(既定)。scratchpad へ書くだけ
  py -3.12 -X utf8 cloud/noken_index.py --out out/           # 書き出し先を変える
  py -3.12 -X utf8 cloud/noken_index.py --env pipeline/.env.nar --apply   # 実弾(nar_meta へ upsert)
環境変数: SUPABASE_URL / SUPABASE_ANON_KEY(読み) / SUPABASE_SERVICE_KEY(--apply の書き込みだけ)
          CHIHOU_URL / CHIHOU_ANON_KEY(旧DB。既定は公開値なので普段は要らない)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗
"""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env, upsert  # noqa: E402

UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"
JST = dt.timezone(dt.timedelta(hours=9))
META_KEY = "noken_index"
YEARS = 3

# 旧DB(現行プロジェクト)。anon は公開キー= js/data.js の SUPABASE_KEY と同一なので既定値に持つ。
# service key は絶対に使わない(PROJECT.md 技術方針)
CHIHOU_URL = "https://jcrcftvrsgmsewwdkqha.supabase.co"
CHIHOU_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjcmNmdHZyc2dtc2V3d2RrcWhhIiwi"
               "cm9sZSI6ImFub24iLCJpYXQiOjE3ODA4MDY0NjgsImV4cCI6MjA5NjM4MjQ2OH0."
               "UED2rJNsuTPqofrhhNhQ2RM0NKc2eJ6qHllfbnebMe0")

# js/data.js の NOKEN_CHIHOU / NOKEN_NAR と同じ並び。
# §117b で **13地区すべてが主催者公式(nar_meta)**になったので、旧DB(chihou_meta)から読む場は無い。
# ⛔CHIHOU を空にしても旧DBの読み口(sb_get)は残す= 切替が本番で落ち着くまで戻せるようにしておく
CHIHOU = []
NAR = ["iwate", "hyogo", "saga", "banei", "kasamatsu", "nagoya", "kochi", "kanazawa",
       "monbetsu", "ooi", "funabashi", "kawasaki", "urawa"]
ALL = CHIHOU + NAR
# §33.7-3/§33.7-5 1日1本の通し動画をレース別に頭出しできる場(`{prefix}_noken_offsets`)。
# §117b 川崎・浦和・大井も nar_meta 側へ(⛔船橋は画面(js/data.js NOKEN_OFFSETS)が読まないので入れない)
OFFSETS = []
OFFSETS_NAR = ["saga", "banei", "kawasaki", "urawa", "ooi"]
# 1つの地区に競馬場が2つある=どちらで受けたかを持たないと「8/1 水沢」と書けない
MULTI_VENUE = {"iwate", "hyogo"}


def log(msg):
    print(f"[{dt.datetime.now(JST):%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 取得(読むだけ)

def sb_get(base, key, table, meta_key, tries=3):
    """meta の1行の value を返す(無ければ None)。gzip で受ける=岩手・ばんえいは素で 0.5〜0.9MB ある"""
    url = f"{base}/rest/v1/{table}?select=value&key=eq.{meta_key}"
    req = urllib.request.Request(url, headers={
        "apikey": key, "Authorization": f"Bearer {key}",
        "Accept-Encoding": "gzip", "User-Agent": UA})
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            rows = json.loads(raw.decode("utf-8"))
            return rows[0]["value"] if rows else None
        except Exception as e:                     # 5xx も切断も同じ扱い=間を置いてもう一度
            last = e
            if n < tries - 1:
                time.sleep(2 * (n + 1))
    raise RuntimeError(f"{table}/{meta_key} が読めない: {type(last).__name__}: {str(last)[:150]}")


# ---------------------------------------------------------------- 正規化(js/data.js の noken* と同じ規則)

def text(v):
    """投入側(Python)が None をそのまま文字にした値が混ざっている(南関の 'None'・タイムや着順の '-')"""
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "None", "null", "-") else s


_TIME_OK = re.compile(r"(?:\d{1,2}:)?\d{1,2}\.\d")


def time_of(v):
    """主催者ごとに書き方が違うタイムを表示用の1つの形へ。'51.6' / '1:24.5' / '2:44.1'。

    実測の形: 'DD.D'(南関・門別)・'D.DD.D'(岩手・佐賀・高知・金沢ほか)・'D:DD.D'(岩手・名古屋)・
    'DD:DD.D'(ばんえい '02:44.1')。**タイム欄に '中止'/'取消'/'除外' が入っている地区がある**(岩手・佐賀)ので、
    形が合わないものは捨てる=索引に「51.6」以外の文字を混ぜない。'00.0' のような中身の無い値も捨てる。
    """
    s = text(v)
    if not s:
        return None
    s = unicodedata.normalize("NFKC", s)
    m = re.fullmatch(r"(\d+)\.(\d{2}\.\d)", s)
    if m:                                            # '1.24.5' → '1:24.5'
        s = f"{m.group(1)}:{m.group(2)}"
    m = re.fullmatch(r"(\d+):(\d{2}):(\d)", s)
    if m:                                            # '1:11:1'(岩手に1件の誤植)→ '1:11.1'
        s = f"{m.group(1)}:{m.group(2)}.{m.group(3)}"
    s = re.sub(r"^0(\d:)", r"\1", s)                 # '02:44.1' → '2:44.1'
    if not _TIME_OK.fullmatch(s) or not re.search(r"[1-9]", s):
        return None
    return s


def time_sec(disp):
    """time_of() が返した表示用の文字列を秒に(順位付けの比較用)。'51.6'→51.6 / '1:24.5'→84.5 / '2:44.1'→164.1。
    time_of を通した文字列しか渡さない=ここで形の判定はもうしない(通らなければ None)"""
    if not disp:
        return None
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}\.\d)", disp)
    if not m:
        return None
    return float(m.group(2)) + (int(m.group(1)) * 60 if m.group(1) else 0)


def last3f_of(v):
    """上がり3F。**競馬ブック由来の5場だけ**が持つ列で、実測は '38.4' か '-'(空欄)の2通りしかない
    (全 1,834 行を検査。'-' が 29行・空が1行)。形が違うものは捨てる=画面に数字以外を出さない"""
    s = text(v)
    if not s:
        return None
    s = unicodedata.normalize("NFKC", s)
    if not re.fullmatch(r"\d{1,2}(?:\.\d)?", s):
        return None
    x = float(s)
    return x if x > 0 else None


def int_of(v):
    """整数(距離など)。地区によって 800 と '800' が混ざるので、どちらでも同じ値になるようにする"""
    s = text(v)
    if s is None:
        return None
    try:
        return int(float(unicodedata.normalize("NFKC", s)))
    except ValueError:
        return None


def ten1f_of(dist, sec, last3f):
    """テン1F(最初の1F)= 走破タイム − 上がり3F。**800m(4F)の検査にだけ成り立つ**。
    ⛔ 門別1000m・川崎900m・大井1200m の検査もあるので、そこで引き算すると「最初の2F」等の別物になる。
    js/data.js の nokenOf が画面で使っている規則と1文字も変えない(索引と馬ページが食い違わないように)。
    ⚠ 引き算は**1/10秒の整数**でする。'51.5' と '38.8' は2進で丸め誤差を持つので、そのまま引いて
      丸めると 12.7 が 12.8 になることがある(検算スクリプトで実際に踏んだ)。両方とも小数第1位までの
      発表なので、10倍して整数にしてから引けば誤差はそもそも生まれない"""
    if dist != 800 or sec is None or last3f is None:
        return None
    v = (round(sec * 10) - round(last3f * 10)) / 10
    return v if v > 0 else None


def rank_of(pairs):
    """[(鍵, 値)] → {鍵: 順位}。値の小さいほど上位・**同値は同順位**で次は人数ぶん飛ばす(1,2,2,4)。
    値の無い馬は呼ぶ前に外してある=**分母に入れない**(§37.7-1)"""
    out, prev, rank = {}, None, 0
    for i, (k, v) in enumerate(sorted(pairs, key=lambda x: x[1]), start=1):
        if prev is None or v != prev:
            rank, prev = i, v
        out[k] = rank
    return out


# 合否の言い方は主催者でばらばら(実測): 合格/合/○/〇/合格* ・ 不合格/否/☓。
# それ以外(欠場・休・出走取消・競走除外・中止・不参加・2Rへ…)は「合とも否とも言っていない」ので null にする。
# ⚠ここで潰した値は build() が地区ごとに数えてログに出す(黙って消えないように)
_OK_YES = {"合格", "合", "○", "〇", "◯", "可"}
_OK_NO = {"不合格", "否", "×", "☓", "✕", "不可"}


def ag_of(age):
    """齢 → 齢帯。§68.11: 2=2歳 / 3以上=3歳以上 / 1歳以下は畳まず None(呼び元が警告を出す)。
    raw の実測は 2〜12歳・1歳以下 0件だが、将来 1歳表記が来ても黙って「3歳以上」にしない"""
    if age == 2:
        return 2
    if age >= 3:
        return 3
    return None


def ok_of(v):
    s = text(v)
    if not s:
        return None, None
    s = s.strip("*＊ 　")
    if s in _OK_YES:
        return "合", None
    if s in _OK_NO:
        return "否", None
    return None, s                                   # 第2要素 = 落とした生の値(ログ用)


# 「ツミノカオリ(コパノエビス)」「クツワホームランの2024(べラジオホームラン)」= 名前が決まる前に受検した馬。
# 括弧の中が登録名(実測 全13地区で4行だけ: 岩手3・笠松1)
_PAREN = re.compile(r"[（(]\s*([^（()）]+?)\s*[）)]\s*$")
_HIRA = re.compile(r"[ぁ-ゖ]")
_DASH = re.compile(r"(?<=[ァ-ヴ])[-‐‑–—―]")


def name_keys(raw):
    """索引の鍵。**主催者発表そのまま**が第一の鍵(v1 の照合を1文字も変えない)。
    それだと引けない書き方が実測で2種類あるので、**別名を足す**(元の鍵は消さない=情報を減らさない):
      ①名前が決まる前の受検 → 括弧の中が登録名。'クツワホームランの2024(べラジオホームラン)'
      ②カタカナ名に紛れた ひらがな・ハイフン → 'べラジオホームラン'(べ が平仮名)・'シクノへリュウ'・'グレ-シー'。
        競走馬名はカタカナだけなので、ひらがなはカタカナへ・カタカナに挟まれた '-' は長音へ直す(実測3行)
    ⛔ここで直した名前が**元の名前を置き換えることはない**。置き換えると、いま合っている 5,600 頭の照合が
      静かに壊れうる(nar_runs 側の書き方は主催者ごとに違う)ので、足すだけにする。
    """
    m = _PAREN.search(raw)
    # 括弧つきは中身が登録名。括弧の外(母名)まで直そうとすると 'クツワホームランの2024' の「の」まで
    # カタカナにしてしまうので、②の直しは**登録名の候補にだけ**かける
    cand = m.group(1) if (m and m.group(1)) else raw
    fixed = _DASH.sub("ー", _HIRA.sub(lambda c: chr(ord(c.group(0)) + 0x60), cand))
    keys = [raw, cand, fixed]
    return [k for i, k in enumerate(keys) if k and k not in keys[:i]]


def video_of(v):
    """§32d 壊れた YouTube ID を出さない(笠松に2件・公式側で13文字に切れている)。
    mp4 など YouTube 以外はそのまま通す(門別=主催者の直mp4・大井/船橋=R2 のレース単位 mp4)"""
    s = text(v)
    if not s or not re.match(r"^https?://", s):
        return None
    if "youtube.com" not in s and "youtu.be" not in s:
        return s
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", s)
    if m:
        return s if len(m.group(1)) >= 18 else None
    m = re.search(r"[?&]v=([A-Za-z0-9_-]+)", s) or re.search(r"youtu\.be/([A-Za-z0-9_-]+)", s)
    if m:
        return s if len(m.group(1)) == 11 else None
    return None


def is_date(s):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s or "")))


def cutoff_date(today, years=YEARS):
    """今日から N 年前。2/29 は 2/28 に寄せる(閏日に走っても落ちない)"""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, month=2, day=28)


# ---------------------------------------------------------------- 索引を組む

def day_offsets(off_value):
    """{prefix}_noken_offsets → {日付: {video_id, {レース番号: 秒}}}。形の壊れた日は落とす"""
    out = {}
    days = (off_value or {}).get("days")
    if not isinstance(days, dict):
        return out
    for date, d in days.items():
        if not is_date(date) or not isinstance(d, dict):
            continue
        vid = text(d.get("video_id"))
        offs = d.get("offsets")
        if not vid or not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) or not isinstance(offs, dict):
            continue
        secs = {}
        for k, v in offs.items():
            try:
                no, sec = int(str(k)), int(v)
            except (TypeError, ValueError):
                continue
            if no >= 1 and sec >= 0:
                secs[no] = sec
        if secs:
            out[date] = (vid, secs)
    return out


def better(a, b):
    """同じ地区・同じ日に同じ馬名が2行あるとき(岩手の '２Rへ' = 1Rを流して2Rで受け直し)どちらを採るか。
    合否が付いている > タイムがある > 後のレース、の順。情報の多い方を残す"""
    def score(x):
        return (1 if x["ok"] else 0, 1 if x["time"] else 0, x.get("_no") or 0)
    return a if score(a) >= score(b) else b


def build(metas, offsets, cut, stats):
    """metas = {prefix: value} → {馬名: [記録…]}"""
    horses = {}
    for prefix in ALL:
        value = metas.get(prefix)
        days = (value or {}).get("days")
        if not isinstance(days, list):
            log(f"⚠ {prefix}: days が無い(この地区は索引に入らない)")
            continue
        off = offsets.get(prefix) or {}
        st = stats.setdefault(prefix, {"days": 0, "days_all": len(days), "rows": 0,
                                       "time": 0, "ok": 0, "video": 0, "cue": 0,
                                       "a": 0, "t1": 0, "r": 0, "tr": 0, "dr": 0, "ag": 0,
                                       "dup": 0, "alias": [], "dropped_ok": {}})
        seen = {}                                    # (馬名, 日付) → 記録(同じ日の重複を1つに)
        for day in days:
            if not isinstance(day, dict):
                continue
            date = str(day.get("date") or "")
            if not is_date(date) or date < cut:
                continue
            st["days"] += 1
            day_video = video_of(day.get("video"))
            cue = off.get(date)
            day_venue = text(day.get("venue"))
            # §50 #188 距離を発表しない日の埋め= その日の base_dists の値が1種類だけならそれ
            # (js/data.js fillDist と同じ規則。笠松のように 800/1400 が混ざる日は埋めない)
            bd = day.get("base_dists")
            fill_vals = {int_of(v) for v in bd.values()} - {None} if isinstance(bd, dict) else set()
            day_fill = fill_vals.pop() if len(fill_vals) == 1 else None
            for race in (day.get("races") or []):
                if not isinstance(race, dict):
                    continue
                try:
                    no = int(str(race.get("no")))
                except (TypeError, ValueError):
                    no = None
                # 映像の在り処は主催者で違う。**レース単位があればそれが最良**(門別=直mp4・大井/船橋=R2の切り出し・
                # 岩手=公式がレースごとに YouTube)。無ければ日単位の通し動画 + 頭出しの秒(川崎・浦和)
                v = video_of(race.get("mp4")) or video_of(race.get("video"))
                s = None
                if not v and day_video:
                    v = day_video
                    if cue and no is not None and no in cue[1]:
                        s = cue[1][no]
                venue = text(race.get("venue")) or day_venue
                # §37.7-1 順位は**そのレースの行から**その場で作る。名前の無い行(実測ゼロだが用心)は
                # 索引に入らないので頭数にも数えない=画面の「N頭中」と索引の中身がずれない
                rows = [x for x in (race.get("rows") or []) if isinstance(x, dict) and text(x.get("name"))]
                dist = int_of(race.get("dist"))
                if dist is None:
                    dist = day_fill
                shown, times, lasts = [], {}, {}
                for i, row in enumerate(rows):
                    shown.append(time_of(row.get("time")))
                    sec = time_sec(shown[i])
                    if sec is not None:
                        times[i] = sec
                    a = last3f_of(row.get("last3f"))
                    if a is not None:
                        lasts[i] = a
                tr_of = rank_of(times.items())
                ar_of = rank_of(lasts.items())
                for i, row in enumerate(rows):
                    name = text(row.get("name"))
                    st["rows"] += 1
                    ok, dropped = ok_of(row.get("ok"))
                    if dropped:
                        st["dropped_ok"][dropped] = st["dropped_ok"].get(dropped, 0) + 1
                    keys = name_keys(name)
                    if len(keys) > 1:
                        st["alias"].append(f"{name}→{keys[1:]}")
                    rec = {"d": prefix, "date": date, "time": shown[i], "ok": ok,
                           "v": v, "s": s, "_no": no, "_keys": keys}
                    # §50 K-1c 距離と齢帯(日全体順位の池の鍵)。sexage='牡2'→2 / 3歳以上は3に畳む
                    if dist is not None:
                        rec["dm"] = dist
                    m_ag = re.search(r"(\d+)", str(row.get("sexage") or ""))
                    if m_ag:
                        ag = ag_of(int(m_ag.group(1)))
                        if ag is not None:
                            rec["ag"] = ag
                        else:
                            log(f"⚠齢が読めない({prefix} {date} {name}: sexage={row.get('sexage')!r})→ ag なし")
                    if prefix in MULTI_VENUE and venue:
                        rec["p"] = venue
                    # 値の無いものはキーごと省略(地区で持っている列が違う。1件ずつのサイズを増やさないため)
                    if no is not None:
                        rec["r"] = no
                    rec["n"] = len(rows)
                    if i in tr_of:
                        rec["tr"] = tr_of[i]
                    if i in lasts:
                        rec["a"] = lasts[i]
                        rec["ar"] = ar_of[i]
                    t1 = ten1f_of(dist, times.get(i), lasts.get(i))
                    if t1 is not None:
                        rec["t1"] = t1
                    k = (name, date)
                    if k in seen:
                        st["dup"] += 1
                        seen[k] = better(seen[k], rec)
                    else:
                        seen[k] = rec
        # §50 K-1c 日全体順位= 同じ日×距離×齢帯の池で、タイムのある馬だけ・同タイムは同順位。
        # 齢帯が読めない行は (日,距離,None) の池=その地区が齢を発表していなければ実質「距離全体」。
        # 2歳/3歳の池には混ぜない(分母をごまかさない)。
        # §50 #188 距離の読めない検査も (日, None, 齢帯) の池で付ける(ばんえい等。
        # /noken の画面が「距離の発表なし」の池でその場計算しているのと同じ寄せ方=/shinba との差を無くす)
        pools = {}
        for rec in seen.values():
            sec = time_sec(rec.get("time"))
            if sec is None:
                continue
            pools.setdefault((rec["date"], rec.get("dm"), rec.get("ag")), []).append((rec, sec))
        for members in pools.values():
            ranks = rank_of([(i, sec) for i, (_r, sec) in enumerate(members)])
            for i, (rec, _sec) in enumerate(members):
                rec["dr"] = ranks[i]
                rec["dn"] = len(members)

        for (_name, _date), rec in seen.items():
            if rec["time"]:
                st["time"] += 1
            if rec["ok"]:
                st["ok"] += 1
            if rec["v"]:
                st["video"] += 1
            if rec["s"] is not None:
                st["cue"] += 1
            for k in ("a", "t1", "r", "tr", "dr", "ag"):   # §37.7-1/§50 地区ごとの充足率(黙って空にならないように)
                if rec.get(k) is not None:
                    st[k] += 1
            rec.pop("_no", None)
            for k in rec.pop("_keys"):
                horses.setdefault(k, []).append(dict(rec))
    # 日付の新しい順(同じ日なら地区名で決めうち=毎回同じ並びになる)
    for name in horses:
        horses[name].sort(key=lambda r: (r["date"], r["d"]), reverse=True)
    return {n: horses[n] for n in sorted(horses)}


# ---------------------------------------------------------------- §50 #187 デビュー済み(ran)

RAN_CHUNK = 200          # in.() の URL 上限の実測(js 側 2026-08-28: 300頭=21KB 可 / 400頭=28KB は 400)に合わせる
RAN_PAGE = 1000          # PostgREST の1回の上限
RAN_PAGE_MAX = 20        # 1チャンクの継ぎ足し上限(200頭×平均15走でも 3,000行=3ページ。20あれば届かない方が異常)
# ⛔#199(2026-08-29 修理): 「走った」= 着順がある or 発走してから止まった(競走中止・失格)。
# 出走取消・競走除外は**走っていない**(ゲートに入っていない)のでデビュー待ちのまま。
# js/data.js の didRun / RAN_FILTER と同じ定義に統一(実測: finish_note は 出走取消510・競走除外254 など)。
# 修理前の finish_note.not.is.null は取消・除外まで旗を付けた(実測: 浦和で9頭がデビュー待ちに戻れなかった)
RAN_FILTER = "or=" + urllib.parse.quote('(finish.not.is.null,finish_note.in.("競走中止","失格"))')


def fetch_ran(base, key, names):
    """馬名の集合 → nar_runs に**結果付きの行**(finish か finish_note がある=実際に走った)が
    1行でもある名前の集合。in.() を200件ずつ・1000行に当たったら horse_name=gt.(最後の名前) で継ぎ足す。
    ⛔#198(2026-08-29 修理): 初版は「行の有無」だけを見ていた= nar_runs には**出馬表の行(finish null)も入る**ので、
    今日明日に出走予定なだけの馬(=まさにデビュー予定の馬)全員に旗が付いた(noken_debuts が即日 0頭になって発覚)。
    「走った」の定義は noken_debuts.py と同じ**結果付きの行**に統一する(取消だけの馬はデビュー待ちのまま)。
    ⚠戻りは (ran, 取り切れなかったチャンク数)。**取り切れなかった名前には旗を付けない**だけで
    ビルドは失敗にしない(旗の無い馬は画面が従来どおり生で照会する=安全側)。
    ⚠`"` を含む名前は in.() に載せられないので外す(実測ゼロ。載せると引用が壊れる)"""
    todo = sorted({n for n in names if n and '"' not in n})
    ran, bad = set(), 0
    for i in range(0, len(todo), RAN_CHUNK):
        chunk = todo[i:i + RAN_CHUNK]
        in_list = ",".join(f'"{n}"' for n in chunk)
        frm, done = None, False
        for _page in range(RAN_PAGE_MAX):
            q = (f"horse_name=in.({urllib.parse.quote(in_list)})&select=horse_name"
                 f"&{RAN_FILTER}"
                 f"&order=horse_name.asc&limit={RAN_PAGE}"
                 + (f"&horse_name=gt.{urllib.parse.quote(frm)}" if frm else ""))
            url = f"{base}/rest/v1/nar_runs?{q}"
            req = urllib.request.Request(url, headers={
                "apikey": key, "Authorization": f"Bearer {key}",
                "Accept-Encoding": "gzip", "User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                rows = json.loads(raw.decode("utf-8"))
            except Exception as e:
                log(f"⚠ ran 照会に失敗(このチャンクの旗は付けない): {type(e).__name__}: {str(e)[:120]}")
                rows = None
            if rows is None:
                break
            got = [str(x.get("horse_name") or "") for x in rows if isinstance(x, dict)]
            ran.update(n for n in got if n)
            if len(rows) < RAN_PAGE:
                done = True
                break
            last = got[-1] if got else None
            if not last or last == frm:
                break                                    # 進めないなら打ち切る(無限に回さない)
            frm = last
        if not done:
            bad += 1
    return ran, bad


# ---------------------------------------------------------------- 入り口

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ実際に投入する(既定はドライラン)")
    ap.add_argument("--dry-run", action="store_true", help="既定。書き出すだけで投入しない")
    ap.add_argument("--out", default=str(HERE.parent / "scratchpad" / "noken_index"),
                    help="noken_index.json の書き出し先ディレクトリ")
    ap.add_argument("--years", type=int, default=YEARS, help="何年前までの検査を入れるか(既定3)")
    ap.add_argument("--env", help="接続先 .env(pipeline/.env.nar)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    service = os.environ.get("SUPABASE_SERVICE_KEY", "")
    read_key = anon or service                       # 読みは anon で足りる(RLS で select 可)
    chihou_url = os.environ.get("CHIHOU_URL", CHIHOU_URL).rstrip("/")
    chihou_key = os.environ.get("CHIHOU_ANON_KEY", CHIHOU_ANON)
    if not base or not read_key:
        log("SUPABASE_URL と SUPABASE_ANON_KEY(または SERVICE_KEY)が要る")
        return 2
    if args.apply and not service:
        log("--apply には SUPABASE_SERVICE_KEY が要る")
        return 2

    today = dt.datetime.now(JST).date()
    cut = cutoff_date(today, args.years).isoformat()
    log(f"能検索引: {cut} 以降の検査を集める(13地区)")

    metas, offsets = {}, {}
    try:
        for p in CHIHOU:
            metas[p] = sb_get(chihou_url, chihou_key, "chihou_meta", f"{p}_noken")
        for p in OFFSETS:
            offsets[p] = day_offsets(sb_get(chihou_url, chihou_key, "chihou_meta", f"{p}_noken_offsets"))
        for p in NAR:
            metas[p] = sb_get(base, read_key, "nar_meta", f"{p}_noken")
        for p in OFFSETS_NAR:
            offsets[p] = day_offsets(sb_get(base, read_key, "nar_meta", f"{p}_noken_offsets"))
    except Exception as e:
        log(f"読み取りに失敗: {e}")
        return 2

    stats = {}
    horses = build(metas, offsets, cut, stats)

    # §50 #187 デビュー済みの旗。鍵(別名込み)ごとに nar_runs の有無を引き、あった名前の記録全部に ran:1。
    # ⚠置く場所は**名前の下の記録ぜんぶ**(同名の再受検で配列が複数でも、旗は「その名前が走ったか」の1情報)
    ran, bad = fetch_ran(base, read_key, horses.keys())
    marked = 0
    for name in horses:
        if name in ran:
            for rec in horses[name]:
                rec["ran"] = 1
            marked += 1
    log(f"ran: {len(horses):,} 鍵中 {marked:,} にデビュー済みの旗"
        + (f" ⚠取り切れなかったチャンク {bad}(その名前は旗なし=画面が生で照会する)" if bad else ""))

    value = {"built": today.isoformat(), "horses": horses}

    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    gz = len(gzip.compress(body, 9))
    entries = sum(len(v) for v in horses.values())
    log(f"{'地区':<10}{'日':>5}{'頭':>7}{'時計':>7}{'合否':>7}{'映像':>7}{'頭出し':>8}"
        f"{'R番号':>7}{'順位':>7}{'上3F':>7}{'テン':>7}  重複")
    for p in ALL:
        s = stats.get(p)
        if not s:
            continue
        got = sum(1 for v in horses.values() for r in v if r["d"] == p)
        log(f"{p:<10}{s['days']:>5}{got:>7}{s['time']:>7}{s['ok']:>7}{s['video']:>7}{s['cue']:>8}"
            f"{s['r']:>7}{s['tr']:>7}{s['a']:>7}{s['t1']:>7}  {s['dup']}"
            + (f"  別名 {s['alias']}" if s["alias"] else "")
            + (f"  ⚠合否を落とした値 {s['dropped_ok']}" if s["dropped_ok"] else ""))
    log(f"合計: {len(horses):,} 頭 / {entries:,} 件 / 素 {len(body) / 1024:.1f}KB / gzip {gz / 1024:.1f}KB")
    if gz > 150 * 1024:
        log("⚠ gzip が 150KB を超えた。目標は数十KB=画面に載せる前に相談すること")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "noken_index.json"
    path.write_bytes(body)
    log(f"{path} に書き出し")

    if not args.apply:
        log("ドライラン(--apply で投入)")
        return 0

    # 冪等: 中身が同じなら書かない(毎朝走るので、変わっていない日は DB を触らない)
    cur = sb_get(base, read_key, "nar_meta", META_KEY)
    if isinstance(cur, dict) and cur.get("horses") == horses:
        log(f"nar_meta/{META_KEY} は変化なし(投入しない)")
        return 0
    status, msg = upsert(base, service, "nar_meta", "key",
                         [{"key": META_KEY, "value": value,
                           "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
    if status not in (200, 201):
        log(f"投入失敗 {status} {msg}")
        return 1
    log(f"nar_meta/{META_KEY} 更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())

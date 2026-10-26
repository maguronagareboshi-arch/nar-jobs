#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究用・1 回きり(2026-10-26)。読み物「言い伝えをデータで確かめる」7 本の集計 実装 B(実装 A と照合する独立の再計算)。

約束= nar-site research/lore-articles/SPEC.md(T1〜T7)。約束で決まっていない所は DECISIONS に書き、summary.md の頭に出す。
⛔本番 DB は REST の単純 select だけ(場ごと・年ごと・一意の order でページ送り)。書き込みなし。rpc なし。
⛔T3 の馬場差は cloud/baba.py を import せず、この台本の中で書き直した(作り方は research_baba_classfirst.py の D と同じ型)。

  python3 cloud/research_lore_b.py            # 便(SUPABASE_URL / SUPABASE_SERVICE_KEY)→ out/B/lore.json・summary.md
  python3 cloud/research_lore_b.py --selftest # 作り物で関数の試験だけ(DB に触らない)
"""
import bisect
import datetime as dtm
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out", "B")
UA = "nar-jobs research_lore_b (+https://yukochi.com/)"

P0, P1 = dtm.date(2024, 10, 1), dtm.date(2026, 9, 30)     # 期間
Y2 = dtm.date(2025, 10, 1)                                # 2 年目の始まり
L0 = dtm.date(2022, 10, 1)                                # 前走をさかのぼる始まり(期間の 2 年前)
VENUES = ["門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松", "名古屋", "園田", "姫路", "高知", "佐賀"]
AREA = {"門別": "北海道", "盛岡": "岩手", "水沢": "岩手", "浦和": "南関東", "船橋": "南関東", "大井": "南関東",
        "川崎": "南関東", "金沢": "金沢", "笠松": "東海", "名古屋": "東海", "園田": "兵庫", "姫路": "兵庫",
        "高知": "高知", "佐賀": "佐賀", "帯広": "帯広", "帯広ば": "帯広"}
BABA_CODE = {"門別": "36", "盛岡": "10", "水沢": "11", "浦和": "18", "船橋": "19", "大井": "20", "川崎": "21",
             "金沢": "22", "笠松": "23", "名古屋": "24", "園田": "27", "姫路": "28", "高知": "31", "佐賀": "32"}
DROP_NOTES = ("出走取消", "競走除外")
# 所属地区(10/26 改訂 T5)= nar_runs.trainer_area → 地区。表に無い値はその値のまま(数表 aff_values に件数)
AFF = {}
for _a, _ks in {"北海道": "北海道 門別 ホッカイドウ", "岩手": "岩手 盛岡 水沢",
                "南関東": "南関東 浦和 埼玉 船橋 千葉 大井 東京 東京都 川崎 神奈川",
                "金沢": "金沢 石川", "東海": "東海 笠松 岐阜 名古屋 愛知", "兵庫": "兵庫 園田 姫路",
                "高知": "高知", "佐賀": "佐賀", "中央": "JRA 中央 美浦 栗東 ＪＲＡ", "帯広": "帯広 ばんえい"}.items():
    for _k in _ks.split():
        AFF[_k] = _a


def aff_of(ta, venue):
    t = re.sub(r"[\s　]", "", ta) if isinstance(ta, str) and ta.strip() else None
    if t is None:
        return AREA.get(venue)          # 所属が空の走= 場の地区で補う(件数は aff_null)
    return AFF.get(t, t)
GAP_BINS = [(1, 13), (14, 20), (21, 27), (28, 41), (42, 62), (63, 90), (91, 180), (181, 365), (366, 99999)]
WC_BINS = [(-999, -10, "−10以下"), (-9, -4, "−9〜−4"), (-3, 3, "−3〜+3"), (4, 9, "+4〜+9"), (10, 19, "+10〜+19"),
           (20, 999, "+20以上")]

DECISIONS = [
    "馬の同定= 馬名+生年月日(生年月日が空の走は 馬名+空 で 1 頭とみなす。件数は数表の「生年月日なしの走」)。",
    "前走をさかのぼる範囲= 2022-10-01 以降(期間の 2 年前から)。それより前にしか前走が無い馬は「初出走」と同じに外れる。",
    "前走= その馬の、そのレースより前の日の『実際に出走した走』(出走取消・競走除外は走に数えない。競走中止・不成立のレースの走は数える)。"
    "中央の走は nar_jra_runs(鍵 kb_horse_id→nar_jra_horses の馬名+生年月日。生年月日が空なら馬名+生年が地方の走で 1 頭に決まるときだけ使う)。"
    "同じ馬・同じ日に地方と中央の両方の行があれば地方の行だけ残す。",
    "地区(T7 の『前の走が同じ地区』)= その走の場の地区。中央の走は中央(nar_jra_runs の place が地方の場名ならその場の地区)。"
    "帯広(ばんえい)の走は読まない(平地の馬の前走には出てこない前提)。",
    "T5 の所属地区(10/26 改訂)= nar_runs.trainer_area を地区へ(北海道/岩手/南関東/金沢/東海(愛知・岐阜・笠松・名古屋)/兵庫/高知/佐賀/JRA→中央)。"
    "表に無い値はその値のまま 1 つの地区とみなす(値と件数は数表 aff_values)。trainer_area が空の走は場の地区で補う(件数 aff_null)。中央の走は全部 中央。",
    "頭数= そのレースで実際に出走した頭数(取消・除外を除いた走の数)。T1 の頭数区分・T2 の内中外もこの頭数。",
    "勝ち= 着順 1・2 着内= 着順 1〜2・3 着内= 着順 1〜3(競走中止は着順なし= どれでもない)。",
    "人気比の期待値= 期間 2 年の『場×人気』の 3 着内率(取消・除外・不成立を外した走で、人気のある走だけ)。",
    "T1 の年ごと= 1 年目 2024-10-01〜2025-09-30・2 年目 2025-10-01〜2026-09-30。",
    "T2 の距離= nar_races.distance_m。100 レース以上= 2 年で取消等を外したあとのレース数。枠番は nar_runs.gate(1〜8 以外は数えない)。",
    "T3 の馬場差= 1〜5 着の時計(注記なし・時計あり・同着は速い方 1 本)ごとに『同じ場×距離×クラス×着順・馬場状態が良・前日までの 365 日』の中央値(8 本以上)との差。"
    "クラスで 8 本に足りなければ 字だけのクラス(A1→A)→ 場×距離 の順に退避(サイトの退避と同じ 3 段)。レースの値= その差の中央値(3 頭以上)。"
    "クラスの読み方はサイトと同じ規則をこの台本に書き直した(重賞・準重賞・オープン= OP・若馬 OP・A/B/C+組・2歳・3歳・複数級)。"
    "クラスが読めないレースは外す。+ は遅い。日の値(4 R 以上の中央値)にはしない= レースごとの値で集計。",
    "T3 の時間帯= nar_races.post_time(『1550』『15:50』)。昼 〜15:59・夕方 16:00〜17:59・夜 18:00〜。読めない時刻は欠けとして数える。",
    "T3 の場×月= 暦の年月(2024-10〜2026-09 の 24 か月を別々)。重み= その組の 2 つの時間帯のレース数の和。"
    "馬場状態は良/良以外(稍重・重・不良)。馬場状態が空のレースは馬場別の比べから外す。",
    "T5 の数え方= 地区が変わった走を 1 走目とし、同じ地区で続く走を 2・3・4 走目以降と数える。データ内で一度も地区が変わっていない馬の走は『移籍なし』。"
    "比べ相手= 前走も同じ地区の走(移籍後 2 走目以降も含む)と、『移籍なし』の 2 つを出す。前の地区= 移ってくる直前の走の地区。",
    "T6 の増減= nar_runs.body_weight_change(発表)。空なら 馬体重 − 前走の馬体重(前走が地方の走で両方あるときだけ)。前走の無い走・馬体重の無い走は外す。",
    "T7 の騎手= nar_runs.jockey の空白と見習いの印(▲△☆◇★)を除いて比べる。前走が同じ地区(地方の走)・間隔 62 日以内・両方の騎手が分かる走だけ。",
    "公式との照合の 5 レース= 期間の取消等を外したレースから乱数(種 20261026+B)で選んだ。",
]


def log(msg):
    print(msg, flush=True)


# ---------- REST(単純 select だけ) ----------
class Rest:
    def __init__(self, base, key):
        self.base, self.key, self.nreq = base.rstrip("/"), key, 0

    def get(self, q):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA,
             "Accept": "application/json"}
        for i in range(4):
            self.nreq += 1
            try:
                r = urllib.request.Request(self.base + "/rest/v1/" + q, headers=h)
                with urllib.request.urlopen(r, timeout=180) as x:
                    return json.loads(x.read() or b"[]")
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429 or i == 3:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if i == 3:
                    raise
            time.sleep(5 * (i + 1))

    def paged(self, q, order):
        rows, off = [], 0
        while True:
            part = self.get(f"{q}&order={order}&limit=1000&offset={off}")
            rows += part
            if len(part) < 1000:
                return rows
            off += 1000


def enc(v):
    return urllib.parse.quote(str(v), safe="")


def year_chunks(lo, hi):
    y = lo.year
    while y <= hi.year:
        yield max(lo, dtm.date(y, 1, 1)).isoformat(), min(hi, dtm.date(y, 12, 31)).isoformat()
        y += 1


RUN_COLS = "track,race_date,race_no,runner_number,gate,horse_name,birth_date,jockey,body_weight,body_weight_change," \
           "finish,finish_note,time_sec,popularity,trainer_area"
RACE_COLS = "track,race_date,race_no,distance_m,race_name,going,race_kind,post_time"


def load(rest):
    runs, races, facts, notes = [], [], [], {}
    for v in VENUES:
        t0 = time.time()
        nr = 0
        for lo, hi in year_chunks(L0, P1):
            rng = f"&track=eq.{enc(v)}&race_date=gte.{lo}&race_date=lte.{hi}"
            part = rest.paged("nar_runs?select=" + RUN_COLS + rng, "race_date.asc,race_no.asc,runner_number.asc")
            nr += len(part)
            runs.append(pd.DataFrame(part))
            races.append(pd.DataFrame(rest.paged("nar_races?select=" + RACE_COLS + rng, "race_date.asc,race_no.asc")))
        log(f"{v} 走 {nr:,} {time.time() - t0:.0f}s")
    runs = pd.concat([d for d in runs if len(d)], ignore_index=True)
    races = pd.concat([d for d in races if len(d)], ignore_index=True)
    facts = pd.DataFrame()                                            # 10/26 改訂= 単勝の倍率は出さない
    jra = pd.DataFrame()
    try:
        hs = pd.DataFrame(rest.paged("nar_jra_horses?select=kb_horse_id,horse_name,birth_date,birth_year",
                                     "kb_horse_id.asc"))
        jr = []
        for lo, hi in year_chunks(L0, P1):
            jr.append(pd.DataFrame(rest.paged(f"nar_jra_runs?select=kb_horse_id,kb_race_id,race_date,place,finish_note"
                                              f"&race_date=gte.{lo}&race_date=lte.{hi}",
                                              "kb_horse_id.asc,kb_race_id.asc")))
        jr = pd.concat([d for d in jr if len(d)], ignore_index=True)
        jra = map_jra(hs, jr, runs)
        notes["jra_rows"] = int(len(jr))
        notes["jra_horses"] = int(len(hs))
    except Exception as e:                                            # noqa: BLE001
        notes["jra_error"] = str(e)[:300]
    notes["nreq"] = rest.nreq
    return runs, races, facts, jra, notes


def map_jra(hs, jr, runs):
    """中央の走に 馬名+生年月日 を付ける。生年月日が空なら 馬名+生年 が地方の走で 1 頭に決まるときだけ"""
    if hs.empty or jr.empty:
        return pd.DataFrame(columns=["horse_name", "birth_date", "race_date", "place", "finish_note"])
    hs = hs.copy()
    if "birth_year" not in hs:
        hs["birth_year"] = np.nan
    bd = runs[["horse_name", "birth_date"]].dropna().drop_duplicates()
    bd["by"] = bd.birth_date.astype(str).str[:4]
    uniq = bd.groupby(["horse_name", "by"]).birth_date.agg(["nunique", "first"]).reset_index()
    uniq = uniq[uniq["nunique"] == 1]
    um = {(a, b): c for a, b, c in zip(uniq.horse_name, uniq.by, uniq["first"])}
    fill = []
    for nm, b, y in zip(hs.horse_name, hs.birth_date, hs.birth_year):
        if isinstance(b, str) and b:
            fill.append(b)
        else:
            yy = str(int(y)) if pd.notna(y) and str(y).strip() not in ("", "None") else None
            fill.append(um.get((nm, yy)) if yy else None)
    hs["birth_date"] = fill
    hs = hs.dropna(subset=["birth_date"])
    out = jr.merge(hs[["kb_horse_id", "horse_name", "birth_date"]], on="kb_horse_id", how="inner")
    return out[["horse_name", "birth_date", "race_date", "place", "finish_note"]]


# ---------- クラスの読み方(サイトの規則を書き直したもの) ----------
_Z = str.maketrans("ＡＢＣ０１２３４５６７８９", "ABC0123456789")
_KN = {"一": "1", "二": "2", "三": "3"}
_LETTER_ONLY = {"名古屋", "笠松"}
_ALPHA = "A-Za-zＡ-Ｚａ-ｚ"


def klass(race_name, track, race_kind):
    t = str(race_name or "").translate(_Z)
    if str(race_kind or "") in ("重賞", "準重賞") or "オープン" in t:
        if re.search(r"[23]歳", t) and not re.search(r"[34]歳以上|[34]歳上|[34]上", t):
            return "OPy"
        return "OP"
    mm = re.search(rf"(?<![{_ALPHA}])([ABC])・?([ABC])(?=混合|級)", t)
    if mm and mm.group(1) != mm.group(2):
        return "".join(sorted(mm.group(1) + mm.group(2)))
    m = re.search(rf"(?<![{_ALPHA}])([ABC])(?:\s?([0-9一二三])|(?![{_ALPHA}]))", t)
    if m:
        n = m.group(2) or ""
        return m.group(1) if track in _LETTER_ONLY else m.group(1) + _KN.get(n, n)
    if re.search(r"2歳|２歳", t):
        return "2y"
    if re.search(r"[34]歳以上|[34]歳上|[34]上", t):
        return None
    if re.search(r"3歳|３歳", t):
        return "3y"
    return None


def coarse(k):
    return "*" + k[0] if k and re.fullmatch(r"[ABC][0-9]?", k) else None


def timeband(pt):
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})", str(pt or "").strip())
    if not m:
        return None
    hm = int(m.group(1)) * 60 + int(m.group(2))
    return "昼" if hm < 16 * 60 else ("夕方" if hm < 18 * 60 else "夜")


def norm_jockey(s):
    if not isinstance(s, str):
        return None
    s = re.sub(r"[\s　▲△☆◇★]", "", s)
    return s or None


# ---------- 集計の道具 ----------
def r1(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x) * 100, 1)


def summ(df):
    n = int(len(df))
    if n == 0:
        return {"n": 0, "win": None, "top3": None, "ratio": None, "n_pop": 0}
    pp = df[df.exp.notna()]
    ratio = round(float(pp.top3.sum() / pp.exp.sum()), 2) if len(pp) and pp.exp.sum() > 0 else None
    return {"n": n, "win": r1(df.win.mean()), "top3": r1(df.top3.mean()), "ratio": ratio, "n_pop": int(len(pp))}


def by(df, keys, order=None):
    out = {}
    for k, g in df.groupby(keys, sort=True, observed=True):
        out[k if isinstance(k, str) else "|".join(map(str, k if isinstance(k, tuple) else (k,)))] = summ(g)
    if order:
        out = {k: out[k] for k in order if k in out}
    return out


def gap_label(g):
    for a, b in GAP_BINS:
        if a <= g <= b:
            return f"{a}〜{b}" if b < 99999 else f"{a}以上"
    return None


def wc_label(w):
    for a, b, nm in WC_BINS:
        if a <= w <= b:
            return nm
    return None


GAP_ORDER = [f"{a}〜{b}" if b < 99999 else f"{a}以上" for a, b in GAP_BINS]
WC_ORDER = [nm for _, _, nm in WC_BINS]
K_ORDER = ["1走目", "2走目", "3走目", "4走目以降", "移籍なし"]


# ---------- 本体の集計 ----------
def prepare(runs, races, jra):
    runs = runs.copy()
    runs["race_date"] = runs.race_date.astype(str).str[:10]
    runs["race_no"] = pd.to_numeric(runs.race_no).astype(int)
    runs["runner_number"] = pd.to_numeric(runs.runner_number).astype(int)
    for c in ("gate", "finish", "popularity", "body_weight", "body_weight_change", "time_sec"):
        runs[c] = pd.to_numeric(runs[c], errors="coerce")
    runs["finish_note"] = runs.finish_note.where(runs.finish_note.notna(), None)
    runs["birth_date"] = runs.birth_date.where(runs.birth_date.notna(), None)
    runs["start"] = ~runs.finish_note.isin(DROP_NOTES)
    races = races.copy()
    races["race_date"] = races.race_date.astype(str).str[:10]
    races["race_no"] = pd.to_numeric(races.race_no).astype(int)
    races["distance_m"] = pd.to_numeric(races.distance_m, errors="coerce")
    races = races.drop_duplicates(["track", "race_date", "race_no"])

    # 前走の鎖(地方の実走+中央)
    loc = runs[runs.start & runs.horse_name.notna()].copy()
    loc["key"] = loc.horse_name.astype(str) + "|" + loc.birth_date.fillna("").astype(str)
    loc["area"] = loc.track.map(AREA)
    loc["src"] = "L"
    if "trainer_area" not in loc:
        loc["trainer_area"] = None
    loc["aff"] = [aff_of(t, v) for t, v in zip(loc.trainer_area, loc.track)]
    aff_values = loc.trainer_area.fillna("(空)").value_counts().head(40).to_dict()
    aff_null = int(loc.trainer_area.isna().sum())
    ch = loc[["key", "race_date", "area", "aff", "src", "track", "race_no", "runner_number", "jockey",
              "body_weight"]].copy()
    n_jra_used = 0
    if jra is not None and len(jra):
        j = jra[~jra.finish_note.isin(DROP_NOTES)].copy()
        j["race_date"] = j.race_date.astype(str).str[:10]
        j["key"] = j.horse_name.astype(str) + "|" + j.birth_date.astype(str)
        j["area"] = [AREA.get(str(p), "中央") if str(p) in VENUES else "中央" for p in j.place]
        j["src"] = "J"
        j["aff"] = "中央"
        j = j[["key", "race_date", "area", "aff", "src"]]
        ch = pd.concat([ch, j], ignore_index=True)
    ch["srank"] = (ch.src == "J").astype(int)
    ch = ch.sort_values(["key", "race_date", "srank", "race_no"]).drop_duplicates(["key", "race_date"], keep="first")
    n_jra_used = int((ch.src == "J").sum())
    g = ch.groupby("key", sort=False)
    for c in ("race_date", "area", "aff", "src", "jockey", "body_weight"):
        ch["p_" + c] = g[c].shift(1)
    ch["gap"] = (pd.to_datetime(ch.race_date) - pd.to_datetime(ch.p_race_date)).dt.days
    ch["chg"] = ch.p_aff.notna() & (ch.aff != ch.p_aff)          # T5= 所属地区が変わった走
    ch["grp"] = ch.groupby("key", sort=False).chg.cumsum()
    ch["k"] = ch.groupby(["key", "grp"], sort=False).cumcount() + 1
    ch["from_area"] = ch.groupby(["key", "grp"], sort=False).p_aff.transform("first")
    chl = ch[ch.src == "L"][["track", "race_date", "race_no", "runner_number", "key", "p_race_date", "p_area",
                             "p_src", "p_jockey", "p_body_weight", "gap", "grp", "k", "from_area", "area", "aff", "p_aff"]]

    # 集計の対象の走(期間・取消除外を外す・不成立を外す)
    st = runs[(runs.race_date >= P0.isoformat()) & (runs.race_date <= P1.isoformat())].copy()
    won = st[st.finish == 1].groupby(["track", "race_date", "race_no"]).size().rename("n_win").reset_index()
    n_runs_all = len(st)
    st = st[st.start]
    st = st.merge(won, on=["track", "race_date", "race_no"], how="inner")
    st["fs"] = st.groupby(["track", "race_date", "race_no"]).runner_number.transform("size")
    st["win"] = (st.finish == 1).astype(int)
    st["top2"] = st.finish.between(1, 2).astype(int)
    st["top3"] = st.finish.between(1, 3).astype(int)
    exp = st[st.popularity.notna()].groupby(["track", "popularity"]).top3.mean().rename("exp").reset_index()
    st = st.merge(exp, on=["track", "popularity"], how="left")
    st = st.merge(races, on=["track", "race_date", "race_no"], how="left")
    st = st.merge(chl, on=["track", "race_date", "race_no", "runner_number"], how="left")
    meta = {"走(期間・全行)": int(n_runs_all), "集計の走": int(len(st)),
            "集計のレース": int(st[["track", "race_date", "race_no"]].drop_duplicates().shape[0]),
            "生年月日なしの走": int(st.birth_date.isna().sum()), "中央の走(鎖に入った行)": n_jra_used,
            "前走の無い走(初出走など)": int(st.p_race_date.isna().sum()),
            "aff_null(trainer_area が空の地方の走・期間外も含む)": aff_null,
            "aff_values": {str(k): int(v) for k, v in aff_values.items()}}
    return runs, races, st, meta


def t1(st, facts):
    fav = st[st.popularity == 1].copy()
    nfav = fav.groupby(["track", "race_date", "race_no"]).size()
    rc = st.drop_duplicates(["track", "race_date", "race_no"])
    out = {"ties_races": int((nfav > 1).sum()), "ties_runs": int(nfav[nfav > 1].sum()),
           "races_without_fav": int(len(rc) - len(nfav)), "venues": {}, "fieldsize": {}}
    fav["fsb"] = np.where(fav.fs <= 8, "8頭以下", np.where(fav.fs <= 10, "9〜10頭", "11頭以上"))
    fav["yr"] = np.where(fav.race_date < Y2.isoformat(), "1年目", "2年目")
    for v in VENUES:
        g = fav[fav.track == v]
        r = rc[rc.track == v]
        if not len(g):
            continue
        out["venues"][v] = {"n": int(len(g)), "win": r1(g.win.mean()), "top2": r1(g.top2.mean()),
                            "top3": r1(g.top3.mean()), "avg_field": round(float(r.fs.mean()), 2),
                            "races": int(len(r)),
                            "by_year": {y: {"n": int(len(h)), "win": r1(h.win.mean())} for y, h in g.groupby("yr")}}
        out["fieldsize"][v] = {b: {"n": int(len(h)), "win": r1(h.win.mean())} for b, h in g.groupby("fsb")}
    out["all"] = {"n": int(len(fav)), "win": r1(fav.win.mean()), "top2": r1(fav.top2.mean()),
                  "top3": r1(fav.top3.mean())}
    return out


def t2(st):
    rc = st.drop_duplicates(["track", "race_date", "race_no"])
    cnt = rc.groupby(["track", "distance_m"]).size()
    keep = cnt[cnt >= 100]
    s = st.copy()
    s["pos"] = np.where(s.runner_number <= s.fs / 3, "内", np.where(s.runner_number > s.fs * 2 / 3, "外", "中"))

    def pos_tab(g):
        return {p: {"n": int(len(h)), "top3": r1(h.top3.mean()), "win": r1(h.win.mean())}
                for p, h in g.groupby("pos")}
    out = {"by_dist": [], "by_venue": {}}
    for (v, d), nrace in keep.items():
        g = s[(s.track == v) & (s.distance_m == d)]
        gg = g[g.gate.between(1, 8)]
        out["by_dist"].append({"venue": v, "dist": int(d), "races": int(nrace),
                               "gate": {int(k): {"n": int(len(h)), "top3": r1(h.top3.mean())}
                                        for k, h in gg.groupby("gate")},
                               "pos": pos_tab(g)})
    out["by_dist"].sort(key=lambda x: (VENUES.index(x["venue"]), x["dist"]))
    for v in VENUES:
        g = s[s.track == v]
        if len(g):
            out["by_venue"][v] = pos_tab(g)
    return out


def race_baba(runs, races):
    """T3 の材料= 期間のレースごとの「ふだんとの差(秒)」。戻り= DataFrame(track, race_date, race_no, v)"""
    rm = races.set_index(["track", "race_date", "race_no"])
    smp = runs[runs.finish.between(1, 5) & runs.time_sec.notna() & runs.finish_note.isna()][
        ["track", "race_date", "race_no", "finish", "time_sec"]].copy()
    smp = smp.sort_values("time_sec").drop_duplicates(["track", "race_date", "race_no", "finish"])
    smp = smp.join(rm[["distance_m", "race_name", "race_kind", "going"]], on=["track", "race_date", "race_no"])
    smp = smp[smp.distance_m.notna()]
    smp["band"] = [klass(a, t, b) for a, t, b in zip(smp.race_name, smp.track, smp.race_kind)]
    smp["ord"] = pd.to_datetime(smp.race_date).map(lambda x: x.toordinal())
    smp["finish"] = smp.finish.astype(int)
    smp["distance_m"] = smp.distance_m.astype(int)
    base = smp[smp.going == "良"].sort_values("ord")
    idx = {}
    for t, d, b, f, o, tm in zip(base.track, base.distance_m, base.band, base.finish, base.ord, base.time_sec):
        ks = [("d", t, d, f)]
        if b:
            ks.append(("b", t, d, b, f))
            if coarse(b):
                ks.append(("c", t, d, coarse(b), f))
        for k in ks:
            e = idx.setdefault(k, ([], []))
            e[0].append(o)
            e[1].append(float(tm))
    idx = {k: (np.array(a), np.array(b)) for k, (a, b) in idx.items()}
    cache = {}

    def med(k, o):
        ck = (k, o)
        if ck in cache:
            return cache[ck]
        e = idx.get(k)
        m = None
        if e is not None:
            i = bisect.bisect_left(e[0], o - 365)
            j = bisect.bisect_left(e[0], o)
            if j - i >= 8:
                m = float(np.median(e[1][i:j]))
        cache[ck] = m
        return m

    tgt = smp[(smp.race_date >= P0.isoformat()) & (smp.race_date <= P1.isoformat()) & smp.band.notna()]
    out, stage = [], [0, 0, 0]
    for (t, ds, rno), g in tgt.groupby(["track", "race_date", "race_no"], sort=False):
        diffs = []
        for d, b, f, o, tm in zip(g.distance_m, g.band, g.finish, g.ord, g.time_sec):
            for si, k in enumerate((("b", t, d, b, f), ("c", t, d, coarse(b), f) if coarse(b) else None,
                                    ("d", t, d, f))):
                if k is None:
                    continue
                m = med(k, o)
                if m is not None:
                    diffs.append(float(tm) - m)
                    stage[si] += 1
                    break
        if len(diffs) >= 3:
            out.append((t, ds, int(rno), float(np.median(diffs))))
    return pd.DataFrame(out, columns=["track", "race_date", "race_no", "v"]), stage


def t3(runs, races, st):
    rb, stage = race_baba(runs, races)
    rc = st.drop_duplicates(["track", "race_date", "race_no"])[["track", "race_date", "race_no", "post_time",
                                                                "going", "race_name", "race_kind"]].copy()
    rc["tb"] = rc.post_time.map(timeband)
    rc["band"] = [klass(a, t, b) for a, t, b in zip(rc.race_name, rc.track, rc.race_kind)]
    miss = {v: int(((rc.track == v) & rc.tb.isna()).sum()) for v in VENUES}
    x = rc.merge(rb, on=["track", "race_date", "race_no"], how="inner")
    out = {"races_total": int(len(rc)), "races_no_class": int(rc.band.isna().sum()),
           "races_with_value": int(len(x)), "post_time_missing": miss,
           "post_time_missing_total": int(sum(miss.values())),
           "value_no_time": int(x.tb.isna().sum()),
           "stage_counts": {"クラス": stage[0], "字だけのクラス": stage[1], "場×距離": stage[2]},
           "by_venue_band": {}, "season": {}}
    x = x[x.tb.notna()].copy()
    for (v, b), g in x.groupby(["track", "tb"]):
        out["by_venue_band"].setdefault(v, {})[b] = {"n": int(len(g)), "mean": round(float(g.v.mean()), 3),
                                                     "median": round(float(g.v.median()), 3)}
    x["ym"] = x.race_date.str[:7]
    x["gcls"] = np.where(x.going == "良", "良", np.where(x.going.fillna("").astype(str).str.len() > 0, "良以外", None))
    pairs = [("夜", "昼"), ("夕方", "昼"), ("夜", "夕方")]

    def seasonal(df, extra):
        res = {}
        agg = df.groupby(["track", "ym"] + extra + ["tb"]).v.agg(["size", "mean"]).reset_index()
        for a, b in pairs:
            A = agg[agg.tb == a].drop(columns="tb")
            B = agg[agg.tb == b].drop(columns="tb")
            j = A.merge(B, on=["track", "ym"] + extra, suffixes=("_a", "_b"))
            j = j[(j.size_a >= 10) & (j.size_b >= 10)]
            j["d"] = j.mean_a - j.mean_b
            j["w"] = j.size_a + j.size_b
            key = f"{a}−{b}"
            grp_keys = ["track"] + extra
            sub = {}
            for k, h in j.groupby(grp_keys):
                k = k if isinstance(k, tuple) else (k,)
                sub["|".join(map(str, k))] = {"cells": int(len(h)), "races": int(h.w.sum()),
                                              "diff": round(float((h.d * h.w).sum() / h.w.sum()), 3)}
            tot = {}
            for k, h in (j.groupby(extra) if extra else [("全場", j)]):
                if len(h):
                    tot[k if isinstance(k, str) else "|".join(map(str, k))] = {
                        "cells": int(len(h)), "races": int(h.w.sum()),
                        "diff": round(float((h.d * h.w).sum() / h.w.sum()), 3)}
            res[key] = {"by": sub, "total": tot}
        return res
    out["season"]["all_going"] = seasonal(x, [])
    out["season"]["by_going"] = seasonal(x[x.gcls.notna()], ["gcls"])
    return out


def t4(st):
    s = st[st.gap.notna()].copy()
    s["gb"] = s.gap.astype(int).map(gap_label)
    return {"excluded_first": int(st.gap.isna().sum()), "all": by(s, "gb", GAP_ORDER),
            "by_venue": {v: by(s[s.track == v], "gb", GAP_ORDER) for v in VENUES}}


def t5(st):
    s = st[st.p_race_date.notna()].copy()
    s["cat"] = np.where(s.grp > 0, np.where(s.k >= 4, "4走目以降", s.k.astype(int).astype(str) + "走目"), "移籍なし")
    s["from"] = np.where(s.from_area == "中央", "中央から", "地方から")
    mv = s[s.grp > 0]
    return {"all": by(s, "cat", K_ORDER),
            "moved_by_from": {f: by(mv[mv["from"] == f], "cat", K_ORDER[:4]) for f in ("中央から", "地方から")},
            "control_same_area": summ(s[s.p_aff == s.aff]),
            "control_never_moved": summ(s[s.grp == 0]),
            "first_run_by_from_area": by(s[(s.grp > 0) & (s.k == 1)], "from_area")}


def t6(st):
    s = st[st.p_race_date.notna() & st.body_weight.notna()].copy()
    calc = s.body_weight - pd.to_numeric(s.p_body_weight, errors="coerce")
    calc = calc.where(s.p_src == "L")
    s["wc"] = s.body_weight_change.where(s.body_weight_change.notna(), calc)
    s["wsrc"] = np.where(s.body_weight_change.notna(), "発表", np.where(calc.notna(), "前走との差", None))
    src = s.wsrc.value_counts(dropna=False).to_dict()
    s = s[s.wc.notna()]
    s["wb"] = s.wc.astype(int).map(wc_label)
    return {"source_counts": {str(k): int(v) for k, v in src.items()},
            "all": by(s, "wb", WC_ORDER), "gap41": by(s[s.gap <= 41], "wb", WC_ORDER)}


def t7(st):
    s = st[(st.p_src == "L") & (st.p_area == st.area) & (st.gap <= 62)].copy()
    s["j"] = s.jockey.map(norm_jockey)
    s["pj"] = s.p_jockey.map(norm_jockey)
    s = s[s.j.notna() & s.pj.notna()]
    s["cat"] = np.where(s.j == s.pj, "同じ騎手", "乗り替わり")
    return {"all": by(s, "cat", ["同じ騎手", "乗り替わり"]),
            "by_venue": {v: by(s[s.track == v], "cat", ["同じ騎手", "乗り替わり"]) for v in VENUES}}


def check_sample(runs, st):
    rc = st.drop_duplicates(["track", "race_date", "race_no"])
    pick = rc.sample(5, random_state=20261026 + 2)
    out = []
    for _, r in pick.iterrows():
        g = runs[(runs.track == r.track) & (runs.race_date == r.race_date) & (runs.race_no == r.race_no)]
        g = g.sort_values("runner_number")
        d = dtm.date.fromisoformat(r.race_date)
        out.append({"venue": r.track, "date": r.race_date, "race_no": int(r.race_no), "post_time": r.post_time,
                    "url": "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate="
                           + enc(d.strftime("%Y/%m/%d")) + f"&k_raceNo={int(r.race_no)}&k_babaCode={BABA_CODE[r.track]}",
                    "runners": [{"no": int(x.runner_number), "gate": None if pd.isna(x.gate) else int(x.gate),
                                 "pop": None if pd.isna(x.popularity) else int(x.popularity),
                                 "fin": None if pd.isna(x.finish) else int(x.finish), "note": x.finish_note,
                                 "wc": None if pd.isna(x.body_weight_change) else int(x.body_weight_change)}
                                for x in g.itertuples()]})
    return out


def compute(runs, races, facts, jra, notes):
    runs, races, st, meta = prepare(runs, races, jra)
    res = {"meta": meta, "notes": notes, "decisions": DECISIONS}
    res["T1"] = t1(st, facts)
    res["T2"] = t2(st)
    res["T3"] = t3(runs, races, st)
    res["T4"] = t4(st)
    res["T5"] = t5(st)
    res["T6"] = t6(st)
    res["T7"] = t7(st)
    res["check"] = check_sample(runs, st)
    return res


# ---------- Markdown ----------
def md(res):
    L = []
    say = L.append

    def table(cols, rows):
        say("| " + " | ".join(cols) + " |")
        say("|" + "---|" * len(cols))
        for r in rows:
            say("| " + " | ".join("—" if x is None else str(x) for x in r) + " |")
        say("")

    def srow(name, s):
        return [name, s["n"], s["win"], s["top3"], s["ratio"]]
    SC = ["区分", "走数", "勝率%", "3着内率%", "人気比"]
    say("# 言い伝えをデータで確かめる 集計 実装 B\n")
    say(f"期間 {P0}〜{P1}・地方 14 場。台本 nar-jobs cloud/research_lore_b.py。\n")
    say("## 決めたこと(約束に無い所)\n")
    for d in res["decisions"]:
        say("- " + d)
    say("")
    say("## 材料\n")
    table(["項目", "値"], [[k, v] for k, v in list(res["meta"].items()) + list(res["notes"].items())])

    T = res["T1"]
    say("## T1 1番人気がいちばん勝つ場は\n")
    say(f"同率で 1 番人気が 2 頭以上のレース {T['ties_races']}(その走 {T['ties_runs']})・1 番人気のいないレース {T['races_without_fav']}。\n")
    rows = []
    for v, x in sorted(T["venues"].items(), key=lambda kv: -(kv[1]["win"] or 0)):
        rows.append([v, x["n"], x["win"], x["top2"], x["top3"], x["avg_field"],
                     x["by_year"].get("1年目", {}).get("win"), x["by_year"].get("2年目", {}).get("win")])
    a = T["all"]
    rows.append(["全場", a["n"], a["win"], a["top2"], a["top3"], "", "", ""])
    table(["場", "1番人気の走数", "勝率%", "2着内率%", "3着内率%", "平均頭数",
           "1年目勝率%", "2年目勝率%"], rows)
    say("頭数別の勝率%(走数)\n")
    fb = ["8頭以下", "9〜10頭", "11頭以上"]
    table(["場"] + fb, [[v] + [f"{T['fieldsize'][v][b]['win']}({T['fieldsize'][v][b]['n']})"
                              if b in T["fieldsize"][v] else "—" for b in fb] for v in VENUES if v in T["fieldsize"]])

    T = res["T2"]
    say("## T2 内枠は有利か\n")
    say("### 場ごと(全距離)内・中・外\n")
    rows = []
    for v, p in T["by_venue"].items():
        rows.append([v] + sum([[p.get(k, {}).get("n"), p.get(k, {}).get("top3"), p.get(k, {}).get("win")]
                               for k in ("内", "中", "外")], []))
    table(["場", "内 走数", "内 3着内%", "内 勝率%", "中 走数", "中 3着内%", "中 勝率%", "外 走数", "外 3着内%", "外 勝率%"], rows)
    say("### 場×距離(100 レース以上)内・中・外\n")
    rows = []
    for x in T["by_dist"]:
        p = x["pos"]
        rows.append([x["venue"], x["dist"], x["races"]] + sum(
            [[p.get(k, {}).get("n"), p.get(k, {}).get("top3"), p.get(k, {}).get("win")] for k in ("内", "中", "外")], []))
    table(["場", "距離", "レース", "内 走数", "内 3着内%", "内 勝率%", "中 走数", "中 3着内%", "中 勝率%", "外 走数",
           "外 3着内%", "外 勝率%"], rows)
    say("### 場×距離 枠番ごとの 3 着内率%(走数)\n")
    rows = []
    for x in T["by_dist"]:
        rows.append([x["venue"], x["dist"]] + [f"{x['gate'][k]['top3']}({x['gate'][k]['n']})" if k in x["gate"] else "—"
                                              for k in range(1, 9)])
    table(["場", "距離"] + [f"{k}枠" for k in range(1, 9)], rows)

    T = res["T3"]
    say("## T3 ナイターは時計が速いか\n")
    say(f"レース {T['races_total']:,}・クラスが読めない {T['races_no_class']:,}・値が出た {T['races_with_value']:,}"
        f"(うち発走時刻なし {T['value_no_time']:,})。基準の段の本数= {T['stage_counts']}。\n")
    say("発走時刻の欠け(レース数)= " + "・".join(f"{v} {n}" for v, n in T["post_time_missing"].items())
        + f"・計 {T['post_time_missing_total']}\n")
    rows = []
    for v in VENUES:
        for b in ("昼", "夕方", "夜"):
            x = T["by_venue_band"].get(v, {}).get(b)
            if x:
                rows.append([v, b, x["n"], x["mean"], x["median"]])
    table(["場", "時間帯", "レース数", "差の平均(秒)", "差の中央値(秒)"], rows)
    for nm, key in (("馬場状態を問わず", "all_going"), ("馬場状態別", "by_going")):
        say(f"### 季節をそろえた比べ({nm}・場×月で両方 10 レース以上)\n")
        rows = []
        for pr, x in T["season"][key].items():
            for k, y in x["total"].items():
                rows.append([pr, "合計", k, y["cells"], y["races"], y["diff"]])
            for k, y in x["by"].items():
                rows.append([pr, k.split("|")[0], "|".join(k.split("|")[1:]) or "", y["cells"], y["races"], y["diff"]])
        table(["比べ", "場", "馬場", "場×月の数", "レース数", "重み付き平均の差(秒)"], rows)

    T = res["T4"]
    say("## T4 休み明けはどのくらい走るか\n")
    say(f"初出走(前走なし)で外した走 {T['excluded_first']:,}。\n")
    table(SC, [srow(k, s) for k, s in T["all"].items()])
    say("### 場ごと(走数/勝率%/3着内率%/人気比)\n")
    table(["場"] + GAP_ORDER, [[v] + [f"{T['by_venue'][v][g]['n']}/{T['by_venue'][v][g]['win']}/{T['by_venue'][v][g]['top3']}/"
                                      f"{T['by_venue'][v][g]['ratio']}" if g in T["by_venue"][v] else "—"
                                      for g in GAP_ORDER] for v in VENUES])

    T = res["T5"]
    say("## T5 移籍初戦はどのくらい走るか\n")
    table(SC, [srow(k, s) for k, s in T["all"].items()]
          + [srow("比べ相手= 前走も同じ地区", T["control_same_area"]), srow("比べ相手= 移籍なし", T["control_never_moved"])])
    for f, x in T["moved_by_from"].items():
        say(f"### {f}\n")
        table(SC, [srow(k, s) for k, s in x.items()])
    say("### 1 走目の前の地区ごと\n")
    table(SC, [srow(k, s) for k, s in T["first_run_by_from_area"].items()])

    T = res["T6"]
    say("## T6 馬体重が大きく増えたら\n")
    say("増減の出どころ= " + "・".join(f"{k} {v:,}" for k, v in T["source_counts"].items()) + "\n")
    say("### 全走\n")
    table(SC, [srow(k, s) for k, s in T["all"].items()])
    say("### 間隔 41 日以内の走だけ\n")
    table(SC, [srow(k, s) for k, s in T["gap41"].items()])

    T = res["T7"]
    say("## T7 乗り替わりはどのくらい響くか\n")
    table(SC, [srow(k, s) for k, s in T["all"].items()])
    rows = []
    for v in VENUES:
        x = T["by_venue"][v]
        rows.append([v] + sum([[x.get(c, {}).get("n"), x.get(c, {}).get("win"), x.get(c, {}).get("top3"),
                                x.get(c, {}).get("ratio")] for c in ("同じ騎手", "乗り替わり")], []))
    table(["場", "同じ 走数", "同じ 勝率%", "同じ 3着内%", "同じ 人気比", "替わり 走数", "替わり 勝率%", "替わり 3着内%",
           "替わり 人気比"], rows)

    say("### T5 の所属の値(trainer_area・上位 40)\n")
    table(["trainer_area", "地方の走"], [[k, v] for k, v in res["meta"]["aff_values"].items()])
    say("## 公式との照合(選んだ 5 レースの DB の値)\n")
    for c in res["check"]:
        say(f"### {c['venue']} {c['date']} {c['race_no']}R 発走 {c['post_time']}\n")
        say(c["url"] + "\n")
        table(["馬番", "枠番", "人気", "着順", "注記", "増減"],
              [[r["no"], r["gate"], r["pop"], r["fin"], r["note"] or "", r["wc"]] for r in c["runners"]])
    return "\n".join(L) + "\n"


def write(res, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "lore.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md(res))


# ---------- 作り物の試験 ----------
def selftest():
    rng = np.random.default_rng(1)
    runs, races = [], []
    horses = [f"馬{i}" for i in range(60)]
    d0 = dtm.date(2023, 9, 1)
    for di in range(0, 1100, 3):
        d = (d0 + dtm.timedelta(days=di)).isoformat()
        for v in ("高知", "大井"):
            for rno in range(1, 6):
                n = 8 + rno % 4
                races.append({"track": v, "race_date": d, "race_no": rno, "distance_m": 1400,
                              "race_name": "Ｃ３－１", "going": "良" if rno % 2 else "重", "race_kind": None,
                              "post_time": ["1450", "16:30", "1900", "", "2010"][rno - 1]})
                hs = rng.choice(horses, n, replace=False)
                fin = rng.permutation(n) + 1
                pop = rng.permutation(n) + 1
                for i in range(n):
                    note = "出走取消" if (i == 0 and rno == 3 and di % 9 == 0) else None
                    runs.append({"track": v, "race_date": d, "race_no": rno, "runner_number": i + 1,
                                 "gate": min(8, i + 1), "horse_name": hs[i], "birth_date": "2020-04-01",
                                 "jockey": ["▲甲", "乙", "丙"][i % 3], "body_weight": 450 + int(rng.integers(-15, 15)),
                                 "body_weight_change": None if i % 5 == 0 else int(rng.integers(-25, 25)),
                                 "finish": None if note else int(fin[i]), "finish_note": note,
                                 "time_sec": 88 + fin[i] * 0.3 + rng.normal(0, .5), "popularity": int(pop[i])})
    runs, races = pd.DataFrame(runs), pd.DataFrame(races)
    jra = pd.DataFrame([{"horse_name": "馬1", "birth_date": "2020-04-01", "race_date": "2024-12-02",
                         "place": "東京", "finish_note": None}])
    fr = runs[(runs.track == "高知") & (runs.popularity == 1) & runs.finish.notna()].iloc[-1]
    facts = pd.DataFrame([{"track": "高知", "race_date": fr.race_date, "race_no": int(fr.race_no),
                           "umaban": int(fr.runner_number), "win_odds_close": 2.5}])
    # map_jra の試験
    hs = pd.DataFrame([{"kb_horse_id": 1, "horse_name": "馬2", "birth_date": None, "birth_year": 2020},
                       {"kb_horse_id": 2, "horse_name": "無い馬", "birth_date": None, "birth_year": 2020}])
    jr = pd.DataFrame([{"kb_horse_id": 1, "kb_race_id": 9, "race_date": "2025-01-05", "place": "中山", "finish_note": None},
                       {"kb_horse_id": 2, "kb_race_id": 9, "race_date": "2025-01-05", "place": "中山", "finish_note": None}])
    mj = map_jra(hs, jr, runs)
    assert len(mj) == 1 and mj.birth_date.iloc[0] == "2020-04-01", mj
    assert klass("Ｃ３－１", "高知", None) == "C3" and klass("Ｃ１５組", "名古屋", None) == "C"
    assert klass("ＪＲＡ認定２歳", "門別", None) == "2y" and klass("Ａ・Ｂ混合", "大井", None) == "AB"
    assert klass("一般", "大井", "重賞") == "OP" and klass("3歳以上", "大井", None) is None
    assert timeband("1559") == "昼" and timeband("16:00") == "夕方" and timeband("1800") == "夜" and timeband("") is None
    assert gap_label(13) == "1〜13" and gap_label(366) == "366以上" and wc_label(-10) == "−10以下" and wc_label(3) == "−3〜+3"
    assert norm_jockey("▲ 甲") == "甲"
    res = compute(runs, races, facts, jra, {"test": 1})
    assert res["T1"]["venues"]["高知"]["n"] > 0
    assert aff_of("愛知", "大井") == "東海" and aff_of(None, "大井") == "南関東" and aff_of("JRA", "高知") == "中央"
    assert res["T3"]["post_time_missing_total"] > 0 and res["T3"]["races_with_value"] > 0
    assert res["meta"]["中央の走(鎖に入った行)"] == 1
    assert sum(x["n"] for x in res["T4"]["all"].values()) + res["T4"]["excluded_first"] == res["meta"]["集計の走"]
    # 人気比: 全走で 1.00
    s = sum(x["n"] for x in res["T7"]["all"].values())
    assert s > 0
    write(res, os.path.join(ROOT, "out", "B_selftest"))
    log("selftest ok " + json.dumps(res["meta"], ensure_ascii=False))
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    t0 = time.time()
    runs, races, facts, jra, notes = load(Rest(base, key))
    log(f"読み終わり {time.time() - t0:.0f}s 走 {len(runs):,} レース {len(races):,} 中央 {len(jra):,}")
    res = compute(runs, races, facts, jra, notes)
    res["meta"]["実行秒"] = int(time.time() - t0)
    write(res)
    log("書いた " + OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())

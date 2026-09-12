# -*- coding: utf-8 -*-
"""本体 cloud: 馬場差の全15場一括計算(DESIGN §48 K-1b)。

公式の勝ち時計(nar_runs.time_sec, finish=1)を「場×距離×クラス帯の**過去3年**中央値」と比べ、
**日×場の中央値**を馬場差(秒)として nar_meta `baba_diff` に入れる。マイナス=速い馬場。

  出力 = {"built":"YYYY-MM-DD",
          "days": {"2026-08-28": {"ooi": {"d": -0.8, "n": 9}, …}, …}}   # 直近90日+当日
  - ⚠その日の対象レースが4本未満の場は出さない(小サンプルから言わない)
  - ⚠帯広ばは対象外(#111: ばんえいは馬場の型が違う。水分率が公式にある)
  - クラス帯は race_name の粗い抽出(Ａ/Ｂ/Ｃ+数字・2歳/3歳)。抽出できない走は場×距離の全体中央値に落とす
    (帯を捏造しない)。帯の基準は標本8本以上のときだけ使う

  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar            # ドライラン(集計と検証だけ)
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --verify   # +公式の馬場状態(going)との相関
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --apply    # nar_meta へ upsert
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ(#8): 全取得はページングで回す。⛔updated_at を必ず送る(#155)。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
import urllib.request

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
WINDOW_DAYS = 90        # blob に載せる日数(⛔§104 でも変えない= 出す日数と標準の窓は別物)
# 標準(場×距離×クラス帯の中央値)を作る窓。⛔2026-09-05 ユーザーFB「1年では弱い」で 365→1095 日。
# ⛔標準に**馬場状態を入れない**= 馬場差は「その日の馬場でどれだけ速かったか」を測るものなので、
#   良/不良で標準を分けると測りたいものが消える(不良の日が不良の標準と比べられて 0 になる)。
STD_DAYS = 1095

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


def rows_all(base, key, path):
    out, off = [], 0
    while True:
        _, body = req(base, key, f"{path}&limit=1000&offset={off}")
        c = json.loads(body)
        out.extend(c)
        if len(c) < 1000:
            return out
        off += 1000


# §104 2026-09-05(Fable・要判断①=a): 名古屋・笠松の公式クラスは Ａ級/Ｂ級/Ｃ級の3つだけで、レース名の数字は
# 「組」(Ｃ１５組=Ｃ級15組)。数字まで拾うと帯が 17 行に割れ「Ｃ１５」が Ｃ1 に化けるので、東海2場は字だけに丸める
LETTER_ONLY_TRACKS = {"名古屋", "笠松"}


def band_of(race_name, track=None):
    """クラス帯の粗い抽出。取れなければ None(=場×距離の全体基準に落ちる)。track が東海2場なら字だけ"""
    t = str(race_name or "").translate(Z)
    # ⛔前後に英字(全角含む=Z はＡＢＣしか半角化しない)が続く A/B/C は級ではない
    #   (「ＪＲＡ認定」「ＪＢＣ」「ＢＡＯＯ」等の英字を拾って2歳戦がA級に混ざる)。
    #   数字が続けば級(「Ａ１Ａ２」は従来どおり A1)・続かなければ直後も英字でないこと
    m = re.search(r"(?<![A-Za-zＡ-Ｚａ-ｚ])([ABC])(?:\s?([0-9一二三])|(?![A-Za-zＡ-Ｚａ-ｚ]))", t)
    if m:
        return m.group(1) if track in LETTER_ONLY_TRACKS else m.group(1) + (m.group(2) or "")
    if re.search(r"2歳|２歳", t):
        return "2y"
    if re.search(r"3歳|３歳", t):
        return "3y"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="公式の馬場状態(going)との相関を出す")
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    today = dt.date.today()
    since = (today - dt.timedelta(days=STD_DAYS)).isoformat()
    # 標準を作る窓ぶんの勝ち時計と、レース属性(距離・クラス・馬場状態)
    wins = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,time_sec"
                               f"&finish=eq.1&time_sec=not.is.null&race_date=gte.{since}&order=race_date.asc,track.asc,race_no.asc")
    races = rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m,race_name,going"
                                f"&race_date=gte.{since}&order=race_date.asc,track.asc,race_no.asc")
    meta = {(r["track"], r["race_date"], r["race_no"]): r for r in races}
    log(f"勝ち時計 {len(wins)}行 / レース {len(races)}行({since}〜・{STD_DAYS}日)")

    # 基準表: (場, 距離, 帯) と (場, 距離) の中央値
    by_band, by_dist = {}, {}
    samples = []           # (track, date, prefix, dist, band, time)
    for w in wins:
        if w["track"] == BANEI or w["track"] not in TRACK2PREFIX:
            continue
        m = meta.get((w["track"], w["race_date"], w["race_no"]))
        if not m or not m.get("distance_m"):
            continue
        t = float(w["time_sec"])
        d = int(m["distance_m"])
        b = band_of(m.get("race_name"), w["track"])
        by_dist.setdefault((w["track"], d), []).append(t)
        if b:
            by_band.setdefault((w["track"], d, b), []).append(t)
        samples.append((w["track"], w["race_date"], d, b, t, str(m.get("going") or "")))
    med_band = {k: statistics.median(v) for k, v in by_band.items() if len(v) >= MIN_BAND}
    med_dist = {k: statistics.median(v) for k, v in by_dist.items() if len(v) >= MIN_BAND}
    log(f"基準: 帯つき {len(med_band)}口 / 場×距離 {len(med_dist)}口")

    # 日×場の馬場差(直近 WINDOW_DAYS 日+当日)
    lo = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    devs = {}              # (date, track) -> [偏差]
    going_of = {}          # (date, track) -> [going]
    for track, date, d, b, t, going in samples:
        if date < lo:
            continue
        basemed = med_band.get((track, d, b)) if b else None
        if basemed is None:
            basemed = med_dist.get((track, d))
        if basemed is None:
            continue
        devs.setdefault((date, track), []).append(t - basemed)
        going_of.setdefault((date, track), []).append(going)
    days = {}
    for (date, track), xs in sorted(devs.items()):
        if len(xs) < MIN_RACES:
            continue
        days.setdefault(date, {})[TRACK2PREFIX[track]] = {
            "d": round(statistics.median(xs), 1), "n": len(xs)}
    n_cells = sum(len(v) for v in days.values())
    log(f"馬場差: {len(days)}日 / {n_cells}場日(レース{MIN_RACES}本未満の場日は出さない)")

    if a.verify:
        # 自然妥当性: 公式の馬場状態別に馬場差の平均を見る(ダートは湿ると速い=重・不良が負側なら健全)
        buckets = {}
        for (date, track), xs in devs.items():
            if len(xs) < MIN_RACES:
                continue
            gs = [g for g in going_of.get((date, track), []) if g]
            if not gs:
                continue
            g = statistics.mode(gs)
            buckets.setdefault(g, []).append(statistics.median(xs))
        for g in ("良", "稍重", "重", "不良"):
            if g in buckets:
                v = buckets[g]
                log(f"  going={g}: 平均 {statistics.mean(v):+.2f}秒 (場日 {len(v)})")

    if not a.apply:
        sample_day = sorted(days)[-1] if days else None
        log(f"ドライラン(--apply なし)。例 {sample_day}: "
            f"{json.dumps(days.get(sample_day, {}), ensure_ascii=False)}")
        return 0

    value = {"built": today.isoformat(), "days": days}
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": META_KEY, "value": value,
                             "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]).encode("utf-8"))
    log(f"nar_meta/{META_KEY} 更新 {st}({len(days)}日 {n_cells}場日)")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())

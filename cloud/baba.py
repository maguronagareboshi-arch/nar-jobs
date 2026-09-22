# -*- coding: utf-8 -*-
"""本体 cloud: 馬場差の全15場一括計算(DESIGN §48 K-1b)。

公式の勝ち時計(nar_runs.time_sec, finish=1)を「場×距離×クラス帯の**過去3年**中央値」と比べ、
**日×場の中央値**を馬場差(秒)として nar_meta `baba_diff` に入れる。マイナス=速い馬場。

  出力 = {"built":"YYYY-MM-DD", "base":"365"|"season",
          "days": {"2026-08-28": {"ooi": {"d": -0.8, "n": 9}, …}, …}}   # 直近90日+当日
          # まだ終わっていない日(=当日)は {"d":…,"n":…,"p":true}= 暫定。翌朝の便で確定して p が消える

  ⛔as-of(§17 監査 2026-09-22 で「as-of でない」と判定された点の直し)
    日 d の標準は **race_date < d**= その日も、その日より後も標準に入れない。
    さらに **一度確定した日の値は二度と上書きしない**。組み直すのは
      (1) blob にまだ無い日  (2) 前回 "p":true(暫定)で置いた日  (3) 当日
    だけ。--rebuild-all のときだけ全部作り直す(定義を変えたときの作り直し用)。
    昔は標準の窓に上限が無く毎朝 90 日をまるごと組み直していたので、過去の日の値があとから動いていた。

  ⛔当日の値は「その日の**終わったレース**(勝ち時計のある走)だけ」から出した暫定値。
    "p":true が付き、画面は「途中まで」と断って出す(js/ui.js babaWord/babaLabel)。

  標準の窓は2案あり --baseline で切替(既定 365)。⛔どちらを見せるかはユーザー判断。
    365    : [d-365, d)  前日までの直近1年。場の常時オフセット(大井 −0.4 など)の大半が消える
    season : 同じ場の「同じ暦の前後45日」×過去3年(すべて d 未満)。季節の波を標準に入れるので
             「例年のこの時期と比べて」の値になる
  - ⚠その日の対象レースが4本未満の場は出さない(小サンプルから言わない)
  - ⚠帯広ばは対象外(#111: ばんえいは馬場の型が違う。水分率が公式にある)
  - クラス帯は race_name の粗い抽出(Ａ/Ｂ/Ｃ+数字・2歳/3歳)。抽出できない走は場×距離の全体中央値に落とす
    (帯を捏造しない)。帯の基準は標本8本以上のときだけ使う

  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar            # ドライラン(集計と検証だけ)
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --verify   # +公式の馬場状態(going)との相関
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --apply    # nar_meta へ upsert(確定済みの日は据え置き)
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --baseline season   # 季節版で試す
  py -3 -X utf8 cloud/baba.py --env pipeline/.env.nar --apply --rebuild-all  # 全部作り直す
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ(#8): 全取得はページングで回す。⛔updated_at を必ず送る(#155)。
"""
import argparse
import bisect
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
# 標準(場×距離×クラス帯の中央値)を作る窓。⛔2026-09-05 ユーザーFB「1年では弱い」で 365→1095 日にしたが、
# §17 監査(2026-09-22)で「3年フラットだと場の常時オフセットと季節の波をその日の馬場として出してしまう」と
# 分かったので、既定を **前日までの直近365日** に戻した(1095 は STD_DAYS_LEGACY として残す)。
# ⛔標準に**馬場状態を入れない**= 馬場差は「その日の馬場でどれだけ速かったか」を測るものなので、
#   良/不良で標準を分けると測りたいものが消える(不良の日が不良の標準と比べられて 0 になる)。
STD_DAYS = 365
STD_DAYS_LEGACY = 1095   # 旧版(§104)。--baseline 1095 で使える
SEASON_YEARS = 3         # season 版: 何年ぶん遡るか
SEASON_PAD = 45          # season 版: 同じ暦日の前後 何日
BASELINES = ("365", "1095", "season")

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


# ─── as-of の標準づくり ────────────────────────────────────────────────
# ⛔ここから下は「日 d の標準は d より前のレースだけ」を守るための道具。手元の写しでも同じ関数を呼べるよう
#   DB に触らない純関数にしてある(検証= tools/verify_baba_asof.py)。

def fetch_days(baseline):
    """標準を作るのに何日ぶんの勝ち時計を読めばよいか(表示する90日ぶんの一番古い日から見た遡り)"""
    if baseline == "season":
        return 365 * SEASON_YEARS + SEASON_PAD + 30
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
    span = STD_DAYS_LEGACY if baseline == "1095" else STD_DAYS
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


def build_days(samples, targets, baseline, today=None, frozen=None, rebuild_all=False):
    """as-of の馬場差を組む。
      samples  : [(track, date, dist, band, time, going)]  勝ち時計(標準の窓ぶん全部)
      targets  : 出したい日(date 文字列)の集合
      frozen   : 前回の blob の days(確定済みは据え置く)
      戻り     : ({日: {場prefix: {d,n[,p]}}}, 組み直した場日の数, {(日,場): 偏差列})
    ⛔p=true(暫定)= その日がまだ終わっていない(=当日)。終わったレースだけから出した途中の値。
    """
    today = today or dt.date.today()
    frozen = frozen or {}
    by_band_all, by_dist_all = {}, {}
    for track, date, dist, band, t, _g in sorted(samples, key=lambda s: s[1]):
        by_dist_all.setdefault(track, {}).setdefault((dist,), []).append((date, t))
        if band:
            by_band_all.setdefault(track, {}).setdefault((dist, band), []).append((date, t))
    per_day = {}
    for track, date, dist, band, t, _g in samples:
        if date in targets:
            per_day.setdefault((date, track), []).append((dist, band, t))

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
            r = day_cell(rows, by_band_all.get(track, {}), by_dist_all.get(track, {}),
                         dt.date.fromisoformat(date), baseline)
            if not r:
                continue
            cell = {"d": r[0], "n": r[1]}
            if date >= tstr:
                cell["p"] = True        # 当日= 暫定(終わったレースだけ)
            out.setdefault(date, {})[prefix] = cell
            devs_of[(date, track)] = r[2]
            rebuilt += 1
    return out, rebuilt, devs_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="公式の馬場状態(going)との相関を出す")
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--baseline", choices=BASELINES, default="365",
                    help="標準の窓。365=前日までの直近1年(既定) / 1095=旧§104 / season=同じ暦±45日×3年")
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

    today = dt.date.today()
    # ⛔表示する一番古い日(today-90)から見て、その日の標準ぶんまで遡って読む(as-of なので日ごとに窓が動く)
    since = (today - dt.timedelta(days=WINDOW_DAYS + fetch_days(a.baseline))).isoformat()
    wins = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_date,race_no,time_sec"
                               f"&finish=eq.1&time_sec=not.is.null&race_date=gte.{since}&order=race_date.asc,track.asc,race_no.asc")
    races = rows_all(base, key, "/rest/v1/nar_races?select=track,race_date,race_no,distance_m,race_name,going"
                                f"&race_date=gte.{since}&order=race_date.asc,track.asc,race_no.asc")
    meta = {(r["track"], r["race_date"], r["race_no"]): r for r in races}
    log(f"勝ち時計 {len(wins)}行 / レース {len(races)}行({since}〜・標準={a.baseline})")

    samples = []           # (track, date, dist, band, time, going)
    for w in wins:
        if w["track"] == BANEI or w["track"] not in TRACK2PREFIX:
            continue
        m = meta.get((w["track"], w["race_date"], w["race_no"]))
        if not m or not m.get("distance_m"):
            continue
        b = band_of(m.get("race_name"), w["track"])
        samples.append((w["track"], w["race_date"], int(m["distance_m"]), b,
                        float(w["time_sec"]), str(m.get("going") or "")))

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
    days, rebuilt, devs = build_days(samples, targets, a.baseline, today=today,
                                     frozen=frozen, rebuild_all=a.rebuild_all)
    days = {d: v for d, v in days.items() if d >= lo}      # 90日の窓から出た日は落とす
    n_cells = sum(len(v) for v in days.values())
    n_prov = sum(1 for v in days.values() for c in v.values() if c.get("p"))
    log(f"馬場差: {len(days)}日 / {n_cells}場日(組み直し {rebuilt}・暫定 {n_prov}・"
        f"確定済みは据え置き・レース{MIN_RACES}本未満の場日は出さない)")

    if a.verify:
        # 自然妥当性: 公式の馬場状態別に馬場差の平均を見る(ダートは湿ると速い=重・不良が負側なら健全)
        going_of = {}
        for track, date, _d, _b, _t, going in samples:
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
    log(f"nar_meta/{META_KEY} 更新 {st}({len(days)}日 {n_cells}場日・暫定 {n_prov})")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())

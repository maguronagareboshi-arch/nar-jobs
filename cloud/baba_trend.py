# -*- coding: utf-8 -*-
"""統合ビューア cloud: 馬場傾向まとめ(全15場・§100)。

日×場ごとに3つの数と、平年からの外れ具合を言葉にしたものを nar_meta `baba_trend` に入れる。

  時計 t  = cloud/baba.py の馬場差 `nar_meta baba_diff`(秒・マイナス=速い)を**そのまま**読む
  前後 f  = レースごとの Spearman ρ(1番目のコーナーの順位, 着順) → 日の中央値
            ⛔ρ>0= 序盤で前にいた馬ほど着順が良い= 前が止まらない
  内外 io = レースごとの Spearman ρ(枠番 gate, 着順) → 日の中央値
            ⛔ρ>0= 内枠ほど着順が良い= **内が有利**(外が伸びるのは ρ<0 の側)

  出力 = {"built":"2026-09-05T09:10+09:00", "q_built":"2026-09-05",
          "days": {"2026-09-05": {"saga": {"t":-0.3,"tn":6,"f":0.41,"fn":6,"io":-0.02,"ion":6,
                                           "partial":true,"w":["前が止まらない"]}, …}}}
  - 数の無い指標はキーごと省く。`w` は閾値表(上下1割)(pipeline/baba_trend_q.json)のある場だけ。
  - ⛔帯広ばは対象外(#111: コーナーの通過順が無い)。
  - ⛔当日は `partial: true`(まだ終わっていないレースがある)。画面が「ここまでの◯R」と言う材料。

  py -3.12 -X utf8 cloud/baba_trend.py --env pipeline/.env.nar              # ドライラン(直近90日)
  py -3.12 -X utf8 cloud/baba_trend.py --env pipeline/.env.nar --apply      # nar_meta へ upsert
  py -3.12 -X utf8 cloud/baba_trend.py --env pipeline/.env.nar --apply --today  # 当日だけ差す(軽い)
  py -3.12 -X utf8 cloud/baba_trend.py --env pipeline/.env.nar --calibrate  # 閾値表(上下1割)を作り直す(年1回)
  py -3.12 -X utf8 cloud/baba_trend.py --env pipeline/.env.nar --verify     # 検品(§3)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY  ⛔#465: --env が無ければ環境変数だけで動く
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ(#8): 全取得はページング。⛔updated_at を必ず送る(#155)。
⛔通過順の読み方は**3か所目を作らない**= cloud/tenkai.py(§99)の corner_ranks / first_corner を使う。
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
# ⛔§99 の読み方をそのまま使う(3か所目を作らない)。first_corner の中で corner_ranks を呼んでいる
from tenkai import first_corner                          # noqa: E402

UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"
META_KEY = "baba_trend"
BABA_KEY = "baba_diff"
BANEI = "帯広ば"
JST = dt.timezone(dt.timedelta(hours=9))
QPATH = os.path.join(ROOT, "pipeline", "baba_trend_q.json")
CSV_KOCHI = os.path.join(ROOT, "docs", "s100_kochi_rho.csv")
# ⛔cloud/baba.py と同じ表(帯広ばは入っていない)
TRACK2PREFIX = {"門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa",
                "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
                "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji",
                "高知": "kochi", "佐賀": "saga"}

MIN_HORSES = 6          # 1レースで ρ を出す最少頭数
MIN_RACES = 4           # 日の中央値を出す最少レース数
WINDOW_DAYS = 90        # blob に載せる日数
CAL_DAYS = 365          # 閾値表(上下1割)を作る窓
MIN_DAYS_Q = 30         # 上下1割の閾値を出す最少日数(これ未満の場は言葉を出さない)
WINDOW_STEP = 30        # 取得を割る窓(日)。⛔1年を一息に引くと 500 が返る
# 言葉を出す場。⛔--verify のゲートに届かない場はここから外す(主担当が判断)
SHOW_WORDS = set(TRACK2PREFIX.values())
BIAS_PREFIXES = ("monbetsu", "ooi", "funabashi")   # 旧DB {prefix}_stats.corner4_inout がある場


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


N_REQ = [0]


def req(base, key, path, method="GET", body=None, tries=2):
    """⛔Supabase は一時的に 500 を返す(台帳の既知挙動)。GET は1回だけ待って引き直す。"""
    last = None
    for i in range(tries):
        N_REQ[0] += 1
        r = urllib.request.Request(base + path, method=method, data=body, headers={
            "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(r, timeout=180) as x:
                return x.status, x.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last = e
            if method != "GET" or e.code < 500 or i == tries - 1:
                raise
            log("  ⚠ HTTP %d。5秒待って引き直す" % e.code)
            time.sleep(5)
        except urllib.error.URLError as e:
            last = e
            if i == tries - 1:
                raise
            log("  ⚠ 通信に失敗。5秒待って引き直す: %s" % str(e)[:80])
            time.sleep(5)
    raise last


def rows_all(base, key, path):
    """⛔offset で送るので `order=` は**一意**にすること(2026-09-05 実測: race_date だけで並べると
    39,475 行中 1,951 行が重複し、同じだけ抜ける。しかも引くたびに中身が変わる)。"""
    out, off = [], 0
    while True:
        _, body = req(base, key, f"{path}&limit=1000&offset={off}")
        c = json.loads(body)
        out.extend(c)
        if len(c) < 1000:
            return out
        off += 1000


def rows_window(base, key, tmpl, lo, hi, step=WINDOW_STEP):
    """`tmpl` の {lo}/{hi} を **30日の窓**に割って集める。

    ⛔1年ぶんを一息に offset で送ると Supabase が 500 を返す(2026-09-05 実測・--calibrate で発生)。
      窓に割ると1回の走査が浅くなり、深い offset も作らない。
    """
    out = []
    a = dt.date.fromisoformat(lo)
    end = dt.date.fromisoformat(hi)
    while a <= end:
        b = min(a + dt.timedelta(days=step - 1), end)
        out.extend(rows_all(base, key, tmpl.format(lo=a.isoformat(), hi=b.isoformat())))
        a = b + dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------- Spearman(標準ライブラリだけ)

def rankdata(xs):
    """同順位は**平均順位**(ties)。scipy.stats.rankdata(method='average')と同じ"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs, ys):
    """順位相関。分散が0(全部同じ値)なら None= 数えない"""
    n = len(xs)
    if n < 2:
        return None
    rx, ry = rankdata(xs), rankdata(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def quartiles(vals):
    """[下 1 割, 上 1 割](十分位)。⛔標本が MIN_DAYS_Q 未満なら None(小サンプルから閾値を作らない)"""
    v = sorted(x for x in vals if x is not None)
    if len(v) < MIN_DAYS_Q:
        return None
    # ⛔Fable 2026-09-05: 四分位だと 90 日 304 場日の 78% に言葉が付いた(3 指標のどれかが外に出る)。
    #   上下 1 割(十分位)にして「言う日」を減らす。MIN_DAYS_Q も 30 に(1 割= 3 日以上の標本)
    q = statistics.quantiles(v, n=10, method="inclusive")
    return [round(q[0], 2), round(q[8], 2)]


# ---------------------------------------------------------------- 取得と集計

def fetch(base, key, lo, hi):
    """[lo, hi] のレースと走 → (races, runs)。⛔帯広ばと表に無い場は落とす"""
    races = rows_window(base, key,
                        "/rest/v1/nar_races?select=track,race_date,race_no,corners,going"
                        "&race_date=gte.{lo}&race_date=lte.{hi}"
                        "&order=race_date.asc,track.asc,race_no.asc", lo, hi)
    races = [r for r in races if r["track"] in TRACK2PREFIX]
    runs = rows_window(base, key,
                       "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,gate,finish"
                       "&race_date=gte.{lo}&race_date=lte.{hi}&finish=gte.1"
                       "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc", lo, hi)
    runs = [r for r in runs if r["track"] in TRACK2PREFIX]
    return races, runs


def race_rhos(races, runs):
    """レースごとの (ρ前後, ρ内外) → {(track, date, race_no): (f, io, 頭数)}"""
    by_race = {}
    for r in runs:
        by_race.setdefault((r["track"], r["race_date"], r["race_no"]), []).append(r)
    out = {}
    for r in races:
        k = (r["track"], r["race_date"], r["race_no"])
        rows = by_race.get(k)
        if not rows:
            continue
        ranks = first_corner(r.get("corners"))
        # 前後= 1番目のコーナーの順位 × 着順
        f = None
        if ranks:
            xs, ys = [], []
            for x in rows:
                u = x.get("runner_number")
                if u is None or int(u) not in ranks:
                    continue
                xs.append(ranks[int(u)])
                ys.append(int(x["finish"]))
            if len(xs) >= MIN_HORSES:
                f = spearman(xs, ys)
        # 内外= 枠番 × 着順(⛔枠が読めない馬は落とす)
        gx = [(int(x["gate"]), int(x["finish"])) for x in rows if x.get("gate") is not None]
        io_ = spearman([a for a, _ in gx], [b for _, b in gx]) if len(gx) >= MIN_HORSES else None
        if f is not None or io_ is not None:
            out[k] = (f, io_, len(rows))
    return out


def day_values(rho, baba_days):
    """日×場 → {date: {prefix: {t,tn,f,fn,io,ion}}}。⛔MIN_RACES 未満の指標は出さない"""
    acc = {}
    for (track, date, _no), (f, io_, _n) in rho.items():
        a = acc.setdefault((date, track), {"f": [], "io": []})
        if f is not None:
            a["f"].append(f)
        if io_ is not None:
            a["io"].append(io_)
    days = {}
    for (date, track), a in sorted(acc.items()):
        cell = {}
        if len(a["f"]) >= MIN_RACES:
            cell["f"] = round(statistics.median(a["f"]), 2)
            cell["fn"] = len(a["f"])
        if len(a["io"]) >= MIN_RACES:
            cell["io"] = round(statistics.median(a["io"]), 2)
            cell["ion"] = len(a["io"])
        b = (baba_days.get(date) or {}).get(TRACK2PREFIX[track])
        if b and b.get("d") is not None:
            cell["t"] = b["d"]
            cell["tn"] = b.get("n")
        if cell:
            days.setdefault(date, {})[TRACK2PREFIX[track]] = cell
    return days


def words_for(prefix, cell, q):
    """上下1割の外にある指標だけ言葉にする。⛔表の無い場・SHOW_WORDS に無い場は言葉を出さない。

    ⛔向き: f が大きい= 序盤で前にいた馬ほど着順が良い=「前が止まらない」。
      io が大きい= **内枠ほど着順が良い**=「内が有利」(外が伸びるのは小さい側)。
    """
    if prefix not in SHOW_WORDS:
        return None                      # 言葉を出さないと決めた場= キーごと省く
    qq = (q or {}).get(prefix)
    if not qq:
        return None                      # 平年の表がまだ無い場= キーごと省く(⛔「偏りなし」とも言わない)
    out = []
    f, io_, t = cell.get("f"), cell.get("io"), cell.get("t")
    if f is not None and qq.get("f"):
        if f > qq["f"][1]:
            out.append("前が止まらない")
        elif f < qq["f"][0]:
            out.append("差しが決まる")
    if io_ is not None and qq.get("io"):
        if io_ > qq["io"][1]:
            out.append("内が有利")
        elif io_ < qq["io"][0]:
            out.append("外が伸びる")
    if t is not None and qq.get("t"):
        if t < qq["t"][0]:
            out.append("時計 速い")
        elif t > qq["t"][1]:
            out.append("時計 かかる")
    return out


def load_q():
    if not os.path.exists(QPATH):
        return {}, None
    d = json.load(io.open(QPATH, encoding="utf-8"))
    return (d.get("q") or {}), d.get("built")


def get_baba(base, key):
    """cloud/baba.py の結果を**読むだけ**(⛔baba.py は触らない)"""
    _, body = req(base, key, "/rest/v1/nar_meta?select=value&key=eq." + BABA_KEY)
    rows = json.loads(body)
    return ((rows or [{}])[0].get("value") or {}).get("days") or {}


def read_blob(base, key):
    try:
        _, body = req(base, key, "/rest/v1/nar_meta?select=value&key=eq." + META_KEY)
        rows = json.loads(body)
        v = (rows or [{}])[0].get("value")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def upsert(base, key, value):
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": META_KEY, "value": value,
                             "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]
                           ).encode("utf-8"))
    return st


def build(base, key, lo, hi, today):
    """[lo, hi] の日×場 → days ブロック"""
    races, runs = fetch(base, key, lo, hi)
    rho = race_rhos(races, runs)
    days = day_values(rho, get_baba(base, key))
    q, q_built = load_q()
    for date, cells in days.items():
        for prefix, cell in cells.items():
            if date == today:
                cell["partial"] = True
            # ⛔`w` が **空の配列**= 平年の上下1割の内側(=画面が「偏りなし」と言える)。
            #   キーが**無い**= 平年の表がまだ無い(=画面は何も言わない)。この2つを混ぜない
            w = words_for(prefix, cell, q)
            if w is not None:
                cell["w"] = w
    return days, q_built, len(races), len(runs), len(rho)


# ---------------------------------------------------------------- 検品

KOCHI_URL = "https://jcrcftvrsgmsewwdkqha.supabase.co"


def kochi_anon(root):
    """⛔鍵をここに書かない。画面が使っている匿名キー(js/data.js の値)をファイルから読む"""
    import re
    src = io.open(os.path.join(root, "js", "data.js"), encoding="utf-8").read()
    m = re.search(r"const SUPABASE_KEY = '([^']+)'", src)
    return m.group(1) if m else None


def verify(base, key):
    log("■ ① 高知のレース単位 ρ を CSV に吐く(lapxl の前残り列と突き合わせるのは主担当)")
    races, runs = fetch(base, key, "2026-04-01", "2026-07-31")
    rho = race_rhos([r for r in races if r["track"] == "高知"],
                    [r for r in runs if r["track"] == "高知"])
    os.makedirs(os.path.dirname(CSV_KOCHI), exist_ok=True)
    with io.open(CSV_KOCHI, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "race_no", "rho_zengo", "rho_uchisoto", "n"])
        for (_t, d, no), (a, b, n) in sorted(rho.items()):
            w.writerow([d, no, "" if a is None else round(a, 4), "" if b is None else round(b, 4), n])
    log("   %s に %d 行(2026-04-01〜07-31)" % (os.path.relpath(CSV_KOCHI, ROOT), len(rho)))

    log("\n■ ② 内外 ρ と 旧DB {prefix}_stats.corner4_inout の向き(3場・日単位)")
    log("   ⛔向きは**逆**が正しい: ρ>0= 内が有利 / corner4_inout>0= 外伸び")
    lo = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    hi = dt.date.today().isoformat()
    races2, runs2 = fetch(base, key, lo, hi)
    days = day_values(race_rhos(races2, runs2), {})
    anon = kochi_anon(ROOT)
    ok_gate = True
    if not anon:
        log("   ⛔匿名キーが js/data.js から読めない= この検査は飛ばす")
    else:
        for prefix in BIAS_PREFIXES:
            r = urllib.request.Request(
                KOCHI_URL + "/rest/v1/chihou_meta?select=value&key=eq." + prefix + "_stats",
                headers={"apikey": anon, "Authorization": "Bearer " + anon, "User-Agent": UA})
            N_REQ[0] += 1
            v = json.loads(urllib.request.urlopen(r, timeout=90).read())
            table = ((v or [{}])[0].get("value") or {}).get("corner4_inout") or {}
            n = agree = 0
            for date, cells in days.items():
                cell = cells.get(prefix)
                old = table.get(date)
                if not cell or cell.get("io") is None or old is None:
                    continue
                a, b = cell["io"], float(old)
                if a == 0 or b == 0:
                    continue
                n += 1
                agree += 1 if (a > 0) != (b > 0) else 0     # ⛔逆向きが一致
            rate = agree / n if n else None
            log("   %-10s 日 %3d / 向きが合う %3d = %s"
                % (prefix, n, agree, ("%.0f%%" % (rate * 100)) if rate is not None else "—"))
            if rate is None or rate < 0.60:
                ok_gate = False

    log("\n■ ③ 時計 t と公式の馬場状態 going(良→不良で負側へ寄れば健全)")
    going_of = {}
    for r in races2:
        g = str(r.get("going") or "")
        if g:
            going_of.setdefault((r["race_date"], TRACK2PREFIX[r["track"]]), []).append(g)
    baba = get_baba(base, key)
    buckets = {}
    for date, cells in baba.items():
        for prefix, c in (cells or {}).items():
            gs = going_of.get((date, prefix))
            if not gs or c.get("d") is None:
                continue
            buckets.setdefault(statistics.mode(gs), []).append(float(c["d"]))
    prev = None
    ok3 = True
    for g in ("良", "稍重", "重", "不良"):
        if g in buckets:
            m = statistics.fmean(buckets[g])
            log("   going=%-3s 平均 %+.2f秒 (場日 %d)" % (g, m, len(buckets[g])))
            if prev is not None and m > prev + 0.05:
                ok3 = False
            prev = m
    log("\nゲート: ②3場とも60%%以上= %s / ③良→不良で負側= %s"
        % ("OK" if ok_gate else "⛔NG", "OK" if ok3 else "⛔NG"))
    return 0


def calibrate(base, key):
    """閾値表(上下1割)を作り直して pipeline/baba_trend_q.json に書く(⛔commit する)"""
    hi = dt.date.today()
    lo = (hi - dt.timedelta(days=CAL_DAYS)).isoformat()
    log("閾値表(上下1割)を作り直す: %s 〜 %s" % (lo, hi.isoformat()))
    races, runs = fetch(base, key, lo, hi.isoformat())
    days = day_values(race_rhos(races, runs), get_baba(base, key))
    acc = {}
    for _date, cells in days.items():
        for prefix, c in cells.items():
            a = acc.setdefault(prefix, {"f": [], "io": [], "t": []})
            for k in ("f", "io", "t"):
                if c.get(k) is not None:
                    a[k].append(c[k])
    q = {}
    for prefix, a in sorted(acc.items()):
        cell = {"n": len(a["f"])}
        for k in ("f", "io", "t"):
            v = quartiles(a[k])
            if v:
                cell[k] = v
        q[prefix] = cell
        log("  %-10s n=%-4d f=%s io=%s t=%s"
            % (prefix, cell["n"], cell.get("f"), cell.get("io"), cell.get("t")))
    doc = {"built": hi.isoformat(), "since": lo, "q": q}
    io.open(QPATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    log("✅ 書き込み: %s" % os.path.relpath(QPATH, ROOT))
    return 0


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--today", action="store_true", help="当日だけ組んで既存の blob に差す")
    ap.add_argument("--calibrate", action="store_true", help="閾値表(上下1割)を作り直す(年1回)")
    ap.add_argument("--verify", action="store_true", help="検品(§3)")
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    if a.calibrate:
        return calibrate(base, key)
    if a.verify:
        return verify(base, key)

    today = dt.datetime.now(JST).date()
    # ⛔--today は既存の blob に差すだけ。blob がまだ無い(初回・消えた)ときは**窓ぜんぶ**を組む
    #   = 「当日1日だけの blob」を作って画面から過去90日を消さないため
    only_today = a.today and bool((read_blob(base, key).get("days") or {}))
    if a.today and not only_today:
        log("※ baba_trend の行がまだ無いので、--today でも窓ぜんぶ(90日)を組む")
    lo = today.isoformat() if only_today else (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    t0 = dt.datetime.now()
    days, q_built, n_races, n_runs, n_rho = build(base, key, lo, today.isoformat(),
                                                  today.isoformat())
    n_cells = sum(len(v) for v in days.values())
    n_words = sum(1 for v in days.values() for c in v.values() if c.get("w"))
    log("■ %s〜%s  レース %d / 走 %d / ρ の出たレース %d → %d日 %d場日(言葉つき %d)  (%.0f秒 / 要求 %d 回)"
        % (lo, today, n_races, n_runs, n_rho, len(days), n_cells, n_words,
           (dt.datetime.now() - t0).total_seconds(), N_REQ[0]))
    if not a.apply:
        k = sorted(days)[-1] if days else None
        log("   ドライラン(--apply なし)。例 %s: %s"
            % (k, json.dumps(days.get(k, {}), ensure_ascii=False)[:400]))
        return 0
    if only_today:
        # ⛔既存の blob を消さない= 当日の日だけ差し替える(90日ぶんは朝の便が組み直す)
        old = read_blob(base, key)
        merged = dict(old.get("days") or {})
        merged.update(days)
        # 窓の外へ出た日は落とす(blob を太らせない)
        edge = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
        days = {d: v for d, v in merged.items() if d >= edge}
        q_built = q_built or old.get("q_built")
    value = {"built": dt.datetime.now(JST).isoformat(timespec="minutes"),
             "q_built": q_built, "days": days}
    st = upsert(base, key, value)
    log("   nar_meta/%s 更新 %s(%d日 %d場日)" % (META_KEY, st, len(days),
                                                sum(len(v) for v in days.values())))
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())

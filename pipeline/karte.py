# -*- coding: utf-8 -*-
"""§239a 分析タブ(カルテ)の事実の**数え方の正本**(通信なし・純関数だけ)。

書き手は cloud/karte_facts.py(材料を REST で集めてここを呼び、nar_karte_facts へ 1 頭 1 行で焼く)。
設計= viewer docs/proposal_s239_karte_facts_20260922.md。数え方= モック v3「各項目の数え方」を決めごとで上書き。

⛔決めごと(設計側で決定・ここで変えない)
  ・発走前の値だけ= **その日より前の走だけ**で数える(同じ日・未来の走は入れない)。
  ・材料が無い= None(⛔0 と書かない)。能力検査は走数に入れない。
  ・ナイター= 発走 17:00 以降。休み明け= 180 日超(馬柱の gapText と同じ)。
  ・調子の 3 項目(1 着との差・人気より上・勝ち切り)= 直近 365 日。
  ・条件との相性(大井/ほか 3 場・ナイター/昼)と相手関係= 通算・**南関の走だけ**。
  ・脚質は nar_run_facts.style を読むだけ(ここでは数えない)。馬の見分けは (名前, 生年)(§238e)。

走 1 本の形(cloud/karte_facts.py が組む)= dict:
  track, race_date('YYYY-MM-DD' か date), race_no, umaban, finish(int|None), note(着の注記),
  pop(人気), time(走破タイム 秒), win_time(そのレースの 1 着のタイム 秒), post_time('1330' 等),
  race_name, noken(能力検査なら True), c1/n1/c4/n4(nar_run_facts), late(True 出遅れ / False 記録あり出遅れ無し /
  None 記録なし)、§281 distance(nar_races.distance_m)/ jockey / trainer(nar_runs)。⛔runs には取消・取りやめの行も入れてよい(ここで is_start で外す。脚質の回数だけは
  run_facts と同じく全行から 5 走を選ぶ)

  py -3.12 -X utf8 pipeline/karte.py --selftest     # 通信なしの自己診断
"""
import datetime as dt
import re
import sys
from decimal import ROUND_HALF_UP, Decimal

try:
    from pipeline import facts                 # 脚質の窓・閾値(⛔nar_run_facts.style と同じ物を使う)
except ImportError:                            # py pipeline/karte.py --selftest で直に走らせたとき
    import facts                               # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

SOUTH = ("大井", "船橋", "川崎", "浦和")      # 南関 4 場(⛔分析タブはここだけ)
OI = "大井"                                  # 右回り・大きいコース(ほか 3 場= 左回り・小さい)
NIGHT_FROM = 1700                            # ナイター= 発走 17:00 以降
LAYOFF_DAYS = 180                            # 休み明け= 180 日超(gapText と同じ)
FORM_DAYS = 365                              # 調子の 3 項目の窓
STYLE_RATE_DAYS = 365                        # 先行して粘った・4角から失速 の窓(設計の表「直近 5 走 / 365 日」)
D30 = 30                                     # 前日までの 30 日
LAST_RUNS = 5                                # 出遅れ・序盤の位置= 直近 5 走
RECENT_RUNS = 3                              # 最近= 直近 3 走
FRONT = 3                                    # 3 番手以内
TOP3 = 3
LATE_RE = re.compile("出遅")                 # ⛔viewer race.js runGearChip と同じ判定
NOKEN_RE = re.compile("能力検査|能検")
LATE_KEY = "karte:late_next:v1"              # nar_meta の鍵(出遅れの割合表)
LATE_FROM, LATE_TO = "2025-09-01", "2026-08-31"   # 割合表の期間(決めごと 3= 南関の 1 年)
LATE_BUCKETS = (0, 1, 2, 3)                  # 直近 5 走の出遅れ回数 0 / 1 / 2 / 3 以上
COURSE_DAYS = 365                            # §281 今日と同じ場・同じ距離帯の窓
DIST_BANDS = (1200, 1600)                    # §281 距離帯= 〜1200 / 1201〜1600 / 1601〜
CLASSES = ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3")   # §281 ⛔cloud/nankan_hist.py CLASSES と同じ並び(上→下)
Z2H = str.maketrans("ＡＢＣ１２３", "ABC123")
NAME_JUNK = re.compile(r"[\s\u3000▲△☆★◇◆◎○●◯]|[（(].*?[)）]")   # 騎手・調教師の名前の比べ方(空白・減量の印・所属の括弧を外す)


# ---------------------------------------------------------------- 小道具

def to_date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def int_or_none(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v == v else None
    s = str(v).strip()
    return int(s) if s.isdigit() else None


def num_or_none(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def ratio(k, n, nd=4):
    """割合(0〜1)。⛔分母 0 / None は None(0 と書かない)。"""
    return None if not n else round(k / n, nd)


def round1(x):
    """0.1 秒に四捨五入(⛔float の round は偶数丸め= 2.45→2.4 になるので Decimal で切る)。"""
    return None if x is None else float(Decimal(repr(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def post_hhmm(v):
    """'1330' / '13:30' / 1330 → 1330。読めなければ None。"""
    if v is None:
        return None
    s = str(v).strip().replace(":", "").replace("：", "")
    return int(s) if s.isdigit() and len(s) in (3, 4) else None


# ---------------------------------------------------------------- 走の選び方

def is_noken(run):
    """能力検査(⛔走数に入れない)。便が付けた noken 旗か、レース名に 能力検査/能検。"""
    return bool(run.get("noken")) or bool(NOKEN_RE.search(str(run.get("race_name") or "")))


def is_start(run):
    """実際に走った走。⛔viewer race.js isActualStart と同じ= 取消/除外は外す・着順がある or 中止/失格。
    ⛔能力検査は入れない。"""
    if not run or is_noken(run):
        return False
    note = str(run.get("note") or "")
    if re.search("取消|除外", note):
        return False
    f = int_or_none(run.get("finish"))
    return (f is not None and f > 0) or bool(re.search("中止|失格", note))


def finished(run):
    """完走(着順の数字がある)。"""
    f = int_or_none(run.get("finish"))
    return f is not None and f > 0


def past_starts(runs, race_date):
    """その日より前の実走だけ・新しい順。⛔同じ日・未来は入れない。"""
    d1 = to_date(race_date)
    out = [r for r in (runs or []) if is_start(r) and to_date(r["race_date"]) < d1]
    out.sort(key=lambda r: (to_date(r["race_date"]), str(r.get("track") or ""), r.get("race_no") or 0),
             reverse=True)
    return out


def in_days(starts, race_date, days):
    """[その日 − days, 前日] の走(⛔facts.pick_past_runs と同じ窓の切り方)。"""
    d1 = to_date(race_date)
    d0 = d1 - dt.timedelta(days=days)
    return [r for r in starts if d0 <= to_date(r["race_date"]) < d1]


def south_only(starts):
    return [r for r in starts if r.get("track") in SOUTH]


# ---------------------------------------------------------------- スタート

def late_count(starts):
    """直近 5 走のうち出遅れの記録がある回数 → (回数, 記録のある走数)。
    ⛔記録の無い走(late is None)は分母から外す。記録が 1 本も無ければ (None, None)。"""
    use = [r for r in starts[:LAST_RUNS] if r.get("late") is not None]
    if not use:
        return None, None
    return sum(1 for r in use if r.get("late")), len(use)


def late_all(starts):
    """通算の出遅れ= その日より前の実走のうち記録のある走すべて(⛔late_count と同じ判定・5 走で切らない)
    → (回数, 記録のある走数)。記録が 1 本も無ければ (None, None)。"""
    use = [r for r in starts if r.get("late") is not None]
    if not use:
        return None, None
    return sum(1 for r in use if r.get("late")), len(use)


def late_runs(starts):
    """出遅れた走の位置= 直近 5 走の中で何走前か(1= 前走)の並び。⛔記録が 1 本も無ければ None・出遅れ 0 回は []。
    モックの「前走・2走前」と同じ数え方(位置は記録の無い走も含めた直近 5 走の中の順番)。"""
    use = starts[:LAST_RUNS]
    if not any(r.get("late") is not None for r in use):
        return None
    return [i + 1 for i, r in enumerate(use) if r.get("late")]


def late_next_pct(late_n, table):
    """割合表(nar_meta karte:late_next:v1)を引くだけ。⛔表が無い・回数が無い= None。"""
    if late_n is None or not isinstance(table, dict):
        return None
    for b in table.get("buckets") or []:
        if int_or_none(b.get("k")) == min(int(late_n), LATE_BUCKETS[-1]):
            v = num_or_none(b.get("pct"))
            return None if v is None else v
    return None


# ---------------------------------------------------------------- 走り方

STYLE_KEYS = ("逃", "先", "差", "追")


def run_style(p):
    """1 走の型= 1 角の位置 p を nar_run_facts.style と同じ閾値で切る(⛔facts.LEAD_P/FRONT_P/MID_P)。"""
    return "逃" if p <= facts.LEAD_P else "先" if p <= facts.FRONT_P else "差" if p <= facts.MID_P else "追"


def style_counts(runs, track, race_date):
    """脚質の回数 {逃, 先, 差, 追}= nar_run_facts.style と**同じ 5 走**(facts.pick_past_runs= その日より前・365 日・
    同じ場が 3 走以上ならその場だけ)を 1 走ずつ型に切って数える。⛔位置の読めた走が 1 本も無ければ None。"""
    past = []
    for r in runs or []:
        c1, n1 = int_or_none(r.get("c1")), int_or_none(r.get("n1"))
        past.append({"track": r.get("track"), "race_date": r["race_date"], "race_no": r.get("race_no"),
                     "p": (c1 / n1) if c1 is not None and n1 else None})
    ps = [r["p"] for r in facts.pick_past_runs(past, track, race_date) if r["p"] is not None]
    if not ps:
        return None
    out = dict.fromkeys(STYLE_KEYS, 0)
    for p in ps:
        out[run_style(p)] += 1
    return out


def pos_range(starts):
    """直近 5 走の最初のコーナーの順位(c1)の幅 → ('3〜7', 使えた走数)。同じなら '5'。c1 が 1 本も無ければ (None, None)。"""
    cs = [int_or_none(r.get("c1")) for r in starts[:LAST_RUNS]]
    cs = [c for c in cs if c is not None]
    if not cs:
        return None, None
    lo, hi = min(cs), max(cs)
    return ("%d" % lo if lo == hi else "%d〜%d" % (lo, hi)), len(cs)


def lead_hold(starts, race_date):
    """先行して粘った= 最初のコーナー 3 番手以内の走のうち 3 着以内 → (残った数, 3 番手以内の走数)。
    ⛔窓= STYLE_RATE_DAYS。c1 の読めた走が 1 本も無ければ (None, None)。"""
    base = [r for r in in_days(starts, race_date, STYLE_RATE_DAYS) if int_or_none(r.get("c1")) is not None]
    if not base:
        return None, None
    lead = [r for r in base if int_or_none(r["c1"]) <= FRONT]
    held = sum(1 for r in lead if finished(r) and int_or_none(r["finish"]) <= TOP3)
    return held, len(lead)


def fade4(starts, race_date):
    """4角から失速= 最後のコーナー(c4)3 番手以内の走のうち 4 着以下 → (失速数, 3 番手以内の走数)。
    ⛔中止(着順なし)は「4 着以下」に数える(3 着以内に残っていない)。c4 が 1 本も無ければ (None, None)。"""
    base = [r for r in in_days(starts, race_date, STYLE_RATE_DAYS) if int_or_none(r.get("c4")) is not None]
    if not base:
        return None, None
    front = [r for r in base if int_or_none(r["c4"]) <= FRONT]
    faded = sum(1 for r in front if not (finished(r) and int_or_none(r["finish"]) <= TOP3))
    return faded, len(front)


# ---------------------------------------------------------------- 使われ方

def runs_30d(starts, race_date):
    """前日までの 30 日に走った回数(⛔能力検査は is_start で外れている)。"""
    return len(in_days(starts, race_date, D30))


def run_of_year(starts, race_date):
    """今回が今年何戦目か(今年の実走数 + 1)。
    ⛔§278 その日より前の地方の実走が 0 件= None(中央からの転入は中央の走を数えられない・2 歳の初出走とも
    区別できない= 「1 戦目」と断定しない・台帳 #41)。"""
    if not starts:
        return None
    y = to_date(race_date).year
    return 1 + sum(1 for r in starts if to_date(r["race_date"]).year == y)


def since_layoff(starts, race_date):
    """180 日を超えて間が空いた後から今回が何戦目か。⛔そういう休みが無い馬は None(初出走の前は休みに数えない)。
    ⛔§278 地方の実走が 0 件の馬も None(下の days が今回 1 日だけ= last が立たない)。"""
    days = sorted({to_date(r["race_date"]) for r in starts}) + [to_date(race_date)]
    last = None
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days > LAYOFF_DAYS:
            last = i
    return None if last is None else len(days) - last


def gap_days(starts, race_date):
    """今回の間隔= 前走(直近の実走)からの日数(⛔馬柱の currentGap/gapText と同じ前走の選び方)。前走が無ければ None。"""
    return (to_date(race_date) - to_date(starts[0]["race_date"])).days if starts else None


def gaps_recent(starts):
    """近ごろの間隔= 直近 5 走それぞれの「その前の走からの日数」(新しい順・最大 5)。
    ⛔走の並びは gap_days / since_layoff と同じ starts(能検・取消は入っていない)。前の走が無い走は数えない。"""
    return [(to_date(starts[i]["race_date"]) - to_date(starts[i + 1]["race_date"])).days
            for i in range(min(LAST_RUNS, len(starts) - 1))]


def gap_usual(gaps):
    """ふだんの間隔= gaps_recent の中央値(偶数個なら真ん中 2 つの平均を切り捨て)。⛔2 つ未満なら None。"""
    if not gaps or len(gaps) < 2:
        return None
    g = sorted(gaps)
    m = len(g) // 2
    return g[m] if len(g) % 2 else (g[m - 1] + g[m]) // 2


# ---------------------------------------------------------------- 条件との相性(通算・南関の走だけ)

def _top3(rows):
    return sum(1 for r in rows if finished(r) and int_or_none(r["finish"]) <= TOP3)


def course_split(starts):
    """大井 / ほか 3 場 → ((大井の 3 着内, 大井の走数), (ほか 3 場の 3 着内, 走数))。
    ⛔南関の走が 1 本も無ければ両方 (None, None)。"""
    s = south_only(starts)
    if not s:
        return (None, None), (None, None)
    oi = [r for r in s if r["track"] == OI]
    ot = [r for r in s if r["track"] != OI]
    return (_top3(oi), len(oi)), (_top3(ot), len(ot))


def time_split(starts):
    """ナイター(発走 17:00 以降)/ 昼 → ((夜の 3 着内, 走数), (昼の 3 着内, 走数))。
    ⛔南関の走だけ・発走時刻の読めない走は外す。材料が無ければ両方 (None, None)。"""
    s = [r for r in south_only(starts) if post_hhmm(r.get("post_time")) is not None]
    if not s:
        return (None, None), (None, None)
    nt = [r for r in s if post_hhmm(r["post_time"]) >= NIGHT_FROM]
    dy = [r for r in s if post_hhmm(r["post_time"]) < NIGHT_FROM]
    return (_top3(nt), len(nt)), (_top3(dy), len(dy))


# ---------------------------------------------------------------- §281 今回の変化・今日と同じ場

def dist_band(m):
    """距離帯 0= 〜1200 / 1= 1201〜1600 / 2= 1601〜。距離が無ければ None。"""
    m = int_or_none(m)
    if m is None or m <= 0:
        return None
    return sum(1 for b in DIST_BANDS if m > b)


def same_course(starts, race_date, track, distance):
    """今日と同じ場・同じ距離帯の 3 着内 → (3 着内, 走数)(⛔窓= COURSE_DAYS・距離の読めない走は外す)。
    ⛔今日の距離か場が無ければ (None, None)。走が 0 本なら (0, 0)(材料はある= 0 走)。"""
    band = dist_band(distance)
    if band is None or not track:
        return None, None
    rows = [r for r in in_days(starts, race_date, COURSE_DAYS)
            if r.get("track") == track and dist_band(r.get("distance")) == band]
    return _top3(rows), len(rows)


def dist_change(starts, distance):
    """距離の変化 → (前走の距離, 今回の距離)。⛔無い方は None。"""
    prev = int_or_none(starts[0].get("distance")) if starts else None
    return prev, int_or_none(distance)


def race_class(name):
    """レース名 → いちばん上のクラス('A1'〜'C3')。⛔cloud/nankan_hist.race_classes と同じ読み方。読めなければ None。"""
    s = str(name or "").translate(Z2H)
    cs = sorted({c for c in re.findall(r"([ABC][123])", s) if c in CLASSES}, key=CLASSES.index)
    return cs[0] if cs else None


def class_move(starts, track, race_name):
    """クラスの変化= 同じ場の前の走(直近)のクラスとくらべて '上' / '同じ' / '下'。⛔どちらかのクラスが読めない・
    同じ場の走が無ければ None(推定で埋めない)。"""
    now = race_class(race_name)
    if now is None:
        return None
    prev = next((r for r in starts if r.get("track") == track), None)
    pc = race_class(prev.get("race_name")) if prev else None
    if pc is None:
        return None
    i, j = CLASSES.index(now), CLASSES.index(pc)
    return "上" if i < j else "下" if i > j else "同じ"


def norm_name(v):
    s = NAME_JUNK.sub("", str(v or ""))
    return s or None


def same_person(a, b):
    """騎手・調教師の名前が同じ人か(⛔出どころで略し方が違う= 片方がもう片方の頭なら同じ)。どちらか無ければ None。"""
    a, b = norm_name(a), norm_name(b)
    if a is None or b is None:
        return None
    return a.startswith(b) or b.startswith(a)


def jockey_change(starts, jockey):
    """乗り替わり → (前走と騎手が違うか, 今回の騎手が以前この馬に乗った回数(全期間・実走))。
    ⛔前走が無い・名前が無ければ (None, None)。乗り替わりでなければ回数は None。"""
    if not starts:
        return None, None
    sw = same_person(starts[0].get("jockey"), jockey)
    if sw is None:
        return None, None
    if sw:
        return False, None
    return True, sum(1 for r in starts if same_person(r.get("jockey"), jockey))


def trainer_move(starts, trainer):
    """転厩して初戦= 前走と調教師が違う → '転厩'(前走が南関)/ '転入'(前走が南関の外)。同じ・材料なし= None。"""
    if not starts:
        return None
    same = same_person(starts[0].get("trainer"), trainer)
    if same is None or same:
        return None
    return "転厩" if starts[0].get("track") in SOUTH else "転入"


# ---------------------------------------------------------------- 相手関係(通算・南関の走だけ)

def race_id(r):
    return (r.get("track"), str(r.get("race_date"))[:10], int_or_none(r.get("race_no")))


def h2h(mine, opponents):
    """今日の相手と過去に同じレースを走ったときの先着-負け。⛔どちらも完走したレースだけ・同着は数えない。

    mine= この馬のその日より前の実走 / opponents= [(馬番, 馬名, その馬のその日より前の実走)]。
    → ([{umaban, horse_name, w, l}](馬番順・1 回でも勝ち負けが付いた相手だけ), 勝ちの合計, 負けの合計)。
    ⛔1 頭とも勝ち負けが付かなければ (None, None, None)。
    """
    my = {race_id(r): int_or_none(r["finish"]) for r in south_only(mine) if finished(r)}
    out = []
    for no, name, runs in sorted(opponents, key=lambda x: (int_or_none(x[0]) or 0)):
        w = lo = 0
        for r in south_only(runs):
            f0 = my.get(race_id(r))
            if f0 is None or not finished(r):
                continue
            f1 = int_or_none(r["finish"])
            w += 1 if f0 < f1 else 0
            lo += 1 if f0 > f1 else 0
        if w or lo:
            out.append({"umaban": int_or_none(no), "horse_name": name, "w": w, "l": lo})
    if not out:
        return None, None, None
    return out, sum(x["w"] for x in out), sum(x["l"] for x in out)


# ---------------------------------------------------------------- 調子(直近 365 日)

def margin_sec(run):
    """1 着との差(秒)= 走破タイム − そのレースの 1 着のタイム。どちらか無ければ None。"""
    t, w = num_or_none(run.get("time")), num_or_none(run.get("win_time"))
    if t is None or w is None or not finished(run) or t < w:
        return None                               # ⛔1 着より速い= 読めない値(推定で直さない)
    return round1(t - w)


def form(starts, race_date):
    """→ dict(best_margin, best_margin_date, best_finish, recent3_margin, pop_beat(k, n), win_conv(k, n))。
    ⛔この 1 年に走っていない馬は全部 None。
    いちばん良い走= 1 着との差がいちばん小さい走(同じなら新しい方)。最近= 直近 3 走の 1 着との差の平均
    (⛔差の出せない走は平均から外す)。人気より上= 着順 < 人気 の割合(着順と人気が両方ある走が分母)。
    勝ち切り= 3 着以内のうち 1 着の割合。"""
    yr = in_days(starts, race_date, FORM_DAYS)
    out = {"best_margin": None, "best_margin_date": None, "best_finish": None, "recent3_margin": None,
           "pop_beat": (None, None), "win_conv": (None, None)}
    if not yr:
        return out
    ms = [(margin_sec(r), r) for r in yr]
    ms = [(m, r) for m, r in ms if m is not None]
    if ms:
        # yr は新しい順= 同じ差なら先に出た(新しい)方を残す
        m, r = min(ms, key=lambda x: x[0])
        out["best_margin"], out["best_margin_date"] = m, str(r["race_date"])[:10]
        out["best_finish"] = int_or_none(r.get("finish"))
    rec = [margin_sec(r) for r in yr[:RECENT_RUNS]]
    rec = [m for m in rec if m is not None]
    if rec:
        out["recent3_margin"] = round1(sum(rec) / len(rec))
    pp = [r for r in yr if finished(r) and int_or_none(r.get("pop")) is not None]
    if pp:
        out["pop_beat"] = (sum(1 for r in pp if int_or_none(r["finish"]) < int_or_none(r["pop"])), len(pp))
    t3 = [r for r in yr if finished(r) and int_or_none(r["finish"]) <= TOP3]
    out["win_conv"] = (sum(1 for r in t3 if int_or_none(r["finish"]) == 1), len(t3))
    return out


# ---------------------------------------------------------------- 出遅れの割合表

def late_table_counts(targets):
    """targets= [(その走の出遅れ True/False, 直前の直近 5 走の出遅れ回数 int)] → 割合表の buckets。
    ⛔その走に記録が無い / 直前の 5 走に記録が 1 本も無い走は呼ぶ側で外しておく。"""
    acc = {k: [0, 0] for k in LATE_BUCKETS}
    for late, k in targets:
        b = acc[min(int(k), LATE_BUCKETS[-1])]
        b[0] += 1
        b[1] += 1 if late else 0
    return [{"k": k, "n": acc[k][0], "late": acc[k][1],
             "pct": None if not acc[k][0] else round(100.0 * acc[k][1] / acc[k][0], 1)} for k in LATE_BUCKETS]


def late_targets(runs, lo, hi, tracks=SOUTH):
    """1 頭の全走 → 割合表の材料 [(その走で出遅れたか, 直前の直近 5 走の出遅れ回数)]。
    その走= [lo, hi] の tracks の実走で記録のある走。直前= その日より前の実走(late_count と同じ数え方)。"""
    d0, d1 = to_date(lo), to_date(hi)
    out = []
    for r in runs or []:
        d = to_date(r["race_date"])
        if not (d0 <= d <= d1) or r.get("track") not in tracks or not is_start(r) or r.get("late") is None:
            continue
        k, n = late_count(past_starts(runs, d))
        if n:
            out.append((bool(r["late"]), k))
    return out


# ---------------------------------------------------------------- 1 頭 1 行

def build_row(entry, runs, opponents, style, late_table, computed_at):
    """1 頭ぶんの nar_karte_facts の行(dict)。⛔欠けは None のまま(0 で埋めない)。

    entry= 今日の出走表の行 {race_date, track, race_no, umaban, horse_name, horse_key,
           §281 distance, race_name, jockey, trainer(無くてよい= 該当の列が None)}
    runs= この馬の全走(走 1 本の形・今日の行や未来の行が混じっていてよい= ここで切る)
    opponents= [(馬番, 馬名, その馬の全走)](今日の相手)/ style= 今日の nar_run_facts.style
    horse_key が None(名前か生年が無い)なら事実は全部 None(⛔名前だけで別の馬をつながない)。
    """
    d = str(entry["race_date"])[:10]
    row = dict.fromkeys(COLUMNS)                          # ⛔表の列の並びのまま・欠けは None
    row.update({"race_date": d, "track": entry["track"], "race_no": int(entry["race_no"]),
                "umaban": int(entry["umaban"]), "horse_key": entry.get("horse_key"),
                "horse_name": entry.get("horse_name"), "style": style, "computed_at": computed_at})
    if not entry.get("horse_key"):
        return row
    st = past_starts(runs, d)
    ln, lden = late_count(st)
    lan, laden = late_all(st)
    gr = gaps_recent(st)
    lruns = late_runs(st)
    pv, pvn = pos_range(st)
    lh, lhn = lead_hold(st, d)
    fd, fdn = fade4(st, d)
    (ok, on), (tk, tn) = course_split(st)
    (nk, nn), (dk, dn) = time_split(st)
    hh, hw, hl = h2h(st, [(no, nm, past_starts(rs, d)) for no, nm, rs in opponents])
    fm = form(st, d)
    sk, sn = same_course(st, d, entry["track"], entry.get("distance"))
    dp, dnow = dist_change(st, entry.get("distance"))
    jsw, jrides = jockey_change(st, entry.get("jockey"))
    row.update({
        "late_n": ln, "late_den": lden, "late_next_pct": late_next_pct(ln, late_table), "late_runs": lruns,
        "style_counts": style_counts(runs, entry["track"], d),
        "lead_hold_rate": ratio(lh, lhn), "lead_hold_n": lhn,
        "fade4_rate": ratio(fd, fdn), "fade4_n": fdn,
        "pos_var": pv, "pos_var_n": pvn,
        "runs_30d": runs_30d(st, d), "run_of_year": run_of_year(st, d), "since_layoff": since_layoff(st, d),
        "gap_days": gap_days(st, d),
        "late_all_n": lan, "late_all_den": laden, "gap_usual_days": gap_usual(gr), "gaps_recent": gr or None,
        "oi_top3_rate": ratio(ok, on), "oi_n": on, "other3_top3_rate": ratio(tk, tn), "other3_n": tn,
        "night_top3_rate": ratio(nk, nn), "night_n": nn, "day_top3_rate": ratio(dk, dn), "day_n": dn,
        "h2h": hh, "h2h_w": hw, "h2h_l": hl,
        "best_margin": fm["best_margin"], "best_margin_date": fm["best_margin_date"], "best_finish": fm["best_finish"],
        "recent3_margin": fm["recent3_margin"],
        "pop_beat_rate": ratio(*fm["pop_beat"]), "pop_beat_n": fm["pop_beat"][1],
        "win_conv_rate": ratio(*fm["win_conv"]), "win_conv_n": fm["win_conv"][1],
        "same_cd_top3": sk, "same_cd_n": sn, "dist_prev_m": dp, "dist_now_m": dnow,
        "class_move": class_move(st, entry["track"], entry.get("race_name")),
        "jockey_switch": jsw, "jockey_rides": jrides, "trainer_move": trainer_move(st, entry.get("trainer")),
    })
    return row


# 表の列(⛔pipeline/sql/karte_facts_20260922.sql + karte_facts_s274_20260924.sql + karte_facts_s281_20260925.sql と同じ並び)
COLUMNS = (
    "race_date", "track", "race_no", "umaban", "horse_key", "horse_name",
    "late_n", "late_den", "late_next_pct", "late_runs",
    "style", "style_counts", "lead_hold_rate", "lead_hold_n", "fade4_rate", "fade4_n", "pos_var", "pos_var_n",
    "runs_30d", "run_of_year", "since_layoff", "gap_days",
    "oi_top3_rate", "oi_n", "other3_top3_rate", "other3_n", "night_top3_rate", "night_n", "day_top3_rate", "day_n",
    "h2h", "h2h_w", "h2h_l",
    "best_margin", "best_margin_date", "best_finish", "recent3_margin", "pop_beat_rate", "pop_beat_n", "win_conv_rate", "win_conv_n",
    "computed_at",
    "late_all_n", "late_all_den", "gap_usual_days", "gaps_recent",      # §274(ADD COLUMN= 末尾に付く)
    "same_cd_top3", "same_cd_n", "dist_prev_m", "dist_now_m", "class_move",   # §281
    "jockey_switch", "jockey_rides", "trainer_move",
)


# ---------------------------------------------------------------- 自己診断(通信なし)

def _run(d, track="浦和", no=1, finish=5, **kw):
    r = {"track": track, "race_date": d, "race_no": no, "umaban": 1, "finish": finish, "note": None}
    r.update(kw)
    return r


def selftest(quiet=False):
    bad = n = 0

    def check(label, got, want):
        nonlocal bad, n
        ok = got == want
        n += 1
        bad += 0 if ok else 1
        if not quiet or not ok:
            print("  %s %s → %r" % ("OK " if ok else "NG ", label, got))

    D = "2026-09-22"
    runs = [
        _run("2026-09-22", finish=None),                                        # 今日(⛔入れない)
        _run("2026-09-30", finish=1),                                           # 未来(⛔入れない)
        _run("2026-09-01", finish=2, late=True, c1=2, c4=2, pop=5, time=85.0, win_time=84.8, post_time="1330"),
        _run("2026-08-20", finish=None, note="取消", late=True),                # 取消(⛔走ではない)
        _run("2026-08-10", track="大井", finish=1, late=False, c1=1, c4=1, pop=1, time=80.0, win_time=80.0,
             post_time="2010"),
        _run("2026-08-05", finish=3, noken=True, late=True),                    # 能力検査(⛔数えない)
        _run("2026-07-01", finish=7, late=None, c1=8, c4=6, pop=3, time=86.3, win_time=85.1, post_time="1500"),
        _run("2025-01-01", track="園田", finish=4, late=None, c1=3, c4=3, pop=2, time=90.0, win_time=89.0),
    ]
    st = past_starts(runs, D)
    check("past_starts 今日・未来・取消・能検を外す", [r["race_date"] for r in st],
          ["2026-09-01", "2026-08-10", "2026-07-01", "2025-01-01"])
    check("late_count 記録なしは分母から外す", late_count(st), (1, 2))
    check("late_count 空", late_count([]), (None, None))
    check("late_runs 前走", late_runs(st), [1])
    check("late_runs 記録なし", late_runs(st[2:]), None)
    check("gap_days", gap_days(st, D), 21)
    # 浦和の行が 3 つ以上(取消の行も数える= run_facts と同じ)→ 浦和だけ: 9/1 p0.2 逃・7/1 p0.8 追(大井 8/10 は外れる)
    check("style_counts 同じ場だけ", style_counts([dict(r, n1=10) for r in runs], "浦和", D),
          {"逃": 1, "先": 0, "差": 0, "追": 1})
    check("style_counts 位置なし", style_counts([dict(r, c1=None) for r in runs], "浦和", D), None)
    check("late_next_pct", late_next_pct(5, {"buckets": [{"k": 3, "pct": 40.0}]}), 40.0)
    check("late_next_pct 表なし", late_next_pct(1, None), None)
    check("pos_range", pos_range(st), ("1〜8", 4))
    check("lead_hold 365 日", lead_hold(st, D), (2, 2))
    check("fade4 365 日", fade4(st, D), (0, 2))
    check("runs_30d", runs_30d(st, D), 1)
    check("run_of_year", run_of_year(st, D), 4)
    check("since_layoff", since_layoff(st, D), 4)
    check("since_layoff 休みなし", since_layoff(st[:3], D), None)
    check("course_split", course_split(st), ((1, 1), (1, 2)))
    check("time_split", time_split(st), ((1, 1), (1, 2)))
    check("form best", (form(st, D)["best_margin"], form(st, D)["best_margin_date"]), (0.0, "2026-08-10"))
    check("form recent3", form(st, D)["recent3_margin"], round1((0.2 + 0.0 + 1.2) / 3))
    check("form pop_beat", form(st, D)["pop_beat"], (1, 3))
    check("form win_conv", form(st, D)["win_conv"], (1, 2))
    check("form 1 年走っていない", form(st[3:], D)["best_margin"], None)
    check("round1 半分は上へ", round1(2.45), 2.5)
    opp = [(3, "相手", [_run("2026-09-01", finish=5), _run("2026-08-10", track="大井", finish=2),
                        _run("2025-01-01", track="園田", finish=1)])]
    check("h2h 南関だけ", h2h(st, opp), ([{"umaban": 3, "horse_name": "相手", "w": 2, "l": 0}], 2, 0))
    check("h2h 会っていない", h2h(st, [(4, "他", [])]), (None, None, None))
    # §281(st= 9/1 浦和 2 着・8/10 大井 1 着・7/1 浦和 7 着・2025-01-01 園田 4 着)
    s3 = [dict(r, distance=dv, jockey=jv, trainer=tv, race_name=nv) for r, dv, jv, tv, nv in zip(st, (
        1400, 1500, 1400, 1200), ("森泰斗", "笹川翼", "森　泰", None), ("A師", "A師", "B師", "C師"), ("C1", "B3", "C2", "C3"))]
    check("dist_band", [dist_band(x) for x in (1200, 1201, 1600, 1601, None)], [0, 1, 1, 2, None])
    check("same_course 浦和・1201〜1600", same_course(s3, D, "浦和", 1500), (1, 2))
    check("same_course 距離なし", same_course(s3, D, "浦和", None), (None, None))
    check("dist_change", dist_change(s3, 1600), (1400, 1600))
    check("race_class 全角・混合は上", (race_class("Ｃ２Ｃ３"), race_class("B3C1"), race_class("オープン")), ("C2", "B3", None))
    check("class_move 同じ場の前の走", class_move(s3, "浦和", "B3"), "上")
    check("class_move 同じ", class_move(s3, "浦和", "C1"), "同じ")
    check("class_move 読めない", class_move(s3, "浦和", "オープン"), None)
    check("jockey_change 略しても同じ人", jockey_change(s3, "森泰"), (False, None))
    check("jockey_change 再騎乗", jockey_change(s3[1:], "森泰斗"), (True, 1))
    check("trainer_move 転厩", trainer_move(s3[2:], "Z師"), "転厩")
    check("trainer_move 転入", trainer_move(s3[3:], "Z師"), "転入")
    check("trainer_move 同じ", trainer_move(s3, "A師"), None)
    check("late_table_counts", late_table_counts([(True, 0), (False, 0), (True, 4)])[0]["pct"], 50.0)
    if not quiet:
        print("karte selftest: %d/%d" % (n - bad, n))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(selftest(quiet="--quiet" in sys.argv))

# -*- coding: utf-8 -*-
"""§238a 検算= 派生表の規則(pipeline/facts.py)と **3 つの写し**の答えが同じかを実データで数える。

比べる相手:
  (a) 旧 `cloud/tenkai.py` の corner_ranks / first_corner / pick_runs+style_of(展開の見立て)
      ⛔§238a2 で本番からは消えたので、**消える直前のコードをこの中に凍結**して比べ続ける。
  (b) `pipeline/sql/ai_feat_20260908.sql` の t_cmap/t_corner(c1..c4 の枠の決め方)と style の式
      ⛔SQL は本番でしか動かせないので、**SQL の字面を Python に写した** ai_feat_* 関数と比べる
      (写しが正しいことは SQL のコメントと式を 1 行ずつ突き合わせた= notes に書く)。
  (c) `js/data.js cornerRanks()` を **node でそのまま呼ぶ**(tests/run_facts_corner_node.mjs)。
      ⛔§238a2 で画面も派生表読みになったので、今の js/data.js には cornerRanks() が無い=
        この (c) は **§238a2 より前の data.js** を --data-js に渡したときだけ動く(無ければ飛ばす)。

  py -3.12 -X utf8 tests/run_facts_check.py --from 2026-06-21 --to 2026-09-20 \
      --data-js "C:/…/js/data.js" --notes docs/notes_s238a_check.md

環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(読むだけ・⛔鍵はコードに書かない)。
終了コード: 0 一致 100% / 1 差がある(notes に例 10 件) / 2 取得に失敗
"""
import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import facts                                          # noqa: E402
from cloud import run_facts                                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

MAX_EXAMPLES = 10


# ---------------------------------------------------------------- (a) 旧 cloud/tenkai.py の**凍結した写し**
# ⛔§238a2(2026-09-22)で cloud/tenkai.py から corner_ranks / first_corner / style_of は消えた
#   (派生表 nar_run_facts を読むだけになった)。この検算をこの先も回せるように、**消える直前の
#   コード(commit 5f699f8)を字面のまま**ここへ凍結する。⛔ここを直すのは「昔こう動いていた」を
#   直すことなので、直してはいけない。


LEGACY_PAST_DAYS = 365
LEGACY_N_RUNS = 5
LEGACY_SAME_TRACK_MIN = 3
LEGACY_MIN_RUNS = 2
LEGACY_LEAD_P, LEGACY_FRONT_P, LEGACY_MID_P = 0.2, 0.4, 0.7


def legacy_corner_ranks(order):
    """旧 cloud/tenkai.py corner_ranks()(2026-09-22 まで)。"""
    s = str(order or "").strip()
    if not s:
        return None
    out, rank, i = {}, 1, 0
    while i < len(s):
        ch = s[i]
        if ch in ",-= 　":
            i += 1
            continue
        if ch == "(":
            end = s.find(")", i)
            if end < 0:
                return None
            nums = []
            for x in s[i + 1:end].split(","):
                x = x.strip()
                if not x.isdigit() or int(x) <= 0:
                    return None
                nums.append(int(x))
            if not nums:
                return None
            for n in nums:
                out.setdefault(n, rank)
            rank += len(nums)
            i = end + 1
            continue
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == i:
            return None
        out.setdefault(int(s[i:j]), rank)
        rank += 1
        i = j
    return out or None


def legacy_first_corner(corners):
    """旧 cloud/tenkai.py first_corner()。"""
    for c in (corners or []):
        if not isinstance(c, dict):
            continue
        ranks = legacy_corner_ranks(c.get("order"))
        if ranks:
            return ranks
    return None


def legacy_pick_runs(runs, track):
    """旧 cloud/tenkai.py pick_runs()。"""
    same = [r for r in runs if r["track"] == track]
    return (same if len(same) >= LEGACY_SAME_TRACK_MIN else runs)[:LEGACY_N_RUNS]


def legacy_style_of(ps):
    """旧 cloud/tenkai.py style_of()(型だけ返す)。"""
    ps = [p for p in ps if p is not None]
    if len(ps) < LEGACY_MIN_RUNS:
        return None
    m = statistics.fmean(ps)
    if sum(1 for p in ps if p <= LEGACY_LEAD_P) * 2 > len(ps):
        return "逃げ"
    return "先行" if m <= LEGACY_FRONT_P else "差し" if m <= LEGACY_MID_P else "追込"


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- (b) ai_feat SQL の Python 写し

def ai_feat_slots(corners):
    """ai_feat_20260908.sql の t_cmap → t_corner を**字面のまま**写したもの。

    SQL:
      t_cmap= `maps = array_agg(m order by ord) where m is not null`(読めたコーナーだけ・並びは元順)
              `ns   = array_agg(コーナーの頭数 order by ord)`
      t_corner= pos1= maps[1] / n1= ns[1]
                pos2= maps[2] ・n2= ns[2]  ⛔`array_length(maps,1) >= 3` のときだけ
                pos3= maps[len-1]・n3= ns[len-1] ⛔`>= 2` のときだけ
                pos4= maps[len] ・n4= ns[len]
    """
    maps = []
    for c in (corners or []):
        if not isinstance(c, dict):
            continue
        m = legacy_corner_ranks(c.get("order"))      # ⛔旧 SQL nar_corner_ranks と同じ規則
        if m is not None:
            maps.append(m)
    k = len(maps)
    if k == 0:
        return None
    ns = [len(m) for m in maps]
    return {
        "pos1": maps[0], "n1": ns[0],
        "pos2": maps[1] if k >= 3 else None, "n2": ns[1] if k >= 3 else None,
        "pos3": maps[k - 2] if k >= 2 else None, "n3": ns[k - 2] if k >= 2 else None,
        "pos4": maps[k - 1], "n4": ns[k - 1],
    }


def ai_feat_style(fwds):
    """ai_feat の style 式(fwd = 1 - pos1/n1 の直近 5 走・⛔窓も同じ場の条件も無い)。

    SQL: cnt5(fwd) < 2 → null / fwd>=0.8 が過半数 → 0(逃げ)/ 1-avg <= 0.4 → 1 / <= 0.7 → 2 / else 3
    """
    xs = [x for x in fwds if x is not None][:5]
    if len(xs) < 2:
        return None
    if sum(1 for x in xs if x >= 0.8) * 2 > len(xs):
        return "逃げ"
    m = 1 - statistics.fmean(xs)
    return "先行" if m <= 0.4 else "差し" if m <= 0.7 else "追込"


# ---------------------------------------------------------------- (c) node で js/data.js を呼ぶ

def node_corner_ranks(data_js, orders):
    """node があれば js/data.js の cornerRanks() の答え {order: ranks}。無ければ None。"""
    if not data_js or not os.path.exists(data_js):
        return None, "js/data.js のパスが無い"
    exe = None
    for cand in ("node", os.environ.get("NODE_BIN") or ""):
        if not cand:
            continue
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=True, timeout=30)
            exe = cand
            break
        except Exception:                                            # noqa: BLE001
            continue
    if exe is None:
        return None, "node が無い"
    here = os.path.dirname(os.path.abspath(__file__))
    with tempfile.TemporaryDirectory() as tmp:
        fin = os.path.join(tmp, "in.json")
        fout = os.path.join(tmp, "out.json")
        with open(fin, "w", encoding="utf-8") as f:
            json.dump(list(orders), f, ensure_ascii=False)
        r = subprocess.run([exe, os.path.join(here, "run_facts_corner_node.mjs"), data_js, fin, fout],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None, "node が落ちた: %s" % (r.stderr or "")[:200]
        with open(fout, encoding="utf-8") as f:
            rows = json.load(f)
    return {x["order"]: (None if x["ranks"] is None else {int(k): v for k, v in x["ranks"].items()})
            for x in rows}, None


# ---------------------------------------------------------------- 検算

def check_window(base, key, lo, hi, data_js):
    """1 窓ぶんの一致数。返り値= (counts, examples)。"""
    races = run_facts.fetch_races(base, key, lo, hi)
    runs = run_facts.fetch_runs(base, key, lo, hi)
    race_of = {(r["track"], str(r["race_date"])[:10], int(r["race_no"])): r for r in races}
    keys = {facts.horse_key(r.get("horse_name"), r.get("birth_date")) for r in runs}
    past = run_facts.fetch_past_positions(base, key, lo, hi, keys)

    counts = {k: [0, 0] for k in ("a_ranks", "a_first", "a_style", "b_slots", "b_style", "c_ranks")}
    ex = {k: [] for k in counts}

    def hit(k, ok, example):
        counts[k][1] += 1
        if ok:
            counts[k][0] += 1
        elif len(ex[k]) < MAX_EXAMPLES:
            ex[k].append(example)

    # ---- (a)/(c) 通過順の字面。レースの corners に出てくる並びを全部
    orders = []
    for r in races:
        for c in (r.get("corners") or []):
            if isinstance(c, dict) and c.get("order"):
                orders.append(str(c["order"]))
    uniq = sorted(set(orders))
    for o in uniq:
        hit("a_ranks", facts.corner_ranks(o) == legacy_corner_ranks(o),
            {"order": o, "facts": facts.corner_ranks(o), "tenkai": legacy_corner_ranks(o)})
    js_map, js_why = node_corner_ranks(data_js, uniq)
    if js_map is not None:
        for o in uniq:
            hit("c_ranks", facts.corner_ranks(o) == js_map.get(o),
                {"order": o, "facts": facts.corner_ranks(o), "js": js_map.get(o)})

    # ---- (a) 1 角の表 / (b) c1..c4 の枠
    for r in races:
        c = r.get("corners")
        hit("a_first", facts.first_corner(c) == legacy_first_corner(c),
            {"race": [r["track"], str(r["race_date"])[:10], r["race_no"]]})
        mine = facts.corner_slots(c)
        theirs = ai_feat_slots(c)
        if theirs is None:
            ok = all(m is None for m, _n in mine)
        else:
            ok = ([m for m, _n in mine] == [theirs["pos1"], theirs["pos2"], theirs["pos3"], theirs["pos4"]]
                  and [n for _m, n in mine] == [theirs["n1"], theirs["n2"], theirs["n3"], theirs["n4"]])
        hit("b_slots", ok, {"race": [r["track"], str(r["race_date"])[:10], r["race_no"]],
                            "facts": [[m and "map", n] for m, n in mine]})

    # ---- 脚質。⛔同じ材料(過去走の p)を 3 つの規則に通して、規則の違いだけを見る
    for r in runs:
        d = str(r["race_date"])[:10]
        k = (r["track"], d, int(r["race_no"]))
        if k not in race_of or r.get("runner_number") is None:
            continue
        hk = facts.horse_key(r.get("horse_name"), r.get("birth_date"))
        hist = past.get(hk, [])
        mine = facts.style_asof(hist, r["track"], d)[0]

        # (a) tenkai.py の選び方= 新しい順・365 日窓・同じ場 3 走以上ならその場だけ・5 走
        win = [x for x in hist
               if (dt.date.fromisoformat(d) - dt.timedelta(days=LEGACY_PAST_DAYS)).isoformat() <= x["race_date"] < d]
        win.sort(key=lambda x: (x["race_date"], x["track"], x["race_no"]), reverse=True)
        t_use = legacy_pick_runs(win, r["track"])
        t_style = legacy_style_of([x["p"] for x in t_use if x["p"] is not None])
        hit("a_style", mine == t_style,
            {"horse": hk, "race": list(k), "facts": mine, "tenkai": t_style, "n": len(t_use)})

        # (b) ai_feat の選び方= 直近 5 走(⛔窓も同じ場の条件も無い)
        prev = sorted([x for x in hist if x["race_date"] < d],
                      key=lambda x: (x["race_date"], x["track"], x["race_no"]), reverse=True)[:5]
        b_style = ai_feat_style([None if x["p"] is None else 1 - x["p"] for x in prev])
        hit("b_style", mine == b_style,
            {"horse": hk, "race": list(k), "facts": mine, "ai_feat": b_style,
             "days": [x["race_date"] for x in prev]})
    return counts, ex, js_why


def main():
    ap = argparse.ArgumentParser(description="§238a 検算(派生表の規則 vs 3 写し)")
    today = dt.datetime.now(run_facts.JST).date()
    ap.add_argument("--from", dest="lo", default=(today - dt.timedelta(days=90)).isoformat())
    ap.add_argument("--to", dest="hi", default=(today - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--data-js", help="統合ビューア origin/master の js/data.js の写し((c) に使う)")
    ap.add_argument("--notes", default="docs/notes_s238a_check.md")
    a = ap.parse_args()

    if facts.selftest(quiet=True):
        log("⛔規則の自己診断が落ちた= 検算しない")
        return 2
    base, key = run_facts.env()
    total = {k: [0, 0] for k in ("a_ranks", "a_first", "a_style", "b_slots", "b_style", "c_ranks")}
    ex = {k: [] for k in total}
    js_why = None
    t0 = time.time()
    for w_lo, w_hi in run_facts.windows(a.lo, a.hi):
        c, e, why = check_window(base, key, w_lo, w_hi, a.data_js)
        js_why = js_why or why
        for k in total:
            total[k][0] += c[k][0]
            total[k][1] += c[k][1]
            for x in e[k]:
                if len(ex[k]) < MAX_EXAMPLES:
                    ex[k].append(x)
        log("  %s〜%s (%.0fs) " % (w_lo, w_hi, time.time() - t0)
            + " / ".join("%s %d/%d" % (k, c[k][0], c[k][1]) for k in total if c[k][1]))

    log("— 合計 —")
    bad = 0
    for k, (ok, n) in total.items():
        if not n:
            log("  %-8s 0 件(比べる材料が無い)" % k)
            continue
        rate = 100.0 * ok / n
        bad += 0 if ok == n else 1
        log("  %-8s %d/%d (%.4f%%)" % (k, ok, n, rate))
    write_notes(a.notes, a.lo, a.hi, total, ex, js_why)
    log("notes= %s" % a.notes)
    return 0 if not bad else 1


def write_notes(path, lo, hi, total, ex, js_why):
    LABEL = {
        "a_ranks": "(a) 通過順の字面 vs 旧 cloud/tenkai.py corner_ranks(凍結)",
        "a_first": "(a) 1 角の表 vs 旧 cloud/tenkai.py first_corner(凍結)",
        "a_style": "(a) 脚質 vs 旧 cloud/tenkai.py pick_runs+style_of(凍結)",
        "b_slots": "(b) c1..c4 の枠 vs ai_feat SQL t_corner(Python 写し)",
        "b_style": "(b) 脚質 vs ai_feat SQL style 式(直近 5 走・窓なし)",
        "c_ranks": "(c) 通過順の字面 vs js/data.js cornerRanks(node)",
    }
    out = ["# §238a 検算の結果(%s〜%s)" % (lo, hi), "",
           "作ったもの= `tests/run_facts_check.py`。規則の正本= `pipeline/facts.py`。", ""]
    if js_why:
        out += ["⚠ (c) の node 実行= **できなかった**(%s)。この行は Python の写しで代用していない"
                "= 数えていない。" % js_why, ""]
    out += ["| 比べた相手 | 一致 | 件数 | 一致率 |", "|---|---:|---:|---:|"]
    for k, (ok, n) in total.items():
        out.append("| %s | %d | %d | %s |" % (LABEL[k], ok, n, "—" if not n else "%.4f%%" % (100.0 * ok / n)))
    out.append("")
    for k, (ok, n) in total.items():
        if n and ok != n:
            out += ["## 差の例 %s" % LABEL[k], ""]
            for x in ex[k]:
                out.append("- `%s`" % json.dumps(x, ensure_ascii=False, default=str)[:300])
            out.append("")
    out += ["## 差の理由(規則の違い・⛔直す前に読む)", "",
            "- **(b) 脚質**= ai_feat は**直近 5 走をそのまま**使う(365 日の窓なし・同じ場が 3 走以上なら"
            "その場だけ、も無し)。派生表は展開便(tenkai.py)と同じ窓を採る= ここは**定義が元から違う**。"
            "どちらに寄せるかはユーザー判断(⛔勝手に片方へ寄せない)。",
            "- **(a) 脚質**= 差は 12 か月で **0 件**。⚠差が出うる所= 展開便は `finish=not.is.null`(着順の入った走)だけを材料にし、派生表は"
            "**通過順が読めた走**を材料にする。取消・中止で着順が無くても通過順がある走で差が出る。",
            "- **(b) c1..c4**= 枠の決め方は同じ(読めたコーナーの並びの位置)。差が 0 でなければ"
            "`corners` の中に配列でない要素が混じった行なので、元の行を見ること。", ""]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    raise SystemExit(main())

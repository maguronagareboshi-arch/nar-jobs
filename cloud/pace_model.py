# -*- coding: utf-8 -*-
"""月 1 の便: 出走全頭の前半3F で流れ(速い/平均/遅い)を当てる係数を場ごとに作り、nar_meta 'pace_model:v1' の
1 行に書く。tenkai.py が PACE_MODEL_TRACKS の場でこの係数を使う(読めなければ今の見立て add_pace に戻る)。

⛔材料・特徴量・欠損の扱い・標準化・学習は cloud/pace_pred_test.py の D と**同じ関数**(load_recs(with_d=True) /
  fit_model(fk="fd") / tenkai.d_ten / tenkai.pace_feat / tenkai.pace_vec)。ここで作り直さない。
  2026-10-23 からテンは D(走破 − 上がり3F の §232b 物差し)。value に "ten": "d"(無い係数は tenkai が使わない)。
学習= 直前 12 か月(--to の月まで)。当たりの割合= その 12 か月を月ごとのウォークフォワード(各月は前 12 か月で学習)。
数えるのはこの runner の中(⛔本番 DB では集計しない・書くのは nar_meta の 1 行だけ)。

  python cloud/pace_model.py --dry              # 書かずに log に出す
  python cloud/pace_model.py --apply [--to YYYY-MM]
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tenkai as tk  # noqa: E402
import pace_pred_test as pp  # noqa: E402


def export(m):
    """fit_model の戻り → nar_meta に書く形(None は書かない)"""
    if m is None:
        return None
    if isinstance(m, tuple):
        return {"kind": "const", "label": m[1]}
    sc, lr = m.steps[0][1], m.steps[-1][1]
    return {"kind": "lr", "classes": [str(c) for c in lr.classes_],
            "mean": [float(x) for x in sc.mean_], "scale": [float(x) for x in sc.scale_],
            "coef": [[float(x) for x in row] for row in lr.coef_],
            "intercept": [float(x) for x in lr.intercept_]}


def build(recs, to, tracks=tk.PACE_MODEL_TRACKS):
    """recs(load_recs の戻り)→ value。学習= [to−11, to]・当たりの割合= 同じ 12 か月の WF"""
    lo = pp.ym_add(to, -(pp.TRAIN_MONTHS - 1))
    wf = pp.summarize(pp.walk_forward([r for r in recs if r["t"] in tracks], pp.months(lo, to)))
    out = {}
    for t in tracks:
        train = [r for r in recs if r["t"] == t and lo <= r["ym"] <= to]
        mp = export(pp.fit_model(train, "fd"))
        if mp is None:
            continue
        w = wf.get(t) or {}
        mp["n_train"] = len(train)
        mp["wf"] = {"races": w.get("races"), "hit_all": w.get("d_hit_all"), "hit_cover": w.get("d_hit_cover"),
                    "const_hit_all": w.get("c_hit_all")}
        out[t] = mp
    return {"built": dt.datetime.now(tk.JST).isoformat(timespec="minutes"), "train": [lo, to],
            "ten": "d", "d_runs": tk.PACE_D_RUNS, "features": list(tk.PACE_FEATURES), "tracks": out}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--to", help="学習の最後の月 YYYY-MM(既定= 前の月)")
    a = ap.parse_args()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        tk.log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    to = a.to or pp.ym_add(dt.datetime.now(tk.JST).strftime("%Y-%m"), -1)
    # WF の最初の月も前 12 か月で学習するので、材料は 24 か月ぶん
    recs = pp.load_recs(base, key, pp.months(pp.ym_add(to, -(2 * pp.TRAIN_MONTHS - 1)), to),
                       with_d=True)
    value = build(recs, to)
    for t, mp in value["tracks"].items():
        tk.log("  %s %s 学習 %d 本・WF 一致(全) %s・いつも同じ答え %s"
               % (t, mp["kind"], mp["n_train"], mp["wf"]["hit_all"], mp["wf"]["const_hit_all"]))
    if not a.apply:
        tk.log("ドライラン(--apply なし)。%d 場" % len(value["tracks"]))
        return 0
    tk.N_REQ[0] += 1
    st, _ = tk.req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                   json.dumps([{"key": tk.PACE_MODEL_KEY, "value": value,
                                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}],
                              ensure_ascii=False).encode("utf-8"))
    tk.log("nar_meta/%s 更新 %s(%d 場)" % (tk.PACE_MODEL_KEY, st, len(value["tracks"])))
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main())

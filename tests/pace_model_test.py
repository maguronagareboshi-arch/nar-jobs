# -*- coding: utf-8 -*-
"""cloud/pace_model.py と tenkai の全頭版の 2 則(⛔ネット・DB なし・sklearn は要る)。
実行: py -3.12 -X utf8 -m unittest tests.pace_model_test"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import tenkai as tk  # noqa: E402
import pace_pred_test as pp  # noqa: E402
import pace_model as pm  # noqa: E402


def fake_recs(seed=7, n=400):
    rnd, out = random.Random(seed), []
    for i in range(n):
        tens = {u: round(rnd.gauss(0, 0.6), 2) for u in range(1, rnd.randint(0, 9) + 1)}
        lead = [u for u in tens if rnd.random() < 0.15]
        front = [u for u in tens if u not in lead and rnd.random() < 0.3]
        f = tk.pace_feat(tens, lead, front)
        z = (f["f1"] if f["f1"] is not None else 0.2) - 0.3 * f["n_lead"] + rnd.gauss(0, 0.4)
        y = "速い" if z < -0.5 else ("遅い" if z > 0.1 else "平均")
        out.append({"t": "大井", "ym": "2026-%02d" % (i % 12 + 1), "y": y, "f": f, "a": None})
    return out


class ModelEqualsB(unittest.TestCase):
    def test_tenkai_apply_matches_pace_pred_test_b(self):
        recs = fake_recs()
        train, test = recs[:300], recs[300:]
        b = pp.fit_predict(train, test)
        mp = pm.export(pp.fit_model(train))
        self.assertEqual(mp["kind"], "lr")
        mine = [tk.pace_apply(mp, r["f"])[0] for r in test]
        self.assertEqual(mine, b)
        # 確率も sklearn と同じ
        m = pp.fit_model(train)
        pr = m.predict_proba([pp.vec(test[0]["f"])])[0]
        p = tk.pace_apply(mp, test[0]["f"])[1]
        for c, v in zip(m.classes_, pr):
            self.assertAlmostEqual(p[c], v, places=9)
        self.assertEqual(pm.export(pp.fit_model(train[:10])), None)          # 行が足りない場は書かない


def race_inputs():
    """大井 1R・3 頭。1 番= 逃げ・テン −0.5(今の見立ては「速い」)。3 番は型が無いがテンはある"""
    d = "2026-10-22"
    runs = [{"track": "大井", "race_no": 1, "runner_number": u, "horse_name": "馬%d" % u, "birth_date": None}
            for u in (1, 2, 3)]
    past, ten_of = {}, {}
    for u, x in ((1, 36.0), (2, 36.8), (3, 35.9)):
        past["馬%d" % u] = [{"track": "大井", "race_date": "2026-09-%02d" % (i + 1), "race_no": 1,
                             "runner_number": u} for i in range(3)]
        for i in range(3):
            ten_of[("大井", "2026-09-%02d" % (i + 1), 1, u)] = (x, 1200)
    std = {("大井", 1200): 36.5}
    band = {"大井": [-0.3, 0.3]}
    sty = {("大井", 1, 1): ("逃げ", 0.1, 5), ("大井", 1, 2): ("差し", 0.6, 5)}
    races = [{"track": "大井", "race_no": 1, "distance_m": 1200, "field_size": 3}]
    return d, races, runs, past, sty, (ten_of, std, band, None)


class FallbackToCurrent(unittest.TestCase):
    def test_no_coef_keeps_add_pace(self):
        _d, races, runs, past, sty, ten = race_inputs()
        old, _ = tk.build_races(races, runs, past, sty, ten)
        for pm_arg in (None, {}, {"大井": {"kind": "lr", "classes": ["速い"]}}):   # 無い・空・壊れた係数
            new, _ = tk.build_races(races, runs, past, sty, ten, pm_arg)
            self.assertEqual(new, old)
        self.assertEqual(old["ooi-1"]["pace"], "速い")
        self.assertEqual(old["ooi-1"]["pace_by"], 1)
        self.assertNotIn("pace_p", old["ooi-1"])

    def test_with_coef_uses_all_runners(self):
        _d, races, runs, past, sty, ten = race_inputs()
        mp = {"kind": "const", "label": "遅い"}
        new, _ = tk.build_races(races, runs, past, sty, ten, {"大井": mp})
        r = new["ooi-1"]
        self.assertEqual(r["pace"], "遅い")
        self.assertEqual(r["pace_p"], {"速い": 0.0, "平均": 0.0, "遅い": 1.0})
        self.assertEqual(r["pace_why"], {"ten": [[3, -0.6], [1, -0.5], [2, 0.3]], "lead": 1, "front": 0})
        self.assertNotIn("pace_by", r)
        self.assertNotIn("pace_hit", r)   # wf が無い係数では置かない
        r2 = tk.build_races(races, runs, past, sty, ten, {"大井": dict(mp, wf={"hit_all": 0.51234})})[0]["ooi-1"]
        self.assertEqual(r2["pace_hit"], 0.512)


if __name__ == "__main__":
    unittest.main()

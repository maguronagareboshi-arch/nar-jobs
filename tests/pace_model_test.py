# -*- coding: utf-8 -*-
"""cloud/pace_model.py と tenkai の全頭版の 2 則(⛔ネット・DB なし・sklearn は要る)。
実行: py -3.12 -X utf8 -m unittest tests.pace_model_test"""
import datetime as dt
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
        d, races, runs, past, sty, ten = race_inputs()
        mp = {"kind": "const", "label": "遅い"}
        dten = (d, ten[0], ten[1])              # D の材料(ここでは前半3F と同じ値・平年値 36.5)
        self.assertEqual(tk.build_races(races, runs, past, sty, ten, {"大井": mp})[0],
                         tk.build_races(races, runs, past, sty, ten)[0])   # D の材料が無ければ今の見立て
        new, _ = tk.build_races(races, runs, past, sty, ten, {"大井": mp}, dten)
        r = new["ooi-1"]
        self.assertEqual(r["pace"], "遅い")
        self.assertEqual(r["pace_p"], {"速い": 0.0, "平均": 0.0, "遅い": 1.0})
        self.assertEqual(r["pace_why"], {"ten": [[3, -0.6], [1, -0.5], [2, 0.3]], "lead": 1, "front": 0})
        self.assertNotIn("pace_by", r)
        self.assertNotIn("pace_hit", r)   # wf が無い係数では置かない
        r2 = tk.build_races(races, runs, past, sty, ten, {"大井": dict(mp, wf={"hit_all": 0.51234})}, dten)[0]["ooi-1"]
        self.assertEqual(r2["pace_hit"], 0.512)



class OldCoefFallback(unittest.TestCase):
    def test_old_coef_is_not_used(self):
        base = {"features": list(tk.PACE_FEATURES), "tracks": {"大井": {"kind": "const", "label": "遅い"}}}
        orig = tk.rows_all
        try:
            tk.rows_all = lambda *_a, **_k: [{"value": base}]                   # "ten" の無い古い係数
            self.assertEqual(tk.fetch_pace_model("u", "k"), {})
            tk.rows_all = lambda *_a, **_k: [{"value": dict(base, ten="b")}]
            self.assertEqual(tk.fetch_pace_model("u", "k"), {})
            tk.rows_all = lambda *_a, **_k: [{"value": dict(base, ten="d")}]
            self.assertEqual(tk.fetch_pace_model("u", "k"), base["tracks"])
        finally:
            tk.rows_all = orig
        # 古い係数= {} → build_races は今の見立てと 1 バイトも変わらない
        d, races, runs, past, sty, ten = race_inputs()
        self.assertEqual(tk.build_races(races, runs, past, sty, ten, {}, (d, ten[0], ten[1]))[0],
                         tk.build_races(races, runs, past, sty, ten)[0])


def d_race():
    """大井 3R・4 頭の D の材料。馬 1〜3 は他場の走も持つ。馬 4 は 2 走だけ(テンなし)。未来の走は極端に速い"""
    d = "2026-10-22"
    std = {("大井", 1400): 88.0, ("金沢", 1400): 89.5, ("川崎", 1500): 95.0}
    past, dist, runs = {}, {}, []
    spec = {1: [("大井", 1400, 87.6), ("金沢", 1400, 89.0), ("大井", 1400, 87.9), ("川崎", 1500, 95.2)],
            2: [("大井", 1400, 88.8), ("大井", 1400, 88.4), ("川崎", 1500, 95.9), ("大井", 1100, 60.0),
                ("大井", 1400, 88.1), ("大井", 1400, 88.6), ("大井", 1400, 70.0)],      # 6 走目以降は使わない
            3: [("金沢", 1400, 89.9), ("金沢", 1400, 90.1), ("金沢", 1400, 89.4)],
            4: [("大井", 1400, 86.0), ("大井", 1400, 86.0)]}
    for u, xs in spec.items():
        h = []
        for i, (t, dm, v) in enumerate(xs):
            rd = (dt.date(2026, 10, 1) - dt.timedelta(days=7 * i)).isoformat()
            h.append({"track": t, "race_date": rd, "race_no": 2, "runner_number": u, "horse_name": "D%d" % u,
                      "birth_date": None, "time_sec": v + 37.0, "last3f": 37.0})
            dist[(t, rd, 2)] = dm
        for rd, no in ((d, 1), ("2026-11-01", 2)):                          # 同じ日の前の R も「発走日より前」でない
            h.insert(0, {"track": "大井", "race_date": rd, "race_no": no, "runner_number": u,
                         "horse_name": "D%d" % u, "birth_date": None, "time_sec": 80.0, "last3f": 37.0})
            dist[("大井", rd, no)] = 1400
        past["D%d" % u] = h
        runs.append({"track": "大井", "race_no": 3, "runner_number": u, "horse_name": "D%d" % u, "birth_date": None})
    sty = {("大井", 3, 1): ("逃げ", 0.1, 5), ("大井", 3, 2): ("先行", 0.3, 5), ("大井", 3, 4): ("先行", 0.3, 5)}
    races = [{"track": "大井", "race_no": 3, "distance_m": 1400, "field_size": 4}]
    return d, races, runs, past, sty, dist, std


class TenkaiEqualsD(unittest.TestCase):
    def test_same_answer_as_pace_pred_test_d_and_no_future(self):
        d, races, runs, past, sty, dist, std = d_race()
        allr = [x for v in past.values() for x in v]
        dval = tk.d_values(allr, dist)
        # 試しの D(pace_pred_test.race_features_d)
        rows = [dict(r, race_date=d) for r in runs]
        fd = pp.race_features_d(d, rows, past, {u: s[0] for (_t, _n, u), s in sty.items()}, dval, std)
        self.assertEqual(fd["n_ten"], 3)
        recs = [dict(r, fd=r["f"]) for r in fake_recs()]
        m = pp.fit_model(recs[:300], "fd")
        mp = pm.export(m)
        want = pp.fit_predict(recs[:300], [{"fd": fd}], "fd")[0]
        got, _ = tk.build_races(races, runs, past, sty, ({}, {}, {}, None), {"大井": mp}, (d, dval, std))
        r = got["ooi-3"]
        self.assertEqual(r["pace"], want)
        self.assertEqual(r["pace"], tk.pace_apply(mp, fd)[0])
        pr = m.predict_proba([pp.vec(fd)])[0]
        for c, v in zip(m.classes_, pr):
            self.assertAlmostEqual(r["pace_p"][c], round(v, 3), places=9)
        # pace_why.ten は D のテン(ふだんとの差の秒)
        # 1= (−0.4 −0.5 −0.1 +0.2)/4・2= 直近 5 走(1100m は除く)(0.8+0.4+0.9+0.1+0.6)/5・3= 金沢だけ 3 走・4= 2 走で出さない
        self.assertEqual(r["pace_why"]["ten"], [[1, -0.2], [3, 0.3], [2, 0.56]])
        self.assertEqual(r["pace_why"]["lead"], 1)
        self.assertEqual(r["pace_why"]["front"], 2)
        # 未来の走(発走日当日・後の日)を抜いても同じ
        cut = {k: [x for x in v if x["race_date"] < d] for k, v in past.items()}
        got2, _ = tk.build_races(races, runs, cut, sty, ({}, {}, {}, None), {"大井": mp},
                                 (d, tk.d_values([x for v in cut.values() for x in v], dist), std))
        self.assertEqual(got2, got)

    def test_build_writes_d_coef(self):
        recs = [dict(r, fd=r["f"], f=tk.pace_feat({}, [], [])) for r in fake_recs()]
        v = pm.build(recs, "2026-12", tracks=("大井",))
        self.assertEqual(v["ten"], "d")
        self.assertEqual(v["tracks"]["大井"], dict(pm.export(pp.fit_model(recs, "fd")),
                                                  n_train=len(recs), wf=v["tracks"]["大井"]["wf"]))


if __name__ == "__main__":
    unittest.main()

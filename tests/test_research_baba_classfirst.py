# -*- coding: utf-8 -*-
"""研究便 research_baba_classfirst の通し試験(作り物の REST・⛔通信ゼロ)。
落ちずに result.md の全章が書けること・A が build_days(going)と同じ値で照合 100% になることだけ見る。

  py -3 -m unittest discover -s tests -p "test_research_baba_classfirst.py"
"""
import datetime as dt
import os
import random
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud"))
    import research_baba_classfirst as R  # noqa: E402
    import baba  # noqa: E402

TODAY = dt.date(2026, 10, 25)


def make_data():
    rnd = random.Random(7)
    races, runs = [], []
    names = ["C1", "C2", "B1", "A1", "2歳", "", "オープン"]
    for track in ("金沢", "大井"):
        horses = [f"{track}馬{i}" for i in range(60)]
        d = dt.date(2022, 6, 1)
        while d <= dt.date(2026, 10, 20):
            ds = d.isoformat()
            going = rnd.choice(["良", "良", "稍重", "重", "不良"])
            eff = rnd.gauss(0, 1)
            for r in range(1, 7):
                dist = rnd.choice([1400, 1500])
                nm = rnd.choice(names)
                races.append({"track": track, "race_date": ds, "race_no": r, "distance_m": dist,
                              "race_name": nm, "going": going, "race_kind": None})
                for f, h in enumerate(rnd.sample(horses, 8), start=1):
                    runs.append({"track": track, "race_date": ds, "race_no": r, "runner_number": f,
                                 "finish": f, "time_sec": round(60 + dist / 100 + 0.3 * f + eff + rnd.gauss(0, .3), 1),
                                 "finish_note": None, "horse_name": h, "birth_date": "2020-04-01"})
            d += dt.timedelta(days=3)
    return races, runs


class FakeRest:
    def __init__(self):
        self.races, self.runs = make_data()
        self.meta = None

    def _filter(self, rows, q):
        qs = urllib.parse.parse_qsl(q.split("?", 1)[1])
        out = rows
        for k, v in qs:
            if k in ("select", "order", "limit", "offset"):
                continue
            op, val = v.split(".", 1)
            if k == "track":
                out = [r for r in out if r["track"] == val]
            elif k == "race_date":
                out = [r for r in out if (r["race_date"] >= val if op == "gte" else r["race_date"] <= val)]
            elif k == "finish" and op in ("gte", "lte"):
                out = [r for r in out if r["finish"] is not None
                       and (r["finish"] >= int(val) if op == "gte" else r["finish"] <= int(val))]
        return out

    def paged(self, q, order):
        return self._filter(self.races if q.startswith("nar_races") else self.runs, q)

    def get(self, q):
        return [{"value": self.meta}] if self.meta else []

    def req(self, path, *a, **k):
        raise urllib.error.HTTPError(path, 404, "nf", None, None)


@unittest.skipUnless(HAVE, "numpy/pandas が無い")
class ResearchSmokeTest(unittest.TestCase):
    def test_runs_and_writes(self):
        rest = FakeRest()
        # 本番 blob の代わり= build_days(going) で組んだ直近の値(照合 100% になるはず)
        smp = [s for t in ("金沢", "大井") for s in R.baba_hist.to_samples(
            t, [w for w in rest.runs if w["track"] == t and w["finish"] <= 5],
            [r for r in rest.races if r["track"] == t])]
        tg = {s[1] for s in smp if "2026-07-28" <= s[1] <= "2026-09-27"}
        days, _, _ = baba.build_days(smp, tg, "going", today=TODAY, rebuild_all=True)
        rest.meta = {"base": "going", "days": days}
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "result.md")
            self.assertEqual(R.run(rest, out_path=out, nb=20, today=TODAY, log=lambda s: None), 0)
            with open(out, encoding="utf-8") as f:
                txt = f.read()
        for h in ("## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## まとめ"):
            self.assertIn(h, txt)
        self.assertIn("(100.0%)", txt.split("## 6.")[1].split("## 5.")[0])
        self.assertIn("C クラス優先・帯なしは外す", txt)
        self.assertNotIn("組が無かった", txt)


if __name__ == "__main__":
    unittest.main()

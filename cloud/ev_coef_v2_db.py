# -*- coding: utf-8 -*-
"""ev_coef:v2 の材料(DB 分)。cloud/ev_coef_time_audit.py と同じ集め方で、区分だけ 0-5 / 5-10 / 10-20 / 20-30 / 30-60 / 60+ に変える。
便 .github/workflows/ev-coef-v2-db.yml(手動だけ)。⛔読むだけ・nar_meta に書かない・出力は値の並びと件数だけ(成果物・commit しない)。

  python3 cloud/ev_coef_v2_db.py --from 2026-09-02 --to 2026-10-24 --out out/ev_coef_v2_db
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev_coef_time_audit as T  # noqa: E402

T.SEGS = (('0-5', 0, 5), ('5-10', 5, 10), ('10-20', 10, 20), ('20-30', 20, 30), ('30-60', 30, 60), ('60+', 60, 10 ** 6))
T.UA = "nar-jobs ev_coef_v2_db"

if __name__ == "__main__":
    sys.exit(T.main())

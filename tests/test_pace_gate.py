# -*- coding: utf-8 -*-
"""§224 段 2b ゲート試験の材料の検算(通信ゼロ)。

  py -3.12 -m unittest discover -s tests -p "test_pace_gate*.py"

  ①暗号を戻すと元に戻る ②lift の窓に m 以降の月が混ざらない
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud"))

import pace_gate_dump as G                                         # noqa: E402


class T(unittest.TestCase):
    def test_roundtrip(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        data = "走|高知|2026-05-01|3".encode("utf-8") * 1000
        blob = G.encrypt(data, k.public_key())
        self.assertNotIn(data[:20], blob)
        self.assertEqual(G.decrypt(blob, k), data)

    def test_no_future(self):
        self.assertEqual(G.prev_months("2026-01")[0], "2025-01")
        self.assertEqual(G.prev_months("2026-01")[-1], "2025-12")
        cell = ("kochi", 1400, "逃げ", "速い")
        past = ({("kochi", 1400): [100, 30]}, {cell: [50, 30]})          # lift= 0.6/0.3= 2.0
        future = ({("kochi", 1400): [100000, 0]}, {cell: [100000, 0]})   # 混ざれば lift が崩れる
        monthly = {"2025-06": past, "2026-01": future, "2026-02": future}
        self.assertAlmostEqual(G.lift_table(monthly, "2026-01")[cell], 2.0)
        self.assertEqual(G.lift_table({"2026-01": future}, "2026-01"), {})


if __name__ == "__main__":
    unittest.main()

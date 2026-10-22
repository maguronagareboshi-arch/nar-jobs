# -*- coding: utf-8 -*-
"""研究用・§224 段 2b のゲート試験の材料(⛔本番 DB には書かない・読むだけ)。

各月 m(既定 2025-09〜2026-08)の走ごとに 着順・真のペース・見立てのペース(あれば)・lift(実)・lift(見立て)
を並べ、**暗号にして** 1 つのファイルに出す。log loss は手元(AI の 1 着見込みは PC の外に出さない)で数える。

  lift は m より**前の 12 か月**の実走だけで数える(⛔未来混入なし)。数え方は cloud/pace_lift.py の
  count / pack をそのまま使う(20 走未満の枡は lift=None のまま出す= 1.0 扱いは手元で)。
  見立てのペース= nar_meta `tenkai:YYYY-MM-DD` の races["<場>-<R>"].pace(予想時点の値・無ければ None)。
  rid= "場|YYYY-MM-DD|R"(~/ai_v1/wf1_win_pred.parquet の rid と同じ形)。

⛔nar-jobs は PUBLIC= 走ごとの値は平文で log にも artifact にも出さない。出すのは件数だけ。
  暗号= gzip(JSON) を AES-256-GCM で包み、その鍵を RSA-OAEP(SHA-256)で公開鍵に包む。
  形= b"PG1" + 包んだ鍵の長さ(2 バイト)+ 包んだ鍵 + nonce(12)+ 暗号文

  python cloud/pace_gate_dump.py --pubkey "<PEM か DER の base64>" --out pace_gate.bin
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
"""
import argparse
import base64
import datetime as dt
import gzip
import json
import os
import struct
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pace_lift as PL                                             # noqa: E402
from tenkai import TRACK2PREFIX                                    # noqa: E402

MAGIC = b"PG1"
TEST_FROM, TEST_TO = "2025-09", "2026-08"


# ---------------------------------------------------------------- 暗号

def load_pub(text):
    from cryptography.hazmat.primitives import serialization
    t = text.strip()
    if t.startswith("-----"):
        return serialization.load_pem_public_key(t.encode("ascii"))
    return serialization.load_der_public_key(base64.b64decode("".join(t.split())))


def encrypt(data, pub):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    k = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = AESGCM(k).encrypt(nonce, gzip.compress(data), MAGIC)
    wrapped = pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                          algorithm=hashes.SHA256(), label=None))
    return MAGIC + struct.pack(">H", len(wrapped)) + wrapped + nonce + ct


def decrypt(blob, priv):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    if blob[:3] != MAGIC:
        raise ValueError("形が違う")
    n = struct.unpack(">H", blob[3:5])[0]
    wrapped, nonce, ct = blob[5:5 + n], blob[5 + n:17 + n], blob[17 + n:]
    k = priv.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                           algorithm=hashes.SHA256(), label=None))
    return gzip.decompress(AESGCM(k).decrypt(nonce, ct, MAGIC))


# ---------------------------------------------------------------- 窓(未来混入なし)

def prev_months(m, n=PL.MONTHS):
    """'YYYY-MM' → その月より**前**の n か月(古い順)。m 自身は入れない"""
    y, mo = (int(x) for x in m.split("-"))
    out = []
    for _ in range(n):
        y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
        out.append("%04d-%02d" % (y, mo))
    return out[::-1]


def lift_table(monthly, m):
    """月ごとの数 {月: (base, cells)} → m の lift 表 {(場, 帯, 脚質, ペース): lift or None}。
    ⛔使うのは prev_months(m) だけ(m 以降の月は見ない)"""
    base, cells = {}, {}
    for pm in prev_months(m):
        if pm not in monthly:
            continue
        b, c = monthly[pm]
        for k, (n, t) in b.items():
            x = base.setdefault(k, [0, 0]); x[0] += n; x[1] += t
        for k, (n, t) in c.items():
            x = cells.setdefault(k, [0, 0]); x[0] += n; x[1] += t
    if not cells:
        return {}
    v = PL.pack(base, cells, [(m, "", "")], "")
    out = {}
    for k, e in v["cells"].items():
        pre, b, st, pa = k.split("|")
        out[(pre, int(b), st, pa)] = e["lift"]
    return out


# ---------------------------------------------------------------- 読む

def forecast_paces(api, key, lo, hi):
    """nar_meta tenkai:日付 → {(場, 日付, R): 見立てのペース}。⛔値が無い日は何も返さない"""
    pre2tr = {v: k for k, v in TRACK2PREFIX.items()}
    d, end, out = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi), {}
    while d <= end:
        days = [(d + dt.timedelta(days=i)) for i in range(7) if d + dt.timedelta(days=i) <= end]
        keys = ",".join(urllib.parse.quote('"tenkai:%s"' % x.isoformat()) for x in days)
        _st, _cr, body = PL.req(api, key, "/rest/v1/nar_meta?select=key,races:value->races&key=in.(%s)" % keys)
        for row in json.loads(body):
            day = row["key"].split(":", 1)[1]
            for rk, rec in (row.get("races") or {}).items():
                if not isinstance(rec, dict) or rec.get("pace") not in PL.PACES:
                    continue
                pre, _, no = rk.rpartition("-")
                if pre in pre2tr and no.isdigit():
                    out[(pre2tr[pre], day, int(no))] = rec["pace"]
        d += dt.timedelta(days=7)
    return out


def month_rows(paces, races, facts, runs, fpace, lifts):
    """1 か月の走 → 出す行。lift は lifts(その月の表= 前 12 か月)から引く"""
    pace_of = {(r["track"], r["race_date"], int(r["race_no"])): r.get("pace")
               for r in paces if r.get("pace") in PL.PACES}
    race_of = {}
    for r in races:
        tr = r.get("track")
        if tr in TRACK2PREFIX and r.get("distance_m") is not None:
            b = PL.band_of(r["distance_m"])
            if b is not None:
                race_of[(tr, r["race_date"], int(r["race_no"]))] = (TRACK2PREFIX[tr], b)
    style_of = {(r["track"], r["race_date"], int(r["race_no"]), int(r["umaban"])): r.get("style")
                for r in facts if r.get("style") in PL.STYLES}
    out = []
    for r in runs:
        u = r.get("runner_number")
        if u is None:
            continue
        rk = (r["track"], r["race_date"], int(r["race_no"]))
        pa, pf, cell = pace_of.get(rk), fpace.get(rk), race_of.get(rk)
        st = style_of.get(rk + (int(u),))
        fin = r.get("finish")
        f = int(fin) if isinstance(fin, int) or (isinstance(fin, str) and fin.isdigit()) else None
        lt = lifts.get(cell + (st, pa)) if (cell and st and pa) else None
        lf = lifts.get(cell + (st, pf)) if (cell and st and pf) else None
        out.append(["%s|%s|%d" % rk, int(u), f, pa, pf, st, lt, lf])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pubkey", required=True)
    ap.add_argument("--out", default="pace_gate.bin")
    ap.add_argument("--from", dest="m_from", default=TEST_FROM)
    ap.add_argument("--to", dest="m_to", default=TEST_TO)
    a = ap.parse_args()
    api = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not api or not key:
        PL.log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    pub = load_pub(a.pubkey)
    tests = PL.month_range(a.m_from, a.m_to)
    allm = PL.month_range(prev_months(tests[0][0])[0], a.m_to)
    test_names = {t[0] for t in tests}
    monthly, raw = {}, {}
    for name, lo, hi in allm:
        t0 = time.time()
        paces = PL.window(api, key, PL.PACE_TMPL, lo, hi)
        races = PL.window(api, key, PL.RACE_TMPL, lo, hi)
        facts = PL.window(api, key, PL.FACT_TMPL, lo, hi)
        runs = PL.window(api, key, PL.RUN_TMPL, lo, hi)
        monthly[name] = PL.count(paces, races, facts, runs)
        if name in test_names:
            raw[name] = (paces, races, facts, runs, forecast_paces(api, key, lo, hi))
        PL.log("  %s  pace %5d / race %5d / facts %6d / run %6d  %.1f 秒"
               % (name, len(paces), len(races), len(facts), len(runs), time.time() - t0))
    rows, summary = [], []
    for name, _lo, _hi in tests:
        lifts = lift_table(monthly, name)
        paces, races, facts, runs, fp = raw[name]
        rs = month_rows(paces, races, facts, runs, fp, lifts)
        rows.extend(rs)
        summary.append((name, len(rs), sum(1 for x in rs if x[6] is not None),
                        len(fp), sum(1 for x in rs if x[7] is not None)))
    for s in summary:      # ⛔件数だけ(走ごとの値は出さない)
        PL.log("  %s  走 %6d / lift(実)あり %6d / 見立てのあるレース %4d / lift(見立て)あり %6d" % s)
    data = json.dumps({"cols": ["rid", "runner_number", "finish", "pace", "pace_f", "style",
                                "lift", "lift_f"], "rows": rows,
                       "months": [tests[0][0], tests[-1][0]], "min_n": PL.CELL_MIN},
                      ensure_ascii=False).encode("utf-8")
    blob = encrypt(data, pub)
    open(a.out, "wb").write(blob)
    PL.log("  → %s(%d 行・暗号 %d バイト)" % (a.out, len(rows), len(blob)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

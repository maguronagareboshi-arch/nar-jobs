# -*- coding: utf-8 -*-
"""馬主・生産者の名寄せ表 nar_name_alias を作る(2026-10-02・規則は nar-site/research/owner-breeder/name_rules.md)。

  build(rows, manual) → [(kind, alias, canonical)]
    rows   = [(kind, 表記, 頭数, 直近2年の頭数)]   nar_horse_profiles の owner / breeder
    manual = [(kind, 表記A, 表記B)]               ob_alias_manual.csv(手で承認した 27 組)

寄せ方(3 段のうち自動は L1 と会社の形の書き方・生産者だけ会社の形の有無):
  L1  NFKC・空白を全部消す・英字は小文字
  A   L1 の上で (株)(有)(同)(資)(名) を 株式会社 等に書き直した鍵が同じ
  B   生産者だけ= 会社の形を全部消した鍵が同じ かつ 3 文字以上
  C   旧字・有限→株式・個人/法人 は自動にしない= manual だけ
代表表記= 組の中で 直近2年の頭数 → 頭数 → 表記 の順で最大の表記を NFKC(前後の空白は落とす)。
⛔標準ライブラリだけ。
"""
import csv
import os
import re
import unicodedata

FORM_ABBR = {"(株)": "株式会社", "(有)": "有限会社", "(同)": "合同会社", "(資)": "合資会社", "(名)": "合名会社"}
FORMS = ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "(株)", "(有)", "(同)", "(合)", "(資)", "(名)")
HERE = os.path.dirname(os.path.abspath(__file__))
MANUAL = os.path.join(HERE, "ob_alias_manual.csv")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def key_l1(s):
    return re.sub(r"\s+", "", nfkc(s)).lower()


def key_a(s):
    k = key_l1(s)
    for a, full in FORM_ABBR.items():
        k = k.replace(a, full)
    return k


def key_b(s):
    k = key_l1(s)
    for f in FORMS:
        k = k.replace(f, "")
    return k


def load_manual(path=MANUAL):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [(r["kind"], r["a"], r["b"]) for r in csv.DictReader(f)]


def build(rows, manual):
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    stat = {}
    for kind, raw, n, recent in rows:
        if not raw or not nfkc(raw):
            continue
        stat[(kind, raw)] = (int(recent or 0), int(n or 0))
        parent[(kind, raw)] = (kind, raw)
    by_key = {}
    for kind, raw in stat:
        first = by_key.setdefault((kind, key_a(raw)), (kind, raw))
        union(first, (kind, raw))
    # B= 会社の形の「無い」表記と「有る」表記だけを結ぶ(有限↔株式のような形どうしは結ばない= C)
    bare = {}
    for kind, raw in stat:
        kb = key_b(raw)
        if kind == "breeder" and len(kb) >= 3 and kb == key_l1(raw):
            bare.setdefault(kb, (kind, raw))
    for kind, raw in stat:
        kb = key_b(raw)
        if kind == "breeder" and len(kb) >= 3 and kb != key_l1(raw) and kb in bare:
            union(bare[kb], (kind, raw))
    # 手で承認した組= L1 の鍵で表記に当てる(全角半角・空白の揺れがあっても当たる)
    l1 = {}
    for kind, raw in stat:
        l1.setdefault((kind, key_l1(raw)), []).append((kind, raw))
    missing = []
    for kind, a, b in manual:
        ga, gb = l1.get((kind, key_l1(a)), []), l1.get((kind, key_l1(b)), [])
        if not ga or not gb:
            missing.append((kind, a, b))
            continue
        for x in ga + gb:
            union(ga[0], x)
    groups = {}
    for x in stat:
        groups.setdefault(find(x), []).append(x)
    out = []
    for members in groups.values():
        best = max(members, key=lambda x: (stat[x][0], stat[x][1], x[1]))
        canon = nfkc(best[1])
        for kind, raw in members:
            out.append((kind, raw, canon))
    out.sort()
    return out, missing

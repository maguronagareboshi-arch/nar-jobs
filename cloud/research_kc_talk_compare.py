"""研究用(11/1): 集計 A と B の突き合わせ。docs/research-kc-talk/result_a.csv と result_b.csv を全セルで比べ、
差が 0.001 を超えるセル(片方だけ空も含む)を docs/research-kc-talk/compare.md に書く。B が無ければ「B なし」。"""
import csv
import os
import sys

D = "docs/research-kc-talk"


def load(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    v = (v or "").strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return v


def main():
    pa, pb, out = os.path.join(D, "result_a.csv"), os.path.join(D, "result_b.csv"), os.path.join(D, "compare.md")
    lines = ["# 集計 A と B の突き合わせ", ""]
    if not os.path.exists(pb):
        lines.append("B なし")
        n = None
    else:
        a, b = load(pa), load(pb)
        ia = {r["key"]: r for r in a}
        ib = {r["key"]: r for r in b}
        cols = list(a[0].keys()) if a else []
        diffs = []
        for c in sorted(set(cols) ^ set(b[0].keys() if b else [])):
            diffs.append(("(列)", c, "A にある" if c in cols else "", "B にある" if c not in cols else ""))
        for k in sorted(set(ia) | set(ib)):
            if k not in ia or k not in ib:
                diffs.append((k, "(行)", "あり" if k in ia else "なし", "あり" if k in ib else "なし"))
                continue
            for c in cols:
                if c == "key" or c not in ib[k]:
                    continue
                x, y = num(ia[k][c]), num(ib[k][c])
                if x is None and y is None:
                    continue
                if (x is None) != (y is None) or isinstance(x, str) or isinstance(y, str):
                    if x != y:
                        diffs.append((k, c, ia[k][c], ib[k][c]))
                elif abs(x - y) > 0.001:
                    diffs.append((k, c, ia[k][c], ib[k][c]))
        n = len(diffs)
        lines.append(f"差が 0.001 を超えるセル: {n}(行 A {len(a)}・B {len(b)})")
        if diffs:
            lines += ["", "| 鍵 | 列 | A | B |", "|---|---|---|---|"]
            lines += [f"| {k} | {c} | {x} | {y} |" for k, c, x, y in diffs]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

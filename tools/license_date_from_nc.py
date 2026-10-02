# -*- coding: utf-8 -*-
"""一回便(PC で 1 回)= KDSCOPE NC(調教師台帳)の免許日 → nar_persons.license_date の SQL を書き出す(2026-10-02)。

  py -3.12 tools/license_date_from_nc.py <NC.DAT> <出力.sql> [<見るだけ.sql>]

突き合わせ= 生年月日が同じ かつ 略称の先頭 1 字が同じ(旧字 齊櫻廣濱 は 斉桜広浜 に寄せる)で 1 人に決まる調教師だけ。
  NC のコードは免許番号と別物なのでコードでは引かない(nar-site/mock/trainer/nc_match.py と同じ)。
  当てるのは SQL の中(nar_persons 側は本番の今の行)= 名簿の写しを持たない。
出力.sql= UPDATE(本体が「手動」モードで流す・owner_breeder_20261002.sql の後)。
見るだけ.sql= 同じ当て方の SELECT(件数だけ・本番で読み取りとして流せる)。
⛔本番には書かない(この台本は SQL を書くだけ)。
"""
import sys
import unicodedata

L = 5098
OLD = str.maketrans("齊櫻廣濱", "斉桜広浜")


def head(s):
    return unicodedata.normalize("NFKC", s).replace(" ", "").translate(OLD)[:1]


def read_nc(path):
    out = []
    with open(path, "rb") as f:
        while True:
            r = f.read(L)
            if len(r) < L:
                break
            if r[:2] != b"NC":
                continue
            g = lambda o, n: r[o:o + n].decode("cp932", "replace").strip().replace("　", "")
            lic, birth, abbr = g(17, 8), g(33, 8), g(105, 8)
            if len(lic) == 8 and lic.isdigit() and lic != "00000000" and len(birth) == 8 and birth.isdigit() and abbr:
                out.append((f"{birth[:4]}-{birth[4:6]}-{birth[6:]}", head(abbr), f"{lic[:4]}-{lic[4:6]}-{lic[6:]}"))
    return sorted(set(out))


def cte(nc):
    vals = ",\n".join(f"  (date '{b}', '{h}', date '{d}')" for b, h, d in nc)
    return (f"with nc(birth, head, lic) as (values\n{vals}\n),\n"
            "cand as (select p.license_no, n.lic from public.nar_persons p join nc n on n.birth = p.birth\n"
            "  and n.head = left(translate(normalize(replace(replace(p.name_short, ' ', ''), '　', ''), NFKC), '齊櫻廣濱', '斉桜広浜'), 1)\n"
            "  where p.kind = 'trainer'),\n"
            "one as (select license_no, min(lic) as lic from cand group by license_no having count(distinct lic) = 1)\n")


def main(ncp, out, check=None):
    nc = read_nc(ncp)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"-- 2026-10-02 KDSCOPE NC の免許日 → nar_persons.license_date(tools/license_date_from_nc.py で生成・NC {len(nc)} 行)\n")
        f.write("begin;\n" + cte(nc) +
                "update public.nar_persons p set license_date = one.lic from one\n"
                " where p.kind = 'trainer' and p.license_no = one.license_no;\ncommit;\n")
    if check:
        with open(check, "w", encoding="utf-8", newline="\n") as f:
            f.write(cte(nc) + "select (select count(*) from public.nar_persons where kind = 'trainer') as trainers,\n"
                    "  (select count(*) from one) as decided,\n"
                    "  (select count(distinct license_no) from cand) - (select count(*) from one) as many;\n")
    print(f"NC {len(nc)} 行 → {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])

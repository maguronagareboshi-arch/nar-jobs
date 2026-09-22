# -*- coding: utf-8 -*-
"""§240 の移行 SQL から「節」だけを切り出して stdout に出す(⛔DB には触らない・文字を切るだけ)。

なぜ要るか= 1 表ぶんの SQL は §0 読みの確認から §5 の掃除まで 1 ファイルに入っている。本番へは
**節ごとに**当てる(1 ステップ 1 トランザクション・間に人が結果を見る)。psql に渡すのはその節だけ。

節の見出しは 2 行組= `-- ====…` の次の行が `-- §<番号> …`。番号は 0 / 1 / 2 / 4' / 3' / 5。
入力の番号は `4` と書けば `4'`、`3` と書けば `3'` として探す(GitHub Actions の入力が書きやすいように)。

使い方:
  py -3.12 pipeline/sql/partition_s240/run_section.py 40_nar_runs.sql 2        # §2 だけ
  py -3.12 pipeline/sql/partition_s240/run_section.py 40_nar_runs.sql 4        # §4' だけ
  py -3.12 pipeline/sql/partition_s240/run_section.py 99_verify.sql            # 節を指定しない= 全部

出す先頭に `\\timing on` を付ける(Actions のログに各文の所要が出る)。
⛔切り出した中で `vacuum` がトランザクションの中に入っていたら、流す前にここで落とす
  (psql の中で `vacuum` をトランザクションに入れると必ず失敗する)。
"""
import io
import os
import re
import sys

HEAD = re.compile(r"^--\s*§([0-9])('?)\s")
BANNER = re.compile(r"^--\s*=====")


def find_sections(lines):
    """[(節の番号, 開始行, 終了行)] を返す。開始は `-- ====` の行。"""
    marks = []
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if m and i > 0 and BANNER.match(lines[i - 1]):
            marks.append((m.group(1) + m.group(2), i - 1))
    out = []
    for k, (sec, start) in enumerate(marks):
        end = marks[k + 1][1] if k + 1 < len(marks) else len(lines)
        out.append((sec, start, end))
    return out


def pick(text, section):
    """節を切り出す。section が None / '' なら全部。"""
    lines = text.split("\n")
    if not section:
        return text
    secs = find_sections(lines)
    if not secs:
        raise SystemExit("節の見出し(`-- ====` + `-- §N`)が 1 つも無い= 節を指定できないファイル")
    want = str(section).strip()
    cands = [want]
    if want in ("3", "4"):            # 入力は 3 / 4 でも、ファイルの見出しは 3' / 4'
        cands.append(want + "'")
    for c in cands:
        for sec, start, end in secs:
            if sec == c:
                return "\n".join(lines[start:end]).rstrip() + "\n"
    raise SystemExit("§%s が無い。あるのは= %s" % (want, " / ".join(s for s, _, _ in secs)))


def check_vacuum_outside_tx(sql, where=""):
    """⛔vacuum がトランザクションの中に無いこと。begin/commit は行頭のものだけ数える。"""
    depth = 0
    for i, raw in enumerate(sql.split("\n"), start=1):
        line = re.sub(r"--.*$", "", raw).strip().lower()
        if re.match(r"^begin\s*;", line):
            depth += 1
        elif re.match(r"^commit\s*;", line):
            depth = max(0, depth - 1)
        elif line.startswith("vacuum") and depth > 0:
            raise SystemExit("%s%d 行目の vacuum がトランザクションの中にある= 流す前に止めた" % (where, i))
    if depth != 0:
        raise SystemExit("%s閉じていない begin が %d 個ある= 流す前に止めた" % (where, depth))
    return True


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    path = argv[1]
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    section = argv[2] if len(argv) > 2 else None
    text = io.open(path, encoding="utf-8").read()
    out = pick(text, section)
    check_vacuum_outside_tx(out, where="%s §%s の " % (os.path.basename(path), section or "all"))
    sys.stdout.write("\\timing on\n\\set ON_ERROR_STOP on\n")
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

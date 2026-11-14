"""便(.github/workflows/*.yml)の守りの検査(2026-11-14 総合レビュー security #13)。⛔通信なし= ファイルの字だけを見る。
1) どの便にも一番上の階層に permissions がある(無いと repo の既定の権限に任せることになる)。
2) 手で起こすときの入力(inputs)を、スクリプトの中に直に埋めない(env を通してから使う)。
   型が選択肢・真偽だけの 2 か所は、入れられる字が決まっているので今のまま認める。"""
import re
from pathlib import Path

WF = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
KEY_LINE = re.compile(r"^\s*(- )?([A-Za-z_][A-Za-z0-9_-]*):(\s|$)")
INPUT = re.compile(r"\$\{\{[^}]*\b(github\.event\.inputs|inputs)\.")
ALLOW = {("auction.yml", 'MODE="${{ github.event.inputs.mode }}"'),      # type: choice
         ("monbetsu-class.yml", 'if [ "${{ inputs.force }}" = "true" ]; then')}   # type: boolean


def test_there_are_workflows():
    assert len(WF) >= 100


def test_every_workflow_has_top_level_permissions():
    missing = [p.name for p in WF if not re.search(r"(?m)^permissions:", p.read_text(encoding="utf-8"))]
    assert missing == [], "permissions が無い便: " + ", ".join(missing)


def test_no_write_all():
    bad = [p.name for p in WF if re.search(r"(?m)^permissions:\s*write-all", p.read_text(encoding="utf-8"))]
    assert bad == [], "write-all の便: " + ", ".join(bad)


def test_inputs_are_not_embedded_in_scripts():
    bad = []
    for p in WF:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not INPUT.search(line) or line.lstrip().startswith("#"):
                continue
            m = KEY_LINE.match(line)
            if m and m.group(2) != "run":
                continue                      # env・if・with・group など「鍵: 値」の行= スクリプトの外
            if (p.name, line.strip()) in ALLOW:
                continue
            bad.append(f"{p.name}:{i} {line.strip()[:80]}")
    assert bad == [], "入力をスクリプトに直に埋めている: " + " / ".join(bad)

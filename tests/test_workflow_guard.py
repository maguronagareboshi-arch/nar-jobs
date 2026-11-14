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


# 2026-11-14 総合レビュー #15。字だけ= yaml を読むだけ(通信なし)。pyyaml は "on" を True と読む。
def _load(p):
    import yaml
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def test_scheduled_workflows_have_concurrency():
    """定期便(schedule あり)は concurrency を持つ(前の回が長引いて重なるのを防ぐ)。"""
    bad = []
    for p in WF:
        d = _load(p)
        on = d.get("on", d.get(True)) or {}
        if isinstance(on, dict) and "schedule" in on and "concurrency" not in d:
            bad.append(p.name)
    assert bad == [], "concurrency が無い定期便: " + ", ".join(bad)


def test_jobs_have_timeout():
    """job は timeout-minutes を持つ(無いと既定の 360 分)。他の便の呼び出し(uses:)は持てないので除く。"""
    bad = []
    for p in WF:
        for name, job in (_load(p).get("jobs") or {}).items():
            if isinstance(job, dict) and "uses" not in job and "timeout-minutes" not in job:
                bad.append(f"{p.name}:{name}")
    assert bad == [], "timeout-minutes が無い job: " + ", ".join(bad)

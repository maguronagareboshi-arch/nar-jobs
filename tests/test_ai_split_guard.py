# -*- coding: utf-8 -*-
"""2026-11-27 予想のコード(pipeline/ai)を非公開の置き場 nj-core へ切った後の守り。
公開の置き場に予想のコードが戻っていないか・便が非公開の中身を取る段を持つかを見る(通信も鍵も使わない)。
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
STOPPED = "非公開の置き場 nj-core へ切った"   # 止めてある便の頭の注意書き


def _jobs(text):
    """便の定義を job ごとの字に分ける(jobs: の下の 2 字下げの名前で切る)。"""
    body = text.split("\njobs:", 1)[1] if "\njobs:" in text else ""
    parts = re.split(r"\n  ([A-Za-z0-9_-]+):\s*\n", "\n" + body)
    return dict(zip(parts[1::2], parts[2::2]))


def test_no_ai_code_tracked():
    out = subprocess.run(["git", "ls-files", "pipeline/ai"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "", "公開の置き場に pipeline/ai が戻っている: " + out[:300]


def test_ai_ref_is_sha():
    sha = (ROOT / "ops" / "ai_ref.txt").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9a-f]{40}", sha)


def test_jobs_using_ai_code_fetch_it():
    bad = []
    for f in sorted(WF.glob("*.yml")):
        t = f.read_text(encoding="utf-8")
        if STOPPED in t.splitlines()[0]:
            continue
        assert "mode: fallback" not in t, f"{f.name}: 移行中の逃げ道 mode: fallback が残っている"
        for job, s in _jobs(t).items():
            uses = [ln for ln in s.splitlines() if "pipeline/ai/" in ln and not ln.strip().startswith("#")]
            if uses and "./.github/actions/ai-code" not in s:
                bad.append(f"{f.name}:{job}")
    assert not bad, "予想のコードを使うのに ai-code の段が無い: " + ", ".join(bad)


def test_artifacts_do_not_carry_code():
    bad = []
    for f in sorted(WF.glob("*.yml")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            if re.search(r"uses:\s*actions/(upload-artifact|cache)", ln):
                for nxt in lines[i + 1:i + 12]:
                    m = re.match(r"\s*path:\s*(.*)", nxt)
                    if m:
                        p = m.group(1).strip().strip("'\"")
                        if p in (".", "./") or "pipeline" in p or "_ai" in p:
                            bad.append(f"{f.name}:{i + 1} {p}")
    assert not bad, "成果物・cache にコードの道: " + ", ".join(bad)

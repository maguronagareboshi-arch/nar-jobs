#!/usr/bin/env bash
# 2026-10-30 直前の便の自動の回し直し(DB の時計 private.nar_live_guard が guard=yes で起こす)の入口の点検。
#   10/29 12:29 JST に nar-ai-last・v3-gap-live が GitHub 側の内部エラーで消え、午後の便まで 2.5 時間抜けた
#   (nankan-ai-v3 out/incident_20261029_last.md)。生存の記録が途切れても便が本当は生きていることがある
#   (土台の待ち・GitHub の表示の遅れ)= 同じ便がまだ動いている/待っているなら回し直さない(go=no)。
#   一覧が取れないときは回す(抜けより 2 重のほうがまし)。
#   使い方: bash ops/live_guard_check.sh nar-ai-last.yml   → $GITHUB_OUTPUT に go=yes|no
set -u
WF="$1"
N=$(gh run list -R "$GITHUB_REPOSITORY" -w "$WF" -L 30 --json databaseId,status \
      --jq "[.[] | select(.status != \"completed\" and .databaseId != $GITHUB_RUN_ID)] | length" 2>/dev/null) || N=""
if ! [[ "$N" =~ ^[0-9]+$ ]]; then
  echo "::warning::$WF の便の一覧が取れない = 回し直す"
  echo "go=yes" >> "$GITHUB_OUTPUT"
elif [ "$N" -gt 0 ]; then
  echo "$WF はまだ $N 本動いている/待っている = 回し直さない"
  echo "go=no" >> "$GITHUB_OUTPUT"
else
  echo "$WF は動いていない = 回し直す"
  echo "go=yes" >> "$GITHUB_OUTPUT"
fi

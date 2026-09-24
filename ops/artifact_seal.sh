#!/usr/bin/env bash
# 監査 A3(2026-09-24): 公開 repo の成果物は GitHub にログインした誰でも落とせる= 置く前に暗号化し、受け取る側で戻す。
# 鍵は新しい secret を作らず、便の中で既存の SUPABASE_SERVICE_KEY から作る(sha256 の 64 桁)。
#   bash ops/artifact_seal.sh seal <元のフォルダ> <出す先.tar.gz.enc>   … フォルダの中身を 1 つにまとめて暗号化
#   bash ops/artifact_seal.sh unseal <フォルダ>                         … 下にある *.tar.gz.enc を同じ場所へ戻して消す
#     ⛔暗号化されていない古い成果物(.enc が無い)はそのまま= 何もしない。
# 手元で戻す(1 行):
#   ARTIFACT_KEY=$(printf '%s' "$SUPABASE_SERVICE_KEY" | sha256sum | cut -c1-64) openssl enc -d -aes-256-cbc -pbkdf2 -pass env:ARTIFACT_KEY -in X.tar.gz.enc | tar -xzf -
set -euo pipefail
: "${SUPABASE_SERVICE_KEY:?SUPABASE_SERVICE_KEY が無い(step の env に渡すこと)}"
ARTIFACT_KEY=$(printf '%s' "$SUPABASE_SERVICE_KEY" | sha256sum | cut -c1-64)
export ARTIFACT_KEY
case "${1:-}" in
  seal)
    src=$2; out=$3
    [ -d "$src" ] || { echo "seal: $src が無い"; exit 1; }
    mkdir -p "$(dirname "$out")"
    tar -C "$src" -czf - . | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:ARTIFACT_KEY -out "$out"
    ls -l "$out"
    ;;
  unseal)
    dir=$2; n=0
    while IFS= read -r -d '' f; do
      openssl enc -d -aes-256-cbc -pbkdf2 -pass env:ARTIFACT_KEY -in "$f" | tar -C "$(dirname "$f")" -xzf -
      rm -f "$f"; n=$((n+1))
    done < <(find "$dir" -type f -name '*.tar.gz.enc' -print0)
    echo "unseal: $n 個を戻した(0= 平文の古い成果物なのでそのまま使う)"
    ;;
  *) echo "usage: $0 seal <dir> <out.tar.gz.enc> | unseal <dir>"; exit 2 ;;
esac

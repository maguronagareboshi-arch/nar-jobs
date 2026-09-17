#!/usr/bin/env bash
# §196b 逆算の材料を本番 DB(nar-official)から 1 回の接続で手元へ(⛔読むだけ・重い計算はしない)。
#   bash tools/nankan_recon_dump.sh <.env.nar のパス>   → data/recon/{points,runs,races,prize}.csv
# 鍵は .env.nar の SUPABASE_DB_PASSWORD を環境変数で渡す(画面・ファイルに出さない)。
set -euo pipefail
ENV_FILE="${1:?.env.nar のパス}"
PSQL="${PSQL:-/c/Program Files/PostgreSQL/11/bin/psql.exe}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/data/recon"
mkdir -p "$OUT"
PGPASSWORD="$(grep -E '^SUPABASE_DB_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r"')"
export PGPASSWORD
cd "$OUT"
T0=$(date +%s)
"$PSQL" -v ON_ERROR_STOP=1 -q \
  -h aws-0-ap-northeast-1.pooler.supabase.com -p 5432 -U postgres.qgsnsdjvzzeazbazjlwa -d postgres <<'SQL'
\copy (select code, horse_name, kaku, points, asof, birth_date, last_run, seen_track, fetched from nar_nankan_points) to 'points.csv' csv header
\copy (select track, race_date, race_no, runner_number, horse_name, sex, age, finish, finish_note, birth_date from nar_runs where track in ('大井','船橋','川崎','浦和')) to 'runs.csv' csv header
\copy (select track, race_date, race_no, race_name, race_kind, condition, field_size, prize_yen, cancelled from nar_races where track in ('大井','船橋','川崎','浦和')) to 'races.csv' csv header
\copy (select p.code, p.horse_name, p.age, p.last_run, p.runs from nar_horse_prize p where p.horse_name in (select horse_name from nar_nankan_points)) to 'prize.csv' csv header
SQL
echo "dump $(( $(date +%s) - T0 )) s"
wc -l "$OUT"/*.csv

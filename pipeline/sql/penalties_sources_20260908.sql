-- §111 / #528 制裁の読み済み記録(2026-09-08)。cloud/penalties.py が日次で 14 日ぶんの NAR 成績 PDF を毎回読み直して
--   1 本 12 秒×54 本= 約 11 分を使っていた。**取り直した PDF の sha256 と読み手の版(parser_version)が前回と同じ**なら
--   読み直さない、その記録だけを持つ表。⛔原本(PDF)は保存しない。⛔行(nar_penalties)の意味は変えない。
--   読み手の版を上げれば自動で全部読み直す。apply のときだけ書く(ドライランは記録しない)。
-- 適用= horse-health.yml の migrate 段(psql)。冪等。閲覧者は読まない(anon に権限を与えない)。
begin;
create table if not exists public.nar_penalty_sources (
  track          text        not null,
  race_date      date        not null,
  source_hash    text        not null,
  parser_version text        not null,
  rows           integer     not null default 0,
  parsed_at      timestamptz not null default now(),
  primary key (track, race_date),
  constraint nar_penalty_sources_hash_ck check (source_hash ~ '^[0-9a-f]{64}$')
);
alter table public.nar_penalty_sources enable row level security;
revoke all on table public.nar_penalty_sources from public, anon, authenticated;
grant select, insert, update, delete on public.nar_penalty_sources to service_role;
commit;

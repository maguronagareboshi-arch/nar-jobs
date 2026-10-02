-- 案件 A・B・D(2026-10-02)の器と投入。kds-abd-load.yml が gunzip した CSV を同じフォルダーに置いてから流す。
-- psql -v apply=true|false。false は全部を 1 つの取引で流して数を出し、最後に巻き戻す(何も残らない)。
-- 再実行で差分が入る(on conflict do update)。KDSCOPE は PC でしか新しくならない= 台本 build_abd.py / build_jockey_silks.py で CSV を作り直して再び流す。
\set ON_ERROR_STOP on
begin;

create table if not exists public.nar_jockey_silks (
  jockey_code text not null, jockey_name text, from_date date not null, silks text not null,
  primary key (jockey_code, from_date));
create table if not exists public.nar_run_silks_ex (
  track text not null, race_date date not null, race_no int not null, umaban int not null, silks text not null,
  primary key (track, race_date, race_no, umaban));
create table if not exists public.nar_horse_meaning (
  horse_name text not null, birth_date date not null, meaning text not null,
  primary key (horse_name, birth_date));
create table if not exists public.nar_horse_siblings (
  dam text not null, dam_birth_year int not null, horse_name text not null, birth_year int not null,
  sex text, sire text, nar_starts int not null default 0, nar_wins int not null default 0,
  jra_starts int not null default 0, jra_wins int not null default 0,
  primary key (dam, dam_birth_year, horse_name, birth_year));
create index if not exists nar_horse_siblings_horse on public.nar_horse_siblings (horse_name, birth_year);
create index if not exists nar_jockey_silks_name on public.nar_jockey_silks (jockey_name, from_date);

do $$ declare t text; begin
  foreach t in array array['nar_jockey_silks','nar_run_silks_ex','nar_horse_meaning','nar_horse_siblings'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_read', t);
    execute format('create policy %I on public.%I for select to anon, authenticated using (true)', t || '_read', t);
    execute format('grant select on public.%I to anon, authenticated', t);
  end loop; end $$;

create temp table t_js (like public.nar_jockey_silks) on commit drop;
create temp table t_ex (like public.nar_run_silks_ex) on commit drop;
create temp table t_hm (like public.nar_horse_meaning) on commit drop;
create temp table t_hs (like public.nar_horse_siblings) on commit drop;
\copy t_js from 'pipeline/kds_abd/nar_jockey_silks.csv' with (format csv, header true)
\copy t_ex from 'pipeline/kds_abd/nar_run_silks_ex.csv' with (format csv, header true)
\copy t_hm from 'pipeline/kds_abd/nar_horse_meaning.csv' with (format csv, header true)
\copy t_hs from 'pipeline/kds_abd/nar_horse_siblings.csv' with (format csv, header true)

select 'csv' as k, (select count(*) from t_js) as jockey_silks, (select count(*) from t_ex) as run_silks_ex,
       (select count(*) from t_hm) as horse_meaning, (select count(*) from t_hs) as horse_siblings;

insert into public.nar_jockey_silks select * from t_js
  on conflict (jockey_code, from_date) do update set jockey_name = excluded.jockey_name, silks = excluded.silks
  where (nar_jockey_silks.jockey_name, nar_jockey_silks.silks) is distinct from (excluded.jockey_name, excluded.silks);
insert into public.nar_run_silks_ex select * from t_ex
  on conflict (track, race_date, race_no, umaban) do update set silks = excluded.silks
  where nar_run_silks_ex.silks is distinct from excluded.silks;
insert into public.nar_horse_meaning select * from t_hm
  on conflict (horse_name, birth_date) do update set meaning = excluded.meaning
  where nar_horse_meaning.meaning is distinct from excluded.meaning;
insert into public.nar_horse_siblings select * from t_hs
  on conflict (dam, dam_birth_year, horse_name, birth_year) do update set sex = excluded.sex, sire = excluded.sire,
    nar_starts = excluded.nar_starts, nar_wins = excluded.nar_wins, jra_starts = excluded.jra_starts, jra_wins = excluded.jra_wins
  where (nar_horse_siblings.sex, nar_horse_siblings.sire, nar_horse_siblings.nar_starts, nar_horse_siblings.nar_wins,
         nar_horse_siblings.jra_starts, nar_horse_siblings.jra_wins)
        is distinct from (excluded.sex, excluded.sire, excluded.nar_starts, excluded.nar_wins, excluded.jra_starts, excluded.jra_wins);

select 'table' as k, (select count(*) from public.nar_jockey_silks) as jockey_silks, (select count(*) from public.nar_run_silks_ex) as run_silks_ex,
       (select count(*) from public.nar_horse_meaning) as horse_meaning, (select count(*) from public.nar_horse_siblings) as horse_siblings;
select relname, pg_size_pretty(pg_total_relation_size(oid)) from pg_class
 where relname in ('nar_jockey_silks','nar_run_silks_ex','nar_horse_meaning','nar_horse_siblings') order by 1;

\if :apply
commit;
\echo 'applied'
\else
rollback;
\echo 'dry run (rolled back)'
\endif

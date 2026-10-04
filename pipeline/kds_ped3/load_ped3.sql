-- 案件 G(2026-10-04)3代血統表 nar_horse_pedigree3 の器と投入。kds-ped3-load.yml が gunzip した CSV を同じフォルダーに置いてから流す。
-- psql -v apply=true|false。false は 1 つの取引で流して数を出し、最後に巻き戻す(何も残らない)。
-- 再実行で差分が入る(on conflict do update)。CSV は PC の KDSCOPE から nar-site\research\kdscope-ideas\efg\ped3_build.py で作り直す。
-- 列: ss=父父 sd=父母 ds=母父 dd=母母 / sss=父父父 ssd=父父母 sds=父母父 sdd=父母母 dss=母父父 dsd=母父母 dds=母母父 ddd=母母母(父・母は既存表)
\set ON_ERROR_STOP on
begin;

create table if not exists public.nar_horse_pedigree3 (
  horse_name text not null, birth_date date not null, kd_ketto text,
  ss text, sd text, ds text, dd text,
  sss text, ssd text, sds text, sdd text, dss text, dsd text, dds text, ddd text,
  primary key (horse_name, birth_date));

alter table public.nar_horse_pedigree3 enable row level security;
drop policy if exists nar_horse_pedigree3_read on public.nar_horse_pedigree3;
create policy nar_horse_pedigree3_read on public.nar_horse_pedigree3 for select to anon, authenticated using (true);
grant select on public.nar_horse_pedigree3 to anon, authenticated;

create temp table t_p3 (like public.nar_horse_pedigree3) on commit drop;
\copy t_p3 from 'pipeline/kds_ped3/nar_horse_pedigree3.csv' with (format csv, header true)
select 'csv' as k, count(*) as rows from t_p3;

insert into public.nar_horse_pedigree3 select * from t_p3
  on conflict (horse_name, birth_date) do update set kd_ketto = excluded.kd_ketto,
    ss = excluded.ss, sd = excluded.sd, ds = excluded.ds, dd = excluded.dd,
    sss = excluded.sss, ssd = excluded.ssd, sds = excluded.sds, sdd = excluded.sdd,
    dss = excluded.dss, dsd = excluded.dsd, dds = excluded.dds, ddd = excluded.ddd
  where (nar_horse_pedigree3.kd_ketto, nar_horse_pedigree3.ss, nar_horse_pedigree3.sd, nar_horse_pedigree3.ds, nar_horse_pedigree3.dd,
         nar_horse_pedigree3.sss, nar_horse_pedigree3.ssd, nar_horse_pedigree3.sds, nar_horse_pedigree3.sdd,
         nar_horse_pedigree3.dss, nar_horse_pedigree3.dsd, nar_horse_pedigree3.dds, nar_horse_pedigree3.ddd)
        is distinct from (excluded.kd_ketto, excluded.ss, excluded.sd, excluded.ds, excluded.dd,
         excluded.sss, excluded.ssd, excluded.sds, excluded.sdd, excluded.dss, excluded.dsd, excluded.dds, excluded.ddd);

select 'table' as k, count(*) as rows from public.nar_horse_pedigree3;
select relname, pg_size_pretty(pg_total_relation_size(oid)) from pg_class where relname = 'nar_horse_pedigree3';

\if :apply
commit;
\echo 'applied'
\else
rollback;
\echo 'dry run (rolled back)'
\endif

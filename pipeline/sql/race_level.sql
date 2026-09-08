-- レースレベル(その後成績)の夜間集計(2026-08-25 新設・DESIGN §23)。
-- 各レースについて「そのレースの出走馬が次走でどう走ったか」を1行の JSON にする。
-- けーばの「次走以降 勝x/複y」相当。馬柱の過去走セルと将来の独自指標の土台。
-- 毎朝 05:30 の月次ジョブで全面作り直し・冪等。
set statement_timeout = '20min';

create table if not exists public.nar_race_level (
  track      text not null,
  race_date  date not null,
  race_no    integer not null,
  stats      jsonb not null,   -- {n: 次走が確定した頭数, w1: 次走勝ち, t3: 次走3着内, top3n/top3w1: 上位3着内馬だけの同値}
  updated_at timestamptz not null default now(),
  primary key (track, race_date, race_no)
);
alter table public.nar_race_level enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='nar_race_level' and policyname='nar_race_level_read') then
    create policy nar_race_level_read on public.nar_race_level for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_race_level to anon, authenticated;

-- 各走に「同じ馬の次走の着順」を並べる(馬名キー・window 1パス)
drop table if exists tmp_next;
create temp table tmp_next as
select track, race_date, race_no, finish,
       lead(finish) over w as next_finish,
       lead(race_date) over w as next_date
from public.nar_runs
where horse_name is not null and horse_name <> ''
window w as (partition by horse_name order by race_date, race_no);

delete from public.nar_race_level;
insert into public.nar_race_level (track, race_date, race_no, stats, updated_at)
select track, race_date, race_no,
  jsonb_build_object(
    'n',  count(*) filter (where next_finish is not null),
    'w1', count(*) filter (where next_finish = 1),
    't3', count(*) filter (where next_finish <= 3),
    'top3n',  count(*) filter (where finish <= 3 and next_finish is not null),
    'top3w1', count(*) filter (where finish <= 3 and next_finish = 1)), now()
from tmp_next
where finish is not null
group by track, race_date, race_no
having count(*) filter (where next_finish is not null) > 0;

select count(*) as races, pg_size_pretty(pg_total_relation_size('public.nar_race_level')) as size from public.nar_race_level;

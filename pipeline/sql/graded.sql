-- 重賞ページ用の一覧(2026-08-25 新設・DESIGN §27.2)。nar_races.race_kind(公式の競走種類名称)が正本。
-- 未来のレース(出馬表のみ)も入れる=「今週の重賞」に使う。勝ち馬は決着後に入る。全面作り直し・冪等・数秒。
set statement_timeout = '5min';

create table if not exists public.nar_graded (
  track        text not null,
  race_date    date not null,
  race_no      integer not null,
  race_name    text,
  race_kind    text not null,            -- '重賞' | '準重賞'
  distance_m   integer,
  post_time    text,
  field_size   integer,
  prize1_yen   bigint,                   -- 1着賞金
  winner_horse text,                     -- 決着前は null。同着は馬番の小さい方
  winner_jockey text,
  winner_pop   integer,
  updated_at   timestamptz not null default now(),
  primary key (track, race_date, race_no)
);
alter table public.nar_graded enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_graded' and policyname = 'nar_graded_read') then
    create policy nar_graded_read on public.nar_graded for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_graded to anon, authenticated;

delete from public.nar_graded;
insert into public.nar_graded (track, race_date, race_no, race_name, race_kind, distance_m, post_time,
                               field_size, prize1_yen, winner_horse, winner_jockey, winner_pop, updated_at)
select r.track, r.race_date, r.race_no, r.race_name, r.race_kind, r.distance_m, r.post_time,
       r.field_size, nullif((r.prize_yen->>0)::bigint, 0), w.horse_name, w.jockey, w.popularity, now()
from public.nar_races r
left join lateral (
  select u.horse_name, u.jockey, u.popularity from public.nar_runs u
  where (u.track, u.race_date, u.race_no) = (r.track, r.race_date, r.race_no) and u.finish = 1
  order by u.runner_number limit 1
) w on true
where r.race_kind in ('重賞', '準重賞');

select race_kind, count(*) as rows, count(winner_horse) as with_winner,
       max(race_date) as latest from public.nar_graded group by 1;

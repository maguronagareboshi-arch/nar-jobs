-- §18 父の成績= この場×この距離×同じ馬場・そのレースの前日まで 10 年(2026-10-10 ユーザー了承)の本番の器。
-- ⛔本番 DB へは本体がユーザーの「手動」切替の後に 1 回だけ流す(下請け・便は流さない)。中身は nar-stats(stats_local)が差分で書く。
-- 1 行= (レース, 馬番, 馬場)。umaban 0 = その場・距離・馬場の全馬平均(sire '*')。going '*' = 馬場問わず。
-- RLS・anon の select は nar_person_stats と同じ扱い。
create table if not exists public.nar_sire_course (
  track      text not null,          -- 場コード(nar_races と同じ)
  race_date  date not null,
  race_no    int  not null,
  umaban     int  not null,          -- 0 = 全馬平均
  going      text not null,          -- '良','稍重','重','不良','*'
  sire       text,                   -- 父(umaban 0 は '*')
  n          int  not null,
  w1         int  not null,
  w2         int  not null,
  w3         int  not null,
  roi        int,                    -- 単回収(100 円あたり・n=0 は null)
  roi3       int,                    -- 複回収
  updated_at timestamptz not null default now(),
  primary key (track, race_date, race_no, umaban, going)
);
alter table public.nar_sire_course enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_sire_course' and policyname = 'nar_sire_course_read') then
    create policy nar_sire_course_read on public.nar_sire_course for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_sire_course to anon, authenticated;

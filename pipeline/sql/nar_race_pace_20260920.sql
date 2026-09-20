-- §232 過去のレースの「実際のペース」(2026-09-20 新設)。作るのは cloud/tenkai.py --pace-log。
-- 1 レース 1 行= そのレースで実際に 1 角先頭だった馬のテン(前半3F − 場×距離の平年値)を
-- cloud/tenkai.py の pace_word に通した言葉。⛔値の出せないレースは行を作らない(「平均」で埋めない)。
-- ⛔読みは anon/authenticated の select だけ(nar_person_stats と同じ書き方)。冪等。
create table if not exists public.nar_race_pace (
  track       text not null,              -- 公式の場名
  race_date   date not null,
  race_no     int  not null,
  pace        text not null,              -- '速い' | '平均' | '遅い'
  lead_umaban int  not null,              -- 実際に 1 角先頭だった馬(同着で決まらないレースは行なし)
  lead_ten    numeric not null,           -- その馬の前半3F − 平年値(マイナスが速い)
  std_sec     numeric not null,           -- 使った平年値(場 × 距離の中央値)
  std_from    date not null,              -- 平年値を作った期間の始め(⛔レース日より前の 1 年)
  built       timestamptz not null,
  primary key (track, race_date, race_no)
);
create index if not exists nar_race_pace_date_idx on public.nar_race_pace (race_date desc, track);
alter table public.nar_race_pace enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_race_pace' and policyname = 'nar_race_pace_read') then
    create policy nar_race_pace_read on public.nar_race_pace for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_race_pace to anon, authenticated;

-- §232 過去のレースの「実際のペース」(2026-09-20 新設)。作るのは cloud/tenkai.py --pace-log。
-- 1 レース 1 行= そのレースで**いちばん速かった前半**と平年値の差を cloud/tenkai.py の pace_word に
-- 通した言葉。前半= 距離 − 600m の通過(走破タイム − 上がり3F・公式の走にある実測)= 1200m なら前半3F と同じ量。
-- ⛔平年値も同じ量(レースごとの最速)の中央値で作る= 比べる物差しをそろえる。
-- ⛔値の出せないレースは行を作らない(「平均」で埋めない)。⛔1200m 未満は前半の意味が変わるので入れない。
-- ⛔読みは anon/authenticated の select だけ(nar_person_stats と同じ書き方)。冪等。
create table if not exists public.nar_race_pace (
  track       text not null,              -- 公式の場名
  race_date   date not null,
  race_no     int  not null,
  pace        text not null,              -- '速い' | '平均' | '遅い'
  lead_umaban int,                        -- その時計を出した馬(同じ時計が 2 頭以上なら空)
  lead_ten    numeric not null,           -- そのレースの最速の前半 − 平年値(マイナスが速い)
  std_sec     numeric not null,           -- 使った平年値(場 × 距離・レースごとの最速の前半の中央値)
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

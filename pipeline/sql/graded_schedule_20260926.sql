-- 検索集客 案 2-④(2026-09-26) 地方競馬の年間の重賞日程(公式 https://www.keiba.go.jp/gradedrace/schedule_<年>.html)を残す器。
-- 目的= 重賞の年ページ(viewer /graded/<slug>/<年>)を開催の 2 週以上前から出す。nar_graded は出馬表が出る約 1 週前にしか行が入らないため。
-- 書き手= cloud/graded_schedule.py(便 graded-schedule.yml・毎朝)。同じ年を取り直したら上書きし、今回の一覧から消えた行は消す。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
-- 読み手= viewer functions/graded/[slug]/[year].js・js/data.js(anon の select だけ)。
create table if not exists public.nar_graded_schedule (
  sched_year  integer not null,          -- 一覧の年(schedule_<年>.html の年= 1/1〜12/31)
  race_date   date not null,
  track       text not null,             -- 公式一覧の場名(帯広は '帯広'。nar_graded は '帯広ば')
  race_name   text not null,             -- 一覧の競走名(回次・条件なし。例 '東京大賞典')
  grade       text,                      -- 一覧の格付け(例 'GⅠ' 'JpnⅢ' 'SⅢ' 'BG1'・無ければ null)
  distance_m  integer,
  mare_only   boolean not null default false,  -- 牝馬限定の印
  detail_url  text,                      -- ダートグレードの紹介ページ(あるときだけ)
  fetched_at  timestamptz not null default now(),
  primary key (race_date, track, race_name)
);
create index if not exists nar_graded_schedule_year on public.nar_graded_schedule (sched_year, race_date);
alter table public.nar_graded_schedule enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_graded_schedule' and policyname = 'nar_graded_schedule_read') then
    create policy nar_graded_schedule_read on public.nar_graded_schedule for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_graded_schedule from anon, authenticated;
grant select on public.nar_graded_schedule to anon, authenticated;

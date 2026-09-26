-- §287(2026-09-26) 南関4場(大井・川崎・船橋・浦和)の「降級の目安」(見込みの一覧)。書き手= cloud/nankan_demotion.py(便 nankan-demotion.yml)。
-- 式= nar-site/BACKTEST-demotion-nankan-20260926.md(拾い率 1月 99.5%・7月 99.0%):
--   今の格付ポイント(nar_nankan_points.points)< 切替後の半期表 × 切替後の馬齢 × 今の級 の線 → 「下がる」見込み。
-- 1 回の便で全行を upsert → 古い asof の行を消す(= 表はいつも最新の見込みだけ)。
-- target= 当てる切替日(1/1 か 7/1)。pending= 切替日は過ぎたが、その馬の格付(asof)がまだ切替前の値(主催者の反映待ち)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.nar_nankan_demotion (
  code        text not null,             -- 南関の馬コード(nar_nankan_points.code)
  horse_name  text not null,
  track       text,                      -- 最後に見た場(nar_nankan_points.seen_track)
  cls_now     text not null,             -- 'A1'〜'C2'(主催者の今の格)
  pts         integer not null,          -- 今の格付ポイント
  pts_asof    date,                      -- その格付ポイントの基準日(主催者の「◯月◯日現在」)
  age         integer not null,          -- 切替後の馬齢
  line        integer not null,          -- 切替後の今の級の線
  short       integer not null,          -- 線 − 今の点(足りない分)
  target      date not null,             -- 当てる切替日
  target_label text not null,            -- 画面の札(例 '2027年1月')
  pending     boolean not null default false,
  asof        timestamptz not null default now(),
  primary key (code)
);
create index if not exists nar_nankan_demotion_name on public.nar_nankan_demotion (horse_name);
alter table public.nar_nankan_demotion enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_nankan_demotion' and policyname = 'nar_nankan_demotion_read') then
    create policy nar_nankan_demotion_read on public.nar_nankan_demotion for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_nankan_demotion from anon, authenticated;
grant select on public.nar_nankan_demotion to anon, authenticated;

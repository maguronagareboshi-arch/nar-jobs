-- §287(2026-09-26) 笠松・名古屋の「降級の目安」(見込みの一覧)。書き手= cloud/tokai_demotion.py(便 tokai-demotion.yml)。
-- 1 回の便で場ごとに全行を upsert → 同じ場の古い asof の行を消す(= 表はいつも最新の見込みだけ)。
-- 額の単位= 千円(一覧の番組賞金と同じ)。need_man だけ万円。級= 'A' / 'B' / 'C'。
-- pending= 見直しは済んだが主催者の見直し後の一覧がまだ出ていない(p1 はその見直しの見込み・p2 はその次)。
--   pending でないとき p1= 次の見直しの見込み・p2= その次(以後の稼ぎ 0)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.nar_tokai_demotion (
  venue       text not null,             -- 'kasamatsu' / 'nagoya'(画面の場の名)
  horse_name  text not null,
  cls_now     text not null,             -- 一覧の P から見た今の級
  p_now       integer not null,          -- 一覧の番組賞金(千円)
  earn        integer not null default 0,  -- 前回の見直しの翌日からの一般格の収得(千円)
  won         boolean not null default false,  -- 同じ期間に一般格で勝った
  p1          integer not null,
  cls1        text not null,
  p2          integer not null,
  cls2        text not null,
  need_man    integer,                   -- 級に残るのに要る額(万円)。無ければ null
  pending     boolean not null default false,
  asof        timestamptz not null default now(),
  primary key (venue, horse_name)
);
alter table public.nar_tokai_demotion enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_tokai_demotion' and policyname = 'nar_tokai_demotion_read') then
    create policy nar_tokai_demotion_read on public.nar_tokai_demotion for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_tokai_demotion from anon, authenticated;
grant select on public.nar_tokai_demotion to anon, authenticated;

-- §286(2026-09-26) 兵庫の主催者の名簿(番組・馬連名簿 https://www.sonoda-himeji.jp/race/program/)を週ごとに残す器。
-- 書き手= cloud/hyogo_roster.py(便 hyogo-roster.yml・月木)。同じ週を取り直したら上書き(消えた馬の行も消す)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.nar_hyogo_roster (
  week_label  text not null,             -- 'R8 9月4週'(令和◯年度・月・第◯週。表示の写し)
  week_start  date not null,             -- その週の月曜(hyogo_roster.week_start の規則)。発走前の値として当てる週
  fetched_at  timestamptz not null default now(),
  section     text not null,             -- '2歳' / 'A1' 'A2' 'B1' 'B2' 'C1' 'C2' 'C3'
  horse_name  text not null,
  code        text,                      -- nar_horse_codes.code(結べたときだけ)
  sex         text,
  age         smallint,
  points      integer,                   -- 3歳以上の点
  prize_yen   bigint,                    -- 2歳の賞金(円)
  cls         text,                      -- 格
  trainer     text not null default '',
  note        text,                      -- 備考
  home_mark   boolean not null default false,  -- ※= 自場馬
  primary key (week_label, section, horse_name, trainer)
);
create index if not exists nar_hyogo_roster_code on public.nar_hyogo_roster (code, week_start);
create index if not exists nar_hyogo_roster_name on public.nar_hyogo_roster (horse_name, week_start);
alter table public.nar_hyogo_roster enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_hyogo_roster' and policyname = 'nar_hyogo_roster_read') then
    create policy nar_hyogo_roster_read on public.nar_hyogo_roster for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_hyogo_roster from anon, authenticated;
grant select on public.nar_hyogo_roster to anon, authenticated;

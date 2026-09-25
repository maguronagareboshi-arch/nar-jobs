-- §285-F(2026-09-25・未適用)。門別の過去レースの「その時点の番組賞金と級」(昇級ライン用)。
-- 書き手= cloud/class_monbetsu_level_hist.py --apply。読み手= viewer js/pages/race-level.js(公式最新回の asof 以前のレース)。
-- 値= レース日 D より前に出た最新の公式回(asof < D)を起点に、その回の締め〜D の前日の走を要領 第7 で足したもの(発走前の値)。
create table if not exists public.nar_monbetsu_level_hist (
  race_date   date    not null,
  race_no     int     not null,
  horse_name  text    not null,
  prize_yen   bigint  not null,       -- 発走前の番組賞金(円)
  kaku        text,                   -- その時点の級(Ｃ２ など・2歳や級の形でない馬は null)
  kai         int     not null,       -- 起点にした公式の回
  calc        boolean not null,       -- 起点の後の自前加算を含むか
  updated_at  timestamptz not null default now(),
  primary key (race_date, race_no, horse_name)
);
alter table public.nar_monbetsu_level_hist enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='nar_monbetsu_level_hist' and policyname='nar_monbetsu_level_hist_read') then
    create policy nar_monbetsu_level_hist_read on public.nar_monbetsu_level_hist for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_monbetsu_level_hist to anon, authenticated;

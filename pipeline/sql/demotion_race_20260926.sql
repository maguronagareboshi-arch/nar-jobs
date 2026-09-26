-- §294(2026-09-26) 降級の目安を「レースごと・出走馬ごと」に残す表(過去のレースでも発走前の値を出す)。兵庫は対象外。
-- 書き手= cloud/demotion_race.py(①毎日の便= tokai_demotion.py・nankan_demotion.py・saga_demotion.py の --apply の最後
--   ②埋め戻し= 便 demotion-race-backfill.yml)。読み手= viewer js/data.js getDemotionRace(過去のレースだけ)。
-- 1 行= 1 レースの 1 頭(出走表の全馬)。v= その馬の目安(今の 3 表の行と同じ形の jsonb)・一覧に居ない馬は null。
--   kind= 'tokai'(nar_tokai_demotion の行)/'nankan'(nar_nankan_demotion の行)/'saga'(nar_saga_demotion の行)。
--   meta= 画面の見出しに要る値(tokai {pending, adj, D, D2}・nankan {next, asof}・saga {calc_date, target})。
--   asof= 計算に使った最後の日(埋め戻し= レースの前日・毎日の便= 計算した日)・calc_date= 計算した日。
-- ⛔レースの日が今日(JST)より前の行は上書きしない= 発走前の値を凍結(下の trigger。便の側でも今日以降だけ書く)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.nar_demotion_race (
  venue       text not null,             -- 画面の場の名('kasamatsu' / 'nagoya' / 'ooi' / 'kawasaki' / 'funabashi' / 'urawa' / 'saga')
  race_date   date not null,
  race_no     integer not null,
  horse_name  text not null,             -- 出走表(nar_runs)の馬名
  kind        text not null check (kind in ('tokai', 'nankan', 'saga')),
  v           jsonb,                     -- その馬の目安(無ければ null)
  meta        jsonb,
  asof        date not null,
  calc_date   date not null,
  updated_at  timestamptz not null default now(),
  primary key (venue, race_date, race_no, horse_name)
);
alter table public.nar_demotion_race enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_demotion_race' and policyname = 'nar_demotion_race_read') then
    create policy nar_demotion_race_read on public.nar_demotion_race for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_demotion_race from anon, authenticated;
grant select on public.nar_demotion_race to anon, authenticated;

-- 凍結= レースの日が今日(JST)より前の行の上書きは黙って捨てる(upsert の merge でも変わらない)
create or replace function public.nar_demotion_race_freeze() returns trigger language plpgsql as $$
begin
  if old.race_date < (now() at time zone 'Asia/Tokyo')::date then
    return null;
  end if;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists nar_demotion_race_freeze on public.nar_demotion_race;
create trigger nar_demotion_race_freeze before update on public.nar_demotion_race
  for each row execute function public.nar_demotion_race_freeze();

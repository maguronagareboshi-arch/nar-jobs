-- 南関の走破指数(SI5)の保存(2026-10-26)。⛔本番への適用はユーザーの手で(SQL エディタで 1 回)。
-- ① 記録の表 nar_si5 = 南関の走りごとの SI5(場・日・R・馬番・馬の鍵・SI5)。書き手は nar-jobs pipeline/ai/v3/si5_store.py
--    (毎日の南関の便 nar-ai-v3 が直近 21 日分を upsert・過去 2014〜 は手元から 1 回だけ)。
--    ⛔読む口は開けない(anon は表を読めない)= サイトは nar_runs.si5(下の ②)を今までの窓口(runs_*)で読む。
create table if not exists public.nar_si5 (
  track text not null,
  race_date date not null,
  race_no integer not null,
  runner_number integer not null,
  horse_key text,
  si5 numeric(6,1) not null,
  updated_at timestamptz not null default now(),
  primary key (track, race_date, race_no, runner_number)
);
alter table public.nar_si5 enable row level security;
revoke all on public.nar_si5 from anon, authenticated;
comment on table public.nar_si5 is '南関の走破指数 SI5(当サイトの推定・t5_base.make_si5)。書き手 pipeline/ai/v3/si5_store.py';

-- ② 出馬表・馬柱の窓口(runs_* は setof nar_runs)にそのまま乗るよう、nar_runs に写しの列を足す。null= 出せない走(他場・中央・初出走など)
alter table public.nar_runs add column if not exists si5 numeric(6,1);
comment on column public.nar_runs.si5 is '南関の走破指数 SI5(nar_si5 の写し・当サイトの推定)。null= 出せない走';

-- ③ nar_si5 に書いたら nar_runs.si5 へ写す(同じ値なら書かない)
create or replace function public.nar_si5_copy() returns trigger
  language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
begin
  update public.nar_runs r set si5 = new.si5
   where r.track = new.track and r.race_date = new.race_date and r.race_no = new.race_no
     and r.runner_number = new.runner_number and r.si5 is distinct from new.si5;
  return null;
end $$;
drop trigger if exists nar_si5_copy on public.nar_si5;
create trigger nar_si5_copy after insert or update on public.nar_si5
  for each row execute function public.nar_si5_copy();

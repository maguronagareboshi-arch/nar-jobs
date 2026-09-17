-- §200(2026-09-17・Fable・本番適用済み)。他場の計算(番組賞金・ポイント・表の位置)のレース日時点。
create table if not exists public.nar_class_calc_hist (
  code        text not null,          -- nar_horse_prize.code
  prefix      text not null,          -- kochi / obihiro / saga / tokai / hyogo(class_calc.py の prefix)
  asof        date not null,          -- レース日(計算の中で lag を引く= 当日の calc 列と同じ asof の取り方)
  calc        jsonb not null,         -- nar_horse_prize.calc と同じ形
  updated_at  timestamptz not null default now(),
  primary key (code, prefix, asof)
);
alter table public.nar_class_calc_hist enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='nar_class_calc_hist' and policyname='nar_class_calc_hist_read') then
    create policy nar_class_calc_hist_read on public.nar_class_calc_hist for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_class_calc_hist to anon, authenticated;
create index if not exists nar_class_calc_hist_asof_idx on public.nar_class_calc_hist (asof);

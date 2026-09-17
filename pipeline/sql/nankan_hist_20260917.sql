-- §196b 第 2 段(2026-09-17・Fable・本番適用済み)。南関 格付ポイントの履歴表と、nar_races の南関列。
create table if not exists public.nar_nankan_point_hist (
  code        text not null,            -- nankankeiba の馬コード(nar_nankan_points.code)
  meet_end    date not null,            -- その開催の最終日(反映の時点。原文 L227)
  points      integer,                  -- 反映後の格付ポイント(null= 決められない走があった)
  src         text not null check (src in ('official','recon')),  -- official= 主催者の値(asof がこの開催の後の最初の値)・recon= 逆算
  kaku_ran    text,                     -- その開催で走ったレースの格(C3/B2/A1…)
  kaku_src    text check (kaku_src is null or kaku_src in ('race','carry')),  -- race= 単一クラスの条件から・carry= 前の開催の値を引き継ぎ
  last_run    date,                     -- その開催でのその馬の最後の走
  updated_at  timestamptz not null default now(),
  primary key (code, meet_end)
);
alter table public.nar_nankan_point_hist enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='nar_nankan_point_hist' and policyname='nar_nankan_point_hist_read') then
    create policy nar_nankan_point_hist_read on public.nar_nankan_point_hist for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_nankan_point_hist to anon, authenticated;
create index if not exists nar_nankan_point_hist_meet_idx on public.nar_nankan_point_hist (meet_end);
-- 南関のレースだけ: {"raceid": 主催者の raceid, "pts": [1着..5着の番組ポイント], "grade": "SIII"|null}
alter table public.nar_races add column if not exists nankan jsonb;

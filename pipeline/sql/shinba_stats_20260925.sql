-- §280(2026-09-25) 新馬戦の「傾向カード」の本番の器。中身は nar-stats 便(stats_local.py shinba → diff/apply)が差分で入れる。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
-- ⛔これを流す前に nar-stats の OUTPUTS に nar_shinba_stats を入れた版を動かすと、dump(本番の出力の写し)で表が無くて落ちる。
create table if not exists public.nar_shinba_stats (
  kind       text not null,             -- sd bd st td br jk nj nr nw nc ka kt au dm(設計書 §2-2)
  a          text not null,             -- 父・母父・調教師・生産者・騎手・地区・母 / 全体は '*'
  b          text not null,             -- 距離帯・場・順位帯・週数帯 など / 無しは ''
  stats      jsonb not null,            -- {n, w1, w2, w3, pay}(dm だけ sib を足す)
  as_of      date not null default current_date,
  updated_at timestamptz not null default now(),
  primary key (kind, a, b)
);
alter table public.nar_shinba_stats enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_shinba_stats' and policyname = 'nar_shinba_stats_read') then
    create policy nar_shinba_stats_read on public.nar_shinba_stats for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_shinba_stats from anon, authenticated;
grant select on public.nar_shinba_stats to anon, authenticated;

-- (2026-10-02) KDSCOPE の馬の台帳(UM 中央・NU 地方)から、2008 年以降生まれの馬の血統を持つ表。
-- 書き手= 便 kd-pedigree-load.yml(pipeline/kd_pedigree_load.py が data/kd_pedigree/kd_pedigree.csv.gz を upsert)。
-- CSV は手元の pipeline/kd_pedigree_export.py が v3/kd_horse.parquet から作る(KDSCOPE の利用許可は取得済み)。
-- 鍵= 血統登録番号(ketto)。同名馬の使い回しがあるので、引くときは (horse_name, birth_date) で引く。
-- 読み手= pipeline/stats_local/shinba_stats.sql(兄姉の初戦 dm・父/母父 sd/bd/st/sv/bv・生産牧場 br)。無ければ nar_horses へ落とす。
-- 名前は NFKC+前後空白の除去済み。sex= '牡' / '牝' / 'セ'。src= 'UM' / 'NU'(同じ ketto は NU を優先)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.nar_kd_pedigree (
  ketto           text primary key,
  horse_name      text not null,
  birth_date      date,
  sex             text,
  sire            text,
  dam             text,
  broodmare_sire  text,
  breeder         text,
  src             text not null,
  updated_at      timestamptz not null default now()
);
create index if not exists nar_kd_pedigree_name_birth on public.nar_kd_pedigree (horse_name, birth_date);
alter table public.nar_kd_pedigree enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_kd_pedigree' and policyname = 'nar_kd_pedigree_read') then
    create policy nar_kd_pedigree_read on public.nar_kd_pedigree for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_kd_pedigree from anon, authenticated;
grant select on public.nar_kd_pedigree to anon, authenticated;

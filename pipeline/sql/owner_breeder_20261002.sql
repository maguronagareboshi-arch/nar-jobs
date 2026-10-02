-- 馬主・生産者・調教師ページ(2026-10-02)の本番の器 5 表+nar_persons.license_date。
-- 取り決めは nar-site/research/owner-breeder/impl_spec.md。中身は nar-stats 便(stats_local.py ob → diff/apply)が差分で入れる。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
-- ⛔これを流す前に nar-stats の OUTPUTS に 5 表を入れた版を動かすと、dump(本番の出力の写し)で表が無くて落ちる。
-- 手元(Actions 内 Postgres)では nar_name_alias は schema.sql、他の 4 表は owner_breeder.sql が同じ形で作る(⛔形を変えるときは 3 か所)。

-- 表記 → 代表表記(代表表記= 組の中で直近 2 年の頭数が最多の表記を NFKC にしたもの・URL /owner/:canonical に使う)
create table if not exists public.nar_name_alias (
  kind       text not null,             -- 'owner' | 'breeder'
  alias      text not null,             -- nar_horse_profiles.owner / breeder の表記そのまま
  canonical  text not null,
  updated_at timestamptz not null default now(),
  primary key (kind, alias)
);
create index if not exists nar_name_alias_canon_idx on public.nar_name_alias (kind, canonical);

-- 調教師の年×場の成績(name= nar_runs.trainer の略称)。同じ略称 55 略称の 2014〜2021 は入れない(ユーザー精査待ち)
create table if not exists public.nar_person_year (
  kind       text not null,             -- 'trainer'
  name       text not null,
  year       integer not null,
  track      text not null,
  n          integer not null,
  w1         integer not null,
  w2         integer not null,
  w3         integer not null,
  updated_at timestamptz not null default now(),
  primary key (kind, name, year, track)
);

-- 馬主・生産者の年×場の成績(name= canonical)
create table if not exists public.nar_ob_year (
  kind       text not null,             -- 'owner' | 'breeder'
  name       text not null,
  year       integer not null,
  track      text not null,
  horses     integer not null,          -- その年その場で走った馬の数
  n          integer not null,
  w1         integer not null,
  w2         integer not null,
  w3         integer not null,
  updated_at timestamptz not null default now(),
  primary key (kind, name, year, track)
);

-- 馬主・生産者ごとの馬(名簿 nar_horse_profiles の全馬・走っていない馬は n=0)
create table if not exists public.nar_ob_horses (
  kind        text not null,
  name        text not null,
  horse_name  text not null,
  birth_date  date not null,
  sex         text,
  sire        text,
  first_date  date,
  last_date   date,                     -- 「いま走っている」= last_date が 180 日以内(画面で判定)
  n           integer not null,
  w1          integer not null,
  w2          integer not null,
  w3          integer not null,
  last_track  text,
  updated_at  timestamptz not null default now(),
  primary key (kind, name, horse_name, birth_date)
);

-- 重賞・準重賞の 1〜3 着(2022-11 から)
create table if not exists public.nar_ob_graded (
  kind       text not null,
  name       text not null,
  race_date  date not null,
  track      text not null,
  race_no    integer not null,
  horse_name text not null,
  race_name  text,
  finish     integer not null,          -- 1〜3
  updated_at timestamptz not null default now(),
  primary key (kind, name, race_date, track, race_no, horse_name)
);

-- 読み取り許可(既存の nar_shinba_stats と同じ形)
do $$
declare t text;
begin
  foreach t in array array['nar_name_alias', 'nar_person_year', 'nar_ob_year', 'nar_ob_horses', 'nar_ob_graded'] loop
    execute format('alter table public.%I enable row level security', t);
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = t and policyname = t || '_read') then
      execute format('create policy %I on public.%I for select to anon, authenticated using (true)', t || '_read', t);
    end if;
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to anon, authenticated', t);
  end loop;
end $$;

-- 調教師になった日(KDSCOPE NC の免許日)。中身は一回便(nar-site/research/owner-breeder/license_date_update.sql)で入れる
alter table public.nar_persons add column if not exists license_date date;

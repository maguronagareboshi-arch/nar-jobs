-- 監査 A7(2026-09-24) 集計を Actions 内の Postgres で作るための「手元の器」。
-- ⛔これは Actions の中で docker で立てた使い捨ての Postgres にだけ流す(本番には流さない)。
-- 入力表の型は本番と同じ(2026-09-24 に本番の pg_attribute で確認)。列は集計 SQL 6 本が使う分+updated_at だけ。
-- ⛔列を増やすときは stats_local.py の INPUTS(写す列の並び)と ここ の両方を同じ並びで直す。

-- Supabase の役(集計 SQL の policy / grant が名前で指す)。手元では中身の無い役でよい
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;

-- ---------------------------------------------------------------- 入力(本番から写す)
create table public.nar_runs (
  track text not null, race_date date not null, race_no integer not null, runner_number integer not null,
  gate integer, horse_name text, jockey text, trainer text, finish integer, finish_note text,
  time_sec numeric, popularity integer, last3f numeric, age integer, birth_date date, updated_at timestamptz not null
);
create table public.nar_races (
  track text not null, race_date date not null, race_no integer not null,
  post_time text, race_name text, surface text, distance_m integer, going text, field_size integer,
  prize_yen jsonb, race_kind text, updated_at timestamptz not null
);
create table public.nar_race_payouts (
  track text not null, race_date date not null, race_no integer not null,
  payouts jsonb not null, updated_at timestamptz not null
);
create table public.nar_horses (
  horse_name text not null, sire text, broodmare_sire text, owner text, dam text, breeder text,
  updated_at timestamptz not null
);
create table public.nar_ai_marks (
  model text not null, track text not null, race_date date not null, race_no integer not null, timing text not null,
  marks jsonb not null, computed_at timestamptz not null, updated_at timestamptz not null
);
-- §280 落札価格帯(kind=au)
create table public.auction_sales (
  source text not null, horse_name text, birth_date date, auction_date date not null, price integer, sold boolean not null
);
-- §280 能検索引(本番 nar_meta key='noken_index' の 1 行)と、それを python で行に開いた表(⛔本番には作らない)
create table public.noken_meta (
  key text primary key, value jsonb not null, updated_at timestamptz not null
);
create table public.noken_recs (
  horse_name text not null, date date not null, d text, r integer, n integer, dr integer, dn integer,
  ar integer, t1 numeric, t1r integer, j text, w integer
);
create index on public.noken_recs (horse_name, date);

-- ---------------------------------------------------------------- 出力のうち、集計 SQL が create しない表
create table public.nar_ai_record (
  model text not null, track text not null, timing text not null, stats jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (model, track, timing)
);
create table public.nar_meta (
  key text primary key, value jsonb not null, updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- 照合用
-- 本番の出力の写しは schema prod に置く(表は集計 SQL を流した後に `like public.<表>` で作る)
create schema prod;

-- 配列の並びだけの違いを見分けるための正規形(配列は要素の文字列順に並べ替える・入れ子も)
create function public.stats_canon(j jsonb) returns jsonb language sql immutable as $$
  select case jsonb_typeof(j)
    when 'array' then coalesce((select jsonb_agg(c order by c::text)
                                from (select public.stats_canon(e) as c from jsonb_array_elements(j) e) s), '[]'::jsonb)
    when 'object' then coalesce((select jsonb_object_agg(k, public.stats_canon(v)) from jsonb_each(j) t(k, v)), '{}'::jsonb)
    else j end
$$;

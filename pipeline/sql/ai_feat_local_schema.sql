-- §129d 予想AI 段階1 の**地元の器**= GitHub Actions の中に立てた Postgres に、本番から写した
-- 材料の表(9 つ)を入れるための create table。⛔本番では流さない(本番には同じ表が既にある)。
--
-- ■ なぜこれが要るのか(9/8 決定)
--   9/7 夜に本番 DB で `refresh_nar_ai_feat()` を流したら 30 分間サイトが読めなくなった
--   (本番は work_mem 2 MB・IO の割当が小さい小さな計算機)。以後、**全量の特徴量作りは本番で流さない**。
--   本番からは `\copy (select * from …)` で**読むだけ**。組み立ては Actions の中の Postgres で行う。
--
-- ■ 列と型の出どころ(⛔推定していない)
--   本番の `pg_attribute` / `pg_constraint` を `pipeline/dbadmin.py sql` で読んで写した(2026-09-08 実測)。
--   ⛔並びは attnum の順そのまま= `\copy (select * from 表)` の列順と一致する(落ちた列は入っていない)。
--   ⛔主キーも本番と同じ。SQL の join に使う索引(nar_horses(horse_name)・
--     nar_kb_runs(track, race_date, race_no, umaban))は**主キーそのもの**なので別に張らない。
--
-- ■ nar_sales_daily は**表ではなく view**(実測 relkind='v')
--   中身は `nar_sales` の group by。本番に group by を掛けないため、材料は **`nar_sales` を写し**、
--   同じ定義の view を地元に作る(⛔値は本番と同じ)。→ 写す実体は 9 つ= 下の 9 表。
--
-- 使い方(Actions / 手元):
--   psql -v ON_ERROR_STOP=1 -f pipeline/sql/ai_feat_local_schema.sql
--   \copy public.nar_runs from 'nar_runs.tsv'   (以下 9 表)
--   analyze;

begin;

-- ---------------------------------------------------------------- 1) 走(144 MB・60 万行)
create table if not exists public.nar_runs (
  track              text    not null,
  race_date          date    not null,
  race_no            integer not null,
  runner_number      integer not null,
  gate               integer,
  horse_name         text,
  sex                text,
  age                integer,
  jockey             text,
  trainer            text,
  carried_weight     numeric,
  body_weight        integer,
  body_weight_change integer,
  finish             integer,
  finish_note        text,
  time_raw           text,
  time_sec           numeric,
  margin             text,
  last3f             numeric,
  popularity         integer,
  updated_at         timestamptz not null,
  birth_date         date,
  trainer_area       text,
  weight_mark        text,
  primary key (track, race_date, race_no, runner_number)
);

-- 索引 2 本。⛔`nar_runs_horse_idx` は本番にもある同じもの。
--   `nar_runs_jockey_idx` は**本番には無い**= 検算道具(tests/ai_feat_check.py の ②「騎手の 365 日窓に
--   当日以降が入っていない」)が騎手で 604,037 行を毎回舐めるため、地元にだけ張る(1 秒で出来る)。
--   ⛔本番には作らない(読むだけの約束)。⛔値には 1 つも関係しない。
create index if not exists nar_runs_horse_idx  on public.nar_runs (horse_name, race_date desc);
create index if not exists nar_runs_jockey_idx on public.nar_runs
  ((nullif(btrim(jockey), '')), race_date);   -- ⛔検算道具の where と**同じ式**で張る(素の jockey では効かない)

-- ---------------------------------------------------------------- 2) レース(44 MB)
create table if not exists public.nar_races (
  track                text    not null,
  race_date            date    not null,
  race_no              integer not null,
  post_time            text,
  race_name            text,
  surface              text,
  direction            text,
  distance_m           integer,
  weather              text,
  going                text,
  field_size           integer,
  condition            text,
  prize_yen            jsonb,
  race_last4f          numeric,
  race_last3f          numeric,
  furlongs             jsonb,
  corners              jsonb,
  source               text not null,
  source_snapshot_hash text,
  updated_at           timestamptz not null,
  race_kind            text,
  cancelled            text,        -- 2026-09-09 本番に増えた 2 列(\copy は列の並びで入るので写しも同じ形に)
  cancel_note          text,
  primary key (track, race_date, race_no)
);

-- ---------------------------------------------------------------- 3) せり(33 MB)
create table if not exists public.auction_sales (
  source        text    not null,
  item_id       integer not null,
  horse_name    text,
  display_name  text    not null,
  sex           text,
  age           smallint,
  birth_date    date,
  category      text,
  auction_date  date    not null,
  round_no      integer,
  start_price   integer,
  price         integer,
  bids          integer not null,
  sold          boolean not null,
  seller        text,
  tags          text[]  not null,
  other_n       smallint not null,
  jbis_id       text,
  url           text    not null,
  fetched_at    timestamptz,
  updated_at    timestamptz not null,
  runs_after    integer,
  first_after   date,
  sire          text,
  dam           text,
  buyer         text,
  primary key (source, item_id)
);

-- ---------------------------------------------------------------- 4) 馬(血統・馬主・生産者)
create table if not exists public.nar_horses (
  horse_name      text not null,
  sex             text,
  sire            text,
  dam             text,
  broodmare_sire  text,
  owner           text,
  breeder         text,
  first_date      date,
  last_date       date,
  runs            integer,
  updated_at      timestamptz not null,
  primary key (horse_name)
);

-- ---------------------------------------------------------------- 5) 提供データの走(前半3F・馬装具)
create table if not exists public.nar_kb_runs (
  track       text     not null,
  race_date   date     not null,
  race_no     smallint not null,
  umaban      smallint not null,
  horse_name  text,
  kb_race_id  text,
  blinker     text,
  gear        text,
  first3f     numeric,
  avg_f       numeric,
  pace        text,
  kimete      text,
  start_note  text,
  updated_at  timestamptz not null,
  primary key (track, race_date, race_no, umaban)
);

-- ---------------------------------------------------------------- 6) 疾病・事故(§109/§124)
create table if not exists public.nar_horse_health_events (
  event_id                    text not null,
  horse_name                  text not null,
  birth_date                  date,
  horse_code                  text,
  jbis_id                     text,
  track                       text,
  race_date                   date,
  race_no                     smallint,
  runner_number               smallint,
  event_date                  date,
  reported_date               date not null,
  stage                       text not null,
  event_type                  text not null,
  condition_group             text not null,
  race_status                 text,
  detail                      text not null,
  restriction_from            date,
  restriction_through         date,
  source_kind                 text not null,
  source_ref                  text not null,
  source_url                  text not null,
  source_hash                 text not null,
  source_line_hash            text not null,
  match_method                text not null,
  displayable                 boolean not null,
  parser_version              text not null,
  created_at                  timestamptz not null,
  updated_at                  timestamptz not null,
  event_key                   text,
  support_detail              text,
  support_condition_group     text,
  support_reported_date       date,
  support_restriction_from    date,
  support_restriction_through date,
  support_source_kind         text,
  support_source_ref          text,
  support_source_url          text,
  primary key (event_id)
);

-- ---------------------------------------------------------------- 7) 制裁(§111)
create table if not exists public.nar_penalties (
  penalty_id          text not null,
  track               text not null,
  race_date           date not null,
  race_no             smallint,
  person_kind         text not null,
  person_name         text not null,
  kind                text not null,
  detail              text not null,
  suspension_from     date,
  suspension_through  date,
  source_url          text not null,
  source_hash         text not null,
  parser_version      text not null,
  created_at          timestamptz not null,
  updated_at          timestamptz not null,
  horse_name          text,                 -- §156 F1(2026-09-12)で本番に足した列。⛔本番と列の並びを同じにしないと \copy が「extra data after last expected column」で落ちる
  primary key (penalty_id)
);

-- ---------------------------------------------------------------- 8) 売得(view nar_sales_daily の材料)
create table if not exists public.nar_sales (
  track       text    not null,
  race_date   date    not null,
  race_no     integer not null,
  votes       jsonb   not null,
  refunds     jsonb   not null,
  updated_at  timestamptz not null,
  primary key (track, race_date, race_no)
);

-- ⛔本番の view の定義そのまま(`pg_get_viewdef` の写し・2026-09-08 実測)。
--   本番では group by を掛けない= 材料の nar_sales だけ写して、束ねるのは地元でやる。
create or replace view public.nar_sales_daily as
  select s.track,
         s.race_date,
         count(*)::integer   as races,
         sum(v.net)::bigint  as net_votes,
         max(s.updated_at)   as updated_at
    from public.nar_sales s
    cross join lateral (
      select sum(coalesce((s.votes ->> k.k)::bigint, 0::bigint)
                 - coalesce((s.refunds ->> k.k)::bigint, 0::bigint)) as net
        from jsonb_object_keys(s.votes) k(k)) v
   group by s.track, s.race_date;

-- ---------------------------------------------------------------- 9) メタ(⛔ key='noken_index' の 1 行だけ写す)
create table if not exists public.nar_meta (
  key         text  not null,
  value       jsonb not null,
  updated_at  timestamptz not null,
  primary key (key)
);

commit;

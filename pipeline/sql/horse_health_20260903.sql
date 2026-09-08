-- §89 公表された疾病・競走事故履歴 v1（2026-09-03）。
-- 加算テーブル2本と、source_ref 1単位を1トランザクションで採用する service_role 専用RPC。
-- 適用: py -3.12 -X utf8 pipeline/dbadmin.py file pipeline/sql/horse_health_20260903.sql
-- ⛔既存表・既存行は変更しない。anon/authenticated は displayable=true の履歴だけ読める。

begin;

create table if not exists public.nar_horse_health_events (
  event_id             text        primary key,
  horse_name           text        not null,
  birth_date           date,
  horse_code           text,
  jbis_id               text,
  track                 text,
  race_date             date,
  race_no               smallint,
  runner_number         smallint,
  event_date            date,
  reported_date         date        not null,
  stage                 text        not null,
  event_type            text        not null,
  condition_group       text        not null,
  race_status           text,
  detail                text        not null,
  restriction_from      date,
  restriction_through   date,
  source_kind           text        not null,
  source_ref            text        not null,
  source_url            text        not null,
  source_hash           text        not null,
  source_line_hash      text        not null,
  match_method          text        not null,
  displayable           boolean     not null default false,
  parser_version        text        not null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),

  constraint nar_horse_health_event_id_ck
    check (event_id ~ '^[0-9a-f]{64}$'),
  constraint nar_horse_health_horse_name_ck
    check (btrim(horse_name) <> ''),
  constraint nar_horse_health_horse_code_ck
    check (horse_code is null or horse_code ~ '^[0-9]{11}$'),
  constraint nar_horse_health_race_no_ck
    check (race_no is null or race_no between 1 and 12),
  constraint nar_horse_health_runner_number_ck
    check (runner_number is null or runner_number between 1 and 99),
  constraint nar_horse_health_stage_ck
    check (stage in ('pre_race', 'in_race', 'post_race', 'auction_disclosure')),
  constraint nar_horse_health_event_type_ck
    check (event_type in ('withdrawal', 'exclusion', 'did_not_finish',
                          'post_race_condition', 'auction_disclosure')),
  constraint nar_horse_health_condition_group_ck
    check (condition_group in ('disease', 'musculoskeletal', 'epistaxis',
                               'cardiac', 'accident', 'unspecified')),
  constraint nar_horse_health_race_status_ck
    check (race_status is null or race_status in ('出走取消', '競走除外', '競走中止')),
  constraint nar_horse_health_detail_ck
    check (char_length(btrim(detail)) between 1 and 1000),
  constraint nar_horse_health_restriction_ck
    check (restriction_from is null or restriction_through is null
           or restriction_through >= restriction_from),
  constraint nar_horse_health_source_kind_ck
    check (source_kind in ('nar_pdf', 'rakuten', 'sat')),
  constraint nar_horse_health_source_ref_ck
    check ((source_kind = 'nar_pdf' and source_ref ~ '^[0-9]{8}/[0-9]{2}$')
        or (source_kind = 'rakuten' and source_ref ~ '^rakuten/[0-9]+$')
        or (source_kind = 'sat' and source_ref ~ '^sat/[0-9]+$')),
  constraint nar_horse_health_source_url_ck
    check ((source_kind = 'nar_pdf' and
              (source_url like 'https://www.keiba.go.jp/%' or source_url like 'https://keiba.go.jp/%'))
        or (source_kind = 'rakuten' and source_url like 'https://auction.keiba.rakuten.co.jp/item/%')
        or (source_kind = 'sat' and source_url like 'https://www.sat-auction.jp/auction/%')),
  constraint nar_horse_health_source_hash_ck
    check (source_hash ~ '^[0-9a-f]{64}$'),
  constraint nar_horse_health_source_line_hash_ck
    check (source_line_hash ~ '^[0-9a-f]{64}$'),
  constraint nar_horse_health_match_method_ck
    check (match_method in ('race_key_name', 'name_birth', 'horse_code',
                            'auction_item', 'unmatched')),
  constraint nar_horse_health_parser_version_ck
    check (btrim(parser_version) <> ''),
  constraint nar_horse_health_displayable_identity_ck
    check (not displayable or
      (source_kind = 'nar_pdf'
       and match_method = 'race_key_name'
       and track is not null and btrim(track) <> ''
       and race_date is not null and race_no is not null and runner_number is not null
       and reported_date = race_date
       and stage <> 'auction_disclosure' and event_type <> 'auction_disclosure'
       and source_ref = to_char(race_date, 'YYYYMMDD') || '/' ||
         case track
           when '帯広ば' then '03' when '門別' then '36'
           when '盛岡' then '10' when '水沢' then '11'
           when '浦和' then '18' when '船橋' then '19'
           when '大井' then '20' when '川崎' then '21'
           when '金沢' then '22' when '笠松' then '23'
           when '名古屋' then '24' when '園田' then '27'
           when '姫路' then '28' when '高知' then '31'
           when '佐賀' then '32'
           else '__'
         end)
      or
      (source_kind in ('rakuten', 'sat')
       and match_method = 'auction_item'
       and track is null and race_date is null and race_no is null and runner_number is null
       and stage = 'auction_disclosure' and event_type = 'auction_disclosure'))
);

create index if not exists nar_horse_health_name_birth_date_idx
  on public.nar_horse_health_events (horse_name, birth_date, reported_date desc);
create index if not exists nar_horse_health_horse_code_idx
  on public.nar_horse_health_events (horse_code, reported_date desc);
create index if not exists nar_horse_health_race_runner_idx
  on public.nar_horse_health_events (track, race_date, race_no, runner_number);
create index if not exists nar_horse_health_source_idx
  on public.nar_horse_health_events (source_kind, source_ref);

alter table public.nar_horse_health_events enable row level security;
drop policy if exists nar_horse_health_events_read on public.nar_horse_health_events;
create policy nar_horse_health_events_read on public.nar_horse_health_events
  for select to anon, authenticated using (displayable = true);
revoke all on table public.nar_horse_health_events from public, anon, authenticated;
grant select on public.nar_horse_health_events to anon, authenticated;
grant select, insert, update, delete on public.nar_horse_health_events to service_role;

-- 取得・採用状態。画面からは存在も内容も読ませない。
create table if not exists public.nar_health_imports (
  source_kind          text        not null,
  source_ref           text        not null,
  source_url           text        not null,
  source_hash          text,
  parser_version       text        not null,
  status               text        not null,
  event_count          integer     not null default 0,
  review_count         integer     not null default 0,
  attempt_count        integer     not null default 0,
  failure_count        integer     not null default 0,
  http_etag            text,
  http_last_modified   text,
  first_seen_at        timestamptz not null default now(),
  last_checked_at      timestamptz not null default now(),
  completed_at         timestamptz,
  last_error           text,
  primary key (source_kind, source_ref),

  constraint nar_health_imports_source_kind_ck
    check (source_kind in ('nar_pdf', 'rakuten', 'sat')),
  constraint nar_health_imports_source_ref_ck
    check ((source_kind = 'nar_pdf' and source_ref ~ '^[0-9]{8}/[0-9]{2}$')
        or (source_kind = 'rakuten' and source_ref ~ '^rakuten/[0-9]+$')
        or (source_kind = 'sat' and source_ref ~ '^sat/[0-9]+$')),
  constraint nar_health_imports_source_url_ck
    check ((source_kind = 'nar_pdf' and
              (source_url like 'https://www.keiba.go.jp/%' or source_url like 'https://keiba.go.jp/%'))
        or (source_kind = 'rakuten' and source_url like 'https://auction.keiba.rakuten.co.jp/item/%')
        or (source_kind = 'sat' and source_url like 'https://www.sat-auction.jp/auction/%')),
  constraint nar_health_imports_hash_ck
    check (source_hash is null or source_hash ~ '^[0-9a-f]{64}$'),
  constraint nar_health_imports_parser_version_ck
    check (btrim(parser_version) <> ''),
  constraint nar_health_imports_status_ck
    check (status in ('complete', 'not_ready', 'review', 'error', 'changed')),
  constraint nar_health_imports_counts_ck
    check (event_count >= 0 and review_count >= 0 and attempt_count >= 0),
  constraint nar_health_imports_failure_count_ck
    check (failure_count >= 0),
  constraint nar_health_imports_error_len_ck
    check (last_error is null or char_length(last_error) <= 500)
);

-- 既にv1表があるDBへも安全に足す。旧attempt_count/first_seen_atから推測せず0開始。
alter table public.nar_health_imports
  add column if not exists failure_count integer not null default 0;
do $$ begin
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.nar_health_imports'::regclass
       and conname = 'nar_health_imports_failure_count_ck'
  ) then
    alter table public.nar_health_imports
      add constraint nar_health_imports_failure_count_ck check (failure_count >= 0);
  end if;
end $$;

alter table public.nar_health_imports enable row level security;
drop policy if exists nar_health_imports_read on public.nar_health_imports;
revoke all on table public.nar_health_imports from public, anon, authenticated;
grant select, insert, update, delete on public.nar_health_imports to service_role;

-- source 1件の検証済みstaging(JSON)を一括採用する。
-- p_events=NULL は304/同一hashのtouch（本文同期なし）、[] は解析成功0件（旧行を0件へ置換）。
-- completeだけが公開行を丸ごと置換する。reviewは非公開候補だけ同期し、従来の公開行は保持する。
create or replace function public.apply_nar_health_source(
  p_source_kind        text,
  p_source_ref         text,
  p_source_url         text,
  p_source_hash        text,
  p_parser_version     text,
  p_status             text,
  p_events             jsonb,
  p_review_count       integer,
  p_http_etag          text,
  p_http_last_modified text,
  p_last_error         text,
  p_force              boolean default false
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_kind             text := btrim(coalesce(p_source_kind, ''));
  v_ref              text := btrim(coalesce(p_source_ref, ''));
  v_url              text := btrim(coalesce(p_source_url, ''));
  v_parser           text := btrim(coalesce(p_parser_version, ''));
  v_status           text := btrim(coalesce(p_status, ''));
  v_hash             text := nullif(btrim(coalesce(p_source_hash, '')), '');
  v_event_count      integer := 0;
  v_review_count     integer := 0;
  v_displayable      integer := 0;
  v_distinct_ids     integer := 0;
  v_old_hash         text;
  v_old_events       integer := 0;
  v_old_review       integer := 0;
  v_old_displayable  integer := 0;
  v_db_events        integer := 0;
  v_db_review        integer := 0;
begin
  if v_kind not in ('nar_pdf', 'rakuten', 'sat') then
    raise exception 'bad source_kind';
  end if;
  if v_ref = '' or v_url = '' or v_parser = '' then
    raise exception 'source_ref/source_url/parser_version is required';
  end if;
  if v_status not in ('complete', 'not_ready', 'review', 'error', 'changed') then
    raise exception 'bad import status';
  end if;
  if not ((v_kind = 'nar_pdf' and
             (v_url like 'https://www.keiba.go.jp/%' or v_url like 'https://keiba.go.jp/%'))
       or (v_kind = 'rakuten' and v_url like 'https://auction.keiba.rakuten.co.jp/item/%')
       or (v_kind = 'sat' and v_url like 'https://www.sat-auction.jp/auction/%')) then
    raise exception 'source_url host is not allowed';
  end if;
  if p_last_error is not null and char_length(p_last_error) > 500 then
    raise exception 'last_error is too long';
  end if;

  -- 304/同一hash: 採用済み状態を一切動かさず、観測情報だけ更新する。
  if p_events is null then
    update public.nar_health_imports
       set attempt_count = attempt_count + 1,
           failure_count = case when v_status = 'complete' then 0 else failure_count end,
           last_checked_at = now(),
           http_etag = coalesce(p_http_etag, http_etag),
           http_last_modified = coalesce(p_http_last_modified, http_last_modified)
     where source_kind = v_kind and source_ref = v_ref;
    if not found then
      raise exception 'cannot touch an unknown source';
    end if;
    return (select jsonb_build_object(
      'status', i.status, 'applied', false, 'touched', true,
      'event_count', i.event_count, 'review_count', i.review_count,
      'failure_count', i.failure_count,
      'source_hash', i.source_hash)
      from public.nar_health_imports i
      where i.source_kind = v_kind and i.source_ref = v_ref);
  end if;

  -- 取得失敗系はイベントを採用しない。既存hash/parser/count/公開行を保持する。
  if v_status in ('not_ready', 'error', 'changed') then
    insert into public.nar_health_imports as i
      (source_kind, source_ref, source_url, source_hash, parser_version, status,
       event_count, review_count, attempt_count, failure_count, http_etag, http_last_modified,
       first_seen_at, last_checked_at, completed_at, last_error)
    values
      (v_kind, v_ref, v_url, null, v_parser, v_status,
       0, 0, 1,
       case when v_status in ('not_ready', 'error') and not coalesce(p_force, false) then 1 else 0 end,
       p_http_etag, p_http_last_modified,
       now(), now(), null, p_last_error)
    on conflict (source_kind, source_ref) do update
      set source_url = excluded.source_url,
          status = case
            when v_kind = 'nar_pdf' and v_status in ('not_ready', 'error')
                 and not coalesce(p_force, false) and i.failure_count + 1 >= 7 then 'review'
            else excluded.status
          end,
          review_count = case
            when v_kind = 'nar_pdf' and v_status in ('not_ready', 'error')
                 and not coalesce(p_force, false) and i.failure_count + 1 >= 7 then greatest(i.review_count, 1)
            else i.review_count
          end,
          attempt_count = i.attempt_count + 1,
          failure_count = case
            when v_status in ('not_ready', 'error') and not coalesce(p_force, false) then i.failure_count + 1
            else i.failure_count
          end,
          http_etag = coalesce(excluded.http_etag, i.http_etag),
          http_last_modified = coalesce(excluded.http_last_modified, i.http_last_modified),
          last_checked_at = now(),
          last_error = excluded.last_error;
    return (select jsonb_build_object(
      'status', i.status, 'applied', false, 'touched', false,
      'event_count', i.event_count, 'review_count', i.review_count,
      'failure_count', i.failure_count,
      'source_hash', i.source_hash)
      from public.nar_health_imports i
      where i.source_kind = v_kind and i.source_ref = v_ref);
  end if;

  if jsonb_typeof(p_events) <> 'array' then
    raise exception 'p_events must be an array or null';
  end if;
  if v_hash is not null and v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'bad source_hash';
  end if;

  select count(*), count(distinct e ->> 'event_id'),
         count(*) filter (where coalesce((e ->> 'displayable')::boolean, false) = false),
         count(*) filter (where coalesce((e ->> 'displayable')::boolean, false) = true)
    into v_event_count, v_distinct_ids, v_review_count, v_displayable
    from jsonb_array_elements(p_events) e;

  if v_distinct_ids <> v_event_count then
    raise exception 'duplicate event_id in source staging';
  end if;
  if coalesce(p_review_count, -1) < 0 then raise exception 'bad review_count'; end if;
  if v_status = 'complete' and v_hash is null then raise exception 'source_hash is required for complete'; end if;
  if v_status = 'review' and v_event_count > 0 and v_hash is null then
    raise exception 'source_hash is required for review events';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_events) e
     where coalesce(e ->> 'event_id', '') !~ '^[0-9a-f]{64}$'
        or e ->> 'source_kind' is distinct from v_kind
        or e ->> 'source_ref' is distinct from v_ref
        or e ->> 'source_url' is distinct from v_url
        or e ->> 'source_hash' is distinct from v_hash
        or e ->> 'parser_version' is distinct from v_parser
  ) then
    raise exception 'event staging/source metadata mismatch';
  end if;
  if v_status = 'complete' and (v_review_count <> 0 or p_review_count <> 0) then
    raise exception 'complete source contains non-displayable rows';
  end if;
  if v_status = 'review' and (v_displayable <> 0 or p_review_count < 1) then
    raise exception 'review source contains displayable rows';
  end if;
  if exists (
    select 1
      from jsonb_to_recordset(p_events) as x(
        horse_name text, track text, race_date date, race_no smallint,
        runner_number smallint, reported_date date, source_kind text,
        displayable boolean)
     where coalesce(x.displayable, false)
       and x.source_kind = 'nar_pdf'
       and not exists (
         select 1 from public.nar_runs r
          where r.track = x.track and r.race_date = x.race_date
            and r.race_no = x.race_no and r.runner_number = x.runner_number
            and btrim(coalesce(r.horse_name, '')) = btrim(coalesce(x.horse_name, ''))
            and x.reported_date = x.race_date
       )
  ) then
    raise exception 'displayable NAR event does not match nar_runs identity';
  end if;
  if exists (
    select 1
      from jsonb_to_recordset(p_events) as x(
        horse_name text, birth_date date, jbis_id text, reported_date date,
        source_kind text, source_ref text, source_url text, displayable boolean)
     where coalesce(x.displayable, false)
       and x.source_kind in ('rakuten', 'sat')
       and not exists (
         select 1 from public.auction_sales a
          where a.source = x.source_kind
            and a.item_id::text = split_part(x.source_ref, '/', 2)
            and btrim(coalesce(a.horse_name, '')) = btrim(coalesce(x.horse_name, ''))
            and a.birth_date is not distinct from x.birth_date
            and nullif(btrim(coalesce(a.jbis_id, '')), '') is not distinct from
                nullif(btrim(coalesce(x.jbis_id, '')), '')
            and a.auction_date = x.reported_date
            and a.url = x.source_url
       )
  ) then
    raise exception 'displayable auction event does not match auction_sales identity';
  end if;
  if exists (
    select 1
      from public.nar_horse_health_events h
      join jsonb_array_elements(p_events) e on e ->> 'event_id' = h.event_id
     where h.source_kind <> v_kind or h.source_ref <> v_ref
  ) then
    raise exception 'event_id already belongs to another source';
  end if;

  -- 同じsourceへの並行適用を直列化するため、監査行を先に作って行ロックする。
  insert into public.nar_health_imports
    (source_kind, source_ref, source_url, source_hash, parser_version, status,
     event_count, review_count, attempt_count, first_seen_at, last_checked_at)
  values (v_kind, v_ref, v_url, null, v_parser, 'not_ready', 0, 0, 0, now(), now())
  on conflict (source_kind, source_ref) do nothing;

  select i.source_hash, i.review_count into v_old_hash, v_old_review
    from public.nar_health_imports i
   where i.source_kind = v_kind and i.source_ref = v_ref
   for update;
  select count(*), count(*) filter (where displayable)
    into v_old_events, v_old_displayable
    from public.nar_horse_health_events
   where source_kind = v_kind and source_ref = v_ref;

  -- completeの公式訂正・解析退行は、明示forceまで旧公開行を保つ。
  if v_status = 'complete' and not coalesce(p_force, false)
     and (v_old_hash is not null and v_old_hash <> v_hash
          or (v_old_events > 0 and v_event_count = 0)
          or v_displayable < v_old_displayable) then
    update public.nar_health_imports
       set source_url = v_url,
           status = 'changed',
           attempt_count = attempt_count + 1,
           http_etag = coalesce(p_http_etag, http_etag),
           http_last_modified = coalesce(p_http_last_modified, http_last_modified),
           last_checked_at = now(),
           last_error = coalesce(p_last_error, 'source hash or displayable event set changed')
     where source_kind = v_kind and source_ref = v_ref;
    return jsonb_build_object(
      'status', 'changed', 'applied', false, 'touched', false,
      'event_count', v_old_events, 'review_count', v_old_review,
      'source_hash', v_old_hash);
  end if;

  -- review候補は以前の非公開候補だけ入れ替える。旧completeの公開行は消さない。
  if v_status = 'review' then
    delete from public.nar_horse_health_events
     where source_kind = v_kind and source_ref = v_ref and not displayable;
  end if;

  insert into public.nar_horse_health_events as h
    (event_id, horse_name, birth_date, horse_code, jbis_id,
     track, race_date, race_no, runner_number, event_date, reported_date,
     stage, event_type, condition_group, race_status, detail,
     restriction_from, restriction_through,
     source_kind, source_ref, source_url, source_hash, source_line_hash,
     match_method, displayable, parser_version, created_at, updated_at)
  select x.event_id, x.horse_name, x.birth_date, x.horse_code, x.jbis_id,
         x.track, x.race_date, x.race_no, x.runner_number, x.event_date, x.reported_date,
         x.stage, x.event_type, x.condition_group, x.race_status, x.detail,
         x.restriction_from, x.restriction_through,
         x.source_kind, x.source_ref, x.source_url, x.source_hash, x.source_line_hash,
         x.match_method, x.displayable, x.parser_version, now(), now()
    from jsonb_to_recordset(p_events) as x(
      event_id text, horse_name text, birth_date date, horse_code text, jbis_id text,
      track text, race_date date, race_no smallint, runner_number smallint,
      event_date date, reported_date date, stage text, event_type text,
      condition_group text, race_status text, detail text,
      restriction_from date, restriction_through date,
      source_kind text, source_ref text, source_url text, source_hash text,
      source_line_hash text, match_method text, displayable boolean, parser_version text)
  on conflict (event_id) do update
    set horse_name = excluded.horse_name,
        birth_date = excluded.birth_date,
        horse_code = excluded.horse_code,
        jbis_id = excluded.jbis_id,
        track = excluded.track,
        race_date = excluded.race_date,
        race_no = excluded.race_no,
        runner_number = excluded.runner_number,
        event_date = excluded.event_date,
        reported_date = excluded.reported_date,
        stage = excluded.stage,
        event_type = excluded.event_type,
        condition_group = excluded.condition_group,
        race_status = excluded.race_status,
        detail = excluded.detail,
        restriction_from = excluded.restriction_from,
        restriction_through = excluded.restriction_through,
        source_kind = excluded.source_kind,
        source_ref = excluded.source_ref,
        source_url = excluded.source_url,
        source_hash = excluded.source_hash,
        source_line_hash = excluded.source_line_hash,
        match_method = excluded.match_method,
        displayable = excluded.displayable,
        parser_version = excluded.parser_version,
        updated_at = now()
    where h.source_kind = v_kind
      and h.source_ref = v_ref
      and (v_status = 'complete' or not h.displayable);

  -- 別sourceとのevent_id競合が並行発生しても、既存行を移管せずsource全体をrollbackする。
  if exists (
    select 1
      from jsonb_array_elements(p_events) e
      left join public.nar_horse_health_events h on h.event_id = e ->> 'event_id'
     where h.event_id is null
        or h.source_kind is distinct from v_kind
        or h.source_ref is distinct from v_ref
  ) then
    raise exception 'event_id conflict during source apply';
  end if;

  if v_status = 'complete' then
    delete from public.nar_horse_health_events h
     where h.source_kind = v_kind and h.source_ref = v_ref
       and not exists (
         select 1 from jsonb_array_elements(p_events) e
          where e ->> 'event_id' = h.event_id
       );
  end if;

  select count(*), count(*) filter (where not displayable)
    into v_db_events, v_db_review
    from public.nar_horse_health_events
   where source_kind = v_kind and source_ref = v_ref;

  update public.nar_health_imports
     set source_url = v_url,
         source_hash = case
           when v_status = 'complete' or v_old_displayable = 0 then v_hash
           else v_old_hash
         end,
         parser_version = case
           when v_status = 'complete' or v_old_displayable = 0 then v_parser
           else parser_version
         end,
         status = v_status,
         event_count = v_db_events,
         review_count = case when v_status = 'complete' then 0 else p_review_count end,
         attempt_count = attempt_count + 1,
         failure_count = case when v_status = 'complete' then 0 else failure_count end,
         http_etag = coalesce(p_http_etag, http_etag),
         http_last_modified = coalesce(p_http_last_modified, http_last_modified),
         last_checked_at = now(),
         completed_at = case
           when v_status = 'complete' then now()
           else completed_at
         end,
         last_error = case when v_status = 'complete' then null else p_last_error end
   where source_kind = v_kind and source_ref = v_ref;

  return jsonb_build_object(
    'status', v_status, 'applied', true, 'touched', false,
    'event_count', v_db_events, 'review_count',
      case when v_status = 'complete' then 0 else p_review_count end,
    'failure_count', case when v_status = 'complete' then 0 else
      (select failure_count from public.nar_health_imports where source_kind = v_kind and source_ref = v_ref) end,
    'source_hash', case
      when v_status = 'complete' or v_old_displayable = 0 then v_hash
      else v_old_hash
    end);
end;
$$;

revoke all on function public.apply_nar_health_source(
  text, text, text, text, text, text, jsonb, integer, text, text, text, boolean
) from public, anon, authenticated, service_role;
grant execute on function public.apply_nar_health_source(
  text, text, text, text, text, text, jsonb, integer, text, text, text, boolean
) to service_role;

notify pgrst, 'reload schema';

commit;

select 'horse health schema ready' as status;

-- §193c オークション健康の分類 v2(2026-09-16・Fable)= condition_group に 13 値を足す・印 2 列・書く関数を v2 へ。
-- 主催者出典(nar_pdf)の経路と 5 値は触らない。実行= ユーザー(dbadmin.py sql)。冪等。
begin;

-- 1. 分類の値を足す(今の 6 値は残す)
alter table public.nar_horse_health_events drop constraint if exists nar_horse_health_condition_group_ck;
alter table public.nar_horse_health_events add constraint nar_horse_health_condition_group_ck
  check (condition_group in (
    'disease', 'musculoskeletal', 'epistaxis', 'cardiac', 'accident', 'unspecified',
    'bone_joint', 'tendon_ligament', 'hoof', 'muscle_back', 'respiratory',
    'digestive', 'eye', 'skin_wound', 'fever_infection', 'symptom', 'castration'));

-- 2. 印 2 列(競走能力喪失・当たった語)
alter table public.nar_horse_health_events add column if not exists racing_ability_lost boolean not null default false;
alter table public.nar_horse_health_events add column if not exists condition_term text;
alter table public.nar_horse_health_events drop constraint if exists nar_horse_health_condition_term_ck;
alter table public.nar_horse_health_events add constraint nar_horse_health_condition_term_ck
  check (condition_term is null or char_length(condition_term) between 1 and 40);

-- 3. 書く関数 v2= v1(9/3 本体・9/4 に private へ改名)の写しに 2 列を足しただけ
create or replace function private._apply_nar_health_auction_source_v2(
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
     match_method, displayable, parser_version, created_at, updated_at,
     racing_ability_lost, condition_term)
  select x.event_id, x.horse_name, x.birth_date, x.horse_code, x.jbis_id,
         x.track, x.race_date, x.race_no, x.runner_number, x.event_date, x.reported_date,
         x.stage, x.event_type, x.condition_group, x.race_status, x.detail,
         x.restriction_from, x.restriction_through,
         x.source_kind, x.source_ref, x.source_url, x.source_hash, x.source_line_hash,
         x.match_method, x.displayable, x.parser_version, now(), now(),
         coalesce(x.racing_ability_lost, false), nullif(btrim(x.condition_term), '')
    from jsonb_to_recordset(p_events) as x(
      event_id text, horse_name text, birth_date date, horse_code text, jbis_id text,
      track text, race_date date, race_no smallint, runner_number smallint,
      event_date date, reported_date date, stage text, event_type text,
      condition_group text, race_status text, detail text,
      restriction_from date, restriction_through date,
      source_kind text, source_ref text, source_url text, source_hash text,
      source_line_hash text, match_method text, displayable boolean, parser_version text,
      racing_ability_lost boolean, condition_term text)
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
        racing_ability_lost = excluded.racing_ability_lost,
        condition_term = excluded.condition_term,
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

revoke all on function private._apply_nar_health_auction_source_v2(
  text, text, text, text, text, text, jsonb, integer, text, text, text, boolean
) from public, anon, authenticated, service_role;
grant execute on function private._apply_nar_health_auction_source_v2(
  text, text, text, text, text, text, jsonb, integer, text, text, text, boolean
) to service_role;

-- 4. 公開の入口を v2 へ(9/4 の包み・中身は呼び先だけ違う)
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
begin
  if btrim(coalesce(p_source_kind, '')) not in ('rakuten', 'sat') then
    raise exception 'apply_nar_health_source is auction-only';
  end if;
  if not private.nar_health_source_url_ok(btrim(p_source_kind), btrim(p_source_url)) then
    raise exception 'source_url is not allowed';
  end if;
  return private._apply_nar_health_auction_source_v2(
    p_source_kind, p_source_ref, p_source_url, p_source_hash, p_parser_version,
    p_status, p_events, p_review_count, p_http_etag, p_http_last_modified,
    p_last_error, p_force
  );
end
$$;

commit;

-- 確認(読むだけ)
select conname, pg_get_constraintdef(oid) from pg_constraint
 where conrelid = 'public.nar_horse_health_events'::regclass and conname like 'nar_horse_health_condition%';
select column_name, data_type, column_default from information_schema.columns
 where table_name = 'nar_horse_health_events' and column_name in ('racing_ability_lost','condition_term');
select proname, pronamespace::regnamespace from pg_proc where proname like '%apply_nar_health_auction_source%';

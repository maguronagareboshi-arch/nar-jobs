-- §217 マイチェック 後続②「振り返り」(2026-09-19 Fable・本番 nar-official に apply 済み)
-- 器= nar_viewer_reviews(端末×馬×レースの控え= 当時の条件/状態/理由+あとから)。正本は端末(localStorage)・サーバーは写し(引き継ぎ用)
create table if not exists public.nar_viewer_reviews (
  device_id  uuid not null,
  horse_id   text not null,
  race_key   text not null,            -- 'ooi/2026-09-18/2'(ビューアの raceId)
  "check"    jsonb,                    -- 当時の条件(nar_viewer_horses.check と同じ形)・無ければ null
  state      text,                     -- 当時の照合の状態 ok/ng/wait/any/cancel
  reason     text,                     -- 当時の理由(140 字まで)
  after      text,                     -- あとから(発走後の追記・140 字まで)
  at         timestamptz not null default now(),   -- 控えた時刻
  updated_at timestamptz not null default now(),
  primary key (device_id, horse_id, race_key)
);
alter table public.nar_viewer_reviews enable row level security;
revoke all on public.nar_viewer_reviews from anon, authenticated;

-- 丸ごと置換(viewer_horses_save と同じ作法)。⛔上限= 300 行/端末・check 600 字・reason/after 140 字。長すぎる行は落として続ける
create or replace function public.viewer_reviews_save(p_device uuid, p_reviews jsonb)
returns void language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare v_n int;
begin
  if p_device is null then raise exception '端末の識別子がありません'; end if;
  if p_reviews is null or jsonb_typeof(p_reviews) <> 'array' then raise exception '振り返りの一覧が配列ではありません'; end if;
  v_n := jsonb_array_length(p_reviews);
  if v_n > 300 then raise exception '振り返りは 300 件までです(いまは % 件)', v_n; end if;
  with src as (
    select btrim(e ->> 'horse_id') as horse_id, btrim(e ->> 'race_key') as race_key,
           case when jsonb_typeof(e -> 'check') = 'object' and char_length((e -> 'check')::text) <= 600 then e -> 'check' else null end as chk,
           nullif(btrim(e ->> 'state'), '') as state,
           nullif(btrim(e ->> 'reason'), '') as reason,
           nullif(btrim(e ->> 'after'), '') as after,
           coalesce((e ->> 'at')::timestamptz, now()) as at, ord
      from jsonb_array_elements(p_reviews) with ordinality as t(e, ord)
     where jsonb_typeof(e) = 'object'
  ), want as (
    select distinct on (horse_id, race_key) * from src
     where coalesce(horse_id, '') <> '' and char_length(horse_id) <= public._viewer_limit('horse')
       and coalesce(race_key, '') <> '' and char_length(race_key) <= 60
       and char_length(coalesce(reason, '')) <= 140 and char_length(coalesce(after, '')) <= 140
       and char_length(coalesce(state, '')) <= 10
     order by horse_id, race_key, ord
  ), del as (
    delete from public.nar_viewer_reviews r
     where r.device_id = p_device and not exists (select 1 from want w where w.horse_id = r.horse_id and w.race_key = r.race_key)
  )
  insert into public.nar_viewer_reviews as t (device_id, horse_id, race_key, "check", state, reason, after, at)
  select p_device, horse_id, race_key, chk, state, reason, after, at from want
  on conflict (device_id, horse_id, race_key) do update
    set "check" = excluded."check", state = excluded.state, reason = excluded.reason, after = excluded.after, at = excluded.at, updated_at = now();
end $$;
grant execute on function public.viewer_reviews_save(uuid, jsonb) to anon;

-- 引き継ぎに reviews を足す(既存の返りはそのまま)
create or replace function public.viewer_handover_claim(p_code text)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare
  v_code text := upper(btrim(coalesce(p_code, '')));
  v_hash text; v_dev uuid; v_tries int; v_notes jsonb; v_horses jsonb; v_reviews jsonb;
begin
  delete from public.nar_viewer_claim_tries where last_at < now() - interval '1 hour';
  delete from public.nar_viewer_handover    where expires_at < now();
  if char_length(v_code) <> public._viewer_limit('code_len') then
    return jsonb_build_object('ok', false, 'error', 'bad_format');
  end if;
  v_hash := public._viewer_code_hash(v_code);
  select tries into v_tries from public.nar_viewer_claim_tries where code_hash = v_hash;
  if coalesce(v_tries, 0) >= public._viewer_limit('claim_fails') then
    delete from public.nar_viewer_handover where code_hash = v_hash;
    return jsonb_build_object('ok', false, 'error', 'too_many_tries');
  end if;
  select device_id into v_dev from public.nar_viewer_handover where code_hash = v_hash and expires_at > now();
  if v_dev is null then
    insert into public.nar_viewer_claim_tries as t (code_hash, tries) values (v_hash, 1)
    on conflict (code_hash) do update set tries = t.tries + 1, last_at = now();
    return jsonb_build_object('ok', false, 'error', 'not_found');
  end if;
  select coalesce(jsonb_agg(jsonb_build_object('horse_id', horse_id, 'body', body, 'updated_at', updated_at) order by updated_at desc), '[]'::jsonb)
    into v_notes from public.nar_viewer_notes where device_id = v_dev;
  select coalesce(jsonb_agg(jsonb_build_object('id', horse_id, 'name', name, 'added_at', added_at, 'check', "check") order by added_at desc), '[]'::jsonb)
    into v_horses from public.nar_viewer_horses where device_id = v_dev;
  select coalesce(jsonb_agg(jsonb_build_object('horse_id', horse_id, 'race_key', race_key, 'check', "check", 'state', state, 'reason', reason, 'after', after, 'at', at) order by at desc), '[]'::jsonb)
    into v_reviews from public.nar_viewer_reviews where device_id = v_dev;
  delete from public.nar_viewer_handover    where device_id = v_dev;
  delete from public.nar_viewer_claim_tries where code_hash = v_hash;
  return jsonb_build_object('ok', true, 'count', jsonb_array_length(v_notes), 'notes', v_notes,
    'horse_count', jsonb_array_length(v_horses), 'horses', v_horses, 'reviews', v_reviews);
end $$;

create or replace function public.viewer_purge(p_device uuid)
returns void language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
begin
  if p_device is null then raise exception '端末の識別子がありません'; end if;
  delete from public.nar_viewer_notes    where device_id = p_device;
  delete from public.nar_viewer_horses   where device_id = p_device;
  delete from public.nar_viewer_reviews  where device_id = p_device;
  delete from public.nar_viewer_handover where device_id = p_device;
end $$;

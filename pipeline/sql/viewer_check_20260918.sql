-- §209 マイチェック(2026-09-18)= マイホースの行に「条件と理由」(check jsonb)を足す。
-- 端末が正本(localStorage kv_my_horses)・サーバは写し。引き継ぎコードで一緒に移る。
-- check の形= {"dist": ""|"1400"|"1600", "going": ""|"good", "reason": "≤140 字", "paused": bool, "at": "ISO"}
alter table public.nar_viewer_horses add column if not exists "check" jsonb;

create or replace function public.viewer_horses_save(p_device uuid, p_horses jsonb)
 returns void language plpgsql security definer set search_path to 'public', 'pg_temp' as $function$
declare
  v_n   int;
  v_bad int;
begin
  if p_device is null then raise exception '端末の識別子がありません'; end if;
  if p_horses is null or jsonb_typeof(p_horses) <> 'array' then raise exception '登録した馬の一覧が配列ではありません'; end if;
  v_n := jsonb_array_length(p_horses);
  if v_n > public._viewer_limit('horses') then
    raise exception '登録できる馬は % 頭までです(いまは % 頭)', public._viewer_limit('horses'), v_n;
  end if;
  select count(*) into v_bad from jsonb_array_elements(p_horses) e where jsonb_typeof(e) <> 'object';
  if v_bad > 0 then raise exception '馬の形が違います(% 件)', v_bad; end if;
  select count(*) into v_bad from jsonb_array_elements(p_horses) e where coalesce(btrim(e ->> 'id'), '') = '';
  if v_bad > 0 then raise exception '馬の識別子がありません(% 件)', v_bad; end if;
  select count(*) into v_bad from jsonb_array_elements(p_horses) e where char_length(btrim(e ->> 'id')) > public._viewer_limit('horse');
  if v_bad > 0 then raise exception '馬の識別子が長すぎます(上限 % 文字・% 件)', public._viewer_limit('horse'), v_bad; end if;
  select count(*) into v_bad from jsonb_array_elements(p_horses) e where char_length(coalesce(btrim(e ->> 'name'), '')) > public._viewer_limit('name');
  if v_bad > 0 then raise exception '馬の名前が長すぎます(上限 % 文字・% 件)', public._viewer_limit('name'), v_bad; end if;
  -- §209 check= object か無し。理由は 140 字まで・全体 600 字まで(1 頭のせいで全部が写らなくなるのは避ける= 長い行は check を落として続ける)
  with src as (
    select btrim(e ->> 'id') as horse_id, coalesce(btrim(e ->> 'name'), '') as name,
           case when jsonb_typeof(e -> 'check') = 'object'
                 and char_length((e -> 'check')::text) <= 600
                 and char_length(coalesce(e -> 'check' ->> 'reason', '')) <= 140
                then e -> 'check' else null end as chk,
           ord
      from jsonb_array_elements(p_horses) with ordinality as t(e, ord)
  ), want as (
    select distinct on (horse_id) horse_id, name, chk from src order by horse_id, ord
  ), del as (
    delete from public.nar_viewer_horses h
     where h.device_id = p_device and not exists (select 1 from want w where w.horse_id = h.horse_id)
  )
  insert into public.nar_viewer_horses as t (device_id, horse_id, name, "check")
  select p_device, w.horse_id, w.name, w.chk from want w
  on conflict (device_id, horse_id) do update
    set name = excluded.name, "check" = excluded."check";   -- ⛔added_at は動かさない
end
$function$;

create or replace function public.viewer_handover_claim(p_code text)
 returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $function$
declare
  v_code   text := upper(btrim(coalesce(p_code, '')));
  v_hash   text;
  v_dev    uuid;
  v_tries  int;
  v_notes  jsonb;
  v_horses jsonb;
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
  -- §209 check も一緒に返す(無ければ null)
  select coalesce(jsonb_agg(jsonb_build_object('id', horse_id, 'name', name, 'added_at', added_at, 'check', "check") order by added_at desc), '[]'::jsonb)
    into v_horses from public.nar_viewer_horses where device_id = v_dev;
  delete from public.nar_viewer_handover    where device_id = v_dev;
  delete from public.nar_viewer_claim_tries where code_hash = v_hash;
  return jsonb_build_object('ok', true, 'count', jsonb_array_length(v_notes), 'notes', v_notes,
    'horse_count', jsonb_array_length(v_horses), 'horses', v_horses);
end
$function$;

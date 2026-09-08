-- §92 全11主催者公式の疾病詳細補完（2026-09-05）。
-- 適用済み20260904 migrationは変更せず、allowlistと同一RPCの受理範囲だけを前進させる。
-- raw HTML/PDFや全文は保存しない。

-- BEGIN §92 ALL HORSE HEALTH ORGANIZERS
begin;

create or replace function private.nar_health_race_kind_ok(p_kind text)
returns boolean
language sql immutable strict
set search_path = pg_catalog, pg_temp
as $$
  select p_kind in (
    'nar_pdf', 'funabashi_official', 'ooi_official', 'urawa_official',
    'kawasaki_official', 'banei_official', 'iwate_official', 'kanazawa_official',
    'kasamatsu_official', 'nagoya_official', 'kochi_official', 'saga_official'
  )
$$;

create or replace function private.nar_health_race_ref_ok(p_kind text, p_ref text)
returns boolean
language sql immutable strict
set search_path = pg_catalog, pg_temp
as $$
  select case p_kind
    when 'nar_pdf' then p_ref ~ '^[0-9]{8}/[0-9]{2}$'
    when 'funabashi_official' then p_ref ~ '^funabashi/[0-9]{8}$'
    when 'ooi_official' then p_ref ~ '^ooi/[0-9]{8}$'
    when 'urawa_official' then p_ref ~ '^urawa/[0-9]{8}$'
    when 'kawasaki_official' then p_ref ~ '^kawasaki/[0-9]{8}$'
    when 'banei_official' then p_ref ~ '^banei/[0-9]{8}$'
    when 'iwate_official' then p_ref ~ '^iwate/[0-9]{8}$'
    when 'kanazawa_official' then p_ref ~ '^kanazawa/[0-9]{8}$'
    when 'kasamatsu_official' then p_ref ~ '^kasamatsu/[0-9]{8}$'
    when 'nagoya_official' then p_ref ~ '^nagoya/[0-9]{8}$'
    when 'kochi_official' then p_ref ~ '^kochi/[0-9]{8}$'
    when 'saga_official' then p_ref ~ '^saga/[0-9]{8}$'
    else false
  end
$$;

create or replace function private.nar_health_source_url_ok(p_kind text, p_url text)
returns boolean
language sql immutable strict
set search_path = pg_catalog, pg_temp
as $$
  select case p_kind
    when 'nar_pdf' then p_url ~ '^https://(www[.])?keiba[.]go[.]jp/seisekipdf/[0-9]{8}/[0-9]{2}/[0-9]{8}_[a-z0-9]+[.]pdf$'
    when 'rakuten' then p_url ~ '^https://auction[.]keiba[.]rakuten[.]co[.]jp/item/[0-9]+/?$'
    when 'sat' then p_url ~ '^https://www[.]sat-auction[.]jp/auction/[0-9]+/?$'
    when 'funabashi_official' then p_url ~ '^https://blog[.]f-keiba[.]com/news/[0-9]{4}/(0[1-9]|1[0-2])/$'
    when 'ooi_official' then p_url ~ '^https://www[.]tokyocitykeiba[.]com/news/[0-9]+/$'
    when 'urawa_official' then p_url ~ '^https://www[.]urawa-keiba[.]jp/info/news/index[.]obj[?]cid=news&fid=file1&uid=[0-9]+$'
    when 'kawasaki_official' then p_url ~ '^https://www[.]kawasaki-keiba[.]jp/info/news/index[.]img[?]cid=news&fid=pdf1&uid=[0-9]+$'
    when 'banei_official' then p_url ~ '^https://banei-keiba[.]or[.]jp/tp_detail[.]php[?]id=[0-9]+$'
    when 'iwate_official' then p_url ~ '^https://www[.]iwatekeiba[.]or[.]jp/news/[0-9a-z-]+$'
    when 'kanazawa_official' then p_url ~ '^https://www[.]kanazawakeiba[.]com/wp-content/uploads/2026/(0[1-9]|1[0-2])/[A-Za-z0-9_.-]+[.]pdf$'
    when 'kasamatsu_official' then p_url ~ '^https://www[.]kasamatsu-keiba[.]com/resources/pdfs/news/2026/[A-Za-z0-9_.-]+[.]pdf$'
    when 'nagoya_official' then p_url ~ '^https://www[.]nagoyakeiba[.]com/news/file/[A-Za-z0-9_.-]+[.]pdf$'
    when 'kochi_official' then p_url ~ '^https://www[.]keiba[.]or[.]jp/[?]p=[0-9]+$'
    when 'saga_official' then p_url ~ '^https://www[.]sagakeiba[.]net/news/2026/(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])/[0-9]+/$'
    else false
  end
$$;

create or replace function private.nar_health_import_url_ok(p_kind text, p_url text)
returns boolean
language sql immutable strict
set search_path = pg_catalog, pg_temp
as $$
  select private.nar_health_source_url_ok(p_kind, p_url)
    or (p_kind = 'ooi_official' and
        p_url ~ '^https://www[.]tokyocitykeiba[.]com/news/feed/[?]s=%E5%87%BA%E6%9D%A5%E4%BA%8B&paged=([1-9]|1[0-9]|20)$')
    or (p_kind = 'urawa_official' and
        p_url ~ '^https://www[.]urawa-keiba[.]jp/info/news/[?]page=1&year=20(19|[2-9][0-9])&month=([1-9]|1[0-2])&category=race$')
    or (p_kind = 'kawasaki_official' and
        (p_url = 'https://www.kawasaki-keiba.jp/search.html?keyword=%E5%87%BA%E6%9D%A5%E4%BA%8B'
         or p_url = 'https://www.kawasaki-keiba.jp/api/api_news_list.html?category=all&limit=20&output=json&page=1'))
    or (p_kind = 'banei_official' and
        p_url = 'https://banei-keiba.or.jp/tp_list.php?wt=key&wv=%E5%87%BA%E6%9D%A5%E4%BA%8B')
    or (p_kind = 'iwate_official' and
        p_url = 'https://www.iwatekeiba.or.jp/feed/?s=%E5%87%BA%E6%9D%A5%E4%BA%8B&paged=1')
    or (p_kind = 'kanazawa_official' and
        p_url = 'https://www.kanazawakeiba.com/info/race/')
    or (p_kind = 'kasamatsu_official' and
        p_url ~ '^https://www[.]kasamatsu-keiba[.]com/news[?]y=2026&m=([1-9]|1[0-2])$')
    or (p_kind = 'nagoya_official' and
        p_url = 'https://www.nagoyakeiba.com/news/2026/')
    or (p_kind = 'kochi_official' and
        p_url = 'https://www.keiba.or.jp/wp/?cat=33&paged=1')
    or (p_kind = 'saga_official' and
        p_url = 'https://www.sagakeiba.net/news/feed/?s=%E4%BB%8A%E6%97%A5%E3%81%AE%E5%87%BA%E6%9D%A5%E4%BA%8B')
$$;

revoke all on function private.nar_health_race_kind_ok(text) from public, anon, authenticated;
revoke all on function private.nar_health_race_ref_ok(text,text) from public, anon, authenticated;
revoke all on function private.nar_health_source_url_ok(text,text) from public, anon, authenticated;
revoke all on function private.nar_health_import_url_ok(text,text) from public, anon, authenticated;
grant execute on function private.nar_health_race_kind_ok(text) to service_role;
grant execute on function private.nar_health_race_ref_ok(text,text) to service_role;
grant execute on function private.nar_health_source_url_ok(text,text) to service_role;
grant execute on function private.nar_health_import_url_ok(text,text) to service_role;

alter table public.nar_horse_health_events
  drop constraint if exists nar_horse_health_source_kind_ck,
  drop constraint if exists nar_horse_health_source_ref_ck,
  drop constraint if exists nar_horse_health_source_url_ck,
  drop constraint if exists nar_horse_health_event_kind_ck,
  drop constraint if exists nar_horse_health_support_ck,
  drop constraint if exists nar_horse_health_displayable_identity_ck;

alter table public.nar_horse_health_events
  add constraint nar_horse_health_source_kind_ck check (
    private.nar_health_race_kind_ok(source_kind) or source_kind in ('rakuten', 'sat')),
  add constraint nar_horse_health_source_ref_ck check (
    private.nar_health_race_ref_ok(source_kind, source_ref)
    or (source_kind = 'rakuten' and source_ref ~ '^rakuten/[0-9]+$')
    or (source_kind = 'sat' and source_ref ~ '^sat/[0-9]+$')),
  add constraint nar_horse_health_source_url_ck check (
    private.nar_health_source_url_ok(source_kind, source_url)),
  add constraint nar_horse_health_event_kind_ck check (
    (event_type = 'auction_disclosure' and source_kind in ('rakuten', 'sat') and event_key is null)
    or (event_type <> 'auction_disclosure' and private.nar_health_race_kind_ok(source_kind))),
  add constraint nar_horse_health_support_ck check (
    (support_source_kind is null and support_detail is null and support_condition_group is null
      and support_reported_date is null and support_restriction_from is null
      and support_restriction_through is null and support_source_ref is null and support_source_url is null)
    or (private.nar_health_race_kind_ok(support_source_kind) and support_source_kind <> 'nar_pdf'
      and char_length(btrim(support_detail)) between 1 and 1000
      and support_condition_group in ('disease', 'musculoskeletal', 'epistaxis', 'cardiac', 'accident', 'unspecified')
      and support_reported_date is not null
      and private.nar_health_race_ref_ok(support_source_kind, support_source_ref)
      and private.nar_health_source_url_ok(support_source_kind, support_source_url))),
  add constraint nar_horse_health_displayable_identity_ck check (not displayable or
    ((private.nar_health_race_kind_ok(source_kind)
      and match_method = 'race_key_name' and event_key is not null
      and track is not null and btrim(track) <> ''
      and race_date is not null and race_no is not null and runner_number is not null
      and stage <> 'auction_disclosure' and event_type <> 'auction_disclosure'
      and (source_kind <> 'nar_pdf' or reported_date = race_date))
     or (source_kind in ('rakuten', 'sat') and match_method = 'auction_item' and event_key is null
      and track is null and race_date is null and race_no is null and runner_number is null
      and stage = 'auction_disclosure' and event_type = 'auction_disclosure')));

alter table public.nar_health_imports
  drop constraint if exists nar_health_imports_source_kind_ck,
  drop constraint if exists nar_health_imports_source_ref_ck,
  drop constraint if exists nar_health_imports_source_url_ck;

alter table public.nar_health_imports
  add constraint nar_health_imports_source_kind_ck check (
    private.nar_health_race_kind_ok(source_kind) or source_kind in ('rakuten', 'sat')),
  add constraint nar_health_imports_source_ref_ck check (
    private.nar_health_race_ref_ok(source_kind, source_ref)
    or (source_kind = 'rakuten' and source_ref ~ '^rakuten/[0-9]+$')
    or (source_kind = 'sat' and source_ref ~ '^sat/[0-9]+$')),
  add constraint nar_health_imports_source_url_ck check (
    private.nar_health_import_url_ok(source_kind, source_url));

alter table public.nar_horse_health_event_evidence
  drop constraint if exists nar_health_evidence_source_kind_ck,
  drop constraint if exists nar_health_evidence_source_ref_ck,
  drop constraint if exists nar_health_evidence_source_url_ck;

alter table public.nar_horse_health_event_evidence
  add constraint nar_health_evidence_source_kind_ck check (
    private.nar_health_race_kind_ok(source_kind)),
  add constraint nar_health_evidence_source_ref_ck check (
    private.nar_health_race_ref_ok(source_kind, source_ref)),
  add constraint nar_health_evidence_source_url_ck check (
    private.nar_health_source_url_ok(source_kind, source_url));

-- RPC署名を変えず、適用済み§92A関数本体のsource allowlistだけを一度拡張する。
do $$
declare
  v_old text;
  v_new text;
  v_step text;
begin
  select pg_get_functiondef(to_regprocedure(
    'public.apply_nar_health_race_source(text,text,text,text,text,text,jsonb,integer,text,text,text,boolean)'
  )) into v_old;
  if v_old is null then
    raise exception 'apply_nar_health_race_source is missing';
  end if;
  v_new := v_old;
  if position('banei_official' in v_new) = 0 then
    v_step := replace(v_new,
      E'''funabashi_official'', ''ooi_official'', ''urawa_official'',\n                   ''kawasaki_official''',
      E'''funabashi_official'', ''ooi_official'', ''urawa_official'',\n                   ''kawasaki_official'', ''banei_official'', ''iwate_official'',\n                   ''kanazawa_official'', ''kasamatsu_official'', ''nagoya_official'',\n                   ''kochi_official'', ''saga_official''');
    if v_step = v_new then raise exception 'race RPC retry allowlist patch failed'; end if;
    v_new := v_step;

    v_step := replace(v_new,
      E'''nar_pdf'', ''funabashi_official'', ''ooi_official'',\n                    ''urawa_official'', ''kawasaki_official''',
      E'''nar_pdf'', ''funabashi_official'', ''ooi_official'',\n                    ''urawa_official'', ''kawasaki_official'', ''banei_official'',\n                    ''iwate_official'', ''kanazawa_official'', ''kasamatsu_official'',\n                    ''nagoya_official'', ''kochi_official'', ''saga_official''');
    if v_step = v_new then raise exception 'race RPC kind allowlist patch failed'; end if;
    v_new := v_step;

    v_step := replace(v_new,
      E'''kawasaki_official'' and v_ref ~ ''^kawasaki/[0-9]{8}$'')',
      E'''kawasaki_official'' and v_ref ~ ''^kawasaki/[0-9]{8}$'')\n    or (v_kind = ''banei_official'' and v_ref ~ ''^banei/[0-9]{8}$'')\n    or (v_kind = ''iwate_official'' and v_ref ~ ''^iwate/[0-9]{8}$'')\n    or (v_kind = ''kanazawa_official'' and v_ref ~ ''^kanazawa/[0-9]{8}$'')\n    or (v_kind = ''kasamatsu_official'' and v_ref ~ ''^kasamatsu/[0-9]{8}$'')\n    or (v_kind = ''nagoya_official'' and v_ref ~ ''^nagoya/[0-9]{8}$'')\n    or (v_kind = ''kochi_official'' and v_ref ~ ''^kochi/[0-9]{8}$'')\n    or (v_kind = ''saga_official'' and v_ref ~ ''^saga/[0-9]{8}$'')');
    if v_step = v_new then raise exception 'race RPC source_ref patch failed'; end if;
    v_new := v_step;

    v_step := replace(v_new,
      E'''kawasaki_official'' and\n            (x.track <> ''川崎'' or v_ref <> ''kawasaki/'' || to_char(x.race_date, ''YYYYMMDD'')))',
      E'''kawasaki_official'' and\n            (x.track <> ''川崎'' or v_ref <> ''kawasaki/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''banei_official'' and\n            (x.track <> ''帯広ば'' or v_ref <> ''banei/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''iwate_official'' and\n            (x.track not in (''盛岡'', ''水沢'') or v_ref <> ''iwate/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''kanazawa_official'' and\n            (x.track <> ''金沢'' or v_ref <> ''kanazawa/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''kasamatsu_official'' and\n            (x.track <> ''笠松'' or v_ref <> ''kasamatsu/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''nagoya_official'' and\n            (x.track <> ''名古屋'' or v_ref <> ''nagoya/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''kochi_official'' and\n            (x.track <> ''高知'' or v_ref <> ''kochi/'' || to_char(x.race_date, ''YYYYMMDD'')))\n        or (v_kind = ''saga_official'' and\n            (x.track <> ''佐賀'' or v_ref <> ''saga/'' || to_char(x.race_date, ''YYYYMMDD'')))');
    if v_step = v_new then raise exception 'race RPC track/ref patch failed'; end if;
    v_new := v_step;
    execute v_new;
  end if;
end $$;

commit;
-- END §92 ALL HORSE HEALTH ORGANIZERS

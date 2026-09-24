-- 監査 A10(2026-09-24) 健康の器が「もう望む形か」を読むだけで確かめる(DDL は 1 つも無い)。
-- 出力= 足りない項目の名前(1 行 1 件)。0 行= 望む形= 便は migrate の DDL(20260903/20260905/20260908/20260916)を飛ばす。
-- 1 行でもあれば従来どおり 4 本を流す(=表の形はこれまでと同じに収まる)。
-- ⛔上の 4 本の SQL を変えたら、ここにも印を足すこと(足さないと新しい形が当たらない)。
with c as (
  select conrelid::regclass::text as tbl, conname, pg_get_constraintdef(oid) as def
    from pg_constraint
   where conrelid in (select oid from pg_class where relnamespace = 'public'::regnamespace
                        and relname in ('nar_horse_health_events', 'nar_health_imports',
                                        'nar_horse_health_event_evidence', 'nar_penalty_sources'))
), want(tbl, conname, marker) as (values
  ('nar_horse_health_events', 'nar_horse_health_source_kind_ck', 'nar_health_race_kind_ok'),
  ('nar_horse_health_events', 'nar_horse_health_source_ref_ck', 'nar_health_race_ref_ok'),
  ('nar_horse_health_events', 'nar_horse_health_source_url_ck', 'nar_health_source_url_ok'),
  ('nar_horse_health_events', 'nar_horse_health_event_kind_ck', 'nar_health_race_kind_ok'),
  ('nar_horse_health_events', 'nar_horse_health_support_ck', 'nar_health_race_ref_ok'),
  ('nar_horse_health_events', 'nar_horse_health_displayable_identity_ck', 'auction_item'),
  ('nar_horse_health_events', 'nar_horse_health_condition_group_ck', 'castration'),
  ('nar_horse_health_events', 'nar_horse_health_condition_term_ck', 'condition_term'),
  ('nar_health_imports', 'nar_health_imports_source_kind_ck', 'nar_health_race_kind_ok'),
  ('nar_health_imports', 'nar_health_imports_source_ref_ck', 'nar_health_race_ref_ok'),
  ('nar_health_imports', 'nar_health_imports_source_url_ck', 'nar_health_import_url_ok'),
  ('nar_health_imports', 'nar_health_imports_failure_count_ck', 'failure_count'),
  ('nar_horse_health_event_evidence', 'nar_health_evidence_source_kind_ck', 'nar_health_race_kind_ok'),
  ('nar_horse_health_event_evidence', 'nar_health_evidence_source_ref_ck', 'nar_health_race_ref_ok'),
  ('nar_horse_health_event_evidence', 'nar_health_evidence_source_url_ck', 'nar_health_source_url_ok'),
  ('nar_penalty_sources', 'nar_penalty_sources_hash_ck', 'source_hash')
)
select 'constraint ' || w.conname
  from want w left join c on c.tbl = w.tbl and c.conname = w.conname
 where c.def is null or position(w.marker in c.def) = 0
union all
select 'column ' || x.t || '.' || x.col
  from (values ('nar_health_imports', 'failure_count'),
               ('nar_horse_health_events', 'racing_ability_lost'),
               ('nar_horse_health_events', 'condition_term')) x(t, col)
 where not exists (select 1 from information_schema.columns
                    where table_schema = 'public' and table_name = x.t and column_name = x.col)
union all
select 'index ' || i.n
  from (values ('nar_horse_health_name_birth_date_idx'), ('nar_horse_health_horse_code_idx'),
               ('nar_horse_health_race_runner_idx'), ('nar_horse_health_source_idx')) i(n)
 where to_regclass('public.' || i.n) is null
union all
select 'rls ' || x.t
  from (values ('nar_horse_health_events'), ('nar_health_imports'), ('nar_penalty_sources')) x(t)
 where not coalesce((select relrowsecurity from pg_class
                      where oid = to_regclass('public.' || x.t)), false)
union all
select 'policy nar_horse_health_events_read'
 where not exists (select 1 from pg_policies where schemaname = 'public'
                     and tablename = 'nar_horse_health_events' and policyname = 'nar_horse_health_events_read')
union all
select 'policy nar_health_imports_read(残っている)'
 where exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'nar_health_imports' and policyname = 'nar_health_imports_read')
union all
select 'function ' || f.sig
  from (values
    ('private.nar_health_race_kind_ok(text)', 'saga_official'),
    ('private.nar_health_race_ref_ok(text,text)', 'p_ref'),
    ('private.nar_health_source_url_ok(text,text)', 'p_url'),
    ('private.nar_health_import_url_ok(text,text)', 'nar_health_source_url_ok'),
    ('public.apply_nar_health_race_source(text,text,text,text,text,text,jsonb,integer,text,text,text,boolean)', 'banei_official'),
    ('private._apply_nar_health_auction_source_v2(text,text,text,text,text,text,jsonb,integer,text,text,text,boolean)', 'condition_term'),
    ('public.apply_nar_health_source(text,text,text,text,text,text,jsonb,integer,text,text,text,boolean)', '_apply_nar_health_auction_source_v2')
  ) f(sig, marker)
 where to_regprocedure(f.sig) is null
    or position(f.marker in pg_get_functiondef(to_regprocedure(f.sig))) = 0
union all
select 'grant ' || g.who || ' ' || g.priv || ' ' || g.t
  from (values
    ('anon', 'select', 'public.nar_horse_health_events', true),
    ('anon', 'insert', 'public.nar_horse_health_events', false),
    ('anon', 'select', 'public.nar_health_imports', false),
    ('anon', 'select', 'public.nar_penalty_sources', false),
    ('service_role', 'insert', 'public.nar_horse_health_events', true),
    ('service_role', 'update', 'public.nar_health_imports', true),
    ('service_role', 'insert', 'public.nar_penalty_sources', true)
  ) g(who, priv, t, expect)
 where to_regclass(g.t) is null or has_table_privilege(g.who, g.t, g.priv) <> g.expect;

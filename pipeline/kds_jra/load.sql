-- 案 F 一回便: KDSCOPE の中央戦績を nar_jra_horses / nar_jra_runs に足す(kb_horse_id='kd'+血統登録番号)。
-- 変数 do_h / do_r(このファイルを読むか)・apply(true で commit・false で巻き戻す)。読む CSV は /tmp/h.csv /tmp/r.csv。
\set ON_ERROR_STOP 1
select pg_database_size(current_database())/1048576 as db_mb_before,
       (select count(*) from nar_jra_horses where kb_horse_id like 'kd%') as kd_horses_before,
       (select count(*) from nar_jra_runs where kb_horse_id like 'kd%') as kd_runs_before;
do $$ begin
  if pg_database_size(current_database()) > 5200::bigint*1048576 then raise exception 'DB が 5200MB を超えた= 止める'; end if;
end $$;
begin;
\if :do_h
create temp table th (like nar_jra_horses including defaults) on commit drop;
\copy th(kb_horse_id,horse_name,birth_year,birth_date,fetched_at,last_jra_date,jra_runs,fetch_error,updated_at,jra_career_runs) from '/tmp/h.csv' csv header
with ins as (insert into nar_jra_horses (kb_horse_id,horse_name,birth_year,birth_date,fetched_at,last_jra_date,jra_runs,fetch_error,updated_at,jra_career_runs) select kb_horse_id,horse_name,birth_year,birth_date,fetched_at,last_jra_date,jra_runs,fetch_error,updated_at,jra_career_runs from th on conflict do nothing returning 1)
select (select count(*) from th) as horses_in_csv, count(*) as horses_inserted from ins;
\endif
\if :do_r
create temp table tr (like nar_jra_runs including defaults) on commit drop;
\copy tr(kb_horse_id,race_date,place,race_no,kai,nichi,kb_race_id,race_name,race_cond,surface,course,direction,distance,weather,going,field_size,gate,finish,finish_note,time_raw,time_sec,margin,last3f,last4f,first3f,race_last3f,passing,pace,popularity,win_odds,carried_weight,jockey,body_weight,updated_at) from '/tmp/r.csv' csv header
with ins as (insert into nar_jra_runs (kb_horse_id,race_date,place,race_no,kai,nichi,kb_race_id,race_name,race_cond,surface,course,direction,distance,weather,going,field_size,gate,finish,finish_note,time_raw,time_sec,margin,last3f,last4f,first3f,race_last3f,passing,pace,popularity,win_odds,carried_weight,jockey,body_weight,updated_at) select kb_horse_id,race_date,place,race_no,kai,nichi,kb_race_id,race_name,race_cond,surface,course,direction,distance,weather,going,field_size,gate,finish,finish_note,time_raw,time_sec,margin,last3f,last4f,first3f,race_last3f,passing,pace,popularity,win_odds,carried_weight,jockey,body_weight,updated_at from tr on conflict do nothing returning 1)
select (select count(*) from tr) as runs_in_csv, count(*) as runs_inserted from ins;
\endif
\if :apply
commit;
\else
rollback;
\endif
select pg_database_size(current_database())/1048576 as db_mb_after,
       (select count(*) from nar_jra_horses where kb_horse_id like 'kd%') as kd_horses_after,
       (select count(*) from nar_jra_runs where kb_horse_id like 'kd%') as kd_runs_after;

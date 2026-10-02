-- 馬主・生産者・調教師ページ(2026-10-02)の集計。取り決めは nar-site/research/owner-breeder/impl_spec.md。
-- ⛔Actions の中の手元 Postgres でだけ流す(stats_local.py ob)。本番へは diff/apply が差分だけ戻す。
-- 前提= stats_local.py ob が public.nar_name_alias(名寄せ)と public.trainer_same_abbr(除く 55 略称)を入れ済み・
--        run(graded.sql)が public.nar_graded を作り済み。
-- 入力= nar_runs・nar_horse_profiles(owner/breeder の正本・(馬名, 生年月日) で一意)・nar_graded。
-- 数える走= 結果のある走(finish あり、または取消・除外以外の finish_note あり)。未来の出馬表・取消・除外は数えない。
-- 走と名簿の当て方= 走に生年月日があれば (馬名, 生年月日)、無ければ 名簿でその馬名が 1 頭だけのときだけ馬名で当てる。
-- w1/w2/w3= 1 着・2 着・3 着の回数(3 着内= w1+w2+w3)。率は画面で割る。
set statement_timeout = '30min';

create table if not exists public.nar_person_year (
  kind text not null, name text not null, year integer not null, track text not null,
  n integer not null, w1 integer not null, w2 integer not null, w3 integer not null,
  updated_at timestamptz not null default now(), primary key (kind, name, year, track));
create table if not exists public.nar_ob_year (
  kind text not null, name text not null, year integer not null, track text not null, horses integer not null,
  n integer not null, w1 integer not null, w2 integer not null, w3 integer not null,
  updated_at timestamptz not null default now(), primary key (kind, name, year, track));
create table if not exists public.nar_ob_horses (
  kind text not null, name text not null, horse_name text not null, birth_date date not null, sex text, sire text,
  first_date date, last_date date, n integer not null, w1 integer not null, w2 integer not null, w3 integer not null,
  last_track text, updated_at timestamptz not null default now(), primary key (kind, name, horse_name, birth_date));
create table if not exists public.nar_ob_graded (
  kind text not null, name text not null, race_date date not null, track text not null, race_no integer not null,
  horse_name text not null, race_name text, finish integer not null,
  updated_at timestamptz not null default now(), primary key (kind, name, race_date, track, race_no, horse_name));

-- ---------------------------------------------------------------- 数える走
drop table if exists tmp_obrun;
create temp table tmp_obrun as
select u.track, u.race_date, u.race_no, u.horse_name, u.birth_date, u.trainer, u.finish,
       extract(year from u.race_date)::int as yr
from public.nar_runs u
where u.finish is not null
   or (u.finish_note is not null and u.finish_note <> '' and u.finish_note !~ '取消|除外');
analyze tmp_obrun;

-- ---------------------------------------------------------------- 調教師の年×場
truncate public.nar_person_year;
insert into public.nar_person_year (kind, name, year, track, n, w1, w2, w3)
select 'trainer', r.trainer, r.yr, r.track, count(*),
       count(*) filter (where r.finish = 1), count(*) filter (where r.finish = 2), count(*) filter (where r.finish = 3)
from tmp_obrun r
where r.trainer is not null and r.trainer <> ''
  and not (r.yr between 2014 and 2021
           and regexp_replace(r.trainer, '\s', '', 'g') in (select regexp_replace(abbr, '\s', '', 'g') from public.trainer_same_abbr))
group by r.trainer, r.yr, r.track;

-- ---------------------------------------------------------------- 名簿に代表表記を付ける(馬主・生産者を縦に)
drop table if exists tmp_obprof;
create temp table tmp_obprof as
select 'owner'::text as kind, coalesce(a.canonical, normalize(btrim(p.owner), NFKC)) as name,
       p.horse_name, p.birth_date, p.sex, p.sire
from public.nar_horse_profiles p left join public.nar_name_alias a on a.kind = 'owner' and a.alias = p.owner
where p.owner is not null and btrim(p.owner) <> ''
union all
select 'breeder', coalesce(a.canonical, normalize(btrim(p.breeder), NFKC)),
       p.horse_name, p.birth_date, p.sex, p.sire
from public.nar_horse_profiles p left join public.nar_name_alias a on a.kind = 'breeder' and a.alias = p.breeder
where p.breeder is not null and btrim(p.breeder) <> '';
create index on tmp_obprof (horse_name, birth_date);

-- 走 → 名簿の馬(horse_name, birth_date)
drop table if exists tmp_obuniq;
create temp table tmp_obuniq as
select horse_name, min(birth_date) as birth_date from public.nar_horse_profiles group by horse_name having count(*) = 1;
drop table if exists tmp_obrh;
create temp table tmp_obrh as
select r.track, r.race_date, r.race_no, r.horse_name, r.birth_date as pbd, r.finish, r.yr
from tmp_obrun r
where r.birth_date is not null
  and exists (select 1 from public.nar_horse_profiles p where p.horse_name = r.horse_name and p.birth_date = r.birth_date)
union all
select r.track, r.race_date, r.race_no, r.horse_name, q.birth_date, r.finish, r.yr
from tmp_obrun r join tmp_obuniq q on q.horse_name = r.horse_name
where r.birth_date is null;
create index on tmp_obrh (horse_name, pbd);
analyze tmp_obrh;

-- ---------------------------------------------------------------- 年×場
truncate public.nar_ob_year;
insert into public.nar_ob_year (kind, name, year, track, horses, n, w1, w2, w3)
select p.kind, p.name, r.yr, r.track, count(distinct (r.horse_name, r.pbd)), count(*),
       count(*) filter (where r.finish = 1), count(*) filter (where r.finish = 2), count(*) filter (where r.finish = 3)
from tmp_obrh r join tmp_obprof p on p.horse_name = r.horse_name and p.birth_date = r.pbd
group by p.kind, p.name, r.yr, r.track;

-- ---------------------------------------------------------------- 馬(名簿の全馬・走っていない馬は n=0)
drop table if exists tmp_obh;
create temp table tmp_obh as
select horse_name, pbd, min(race_date) as first_date, max(race_date) as last_date, count(*) as n,
       count(*) filter (where finish = 1) as w1, count(*) filter (where finish = 2) as w2, count(*) filter (where finish = 3) as w3,
       (array_agg(track order by race_date desc, race_no desc))[1] as last_track
from tmp_obrh group by horse_name, pbd;
truncate public.nar_ob_horses;
insert into public.nar_ob_horses (kind, name, horse_name, birth_date, sex, sire, first_date, last_date, n, w1, w2, w3, last_track)
select p.kind, p.name, p.horse_name, p.birth_date, p.sex, p.sire, h.first_date, h.last_date,
       coalesce(h.n, 0), coalesce(h.w1, 0), coalesce(h.w2, 0), coalesce(h.w3, 0), h.last_track
from tmp_obprof p left join tmp_obh h on h.horse_name = p.horse_name and h.pbd = p.birth_date;

-- ---------------------------------------------------------------- 重賞・準重賞の 1〜3 着(2022-11 から)
truncate public.nar_ob_graded;
insert into public.nar_ob_graded (kind, name, race_date, track, race_no, horse_name, race_name, finish)
select p.kind, p.name, r.race_date, r.track, r.race_no, r.horse_name, g.race_name, r.finish
from tmp_obrh r
join public.nar_graded g on g.track = r.track and g.race_date = r.race_date and g.race_no = r.race_no
join tmp_obprof p on p.horse_name = r.horse_name and p.birth_date = r.pbd
where r.finish between 1 and 3 and r.race_date >= date '2022-11-01'
on conflict do nothing;

analyze public.nar_person_year; analyze public.nar_ob_year; analyze public.nar_ob_horses; analyze public.nar_ob_graded;

select t, kind, rows from (
  select 'nar_name_alias' t, kind, count(*) rows from public.nar_name_alias group by kind
  union all select 'nar_person_year', kind, count(*) from public.nar_person_year group by kind
  union all select 'nar_ob_year', kind, count(*) from public.nar_ob_year group by kind
  union all select 'nar_ob_horses', kind, count(*) from public.nar_ob_horses group by kind
  union all select 'nar_ob_graded', kind, count(*) from public.nar_ob_graded group by kind) s order by 1, 2;

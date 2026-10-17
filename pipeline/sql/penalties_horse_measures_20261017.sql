-- 2026-10-17 制裁の表に「馬への措置」を入れる器(ユーザー承認 A〜D)。⛔冪等= 何度流しても同じ形。
--   A. person_kind に 'horse'・kind に '出走停止' '再検査'。馬の行は person_name = horse_name = 馬名。
--      理由(原文の語・タイムオーバー/鼻出血/発走調教不十分 など)は cause(原文に無ければ null)。
--   B. 賞典停止は kind を変えず(戒告など)prize_suspended = true。期間は今までどおり suspension_from/through。
--   C. 飛び日付「10月19日、21日、22日、23日」は suspension_days(書いてある日だけ・from/through は最初と最後)。
-- 書き手= cloud/penalties.py(penalties-1.3)。⛔9/5 の §111 の「馬の話はここに入れない」はこの日で改める。
-- ⛔制約の作り直しは**今の定義に足りないときだけ**(毎回 drop/add すると表を排他ロックして全件検証するため)。
-- 旧版(penalties-1.2 以前)の行の消し方は nar-jobs docs/penalties_horse_measures_20261017.md(⛔ここでは消さない)。
-- 写し= nar-jobs pipeline/sql/penalties_horse_measures_20261017.sql(horse-health.yml が流す)。2 つは同じ中身。

begin;

alter table public.nar_penalties add column if not exists cause text;
alter table public.nar_penalties add column if not exists prize_suspended boolean not null default false;
alter table public.nar_penalties add column if not exists suspension_days date[];

do $$
declare
  t regclass := 'public.nar_penalties'::regclass;
begin
  if not exists (select 1 from pg_constraint where conrelid = t and conname = 'nar_penalties_person_kind_ck'
                   and pg_get_constraintdef(oid) like '%horse%') then
    alter table public.nar_penalties drop constraint if exists nar_penalties_person_kind_ck;
    alter table public.nar_penalties add constraint nar_penalties_person_kind_ck
      check (person_kind in ('jockey', 'trainer', 'other', 'horse'));
  end if;

  if not exists (select 1 from pg_constraint where conrelid = t and conname = 'nar_penalties_kind_ck'
                   and pg_get_constraintdef(oid) like '%出走停止%'
                   and pg_get_constraintdef(oid) like '%再検査%') then
    alter table public.nar_penalties drop constraint if exists nar_penalties_kind_ck;
    alter table public.nar_penalties add constraint nar_penalties_kind_ck
      check (kind in ('戒告', '過怠金', '騎乗停止', '注意', 'その他', '出走停止', '再検査'));
  end if;

  -- 馬の行は馬名が要る(名簿に当たった馬だけ入れる)
  if not exists (select 1 from pg_constraint where conrelid = t and conname = 'nar_penalties_horse_row_ck') then
    alter table public.nar_penalties add constraint nar_penalties_horse_row_ck
      check (person_kind <> 'horse' or (horse_name is not null and person_name = horse_name));
  end if;

  if not exists (select 1 from pg_constraint where conrelid = t and conname = 'nar_penalties_cause_ck') then
    alter table public.nar_penalties add constraint nar_penalties_cause_ck
      check (cause is null or char_length(btrim(cause)) between 1 and 40);
  end if;

  if not exists (select 1 from pg_constraint where conrelid = t and conname = 'nar_penalties_days_ck') then
    alter table public.nar_penalties add constraint nar_penalties_days_ck
      check (suspension_days is null or cardinality(suspension_days) between 2 and 31);
  end if;
end $$;

commit;

-- 監査 #21 同名の別馬が混ざる — 案 乙・DB 案 X の DDL と移し(2026-09-23・ユーザーが流す)
-- 設計= viewer docs/design_s21_horse_identity_20260923.md §4-2・§4-3 / 乙の決定= docs/opus_s21_otsu_20260923.md
-- 順: ① DDL → ② nar_meta の初期値 → ③ 既存行の移し → ④ 番号 → ⑤ 確かめ。
-- 同名表の中身は ② のあと Actions 便 horse-homonyms(confirm=apply)で作る(nar_runs 全表走査= ここでは流さない)。
-- 取り込み(nar-jobs 枝 s21-horse-profiles)は表が無くても落ちない= ① より先に merge してよい。
-- ⛔nar_horses の形は変えない(AI 便の \copy が列を名指し)。

-- ① 表 --------------------------------------------------------------------------------------------
create table if not exists public.nar_horse_profiles (
  horse_name text not null,
  birth_date date not null,
  code text,
  sex text, sire text, dam text, broodmare_sire text, owner text, breeder text,
  first_seen date, last_seen date,
  updated_at timestamptz not null default now(),
  primary key (horse_name, birth_date)
);
create index if not exists nar_horse_profiles_code on public.nar_horse_profiles (code) where code is not null;
alter table public.nar_horse_profiles enable row level security;
drop policy if exists nar_horse_profiles_read on public.nar_horse_profiles;
create policy nar_horse_profiles_read on public.nar_horse_profiles for select to anon, authenticated using (true);
grant select on public.nar_horse_profiles to anon, authenticated;

-- ② nar_meta の初期値(同名表は Actions 便が上書き・束ね表は手で持つ)。形:
--    horse_homonyms      = ["<馬名>", ...]
--    horse_homonym_merge = {"<馬名>": [[2019, 2020], ...]}   内側 1 つ= 同じ馬として束ねる生年
insert into public.nar_meta (key, value, updated_at) values ('horse_homonyms', '[]'::jsonb, now())
  on conflict (key) do nothing;
insert into public.nar_meta (key, value, updated_at) values ('horse_homonym_merge', '{}'::jsonb, now())
  on conflict (key) do nothing;

-- ③ 既存 nar_horses(約 33,154 行)の移し。今の 1 行= 最新走の馬の属性(取り込みが最新走で上書きしてきた)
--    = 最新走(2022-11 以降・生年月日あり)の生年月日を付ける。走の無い馬・旧期だけの馬は入らない。
--    重ければ `and h.horse_name < 'カ'` / `>= 'カ' and < 'タ'` / `>= 'タ' and < 'ハ'` / `>= 'ハ'` の 4 回に割る。
set statement_timeout = 0;
insert into public.nar_horse_profiles
  (horse_name, birth_date, sex, sire, dam, broodmare_sire, owner, breeder, first_seen, last_seen, updated_at)
select h.horse_name, l.birth_date, h.sex, h.sire, h.dam, h.broodmare_sire, h.owner, h.breeder,
       h.first_date, h.last_date, h.updated_at
from public.nar_horses h
join lateral (
  select r.birth_date from public.nar_runs r
  where r.horse_name = h.horse_name and r.race_date >= date '2022-11-01' and r.birth_date is not null
  order by r.race_date desc, r.race_no desc limit 1) l on true
on conflict (horse_name, birth_date) do nothing;
-- 同名の「古い方の馬」(同じ馬名で生年月日が別)の行は ③ では作られない(属性は上書きで消えている)。
-- 取り直しは Actions で `python cloud/refresh.py --months 2022-11,2022-12,... --only profiles`(公式の月次 ZIP)。

-- ④ 番号(同じ (馬名, 生年月日) に番号 2 つ以上は埋めない)。以後は毎朝 horse_ledger ③ が埋める。
update public.nar_horse_profiles p
set code = c.code
from (
  select horse_name, birth_date, min(code) as code
  from public.nar_horse_codes
  where birth_date is not null
  group by horse_name, birth_date
  having count(distinct code) = 1
) c
where c.horse_name = p.horse_name and c.birth_date = p.birth_date and p.code is null;

-- ⑤ 確かめ(読むだけ)
select count(*) as profiles, count(code) as with_code from public.nar_horse_profiles;
select count(*) as names_with_2_births
from (select horse_name from public.nar_horse_profiles group by horse_name having count(*) >= 2) s;
-- 最新走の sex と profiles の sex が食い違う行(0 が期待)
select count(*) as sex_mismatch
from public.nar_horse_profiles p
join lateral (
  select r.sex from public.nar_runs r
  where r.horse_name = p.horse_name and r.birth_date = p.birth_date
  order by r.race_date desc, r.race_no desc limit 1) l on true
where p.sex is distinct from l.sex;

-- 戻し(必要なときだけ・コメントを外して流す)
-- drop table public.nar_horse_profiles;
-- delete from public.nar_meta where key in ('horse_homonyms', 'horse_homonym_merge');

-- 騎手・調教師のプロフィール(DESIGN §65 / §54.2)。公式 DataRoom の RiderMark / TrainerMark 由来。
-- 中身を入れるのは cloud/persons.py。ここは**器だけ**(何度流しても同じ)。
--
-- ⛔name_short = 出典(nar_runs.jockey / trainer)と同じ略し方= **姓[:2] + 名[:3-len(姓[:2])]**(必ず3文字)。
--   実測(2026-08-30): 佐々木大輔→佐々大 / 山本聡哉→山本聡 / 西謙一→西謙一 / 長谷川剛史→長谷剛。
--   現役の騎手 301/350・調教師 449/562 が nar_person_stats.name と一致(残りは出走10未満で行が無いだけ)。
-- ⛔name_short は**一意ではない**(#X1)。同じ略称に2人いる組が実測7件あり、その人たちは
--   nar_runs の側で既に1人に混ざっている。⛔画面はその略称に**生年月日を出してはいけない**
--   (2人の生年月日が違えば嘘になる。ユーザー裁定 2026-08-30=「今は出さないだけにする」)。

create table if not exists public.nar_persons (
  kind        text        not null,          -- 'jockey' | 'trainer'
  license_no  text        not null,          -- 公式の k_riderLicenseNo / k_trainerLicenseNo
  name_full   text        not null,          -- 氏名(空白を詰めたもの。例 山本聡哉)
  name_sei    text,                          -- 姓(例 山本)
  name_mei    text,                          -- 名(例 聡哉)
  name_short  text,                          -- 上の規則で作った3文字(例 山本聡)= nar_runs と突合する鍵
  birth       date,                          -- 生年月日(取れなければ null)
  area        text,                          -- 所属(ばんえい・岩手 など。公式の字のまま)
  active      boolean     not null default true,
  updated_at  timestamptz not null default now(),
  primary key (kind, license_no)
);

-- 突合は (kind, name_short) で引く。⛔一意ではないので**必ず件数を数えてから使う**
create index if not exists nar_persons_short_idx on public.nar_persons (kind, name_short);
-- 「今日が誕生日」は月日で引く(年は見ない)
create index if not exists nar_persons_birth_idx on public.nar_persons (kind, birth) where birth is not null;

alter table public.nar_persons enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies
                 where schemaname = 'public' and tablename = 'nar_persons' and policyname = 'nar_persons_read') then
    create policy nar_persons_read on public.nar_persons for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_persons to anon, authenticated;

select kind, count(*) as rows, count(birth) as with_birth,
       count(*) filter (where active) as active
from public.nar_persons group by kind order by kind;

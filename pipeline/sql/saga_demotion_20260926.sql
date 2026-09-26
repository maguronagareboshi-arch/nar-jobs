-- §288(2026-09-26) 佐賀の「降級の目安」(翌1月の減額の見込み)。書き手= cloud/saga_demotion.py(便 nar-refresh.yml の朝の class calc の後)。
-- 式= 要領 第4-1(3)③(ロ)(ハ)(ニ): 6歳になった時点で2歳時・7歳で3歳時・8歳で4歳時の収得賞金(換算後)を全額減額。
--   value= その日の番組賞金(cloud/class_calc.py saga_state と同じ計算)、cut= 翌1月に引かれる額、after= value − cut。
--   行= 翌1月に減額がある在籍馬の全部(級が下がらない馬も入る。下がるか= cls_after と cls_now を比べる)。
-- 計算した日(calc_date)ごとに行を残す= 過去のレースの画面は「レースの日より前の最新の calc_date」を出す。
-- 同じ日に流し直したら上書き(冪等)。額の単位= 円(千円未満切捨)。
-- ⛔本番 DB の変更= ユーザーの了承と「手動」への切替の後に本体が 1 回だけ流す。冪等(何度流しても同じ)。
create table if not exists public.nar_saga_demotion (
  code        text not null,             -- 馬コード(nar_horse_prize.code)
  horse_name  text not null,
  calc_date   date not null,             -- 計算した日(JST)
  cls_now     text not null,             -- 今の級(最後に走った佐賀の級。無ければ計算の級)'Ａ１'〜'Ｃ２'
  cls_calc    text not null,             -- 番組賞金(value)から見た級
  value       integer not null,          -- 番組賞金(円)
  cut         integer not null,          -- 翌1月の減額(円)
  after       integer not null,          -- 減額後(円)
  cls_after   text not null,             -- 減額後の級
  need        integer,                   -- 今の級に残るのに要る額(円)= 今の級の下限 − after。0 以下= 下がらない。Ｃ２は null
  cut_age     integer not null,          -- 減額される年齢の時の賞金(2・3・4)
  age_next    integer not null,          -- 翌1月の馬齢(6・7・8)
  target      date not null,             -- 減額の日(翌年 1/1)
  asof        timestamptz not null default now(),
  primary key (code, calc_date)
);
create index if not exists nar_saga_demotion_name on public.nar_saga_demotion (horse_name, calc_date desc);
alter table public.nar_saga_demotion enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'nar_saga_demotion' and policyname = 'nar_saga_demotion_read') then
    create policy nar_saga_demotion_read on public.nar_saga_demotion for select to anon, authenticated using (true);
  end if;
end $$;
revoke all on public.nar_saga_demotion from anon, authenticated;
grant select on public.nar_saga_demotion to anon, authenticated;

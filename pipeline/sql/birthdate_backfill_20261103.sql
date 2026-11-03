-- 11/3 監査 #39: 2022-11 前の nar_runs は生年月日が全部空= 境をまたぐ馬が 2022-11 の前後で別の馬に分かれる。
-- 補い方= 同じ馬名で 2022-11 以降に生年月日のある行があり、その生年(年)が「レースの年 − 馬齢」と同じ生年月日が
--   ちょうど 1 つのときだけ埋める(2 つ以上= 同名同年の別馬の恐れ= 埋めない)。境をまたがない馬は元から分かれないので触らない。
-- 11/3 の数(読み取りだけで数えた): 高知 1,006 頭 15,841 行・ほか 10,691 頭 242,021 行・埋めない(同名同年 2 つ)1 頭 121 行。
-- ⛔updated_at は動かさない(取り込み時刻の意味を壊さない・push_notify は昨日以降しか見ない)。
-- ⛔名前|生年月日 を馬の鍵にする読み手(予想 AI の horse_key・格の計算など)で、2022-11 前の走がつながる= 材料が変わる。
-- ⛔本番 DB の変更= 「手動」モードで流す(nar-viewer から): py -3.12 -X utf8 pipeline\dbadmin.py file ..\nar-jobs\pipeline\sql\birthdate_backfill_20261103.sql
-- 年ごとに分けて書く(1 回の行数と WAL を小さく)。何度流しても同じ(空の行だけ埋める)。
set statement_timeout = '10min';

create temp table t_bd as
select horse_name, extract(year from birth_date)::int as y, min(birth_date) as bd
  from public.nar_runs
 where race_date >= '2022-11-01' and birth_date is not null
 group by 1, 2
having count(distinct birth_date) = 1;
create index on t_bd (horse_name, y);
analyze t_bd;

do $$
declare yr int; n bigint; total bigint := 0;
begin
  for yr in select distinct extract(year from race_date)::int from public.nar_runs
             where race_date < '2022-11-01' and birth_date is null order by 1 loop
    update public.nar_runs u
       set birth_date = t.bd
      from t_bd t
     where u.race_date >= make_date(yr, 1, 1) and u.race_date < least(make_date(yr + 1, 1, 1), date '2022-11-01')
       and u.birth_date is null and u.age is not null
       and t.horse_name = u.horse_name and t.y = yr - u.age;
    get diagnostics n = row_count;
    total := total + n;
    raise notice '% 年: % 行', yr, n;
  end loop;
  raise notice '計 % 行', total;
end $$;

-- 確かめ(流した後): 埋まった行の数= 約 257,862
-- select count(*) from public.nar_runs where race_date < '2022-11-01' and birth_date is not null;

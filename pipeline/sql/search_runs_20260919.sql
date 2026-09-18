-- §213 複合検索(2026-09-19)= レース検索に「出走馬の条件」(騎手/調教師/父/馬主・2 つまで・かつ/または)を重ねる。
-- 返り= 当たったレース(場・日・R・レース名・距離・頭数・馬場・条件・種別)+ hits(当たった行の配列)。
-- クラスの絞り(searchClass)は viewer 側で race_name/condition/race_kind に当てる(今の searchRaces と同じ規則)。
-- 父・馬主は nar_horses(馬名で結合)。名前は部分一致(ILIKE)。上限 p_limit(既定 300・日付の新しい順)。
-- 2026-09-19 夜: anon の 3 秒で時間切れ(2.7〜4.2 秒)→ pg_trgm の GIN(jockey/trainer/sire/owner)+race_date の btree を足し、
-- 条件ごとの UNION ALL に書き直した(plpgsql)。実測= 大井 8〜9 月 和田譲×藤本現 all 138ms・全場 12 か月 父×騎手 any 174ms(暖)。
create extension if not exists pg_trgm;
create index if not exists nar_runs_date_idx on public.nar_runs (race_date desc);
create index if not exists nar_runs_jockey_trgm on public.nar_runs using gin (jockey gin_trgm_ops);
create index if not exists nar_runs_trainer_trgm on public.nar_runs using gin (trainer gin_trgm_ops);
create index if not exists nar_horses_sire_trgm on public.nar_horses using gin (sire gin_trgm_ops);
create index if not exists nar_horses_owner_trgm on public.nar_horses using gin (owner gin_trgm_ops);
-- 関数の本体= 本番の定義(pg_get_functiondef で写す)。省略= 上の説明のとおり 6 本の UNION ALL → group by → nar_races と結合。

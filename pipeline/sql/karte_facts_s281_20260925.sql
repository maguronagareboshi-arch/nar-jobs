-- §281 分析タブ作り直し: nar_karte_facts に「今日と同じ場・同じ距離帯」と「今回の変化」の 8 列を足す(2026-09-25)。
-- 書き手は cloud/karte_facts.py(数え方は pipeline/karte.py の same_course / dist_change / class_move /
-- jockey_change / trainer_move)。
--
--   same_cd_top3  = 今日と同じ場・同じ距離帯(〜1200/1201〜1600/1601〜)の 3 着内の回数(その日より前の 365 日・実走)
--   same_cd_n     = その走数(⛔今日の距離が無ければ NULL・走が無ければ 0)
--   dist_prev_m   = 前走の距離(m)/ dist_now_m = 今回の距離(m)
--   class_move    = 同じ場の前の走のクラス(A1〜C3・レース名から)とくらべて '上' / '同じ' / '下'。読めなければ NULL
--   jockey_switch = 前走と騎手が違う / jockey_rides = 乗り替わりのとき、今回の騎手が以前この馬に乗った回数(全期間)
--   trainer_move  = 前走と調教師が違う: '転厩'(前走が南関)/ '転入'(前走が南関の外)。同じ・材料なしは NULL
--   ⛔「前にいたとき」は既存の lead_hold_rate / lead_hold_n(最初のコーナー 3 番手以内・365 日の 3 着内)を使う。既存の列は変えない。
--
-- 適用: psql … -v ON_ERROR_STOP=1 -X -f pipeline/sql/karte_facts_s281_20260925.sql(⛔鍵を持つ担当が流す)
-- ⛔cloud/karte_facts.py --apply(nar-refresh の karte facts 段)が新しい列を書くので、この SQL を先に流すこと。
\set ON_ERROR_STOP on

alter table public.nar_karte_facts add column if not exists same_cd_top3  int;
alter table public.nar_karte_facts add column if not exists same_cd_n     int;
alter table public.nar_karte_facts add column if not exists dist_prev_m   int;
alter table public.nar_karte_facts add column if not exists dist_now_m    int;
alter table public.nar_karte_facts add column if not exists class_move    text;
alter table public.nar_karte_facts add column if not exists jockey_switch boolean;
alter table public.nar_karte_facts add column if not exists jockey_rides  int;
alter table public.nar_karte_facts add column if not exists trainer_move  text;

comment on column public.nar_karte_facts.same_cd_top3  is '§281 今日と同じ場・同じ距離帯の 3 着内(365 日)';
comment on column public.nar_karte_facts.same_cd_n     is '§281 今日と同じ場・同じ距離帯の走数(365 日)';
comment on column public.nar_karte_facts.dist_prev_m   is '§281 前走の距離(m)';
comment on column public.nar_karte_facts.dist_now_m    is '§281 今回の距離(m)';
comment on column public.nar_karte_facts.class_move    is '§281 同じ場の前の走とくらべたクラス 上/同じ/下';
comment on column public.nar_karte_facts.jockey_switch is '§281 前走と騎手が違う';
comment on column public.nar_karte_facts.jockey_rides  is '§281 乗り替わりのとき今回の騎手が以前この馬に乗った回数';
comment on column public.nar_karte_facts.trainer_move  is '§281 転厩/転入して初戦';

notify pgrst, 'reload schema';

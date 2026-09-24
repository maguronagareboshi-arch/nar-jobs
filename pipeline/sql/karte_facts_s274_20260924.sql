-- §274 分析タブの事実 nar_karte_facts に「出遅れの通算」と「出走ペース」の 4 列を足す(2026-09-24)。
-- 書き手は cloud/karte_facts.py(数え方は pipeline/karte.py の late_all / gaps_recent / gap_usual)。
--
--   late_all_n     = 通算の出遅れ回数= その日より前の実走のうち記録(nar_kb_runs の行)のある走で start_note に「出遅」の回数
--   late_all_den   = 通算の記録のある走数(⛔late_n/late_den と同じ判定・5 走で切らない)
--   gap_usual_days = ふだんの間隔(日)= gaps_recent の中央値(偶数個は真ん中 2 つの平均を切り捨て)。間隔が 2 つ未満は NULL
--   gaps_recent    = 近ごろの間隔(日)= 直近 5 走それぞれの「その前の走からの日数」(新しい順・最大 5)。無ければ NULL
--   ⛔走の並びは gap_days / since_layoff と同じ(能力検査・取消・除外は数えない)。既存の列は変えない。
--
-- 適用: psql … -v ON_ERROR_STOP=1 -X -f pipeline/sql/karte_facts_s274_20260924.sql(⛔鍵を持つ担当が流す)
-- ⛔cloud/karte_facts.py --apply(nar-refresh の karte facts 段)が新しい列を書くので、この SQL を先に流すこと。
\set ON_ERROR_STOP on

alter table public.nar_karte_facts add column if not exists late_all_n     int;
alter table public.nar_karte_facts add column if not exists late_all_den   int;
alter table public.nar_karte_facts add column if not exists gap_usual_days int;
alter table public.nar_karte_facts add column if not exists gaps_recent    int[];

comment on column public.nar_karte_facts.late_all_n     is '§274 通算の出遅れ回数(記録のある走のうち)';
comment on column public.nar_karte_facts.late_all_den   is '§274 通算の出遅れ記録のある走数';
comment on column public.nar_karte_facts.gap_usual_days is '§274 ふだんの間隔(日)= 直近 5 走の間隔の中央値・2 つ未満は NULL';
comment on column public.nar_karte_facts.gaps_recent    is '§274 近ごろの間隔(日・新しい順・最大 5)';

notify pgrst, 'reload schema';

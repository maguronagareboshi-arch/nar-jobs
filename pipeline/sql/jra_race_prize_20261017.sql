-- 中央のレースの本賞金(1〜5着・付加賞抜き・円)。出どころ= 競馬ブック スマホ版の成績頁 table.syokin(ログイン不要)。
-- 佐賀の番組賞金(cloud/class_calc.py jra_honsho_merge)で、台帳(keiba.go.jp)の付加賞込みの収得賞金を差し替える。
-- 書き手= cloud/kb/jra_race_prize.py(毎朝の nar-refresh・埋め直しは jra-race-prize.yml)。2026-10-17
create table if not exists public.nar_jra_race_prize (
  kb_race_id  text primary key,             -- nar_jra_runs.kb_race_id
  honsho      integer[],                    -- [1着, 2着, 3着, 4着, 5着](円)。頁に賞金の表が無い= null
  fetched_at  timestamptz not null default now()
);
alter table public.nar_jra_race_prize enable row level security;  -- 読み書きは service key だけ

-- 2026-10-28 nar_wind_obs に気象庁 10 分値の列を足す(wind_backfill.py・wind_store.py が常に送る= 便より先に流す)
-- gust_dir は dir と同じ 1..16(北北東=1 … 北=16)。pressure は現地気圧(海面気圧では代えない)。sunshine は 10 分間の日照(分)。
alter table public.nar_wind_obs add column if not exists gust_speed numeric;   -- 最大瞬間風速 m/s
alter table public.nar_wind_obs add column if not exists gust_dir   smallint;  -- 最大瞬間の風向 1..16
alter table public.nar_wind_obs add column if not exists humidity   numeric;   -- 相対湿度 %
alter table public.nar_wind_obs add column if not exists pressure   numeric;   -- 現地気圧 hPa
alter table public.nar_wind_obs add column if not exists sunshine   numeric;   -- 日照 分(10 分間)

-- §239a 分析タブ(カルテ)の事実 nar_karte_facts(2026-09-22 新設)。書き手は cloud/karte_facts.py(数え方は pipeline/karte.py)。
--
-- ■ 何のための表か
--   分析タブ(南関 4 場だけ)の事実を便で**先に焼いておく**= 出走 1 頭 1 行。画面は 1 レース 1 読み
--   (⛔ページを開くたびに本番で集計しない= 設計 docs/proposal_s239_karte_facts_20260922.md 決めごと 6)。
--
-- ■ 決めごと(⛔設計側で決定)
--   ・発走前の値だけ= **その日より前の走だけ**で数える。馬の見分け= (名前, 生年)(§238e)。
--   ・欠け= NULL(⛔0 で埋めない)。能力検査・取消・除外・取りやめ(着の無い走)は走数に入れない。
--   ・割合(*_rate)は 0〜1。分母(*_n)が 0 のときは割合 NULL。材料が 1 本も無いときは分母も NULL。
--   ・出遅れ= 直近 5 走のうち記録(nar_kb_runs の行)のある走で start_note に「出遅」の回数(late_n)/記録のある走数(late_den)。
--     late_next_pct(%)= nar_meta 'karte:late_next:v1'(南関 2025-09〜2026-08 で数え直した割合表)を引くだけ。
--   ・style= nar_run_facts.style をそのまま(⛔ここで数え直さない= 決めごと 4)。style_counts= その 5 走
--     (facts.pick_past_runs)を 1 走ずつ 1 角の位置 p で 逃(<=0.2)/先(<=0.4)/差(<=0.7)/追 に切った回数。
--   ・late_runs= 出遅れた走が直近 5 走の何走前か(1= 前走)。gap_days= 前走(直近の実走)からの日数。
--   ・pos_var= 直近 5 走の最初のコーナーの順位(nar_run_facts.c1)の幅の字 '3〜7'(同じなら '5')/ pos_var_n= 使えた走数。
--   ・先行して粘った= c1 が 3 番手以内の走のうち 3 着以内 / 4角から失速= c4 が 3 番手以内の走のうち 4 着以下(直近 365 日)。
--   ・使われ方= 前日までの 30 日の走数・今年何戦目・180 日超の休みの後から何戦目(無ければ NULL)。
--   ・条件との相性= 通算(2014〜)・**南関の走だけ**: 大井 / ほか 3 場、ナイター(発走 17:00 以降)/ 昼 の 3 着内率と走数。
--   ・相手関係= 通算・南関の走だけ・どちらも完走したレースで先着(w)/負け(l)。h2h= [{umaban, horse_name, w, l}]。
--   ・調子= 直近 365 日: 1 着との差(秒= 走破タイム − 1 着のタイム)のいちばん小さい走とその日・直近 3 走の平均・
--     人気より上の着順の割合・3 着以内のうち 1 着の割合。
--
-- ■ 読み(⛔nar_run_facts と同じ書き方)= anon / authenticated の select だけ。書きは service_role。
-- 適用: psql … -v ON_ERROR_STOP=1 -X -f pipeline/sql/karte_facts_20260922.sql(⛔鍵を持つ担当が流す)
\set ON_ERROR_STOP on

create table if not exists public.nar_karte_facts (
  race_date         date not null,
  track             text not null,              -- 公式の場名(大井・船橋・川崎・浦和)
  race_no           int  not null,
  umaban            int  not null,              -- nar_runs.runner_number と同じ
  horse_key         text,                       -- nar_run_facts.horse_key と同じ字面(名前|生年月日・無ければ 名前|生年)
  horse_name        text,
  -- スタート
  late_n            int,                        -- 直近 5 走のうち出遅れの記録がある回数
  late_den          int,                        -- ⛔記録のある走数(記録の無い走は分母から外す)
  late_next_pct     numeric,                    -- 次も出遅れる割合(%)= 割合表を引くだけ
  late_runs         jsonb,                      -- 出遅れた走の位置 [1, 2](1= 前走・n= n 走前)。0 回は []・記録なしは NULL
  -- 走り方
  style             text,                       -- nar_run_facts.style(今日の行)
  style_counts      jsonb,                      -- 脚質の回数 {"逃":n,"先":n,"差":n,"追":n}= style と同じ 5 走を 1 走ずつ同じ閾値で
  lead_hold_rate    numeric,
  lead_hold_n       int,                        -- 最初のコーナー 3 番手以内の走数(直近 365 日)
  fade4_rate        numeric,
  fade4_n           int,                        -- 最後のコーナー 3 番手以内の走数(直近 365 日)
  pos_var           text,                       -- 直近 5 走の c1 の幅 '3〜7'
  pos_var_n         int,
  -- 使われ方
  runs_30d          int,
  run_of_year       int,
  since_layoff      int,                        -- 休み明け何戦目(180 日超の休みが無ければ NULL)
  gap_days          int,                        -- 今回の間隔= 前走からの日数(画面が gapText で「中◯週」等にする)
  -- 条件との相性(通算・南関の走だけ)
  oi_top3_rate      numeric,
  oi_n              int,
  other3_top3_rate  numeric,
  other3_n          int,
  night_top3_rate   numeric,
  night_n           int,
  day_top3_rate     numeric,
  day_n             int,
  -- 相手関係(通算・南関の走だけ)
  h2h               jsonb,                      -- [{umaban, horse_name, w, l}](馬番順・勝ち負けが付いた相手だけ)
  h2h_w             int,
  h2h_l             int,
  -- 調子(直近 365 日)
  best_margin       numeric,                    -- 1 着との差(秒)のいちばん小さい走
  best_margin_date  date,
  best_finish       int,                        -- いちばん良い走の着順
  recent3_margin    numeric,                    -- 直近 3 走の 1 着との差の平均(秒・0.1 に四捨五入)
  pop_beat_rate     numeric,
  pop_beat_n        int,                        -- 着順と人気が両方ある走数
  win_conv_rate     numeric,
  win_conv_n        int,                        -- 3 着以内の回数
  computed_at       timestamptz not null,
  primary key (race_date, track, race_no, umaban),
  constraint nar_karte_facts_style_ck
    check (style is null or style in ('逃げ', '先行', '差し', '追込')),
  constraint nar_karte_facts_rate_ck
    check (coalesce(lead_hold_rate, 0) between 0 and 1 and coalesce(fade4_rate, 0) between 0 and 1
       and coalesce(oi_top3_rate, 0) between 0 and 1 and coalesce(other3_top3_rate, 0) between 0 and 1
       and coalesce(night_top3_rate, 0) between 0 and 1 and coalesce(day_top3_rate, 0) between 0 and 1
       and coalesce(pop_beat_rate, 0) between 0 and 1 and coalesce(win_conv_rate, 0) between 0 and 1)
);

-- 画面の引き方= 1 レース分(race_date, track, race_no)。主キーの先頭 3 列でそのまま効く。
-- 検算は日付の降順で舐めるので日付の索引を 1 本(nar_run_facts と同じ形)。
create index if not exists nar_karte_facts_date_idx on public.nar_karte_facts (race_date desc, track);

alter table public.nar_karte_facts enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies
                  where schemaname = 'public' and tablename = 'nar_karte_facts'
                    and policyname = 'nar_karte_facts_read') then
    create policy nar_karte_facts_read on public.nar_karte_facts
      for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_karte_facts to anon, authenticated;

comment on table public.nar_karte_facts is
  '§239a 分析タブ(南関)の事実を 1 頭 1 行で先に焼く表(発走前の値だけ)。書き手は cloud/karte_facts.py・数え方は pipeline/karte.py';

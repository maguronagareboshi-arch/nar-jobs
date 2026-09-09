-- §129c base-v1 段階1= 予想AI の**特徴量の表**と、夜にそれを作り直す関数。
-- 設計= docs/proposal_s129b_base_v1_20260907.md(B-2 の 183 列・B-3 の④・C 章)。台帳= DESIGN §10 #524。
-- ⛔本番では流さない(9/8 決定)。Actions の Postgres 用 = 9/7 夜にこの関数を本番で流したら 30 分サイトが読めなくなった。
--   全量の特徴量作りは .github/workflows/nar-ai-feat.yml の中に立てた Postgres で行う(材料は本番から読むだけ)。
--   本番に流してよいのは表の定義まで(§129d)。詳しくは docs/opus_s129d_ai_feat_actions_20260908.md。
-- ⛔§129d で直した所(3 つ)= **insert が一度も通っていなかった**ので、地元で通して見つけた。
--   ①`nar_avg5/std5` は引数が real なのに `p_pos2`(= pos2::real / n2 は double precision)や
--     `p1_c4 - p1_chaku`(int - real)を渡していて「関数が無い」で落ちる → 呼ぶ所に `::real` を足した。
--   ②§129c2 で窓を日に束ねたとき `n_td` を落としていた(`nar_ai_feat_track.n_365` が使う)→ 入れ直した。
--   ③RLS / grant / revoke を `pg_roles` の有無で囲んだ(地元には Supabase の役が無い)。
--   ⛔①②とも**値の定義は変えていない**(型の注釈と、落ちていた count の入れ直しだけ)。
-- 型は pipeline/sql/jockey_change_20260907.sql(refresh_nar_jc)と同じ= security definer・
-- truncate+insert・1 トランザクション・戻りは行数。⛔画面からは読まない= anon に grant しない。
--
-- ■ この表は何か
--   「走 1 行 = その走の**直前時点**で分かっていることだけ」を 1 枚に持つ。
--   当日の出走予定(nar_runs に finish null で入っている出馬表の行)も**同じ INSERT で同じ列が埋まる**。
--   → 学習(where finish is not null)と推論(where race_date = 今日)が literally 同じ行を読む。
--
-- ■ 窓の掛け方(⛔§129c2= 本番で temp が溢れた直し)
--   ・窓と percent_rank の入力は **鍵 + その窓に要る数だけ**の細い表(⛔`r.*` `z.*` `q.*` を渡さない)。
--   ・日単位の窓(`range … preceding`)は先に (partition, d_idx) で sum/count に束ねてから掛ける=
--     **同じ値**で行数が 604,637 → 数万に落ちる。馬ごとの窓は行数が減らないので列を細くする。
--   ・出来た値は鍵で join して戻す。関数の冒頭で `work_mem` を 64MB(このトランザクションだけ)。
--
-- ■ as-of の規則(⛔漏洩ゼロ。ここが最重要)
--   すべての集計窓は **その走の race_date より前(= 前日まで)**で閉じる。
--   ・人・血統・場・コースの窓 … `range between N preceding and 1 preceding`(d_idx= 日の通し番号)
--   ・馬自身の過去走     … 前走= race_date が**厳密に前**の走のうち最後のもの(同じ日の他レースは見ない)
--   ・レース内の順位     … 同じレースの**発走前に分かる特徴量どうし**の順位(結果は使わない)
--   ・馬場差(baba_diff_d)… **前の開催日**の値(その日の勝ち時計は発走前に無い。Fable 9/7 修正)
--   ・コース別(cf/cq)    … コーナー解析ずみの走からしか行が立たないので、当日の行は**直近の日**の値を引く
--                          (学習と推論で同じ列が同じ作り方で埋まるように。Fable 9/7 修正)
--   ⛔`nar_jc_pairs` / `nar_jc_trainer_jockey`(§126)は**全期間**の集計= 未来を含むので使わない。
--     同じ定義を `nar_jc_runs` の走ごとの行から as-of で組み直す(I-7)。
--   ⛔`nar_race_level` は「そのレースの出走馬が**次走**でどう走ったか」= 未来そのもの。使わない
--     (設計書 I-8 の未確認事項を pipeline/sql/race_level.sql で確認した結果)。
--     `opp_str_now` / `p1_fld` / `p2_fld` / `p3_fld` / `avg_fld_3` / `relief_3` は
--     「その日までに分かっている相手の実績(前日までの複勝率の平均)」で作り直している。
--
-- ■ 馬の鍵
--   `horse_key = horse_name || '|' || birth_date`(§126 と同じ)。birth_date は 604,037 行すべてに入っている。
--
-- ■ コーナー通過順の読み方(⛔js/data.js `cornerRanks()` と cloud/tenkai.py `corner_ranks()` と同じ規則)
--   `nar_races.corners` = [{"name":"３角","order":"2,11,(4,6,12),10-(7,9)"}, …](走った順に並ぶ)。
--   数字= 馬番・`( )` = 横に並んだ馬(**先頭の順位を共有**し次はその頭数ぶん飛ぶ)・`-` `=` は差(順位は変えない)。
--   知らない字が出たら**そのコーナーごと捨てる**(⛔推定しない)。読めたコーナーだけを並びの順に使う。
--   ⚠ コーナーの名前は場ごとにばらばら(「正面/２角/３角/４角」「１コーナー…」「２周目４コーナー」…26 種を実測)
--     ので**名前では引かず、読めたコーナーの並びの位置**で決める:
--       pos1 = 最初        … §99a の `first_corner()` と同じ(先行度 qpts・前残りバイアスに使う)
--       pos4 = 最後        … 直線に入る前の最終コーナー(「4角」。２周目がある場でも最後が最終コーナー)
--       pos3 = 最後から2番目(コーナーが 2 つ以上あるときだけ)
--       pos2 = 2 番目      … ⛔読めたコーナーが **3 つ以上**のときだけ(2 つだと pos4 と同じものになるため NULL)
--   順位の分母は ⛔**そのコーナーに並んだ頭数**(field_size ではない。#466 で 48R 中 6 本ずれた)。
--
-- ■ 着差の文字列 → 馬身(ユーザー決定 2026-09-07・標準の対応表)
--   ハナ 0.05 / アタマ 0.1 / クビ 0.3 / 同着 0 / 大差 10 / 「1.1/2」= 1.5 / 「3/4」= 0.75 / 「3」= 3。
--   「レコード」「競走取止め」「競走不成立」は着差ではないので NULL(⛔0 にしない)。
--
-- ■ 段階 1 では埋めない列(NULL のまま列だけ用意する)
--   `pl_theta` `pl_n` `jk_beta` `tr_gamma` `r_plth_pct` `pl_gap_top` `jk_beta_delta`(B-2 158〜164)=
--   Plackett-Luce の逐次レーティング。⛔SQL では日付順 1 パスの逐次更新が書けないので段階 1b(Python)。
--   ⛔`c1_dist`(B-2 140・1角までの距離)は**材料が無い**ので列を作らない(B-4 決定①)。
--
-- ■ 欠けの扱い
--   ⛔false zero 禁止。行が無い・分母が 0・読めない = **NULL**(LightGBM は NaN を扱える)。
--   ⛔欠けの多い列も落とさない(B-4 決定③)。⛔帯広ばんえいも入れる(B-4 決定④)。
--
-- ■ カテゴリ列の数値の割り当て(⛔学習と推論で同じものを使う。nar_ai_meta 'codes' にも入れる)
--   seibetsu: 牡=0 / 牝=1 / セン=2      keibajo: 下の nar_ai_meta 'codes' の 15 場
--   baba_now(going): 良=0 / 稍重=1 / 重=2 / 不良=3(⛔帯広ばんえいの going は含水率の数字なので NULL)
--   style(§99a 脚質): 逃げ=0 / 先行=1 / 差し=2 / 追込=3     jc_tier(§126): 上=1 / 同=0 / 下=-1

set statement_timeout = '30min';

begin;

-- ============================================================ 補助関数(2 本)

-- 着差の文字列 → 馬身。⛔上の対応表そのまま。読めない語は NULL。
create or replace function public.nar_margin_len(p_margin text)
returns real
language sql
immutable
parallel safe
as $fn$
  select case
    when btrim(coalesce(p_margin, '')) = ''       then null
    when btrim(p_margin) = 'ハナ'                 then 0.05::real
    when btrim(p_margin) = 'アタマ'               then 0.10::real
    when btrim(p_margin) = 'クビ'                 then 0.30::real
    when btrim(p_margin) = '同着'                 then 0.00::real
    when btrim(p_margin) = '大差'                 then 10.0::real
    when btrim(p_margin) ~ '^[0-9]+$'             then btrim(p_margin)::real
    when btrim(p_margin) ~ '^[0-9]+/[0-9]+$'      then
      split_part(btrim(p_margin), '/', 1)::real / nullif(split_part(btrim(p_margin), '/', 2)::real, 0)
    when btrim(p_margin) ~ '^[0-9]+\.[0-9]+/[0-9]+$' then
      split_part(btrim(p_margin), '.', 1)::real
      + split_part(split_part(btrim(p_margin), '.', 2), '/', 1)::real
        / nullif(split_part(split_part(btrim(p_margin), '.', 2), '/', 2)::real, 0)
    else null
  end;
$fn$;

-- 1 コーナーぶんの並び → {"馬番": 順位} の jsonb。読めなければ NULL(⛔そのコーナーごと捨てる)。
-- ⛔js/data.js `cornerRanks()` の**そのままの写し**(同じ 5 例が tests/tenkai_corner_test.mjs と
--   cloud/tenkai.py --selftest にある。どれかを直したら 3 つとも直すこと)。
create or replace function public.nar_corner_ranks(p_order text)
returns jsonb
language plpgsql
immutable
parallel safe
as $fn$
declare
  s    text := btrim(coalesce(p_order, ''));
  n    int;
  i    int := 1;
  j    int;
  e    int;
  rk   int := 1;
  ch   text;
  body text;
  part text;
  k    text;
  cnt  int;
  out  jsonb := '{}'::jsonb;
begin
  n := length(s);
  if n = 0 then return null; end if;
  while i <= n loop
    ch := substr(s, i, 1);
    if ch = ',' or ch = '-' or ch = '=' or ch = ' ' or ch = '　' then
      i := i + 1;
      continue;
    end if;
    if ch = '(' then
      e := position(')' in substr(s, i));
      if e = 0 then return null; end if;                 -- 閉じない= 読めない
      e := i + e - 1;
      body := substr(s, i + 1, e - i - 1);
      cnt := 0;
      foreach part in array string_to_array(body, ',') loop
        part := btrim(part);
        if part !~ '^[0-9]+$' then return null; end if;   -- 知らない字= 読めない
        if part::int <= 0 then return null; end if;
        k := part::int::text;
        if not (out ? k) then out := jsonb_set(out, array[k], to_jsonb(rk)); end if;
        cnt := cnt + 1;
      end loop;
      if cnt = 0 then return null; end if;
      rk := rk + cnt;                                     -- 併走は頭数ぶん飛ぶ
      i := e + 1;
      continue;
    end if;
    j := i;
    while j <= n and substr(s, j, 1) ~ '^[0-9]$' loop j := j + 1; end loop;
    if j = i then return null; end if;                    -- 知らない字= 読めない(⛔推定しない)
    k := substr(s, i, j - i)::int::text;
    if not (out ? k) then out := jsonb_set(out, array[k], to_jsonb(rk)); end if;
    rk := rk + 1;
    i := j;
  end loop;
  if out = '{}'::jsonb then return null; end if;
  return out;
end;
$fn$;

-- 直近 5 走の値をまとめる小道具(⛔NULL は「無い」= 数に入れない・0 にしない)。
create or replace function public.nar_cnt5(a real, b real, c real, d real, e real)
returns real language sql immutable parallel safe as $fn$
  select count(y)::real from (values (a), (b), (c), (d), (e)) t(y);
$fn$;

create or replace function public.nar_avg5(a real, b real, c real, d real, e real)
returns real language sql immutable parallel safe as $fn$
  select avg(y)::real from (values (a), (b), (c), (d), (e)) t(y) where y is not null;
$fn$;

-- 母標準偏差(2 本以上あるときだけ)
create or replace function public.nar_std5(a real, b real, c real, d real, e real)
returns real language sql immutable parallel safe as $fn$
  select case when count(y) >= 2 then
    sqrt(greatest(sum(y::float8 * y) / count(y) - (sum(y::float8) / count(y)) ^ 2, 0))::real end
  from (values (a), (b), (c), (d), (e)) t(y) where y is not null;
$fn$;

-- 最小二乗の傾き。x= -1(1 走前)〜 -5(5 走前)= 正なら**最近ほど大きい**
create or replace function public.nar_slope5(a real, b real, c real, d real, e real)
returns real language sql immutable parallel safe as $fn$
  select case when count(y) >= 2 then
    ((count(y) * sum(x * y::float8) - sum(x) * sum(y::float8))
     / nullif(count(y) * sum(x * x) - sum(x) ^ 2, 0))::real end
  from (values (-1.0::float8, a), (-2.0, b), (-3.0, c), (-4.0, d), (-5.0, e)) t(x, y)
  where y is not null;
$fn$;


-- ============================================================ 表(3 つ)

-- 本体。⛔列は **real(float4)** で持つ(double だと倍。設計 C-2 の容量の話)。
-- 列の並びは設計書 B-2 の #1〜#183(#140 c1_dist は無し)+ B-3 の④。
create table if not exists public.nar_ai_feat_run (
  track          text     not null,
  race_date      date     not null,
  race_no        smallint not null,
  runner_number  smallint not null,
  horse_key      text     not null,
  -- 目的変数と照合用(⛔特徴量ではない= 学習の入力に入れない)
  finish         smallint,
  finish_note    text,
  popularity     smallint,
  y_top3         smallint,          -- finish <= 3
  y_win          smallint,          -- finish = 1
  -- ---- B-2 #1〜#19 前走まわり・当日の条件
  prev_chakujun     real, prev_chakusa     real, prev_corner4     real, prev_ninki      real,
  avg_chakujun_3    real, fukusho_rate_5   real, days_since_prev  real, dist_change     real,
  track_change      real, futan            real, futan_diff       real, prev_bataiju    real,
  barei             real, seibetsu         real, tosu             real, wakuban         real,
  kyori             real, keibajo          real, prize1_log       real,
  -- ---- #20〜#37 距離適性・人・血統・当地・時計・コーナー・クラス・ペース
  dist_fukusho_rate real, dist_n           real, kishu_fuku_1y    real, kishu_n_1y      real,
  chokyo_fuku_1y    real, chokyo_n_1y      real, sire_fuku_band   real, sire_n_band     real,
  uma_place_fuku    real, uma_place_n      real, norikae          real, prev_time_z     real,
  avg_time_z_3      real, prev_pos2_rate   real, prev_pos4_rate   real, avg_pos2_3      real,
  class_diff        real, prev_ra_pace     real,
  -- ---- #38〜#54 暦・レース内順位・バイアス・馬場差・年
  race_month        real, hasso_hour       real, r_fuku5_pct      real, r_timez_pct     real,
  r_pchakusa_pct    real, waku_bias_365    real, waku_bias_30     real, pace_bias_365   real,
  pace_bias_30      real, prev_time_za     real, avg_time_za_3    real, r_timeza_pct    real,
  runs_this_year    real, season_debut     real, prevyear_fukusho real, prevyear_timez  real,
  prevyear_n        real,
  -- ---- #55〜#104 過去 5 走(着順/着差/時計偏差/2角/4角/人気/距離差/クラス/間隔/同じ場)
  p1_chaku  real, p2_chaku  real, p3_chaku  real, p4_chaku  real, p5_chaku  real,
  p1_sa     real, p2_sa     real, p3_sa     real, p4_sa     real, p5_sa     real,
  p1_tz     real, p2_tz     real, p3_tz     real, p4_tz     real, p5_tz     real,
  p1_pos2   real, p2_pos2   real, p3_pos2   real, p4_pos2   real, p5_pos2   real,
  p1_pos4   real, p2_pos4   real, p3_pos4   real, p4_pos4   real, p5_pos4   real,
  p1_ninki  real, p2_ninki  real, p3_ninki  real, p4_ninki  real, p5_ninki  real,
  p1_dkyori real, p2_dkyori real, p3_dkyori real, p4_dkyori real, p5_dkyori real,
  p1_cls    real, p2_cls    real, p3_cls    real, p4_cls    real, p5_cls    real,
  p1_gap    real, p2_gap    real, p3_gap    real, p4_gap    real, p5_gap    real,
  p1_same   real, p2_same   real, p3_same   real, p4_same   real, p5_same   real,
  -- ---- #105〜#109 直近 5 走のまとめ
  best_tz_5 real, worst_tz_5 real, std_tz_5 real, best_chaku_5 real, n_tz_5 real,
  -- ---- #110〜#125 残差Z(RZ16)= 条件(場×距離×馬場×クラス×頭数)を除いた時計の速さ
  p1_rz    real, p2_rz    real, p3_rz    real, p4_rz     real, p5_rz     real,
  p1_rzin  real, p2_rzin  real, p3_rzin  real,
  avg_rz_3 real, avg_rz_5 real, best_rz_5 real, std_rz_5  real, avg_rzin_3 real,
  n_rz_5   real, r_rz_pct real, r_bestrz_pct real,
  -- ---- #126〜#139 相手の強さ・当日の馬体重と馬場・道悪・前走騎手
  opp_str_now real, p1_fld real, p2_fld real, p3_fld real, avg_fld_3 real, relief_3 real,
  bataiju_now real, bataiju_diff real, baba_now real,
  wet_n real, wet_fuku real, wet_tza_gap real, p1_kishu_fuku real, kishu_delta real,
  -- ---- #141〜#157 馬体重の傾き・ペア・ラップ・母父・馬場レジーム・距離適性
  --      (⛔#140 c1_dist= 1角までの距離は材料が無いので列を作らない)
  bw_slope_5 real, bw_dev real, p1_season_debut real,
  pair_fuku_3y real, pair_n_3y real, pair_vs_kishu real,
  p1_lappace real, p1_lapfade real, mf_fuku_band real, mf_n_band real,
  sire_rgm_gap real, mf_rgm_gap real, rgm_gap real, rgm_n real, trk_recent_dmz real,
  dist_match real, p1_dist_match real,
  -- ---- #158〜#164 Plackett-Luce の逐次レーティング。⛔段階 1 では NULL(段階 1b・Python で埋める)
  pl_theta real, pl_n real, jk_beta real, tr_gamma real,
  r_plth_pct real, pl_gap_top real, jk_beta_delta real,
  -- ---- #165〜#183 季節・間隔・惜敗・コーナー由来・見習い・休養明け・自己ベスト・反動
  bw_season_dev real, sex_summer real, rest_leq3 real, rest_gt42 real,
  oshi_nose2 real, oshi_nose4 real, oshi_rate real,
  c4lead_lost_rate real, mak_gain_m3 real, pos2_var5 real, fade34_rate5 real,
  qpts real, race_qsum real, race_qmax real, minarai_now real,
  since_layoff real, prev_best5 real, bounce_risk real, has_hist real,
  -- ============ B-3 ④ サイト独自(FEATURES183 に無い) ============
  -- ④2/④4 提供データの前半3F とテン(⛔6 場・2026 年〜。園田は 82 本= 実質欠測)
  ten_kb real, ten_kb_dev real, avg_f real, ten_rank real,
  -- ④19 上がり3F(B-5「足りない」・Fable 9/7)。nar_runs.last3f= 馬ごとの上がり(89%)。z= 場×距離×馬場の前日まで 365 日
  p1_l3z real, p2_l3z real, p3_l3z real, avg_l3z_3 real, best_l3z_5 real, r_l3z_pct real, p1_l3gap real,
  -- ④3 展開の見立て(§99a)。⛔当日の nar_meta tenkai: は 1 日ぶんしか無いので corners から同じ規則で作る
  style real, avg_pos_5 real, lead_n real, n_front real, front_ratio real,
  -- ④5 乗り替わりの相性(§126)。⛔全期間集計の nar_jc_pairs は使わず as-of で組み直す(I-7)
  jc_changed real, jc_rejoin real, jc_tier real,
  jc_pair_n real, jc_pair_hit real, jc_tj_n real, jc_tj_hit real,
  -- ④6 馬具の変化(§119c)。⛔blinker 列は全行 0 件なので使わない= gear の文字列だけ
  gear_now real, gear_first real, gear_off real, gear_n real, gear_hit real, start_note_n real,
  -- ④7 収得賞金(§79 P3)。⛔nar_horse_prize.calc は「今日の値」なので使わず、賞金を as-of で積む
  prize_local real, prize_local_log real, r_prize_pct real,
  -- ④10 馬場傾向(§100)。⛔nar_meta baba_trend は直近 90 日の 1 枚なので内外ρは corners から作り直す
  baba_diff_d real, baba_io_365 real,
  -- ④11 コース別(§103)。⛔nar_meta course_stats も今日の 1 枚なので 365 日 as-of で作り直す
  course_waku_hit real, course_front_win real, course_pos_hit real,
  -- ④13 疾病・取消(§89/§109)。⛔公表日(reported_date)より前のものだけ数える
  ill_n_365 real, ill_last_days real, scratch_n_365 real, p1_scratch real,
  -- ④14 能力検査(§117/§32a)。⛔has_hist=0(初出走)の馬に唯一入る情報
  noken_days real, noken_time real, is_noken_debut real,
  -- ④15 馬主・生産者(FEATURES183 に無いが材料はある)
  owner_hit real, owner_n real, breeder_hit real, breeder_n real,
  -- ④16 せり価格(§54.6)。⛔ほとんどの馬で欠測
  sale_price real, sale_year real,
  -- ④17 制裁(§111)。⛔価値判断の語は入れない(数だけ)
  jockey_penalty_90d real,
  -- ④18 売上(§54.1)。⛔当日の売上は発走前に確定しないので**前日までの場平均**
  race_sales real, sales_vs_venue_avg real,
  updated_at timestamptz not null default now(),
  primary key (track, race_date, race_no, runner_number)
);
create index if not exists nar_ai_feat_run_date_idx  on public.nar_ai_feat_run (race_date);
create index if not exists nar_ai_feat_run_horse_idx on public.nar_ai_feat_run (horse_key, race_date);

-- 場×日×距離のまとめ(C-2)。人が見る用+検算用。⛔バイアスは場×日で作り、距離の行に同じ値を写している。
create table if not exists public.nar_ai_feat_track (
  track         text not null,
  race_date     date not null,
  distance_m    int  not null,
  baba_diff     real,      -- §48 K-1b 馬場差(nar_meta baba_diff。その日その場の時計の出方)
  waku_bias_30  real, waku_bias_365  real,   -- 枠番と着順の順位相関(前日までの 30 日 / 365 日)
  pace_bias_30  real, pace_bias_365  real,   -- 1角の位置と着順の順位相関(同上)
  std_time      real,      -- その場×距離の走破時計のばらつき(前日までの 365 日)
  n_365         int,
  primary key (track, race_date, distance_m)
);

-- 作り直しの記録(nar_jc_meta と同型)
create table if not exists public.nar_ai_meta (
  key text primary key, value jsonb not null, updated_at timestamptz not null default now()
);

-- ⛔画面からは読まない= anon / authenticated に select を渡さない(RLS は有効・ポリシー無し= 誰も読めない)
-- ⛔§129d= ここは Supabase の役(service_role / anon / authenticated)がある所だけ。
--   Actions の中の素の Postgres には無くて落ちるので、役があるときだけ流す。
--   ⛔本番での意味は 1 字も変えていない(本番には service_role があるので前と同じに走る)。
do $rls$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'alter table public.nar_ai_feat_run   enable row level security';
    execute 'alter table public.nar_ai_feat_track enable row level security';
    execute 'alter table public.nar_ai_meta       enable row level security';
    execute 'grant select, insert, update, delete, truncate'
         || ' on public.nar_ai_feat_run, public.nar_ai_feat_track, public.nar_ai_meta to service_role';
  else
    raise notice '(service_role が無い= 地元の Postgres。RLS と grant は飛ばす)';
  end if;
end
$rls$;

-- ============================================================ 夜の作り直し

-- p_from を渡すと「その日以降だけ」差し替える(⛔窓は前日までなので過去行は変わらない= 追記で正しい)。
-- 素形は毎回全期間から組み立てる(窓に過去が要るため)。戻り= (走の行数, 場×日×距離の行数, 所要秒)。
-- §141 D-2(2026-09-09)= 時計プールの窓を引数にした。⛔既定 365= 便の呼び方は 1 字も変えなくていい。
--   ⚠引数を足すと `create or replace` は**置き換えではなく多重定義**になり、
--     いままでの `refresh_nar_ai_feat(null)` が「関数は一意でありません」で落ちる
--     (手元の PostgreSQL 11.11 で実測 2026-09-09)。だから先に旧い形を落とす。
drop function if exists public.refresh_nar_ai_feat(date);
create or replace function public.refresh_nar_ai_feat(p_from date default null, p_pool_days int default 365)
returns table (runs bigint, tracks bigint, seconds numeric)
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  t0 timestamptz := clock_timestamp();
begin
  -- ⛔§129c2= 本番の work_mem は 2,184 kB(実測)で、窓の並べ替えが全部ディスクに落ちて溢れた。
  --   このトランザクションの間だけ 64MB にする(⛔本番の計算機は小さいのでこれ以上は上げない)。
  perform set_config('work_mem', '64MB', true);

  if p_from is null then
    truncate public.nar_ai_feat_run, public.nar_ai_feat_track;
  else
    delete from public.nar_ai_feat_run   where race_date >= p_from;
    delete from public.nar_ai_feat_track where race_date >= p_from;
  end if;

  -- ---------------------------------------------------------- 0) 走の素形
  -- ⛔取消・除外の行も残す(前走にはしないが「前走が取消だった」は特徴量)。
  -- ⛔当日の出走予定(finish null)も同じ表に入れる= 同じ列が同じ作り方で埋まる。
  create temp table t_run on commit drop as
  select
    u.track, u.race_date, u.race_no::smallint as race_no, u.runner_number::smallint as runner_number,
    u.gate, u.horse_name,
    u.horse_name || '|' || coalesce(u.birth_date::text, '') as horse_key,
    nullif(btrim(u.jockey), '')  as jockey,
    nullif(btrim(u.trainer), '') as trainer,
    u.age, u.carried_weight, u.body_weight, u.body_weight_change,
    u.finish, u.finish_note, u.time_sec, u.last3f, u.popularity, u.weight_mark,
    r.distance_m, r.field_size, r.race_kind, r.furlongs, r.race_last3f,
    (u.race_date - date '2000-01-01')::int as d_idx,
    (u.finish is not null)                 as is_run,
    public.nar_margin_len(u.margin)        as sa,
    (case u.sex when '牡' then 0 when '牝' then 1 when 'セン' then 2 end)::real as seibetsu,
    (case r.going when '良' then 0 when '稍重' then 1 when '重' then 2 when '不良' then 3 end)::real as going_ord,
    (case u.track when '帯広ば' then 0 when '門別' then 1 when '盛岡' then 2 when '水沢' then 3
                  when '浦和' then 4 when '船橋' then 5 when '大井' then 6 when '川崎' then 7
                  when '金沢' then 8 when '笠松' then 9 when '名古屋' then 10 when '園田' then 11
                  when '姫路' then 12 when '高知' then 13 when '佐賀' then 14 end)::real as keibajo,
    (nullif(r.prize_yen->>0, ''))::bigint  as prize1,
    (case when u.finish is null then null
          when u.finish between 1 and 5 then coalesce((nullif(r.prize_yen->>(u.finish - 1), ''))::bigint, 0)
          else 0 end)                      as earned,
    (case when u.finish is null then null when u.finish <= 3 then 1 else 0 end)::real as hit3,
    (case when u.finish is null then null when u.finish = 1  then 1 else 0 end)::real as win1,
    (round(r.distance_m / 200.0) * 200)::int as dist_band,   -- ⚠「±200m の帯」は 200m 刻みの箱で近似
    -- 日で束ねる窓の鍵(⛔NULL のままだと join で落ちるので -1 に潰す。partition の分かれ方は同じ)
    coalesce(r.distance_m, -1)                                       as dist_k,
    coalesce((case r.going when '良' then 0 when '稍重' then 1
                           when '重' then 2 when '不良' then 3 end), -1) as gord_k,
    (left(lpad(r.post_time, 4, '0'), 2))::real as hasso_hour,
    extract(month from u.race_date)::real   as race_month,
    extract(year  from u.race_date)::int    as yr,
    (case when coalesce(u.finish_note, '') <> '' then 1 else 0 end)::real as scratched,
    h.sire, h.broodmare_sire, h.owner, h.breeder,
    kb.first3f as kb_f3, kb.avg_f as kb_avgf, (kb.umaban is not null) as kb_row,
    nullif(btrim(coalesce(kb.gear, '')), '')       as kb_gear,
    nullif(btrim(coalesce(kb.start_note, '')), '') as kb_note
  from public.nar_runs u
  join public.nar_races r using (track, race_date, race_no)
  left join public.nar_horses h on h.horse_name = u.horse_name
  left join public.nar_kb_runs kb on kb.track = u.track and kb.race_date = u.race_date
                                 and kb.race_no = u.race_no and kb.umaban = u.runner_number;

  create index t_run_key_idx   on t_run (track, race_date, race_no, runner_number);
  create index t_run_horse_idx on t_run (horse_key, race_date);
  analyze t_run;

  -- ---------------------------------------------------------- 1) コーナー通過順
  -- 読めたコーナーだけを並びの順に持つ(maps)。ns= そのコーナーに並んだ頭数(⛔順位の分母)。
  create temp table t_cmap on commit drop as
  with e as (
    select r.track, r.race_date, r.race_no::smallint as race_no, t.ord,
           public.nar_corner_ranks(t.x->>'order') as m
    from public.nar_races r,
         lateral jsonb_array_elements(r.corners) with ordinality t(x, ord)
    where r.corners is not null and jsonb_typeof(r.corners) = 'array'
  )
  select track, race_date, race_no,
         array_agg(m order by ord) as maps,
         array_agg((select count(*) from jsonb_object_keys(m))::int order by ord) as ns
  from e
  where m is not null
  group by 1, 2, 3;
  create index t_cmap_key_idx on t_cmap (track, race_date, race_no);
  analyze t_cmap;

  create temp table t_corner on commit drop as
  select b.track, b.race_date, b.race_no, b.runner_number,
         (c.maps[1] ->> b.runner_number::text)::int as pos1,
         c.ns[1] as n1,
         case when array_length(c.maps, 1) >= 3
              then (c.maps[2] ->> b.runner_number::text)::int end as pos2,
         case when array_length(c.maps, 1) >= 3 then c.ns[2] end  as n2,
         case when array_length(c.maps, 1) >= 2
              then (c.maps[array_length(c.maps, 1) - 1] ->> b.runner_number::text)::int end as pos3,
         case when array_length(c.maps, 1) >= 2 then c.ns[array_length(c.maps, 1) - 1] end  as n3,
         (c.maps[array_length(c.maps, 1)] ->> b.runner_number::text)::int as pos4,
         c.ns[array_length(c.maps, 1)] as n4
  from t_run b
  join t_cmap c on c.track = b.track and c.race_date = b.race_date and c.race_no = b.race_no;
  create index t_corner_key_idx on t_corner (track, race_date, race_no, runner_number);
  analyze t_corner;

  -- ---------------------------------------------------------- 2) 走ごとの as-of(1 周目)
  -- ⛔窓はすべて `range between N preceding and 1 preceding`= **前日まで**(同じ日の結果は入らない)。
  -- ⛔§129c2(本番で temp が溢れた直し)= **窓の入力は細い表だけ**にする:
  --   ・日単位の窓は先に (partition, d_idx) で sum/count に束ねてから窓を掛ける(⛔同じ値になる)。
  --     604,637 行 → 数万行に落ちるので並べ替えがメモリに収まる。
  --   ・馬ごとの窓は束ねても行数が減らないので、**鍵 + その窓に要る数だけ**の細い行に掛ける。
  --   ・出来た値は**鍵で join して戻す**。⛔`r.*` を窓の入力にしない。
  -- 平均と標準偏差は sum/count から出す(⛔移動窓で percentile / stddev は毎行 O(窓) になるため)。
  -- tz(時計偏差)は **大きいほど速い**= (その条件の平均 − 自分の時計) ÷ その条件のばらつき。

  -- (a) 場×距離×馬場を日で束ねる → 前日まで 365 日の 走破時計・レース上がり・馬の上がり3F
  create temp table t_day_td on commit drop as
  select track, dist_k, gord_k, d_idx,
         (sum(n_t) over w)::bigint                           as n_td,
         (sum(s_t) over w / nullif(sum(n_t) over w, 0))::real as m_td,
         sqrt(greatest(sum(q_t) over w / nullif(sum(n_t) over w, 0)
                       - (sum(s_t) over w / nullif(sum(n_t) over w, 0)) ^ 2, 0))::real as sd_td,
         (sum(s_l3) over w / nullif(sum(n_l3) over w, 0))::real as m_l3,
         (sum(s_l3h) over w / nullif(sum(n_l3h) over w, 0))::real as m_l3h,
         sqrt(greatest(sum(q_l3h) over w / nullif(sum(n_l3h) over w, 0)
                       - (sum(s_l3h) over w / nullif(sum(n_l3h) over w, 0)) ^ 2, 0))::real as sd_l3h
  from (
    select track, dist_k, gord_k, d_idx,
           sum(time_sec) s_t, sum(time_sec * time_sec) q_t, count(time_sec) n_t,
           sum(race_last3f) s_l3, count(race_last3f) n_l3,
           sum(last3f) s_l3h, sum(last3f * last3f) q_l3h, count(last3f) n_l3h
    from t_run group by 1, 2, 3, 4
  ) g
  -- §141 D-2 ⚠**この 1 か所だけ**引数にした(場×距離×馬場の走破時計・上がりのプール)。
  --   ⛔ほかの 365 日窓(騎手 1 年・枠バイアス等)は触っていない。
  window w as (partition by track, dist_k, gord_k order by d_idx
               range between p_pool_days preceding and 1 preceding);
  create index t_day_td_idx on t_day_td (track, dist_k, gord_k, d_idx);
  analyze t_day_td;

  -- (b) 場×距離を日で束ねる → 馬場差の基準になる平均時計と、提供データの前半3F
  create temp table t_day_dn on commit drop as
  select track, dist_k, d_idx,
         (sum(s_t) over w / nullif(sum(n_t) over w, 0))::real as m_dn,
         sum(s_f3) over w as s_f3, sum(n_f3) over w as n_f3
  from (
    select track, dist_k, d_idx, sum(time_sec) s_t, count(time_sec) n_t,
           sum(kb_f3) s_f3, count(kb_f3) n_f3
    from t_run group by 1, 2, 3
  ) g
  window w as (partition by track, dist_k order by d_idx range between 365 preceding and 1 preceding);
  create index t_day_dn_idx on t_day_dn (track, dist_k, d_idx);
  analyze t_day_dn;

  -- (c) 場を日で束ねる → クラス水準(1着賞金の対数)の基準
  create temp table t_day_trk on commit drop as
  select track, d_idx, sum(s_pz) over w as s_pz, sum(n_pz) over w as n_pz
  from (
    select track, d_idx, sum(ln(nullif(prize1, 0)::numeric)) s_pz, count(nullif(prize1, 0)) n_pz
    from t_run group by 1, 2
  ) g
  window w as (partition by track order by d_idx range between 365 preceding and 1 preceding);
  create index t_day_trk_idx on t_day_trk (track, d_idx);
  analyze t_day_trk;

  -- (d) 馬ごとの as-of。⛔窓の入力は「鍵 + 要る数だけ」の細い行
  create temp table t_h1 on commit drop as
  select x.track, x.race_date, x.race_no, x.runner_number,
         (x.s_hit_all / nullif(x.n_hit_all, 0))::real   as hit_car,
         x.n_hit_all::real                              as n_car,
         (x.s_hit_band / nullif(x.n_hit_band, 0))::real as hit_band,
         x.n_hit_band::real                             as n_band,
         (x.s_hit_trk / nullif(x.n_hit_trk, 0))::real   as hit_trk,
         x.n_hit_trk::real                              as n_trk,
         (x.s_hit_wet / nullif(x.n_hit_wet, 0))::real   as hit_wet,
         x.n_hit_wet::real                              as n_wet,
         (x.s_hit_gng / nullif(x.n_hit_gng, 0))::real   as hit_gng,
         x.n_hit_gng::real                              as n_gng,
         x.n_yr::real                                   as runs_this_year,
         (case when x.n_yr = 0 then 1 else 0 end)::real as season_debut,
         (x.s_bw / nullif(x.n_bw, 0))::real             as m_bw,
         (x.s_bwm / nullif(x.n_bwm, 0))::real           as m_bwm,
         (x.s_hit_gear / nullif(x.n_hit_gear, 0))::real as gear_hit,
         x.n_hit_gear::real                             as gear_n,
         x.n_note::real                                 as start_note_n,
         x.n_scratch_365::real                          as scratch_n_365,
         x.prize_local
  from (
    select h.track, h.race_date, h.race_no, h.runner_number,
           sum(h.hit3)   over w_h_all  as s_hit_all,  count(h.hit3) over w_h_all  as n_hit_all,
           sum(h.hit3)   over w_h_band as s_hit_band, count(h.hit3) over w_h_band as n_hit_band,
           sum(h.hit3)   over w_h_trk  as s_hit_trk,  count(h.hit3) over w_h_trk  as n_hit_trk,
           sum(case when h.going_ord >= 1 then h.hit3 end)   over w_h_all as s_hit_wet,
           count(case when h.going_ord >= 1 then h.hit3 end) over w_h_all as n_hit_wet,
           sum(h.hit3)   over w_h_gng  as s_hit_gng,  count(h.hit3) over w_h_gng  as n_hit_gng,
           count(h.hit3) over w_h_yr   as n_yr,
           sum(h.body_weight) over w_h_all as s_bw,   count(h.body_weight) over w_h_all as n_bw,
           sum(h.body_weight) over w_h_bwm as s_bwm,  count(h.body_weight) over w_h_bwm as n_bwm,
           sum(case when h.gear_yes then h.hit3 end)   over w_h_all as s_hit_gear,
           count(case when h.gear_yes then h.hit3 end) over w_h_all as n_hit_gear,
           count(case when h.note_yes then 1 end)      over w_h_all as n_note,
           count(case when h.scr then 1 end)           over w_h_365 as n_scratch_365,
           sum(h.earned) over w_h_all as prize_local
    from (
      select track, race_date, race_no, runner_number, horse_key, d_idx, hit3, going_ord,
             dist_band, yr, race_month, body_weight, earned,
             (scratched = 1)                  as scr,
             (is_run and kb_gear is not null)  as gear_yes,
             (is_run and kb_note is not null)  as note_yes
      from t_run
    ) h
    window
      w_h_all  as (partition by h.horse_key               order by h.d_idx range between unbounded preceding and 1 preceding),
      w_h_band as (partition by h.horse_key, h.dist_band  order by h.d_idx range between unbounded preceding and 1 preceding),
      w_h_trk  as (partition by h.horse_key, h.track      order by h.d_idx range between unbounded preceding and 1 preceding),
      w_h_gng  as (partition by h.horse_key, h.going_ord  order by h.d_idx range between unbounded preceding and 1 preceding),
      w_h_yr   as (partition by h.horse_key, h.yr         order by h.d_idx range between unbounded preceding and 1 preceding),
      w_h_bwm  as (partition by h.horse_key, h.race_month order by h.d_idx range between unbounded preceding and 1 preceding),
      w_h_365  as (partition by h.horse_key               order by h.d_idx range between 365 preceding and 1 preceding)
  ) x;
  create index t_h1_idx on t_h1 (track, race_date, race_no, runner_number);
  analyze t_h1;

  -- (e) その日その場が減量記号を出しているか(#179 minarai_now の分母)
  create temp table t_marks on commit drop as
  select track, race_date, count(weight_mark) as day_marks from t_run group by 1, 2;
  create index t_marks_idx on t_marks (track, race_date);

  -- (f) 走の素形 + コーナー + (a)(b)(c)(d)(e) を鍵で join(⛔値の式は組み直し前と同じ)
  create temp table t_r1 on commit drop as
  select r.*,
         c.pos1, c.n1, c.pos2, c.n2, c.pos3, c.n3, c.pos4, c.n4,
         (c.pos1::real / nullif(c.n1, 0)) as p_pos1,
         (c.pos2::real / nullif(c.n2, 0)) as p_pos2,
         (c.pos4::real / nullif(c.n4, 0)) as p_pos4,
         td.m_td, td.sd_td, td.n_td, dn.m_dn, td.m_l3, td.m_l3h, td.sd_l3h,
         (ln(nullif(r.prize1, 0)::numeric) - tk.s_pz / nullif(tk.n_pz, 0))::real as cls_lvl,
         h.hit_car, h.n_car, h.hit_band, h.n_band, h.hit_trk, h.n_trk,
         h.hit_wet, h.n_wet, h.hit_gng, h.n_gng,
         h.runs_this_year, h.season_debut, h.m_bw, h.m_bwm,
         h.gear_hit, h.gear_n, h.start_note_n, h.scratch_n_365, h.prize_local,
         ((dn.s_f3 / nullif(dn.n_f3, 0)) - r.kb_f3)::real as ten_dev,
         mk.day_marks
  from t_run r
  left join t_corner c on c.track = r.track and c.race_date = r.race_date
                      and c.race_no = r.race_no and c.runner_number = r.runner_number
  left join t_day_td  td on td.track = r.track and td.dist_k = r.dist_k
                        and td.gord_k = r.gord_k and td.d_idx = r.d_idx
  left join t_day_dn  dn on dn.track = r.track and dn.dist_k = r.dist_k and dn.d_idx = r.d_idx
  left join t_day_trk tk on tk.track = r.track and tk.d_idx = r.d_idx
  left join t_h1      h  on h.track = r.track and h.race_date = r.race_date
                        and h.race_no = r.race_no and h.runner_number = r.runner_number
  left join t_marks   mk on mk.track = r.track and mk.race_date = r.race_date;
  create index t_r1_key_idx   on t_r1 (track, race_date, race_no, runner_number);
  create index t_r1_horse_idx on t_r1 (horse_key, d_idx);
  analyze t_r1;


  -- 場×日の馬場差(§48 と同じ考え・⛔nar_meta baba_diff は直近 90 日ぶんしか残らないので作り直す)。
  -- その日その場の**勝ち時計** − その場×距離の前日までの平均、の中央値。マイナス= 速い馬場。
  -- ⛔§129c2= 中央値の並べ替えに t_r1 の全列を渡さない= 先に細い 3 列に落とす。
  create temp table t_baba on commit drop as
  select d.track, d.race_date, d.d_idx, d.baba_d, d.n,
         (sum(d.baba_d) over w30 / nullif(count(d.baba_d) over w30, 0))::real as baba_d_30
  from (
    select track, race_date, min(d_idx) as d_idx,
           percentile_cont(0.5) within group (order by dev)::real as baba_d,
           count(*)::int as n
    from (
      select track, race_date, d_idx, (time_sec - m_dn) as dev
      from t_r1 where finish = 1 and time_sec is not null and m_dn is not null
    ) w
    group by 1, 2
  ) d
  window w30 as (partition by d.track order by d.d_idx range between 30 preceding and 1 preceding);
  create index t_baba_idx on t_baba (track, race_date);
  analyze t_baba;

  -- ---------------------------------------------------------- 3) 走ごとの as-of(2 周目)
  -- 時計偏差 tz を作ってから、それを材料にする残差 rz と、馬場差で補正した tza を出す。
  -- rz(残差Z)= tz から「そのレースの条件(場×格×頭数)で普通に出る tz」を引いたもの。
  --   ⚠設計書 B-1 の RZ16 は B/C が SQL の外で逐次に積む状態量。ここでは**同じ考え方を SQL で**=
  --     条件のぶんを前日までの平均で引く(⛔新しい閾値は作らない= 場・race_kind・頭数は既にある列)。
  -- rzin= 同じ場の中で見た残差(場ごとの水準を引いたもの)。
  -- ⛔§129c2= tz は t_r1 の列から式で出る(窓は要らない)。それを材料にする窓だけを**細い表**に掛ける。
  create temp table t_tz on commit drop as
  select r.track, r.race_date, r.race_no, r.runner_number, r.horse_key, r.d_idx,
         coalesce(r.race_kind, '?')  as rk_k,
         coalesce(r.field_size, -1)  as fs_k,
         r.going_ord, r.hit_car,
         ((r.m_td - r.time_sec) / nullif(r.sd_td, 0))::real              as tz,
         ((r.m_td - (r.time_sec - b.baba_d)) / nullif(r.sd_td, 0))::real as tza
  from t_r1 r
  left join t_baba b on b.track = r.track and b.race_date = r.race_date;
  create index t_tz_key_idx on t_tz (track, race_date, race_no, runner_number);
  analyze t_tz;

  -- 場×格×頭数 と 場 の tz を日で束ねてから窓(rz / rzin のもと)
  create temp table t_day_ctx on commit drop as
  select track, rk_k, fs_k, d_idx,
         (sum(s) over w / nullif(sum(n) over w, 0)) as m_tz_ctx   -- ⛔ここで real にしない(丸めを増やさない)
  from (select track, rk_k, fs_k, d_idx, sum(tz::float8) s, count(tz) n from t_tz group by 1, 2, 3, 4) g
  window w as (partition by track, rk_k, fs_k order by d_idx
               range between 365 preceding and 1 preceding);
  create index t_day_ctx_idx on t_day_ctx (track, rk_k, fs_k, d_idx);
  analyze t_day_ctx;

  create temp table t_day_tzt on commit drop as
  select track, d_idx, (sum(s) over w / nullif(sum(n) over w, 0)) as m_tz_trk
  from (select track, d_idx, sum(tz::float8) s, count(tz) n from t_tz group by 1, 2) g
  window w as (partition by track order by d_idx range between 365 preceding and 1 preceding);
  create index t_day_tzt_idx on t_day_tzt (track, d_idx);
  analyze t_day_tzt;

  -- 馬ごとの as-of(道悪と良の tza・キャリアの自己ベスト)= 細い行に窓を掛ける
  create temp table t_h2 on commit drop as
  select x.track, x.race_date, x.race_no, x.runner_number,
         ((x.s_wet / nullif(x.n_wet, 0)) - (x.s_dry / nullif(x.n_dry, 0)))::real as wet_tza_gap,
         x.best_tz_car
  from (
    select y.track, y.race_date, y.race_no, y.runner_number,
           sum(case when y.going_ord >= 1 then y.tza end)   over w as s_wet,
           count(case when y.going_ord >= 1 then y.tza end) over w as n_wet,
           sum(case when y.going_ord = 0 then y.tza end)    over w as s_dry,
           count(case when y.going_ord = 0 then y.tza end)  over w as n_dry,
           max(y.tz) over w as best_tz_car
    from t_tz y
    window w as (partition by y.horse_key order by y.d_idx
                 range between unbounded preceding and 1 preceding)
  ) x;
  create index t_h2_idx on t_h2 (track, race_date, race_no, runner_number);
  analyze t_h2;

  -- 今走の相手の強さ(レース内の前日までのキャリア複勝率の合計と本数)
  create temp table t_fld on commit drop as
  select track, race_date, race_no, sum(hit_car::float8) as s_fld, count(hit_car) as n_fld
  from t_tz group by 1, 2, 3;
  create index t_fld_idx on t_fld (track, race_date, race_no);
  analyze t_fld;

  create temp table t_r2 on commit drop as
  select y.*,
         (y.tz - dc.m_tz_ctx)::real as rz,
         (y.tz - dt.m_tz_trk)::real as rzin,
         h2.wet_tza_gap,
         h2.best_tz_car,
         (y.hit_band - y.hit_car)::real as dist_match,
         (y.hit_gng  - y.hit_car)::real as rgm_gap,
         ((fl.s_fld - coalesce(y.hit_car, 0))
          / nullif(fl.n_fld - (y.hit_car is not null)::int, 0))::real as fld_loo,
         (y.body_weight - y.m_bw)::real  as bw_dev,
         (y.body_weight - y.m_bwm)::real as bw_season_dev,
         y.baba_d_30::real as trk_recent_dmz
  from (
    select r.*, b.baba_d, b.baba_d_30, z.rk_k, z.fs_k, z.tz, z.tza,
           (r.race_last3f - r.m_l3)::real                        as ra_pace,
           ((r.m_l3h - r.last3f) / nullif(r.sd_l3h, 0))::real     as l3z,
           (r.last3f - r.race_last3f)::real                       as l3gap,
           (1 - r.p_pos1)::real                                   as fwd,
           -- ラップ形状(⛔furlongs は 22.8% しか無い= ほとんど NULL のまま)
           (case when jsonb_array_length(r.furlongs) >= 4 then
               ((select avg(v::real) from jsonb_array_elements_text(r.furlongs) with ordinality t(v, o)
                  where o <= jsonb_array_length(r.furlongs) / 2)
              - (select avg(v::real) from jsonb_array_elements_text(r.furlongs) with ordinality t(v, o)
                  where o >  jsonb_array_length(r.furlongs) / 2))::real end) as lappace,
           (case when jsonb_array_length(r.furlongs) >= 4 then
               ((select v::real from jsonb_array_elements_text(r.furlongs) with ordinality t(v, o)
                  where o = jsonb_array_length(r.furlongs))
              - (select min(v::real) from jsonb_array_elements_text(r.furlongs) t(v)))::real end) as lapfade
    from t_r1 r
    left join t_baba b on b.track = r.track and b.race_date = r.race_date
    join t_tz z on z.track = r.track and z.race_date = r.race_date
               and z.race_no = r.race_no and z.runner_number = r.runner_number
  ) y
  left join t_day_ctx dc on dc.track = y.track and dc.rk_k = y.rk_k
                        and dc.fs_k = y.fs_k and dc.d_idx = y.d_idx
  left join t_day_tzt dt on dt.track = y.track and dt.d_idx = y.d_idx
  left join t_h2      h2 on h2.track = y.track and h2.race_date = y.race_date
                        and h2.race_no = y.race_no and h2.runner_number = y.runner_number
  left join t_fld     fl on fl.track = y.track and fl.race_date = y.race_date
                        and fl.race_no = y.race_no;

  -- 前年の成績(暦年でまとめて yr-1 で引く)。⛔2023 年は 2 か月ぶんしか無い= 落とさず NULL/そのまま入れる
  create temp table t_hyr on commit drop as
  select horse_key, yr,
         count(hit3)::real                          as n,
         (sum(hit3) / nullif(count(hit3), 0))::real  as fuku,
         (sum(tz)   / nullif(count(tz), 0))::real    as tz
  from (select horse_key, yr, hit3, tz from t_r2) g
  group by 1, 2;
  create index t_hyr_idx on t_hyr (horse_key, yr);

  create index t_r2_key_idx   on t_r2 (track, race_date, race_no, runner_number);
  create index t_r2_horse_idx on t_r2 (horse_key, d_idx);
  analyze t_r2;

  -- ---------------------------------------------------------- 4) 馬の過去 5 走
  -- ⛔前走= その走の race_date より**厳密に前**の日に走った(finish のある)走のうち最後のもの。
  --   同じ日の他レースは前走にしない(漏洩ゼロ)。取消・除外は前走にしない(§126 と同じ)。
  -- ⛔並びは一意に(race_date, track, race_no, runner_number)= postgrest-offset-needs-unique-order と同じ理由。
  -- ⛔§129c2= 通し番号の並べ替えに t_r2 の全列を渡さない= 細い鍵表で番号を振ってから join する。
  create temp table t_rn on commit drop as
  select track, race_date, race_no, runner_number, horse_key,
         row_number() over (partition by horse_key
                            order by race_date, track, race_no, runner_number) as rn
  from (select track, race_date, race_no, runner_number, horse_key
        from t_r2 where is_run) n;
  create index t_rn_idx on t_rn (track, race_date, race_no, runner_number);
  analyze t_rn;

  create temp table t_self on commit drop as
  select s.horse_key, n.rn, s.race_date, s.d_idx, s.track, s.distance_m, s.jockey, s.going_ord,
         s.finish::real as chaku, s.sa, s.tz, s.rz, s.rzin, s.popularity::real as ninki,
         s.cls_lvl, s.p_pos2, s.p_pos4, s.pos3, s.pos4, s.fwd, s.fld_loo, s.dist_match,
         s.season_debut, s.lappace, s.lapfade, s.ra_pace, s.body_weight::real as bw, s.hit_car,
         s.kb_f3, s.kb_avgf, s.ten_dev, s.kb_gear, s.l3z, s.l3gap,
         s.carried_weight::real as futan, s.tza
  from t_r2 s
  join t_rn n on n.track = s.track and n.race_date = s.race_date
             and n.race_no = s.race_no and n.runner_number = s.runner_number;
  create index t_self_idx on t_self (horse_key, rn);
  analyze t_self;

  -- その走より前(前日まで)に何回走っているか= p1 が指す番号
  create temp table t_np on commit drop as
  select x.track, x.race_date, x.race_no, x.runner_number, x.horse_key, x.d_idx,
         (count(case when x.is_run then 1 end) over w)::int as n_prev,
         (last_value(x.scratched) over w)::real             as p1_scratch
  from (select track, race_date, race_no, runner_number, horse_key, d_idx, is_run, scratched
        from t_r2) x
  window w as (partition by x.horse_key order by x.d_idx
               range between unbounded preceding and 1 preceding);
  create index t_np_key_idx on t_np (track, race_date, race_no, runner_number);
  analyze t_np;

  -- 休養明け(42 日超の間隔)からの走数。⛔閾値 42 は #168 rest_gt42 と同じものを使う(新しく作らない)
  create temp table t_lay on commit drop as
  select horse_key, rn,
         (row_number() over (partition by horse_key, grp order by rn) - 1)::real as since_at
  from (
    select horse_key, rn,
           count(case when is_break then 1 end) over (partition by horse_key order by rn
                 rows between unbounded preceding and current row) as grp
    from (
      select horse_key, rn, d_idx,
             (d_idx - lag(d_idx) over (partition by horse_key order by rn)) > 42 as is_break
      from t_self
    ) a
  ) b;
  create index t_lay_idx on t_lay (horse_key, rn);

  create temp table t_hist on commit drop as
  select n.track, n.race_date, n.race_no, n.runner_number, n.n_prev, n.p1_scratch,
         p1.chaku p1_chaku, p2.chaku p2_chaku, p3.chaku p3_chaku, p4.chaku p4_chaku, p5.chaku p5_chaku,
         p1.sa p1_sa, p2.sa p2_sa, p3.sa p3_sa, p4.sa p4_sa, p5.sa p5_sa,
         p1.tz p1_tz, p2.tz p2_tz, p3.tz p3_tz, p4.tz p4_tz, p5.tz p5_tz,
         p1.rz p1_rz, p2.rz p2_rz, p3.rz p3_rz, p4.rz p4_rz, p5.rz p5_rz,
         p1.rzin p1_rzin, p2.rzin p2_rzin, p3.rzin p3_rzin,
         p1.ninki p1_ninki, p2.ninki p2_ninki, p3.ninki p3_ninki, p4.ninki p4_ninki, p5.ninki p5_ninki,
         p1.cls_lvl p1_cls, p2.cls_lvl p2_cls, p3.cls_lvl p3_cls, p4.cls_lvl p4_cls, p5.cls_lvl p5_cls,
         p1.p_pos2 p1_pos2, p2.p_pos2 p2_pos2, p3.p_pos2 p3_pos2, p4.p_pos2 p4_pos2, p5.p_pos2 p5_pos2,
         p1.p_pos4 p1_pos4, p2.p_pos4 p2_pos4, p3.p_pos4 p3_pos4, p4.p_pos4 p4_pos4, p5.p_pos4 p5_pos4,
         p1.pos4 p1_c4, p2.pos4 p2_c4, p3.pos4 p3_c4, p4.pos4 p4_c4, p5.pos4 p5_c4,
         p1.pos3 p1_c3, p2.pos3 p2_c3, p3.pos3 p3_c3, p4.pos3 p4_c3, p5.pos3 p5_c3,
         p1.fwd p1_fwd, p2.fwd p2_fwd, p3.fwd p3_fwd, p4.fwd p4_fwd, p5.fwd p5_fwd,
         p1.distance_m p1_dist, p2.distance_m p2_dist, p3.distance_m p3_dist,
         p4.distance_m p4_dist, p5.distance_m p5_dist,
         p1.d_idx p1_d, p2.d_idx p2_d, p3.d_idx p3_d, p4.d_idx p4_d, p5.d_idx p5_d,
         p1.track p1_trk, p2.track p2_trk, p3.track p3_trk, p4.track p4_trk, p5.track p5_trk,
         p1.bw p1_bw, p2.bw p2_bw, p3.bw p3_bw, p4.bw p4_bw, p5.bw p5_bw,
         p1.fld_loo p1_fld, p2.fld_loo p2_fld, p3.fld_loo p3_fld,
         p1.dist_match p1_dist_match, p1.season_debut p1_season_debut,
         p1.lappace p1_lappace, p1.lapfade p1_lapfade, p1.ra_pace p1_ra_pace,
         p1.jockey p1_jockey, p1.going_ord p1_going, l1.since_at p1_since,
         p1.kb_f3 p1_f3, p1.kb_avgf p1_avgf, p1.ten_dev p1_ten_dev, p1.kb_gear p1_gear,
         p1.futan p1_futan, p1.tza p1_tza, p2.tza p2_tza, p3.tza p3_tza,
         p1.l3z p1_l3z, p2.l3z p2_l3z, p3.l3z p3_l3z, p4.l3z p4_l3z, p5.l3z p5_l3z, p1.l3gap p1_l3gap
  from t_np n
  left join t_self p1 on p1.horse_key = n.horse_key and p1.rn = n.n_prev
  left join t_self p2 on p2.horse_key = n.horse_key and p2.rn = n.n_prev - 1
  left join t_self p3 on p3.horse_key = n.horse_key and p3.rn = n.n_prev - 2
  left join t_self p4 on p4.horse_key = n.horse_key and p4.rn = n.n_prev - 3
  left join t_self p5 on p5.horse_key = n.horse_key and p5.rn = n.n_prev - 4
  left join t_lay  l1 on l1.horse_key = n.horse_key and l1.rn = n.n_prev;
  create index t_hist_key_idx on t_hist (track, race_date, race_no, runner_number);
  analyze t_hist;

  -- ---------------------------------------------------------- 5) 人・血統・コースの as-of
  -- 1 枚にまとめて 3 つの窓(365 日 / 1095 日 / 全期間)を一度に出す。kind で引き分ける:
  --   jk= 騎手 / jt= 場×騎手 / tr= 調教師 / pr= 調教師×騎手 /
  --   sb= 種牡馬×距離帯 / sg= 種牡馬×馬場 / sa= 種牡馬 / mb,mg,ma= 母父の同じもの /
  --   ow= 馬主 / br= 生産者 / cw= 場×距離×枠 / cf= 場×距離(1角先頭だった走だけ) / cq= 場×距離×1角の位置帯
  -- ⛔窓はすべて `1 preceding` で閉じる= 前日まで。
  create temp table t_ent on commit drop as
  select kind, k1, k2, d_idx, sum(hit3) as sh, sum(win1) as wn, count(hit3) as cn
  from (
    select 'jk'::text kind, jockey k1, ''::text k2, d_idx, hit3, win1 from t_run where jockey is not null
    union all select 'jt', track || '|' || jockey, '', d_idx, hit3, win1 from t_run where jockey is not null
    union all select 'tr', trainer, '', d_idx, hit3, win1 from t_run where trainer is not null
    union all select 'pr', trainer, jockey, d_idx, hit3, win1 from t_run where trainer is not null and jockey is not null
    union all select 'sb', sire, dist_band::text, d_idx, hit3, win1 from t_run where sire is not null
    union all select 'sg', sire, coalesce(going_ord::text, '?'), d_idx, hit3, win1 from t_run where sire is not null
    union all select 'sa', sire, '', d_idx, hit3, win1 from t_run where sire is not null
    union all select 'mb', broodmare_sire, dist_band::text, d_idx, hit3, win1 from t_run where broodmare_sire is not null
    union all select 'mg', broodmare_sire, coalesce(going_ord::text, '?'), d_idx, hit3, win1 from t_run where broodmare_sire is not null
    union all select 'ma', broodmare_sire, '', d_idx, hit3, win1 from t_run where broodmare_sire is not null
    union all select 'ow', owner, '', d_idx, hit3, win1 from t_run where owner is not null
    union all select 'br', breeder, '', d_idx, hit3, win1 from t_run where breeder is not null
    union all select 'cw', track || '|' || distance_m, gate::text, d_idx, hit3, win1 from t_run where gate is not null
  ) u
  group by 1, 2, 3, 4;

  -- コースの「1角で先頭だった走」と「1角の位置帯」は t_r2(コーナー解析ずみ)から足す
  insert into t_ent
  select 'cf', track || '|' || distance_m, '', d_idx, sum(hit3), sum(win1), count(hit3)
  from t_r2 where pos1 = 1 group by track, distance_m, d_idx;
  insert into t_ent
  select 'cq', track || '|' || distance_m, least(3, floor(p_pos1 * 4))::int::text,
         d_idx, sum(hit3), sum(win1), count(hit3)
  from t_r2 where p_pos1 is not null
  group by track, distance_m, least(3, floor(p_pos1 * 4))::int::text, d_idx;

  create temp table t_asof on commit drop as
  select kind, k1, k2, d_idx,
         (sum(sh) over w365  / nullif(sum(cn) over w365, 0))::real  as f365,
         (sum(wn) over w365  / nullif(sum(cn) over w365, 0))::real  as w365r,
         (sum(cn) over w365)::real                                  as n365,
         (sum(sh) over w1095 / nullif(sum(cn) over w1095, 0))::real as f1095,
         (sum(cn) over w1095)::real                                 as n1095,
         (sum(sh) over wall  / nullif(sum(cn) over wall, 0))::real  as fall,
         (sum(cn) over wall)::real                                  as nall
  from t_ent
  window w365  as (partition by kind, k1, k2 order by d_idx range between 365 preceding and 1 preceding),
         w1095 as (partition by kind, k1, k2 order by d_idx range between 1095 preceding and 1 preceding),
         wall  as (partition by kind, k1, k2 order by d_idx range between unbounded preceding and 1 preceding);
  create index t_asof_idx on t_asof (kind, k1, k2, d_idx);
  analyze t_asof;

  -- ---------------------------------------------------------- 6) 場×日のバイアス
  -- ⛔ρ(順位相関)の代わりに「レース内の割合どうし」の相関を sum から出す(移動窓で順位は組めないため)。
  --   枠= gate/頭数・着= finish/頭数・前= 1角順位/そのコーナーの頭数・4角= 最終コーナー順位/同頭数。
  --   どれも 0〜1 の順位そのものなので順位相関に近い。baba_io_365= 最終コーナーの位置と着順の相関。
  create temp table t_bday on commit drop as
  select track, d_idx,
         count(*) filter (where g is not null and f is not null)                      as n_gf,
         sum(g) filter (where f is not null)  as sg, sum(f) filter (where g is not null) as sf,
         sum(g * f) as sgf, sum(g * g) filter (where f is not null) as sgg,
         sum(f * f) filter (where g is not null) as sff,
         count(*) filter (where q is not null and f is not null)                      as n_qf,
         sum(q) filter (where f is not null)  as sq, sum(f) filter (where q is not null) as sf2,
         sum(q * f) as sqf, sum(q * q) filter (where f is not null) as sqq,
         sum(f * f) filter (where q is not null) as sff2,
         count(*) filter (where c is not null and f is not null)                      as n_cf,
         sum(c) filter (where f is not null)  as sc, sum(f) filter (where c is not null) as sf3,
         sum(c * f) as scf, sum(c * c) filter (where f is not null) as scc,
         sum(f * f) filter (where c is not null) as sff3
  from (
    select track, d_idx,
           (gate::real   / nullif(field_size, 0)) as g,
           (finish::real / nullif(field_size, 0)) as f,
           p_pos1                                 as q,
           p_pos4                                 as c
    from t_r2 where is_run
  ) x
  group by 1, 2;

  create temp table t_bias on commit drop as
  select track, d_idx,
         ((n30 * sgf30 - sg30 * sf30) / nullif(sqrt(greatest(n30 * sgg30 - sg30 ^ 2, 0))
                                             * sqrt(greatest(n30 * sff30 - sf30 ^ 2, 0)), 0))::real as waku_bias_30,
         ((n365 * sgf365 - sg365 * sf365) / nullif(sqrt(greatest(n365 * sgg365 - sg365 ^ 2, 0))
                                             * sqrt(greatest(n365 * sff365 - sf365 ^ 2, 0)), 0))::real as waku_bias_365,
         ((m30 * sqf30 - sq30 * sf230) / nullif(sqrt(greatest(m30 * sqq30 - sq30 ^ 2, 0))
                                             * sqrt(greatest(m30 * sff230 - sf230 ^ 2, 0)), 0))::real as pace_bias_30,
         ((m365 * sqf365 - sq365 * sf2365) / nullif(sqrt(greatest(m365 * sqq365 - sq365 ^ 2, 0))
                                             * sqrt(greatest(m365 * sff2365 - sf2365 ^ 2, 0)), 0))::real as pace_bias_365,
         ((c365 * scf365 - sc365 * sf3365) / nullif(sqrt(greatest(c365 * scc365 - sc365 ^ 2, 0))
                                             * sqrt(greatest(c365 * sff3365 - sf3365 ^ 2, 0)), 0))::real as baba_io_365
  from (
    select track, d_idx,
           sum(n_gf) over w30 n30, sum(sg) over w30 sg30, sum(sf) over w30 sf30,
           sum(sgf) over w30 sgf30, sum(sgg) over w30 sgg30, sum(sff) over w30 sff30,
           sum(n_gf) over w365 n365, sum(sg) over w365 sg365, sum(sf) over w365 sf365,
           sum(sgf) over w365 sgf365, sum(sgg) over w365 sgg365, sum(sff) over w365 sff365,
           sum(n_qf) over w30 m30, sum(sq) over w30 sq30, sum(sf2) over w30 sf230,
           sum(sqf) over w30 sqf30, sum(sqq) over w30 sqq30, sum(sff2) over w30 sff230,
           sum(n_qf) over w365 m365, sum(sq) over w365 sq365, sum(sf2) over w365 sf2365,
           sum(sqf) over w365 sqf365, sum(sqq) over w365 sqq365, sum(sff2) over w365 sff2365,
           sum(n_cf) over w365 c365, sum(sc) over w365 sc365, sum(sf3) over w365 sf3365,
           sum(scf) over w365 scf365, sum(scc) over w365 scc365, sum(sff3) over w365 sff3365
    from t_bday
    window w30  as (partition by track order by d_idx range between 30 preceding and 1 preceding),
           w365 as (partition by track order by d_idx range between 365 preceding and 1 preceding)
  ) c;
  create index t_bias_idx on t_bias (track, d_idx);
  analyze t_bias;

  -- ---------------------------------------------------------- 7) 乗り替わり(§126)を as-of で組み直す
  -- ⛔nar_jc_pairs / nar_jc_trainer_jockey は**全期間**の集計= 未来を含む(設計書 I-7)。
  --   同じ定義(乗替= 前走と騎手が違う / 再コンビ= 以前に乗ったことがある / 上下= その場の複勝率の差 ±5pt・
  --   どちらかが 20 騎乗未満なら判定なし)を、**その走の前日まで**で組み直す。
  create temp table t_jc on commit drop as
  select r.track, r.race_date, r.race_no, r.runner_number, r.d_idx, r.horse_key,
         r.jockey, r.trainer, h.p1_jockey, r.hit3, r.win1,
         case when h.p1_jockey is null then null else (h.p1_jockey <> r.jockey) end as changed,
         case when h.p1_jockey is null or h.p1_jockey = r.jockey then null
              else (r.jockey = any (array_remove(array_agg(r.jockey) over w, null))) end as rejoin
  from t_r2 r
  join t_hist h on h.track = r.track and h.race_date = r.race_date
               and h.race_no = r.race_no and h.runner_number = r.runner_number
  window w as (partition by r.horse_key order by r.d_idx range between unbounded preceding and 1 preceding);
  create index t_jc_key_idx on t_jc (track, race_date, race_no, runner_number);
  analyze t_jc;

  -- 乗替ペア A→B(場ごと)と 厩舎×騎手(乗替時)の as-of 集計
  create temp table t_jcp on commit drop as
  select track, p1_jockey as fj, jockey as tj, d_idx,
         (sum(sh) over w / nullif(sum(cn) over w, 0))::real as hit,
         (sum(cn) over w)::real as n
  from (select track, p1_jockey, jockey, d_idx, sum(hit3) sh, count(hit3) cn
        from t_jc where changed group by 1, 2, 3, 4) g
  window w as (partition by track, p1_jockey, jockey order by d_idx
               range between unbounded preceding and 1 preceding);
  create index t_jcp_idx on t_jcp (track, fj, tj, d_idx);

  create temp table t_jct on commit drop as
  select track, trainer, jockey, d_idx,
         (sum(sh) over w / nullif(sum(cn) over w, 0))::real as hit,
         (sum(cn) over w)::real as n
  from (select track, trainer, jockey, d_idx, sum(hit3) sh, count(hit3) cn
        from t_jc where changed and trainer is not null group by 1, 2, 3, 4) g
  window w as (partition by track, trainer, jockey order by d_idx
               range between unbounded preceding and 1 preceding);
  create index t_jct_idx on t_jct (track, trainer, jockey, d_idx);
  analyze t_jcp; analyze t_jct;

  -- ---------------------------------------------------------- 8) ④ の小さい材料(疾病・能検・せり・制裁・売上)
  -- ⛔疾病は**公表日**(reported_date。無ければ event_date)がその走の前より古いものだけ数える
  create temp table t_ill on commit drop as
  select (horse_name || '|' || coalesce(birth_date::text, '')) as horse_key,
         coalesce(reported_date, event_date) as kdate
  from public.nar_horse_health_events
  where horse_name is not null and coalesce(reported_date, event_date) is not null;
  create index t_ill_idx on t_ill (horse_key, kdate);

  -- 能力検査(§117 の索引・13 地区)。⛔馬名だけの鍵(同名馬は取り違えうる)
  create temp table t_noken on commit drop as
  select k.key as horse_name, (e->>'date')::date as ndate,
         (case when e->>'time' ~ '^[0-9]+:[0-9.]+$'
                 then split_part(e->>'time', ':', 1)::real * 60 + split_part(e->>'time', ':', 2)::real
               when e->>'time' ~ '^[0-9.]+$' then (e->>'time')::real end) as nsec
  from (select value->'horses' as h from public.nar_meta where key = 'noken_index') m,
       lateral jsonb_each(m.h) k(key, val),
       lateral jsonb_array_elements(k.val) e
  where jsonb_typeof(m.h) = 'object' and (e->>'date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$';
  create index t_noken_idx on t_noken (horse_name, ndate);

  -- せり(§54.6)。⛔出品時点の申告= その走より前のものだけ
  create temp table t_sale on commit drop as
  select (horse_name || '|' || coalesce(birth_date::text, '')) as horse_key,
         auction_date, price
  from public.auction_sales
  where horse_name is not null and auction_date is not null and price is not null;
  create index t_sale_idx on t_sale (horse_key, auction_date);

  -- 制裁(§111)。⛔件数だけ。価値判断の語は入れない
  create temp table t_pen on commit drop as
  select person_name, race_date from public.nar_penalties
  where person_kind = 'jockey' and person_name is not null and race_date is not null;
  create index t_pen_idx on t_pen (person_name, race_date);

  -- 売上(§54.1)。⛔当日は発走前に確定しないので**前日までの場平均**だけを使う
  create temp table t_sales on commit drop as
  select track, d_idx,
         (sum(v) over w30  / nullif(sum(c) over w30, 0))::real  as avg30,
         (sum(v) over w365 / nullif(sum(c) over w365, 0))::real as avg365
  from (select track, (race_date - date '2000-01-01')::int as d_idx,
               net_votes::numeric as v, greatest(races, 1)::numeric as c
        from public.nar_sales_daily where net_votes is not null) g
  window w30  as (partition by track order by d_idx range between 30 preceding and 1 preceding),
         w365 as (partition by track order by d_idx range between 365 preceding and 1 preceding);
  create index t_sales_idx on t_sales (track, d_idx);

  -- ---------------------------------------------------------- 8b) レース内の順位・合計(⛔細い表で)
  -- ⛔§129c2= percent_rank と レース内合計の入力に `q.*`(約 250 列)を渡すと並べ替えが溢れる。
  --   材料は全部 t_hist(と prize_local)から出るので、**鍵 + 12 列**の細い表に窓を掛けて鍵で戻す。
  --   ⛔値は組み直し前とまったく同じ(同じ式・同じ窓)。
  create temp table t_rank on commit drop as
  select k.track, k.race_date, k.race_no, k.runner_number,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.fukusho_rate_5) as r_fuku5_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.avg_time_z_3)   as r_timez_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.p1_sa)          as r_pchakusa_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.avg_time_za_3)  as r_timeza_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.avg_rz_3)       as r_rz_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.best_rz_5)      as r_bestrz_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.prize_local)    as r_prize_pct,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.p1_ten_dev)     as ten_rank,
         percent_rank() over (partition by k.track, k.race_date, k.race_no order by k.avg_l3z_3)      as r_l3z_pct,
         (sum(k.qpts) over wr)::real                          as race_qsum,
         max(k.qpts) over wr                                  as race_qmax,
         (count(*) filter (where k.style = 0)  over wr)::real  as lead_n,
         (count(*) filter (where k.style <= 1) over wr)::real  as n_front,
         (count(k.style) over wr)::real                        as n_style
  from (
    select h.track, h.race_date, h.race_no, h.runner_number, h.p1_sa, h.p1_ten_dev, pl.prize_local,
           public.nar_avg5(h.p1_tz, h.p2_tz, h.p3_tz, null, null)    as avg_time_z_3,
           public.nar_avg5(h.p1_tza, h.p2_tza, h.p3_tza, null, null) as avg_time_za_3,
           public.nar_avg5(h.p1_rz, h.p2_rz, h.p3_rz, null, null)    as avg_rz_3,
           greatest(h.p1_rz, h.p2_rz, h.p3_rz, h.p4_rz, h.p5_rz)     as best_rz_5,
           public.nar_avg5(h.p1_l3z, h.p2_l3z, h.p3_l3z, null, null) as avg_l3z_3,
           (coalesce((h.p1_chaku <= 3)::int, 0) + coalesce((h.p2_chaku <= 3)::int, 0)
            + coalesce((h.p3_chaku <= 3)::int, 0) + coalesce((h.p4_chaku <= 3)::int, 0)
            + coalesce((h.p5_chaku <= 3)::int, 0))
             / nullif(public.nar_cnt5(h.p1_chaku, h.p2_chaku, h.p3_chaku, h.p4_chaku, h.p5_chaku), 0)
                                                                     as fukusho_rate_5,
           public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) as qpts,
           (case when public.nar_cnt5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) < 2 then null
                 when (coalesce((h.p1_fwd >= 0.8)::int, 0) + coalesce((h.p2_fwd >= 0.8)::int, 0)
                     + coalesce((h.p3_fwd >= 0.8)::int, 0) + coalesce((h.p4_fwd >= 0.8)::int, 0)
                     + coalesce((h.p5_fwd >= 0.8)::int, 0)) * 2
                      > public.nar_cnt5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) then 0
                 when 1 - public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) <= 0.4 then 1
                 when 1 - public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) <= 0.7 then 2
                 else 3 end)::real                                   as style
    from t_hist h
    join (select track, race_date, race_no, runner_number, prize_local from t_r2) pl
      on pl.track = h.track and pl.race_date = h.race_date
     and pl.race_no = h.race_no and pl.runner_number = h.runner_number
  ) k
  window wr as (partition by k.track, k.race_date, k.race_no);
  create index t_rank_idx on t_rank (track, race_date, race_no, runner_number);
  analyze t_rank;
  -- ---------------------------------------------------------- 9) 1 枚に組み立てて入れる
  insert into public.nar_ai_feat_run (
    track, race_date, race_no, runner_number, horse_key, finish, finish_note, popularity, y_top3, y_win,
    prev_chakujun, prev_chakusa, prev_corner4, prev_ninki, avg_chakujun_3, fukusho_rate_5,
    days_since_prev, dist_change, track_change, futan, futan_diff, prev_bataiju, barei, seibetsu,
    tosu, wakuban, kyori, keibajo, prize1_log,
    dist_fukusho_rate, dist_n, kishu_fuku_1y, kishu_n_1y, chokyo_fuku_1y, chokyo_n_1y,
    sire_fuku_band, sire_n_band, uma_place_fuku, uma_place_n, norikae, prev_time_z, avg_time_z_3,
    prev_pos2_rate, prev_pos4_rate, avg_pos2_3, class_diff, prev_ra_pace,
    race_month, hasso_hour, r_fuku5_pct, r_timez_pct, r_pchakusa_pct,
    waku_bias_365, waku_bias_30, pace_bias_365, pace_bias_30,
    prev_time_za, avg_time_za_3, r_timeza_pct,
    runs_this_year, season_debut, prevyear_fukusho, prevyear_timez, prevyear_n,
    p1_chaku, p2_chaku, p3_chaku, p4_chaku, p5_chaku,
    p1_sa, p2_sa, p3_sa, p4_sa, p5_sa,
    p1_tz, p2_tz, p3_tz, p4_tz, p5_tz,
    p1_pos2, p2_pos2, p3_pos2, p4_pos2, p5_pos2,
    p1_pos4, p2_pos4, p3_pos4, p4_pos4, p5_pos4,
    p1_ninki, p2_ninki, p3_ninki, p4_ninki, p5_ninki,
    p1_dkyori, p2_dkyori, p3_dkyori, p4_dkyori, p5_dkyori,
    p1_cls, p2_cls, p3_cls, p4_cls, p5_cls,
    p1_gap, p2_gap, p3_gap, p4_gap, p5_gap,
    p1_same, p2_same, p3_same, p4_same, p5_same,
    best_tz_5, worst_tz_5, std_tz_5, best_chaku_5, n_tz_5,
    p1_rz, p2_rz, p3_rz, p4_rz, p5_rz, p1_rzin, p2_rzin, p3_rzin,
    avg_rz_3, avg_rz_5, best_rz_5, std_rz_5, avg_rzin_3, n_rz_5, r_rz_pct, r_bestrz_pct,
    opp_str_now, p1_fld, p2_fld, p3_fld, avg_fld_3, relief_3,
    bataiju_now, bataiju_diff, baba_now, wet_n, wet_fuku, wet_tza_gap, p1_kishu_fuku, kishu_delta,
    bw_slope_5, bw_dev, p1_season_debut, pair_fuku_3y, pair_n_3y, pair_vs_kishu,
    p1_lappace, p1_lapfade, mf_fuku_band, mf_n_band,
    sire_rgm_gap, mf_rgm_gap, rgm_gap, rgm_n, trk_recent_dmz, dist_match, p1_dist_match,
    pl_theta, pl_n, jk_beta, tr_gamma, r_plth_pct, pl_gap_top, jk_beta_delta,
    bw_season_dev, sex_summer, rest_leq3, rest_gt42, oshi_nose2, oshi_nose4, oshi_rate,
    c4lead_lost_rate, mak_gain_m3, pos2_var5, fade34_rate5,
    qpts, race_qsum, race_qmax, minarai_now, since_layoff, prev_best5, bounce_risk, has_hist,
    ten_kb, ten_kb_dev, avg_f, ten_rank,
    p1_l3z, p2_l3z, p3_l3z, avg_l3z_3, best_l3z_5, r_l3z_pct, p1_l3gap,
    style, avg_pos_5, lead_n, n_front, front_ratio,
    jc_changed, jc_rejoin, jc_tier, jc_pair_n, jc_pair_hit, jc_tj_n, jc_tj_hit,
    gear_now, gear_first, gear_off, gear_n, gear_hit, start_note_n,
    prize_local, prize_local_log, r_prize_pct, baba_diff_d, baba_io_365,
    course_waku_hit, course_front_win, course_pos_hit,
    ill_n_365, ill_last_days, scratch_n_365, p1_scratch,
    noken_days, noken_time, is_noken_debut,
    owner_hit, owner_n, breeder_hit, breeder_n, sale_price, sale_year, jockey_penalty_90d,
    race_sales, sales_vs_venue_avg, updated_at)
  select
    w.track, w.race_date, w.race_no, w.runner_number, w.horse_key, w.finish, w.finish_note, w.popularity,
    w.y_top3, w.y_win,
    w.p1_chaku, w.p1_sa, w.p1_c4, w.p1_ninki,
    public.nar_avg5(w.p1_chaku, w.p2_chaku, w.p3_chaku, null, null),
    (coalesce((w.p1_chaku <= 3)::int, 0) + coalesce((w.p2_chaku <= 3)::int, 0)
     + coalesce((w.p3_chaku <= 3)::int, 0) + coalesce((w.p4_chaku <= 3)::int, 0)
     + coalesce((w.p5_chaku <= 3)::int, 0))
      / nullif(public.nar_cnt5(w.p1_chaku, w.p2_chaku, w.p3_chaku, w.p4_chaku, w.p5_chaku), 0),
    w.d_idx - w.p1_d, w.kyori - w.p1_dist, (w.track <> w.p1_trk)::int,
    w.futan, w.futan - w.p1_futan, w.p1_bw, w.barei, w.seibetsu,
    w.tosu, w.wakuban, w.kyori, w.keibajo, w.prize1_log,
    w.dist_fukusho_rate, w.dist_n, w.kishu_fuku_1y, w.kishu_n_1y, w.chokyo_fuku_1y, w.chokyo_n_1y,
    w.sire_fuku_band, w.sire_n_band, w.uma_place_fuku, w.uma_place_n, w.norikae, w.p1_tz,
    public.nar_avg5(w.p1_tz, w.p2_tz, w.p3_tz, null, null),
    w.p1_pos2, w.p1_pos4, public.nar_avg5(w.p1_pos2::real, w.p2_pos2::real, w.p3_pos2::real, null, null),
    w.cls_lvl - w.p1_cls, w.p1_ra_pace,
    w.race_month, w.hasso_hour,
    case when w.fukusho_rate_5 is null then null else w.r_fuku5_pct end,
    case when w.avg_time_z_3   is null then null else w.r_timez_pct  end,
    case when w.p1_sa          is null then null else w.r_pchakusa_pct end,
    w.waku_bias_365, w.waku_bias_30, w.pace_bias_365, w.pace_bias_30,
    w.p1_tza, public.nar_avg5(w.p1_tza, w.p2_tza, w.p3_tza, null, null),
    case when w.avg_time_za_3 is null then null else w.r_timeza_pct end,
    w.runs_this_year, w.season_debut, w.prevyear_fukusho, w.prevyear_timez, w.prevyear_n,
    w.p1_chaku, w.p2_chaku, w.p3_chaku, w.p4_chaku, w.p5_chaku,
    w.p1_sa, w.p2_sa, w.p3_sa, w.p4_sa, w.p5_sa,
    w.p1_tz, w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz,
    w.p1_pos2, w.p2_pos2, w.p3_pos2, w.p4_pos2, w.p5_pos2,
    w.p1_pos4, w.p2_pos4, w.p3_pos4, w.p4_pos4, w.p5_pos4,
    w.p1_ninki, w.p2_ninki, w.p3_ninki, w.p4_ninki, w.p5_ninki,
    w.kyori - w.p1_dist, w.kyori - w.p2_dist, w.kyori - w.p3_dist,
    w.kyori - w.p4_dist, w.kyori - w.p5_dist,
    w.p1_cls, w.p2_cls, w.p3_cls, w.p4_cls, w.p5_cls,
    w.d_idx - w.p1_d, w.d_idx - w.p2_d, w.d_idx - w.p3_d, w.d_idx - w.p4_d, w.d_idx - w.p5_d,
    (w.track = w.p1_trk)::int, (w.track = w.p2_trk)::int, (w.track = w.p3_trk)::int,
    (w.track = w.p4_trk)::int, (w.track = w.p5_trk)::int,
    greatest(w.p1_tz, w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz),
    least(w.p1_tz, w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz),
    public.nar_std5(w.p1_tz, w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz),
    least(w.p1_chaku, w.p2_chaku, w.p3_chaku, w.p4_chaku, w.p5_chaku),
    public.nar_cnt5(w.p1_tz, w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz),
    w.p1_rz, w.p2_rz, w.p3_rz, w.p4_rz, w.p5_rz, w.p1_rzin, w.p2_rzin, w.p3_rzin,
    public.nar_avg5(w.p1_rz, w.p2_rz, w.p3_rz, null, null),
    public.nar_avg5(w.p1_rz, w.p2_rz, w.p3_rz, w.p4_rz, w.p5_rz),
    greatest(w.p1_rz, w.p2_rz, w.p3_rz, w.p4_rz, w.p5_rz),
    public.nar_std5(w.p1_rz, w.p2_rz, w.p3_rz, w.p4_rz, w.p5_rz),
    public.nar_avg5(w.p1_rzin, w.p2_rzin, w.p3_rzin, null, null),
    public.nar_cnt5(w.p1_rz, w.p2_rz, w.p3_rz, w.p4_rz, w.p5_rz),
    case when w.avg_rz_3  is null then null else w.r_rz_pct end,
    case when w.best_rz_5 is null then null else w.r_bestrz_pct end,
    w.opp_str_now, w.p1_fld, w.p2_fld, w.p3_fld, w.avg_fld_3, w.avg_fld_3 - w.opp_str_now,
    w.bataiju_now, w.bataiju_diff, w.baba_now, w.wet_n, w.wet_fuku, w.wet_tza_gap,
    w.p1_kishu_fuku, w.kishu_fuku_1y - w.p1_kishu_fuku,
    public.nar_slope5(w.p1_bw, w.p2_bw, w.p3_bw, w.p4_bw, w.p5_bw), w.bw_dev, w.p1_season_debut,
    w.pair_fuku_3y, w.pair_n_3y, w.pair_vs_kishu,
    w.p1_lappace, w.p1_lapfade, w.mf_fuku_band, w.mf_n_band,
    w.sire_rgm_gap, w.mf_rgm_gap, w.rgm_gap, w.rgm_n, w.trk_recent_dmz, w.dist_match, w.p1_dist_match,
    null, null, null, null, null, null, null,
    w.bw_season_dev,
    (case when w.seibetsu is null then null
          when w.seibetsu = 1 and w.race_month between 6 and 8 then 1 else 0 end),
    (case when w.p1_gap is null then null when w.p1_gap <= 28 then 1 else 0 end),
    (case when w.p1_gap is null then null when w.p1_gap >  42 then 1 else 0 end),
    w.oshi_nose2, w.oshi_nose4,
    w.oshi_nose4 / nullif(public.nar_cnt5(w.p1_chaku, w.p2_chaku, w.p3_chaku, w.p4_chaku, w.p5_chaku), 0),
    w.c4lead_lost / nullif(w.c4lead_n, 0),
    public.nar_avg5((w.p1_c4 - w.p1_chaku)::real, (w.p2_c4 - w.p2_chaku)::real,
                    (w.p3_c4 - w.p3_chaku)::real, null, null),
    public.nar_std5(w.p1_pos2::real, w.p2_pos2::real, w.p3_pos2::real, w.p4_pos2::real, w.p5_pos2::real),
    w.fade34_down / nullif(w.fade34_n, 0),
    w.qpts, w.race_qsum, w.race_qmax,
    (case when w.day_marks > 0 then (w.weight_mark is not null)::int end),
    (case when w.p1_d is null then null when w.p1_gap > 42 then 0 else w.p1_since + 1 end),
    greatest(w.p1_tz, w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz) - w.best_tz_car,
    w.p1_tz - public.nar_avg5(w.p2_tz, w.p3_tz, w.p4_tz, w.p5_tz, null),
    (w.n_prev > 0)::int,
    w.p1_f3, w.p1_ten_dev, w.p1_avgf,
    case when w.p1_ten_dev is null then null else w.ten_rank end,
    w.p1_l3z, w.p2_l3z, w.p3_l3z, w.avg_l3z_3,
    greatest(w.p1_l3z, w.p2_l3z, w.p3_l3z, w.p4_l3z, w.p5_l3z),
    case when w.avg_l3z_3 is null then null else w.r_l3z_pct end,
    w.p1_l3gap,
    w.style, 1 - w.qpts, w.lead_n, w.n_front, w.n_front / nullif(w.n_style, 0),
    w.jc_changed, w.jc_rejoin, w.jc_tier, w.jc_pair_n, w.jc_pair_hit, w.jc_tj_n, w.jc_tj_hit,
    w.gear_now,
    (case when w.gear_now = 1 then (w.gear_n = 0)::int end),
    (case when w.gear_now = 0 and w.p1_gear is not null then 1 when w.gear_now is not null then 0 end),
    w.gear_n, w.gear_hit, w.start_note_n,
    w.prize_local, ln(greatest(coalesce(w.prize_local, 0), 0)::numeric + 1)::real,
    case when w.prize_local is null then null else w.r_prize_pct end,
    w.baba_diff_d, w.baba_io_365, w.course_waku_hit, w.course_front_win, w.course_pos_hit,
    w.ill_n_365, w.ill_last_days, w.scratch_n_365, w.p1_scratch,
    w.noken_days, w.noken_time,
    (case when w.noken_days is null then null else (w.n_prev = 0)::int end),
    w.owner_hit, w.owner_n, w.breeder_hit, w.breeder_n, w.sale_price, w.sale_year,
    w.jockey_penalty_90d, w.race_sales, w.sales_vs_venue_avg, now()
  from (
    -- レース内の順位・合計は t_rank(細い表)で先に出してある= ここは鍵で join するだけ(§129c2)
    select q.*, rk.r_fuku5_pct, rk.r_timez_pct, rk.r_pchakusa_pct, rk.r_timeza_pct,
           rk.r_rz_pct, rk.r_bestrz_pct, rk.r_prize_pct, rk.ten_rank, rk.r_l3z_pct,
           rk.race_qsum, rk.race_qmax, rk.lead_n, rk.n_front, rk.n_style
    from (
      select z.*, cq.f365 as course_pos_hit
      from (
        select
          r.track, r.race_date, r.race_no, r.runner_number, r.horse_key, r.finish, r.finish_note,
          r.popularity, r.d_idx, r.weight_mark, r.day_marks, r.cls_lvl, r.best_tz_car,
          (case when r.finish is null then null when r.finish <= 3 then 1 else 0 end)::smallint as y_top3,
          (case when r.finish is null then null when r.finish = 1  then 1 else 0 end)::smallint as y_win,
          r.age::real as barei, r.seibetsu, r.field_size::real as tosu, r.gate::real as wakuban,
          r.distance_m::real as kyori, r.keibajo, r.race_month, r.hasso_hour,
          r.carried_weight::real as futan, r.body_weight::real as bataiju_now,
          r.body_weight_change::real as bataiju_diff, r.going_ord as baba_now,
          ln(nullif(r.prize1, 0)::numeric)::real as prize1_log,
          r.hit_band as dist_fukusho_rate, r.n_band as dist_n,
          r.hit_trk as uma_place_fuku, r.n_trk as uma_place_n,
          r.hit_wet as wet_fuku, r.n_wet as wet_n, r.wet_tza_gap,
          r.rgm_gap, r.n_gng as rgm_n, r.dist_match, r.trk_recent_dmz,
          r.bw_dev, r.bw_season_dev, r.fld_loo as opp_str_now,
          r.runs_this_year, r.season_debut, r.prize_local, r.scratch_n_365,
          r.gear_hit, r.gear_n, r.start_note_n,
          (case when r.kb_row then (r.kb_gear is not null)::int end)::real as gear_now,
          h.n_prev, h.p1_scratch, h.p1_since,
          h.p1_chaku, h.p2_chaku, h.p3_chaku, h.p4_chaku, h.p5_chaku,
          h.p1_sa, h.p2_sa, h.p3_sa, h.p4_sa, h.p5_sa,
          h.p1_tz, h.p2_tz, h.p3_tz, h.p4_tz, h.p5_tz,
          h.p1_rz, h.p2_rz, h.p3_rz, h.p4_rz, h.p5_rz, h.p1_rzin, h.p2_rzin, h.p3_rzin,
          h.p1_ninki, h.p2_ninki, h.p3_ninki, h.p4_ninki, h.p5_ninki,
          h.p1_cls, h.p2_cls, h.p3_cls, h.p4_cls, h.p5_cls,
          h.p1_pos2, h.p2_pos2, h.p3_pos2, h.p4_pos2, h.p5_pos2,
          h.p1_pos4, h.p2_pos4, h.p3_pos4, h.p4_pos4, h.p5_pos4,
          h.p1_c3, h.p2_c3, h.p3_c3, h.p4_c3, h.p5_c3,
          h.p1_c4, h.p2_c4, h.p3_c4, h.p4_c4, h.p5_c4,
          h.p1_dist, h.p2_dist, h.p3_dist, h.p4_dist, h.p5_dist,
          h.p1_d, h.p2_d, h.p3_d, h.p4_d, h.p5_d,
          h.p1_trk, h.p2_trk, h.p3_trk, h.p4_trk, h.p5_trk,
          h.p1_bw, h.p2_bw, h.p3_bw, h.p4_bw, h.p5_bw,
          h.p1_fld, h.p2_fld, h.p3_fld, h.p1_dist_match, h.p1_season_debut,
          h.p1_lappace, h.p1_lapfade, h.p1_ra_pace, h.p1_futan, h.p1_gear,
          h.p1_tza, h.p2_tza, h.p3_tza, h.p1_f3, h.p1_avgf, h.p1_ten_dev,
          h.p1_l3z, h.p2_l3z, h.p3_l3z, h.p4_l3z, h.p5_l3z, h.p1_l3gap,
          public.nar_avg5(h.p1_l3z, h.p2_l3z, h.p3_l3z, null, null)   as avg_l3z_3,
          (r.d_idx - h.p1_d)::real as p1_gap,
          public.nar_avg5(h.p1_tz, h.p2_tz, h.p3_tz, null, null)    as avg_time_z_3,
          public.nar_avg5(h.p1_tza, h.p2_tza, h.p3_tza, null, null) as avg_time_za_3,
          public.nar_avg5(h.p1_rz, h.p2_rz, h.p3_rz, null, null)    as avg_rz_3,
          greatest(h.p1_rz, h.p2_rz, h.p3_rz, h.p4_rz, h.p5_rz)     as best_rz_5,
          public.nar_avg5(h.p1_fld, h.p2_fld, h.p3_fld, null, null) as avg_fld_3,
          (coalesce((h.p1_chaku <= 3)::int, 0) + coalesce((h.p2_chaku <= 3)::int, 0)
           + coalesce((h.p3_chaku <= 3)::int, 0) + coalesce((h.p4_chaku <= 3)::int, 0)
           + coalesce((h.p5_chaku <= 3)::int, 0))
            / nullif(public.nar_cnt5(h.p1_chaku, h.p2_chaku, h.p3_chaku, h.p4_chaku, h.p5_chaku), 0)
                                                                    as fukusho_rate_5,
          public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) as qpts,
          least(3, floor((1 - public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd)) * 4))
            ::int::text                                             as qband,
          r.track || '|' || r.distance_m                            as trk_dist,
          (case when public.nar_cnt5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) < 2 then null
                when (coalesce((h.p1_fwd >= 0.8)::int, 0) + coalesce((h.p2_fwd >= 0.8)::int, 0)
                    + coalesce((h.p3_fwd >= 0.8)::int, 0) + coalesce((h.p4_fwd >= 0.8)::int, 0)
                    + coalesce((h.p5_fwd >= 0.8)::int, 0)) * 2
                     > public.nar_cnt5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) then 0
                when 1 - public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) <= 0.4 then 1
                when 1 - public.nar_avg5(h.p1_fwd, h.p2_fwd, h.p3_fwd, h.p4_fwd, h.p5_fwd) <= 0.7 then 2
                else 3 end)::real                                   as style,
          (coalesce((h.p1_chaku = 2 and h.p1_sa <= 0.05)::int, 0)
           + coalesce((h.p2_chaku = 2 and h.p2_sa <= 0.05)::int, 0)
           + coalesce((h.p3_chaku = 2 and h.p3_sa <= 0.05)::int, 0)
           + coalesce((h.p4_chaku = 2 and h.p4_sa <= 0.05)::int, 0)
           + coalesce((h.p5_chaku = 2 and h.p5_sa <= 0.05)::int, 0))::real as oshi_nose2,
          (coalesce((h.p1_chaku <= 4 and h.p1_sa <= 0.30)::int, 0)
           + coalesce((h.p2_chaku <= 4 and h.p2_sa <= 0.30)::int, 0)
           + coalesce((h.p3_chaku <= 4 and h.p3_sa <= 0.30)::int, 0)
           + coalesce((h.p4_chaku <= 4 and h.p4_sa <= 0.30)::int, 0)
           + coalesce((h.p5_chaku <= 4 and h.p5_sa <= 0.30)::int, 0))::real as oshi_nose4,
          (coalesce((h.p1_c4 = 1)::int, 0) + coalesce((h.p2_c4 = 1)::int, 0)
           + coalesce((h.p3_c4 = 1)::int, 0) + coalesce((h.p4_c4 = 1)::int, 0)
           + coalesce((h.p5_c4 = 1)::int, 0))::real as c4lead_n,
          (coalesce((h.p1_c4 = 1 and h.p1_chaku > 1)::int, 0)
           + coalesce((h.p2_c4 = 1 and h.p2_chaku > 1)::int, 0)
           + coalesce((h.p3_c4 = 1 and h.p3_chaku > 1)::int, 0)
           + coalesce((h.p4_c4 = 1 and h.p4_chaku > 1)::int, 0)
           + coalesce((h.p5_c4 = 1 and h.p5_chaku > 1)::int, 0))::real as c4lead_lost,
          (coalesce((h.p1_c3 is not null and h.p1_c4 is not null)::int, 0)
           + coalesce((h.p2_c3 is not null and h.p2_c4 is not null)::int, 0)
           + coalesce((h.p3_c3 is not null and h.p3_c4 is not null)::int, 0)
           + coalesce((h.p4_c3 is not null and h.p4_c4 is not null)::int, 0)
           + coalesce((h.p5_c3 is not null and h.p5_c4 is not null)::int, 0))::real as fade34_n,
          (coalesce((h.p1_c4 > h.p1_c3)::int, 0) + coalesce((h.p2_c4 > h.p2_c3)::int, 0)
           + coalesce((h.p3_c4 > h.p3_c3)::int, 0) + coalesce((h.p4_c4 > h.p4_c3)::int, 0)
           + coalesce((h.p5_c4 > h.p5_c3)::int, 0))::real as fade34_down,
          py.fuku as prevyear_fukusho, py.tz as prevyear_timez, py.n as prevyear_n,
          jk.f365 as kishu_fuku_1y, jk.n365 as kishu_n_1y,
          trn.f365 as chokyo_fuku_1y, trn.n365 as chokyo_n_1y,
          pr.f1095 as pair_fuku_3y, pr.n1095 as pair_n_3y, (pr.f1095 - jk.f1095) as pair_vs_kishu,
          sb.fall as sire_fuku_band, sb.nall as sire_n_band,
          mb.fall as mf_fuku_band,   mb.nall as mf_n_band,
          (sg.fall - sa.fall) as sire_rgm_gap, (mg.fall - ma.fall) as mf_rgm_gap,
          ow.f365 as owner_hit, ow.n365 as owner_n, brd.f365 as breeder_hit, brd.n365 as breeder_n,
          cw.f365 as course_waku_hit, cf.w365r as course_front_win,
          bi.waku_bias_30, bi.waku_bias_365, bi.pace_bias_30, bi.pace_bias_365, bi.baba_io_365,
          bb.baba_d as baba_diff_d,
          (jc.changed)::int::real as norikae, (jc.changed)::int::real as jc_changed,
          (jc.rejoin)::int::real  as jc_rejoin,
          (case when jc.changed and jt.n365 >= 20 and pjt.n365 >= 20 then
                 (case when jt.f365 - pjt.f365 >=  0.05 then  1
                       when jt.f365 - pjt.f365 <= -0.05 then -1 else 0 end) end)::real as jc_tier,
          jp.n as jc_pair_n, jp.hit as jc_pair_hit, jt2.n as jc_tj_n, jt2.hit as jc_tj_hit,
          pj.f365 as p1_kishu_fuku,
          il.n365::real as ill_n_365, il.lastd::real as ill_last_days,
          (r.race_date - nk.ndate)::real as noken_days, nk.nsec as noken_time,
          sl.price::real as sale_price, extract(year from sl.auction_date)::real as sale_year,
          pn.c::real as jockey_penalty_90d,
          sv.avg30::real as race_sales, (sv.avg30 / nullif(sv.avg365, 0))::real as sales_vs_venue_avg
        from t_r2 r
        join t_hist h on h.track = r.track and h.race_date = r.race_date
                     and h.race_no = r.race_no and h.runner_number = r.runner_number
        left join t_jc jc on jc.track = r.track and jc.race_date = r.race_date
                         and jc.race_no = r.race_no and jc.runner_number = r.runner_number
        left join t_hyr py on py.horse_key = r.horse_key and py.yr = r.yr - 1
        left join t_asof jk  on jk.kind = 'jk' and jk.k1 = r.jockey and jk.k2 = '' and jk.d_idx = r.d_idx
        left join t_asof jt  on jt.kind = 'jt' and jt.k1 = r.track || '|' || r.jockey and jt.k2 = '' and jt.d_idx = r.d_idx
        left join t_asof trn on trn.kind = 'tr' and trn.k1 = r.trainer and trn.k2 = '' and trn.d_idx = r.d_idx
        left join t_asof pr  on pr.kind = 'pr' and pr.k1 = r.trainer and pr.k2 = r.jockey and pr.d_idx = r.d_idx
        left join t_asof sb  on sb.kind = 'sb' and sb.k1 = r.sire and sb.k2 = r.dist_band::text and sb.d_idx = r.d_idx
        left join t_asof sg  on sg.kind = 'sg' and sg.k1 = r.sire and sg.k2 = coalesce(r.going_ord::text, '?') and sg.d_idx = r.d_idx
        left join t_asof sa  on sa.kind = 'sa' and sa.k1 = r.sire and sa.k2 = '' and sa.d_idx = r.d_idx
        left join t_asof mb  on mb.kind = 'mb' and mb.k1 = r.broodmare_sire and mb.k2 = r.dist_band::text and mb.d_idx = r.d_idx
        left join t_asof mg  on mg.kind = 'mg' and mg.k1 = r.broodmare_sire and mg.k2 = coalesce(r.going_ord::text, '?') and mg.d_idx = r.d_idx
        left join t_asof ma  on ma.kind = 'ma' and ma.k1 = r.broodmare_sire and ma.k2 = '' and ma.d_idx = r.d_idx
        left join t_asof ow  on ow.kind = 'ow' and ow.k1 = r.owner and ow.k2 = '' and ow.d_idx = r.d_idx
        left join t_asof brd on brd.kind = 'br' and brd.k1 = r.breeder and brd.k2 = '' and brd.d_idx = r.d_idx
        left join t_asof cw  on cw.kind = 'cw' and cw.k1 = r.track || '|' || r.distance_m and cw.k2 = r.gate::text and cw.d_idx = r.d_idx
        -- ⛔cf/cq はコーナー解析ずみの走からしか行が立たない= 当日の行には同じ日の行が無い(学習では埋まり推論では NULL
        --   になってしまう)ので、直近の日の値を引く。窓は 1 preceding なので同日の行も前日までの値(Fable 9/7 修正)
        left join lateral (select a.w365r from t_asof a
                           where a.kind = 'cf' and a.k1 = r.track || '|' || r.distance_m and a.k2 = ''
                             and a.d_idx <= r.d_idx order by a.d_idx desc limit 1) cf on true
        left join t_bias bi on bi.track = r.track and bi.d_idx = r.d_idx
        -- ⛔馬場差は**前の開催日**の値(その日の勝ち時計は発走前に無い= 同日の結果を使わない。Fable 9/7 修正)
        left join lateral (select b.baba_d from t_baba b
                           where b.track = r.track and b.race_date < r.race_date
                           order by b.race_date desc limit 1) bb on true
        left join t_jcp jp  on jp.track = r.track and jp.fj = h.p1_jockey and jp.tj = r.jockey and jp.d_idx = r.d_idx
        left join t_jct jt2 on jt2.track = r.track and jt2.trainer = r.trainer and jt2.jockey = r.jockey and jt2.d_idx = r.d_idx
        left join lateral (select a.f365, a.n365 from t_asof a
                           where a.kind = 'jk' and a.k1 = h.p1_jockey and a.k2 = '' and a.d_idx < r.d_idx
                           order by a.d_idx desc limit 1) pj on true
        left join lateral (select a.f365, a.n365 from t_asof a
                           where a.kind = 'jt' and a.k1 = r.track || '|' || h.p1_jockey and a.k2 = ''
                             and a.d_idx < r.d_idx order by a.d_idx desc limit 1) pjt on true
        left join lateral (select count(*) filter (where i.kdate > r.race_date - 365) as n365,
                                  (r.race_date - max(i.kdate)) as lastd
                           from t_ill i where i.horse_key = r.horse_key and i.kdate < r.race_date) il on true
        left join lateral (select n.ndate, n.nsec from t_noken n
                           where n.horse_name = r.horse_name and n.ndate < r.race_date
                           order by n.ndate desc limit 1) nk on true
        left join lateral (select s.price, s.auction_date from t_sale s
                           where s.horse_key = r.horse_key and s.auction_date < r.race_date
                           order by s.auction_date desc limit 1) sl on true
        left join lateral (select count(*) as c from t_pen p
                           where p.person_name = r.jockey and p.race_date < r.race_date
                             and p.race_date >= r.race_date - 90) pn on true
        left join lateral (select x.avg30, x.avg365 from t_sales x
                           where x.track = r.track and x.d_idx < r.d_idx
                           order by x.d_idx desc limit 1) sv on true
        where p_from is null or r.race_date >= p_from
      ) z
      left join lateral (select a.f365 from t_asof a
                         where a.kind = 'cq' and a.k1 = z.trk_dist and a.k2 = z.qband
                           and a.d_idx <= z.d_idx order by a.d_idx desc limit 1) cq on true
    ) q
    join t_rank rk on rk.track = q.track and rk.race_date = q.race_date
                  and rk.race_no = q.race_no and rk.runner_number = q.runner_number
  ) w;

  -- ---------------------------------------------------------- 10) 場×日×距離のまとめ
  insert into public.nar_ai_feat_track (track, race_date, distance_m, baba_diff,
    waku_bias_30, waku_bias_365, pace_bias_30, pace_bias_365, std_time, n_365)
  select r.track, r.race_date, r.distance_m,
         max(bb.baba_d), max(bi.waku_bias_30), max(bi.waku_bias_365),
         max(bi.pace_bias_30), max(bi.pace_bias_365), max(r.sd_td), max(r.n_td)::int
  from t_r2 r
  left join t_baba bb on bb.track = r.track and bb.race_date = r.race_date
  left join t_bias bi on bi.track = r.track and bi.d_idx = r.d_idx
  where p_from is null or r.race_date >= p_from
  group by 1, 2, 3;

  -- ---------------------------------------------------------- 11) 記録
  insert into public.nar_ai_meta (key, value, updated_at)
  values ('refresh', jsonb_build_object(
            'at', now(), 'from', p_from,
            'min_date', (select min(race_date) from public.nar_ai_feat_run),
            'max_date', (select max(race_date) from public.nar_ai_feat_run),
            'runs',     (select count(*) from public.nar_ai_feat_run),
            'today',    (select count(*) from public.nar_ai_feat_run where finish is null),
            'seconds',  round(extract(epoch from clock_timestamp() - t0)::numeric, 1)), now())
  on conflict (key) do update set value = excluded.value, updated_at = now();

  -- ⛔カテゴリ列の数値の割り当て。学習(段階 2)と推論(段階 3)はここを読んで同じ字を使う
  insert into public.nar_ai_meta (key, value, updated_at)
  values ('codes', jsonb_build_object(
            'seibetsu', jsonb_build_object('牡', 0, '牝', 1, 'セン', 2),
            'baba_now', jsonb_build_object('良', 0, '稍重', 1, '重', 2, '不良', 3),
            'style',    jsonb_build_object('逃げ', 0, '先行', 1, '差し', 2, '追込', 3),
            'jc_tier',  jsonb_build_object('up', 1, 'same', 0, 'down', -1),
            'keibajo',  jsonb_build_object('帯広ば', 0, '門別', 1, '盛岡', 2, '水沢', 3, '浦和', 4,
                                           '船橋', 5, '大井', 6, '川崎', 7, '金沢', 8, '笠松', 9,
                                           '名古屋', 10, '園田', 11, '姫路', 12, '高知', 13, '佐賀', 14)), now())
  on conflict (key) do update set value = excluded.value, updated_at = now();

  return query select (select count(*) from public.nar_ai_feat_run),
                      (select count(*) from public.nar_ai_feat_track),
                      round(extract(epoch from clock_timestamp() - t0)::numeric, 1);
end;
$fn$;

-- ⛔§129d= 上と同じ理由(anon / authenticated は Supabase の役)。
do $rev$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function public.refresh_nar_ai_feat(date, int) from public, anon, authenticated';
  end if;
end
$rev$;

commit;

-- ============================================================ 検算(⛔ refresh を 1 回流したあとに読む)
--   select * from public.refresh_nar_ai_feat();       -- 全量(⛔Fable が流す・時計プールは 365 日)
--   select * from public.refresh_nar_ai_feat('2026-01-01'); -- その日以降だけ差し替え
--   select * from public.refresh_nar_ai_feat(null, 730);    -- §141 D-2 時計プールだけ 730 日にして焼き直す

-- ① 行数が nar_runs と合っているか・当日(まだ走っていない)の行数・期間
select (select count(*) from public.nar_ai_feat_run)                         as feat_rows,
       (select count(*) from public.nar_runs)                                as runs_rows,
       (select count(*) from public.nar_ai_feat_run where finish is null)    as today_rows,
       (select count(*) from public.nar_ai_feat_track)                       as track_rows,
       (select value from public.nar_ai_meta where key = 'refresh')          as last_refresh;

-- ② 鍵の重複が 0 か(PK があるので 0 のはず。壊れていないことの確認)
select count(*) as dup_keys from (
  select track, race_date, race_no, runner_number
  from public.nar_ai_feat_run group by 1, 2, 3, 4 having count(*) > 1) d;

-- ③ 欠けの多い列 トップ 20(2% の抜き取りで数える。⛔全行を舐めない)
select k as col, round(100.0 * avg((v = 'null'::jsonb)::int), 1) as null_pct
from (select to_jsonb(f) as j from public.nar_ai_feat_run f tablesample system (2)) s,
     lateral jsonb_each(s.j) e(k, v)
group by 1 order by 2 desc, 1 limit 20;

-- ④ 表の大きさ(⛔I-1 容量。1.4 GB を超えていないか)
select pg_size_pretty(pg_total_relation_size('public.nar_ai_feat_run')) as feat_size,
       pg_size_pretty(pg_database_size(current_database()))             as db_size;

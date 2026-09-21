-- §238a 派生表 nar_run_facts(2026-09-21 新設)。書き手は cloud/run_facts.py(pipeline/facts.py の規則)。
--
-- ■ 何のための表か
--   同じ事実(通過順の順位・脚質・前半3F・発走直前の単勝)の**定義が 3 か所に写されている**のをやめ、
--   1 頭 1 行で先に焼いておく。画面・予想 AI・展開便はこの表を読むだけにする(置換は §238a2)。
--
-- ■ 決めごと(⛔設計 docs/proposal_s238_run_facts_20260921.md)
--   ・欠けは NULL(⛔0 で埋めない)。読めないコーナーはそのコーナーごと捨てる(⛔推定しない)。
--   ・順位の分母は**そのコーナーに並んだ頭数**(field_size ではない)= n1..n4 を一緒に持つ。
--     ⛔持たないと読み手が p(位置)を出せず、また分母を各自で推定し始める(それが今回直したい病)。
--   ・c1= 読めたコーナーの最初 / c4= 最後 / c3= 最後から 2 番目(読めたコーナーが 2 つ以上のとき)/
--     c2= 2 番目(⛔読めたコーナーが **3 つ以上**のときだけ。2 つだと c4 と同じ物になる)。
--     ⛔コーナーの名前は場ごとにばらばらなので**名前では引かず並びの位置**で決める(ai_feat と同じ)。
--   ・style= 発走前 as-of(その日より前の走だけ)・直近 5 走・365 日窓・同じ場が 3 走以上ならその場だけ。
--     p<=0.2 の走が過半数なら 逃げ / 平均 p<=0.4 先行 / <=0.7 差し / それ以外 追込。2 走未満は NULL。
--   ・first3f の優先順= own(当サイトの計測・実測の札が付いた馬だけ)> paper(紙面)> kb(提供データ)> est。
--     ⛔first3f が NULL の行は first3f_src も NULL(「無い」を「推定した」に見せない)。
--   ・win_odds_close= nar_odds_ticks の最終の点の単勝(f=true があればそれ・無ければ最後の点)。
--   ・帯広ばは corners が無いので c1..c4 は NULL のまま行だけ作る(⛔行ごと落とさない)。
--
-- ■ 読み(⛔nar_race_pace と同じ書き方)= anon / authenticated の select だけ。書きは service_role。
-- 適用: psql … -v ON_ERROR_STOP=1 -X -f pipeline/sql/run_facts_20260921.sql(⛔鍵を持つ担当が流す)
\set ON_ERROR_STOP on

create table if not exists public.nar_run_facts (
  race_date      date not null,
  track          text not null,              -- 公式の場名
  race_no        int  not null,
  umaban         int  not null,              -- nar_runs.runner_number と同じ
  horse_key      text,                       -- horse_name || '|' || birth_date(§126 と同じ)
  horse_name     text,
  c1             int,                        -- 読めたコーナーの最初の順位
  n1             int,                        -- ⛔その コーナーに並んだ頭数(c1 の分母)
  c2             int,                        -- 2 番目(読めたコーナーが 3 つ以上のときだけ)
  n2             int,
  c3             int,                        -- 最後から 2 番目(読めたコーナーが 2 つ以上のときだけ)
  n3             int,
  c4             int,                        -- 最後(直線に入る前)
  n4             int,
  style          text,                       -- '逃げ' | '先行' | '差し' | '追込'(⛔発走前 as-of)
  style_p        numeric,                    -- style の材料= 直近 5 走の 1 角の平均位置
  style_n        int,                        -- style に使えた走の数(⛔2 未満なら style は NULL)
  first3f        numeric,
  first3f_src    text,                       -- 'own' | 'paper' | 'kb' | 'est'(⛔first3f があるときだけ)
  last3f         numeric,                    -- nar_runs.last3f(公式)をそのまま
  win_odds_close numeric,                    -- 発走直前の単勝(nar_odds_ticks の最終の点)
  src            text not null,              -- 'official' | 'kb_archive' | 'kochi_legacy'
  computed_at    timestamptz not null,
  primary key (race_date, track, race_no, umaban),
  constraint nar_run_facts_first3f_src_ck
    check (first3f_src is null or first3f_src in ('own', 'paper', 'kb', 'est')),
  constraint nar_run_facts_first3f_pair_ck
    check ((first3f is null) = (first3f_src is null)),
  constraint nar_run_facts_style_ck
    check (style is null or style in ('逃げ', '先行', '差し', '追込'))
);

-- 画面の引き方= 1 レース分(race_date, track, race_no)。主キーの先頭 3 列でそのまま効く。
-- 検算と遡りは日付の降順で舐めるので日付の索引を 1 本(nar_race_pace と同じ形)。
create index if not exists nar_run_facts_date_idx on public.nar_run_facts (race_date desc, track);
-- 馬ページ(1 頭の過去走)は horse_key で引く。
create index if not exists nar_run_facts_horse_idx on public.nar_run_facts (horse_key, race_date desc);

alter table public.nar_run_facts enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies
                  where schemaname = 'public' and tablename = 'nar_run_facts'
                    and policyname = 'nar_run_facts_read') then
    create policy nar_run_facts_read on public.nar_run_facts
      for select to anon, authenticated using (true);
  end if;
end $$;
grant select on public.nar_run_facts to anon, authenticated;

comment on table public.nar_run_facts is
  '§238a 1 頭 1 行の派生表。通過順の順位・脚質(発走前 as-of)・前半3F(出どころ付き)・発走直前の単勝。書き手は cloud/run_facts.py';

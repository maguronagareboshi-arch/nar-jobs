# §196b 第 2 段 南関 格付ポイントの履歴を表に積む(Opus・nar-jobs) 2026-09-17

## 出どころ
第 1 段 docs/s196b_recon.md(03e06da)= 着内ポイント 889/893 一致・格 97.6%・全頭 87.9% 復元。ユーザー: 「過去にどういうポイントでどう動いたか(昇級・降級)を追えないと困る・研究にも使う」。
第 1 段の 要判断への Fable の答え= (1) 履歴は **開催最終日** 単位 (2) 格は逆算で決めず **レースの条件の格** から取る(単一クラス= race・混合/選抜= 前の開催から carry・無ければ null) (3) nar_races に **番組ポイント 5 つと重賞の格** を持つ(列 1 本 jsonb) (4) raceid も同じ列に (5) 着順の欠け 275 走の取り直しは **別工事 B**(この工事ではその走で止める)。

## 器(Fable が本番に作成済み・pipeline/sql/nankan_hist_20260917.sql)
- 表 `nar_nankan_point_hist`(code, meet_end)= points・src(official|recon)・kaku_ran・kaku_src(race|carry)・last_run。anon 読み可。
- 列 `nar_races.nankan jsonb`= {"raceid","pts":[5],"grade"}。南関 4 場だけ。⛔他の場は null のまま。
- ⛔ AI 便の器 pipeline/sql/ai_feat_local_schema.sql には Fable が列を足した(触らない)。

## 変える所(新規 1 本+既存 1 本)
**A. cloud/nankan_hist.py(新規 ≤ 500 行・tools/nankan_recon.py の逆算をそのまま移す・DB へは upsert だけ)**
 1. 対象= `--days N`(既定 3)に南関で走った馬(nar_nankan_points に code がある馬)。`--all` で 2024-01-01 以降に走った全頭(初回の埋め・手押し)。
 2. 開催の区切り= 第 1 段と同じ(同じ場・間 4 日以内)。各馬について 2024-01-01 以降の開催ごとに 1 行:
    - points= いまの公式値から、その開催より後の開催で稼いだ着内ポイントを引く(recon)。着内ポイントは **nar_races.nankan.pts があればそれ**、無ければ第 1 段の表(レース名×公式の表)。決められない走(S 格で pts なし・着順なし・遠征先の地方交流重賞)より古い開催は points=null(⛔推定で埋めない)。遠征(他地区の走)は nar_horse_prize.runs の賞金÷1万・端数はそのまま(原文に無い= 切らない)。
    - 主催者の値(nar_nankan_points.asof)がその開催の後の最初の値なら、その開催の行は src=official・points=公式値(以後の便で asof が進むたびに official の行が増える= 逆算のズレはここで止まる)。
    - kaku_ran= その開催で走ったレースの条件の格。単一クラス(Ｃ３(二)・Ｂ１ など)→ race。混合(Ａ２Ｂ１)・選抜/選定・オープン・重賞 → 前の開催の kaku_ran を carry(無ければ null)。
 3. upsert(on_conflict= code,meet_end)。冪等。1 頭 ≤ 40 行。日次は走った馬だけ(≈150 頭)・初回 `--all` は 3,339 頭 ≈ 10 万行(手押し・分けて流してよい `--shard i/n`)。
**B. cloud/nankan_points.py(既存・馬ページの直後に 1 段足す)**= その日に南関で走ったレースの結果ページ `/result/{raceid}.do` を 1 本ずつ取り(1.8 秒間隔・cp932)、nar_races.nankan を upsert(raceid は馬ページのリンクの本物を優先・無ければ DB の日程から組む)。1 日 ≈ 40 本 ≈ 80 秒。`--results-dates YYYY-MM-DD..YYYY-MM-DD` で過去分(初回= 2024-01-01 以降の S 格重賞 114 本と、pts の無い開催)。⛔既存の馬ページの流れ・表 nar_nankan_points の列は変えない。
**C. nar-refresh.yml の朝の便**に `python cloud/nankan_hist.py --apply --days 3` を nankan_points の直後に 1 行(Fable が yml を触る= Opus は HANDOFF に「足す 1 行」を書くだけ。⛔yml の name に「: 」を書かない)。
**D. tests/test_nankan_hist.py(≤100 行)**= 開催の区切り・official/recon の切替・carry・null の伝播(決められない走より古い側は null)。

## 合格(オラクル 1 本+目視+console)
1. オラクル= 第 1 段の 50 頭(seed 196)で、表の points が第 1 段 `data/recon/recon_all.csv` と全行一致・kaku_ran(race)が結果ページの格と 100% 一致(carry は数えない)。
2. 初回 `--all` 後の SQL: 頭数 3,339・points null の行の割合・official 行の数(= 馬数)を HANDOFF に。points<0 の行 0(遠征 20 頭は null にせず値のまま・印は要らない= 画面側で扱う)。
3. 通信= nankankeiba の本数と所要・DB の upsert 行数。

## やらないこと
画面(工事 C・viewer・Fable 設計)/ 着順の欠け 275 走の取り直し(工事 B)/ 2024 年より前 / 抹消馬(いまの値が無い 420 頭)。

## 触らないもの
nar_nankan_points の列と取り直し規則・Actions yml・viewer・本番の他の表。push しない(commit まで)。初回 `--all` の実行は Fable(鍵)。

## 報告
HANDOFF 7 行。⚠筆頭= points null になった走の内訳(S 格 pts 無し/着順なし/遠征交流)。要判断= 画面(工事 C)に効く発見。

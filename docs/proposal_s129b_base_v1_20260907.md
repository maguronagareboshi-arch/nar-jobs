# §129b 設計書(下書き): 予想 AI「base-v1」— B/C の特徴量の考え方を、毎晩の差分集計+朝の軽い推論で作り直す(2026-09-07)

読むだけの下書き。⛔リポジトリのコードは 1 字も変えていない・⛔DB には 1 行も書いていない(SELECT のみ)・⛔鍵の値は 1 つも印字していない。
前提の下調べ= `設計書`(全部読んだ)。本書はその A-3「base-v1」を実際の列まで落としたもの。
⚠ 本書は**提案**であって約束ではない。精度の見込みは 1 つも実測していない(I 章)。

---

## A. 結論 — base-v1 の形(10 行)

1. **学習器**= LightGBM(`binary`)1 本。B/C と同じ道具・同じハイパラの初期値(`num_leaves=63 / lr=0.05 / feature_fraction=0.9 / bagging=0.8 / min_child_samples=100 / seed=42`)。
2. **目的変数**= `finish <= 3`(3 着以内)。⛔評価ゲート(`nar_ai_record`)の主な物差しが**複勝率と単勝回収率**なので、そこに合わせる。`finish = 1` の 2 本目は第 2 段で足す(H 章)。
3. **入力**= 本書 B 章の表。FEATURES183 のうち**そのまま作れる 116 列・近い形で作れる 66 列・作れない 1 列**、加えてサイト独自の 18 族(④)。
4. **特徴量の作り方**= 「走 1 行 = その走の**直前時点**の特徴量」を持つ 1 枚の表 `nar_ai_feat_run` を夜に作り直す。**当日の出走予定行も同じ表に同じ SQL で入る**(`finish is null` の行)。
5. → **学習と推論が literally 同じ行を読む**。これが設計の柱(C 章)。食い違い(train/serve skew)の入る隙間を構造で消す。
6. **出力の印**= レース内で取消・除外を除いた馬の予測確率を再正規化し、降順に `◎ ○ ▲ △` の 4 件固定。`score` = 再正規化後の確率 × 100(小数 1 桁)。base-v0 の「足し算の点数」ではなく**確率**にする(B/C と同じ読み方)。
7. **timing**= `morning` と `last` の両方を書く。当日しか出ない 3 列(`bataiju_now` / `bataiju_diff` / `baba_now`)は morning では欠測(NaN)にし、**学習データにも同じ穴を空けた行を混ぜる**(B/C の MASK37 と同じ発想。ただし列を消すのではなく「欠測の行を足す」ので情報は潰れない)。
8. **書き先**= `nar_ai_marks`(`model='base-v1'`)。既存の契約・既存のトリガー・既存の鍵をそのまま使う。SQL の変更は 0 行。
9. **base-v0 との切替**= `js/data.js` の `AI_MODELS_SELECTABLE` に 1 行(`{ id:'base-v1', label:'v1' }`)。⛔`AI_PUBLIC_MODELS` と `AI_PRIMARY_MODEL` は不変= **/record には出ない・評価中のまま成績だけ数えられる**。
10. **公開の条件**= 同じ期間・同じ場集合・同じ `timing` で、base-v0 に**複勝率と単勝回収率の両方で勝つ**まで公開しない(F 章)。勝てなければ切替でだけ見られる評価中モデルのまま。⛔昇格の判断はユーザーのもの。

---

## B. 特徴量の一覧

### B-0. 分類の集計

| 分類 | 意味 | 本数 |
|---|---|---|
| **①** | うちの DB(nar-official)でそのまま作れる | **116** |
| **②** | 近い形で作れる(材料はあるが定義か濃さが違う) | **66** |
| **③** | 作れない(材料そのものが無い) | **1**(`c1_dist`= 1角までの距離) |
| 計 | | **183** |
| **④** | サイト独自の新規(FEATURES183 に無い) | **18 族**(下の B-3) |

FEATURES183 の名前と順序は、`py/lib/nar.py` の `FEATURES22`(220 列)から `py/m60_mask183/spec.py` の `MASK37` を引いて**手元で再計算し、凍結 SHA `712FCC215BF5BB6E62D7D0E1E29C3FFA44949B174BFFF860FB5C92F0F304F272` と完全一致**したものを使っている(創作ではない)。

### B-1. ②が②である理由(まとめ)

| 束 | 本数 | 何が違うか |
|---|---|---|
| **コーナー通過順 由来**(`prev_corner4` / `p*_pos2` / `p*_pos4` / `pace_bias_*` / `qpts` / `race_qsum` / `race_qmax` / `c4lead_lost_rate` / `mak_gain_m3` / `pos2_var5` / `fade34_rate5` / `prev_pos2_rate` / `prev_pos4_rate` / `avg_pos2_3`) | 26 | ⛔下調べ F-8 の「コーナー通過順は無い」は**誤り**。`nar_races.corners` に **52,042/59,305 本(87.8%)**ある(実測)。ただし ①「正面/２角/３角/４角」の 4 点で全コーナーではない ②`"7,5-(2,3),(8,6),1-4"` のような**括弧(併走)と ハイフン(差)を含む文字列** ③ 12.2% は空 `[]`。§99a の既存パーサ(`cloud/tenkai.py` の `corner_ranks()`)が同じ形式を読んでいるので流用できる |
| **残差Z(RZ16)** | 16 | B/C は SQL の外で逐次に積む状態量として注入している。うちは「場×距離×going×クラス×頭数の回帰の残差」を夜に組み直す= **同じ考え方・別の値** |
| **Plackett-Luce レーティング(M21-7)** | 7 | 材料(誰が誰に勝ったか)は全部ある。逐次更新の実装を自前で書く= 同じ考え方・別の値 |
| **着差(margin)由来**(`prev_chakusa` / `p*_sa` / `r_pchakusa_pct` / `oshi_*`) | 11 | `nar_runs.margin` は `"1.1/4"` `"ハナ"` `"クビ"` 等の**文字列**。秒/馬身への数値化表を作る必要がある(既知の対応表なので難しくはないが「規則を足す」場所= ⛔一覧を先にユーザーへ見せる) |
| **クラス**(`class_diff` / `p*_cls`) | 6 | `nar_horse_prize.calc`(§79 P3 のクラス計算)は **kochi / obihiro / saga / tokai / hyogo の 5 prefix だけ**。他場は `nar_races.condition` の文字列で近似する |
| **ラップ形状**(`p1_lappace` / `p1_lapfade`) | 2 | `nar_races.furlongs` は **13,541/59,305(22.8%)**しか無い。⛔false zero 禁止・NaN で入れる |
| **ペース**(`prev_ra_pace`) | 1 | `nar_kb_runs.pace` は 6 場 2026 年のみ。全場は `race_last3f`/`race_last4f` からの近似 |
| **減量**(`minarai_now`) | 1 | `nar_runs.weight_mark` は **84,996/604,037(14.1%)**しか無い |
| 計 | **66** | |

### B-2. 183 列の表

「差分」列= 夜の差分集計に向くか。**○**= その走の直前の有限窓だけ見れば決まる(新しい日だけ足せる)。**△**= 全キャリア累積だが「走ごとに as-of の値を確定して持つ」ので、**過去行は二度と変わらない**= 実質○(追記のみ)。**×**= 当日しか出ない(朝は欠測)。
| # | 名前 | 意味 | 元の表と列 | 集計の窓 | 差分 | 分類 | 備考 | 実装(§129c) |
|---|---|---|---|---|---|---|---|---|
| 1 | `prev_chakujun` | 前走の着順 | nar_runs.finish | 前走1走 | ○ | **①** |  | 同名 |
| 2 | `prev_chakusa` | 前走の着差 | nar_runs.margin(text) | 前走1走 | ○ | **②** | 「1.1/4」「ハナ」等の文字列 → 秒/馬身への数値化が要る | 同名。②着差の文字を標準の対応表で馬身に(ハナ.05/アタマ.1/クビ.3/「1.1/2」=1.5/大差 10・レコード等は NULL) |
| 3 | `prev_corner4` | 前走の4角通過順 | nar_races.corners『４角』 | 前走1走 | ○ | **②** | corners は 52,042/59,305(87.8%)・括弧(併走)の解釈は §99a のパーサ流用 | 同名。②corners の**読めた最後のコーナー**の順位(名前で引かず並びの位置で決める) |
| 4 | `prev_ninki` | 前走の人気 | nar_runs.popularity | 前走1走 | ○ | **①** |  | 同名 |
| 5 | `avg_chakujun_3` | 直近3走の平均着順 | nar_runs.finish | 3走 | ○ | **①** |  | 同名 |
| 6 | `fukusho_rate_5` | 直近5走の3着内率 | nar_runs.finish | 5走 | ○ | **①** |  | 同名 |
| 7 | `days_since_prev` | 前走からの日数 | nar_runs.race_date | 前走1走 | ○ | **①** |  | 同名 |
| 8 | `dist_change` | 前走からの距離変化 | nar_races.distance_m | 前走1走 | ○ | **①** |  | 同名 |
| 9 | `track_change` | 場替わりか | nar_runs.track | 前走1走 | ○ | **①** |  | 同名 |
| 10 | `futan` | 斤量 | nar_runs.carried_weight | 当日 | ○ | **①** |  | 同名 |
| 11 | `futan_diff` | 前走との斤量差 | nar_runs.carried_weight | 前走1走 | ○ | **①** |  | 同名 |
| 12 | `prev_bataiju` | 前走の馬体重 | nar_runs.body_weight | 前走1走 | ○ | **①** |  | 同名 |
| 13 | `barei` | 馬齢 | nar_runs.age / birth_date | 当日 | ○ | **①** |  | 同名 |
| 14 | `seibetsu` | 性別(カテゴリ) | nar_runs.sex | 当日 | ○ | **①** |  | 同名 |
| 15 | `tosu` | 頭数 | nar_races.field_size | 当日 | ○ | **①** |  | 同名 |
| 16 | `wakuban` | 枠番 | nar_runs.gate | 当日 | ○ | **①** |  | 同名 |
| 17 | `kyori` | 距離 | nar_races.distance_m | 当日 | ○ | **①** |  | 同名 |
| 18 | `keibajo` | 競馬場(カテゴリ) | nar_runs.track | 当日 | ○ | **①** | 15場。B/C は帯広ばんえいを除外していたがこちらは入れる(場カテゴリで分かれる) | 同名 |
| 19 | `prize1_log` | 1着賞金の対数 | nar_races.prize_yen[0] | 当日 | ○ | **①** |  | 同名 |
| 20 | `dist_fukusho_rate` | 同距離帯(±200m)の3着内率 | nar_runs+nar_races | 全キャリア | △ | **①** | 累積= 走ごとに as-of で持てば差分可 | 同名。⚠「±200m」は 200m 刻みの箱で近似 |
| 21 | `dist_n` | 同距離帯の出走数 | 同上 | 全キャリア | △ | **①** |  | 同名。同上 |
| 22 | `kishu_fuku_1y` | 騎手の1年3着内率 | nar_runs(騎手×1年) | 365日 | ○ | **①** | nar_person_stats(場×年)でも近似できるが as-of でないので自前集計を推す | 同名。⛔場は分けない 365 日窓・前日まで(場×騎手は jc_tier 用に別に持つ) |
| 23 | `kishu_n_1y` | 騎手の1年騎乗数 | 同上 | 365日 | ○ | **①** |  | 同名 |
| 24 | `chokyo_fuku_1y` | 調教師の1年3着内率 | nar_runs.trainer | 365日 | ○ | **①** |  | 同名 |
| 25 | `chokyo_n_1y` | 調教師の1年出走数 | 同上 | 365日 | ○ | **①** |  | 同名 |
| 26 | `sire_fuku_band` | 種牡馬×距離帯の3着内率 | nar_horses.sire × nar_runs | 365日〜全期間 | ○ | **①** |  | 同名。窓は**全期間 as-of**(前日まで) |
| 27 | `sire_n_band` | 同 出走数 | 同上 | 同上 | ○ | **①** |  | 同名。同上 |
| 28 | `uma_place_fuku` | 当地(同じ場)の3着内率 | nar_runs | 全キャリア | △ | **①** |  | 同名 |
| 29 | `uma_place_n` | 当地の出走数 | 同上 | 全キャリア | △ | **①** |  | 同名 |
| 30 | `norikae` | 乗り替わりか | nar_jc_runs.changed | 前走1走 | ○ | **①** | §126 の集計表がそのまま使える | 同名。②nar_jc_runs は使わず前走騎手から as-of で判定 |
| 31 | `prev_time_z` | 前走の走破時計の偏差 | nar_runs.time_sec(97.8%) | 場×距離×馬場 | ○ | **①** |  | 同名。⛔**大きいほど速い**=(場×距離×馬場の前日まで 365 日平均 − 自分の時計)÷ばらつき |
| 32 | `avg_time_z_3` | 直近3走の時計偏差の平均 | 同上 | 3走 | ○ | **①** |  | 同名。p1〜p3 の平均 |
| 33 | `prev_pos2_rate` | 前走の2角位置(頭数比) | nar_races.corners『２角』 | 前走1走 | ○ | **②** | corners 87.8% | 同名。②2 角= 読めたコーナーが**3 つ以上**のときの 2 番目(2 つだと 4 角と同じになるので NULL) |
| 34 | `prev_pos4_rate` | 前走の4角位置(頭数比) | corners『４角』 | 前走1走 | ○ | **②** |  | 同名。②最後のコーナーの順位 ÷ そのコーナーに並んだ頭数 |
| 35 | `avg_pos2_3` | 直近3走の2角位置の平均 | corners | 3走 | ○ | **②** |  | 同名 |
| 36 | `class_diff` | 前走とのクラス差 | nar_races.condition/race_kind + nar_horse_prize.calc | 前走1走 | ○ | **②** | calc(クラス計算)は kochi/obihiro/saga/tokai/hyogo の 5 prefix だけ。他場は condition の文字列で近似 | 同名。②クラスは `ln(1着賞金) − その場の前日まで 365 日平均`(賞金のはしご)で数値化 |
| 37 | `prev_ra_pace` | 前走レースのペース | nar_races.race_last3f/race_last4f・nar_kb_runs.pace | 前走1走 | ○ | **②** | kb の pace は 6 場 2026 年のみ。全場は last3f/last4f からの近似になる | 同名。②`前走の race_last3f − その場×距離×馬場の前日まで平均`(⛔大きいほど上がりが遅い= 前が速かった) |
| 38 | `race_month` | 月 | race_date | 当日 | ○ | **①** |  | 同名 |
| 39 | `hasso_hour` | 発走時刻(時) | nar_races.post_time | 当日 | ○ | **①** |  | 同名 |
| 40 | `r_fuku5_pct` | レース内での fukusho_rate_5 の順位 | レース内 | 当日 | ○ | **①** |  | 同名。レース内 percent_rank(材料= fukusho_rate_5) |
| 41 | `r_timez_pct` | レース内での時計偏差の順位 | レース内 | 当日 | ○ | **①** |  | 同名。材料= avg_time_z_3 |
| 42 | `r_pchakusa_pct` | レース内での前走着差の順位 | レース内 | 当日 | ○ | **②** | 着差の数値化に依存 | 同名。材料= p1_sa |
| 43 | `waku_bias_365` | 枠バイアス(1年) | nar_runs.gate×finish | 365日 | ○ | **①** | §100 baba_trend の内外ρと同族(そちらは nar_meta に既にある) | 同名。②ρ の代わりに `枠/頭数` と `着/頭数` の**相関**(移動窓で順位は組めないため) |
| 44 | `waku_bias_30` | 枠バイアス(30日) | 同上 | 30日 | ○ | **①** |  | 同名。同上(30 日) |
| 45 | `pace_bias_365` | 前残りバイアス(1年) | corners 1角順位×finish のρ | 365日 | ○ | **②** | §100 baba_trend の『前後』と同じ定義。corners 依存 | 同名。②`1角順位/そのコーナーの頭数` と `着/頭数` の相関 |
| 46 | `pace_bias_30` | 前残りバイアス(30日) | 同上 | 30日 | ○ | **②** |  | 同名。同上(30 日) |
| 47 | `prev_time_za` | 馬場差で補正した前走時計偏差 | time_sec + nar_meta baba_diff | 前走1走 | ○ | **①** | §48 K-1b 馬場差が全15場ぶん既にある | 同名。⛔nar_meta baba_diff は直近 90 日しか残らないので**同じ定義で作り直した**(日×場の勝ち時計 − 場×距離の前日まで平均、の中央値) |
| 48 | `avg_time_za_3` | 同 直近3走平均 | 同上 | 3走 | ○ | **①** |  | 同名 |
| 49 | `r_timeza_pct` | レース内での順位 | レース内 | 当日 | ○ | **①** |  | 同名。材料= avg_time_za_3 |
| 50 | `runs_this_year` | 年内の出走数 | nar_runs | 暦年 | ○ | **①** | 2023 年以降は正しい。2022 年(11-12月)だけ切れる | 同名 |
| 51 | `season_debut` | 年内初戦か | 同上 | 暦年 | ○ | **①** |  | 同名 |
| 52 | `prevyear_fukusho` | 前年の3着内率 | 同上 | 前暦年 | ○ | **①** | 2024 年以降が正しい。2023 年は 2 か月ぶんしか無い → ⛔落とさず欠測(NaN)で入れる | 同名。暦年でまとめて yr-1 を引く |
| 53 | `prevyear_timez` | 前年の時計偏差 | 同上 | 前暦年 | ○ | **①** |  | 同名。同上(tz の平均) |
| 54 | `prevyear_n` | 前年の出走数 | 同上 | 前暦年 | ○ | **①** |  | 同名 |
| 55 | `p1_chaku` | 1走前の着順 | nar_runs.finish | 1走前 | ○ | **①** |  | 同名 |
| 56 | `p2_chaku` | 2走前の着順 | nar_runs.finish | 2走前 | ○ | **①** |  | 同名 |
| 57 | `p3_chaku` | 3走前の着順 | nar_runs.finish | 3走前 | ○ | **①** |  | 同名 |
| 58 | `p4_chaku` | 4走前の着順 | nar_runs.finish | 4走前 | ○ | **①** |  | 同名 |
| 59 | `p5_chaku` | 5走前の着順 | nar_runs.finish | 5走前 | ○ | **①** |  | 同名 |
| 60 | `p1_sa` | 1走前の着差 | nar_runs.margin(text) | 1走前 | ○ | **②** | 着差の数値化が要る | 同名。②着差の対応表 |
| 61 | `p2_sa` | 2走前の着差 | nar_runs.margin(text) | 2走前 | ○ | **②** | 着差の数値化が要る | 同上 |
| 62 | `p3_sa` | 3走前の着差 | nar_runs.margin(text) | 3走前 | ○ | **②** | 着差の数値化が要る | 同上 |
| 63 | `p4_sa` | 4走前の着差 | nar_runs.margin(text) | 4走前 | ○ | **②** | 着差の数値化が要る | 同上 |
| 64 | `p5_sa` | 5走前の着差 | nar_runs.margin(text) | 5走前 | ○ | **②** | 着差の数値化が要る | 同上 |
| 65 | `p1_tz` | 1走前の時計偏差 | nar_runs.time_sec | 1走前 | ○ | **①** |  | 同名 |
| 66 | `p2_tz` | 2走前の時計偏差 | nar_runs.time_sec | 2走前 | ○ | **①** |  | 同名 |
| 67 | `p3_tz` | 3走前の時計偏差 | nar_runs.time_sec | 3走前 | ○ | **①** |  | 同名 |
| 68 | `p4_tz` | 4走前の時計偏差 | nar_runs.time_sec | 4走前 | ○ | **①** |  | 同名 |
| 69 | `p5_tz` | 5走前の時計偏差 | nar_runs.time_sec | 5走前 | ○ | **①** |  | 同名 |
| 70 | `p1_pos2` | 1走前の2角位置 | nar_races.corners | 1走前 | ○ | **②** |  | 同名。②B-2 #33 と同じコーナーの決め方 |
| 71 | `p2_pos2` | 2走前の2角位置 | nar_races.corners | 2走前 | ○ | **②** |  | 同上 |
| 72 | `p3_pos2` | 3走前の2角位置 | nar_races.corners | 3走前 | ○ | **②** |  | 同上 |
| 73 | `p4_pos2` | 4走前の2角位置 | nar_races.corners | 4走前 | ○ | **②** |  | 同上 |
| 74 | `p5_pos2` | 5走前の2角位置 | nar_races.corners | 5走前 | ○ | **②** |  | 同上 |
| 75 | `p1_pos4` | 1走前の4角位置 | nar_races.corners | 1走前 | ○ | **②** |  | 同名。②B-2 #34 と同じ |
| 76 | `p2_pos4` | 2走前の4角位置 | nar_races.corners | 2走前 | ○ | **②** |  | 同上 |
| 77 | `p3_pos4` | 3走前の4角位置 | nar_races.corners | 3走前 | ○ | **②** |  | 同上 |
| 78 | `p4_pos4` | 4走前の4角位置 | nar_races.corners | 4走前 | ○ | **②** |  | 同上 |
| 79 | `p5_pos4` | 5走前の4角位置 | nar_races.corners | 5走前 | ○ | **②** |  | 同上 |
| 80 | `p1_ninki` | 1走前の人気 | nar_runs.popularity | 1走前 | ○ | **①** |  | 同名 |
| 81 | `p2_ninki` | 2走前の人気 | nar_runs.popularity | 2走前 | ○ | **①** |  | 同名 |
| 82 | `p3_ninki` | 3走前の人気 | nar_runs.popularity | 3走前 | ○ | **①** |  | 同名 |
| 83 | `p4_ninki` | 4走前の人気 | nar_runs.popularity | 4走前 | ○ | **①** |  | 同名 |
| 84 | `p5_ninki` | 5走前の人気 | nar_runs.popularity | 5走前 | ○ | **①** |  | 同名 |
| 85 | `p1_dkyori` | 1走前との距離差 | nar_races.distance_m | 1走前 | ○ | **①** |  | 同名 |
| 86 | `p2_dkyori` | 2走前との距離差 | nar_races.distance_m | 2走前 | ○ | **①** |  | 同名 |
| 87 | `p3_dkyori` | 3走前との距離差 | nar_races.distance_m | 3走前 | ○ | **①** |  | 同名 |
| 88 | `p4_dkyori` | 4走前との距離差 | nar_races.distance_m | 4走前 | ○ | **①** |  | 同名 |
| 89 | `p5_dkyori` | 5走前との距離差 | nar_races.distance_m | 5走前 | ○ | **①** |  | 同名 |
| 90 | `p1_cls` | 1走前のクラス | nar_races.condition/race_kind | 1走前 | ○ | **②** | 5 prefix 以外は文字列近似 | 同名。②class_diff と同じ賞金ベースのクラス水準 |
| 91 | `p2_cls` | 2走前のクラス | nar_races.condition/race_kind | 2走前 | ○ | **②** | 5 prefix 以外は文字列近似 | 同上 |
| 92 | `p3_cls` | 3走前のクラス | nar_races.condition/race_kind | 3走前 | ○ | **②** | 5 prefix 以外は文字列近似 | 同上 |
| 93 | `p4_cls` | 4走前のクラス | nar_races.condition/race_kind | 4走前 | ○ | **②** | 5 prefix 以外は文字列近似 | 同上 |
| 94 | `p5_cls` | 5走前のクラス | nar_races.condition/race_kind | 5走前 | ○ | **②** | 5 prefix 以外は文字列近似 | 同上 |
| 95 | `p1_gap` | 1走前との間隔(日) | nar_runs.race_date | 1走前 | ○ | **①** |  | 同名。⛔どれも**今日 − その走の日**(p1 との差ではない) |
| 96 | `p2_gap` | 2走前との間隔(日) | nar_runs.race_date | 2走前 | ○ | **①** |  | 同上 |
| 97 | `p3_gap` | 3走前との間隔(日) | nar_runs.race_date | 3走前 | ○ | **①** |  | 同上 |
| 98 | `p4_gap` | 4走前との間隔(日) | nar_runs.race_date | 4走前 | ○ | **①** |  | 同上 |
| 99 | `p5_gap` | 5走前との間隔(日) | nar_runs.race_date | 5走前 | ○ | **①** |  | 同上 |
| 100 | `p1_same` | 1走前が同じ場か | nar_runs.track | 1走前 | ○ | **①** |  | 同名 |
| 101 | `p2_same` | 2走前が同じ場か | nar_runs.track | 2走前 | ○ | **①** |  | 同名 |
| 102 | `p3_same` | 3走前が同じ場か | nar_runs.track | 3走前 | ○ | **①** |  | 同名 |
| 103 | `p4_same` | 4走前が同じ場か | nar_runs.track | 4走前 | ○ | **①** |  | 同名 |
| 104 | `p5_same` | 5走前が同じ場か | nar_runs.track | 5走前 | ○ | **①** |  | 同名 |
| 105 | `best_tz_5` | 直近5走の最良時計偏差 | time_sec | 5走 | ○ | **①** |  | 同名 |
| 106 | `worst_tz_5` | 直近5走の最悪時計偏差 | time_sec | 5走 | ○ | **①** |  | 同名 |
| 107 | `std_tz_5` | 直近5走の時計偏差のばらつき | time_sec | 5走 | ○ | **①** |  | 同名 |
| 108 | `best_chaku_5` | 直近5走の最良着順 | finish | 5走 | ○ | **①** |  | 同名 |
| 109 | `n_tz_5` | 直近5走で時計偏差が取れた本数 | time_sec | 5走 | ○ | **①** |  | 同名 |
| 110 | `p1_rz` | 1走前の残差Zスコア(条件モデルの残差= 時計の真の速さ) | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名。②`tz − その場×格(race_kind)×頭数の前日まで 365 日平均の tz`(条件のぶんを引いた残差) |
| 111 | `p2_rz` | 2走前の残差Z | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同上 |
| 112 | `p3_rz` | 3走前の残差Z | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同上 |
| 113 | `p4_rz` | 4走前の残差Z | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同上 |
| 114 | `p5_rz` | 5走前の残差Z | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同上 |
| 115 | `p1_rzin` | 1走前の残差Z(同場内) | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名。②`tz − その場の前日まで 365 日平均の tz` |
| 116 | `p2_rzin` | 2走前の残差Z(同場内) | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同上 |
| 117 | `p3_rzin` | 3走前の残差Z(同場内) | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同上 |
| 118 | `avg_rz_3` | 直近3走の残差Z平均 | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名 |
| 119 | `avg_rz_5` | 直近5走の残差Z平均 | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名 |
| 120 | `best_rz_5` | 直近5走の最良残差Z | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名 |
| 121 | `std_rz_5` | 直近5走の残差Zのばらつき | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名 |
| 122 | `avg_rzin_3` | 同場内の残差Z平均(3走) | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名 |
| 123 | `n_rz_5` | 残差Zが取れた本数 | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名 |
| 124 | `r_rz_pct` | レース内での残差Z順位 | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名。材料= avg_rz_3 |
| 125 | `r_bestrz_pct` | レース内での最良残差Z順位 | time_sec + 場×距離×going×クラス×頭数の回帰残差 | 5走 / レース内 | △ | **②** | B/C は SQL の外で逐次に積む状態量として注入(sql_chain.py:110-111)。うちは夜に回帰を組み直して残差を出す= 同じ考え方・別の値 | 同名。材料= best_rz_5 |
| 126 | `opp_str_now` | 今走の相手の強さ | nar_race_level.stats + レース内集計 | 当日 | ○ | **①** | nar_race_level(58,071行)が既にある | ⚠**作り直した**= nar_race_level は使わない(あの表は「出走馬の**次走**の成績」= 未来。I-8 の宿題を pipeline/sql/race_level.sql で確かめた)。同じレースの他馬の**前日までのキャリア複勝率**の平均(自分を除く) |
| 127 | `p1_fld` | 1走前の相手の強さ | 同上 | 1走前 | ○ | **①** |  | 同名。前走の同じ値(同じく nar_race_level は使わない) |
| 128 | `p2_fld` | 2走前の相手の強さ | 同上 | 2走前 | ○ | **①** |  | 同上 |
| 129 | `p3_fld` | 3走前の相手の強さ | 同上 | 3走前 | ○ | **①** |  | 同上 |
| 130 | `avg_fld_3` | 直近3走の相手の強さ平均 | 同上 | 3走 | ○ | **①** |  | 同名 |
| 131 | `relief_3` | 相手が楽になったか | 同上 | 3走 | ○ | **①** |  | 同名(avg_fld_3 − opp_str_now) |
| 132 | `bataiju_now` | 当日の馬体重 | nar_runs.body_weight(98.4%) | 当日 | × | **①** | ⛔発走の直前まで出ない= 朝予想では欠測。last だけ埋まる(B/C が timing=last のみに絞った理由と同じ) | 同名 |
| 133 | `bataiju_diff` | 当日の馬体重増減 | nar_runs.body_weight_change | 当日 | × | **①** | 同上 | 同名 |
| 134 | `baba_now` | 当日の馬場状態 | nar_races.going(100%) | 当日 | × | **①** | 朝は前日の going か欠測 | 同名。良0/稍重1/重2/不良3。⛔帯広ばんえいの going は含水率の数字なので NULL |
| 135 | `wet_n` | 道悪の出走数 | going × nar_runs | 全キャリア | △ | **①** |  | 同名。⛔「今日が道悪か」ではなく**その馬の道悪の成績**(条件つき集計) |
| 136 | `wet_fuku` | 道悪の3着内率 | 同上 | 全キャリア | △ | **①** |  | 同上 |
| 137 | `wet_tza_gap` | 道悪と良の時計差 | 同上 | 全キャリア | △ | **①** |  | 同名。道悪の tza 平均 − 良の tza 平均 |
| 138 | `p1_kishu_fuku` | 前走騎手の3着内率 | nar_jc_runs + nar_runs | 365日 | ○ | **①** | §126 の tier(上乗せ/格下)と同じ材料 | 同名。⛔**前走騎手の「今日時点」の 365 日複勝率**(今日より前で最も新しい as-of 値を引く) |
| 139 | `kishu_delta` | 前走騎手と今走騎手の差 | 同上 | 365日 | ○ | **①** | §126 の tier がそのまま使える | 同名(kishu_fuku_1y − p1_kishu_fuku) |
| 140 | `c1_dist` | 1角までの距離 | ― | ― | ― | **③** | ⛔うちの DB にコース形状(1角までの距離)は無い。nar_meta course_stats(§103)も『枠番・序盤の位置・逃げ馬』の統計で距離そのものは持たない。人手で 15 場×距離の定数表を作れば ② に上がる(1 日仕事・要ユーザー判断) | ⛔**作らない**(材料が無い。B-4 決定①) |
| 141 | `bw_slope_5` | 直近5走の馬体重の傾き | body_weight | 5走 | ○ | **①** |  | 同名。最小二乗の傾き(x= −1〜−5・正なら最近ほど重い) |
| 142 | `bw_dev` | 馬体重の平常からの乖離 | body_weight | 全キャリア | △ | **①** |  | 同名 |
| 143 | `p1_season_debut` | 前走が年内初戦だったか | race_date | 1走前 | ○ | **①** |  | 同名 |
| 144 | `pair_fuku_3y` | 騎手×厩舎ペアの3年3着内率 | nar_jc_runs / nar_runs | 1095日 | ○ | **①** | ⚠2022-11 起点なので 2025-11 より前は 3 年に満たない= 窓を『取れる範囲』にして n も一緒に入れる | 同名。1095 日窓・前日まで |
| 145 | `pair_n_3y` | 同 騎乗数 | 同上 | 1095日 | ○ | **①** |  | 同名 |
| 146 | `pair_vs_kishu` | ペアの上乗せ分 | 同上 | 1095日 | ○ | **①** |  | 同名(ペアの 1095 日複勝率 − その騎手の 1095 日複勝率) |
| 147 | `p1_lappace` | 前走のラップ形状(前傾/後傾) | nar_races.furlongs | 1走前 | ○ | **②** | ⛔furlongs は 13,541/59,305(22.8%)しか無い= ほぼ欠測。⛔false zero 禁止・NaN で入れる | 同名。②furlongs の前半平均 − 後半平均。⛔22.8% しか無い= ほぼ NULL |
| 148 | `p1_lapfade` | 前走の失速度 | 同上 | 1走前 | ○ | **②** | 同上 | 同名。②最終ハロン − 最速ハロン。同上 |
| 149 | `mf_fuku_band` | 母父×距離帯の3着内率 | nar_horses.broodmare_sire | 365日〜全期間 | ○ | **①** |  | 同名。全期間 as-of |
| 150 | `mf_n_band` | 同 出走数 | 同上 | 同上 | ○ | **①** |  | 同名 |
| 151 | `sire_rgm_gap` | 種牡馬×馬場レジームの差 | sire × going | 365日〜 | ○ | **①** |  | 同名。種牡馬の「今日の馬場」の複勝率 − 全体の複勝率 |
| 152 | `mf_rgm_gap` | 母父×馬場レジームの差 | broodmare_sire × going | 365日〜 | ○ | **①** |  | 同名。母父で同じもの |
| 153 | `rgm_gap` | その馬の馬場レジーム適性 | nar_runs × going | 全キャリア | △ | **①** |  | 同名。その馬の「今日の馬場」の複勝率 − キャリア複勝率 |
| 154 | `rgm_n` | 同 本数 | 同上 | 全キャリア | △ | **①** |  | 同名 |
| 155 | `trk_recent_dmz` | その場の直近の時計の出方 | nar_meta baba_diff(§48) | 30日 | ○ | **①** | 既にある | 同名。作り直した馬場差の**その場 30 日平均**(前日まで) |
| 156 | `dist_match` | 距離適性の一致度 | nar_runs × distance_m | 全キャリア | △ | **①** |  | 同名(同距離帯の複勝率 − キャリア複勝率) |
| 157 | `p1_dist_match` | 前走の距離適性一致度 | 同上 | 1走前 | ○ | **①** |  | 同名。前走の同じ値 |
| 158 | `pl_theta` | Plackett-Luce の馬の強さθ(対戦ベース・時計非依存) | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | ⛔段階 1 では **NULL の列だけ**(逐次更新は SQL で書けない= 段階 1b・Python) |
| 159 | `pl_n` | θ の更新回数 | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | 同上 |
| 160 | `jk_beta` | 交絡を除いた騎手効果β | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | 同上 |
| 161 | `tr_gamma` | 交絡を除いた厩舎効果γ | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | 同上 |
| 162 | `r_plth_pct` | レース内でのθ順位 | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | 同上 |
| 163 | `pl_gap_top` | レース内トップとのθ差 | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | 同上 |
| 164 | `jk_beta_delta` | 前走騎手とのβ差 | nar_runs(着順の並びだけ) | 全キャリア(逐次) | △ | **②** | 材料(誰が誰に勝ったか)は全部ある。ただし B/C は SQL 外で逐次に積む状態量= うちは日付順に 1 パスで更新する実装を自前で書く= 同じ考え方・別の値。⛔学習と推論で必ず同じ実装を使う | 同上 |
| 165 | `bw_season_dev` | 季節を除いた馬体重の乖離 | body_weight + race_month | 全キャリア | △ | **①** |  | 同名。同じ月の平常の馬体重との差 |
| 166 | `sex_summer` | 牝馬の夏場 | sex + race_month | 当日 | ○ | **①** |  | 同名(牝馬 and 6〜8 月) |
| 167 | `rest_leq3` | 中3週以内 | race_date | 1走前 | ○ | **①** |  | 同名。⚠「中3週」は **28 日以内**とした |
| 168 | `rest_gt42` | 休養42日超 | race_date | 1走前 | ○ | **①** |  | 同名(42 日超) |
| 169 | `oshi_nose2` | ハナ差2着の回数 | margin + finish | 5走 | ○ | **②** | 着差文字列(「ハナ」「アタマ」「クビ」)の解析が要る | 同名。②2 着 and 着差 ≤ 0.05(=ハナ)の回数 |
| 170 | `oshi_nose4` | 僅差4着以内の回数 | 同上 | 5走 | ○ | **②** |  | 同名。②4 着以内 and 着差 ≤ 0.30(=クビ)の回数 |
| 171 | `oshi_rate` | 惜敗率 | 同上 | 5走 | ○ | **②** |  | 同名(oshi_nose4 ÷ 直近 5 走のうち着順のある本数) |
| 172 | `c4lead_lost_rate` | 4角先頭から負けた率 | corners『４角』+ finish | 5走 | ○ | **②** | corners 87.8% | 同名。②最後のコーナーで 1 位だった走のうち 1 着でなかった割合 |
| 173 | `mak_gain_m3` | 直近3走の追い上げ幅(4角→着順) | corners + finish | 3走 | ○ | **②** |  | 同名。②(最後のコーナー順位 − 着順)の直近 3 走平均 |
| 174 | `pos2_var5` | 2角位置のばらつき | corners | 5走 | ○ | **②** |  | 同名。②2 角位置(頭数比)の母標準偏差 |
| 175 | `fade34_rate5` | 3角→4角で下がる率 | corners『３角』『４角』 | 5走 | ○ | **②** |  | 同名。②(最後から 2 番目のコーナー → 最後のコーナー)で順位が下がった割合 |
| 176 | `qpts` | Quirin 近似の先行度 | corners 1角順位 | 5走 | ○ | **②** | §99a の『最初のコーナー通過順÷頭数』がそのまま使える | 同名。②`1 − 1角順位/そのコーナーの頭数` の直近 5 走平均(**大きいほど前**) |
| 177 | `race_qsum` | レースの先行度合計 | 同上 | 当日レース内 | ○ | **②** | §99a の『前が多い/手薄』と同じ材料 | 同名。レース内合計 |
| 178 | `race_qmax` | レースの先行度最大 | 同上 | 当日レース内 | ○ | **②** |  | 同名。レース内最大 |
| 179 | `minarai_now` | 減量騎手か | nar_runs.weight_mark | 当日 | ○ | **②** | ⛔weight_mark は 84,996/604,037(14.1%)しか無い。騎手名から見習い期間を組む方が濃い= 別実装 | 同名。②weight_mark の有無。⛔**その日その場が記号を出しているとき**だけ 0/1・それ以外は NULL |
| 180 | `since_layoff` | 休養明けからの走数 | race_date | 全キャリア | △ | **①** |  | 同名。42 日超の間隔を「休養」として、そこからの走数 |
| 181 | `prev_best5` | 直近5走の自己ベスト | time_sec | 5走 | ○ | **①** |  | ⚠**言い換えた**= 直近 5 走の自己ベスト tz − **キャリアの自己ベスト tz**(そのままだと #105 best_tz_5 と同じ列になるため) |
| 182 | `bounce_risk` | 反動リスク(好走直後) | finish + time_sec | 2走 | ○ | **①** |  | 同名。②`p1_tz − p2〜p5 の tz 平均`(前走がいつもよりどれだけ良かったか) |
| 183 | `has_hist` | 地方平地の過去走があるか | nar_runs | 全キャリア | ○ | **①** |  | 同名(前日までに走った本数 > 0) |

### B-3. ④ サイト独自の新規(FEATURES183 に無い・B/C が持っていない材料)

これが「予想家を増やす」意味そのもの。⛔**うちにしか無いのはここ**なので、①②の再現より優先度が高い。

| # | 族 | 中身(列の例) | 元の表と列 | 実測の濃さ | 差分 | ⛔注意 |
|---|---|---|---|---|---|---|
| ④1 | **高知の前半3F 実測** | `ten_kochi`(前半3F 秒)・`ten_kochi_dev`(場×距離の標準との差)・`ten_kochi_n` | 旧DB `keiba_horses.first3f`(`baba_code=31`)× `nar_meta kochi_3f_kinds:<日>` が **`実測`** の馬だけ | 高知のみ・2024〜。`cloud/tenkai.py:483-500` が既に日単位で引いている | ○ | ⛔`推定` は使わない(§99b と同じ規律)。⛔1200m 未満は「距離−600m 通過」で別物 |
| ④2 | **提供データの前半3F**(6 場) | `ten_kb` / `ten_kb_dev` / `avg_f`(平均F) | `nar_kb_runs.first3f`(29,968/42,264)・`avg_f` | 大井 9,247 / 船橋 5,777 / 門別 6,468 / 川崎 4,343 / 浦和 4,051 / **園田 82**・**2026-01〜のみ** | ○ | ⛔園田は 82 本しか無い= 実質欠測。⛔閲覧者向けの文言に提供元の社名は出さない |
| ④3 | **展開の見立て(§99a)** | `style`(逃/先/差/追)・`n_front`(逃げ候補の数)・`word`(逃げ馬不在/単騎/2頭/ハナ争い)・`front_thick`(前が多い/手薄) | `nar_meta tenkai:<日>`(当日)/ 過去は `corners` から同じ規則で再計算 | 全 15 場・当日は既に毎朝作っている | ○ | ⛔当日の `tenkai:` は 1 日ぶんしか無い= **過去ぶんは同じ規則で作り直す**(`cloud/tenkai.py` の `style_of()` を SQL か Python で再実装。学習と推論で同じ実装を使う) |
| ④4 | **テンとペース見込み(§99b)** | `ten`(テン秒= 前半3F − 場×距離の標準)・`pace_hat`(速い/平均/遅い)・`ten_rank`(レース内順位) | ④1+④2 + 場×距離の標準(過去 1 年の中央値) | 高知+6 場。他 8 場は欠測 | ○ | ⛔高知だけ ±0.4 秒の固定帯・他場は四分位(`kochi-pace-definition`)。⛔標準は「過去 1 年の全開催日」で作る(その日の出走馬が触った日だけだと 0.05 秒揺れる= §99b で直した所) |
| ④5 | **乗り替わりの相性(§126)** | `jc_changed` / `jc_rejoin`(再コンビ)/ `jc_tier`(上乗せ/格下/同格)/ `jc_pair_hit`(この A→B の複勝率)/ `jc_pair_n` / `jc_tj_hit`(厩舎×騎手の乗替時複勝率) | `nar_jc_runs` / `nar_jc_pairs` / `nar_jc_trainer_jockey` | 全 15 場・590,230 走・2022-11〜 | ○ | ⛔`nar_jc_pairs` は「全期間」の集計= **未来を含む**。学習にそのまま使うと漏洩する → **as-of で組み直す**(その走の前日までの集計)。ここが一番の落とし穴 |
| ④6 | **馬具の変化(§119c)** | `gear`(B/SR 等)・`gear_first`(初着用)・`gear_off`(外した)・`gear_hit`(その馬の着用時複勝率) | `nar_kb_runs.gear` / `blinker` / `start_note`(出遅) | 6 場・2026〜・gear 11,200 走 | ○ | ⛔`blinker` 列は**全行 0 件**(実測)= 使えない。gear の文字列だけ。⛔行の無い走は「不明」= NaN(§119c と同じ規律) |
| ④7 | **クラス計算・収得賞金(§79 P3)** | `cls_calc`(当サイトの計算クラス)・`prize_local`(地方収得賞金)・`next_gap`(次のクラスまであと◯円)・`cls_lag` | `nar_horse_prize.calc` / `local_prize` / `n_runs` / `last_cls` | 5 prefix(kochi/obihiro/saga/tokai/hyogo)。`local_prize` 自体は全場 | △(日次スナップショット) | ⛔`calc` は**今日の値**しか無い= 過去の走の時点の値ではない。学習に使うなら `local_prize` の累積を `nar_runs` の賞金から自前で積む(`nar_races.prize_yen` × `finish`)= ① の材料で作れる |
| ④8 | **南関の格付ポイント(§38 1-C)** | `nk_points` | `nar_nankan_points` | 南関 4 場 | △ | ⛔同上(今日の値)。窓を切って使う |
| ④9 | **2 分刻みオッズ(§77 W4 / §123)** | `odds_win`(単勝)・`odds_pop`(人気順位)・`odds_drift`(40 分前→15 分前の動き)・`odds_synth_u1`(馬単1着合成)・`odds_synth_s1`(3連単1着合成) | `nar_odds_ticks.w/p/u1/s1` | **4,419 行・2026-09-02〜(5 日)**。`nar_race_odds` も 695 行・2026-08-23〜 | ○ | ⛔**学習には全く足りない**。G 章の base-v1m はここが致命的な制約。当面は `nar_runs.popularity`(592,719 行)で代用する |
| ④10 | **馬場傾向(§100)** | `baba_diff`(時計)・`baba_fb`(前後 ρ)・`baba_io`(内外 ρ) | `nar_meta baba_diff` / `baba_trend` | 全 15 場・毎朝更新 | ○ | ⛔`baba_trend` は「直近 90 日」の 1 枚= **過去の日の値は残っていない** → 学習用は `corners`+`gate`+`finish` から日ごとに作り直す |
| ④11 | **コース別データ(§103)** | `course_waku_hit`(場×距離×枠の複勝率)・`course_front_win`(逃げ馬の勝率)・`course_pos_hit` | `nar_meta course_stats:<prefix>` | 14 場 | △ | ⛔同上(今日の 1 枚)。学習用は過去 1 年ローリングで作り直す |
| ④12 | **レースの格(既存)** | `rl_n` / `rl_t3` / `rl_w1` / `rl_top3n`(そのレースの出走馬の実績) | `nar_race_level.stats` | 58,071/59,305 レース | ○ | `opp_str_now` / `p*_fld` の実体はここ |
| ④13 | **疾病・取消の履歴(§89/§109)** | `ill_n_365`(1 年の異常歴)・`ill_last_days`・`scratch_n_365` | `nar_horse_health_events` / `nar_runs.finish_note` | 全 15 場(NAR 成績 PDF)・§89 の 2026 backfill 後 | ○ | ⛔`finish_note` の「取消/除外」は**その走を購入対象から外す**のであって特徴量としては「前走が取消だった」で使う |
| ④14 | **能力検査(§117/§32a)** | `noken_time`(能検の時計)・`noken_days`(能検からの日数)・`is_noken_debut` | `nar_meta *_noken`(13 地区) | デビュー前の馬 | ○ | ⛔`has_hist=0`(初出走)の馬に**唯一入る情報**= ここが効く可能性がある |
| ④15 | **馬主・生産者の成績** | `owner_hit` / `owner_n` / `breeder_hit` / `breeder_n` | `nar_horses.owner` / `breeder` | 32,803 頭 | ○ | FEATURES13 の `banushi_fuku` / `seisan_fuku` は 183 に入っていないが、材料はうちにある= **足せる** |
| ④16 | **せり価格(§54.6)** | `sale_price` / `sale_year` | `nar_sales` / `auction_sales`(41MB) | 一部の馬 | △ | ⛔ほとんどの馬で欠測 |
| ④17 | **制裁(§111)** | `jockey_penalty_90d`(騎手の直近 90 日の制裁件数) | `nar_penalties` | 全場 | ○ | ⛔価値判断の語は入れない(数だけ) |
| ④18 | **売上(§54.1)** | `race_sales`(そのレースの総票数)・`sales_vs_venue_avg` | `nar_sales_daily` / `nar_sales_venue_avg` / `nar_sales_win_ref` | 全場 | ○ | 注目度の代理変数。⛔当日の売上は発走前に確定しないので**前日までの場平均**を使う |


**§129c(段階 1)で実際に作った ④ の列**(`pipeline/sql/ai_feat_20260908.sql`。⛔全部 as-of= 前日まで)

| 族 | 作った列 | どう作ったか / 作れなかった理由 |
|---|---|---|
| ④1 高知の前半3F 実測 | ⛔**無し** | 材料は**旧プロジェクト**(kochikeiba-viewer `keiba_horses.first3f`)にある。nar-official からは SQL で届かない= 段階 1 では作らない(要判断) |
| ④2 提供データの前半3F | `ten_kb` `ten_kb_dev` `avg_f` | 前走の値(⛔当日の前半3F は走ってみないと出ない)。`ten_kb_dev`= その場×距離の前日まで平均 − 前走の値(大きいほどテンが速い) |
| ④3 展開の見立て | `style` `avg_pos_5` `lead_n` `n_front` `front_ratio` | corners から §99a と同じ規則で作り直し(逃げ= 位置 ≤ 0.2 の走が過半数・先行 ≤ 0.4・差し ≤ 0.7)。⚠§99a の「同じ場が 3 走以上ならその場だけ」は入れていない= 直近 5 走をそのまま使う |
| ④4 テンとペース見込み | `ten_rank` | レース内の `ten_kb_dev` の順位。⛔`pace_hat`(速い/平均/遅い)は §99b の帯の規則そのものなので段階 1 では作らない(連続値の `ten_kb_dev` を渡す) |
| ④5 乗り替わりの相性 | `jc_changed` `jc_rejoin` `jc_tier` `jc_pair_n` `jc_pair_hit` `jc_tj_n` `jc_tj_hit` | ⛔`nar_jc_pairs` / `nar_jc_trainer_jockey` は**全期間**= 未来を含む(I-7)ので使わず、§126 と同じ定義(±5pt・20 騎乗以上)を**前日まで**で組み直した |
| ④6 馬具の変化 | `gear_now` `gear_first` `gear_off` `gear_n` `gear_hit` `start_note_n` | ⛔`blinker` 列は全行 0 件(I-13)なので `gear` の文字列だけ。行が無い日は「不明」= NULL(0 にしない) |
| ④7 クラス計算・収得賞金 | `prize_local` `prize_local_log` `r_prize_pct` | ⛔`nar_horse_prize.calc` は**今日の値**しか無いので使わず、`nar_races.prize_yen[着順]` を前日まで積み上げた |
| ④8 南関の格付ポイント | ⛔**無し** | `nar_nankan_points` も**今日の値**だけ(過去の時点の値が無い)= 使うと漏洩する |
| ④9 2 分刻みオッズ | ⛔**無し** | 5 日ぶんしか無い(I-9)。人気(`prev_ninki` / `p1_ninki`〜)で代用 |
| ④10 馬場傾向 | `baba_diff_d` `baba_io_365` | ⛔`nar_meta baba_diff` は直近 90 日・`baba_trend` は 1 枚しか残らないので、同じ定義で日ごとに作り直した。**`baba_diff_d` は前の開催日の値**(その日の勝ち時計は発走前に無い= 同日漏洩。Fable 9/7 検品で修正)。`baba_io_365`= 最終コーナーの位置と着順の相関(枠の相関は #43/#44) |
| ④11 コース別データ | `course_waku_hit` `course_front_win` `course_pos_hit` | ⛔`nar_meta course_stats` も今日の 1 枚なので、場×距離×枠 / 1角先頭の勝率 / 位置帯 を 365 日 as-of で作り直した。`course_front_win`/`course_pos_hit` は**直近の開催日の値を引く**(コーナー解析ずみの走からしか行が立たず、当日の行だけ NULL になる= 学習と推論のずれ。Fable 9/7 修正) |
| ④12 レースの格 | ⛔**無し**(`rl_*` は作らない) | `nar_race_level` は「出走馬の**次走**の成績」= 未来そのもの(I-8 を実装で確認)。代わりに #126〜#131 を前日までの相手実績で作り直した |
| ④13 疾病・取消の履歴 | `ill_n_365` `ill_last_days` `scratch_n_365` `p1_scratch` | ⛔**公表日**(`reported_date`。無ければ `event_date`)がその走より前のものだけ |
| ④14 能力検査 | `noken_days` `noken_time` `is_noken_debut` | `nar_meta noken_index` の日付つきの記録を as-of で。⚠鍵が**馬名だけ**(同名馬は取り違えうる) |
| ④15 馬主・生産者 | `owner_hit` `owner_n` `breeder_hit` `breeder_n` | 365 日 as-of |
| ④16 せり価格 | `sale_price` `sale_year` | `auction_sales` の、その走より前のいちばん新しい取引 |
| ④17 制裁 | `jockey_penalty_90d` | 件数だけ(⛔価値判断の語は入れない)。⚠`nar_penalties` は 335 行しか無い |
| ④18 売上 | `race_sales` `sales_vs_venue_avg` | ⛔当日の売上は発走前に確定しないので**前日までの場平均**(30 日)と、365 日平均との比。⚠`nar_sales_daily` は 2025-07-30 から |
| ④19 上がり3F(B-5 足りない) | `p1_l3z` `p2_l3z` `p3_l3z` `avg_l3z_3` `best_l3z_5` `r_l3z_pct` `p1_l3gap` | Fable 9/7 追記。`nar_runs.last3f`(馬ごとの上がり・89%)を場×距離×馬場の前日まで 365 日の平均/ばらつきで z 化(大きいほど速い)。`p1_l3gap`= 前走の自分の上がり − そのレースの `race_last3f`。B/C が MASK37 で捨てていた系統 |

### B-4. ⛔ 落とす判断が要る所(先にユーザーへ見せる)

`feedback-dont-crush-info-dont-add-rules` に従い、**「取れないから落とす」は勝手に決めない**。判断が要るのは次の 5 つだけ:

| # | 判断 | 選択肢 |
|---|---|---|
| 1 | `c1_dist`(1角までの距離・唯一の③) | (a) 落とす (b) 15 場×距離のコース定数表を人手で 1 日かけて作る |
| 2 | 着差 `margin` の文字列 → 数値の対応表(11 列が依存) | (a) 作る(ハナ=0.05 馬身 等の標準表) (b) 「僅差か否か」の 2 値に潰す (c) 落とす |
| 3 | `furlongs` 22.8% の 2 列 | (a) NaN で入れる(推奨) (b) 落とす |
| 4 | `weight_mark` 14.1% の `minarai_now` | (a) NaN で入れる (b) 騎手名から見習い期間を自前で組む |
| 5 | 帯広ばんえいを学習に入れるか | (a) 入れる(`keibajo` カテゴリで分かれる・base-v0 と同じ土俵になる= 推奨) (b) B/C に合わせて外す |

---


### B-5. Fable の精査(9/7・183 列の「いらない/伸ばす/危険/足りない」)= 段階 2 で列を選ぶときの根拠

**いらない・束ねる(約 50 列→15 列)**
- 完全な重複 6 組: 1=55・2=60・4=80・3≈75・7=95(prev_* と p1_* が二重)→ 片方。
- 時計の指標が 3 世代(素の偏差 31-32/41/65-69/105-107/181・馬場差補正 47-49・回帰残差 Z 110-125)→ **回帰残差 Z の 1 系統に統一**(p1〜p5・平均/最良/ばらつき/本数・レース内順位)。
- 5 走ぶん並べた列のうち薄いもの: 距離差 85-89 → p1 だけ+dist_match/ 同じ場か 100-104 → p1+5 走中の本数/ 間隔 95-99 → p1+平均。着順・時計・位置・人気の 5 本ずつは残す。
- 人が閾値を決めた規則列: 167-168(中 3 週/42 日超)・182(反動)・169-171(惜敗 3 列)→ 外す(元の数値があれば木が切る。⛔規則を足さない)。
- 暦年で切る 50-54・143 → **直近 365 日の出走数・複勝率・時計**に置換(年始リセットと 2022-11 起点の欠けを消す)。
- 道悪 135-137 と馬場レジーム 151-154 → 1 系統。

**伸ばす**
- **上がり 3F**(nar_runs.last3f 87.4%・B/C は furlongs 22.8% しか無く捨てていた): p1〜p3 の上がり偏差(場×距離×馬場の中央値との差)・最良上がり・上がり最速回数・レース内順位。**今回最大の追加**。
- **汎用クラス指標**: 過去 5 走の 1 着賞金 log の平均(全 15 場共通の「格」)・今走との差・昇級初戦/降級/転厩初戦/転入初戦の旗(nar_horse_changes)。
- 騎手×場×距離帯・厩舎×場・厩舎の休み明け成績(件数で全体平均に寄せる縮約)。
- 展開: §99a の予測位置・「逃げ馬の頭数 × 自分の先行度」。
- 2 歳/初出走(has_hist=0): 能検タイム偏差・せり価格 log・種牡馬の 2 歳成績・母父。
- 相対化(J-3): 斤量はレース内平均との差・枠は 枠÷頭数。

**危険(漏洩・要検証)**
- 126-131 相手の強さ(nar_race_level.stats)= 作り方に結果が含まれていないか**段階 1 の検算に入れる**(I-8)。
- 騎手/厩舎の 365 日率= 同日の他レースの結果を入れない。レーティング 158-164= そのレースの結果で更新する前の値(1 走遅らせる)。
- 80-84 前走人気= 漏洩ではないが「市場」。**基礎モデルでは外し、市場モデルで使う**。
- 132-134 当日 3 列= 朝は欠測(設計どおり)。

**足りない(J 以外)**
- 前走の取消/中止/除外の理由(§89・§111)・疾病履歴の件数と直近日・馬具変更(§119c・5 場)・騎手のその日の騎乗数・その馬の発走順(出馬表で分かる)・天候は last だけ。

**進め方**= 段階 1 の表は 182 列のまま作る(real で軽い)。外す/束ねる/足すは**段階 2 の学習側で列を選ぶ**(SQL を作り直さず比較実験できる)。上がり 3F と賞金の格だけは段階 1 の SQL に足す(HANDOFF 後に Fable が追記)。

## C. 差分集計の設計

### C-1. 柱 — 学習と推論で同じ SQL

> **1 枚の表 `nar_ai_feat_run` に「走 1 行 × as-of 特徴量」を持ち、当日の出走予定行も同じ INSERT で入れる。**
> 学習は `where race_date <= '2025-12-31' and finish is not null`、推論は `where race_date = 今日 and track = ... and race_no = ...`。
> **同じ表・同じ列・同じ作り方**。特徴量を作るコードは片方にしか存在しない。

これで下調べ F-8 と `feedback-dont-crush-info-dont-add-rules` の両方に効く。B/C が「学習側にも同じ穴を空けた」のと同じ発想を、**列を消す方向ではなく「1 本の SQL に統一する」方向**で実現する。

### C-2. 作る表

| 表 | 鍵 | 列 | 行数(見込み) | 作り方 |
|---|---|---|---|---|
| **`nar_ai_feat_run`** | `(track, race_date, race_no, runner_number)` | `horse_key text` + 特徴量 **約 200 列** を `real`(float4)+ `y_top3 smallint` / `y_win smallint` / `finish` / `popularity` | **604,037 + 当日 600** | 本体。`refresh_nar_ai_feat()` を `truncate + insert` で 1 トランザクション(`refresh_nar_jc()` と同型) |
| `nar_ai_feat_person` | `(kind, name, track, asof_date)` | `n / w1 / hit / rate`(騎手・調教師・ペア) | 約 3〜5 M(日×人) | ⚠ 日ごとに持つと大きい → **`nar_ai_feat_run` に直接埋め込む**(下の C-3 の窓関数)ことにして**この表は作らない** |
| `nar_ai_feat_track` | `(track, race_date, distance_m)` | `baba_diff / waku_bias_30 / waku_bias_365 / pace_bias_30 / pace_bias_365 / std_time` | 59,305 × 距離 ≈ 15 万 | 日×場の集計。夜に全部作り直し(軽い) |
| `nar_ai_feat_rating` | `(horse_key, race_date, race_no)` | `pl_theta / pl_n / jk_beta / tr_gamma` | 604,037 | **逐次**なので日付順 1 パス。plpgsql のループか Python で作って COPY |
| `nar_ai_meta` | `key` | `refresh`(時刻・期間・行数)・`model`(SHA・学習日・列の順序 SHA) | 数行 | `nar_jc_meta` と同型 |

**容量の見積もり**(⛔ 2026-09-04 に Storage Size Exceeded で本番 3 時間停止した前科がある。ここは慎重に):

- 現在の DB= **829 MB**(public 816 MB。内訳は `nar_runs` 255MB / `nar_jc_runs` 164MB / `nar_race_payouts` 78MB / `nar_jc_pairs` 62MB)。
- `nar_ai_feat_run` を 200 列 `real` で持つと **604,637 行 × 約 830 B ≈ 500 MB**(+ 索引 50 MB)。`double precision` だと 1.0 GB。
- → **⛔`real` で持つこと**。それでも DB は 829 MB → **約 1.4 GB** になる。Supabase Pro のディスクには収まるが、**⛔第 1 段の前に実際の空きをユーザーと確認する**(I-1)。
- **代案(容量が厳しい場合)**= DB には**直近 400 日だけ**置き(約 17 万行・140 MB)、学習用の全期間は **PC で一時表 → `\copy` で CSV → `drop`** する。柱(同じ SQL)は守れる。

### C-3. 作り方(`refresh_nar_ai_feat()` の骨格)

`refresh_nar_jc()` と同じ型。`security definer` / `search_path = public` / `truncate + insert` / 1 トランザクション / 戻りは行数。

```
create or replace function public.refresh_nar_ai_feat(p_from date default null)
returns table (runs bigint, tracks bigint)
language plpgsql security definer set search_path = public as $$
begin
  truncate public.nar_ai_feat_run, public.nar_ai_feat_track;

  -- 0) 走の素形(取消・除外も残す= 前走にはしないが「前走が取消」は特徴量)
  create temp table t_run on commit drop as
  select u.track, u.race_date, u.race_no, u.runner_number, u.gate,
         u.horse_name || '|' || coalesce(u.birth_date::text,'') as horse_key,
         u.jockey, u.trainer, u.sex, u.age, u.carried_weight, u.body_weight,
         u.body_weight_change, u.finish, u.finish_note, u.time_sec, u.margin,
         u.last3f, u.popularity, u.weight_mark,
         r.distance_m, r.going, r.weather, r.field_size, r.condition, r.race_kind,
         r.post_time, r.prize_yen, r.corners, r.furlongs, r.race_last3f, r.race_last4f,
         h.sire, h.broodmare_sire, h.owner, h.breeder
  from public.nar_runs u
  join public.nar_races r using (track, race_date, race_no)
  left join public.nar_horses h on h.horse_name = u.horse_name;

  -- 1) コーナー位置(§99a の corner_ranks と同じ規則を SQL で)
  --    corners は [{"name":"正面","order":"7,5-(2,3),..."}] の 4 点。
  --    括弧= 併走(同順)・ハイフン= 差。順位は「並びの位置」で取り、分母は
  --    ⛔「そのコーナーに並んだ頭数」(field_size ではない。#466 で 48R 中 6 本ずれた)
  create temp table t_corner on commit drop as ... ;

  -- 2) 馬ごとの過去走(window 関数で 1 パス)
  --    lag(...) over (partition by horse_key order by race_date, track, race_no) を 5 段
  --    累積(全キャリア)は rows between unbounded preceding and 1 preceding
  --    ⛔ order by は一意に(race_date, track, race_no, runner_number)
  --      = postgrest-offset-needs-unique-order と同じ理由

  -- 3) 人(騎手・調教師・ペア)の as-of 集計
  --    range between '365 days' preceding and '1 day' preceding
  --    ⛔ 当日を含めない(同じ日の他レースの結果を見ない)

  -- 4) 血統(種牡馬・母父 × 距離帯 × going)も同じ窓で

  -- 5) 場×日の馬場・バイアス → nar_ai_feat_track

  -- 6) レース内の順位(r_*_pct)は最後に percent_rank() over (partition by レース)

  -- 7) 当日・翌日の出走予定(finish is null)も 0〜6 を通る= 同じ列が埋まる

  insert into public.nar_ai_feat_run select ... ;
  ...
end; $$;
```

**⛔ 4 つの守り**

1. **as-of の窓は必ず「前日まで」**。`1 day preceding` を全部の人・血統・場の窓に付ける。④5(`nar_jc_pairs`)を素のまま使うと**全期間の集計= 未来を含む**ので漏洩する。ここが一番の落とし穴。
2. **並び順は一意に**(`race_date, track, race_no, runner_number`)。`postgrest-offset-needs-unique-order` と同じ理由で、一意でない `lag()` は走が入れ替わる。
3. **馬の同一性**= `horse_name || '|' || birth_date`(§126 と同じ)。⛔`birth_date` は **604,037 行すべてに入っている**(実測)ので、このキーは堅い。`nar_horse_codes` は 6 場しか無いので使わない。
4. **NaN と 0 を区別する**。「行が無い」は NULL のまま(LightGBM は NaN を扱える)。⛔false zero 禁止。

**⛔ 5 つ目の守り(§129c2・2026-09-07 に本番で temp が溢れたので足した)**

5. **窓の入力は細い表だけ**。本番の `work_mem` は **2,184 kB**(実測)で、窓の並べ替えは全部ディスクに落ちる。`select r.* … 窓 10 個` のように**太い行**を並べ替えると 1 文で数 GB の一時ファイルになり、`No space left on device` で落ちる(実測: `create temp table t_r1` で 9 分 17 秒後に失敗)。
   - **日単位の窓**(`range between N preceding and 1 preceding`)は、先に `(partition, d_idx)` で sum/count に束ねてから窓を掛ける= **同じ値**で行数が 604,637 → 数万に落ちる。
   - **馬ごとの窓**は束ねても行数が減らないので、「鍵 + その窓に要る数だけ」の細い行に掛けて**鍵で join して戻す**。`percent_rank` も同じ(⛔約 250 列の `q.*` を渡さない)。関数の冒頭で `work_mem` を 64MB(そのトランザクションだけ)。

### C-4. 見込み所要

**⛔置き場は「Actions の中の Postgres」に変えた(9/8 ユーザー決定)。この節の下の見積りは残すが、本番 DB で流す前提の所は無効。**
理由= 9/7 22:14 の 1 回目は temp がディスクを使い切って 9 分で失敗し、23:21 の 2 回目は 30 分過ぎに本番 DB が固まって **23:52〜00:22 サイトのデータが読めなくなった**(pooler の認証も通らず・ダッシュボードの Restart project で復旧)。原因は SQL でなく器= 本番は work_mem 2 MB・IO の割当が小さい計算機で、60 万行 × 246 列の組み立てに耐えない。
新しい形= `.github/workflows/nar-ai-feat.yml` が自分用の Postgres 16(work_mem 256MB)を立て、本番からは材料 9 表を `\copy (select * from …) to` で**読むだけ**写し、そこで `refresh_nar_ai_feat()` を回して `nar_ai_feat_run` を作る。器は `pipeline/sql/ai_feat_local_schema.sql`。
成果物は artifact(`nar_ai_feat_run.csv.gz` ほか・保存 14 日)に置き、段階 2(学習)はそれを読む。⛔本番への書き込みは 0(印を書くのは段階 3 の便だけ)。
⛔全量の特徴量作りを本番 DB で流すことは二度としない。守りの検査= `tests/ai_feat_workflow_test.mjs`(本番に繋ぐ step に `\copy … to` 以外を書かせない)。
⛔cron はまだ付けない= `workflow_dispatch` で 1 回流して所要を実測してから Fable が決める。

`refresh_nar_jc()` の実測が土台: **590,230 走 → 4 表(runs 590,230 / 調教師×騎手 89,782 / ペア 358,204 / 人気帯 3,368)を 181 秒**。中身は同じ `nar_runs` の全走 + window 関数 + cross join lateral の集計。

| 段 | 中身 | 見込み | 根拠 |
|---|---|---|---|
| 0-1 | 素形+コーナー解析 | 60〜120 秒 | 文字列解析が 52,042 レース× 平均 10 頭 |
| 2 | 過去 5 走の window(50 列超) | 120〜240 秒 | nar_jc は lag 3 本で 181 秒のうち体感の大半 |
| 3-4 | 人・血統の 365 日窓 | 60〜120 秒 | |
| 5-6 | 場×日+レース内順位 | 30〜60 秒 | |
| 7 | insert(604k 行 × 200 列 real) | 60〜120 秒 | |
| **計** | | **推定 6〜12 分** | ⚠**推定**。実測していない。⛔`set statement_timeout` を `30min` にする(`ai_record.sql` は `10min`) |
| 別 | `nar_ai_feat_rating`(逐次) | **推定 3〜10 分** | Python で 604k 走を 1 パス+COPY。plpgsql ループは遅いので Python を推す |

~~**置き場**= `nar-refresh.yml` の **monthly 便(JST 05:33)**。`jockey change stats`(181 秒)の直後。月次便は timeout 60 分・現状 29〜30 分なので、+10〜20 分は**入るが余裕は薄い**(⛔#520 で 30 分に達して切られた前科がある)。→ **⛔第 3 段の前に月次便の所要を測り直し、超えるなら専用の workflow に分ける**。~~ (⛔9/8 に無効= 上の C-4 冒頭のとおり本番では流さない)

**差し替えの単位**= 第 1 段は `truncate + insert`(全量)。安定したら **`p_from` を受けて「その日以降だけ delete + insert」**の日付単位に変える(`feedback-one-year-scope` の「修理は全量置き換えでなく日付単位の差し替え」)。⚠ ただし人・血統の 365 日窓は前日までなので、**日付単位の差し替えでも過去行は変わらない**= 追記で正しい。

### C-5. 朝の推論で 1 レースぶんを引く SQL

**特徴量は既に表にある**ので、推論側は「引くだけ」。これが柱の効き所。

```sql
-- 1 日ぶんまとめて(1 便 1 クエリ)。⛔学習と同じ列・同じ順序で select する
select f.track, f.race_no, f.runner_number, f.horse_key,
       f.prev_chakujun, f.prev_chakusa, ... , f.has_hist   -- 183 + ④
from public.nar_ai_feat_run f
join public.nar_races r using (track, race_date, race_no)
where f.race_date = $1                          -- 今日(JST)
  and f.finish is null                          -- まだ走っていない
  and coalesce(f.finish_note,'') !~ '取消|除外'  -- 発走前に分かる不出走
order by f.track, f.race_no, f.runner_number;
```

- 1 日 33〜60 レース × 平均 10 頭 = **400〜600 行 × 約 200 列**。pg8000 で 1 本・**推定 2〜5 秒**。
- ⛔ PostgREST(`sb_get`)では列が多すぎて URL が長くなる → **pg8000 を使う**(`cloud/horse_changes.py` / `cloud/jockey_change.py` に先例あり・`NAR_DB_PASSWORD` は既に Secrets にある)。
- ⛔ 列の順序は **モデルの `feature_name` と完全一致**させる。学習時に `設計台帳` へ順序 SHA を記録し、推論側で照合して**合わなければ何も書かずに終わる**(fail-closed。B/C の `FeatureContract` と同じ考え)。
- `timing='morning'` のときは `bataiju_now` / `bataiju_diff` / `baba_now` を **NULL に上書きしてから**推論する(D-3 と対)。

---

## D. 学習

### D-1. どこで

**PC(手元)**を推す。理由:

- データの取り出しが `psql \copy` 1 本で済む(`pipeline/dbadmin.py` の経路が既にある)。
- Actions の 6 時間枠でもできるが、**学習用 CSV を Actions に渡す手段がない**(DB から直接引けば同じだが、失敗のたびに 6 時間枠を消費する)。
- ⛔`feedback-assume-pc-closed`(PC は閉じている前提)は**毎日の運用**の話。学習は月 1 回の人手の作業なので PC で構わない。

**手順**:
```
psql ... -c "\copy (select * from public.nar_ai_feat_run where finish is not null order by race_date) to 'train.csv' csv header"
py -3.12 tools/train_base_v1.py --csv train.csv --out cloud/data/base_v1.txt
```

### D-2. データ量

| 期間 | 用途 | 走(見込み) |
|---|---|---|
| 2022-11-01 〜 2025-12-31 | **学習** | 約 490,000(実測 604,037 のうち 2026 年ぶんを引いた概算) |
| 2026-01-01 〜 | **検証**(walk-forward・封印) | 約 114,000 |

- CSV は 604k 行 × 200 列 ≈ **900 MB**(gzip で 150 MB)。PC のメモリは pandas で 604k × 200 × 4B = **500 MB** = 全く問題ない(B/C の 14.8 GB とは桁が 2 つ違う)。
- ⛔ 2022-11 起点の歪み: `prevyear_*`(前年成績)は 2024 年以降しか正しくない・`pair_*_3y`(3 年ペア)は 2025-11 以降しか 3 年に満たない。**⛔落とさず NaN で入れ、フォールド別に効きを見る**(`feedback-dont-crush-info-dont-add-rules`)。

### D-3. 当日列の穴あけ(morning 用)

学習データを**2 倍にはしない**。代わりに:

- 各行を**確率 0.5 で** `bataiju_now` / `bataiju_diff` / `baba_now` を NaN にした複製に置き換える(= 実質「当日情報がある行」と「無い行」を半々で学習)。行数は 490,000 のまま。
- ⛔ こうすると 1 本のモデルで morning / last の両方に出せる。**B/C が「morning は出せない」と契約で禁じた所を、うちは越える**。
- ⚠ これは**推定**。「穴あけ学習が本当に効くか」は検証窓で morning / last 別に測って確かめる(H-4)。

### D-4. LightGBM の初期値

```python
params = dict(
    objective="binary", metric=["auc", "binary_logloss"],
    num_leaves=63, learning_rate=0.05, feature_fraction=0.9,
    bagging_fraction=0.8, bagging_freq=1, min_child_samples=100,
    seed=42, num_threads=0, verbose=-1)
categorical_feature = ["keibajo", "seibetsu"]   # B/C と同じ 2 つ
num_boost_round = 3000
early_stopping_rounds = 100     # 検証窓の最初の 3 か月(2026-01〜03)で止める
```

- ⛔ **B/C とそっくり同じにする**。「うちが勝てるかどうか」の差を**特徴量とデータの新しさだけ**にしたいので、ハイパラで差を作らない(第 1 段では調整しない)。
- ⛔ **AUC / logloss / 較正(ECE)を必ず記録する**。B/C はこれを一度も保存していなかった(下調べ F-2)。同じ穴に落ちない。

### D-5. 時系列の分け方

```
学習   2022-11-01 〜 2025-12-31
早停め 2026-01-01 〜 2026-03-31   (early stopping にだけ使う)
検証   2026-04-01 〜              (封印。ここを見て特徴量やハイパラを触ったら検証ではなくなる)
```

- ⛔ **早停めに使った窓を検証に使わない**。B/C の一番大きな瑕疵(評価窓が学習期間の内側)を繰り返さない。
- ⛔ **「いつも多数派」と比べる**(`classifier-compare-to-majority-baseline`)。3 着内率の無情報ベースライン= 頭数の逆数×3。◎ の複勝率は「1 番人気を常に ◎」に対して比べる。

### D-6. モデルファイルの置き場

- LightGBM のテキスト booster。B/C は 183 列 / 1,043 木で **7.4 MB**。うちも同規模 → **5〜9 MB**。
- 置き場= **`cloud/data/base_v1.txt`**(git に入れる)。
- ⚠⛔ **`keiba-deploy` は push = 自動デプロイ**。CI が**許可リスト完全一致**なので、9 MB のファイルを足すと ①CI の許可リストに載せる必要がある ②Cloudflare Pages の配信物に入ると閲覧者が 9 MB を引く可能性がある。
  → **⛔第 3 段の前に、`cloud/` 以下が配信物に入らないことを `validate-production.py` と `_headers` で確認する**(I-2)。入るなら **git LFS か Actions の artifact か Supabase Storage** に逃がす。
- **SHA256 を `設計台帳` に記録**する(B/C の `model_sha256` と同じ)。加えて**学習時の LightGBM の版**も記録する(⛔B/C はこれを記録せず、推論の再現性の裏取りができなくなっている= 下調べ G-3)。

### D-7. 再学習の頻度

**月 1 回**(月初)。理由:

- B/C は 2026-08-13 に凍結して以来**一度も再学習されていない**(下調べ F-2)= 本日時点で学習データが 5 週間前まで。同じ穴に落ちない。
- ⛔ 再学習したら**検証窓も前に進める**。前の版の成績は `nar_ai_record` に残るので、`model` 名に版を付けるか(`base-v1`/`base-v1.1`)、`nar_ai_meta` に「いつからどの重みか」を記録する。
  → **推奨= model 名は `base-v1` のまま固定し、`nar_ai_meta` に切替日を記録する**。model 名を増やすと `nar_ai_record` の n が分断されて 1 か月の検定ができなくなる(下調べ E-4)。

---

## E. 推論と書き込み

### E-1. どの段に何分で

`nar-refresh.yml` の `ai marks`(base-v0)の**すぐ下**に 1 段:

```yaml
      # §129b base-v1(学習した重み)。base-v0 と同じ契約・同じ頻度。
      # ⛔失敗しても便を落とさない(base-v0 の印は既に書かれている)
      - name: ai marks v1
        continue-on-error: true
        env:
          SUPABASE_URL: ${{ secrets.NAR_SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.NAR_SUPABASE_SERVICE_KEY }}
          SUPABASE_DB_PASSWORD: ${{ secrets.NAR_DB_PASSWORD }}
        run: python cloud/marks_v1.py
```

⛔ `cloud/marks.py` は**改造しない**。`cloud/marks_v1.py` を新規で書く(`load_nar_official.upsert()` と `odds.sb_get/log` は再利用)。

**所要の見込み**(⚠ 推定):

| 段 | 見込み |
|---|---|
| `pip install lightgbm numpy`(`cloud/requirements.txt` に 2 行) | **+30〜60 秒**(wheel: lightgbm 約 4 MB・numpy 約 18 MB) |
| モデル読み込み(`lgb.Booster(model_file=...)` 9 MB) | 1〜3 秒 |
| 特徴量 1 日ぶんを pg8000 で 1 クエリ(600 行 × 200 列) | 2〜5 秒 |
| 推論(600 行) | **1 秒未満** |
| `nar_ai_marks` へ upsert(最大 120 行= 60R × morning/last) | 2〜4 秒 |
| **計** | **40〜75 秒**(pip が支配的) |

日次便は現状 1〜2 分なので **2〜3 分**になる。20 分おきの便としては十分収まる。
⚠ `pip install` が毎便 40〜60 秒増えるのは**全段に効く**(base-v0 の段も遅くなるわけではないが便全体が伸びる)。気になるなら `actions/cache` で pip を効かせる(別途 10 行)。

### E-2. `nar_ai_marks` への書き方

**base-v0 と同じ契約**(下調べ §B-6 / `cloud/marks.py`):

```json
{ "model": "base-v1", "track": "高知", "race_date": "2026-09-08", "race_no": 5,
  "timing": "last",
  "marks": [ {"num": 3, "mark": "◎", "score": 34.2}, {"num": 7, "mark": "○", "score": 21.8},
             {"num": 1, "mark": "▲", "score": 15.0}, {"num": 9, "mark": "△", "score": 9.6} ],
  "meta": { "factors": {"3": ["近走好調","同距離実績"]}, "n": 11 },
  "computed_at": "2026-09-08T09:07:31+09:00" }
```

- **marks は 4 件固定**・印は位置固定 `◎ ○ ▲ △`。⛔4 頭未満のレースは対象外(base-v0 と同じ)。
- `score` = 取消・除外を除いて**再正規化した 3 着内確率 × 100**、小数 1 桁。⛔画面で 100 倍しない。
- `meta.factors` = ⛔**専門用語を出さない**(`feedback-no-jargon-for-viewers`)。SHAP の列名をそのまま出さず、上位の寄与を base-v0 と同じ言葉(「近走好調」「同距離実績」「当地実績」「騎手好調」「休み明け」)に落とす。**⚠ 対応表を作る所が「規則を足す」場所**= 第 3 段で一覧をユーザーに見せる。
- `meta.n` = 出走見込み頭数。⛔B/C は契約書に `meta.n` があるのに実物が `{}` だった(下調べ F-6)。うちは base-v0 が既に入れているので同じにする。
- `computed_at` は書く側が渡す・`+09:00` 厳密。
- **凍結ルールは base-v0 と同じ**: `morning` はその日の最初の 1 回だけ・`last` は発走 15 分前まで上書き・発走 15 分前を過ぎたレースには新規でも書かない。
  ⛔ さらに DB トリガー `ai_marks_guard_20260825.sql` が **model を見ずに**同じ規律を効かせる= 二重の安全弁。⛔ **「エラーが出なかった」は採用の証拠にならない= read-back 必須**。

### E-3. 失敗時の扱い

| 失敗 | 振る舞い |
|---|---|
| 特徴量の表に当日の行が無い(夜の便が落ちた) | **何も書かない**・log に理由・exit 0(便は落とさない)。⛔前日の印を使い回さない |
| モデルの列順序 SHA が合わない | **何も書かない**・exit 1(`continue-on-error` で便は続く)。fail-closed |
| DB が引けない / 402 等 | **何も書かない**・exit 2 |
| 一部のレースだけ特徴量が欠ける | **そのレースだけ飛ばす**(他は書く)。⛔全部落とさない |
| upsert が 5xx | 3 回だけ再試行(`upsert()` の既存の作り) |

⛔ **空のまま**が正しい姿。`ai_record.sql` は `computed_at < 発走時刻` の行しか数えないので、遅れて書いた行は自動で成績から外れる= 後追いのズルができない。
⛔ **静かに失敗し続ける**のを防ぐため、`cloud/coverage.py`(§118)に「`nar_ai_marks` の `base-v1` の当日行数」を 1 行足して `/status` で見えるようにする。

---

## F. 評価ゲートと土俵

### F-1. `ai_record.sql` はモデル別に数える(変更 0 行)

- 集計の粒度は **`(model, track, timing)`**。`from (select distinct model, track, timing from tmp_ai_u) g` で、**model の許可リストは無い**(意図的・DESIGN #177)。
- `base-v1` の行を `nar_ai_marks` に書けば、**翌朝の monthly 便(JST 05:33)で `nar_ai_record` に自動で成績が生える**。SQL の変更は 0 行。
- 誠実さの三条件が既に入っている: ①`computed_at < 発走時刻` ②取消・除外は購入から除外 ③1 着が入っている決着済みレースのみ。

### F-2. 比較の物差し

| 項目 | 値 |
|---|---|
| **主**(公開の条件) | `top.fuku`(◎の複勝率)と `top.tanRet`(◎の単勝回収・100 円あたり)の**両方**で base-v0 以上 |
| 副 | `top.win`(単勝率)・`top.n`・`byMark` の 4 印・`popBands`(人気帯別)・`monthly` |
| 期間 | `stats.from` / `stats.to` を**必ず併記**。⛔両モデルで**同じ期間**を切る |
| `timing` | ⛔**同じ timing どうし**。base-v1 は morning / last の両方を出すので、base-v0 と 2 通り比べられる(B/C は last のみだった) |
| 場 | base-v1 は帯広ばんえいを**含める**(B-4 #5 で (a) を選ぶ場合)。含めれば `all` どうしをそのまま比べられる。⛔含めないなら `all` を直接見比べない(場別で比べる) |
| 期間の長さ | ⛔**最短 1 か月**(◎ 勝率 25% どうしで 5pt の差を見るのに片側 1,000R ≒ 26 開催日。下調べ E-4) |

⛔ **無情報の相手にも勝つこと**(`classifier-compare-to-majority-baseline`)。`popBands` を見て「◎ がほぼ 1 番人気」なら、それは人気を並べ替えただけ。**「常に 1 番人気を ◎」の仮想成績**を同じ SQL で 1 本作って並べる(`model='ninki-1'` として `nar_ai_marks` に書けば同じ表に載る= **⛔これは第 4 段でユーザーに提案する**)。

### F-3. 公開の条件と切替

| 段階 | 見え方 | 変える所 |
|---|---|---|
| **評価中**(第 3〜4 段) | レース画面の切替でだけ見える。`/record` には出ない | `js/data.js` の `AI_MODELS_SELECTABLE` に **1 行**:<br>`{ id: 'base-v1', label: 'v1' }` |
| **公開**(第 5 段・⛔ユーザー判断) | `/record` に並ぶ | `AI_PUBLIC_MODELS` に `'base-v1'` を足す |

⛔ `AI_PRIMARY_MODEL`(出馬表の主役印・トップ・初期表示)は**触らない**。
⛔ `tests/ai_bc_marks_test.mjs:34` が `AI_PUBLIC_MODELS === ['base-v0']` を assert している= 公開時はテストも直す(**片方だけ直さない**。`feedback-ledger-correct-in-place` の「同じゲートは grep して両方直す」)。
⛔ **昇格の前に表示名の表を作る**。`js/pages/record.js:106` はボタンのラベルに**生の内部 ID** を出す(DESIGN #274)。`base-v1` はまだ読めるが、規律として先に直す。

---

## G. 市場版(base-v1m)= オッズを見てから出す予想家

### G-1. ⛔ いちばん重要な事実 — オッズの履歴が 5 日しか無い

| 表 | 行数 | 期間 |
|---|---|---|
| `nar_odds_ticks`(2 分刻み・単勝/複勝/合成) | **4,419** | **2026-09-02 〜 09-07** |
| `nar_race_odds`(単複のスナップショット) | **695** | 2026-08-23 〜 09-07 |
| `nar_runs.popularity`(結果表の人気) | **592,719** | 2022-11 〜 |

→ **オッズ倍率そのものでは学習できない**(5 日)。⛔ここを曖昧にしたまま「市場版を作る」と言わない。

### G-2. だから 2 段構えにする

| 版 | 学習に使う市場情報 | 推論に使う市場情報 | いつ作れるか |
|---|---|---|---|
| **base-v1m(第 1 版・今すぐ作れる)** | `nar_runs.popularity`(**人気の順位**・592,719 行) | 2 分刻みオッズから作った**その時点の人気順位**(`nar_odds_ticks.w` を昇順に並べる) | **今すぐ** |
| base-v1m2(1 年後) | `nar_odds_ticks` の**倍率と動き**(40 分前→15 分前のドリフト・合成オッズ u1/s1) | 同じ | **2027 年秋**(1 年ぶん溜まってから) |

- 人気は「発走時のオッズ順位」なので**発走前に取れる情報**= 漏洩ではない。⛔ただし `nar_runs.popularity` は**確定オッズの順位**(締切時点)で、推論時の「40 分前の順位」とは少しズレる。**⛔このズレは train/serve skew** で、C 章の柱に反する。
  → **緩和策**= 学習側でも「締切 40 分前の順位」に近づけるため、**人気を順位そのものではなく粗い帯(1 / 2 / 3 / 4-6 / 7+)で入れる**(§126 の人気帯と同じ切り方)。帯なら 40 分前と締切でほとんど動かない。⚠ これは**推定**。溜まった 5 日ぶんで「40 分前の帯 vs 締切の帯」の一致率を測れば確かめられる(1 時間の作業・第 4 段)。

### G-3. どの便で回すか

⛔ **オッズ収集の 2 分便(公開リポ `nar-odds-collector`)には相乗りしない**。理由: 公開リポに lightgbm と 9 MB のモデルを入れることになり、2 分おきに pip install が走る。

代わりに **`nar-refresh` の 20 分便に 1 段足す**:

- 各便で「**発走まで 15〜35 分**のレース」だけを処理する。20 分おきなので、どのレースも**この窓に必ず 1 回は入る**。
- ⛔ 発走 15 分前を過ぎたら書けない(トリガーが `RETURN NULL` で静かに捨てる)ので、**窓の下限は 15 分ではなく 17〜18 分**にして余裕を取る。
- ⚠ GitHub の cron は混雑で間引かれる(特に JST 9〜10 時台)。⛔ **`dispatcher.sql`(pg_cron + pg_net・09:05〜21:45 の 20 分おき)が既に叩いている**ので、間引きへの保険は既にある。それでも取りこぼす便はある → **取れなかったレースは空のまま**(前の印を使い回さない)。

### G-4. base-v1 との違いと、公開時の断り文

| | base-v1 | base-v1m |
|---|---|---|
| 市場情報 | **使わない** | 人気帯(将来は倍率と動き) |
| timing | morning + last | **last のみ**(発走 15〜35 分前) |
| 便 | 全便 | 発走 15〜35 分前の窓に入るレースだけ |
| model 名 | `base-v1` | `base-v1m` |
| 立ち位置 | 「データだけで見る予想家」 | 「みんなの見方も見てから出す予想家」 |

**公開時の断り文(閲覧者向け・⛔専門用語なし・⛔社名なし)**:

> **v1m について** — この予想は、発走の少し前のオッズ(人気の順)も見てから印を付けています。オッズを見ない v1 とは別の予想家として並べています。どちらが当たるかは成績のページで比べられます。予想は当サイトの計算によるもので、結果を保証するものではありません。

⛔ 「回収率」「期待値」「EV」等は出さない(`feedback-no-jargon-for-viewers`)。⛔ **買い方の推奨はしない**(下調べ F-1 の独立 AI ラインで「1 的中依存」になった前例)。

---

## H. 工程

| 段 | 中身 | 日数 | 検品の方法 |
|---|---|---|---|
| **0** | ⛔**先にユーザー判断**: B-4 の 5 つ + C-2 の容量 + D-6 の配信物 | 0.5 日 | 一覧を出して合格をもらう。⛔ここを飛ばして進めない |
| **1** | `nar_ai_feat_run` / `nar_ai_feat_track` / `nar_ai_feat_rating` と `refresh_nar_ai_feat()` | **3〜4 日** | ①**手計算のオラクル 3 本**: 高知の 1 レースを人手で追い、`prev_chakujun` / `p1_pos4` / `kishu_fuku_1y` が一致するか。②**漏洩の検算**: 適当な 100 走で「特徴量の窓が前日で切れているか」(その走の当日の結果が入っていないか)を SQL で確認。③行数= `nar_runs` と一致 |
| **2** | 学習(`tools/train_base_v1.py`)+ AUC/logloss/較正の記録 | **2〜3 日** | ①検証窓(2026-04〜)で AUC・logloss・ECE を出す。②**「常に 1 番人気」に勝つか**を同じ窓で。③フォールド別(2023/2024/2025)に効きを見て 2022-11 起点の歪みを確認 |
| **3** | `cloud/marks_v1.py` + workflow 1 段 + `AI_MODELS_SELECTABLE` 1 行 | **1〜2 日** | ①`--dry-run` で当日ぶんの印を目視。②本番 1 便流して `nar_ai_marks` を **read-back**(⛔エラー無しを証拠にしない)。③翌朝 `nar_ai_record` に `base-v1` の行が生えるのを確認。④**レース画面を目視スクショ**(⛔実装と同じセレクタで引かない・`feedback-verify-with-eyes-not-same-selector`)。⑤console 0 |
| **4** | **1 か月走らせる** + base-v1m(G 章)を並走 | **26 開催日** | 毎週 `nar_ai_record` の `top.n` を確認するだけ。⛔途中で特徴量を触ったら期間がリセット |
| **5** | 評価 → 公開判断 | 1 日 | F-2 の物差しで並べてユーザーへ提示。⛔昇格はユーザー判断 |

**合計= 手を動かすのが 7〜11 日 + 待ちが 1 か月**。費用 0・新しい鍵 0・新しい起こし手 0。

---

## I. 危うい点と未確認

⛔ **推定は推定と書く**。以下で「実測」と書いていないものは全部推定。

| # | 内容 | 種別 |
|---|---|---|
| **I-1** | **DB の容量**。現在 **829 MB**(実測)。`nar_ai_feat_run` を `real` 200 列で足すと **+約 550 MB → 約 1.4 GB**(推定)。⛔**2026-09-04 に「Storage Size Exceeded」で両プロジェクトの REST が止まり本番 3 時間停止した前科がある**。Pro の実際の空き(ディスク上限)を**確認していない** | ⛔未確認・要ユーザー確認 |
| **I-2** | **9 MB のモデルを git に入れて配信物に入らないか**。`keiba-deploy` は push = 自動デプロイ・CI が許可リスト完全一致。`cloud/` が Cloudflare Pages の配信物に入らないことを**確認していない** | ⛔未確認 |
| **I-3** | **`refresh_nar_ai_feat()` の実所要**。`refresh_nar_jc()` の 181 秒(実測)からの外挿で **6〜12 分**と見ているが、列数が 50 倍近い。**測っていない**。月次便は現状 29〜30 分で timeout 60 分= 超えると #520 と同じ「途中で切られる」事故になる | ⛔未確認・推定 |
| **I-4** | **`pip install lightgbm numpy` の実所要**。40〜60 秒と見ているが**測っていない**。20 分おきの便が全部伸びる | 推定 |
| **I-5** | **精度の見込みがゼロ検証**。base-v1 が base-v0 に勝つ根拠は 1 つも無い。⛔**提案であって約束ではない**。B/C ですら base-v0 との比較規則が存在しない(下調べ F-1) | ⛔未検証 |
| **I-6** | **`corners` の 12.2% 欠測とパーサ**。52,042/59,305(実測)。⛔括弧(併走)とハイフンの解釈は §99a の実装がある = 学習と推論で**必ず同じ実装**を使う。SQL で書き直すと Python 版とズレる → **⛔片方に寄せる**(SQL 側に寄せて Python は呼ぶだけ、を推す) |
| **I-7** | **④5 の漏洩**。`nar_jc_pairs` / `nar_jc_trainer_jockey` は**全期間の集計= 未来を含む**(実測: `yr='all'` の行がある)。素のまま学習に入れると成績が幻になる。⛔**as-of で組み直す**のが必須 | ⛔設計上の必須事項 |
| **I-8** | **`nar_race_level` の作り方を読んでいない**。`{"n":11,"t3":3,"w1":1,"top3n":3,"top3w1":1}`(実測)が「そのレースの出走馬の過去実績」なのか「結果を含む」のかを**確認していない**。結果を含むなら漏洩する | ⛔未確認 |
| **I-9** | **馬名の同一性**。`horse_name + birth_date`(§126 と同じ)を使う。`birth_date` は 604,037 行すべてに入っている(実測)が、**同名同生年月日の別馬**が居ないことは確認していない | 未確認 |
| **I-10** | **`bataiju_now` の朝の扱い**。D-3 の「確率 0.5 で穴を空ける」学習が効くかは**推定**。効かなければ morning 用と last 用でモデルを 2 本に分ける(モデルファイルが 2 倍= 18 MB) | 推定 |
| **I-11** | **G-2 の人気帯のズレ**。「40 分前の人気帯」と「締切の人気帯」の一致率を**測っていない**。溜まった 5 日ぶんで測れる | ⛔未確認(測れる) |
| **I-12** | **`nar_kb_runs` の 園田 first3f が 82/9,912 本しか無い**(実測)。④2 は実質 5 場。⛔「6 場」と言わない |
| **I-13** | **`nar_kb_runs.blinker` が全 6 場で 0 件**(実測)。④6 の blinker 列は**使えない**。gear の文字列だけ |
| **I-14** | **`nar_ai_record` の `updated_at` が 2026-09-05 22:37 のまま**(下調べ G-9)。monthly 便でしか更新されないので、base-v1 の成績も**翌朝までは見えない**。⛔「書いたのに成績が出ない」を事故と誤認しない |
| **I-15** | **`AI_MODELS_SELECTABLE` に 3 つ目を足したときの画面**。#508 の器は base / B / C の 3 つで動いている(実測)。4 つ目・5 つ目(v1・v1m)の切替が横に入るかを**目視していない** | 未確認 |
| **I-16** | **`race_last3f` が 52,038/59,305・`time_sec` が 590,676/604,037・`last3f` が 528,200/604,037**(全部実測)。時計系は 87〜98% で、`last3f` は **87.4%**= `prev_a3f` 相当が薄い。⛔B/C が MASK37 で上がり系を全部落としたのは「10:30 に取れないから」だが、うちは**遡って取れる**ので落とさない |

---

### B-6. 外し実験の実測(Fable 2026-09-08 03:25・段階 2 の base-v1・模型 A・test 2026-05〜08 の 4 か月 5,415 レース)
`pipeline/ai/research_walkforward.py --drop '<regex>'` で列群ごと外して同じ物差しで測った。⛔4 か月なので ◎の率は ±0.6pt・回収は ±2pt が誤差の目安。対数損失がいちばん安定。

| 外した群 | 対数損失 | AUC | ◎3着内 | ◎回収 | 判断 |
|---|---|---|---|---|---|
| なし(全 279 列) | 0.4818 | 0.7993 | 72.1% | 83.8% | 基準 |
| レース内の相対値(rel_/rk_・J 章) | **0.4868** | 0.7941 | 71.8% | **81.3%** | ⛔外すと明確に悪化= **効いている** |
| 人物(騎手/調教師/ペア/馬主/生産者/乗替) | **0.4872** | 0.7931 | **71.2%** | 82.9% | ⛔外すと悪化= 効いている |
| コーナー由来(位置・脚質・先行度・惜敗…) | 0.4821 | 0.7991 | 71.6% | 83.3% | 小さく効いている |
| 残差Z(RZ16 相当) | 0.4822 | 0.7988 | 72.1% | 82.8% | 重複が多いが害なし= 残す |
| 提供データ(前半3F・馬具・出遅れ) | 0.4815 | 0.7995 | 72.3% | 84.3% | 差なし(6 場・2026 年だけの列)= 12 か月で再確認 |
| 時計系(tz/tza/自己ベスト/反動) | 0.4828 | 0.7983 | 72.9% | 84.3% | 対数損失は悪化・◎の率は良化= 誤差の範囲。12 か月で再確認 |
| (参考)人気 1 番 | — | — | 74.9% | 80.3% | |

12 か月(15,423 レース)での再確認(03:46)= 提供データを外す: 対数損失 0.4726(基準 0.4727)・◎3着内 73.1%(73.0%)・回収 83.9%(83.8%)= **完全に同じ**(害も益もない= 残す。データが増えれば効きうる)。時計系を外す: 対数損失 **0.4739**(悪化)・◎3着内 73.3%・回収 83.4%= 残す。

木の設定(04:15・12 か月)= 葉 127/学習率 0.03: 対数損失 0.4719(基準 0.4727)・◎3着内 73.1%・回収 82.9%・学習 1.6 倍の時間 / 葉 31/列 50%: 0.4722・73.2%・83.2%。どちらも対数損失の差は 0.001 未満で ◎の回収はむしろ下= **今の設定(葉 63・学習率 0.05・850 反復)のまま**(朝便の学習時間 7.7 分を増やさない)。

結論(9/8)= **列は削らない**。誤差の範囲で動く群を追いかけると閾値探しと同じ罠になる(教訓 5)。削るなら 12 か月で対数損失が改善する群だけ。


## J. Fable(5.1)の追加提案 — 段階 2 で採る(9/7・ユーザー「5.1 ならどう作るか」への答え)

段階 1 の SQL には影響しない(列が増える方向だけ)。段階 2(学習)の設計に入れる。
1. **学習の単位をレースにする**= 「1 頭ずつ 3 着以内か」の 2 値でなく、**レース内ランキング学習**(LightGBM lambdarank か レース内 softmax の条件付きロジット)。出力はレースごとに合計 1 の勝率。印と回収率の計算がそのまま。2 値の `y_top3` は比較用に残す。
2. **市場を敵にする**= 予想家を 2 人置く。①基礎(市場を見ない・今の設計)②**市場アンカー**(市場の確率を log-odds のオフセットにして差分だけ学習・旧ビューアで最良だった型)。物差しは「1 番人気に勝つ」でなく「**市場の確率より対数損失が小さいか**」と、控除率(地方 約 25%)込みの購入シミュレーション(ケリー分数)。第 1 版の市場= `popularity` の人気帯(G 章)、倍率版は履歴が溜まってから。
3. **相対化**= 各特徴量に「レース内順位」「レース内平均との差」「最大との差」を機械的に足す。展開 §99a から「逃げ馬の頭数」を作り、各馬の脚質と掛け合わせる(ペースの読み)。
4. **うちにしか無い材料を 2 歳戦に**= 過去走の無い馬は 能検タイム・せり価格・血統・馬主/生産者 で埋める。高知は前半3F 実測と区間ラップ。乗替の意味(初コンビ・上位騎手へ)・馬具変更・転厩初戦・距離変更・休み明け日数×厩舎の休み明け成績。
5. **評価の作法を先に固定**= 時系列の交差検証(2023→2024→2025 を順に検証)・レース単位の対数損失/Brier・場ごとの表・購入シミュレーション。⛔B/C はこれが無かった。
6. **変えない**= LightGBM・直前時点・穴あけ・凍結・データ量。
到達点の現実= 全場で市場に勝つのは無理。狙いは 高知(自前 3F)・2 歳戦(能検・せり)・少頭数の場。予想家を複数持つ意味はここ。

## 付録: 参照した実測値の一覧(すべて SELECT のみ)

| 対象 | 実測値 |
|---|---|
| `nar_runs` | 604,037 行・2022-11-01 〜 2026-09-09 |
| `nar_races` | 59,305 行・同期間 |
| `nar_races.corners` が空でない | **52,042(87.8%)** |
| `nar_races.furlongs` が空でない | **13,541(22.8%)** |
| `nar_races.prize_yen` / `going` / `weather` / `race_kind` | **59,305(100%)** |
| `nar_races.race_last3f` | 52,038(87.7%) |
| `nar_runs.body_weight` / `time_sec` / `popularity` / `last3f` | 594,559 / 590,676 / 592,719 / 528,200 |
| `nar_runs.birth_date` / `gate` / `carried_weight` / `trainer` | **604,037(100%)** |
| `nar_runs.weight_mark` | 84,996(14.1%) |
| `nar_horses` | 32,803 頭(sire / dam / broodmare_sire / owner / breeder) |
| `nar_kb_runs` | 42,264 行・2026-01-01 〜 09-04・6 場。first3f 29,968・gear 11,200・**blinker 0**・園田 first3f **82** |
| `nar_odds_ticks` | **4,419 行・2026-09-02 〜 09-07** |
| `nar_race_odds` | 695 行・2026-08-23 〜 |
| `nar_person_stats` | 10,341 行(jockey/trainer/sire/bms × all/2025/2026) |
| `nar_race_level` | 58,071 行 |
| DB 全体 / public | **829 MB / 816 MB**(最大は nar_runs 255MB・nar_jc_runs 164MB) |
| `refresh_nar_jc()` の実測 | **181 秒**で 590,230 走 → 4 表(#513) |
| FEATURES183 の順序 SHA | 手元で再計算し `712FCC21…F272` と**完全一致** |

---

### お知らせ文

⛔ 本タスクは設計書の下書きのみで、本番に出た変更はありません。お知らせ文は不要です。

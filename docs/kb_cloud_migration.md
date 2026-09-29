# 競馬ブックの 2 段を PC タスクから Actions へ(2026-09-29・枝 kb-cloud)

## 移した段(PC daily_update.py 119〜125 行)
| PC の段 | cloud の手順(.github/workflows/kb-daily.yml) | 書き先(apply=1 のときだけ) |
|---|---|---|
| 馬具 6場 成績 `fetch_kb_all.py --since 7日前 --what seiseki --track 門別,大井,船橋,川崎,浦和,園田` | gear six tracks seiseki | (手元 /tmp/kbdata/kb_all) |
| 馬具 投入 `push_kb_runs.py --since 7日前` | gear push(apply 空= `--dry-run`) | nar_kb_runs |
| 中央戦績 `fetch_jra_runs.py --dates 今日,明日,明後日 --collect-cards --push` | jra runs(apply 空= `--push` なし= dry-run) | nar_jra_runs・nar_jra_horses・nar_job_heartbeat |

- 起動は workflow_dispatch だけ(cron なし)。入力 apply= 空なら本番 DB に書かない(読むのは nar_runs・nar_jra_horses)。
- TZ=Asia/Tokyo(台本の「今日」・7 日前・3 日分を JST で)。

## 台本 cloud/kb/(PC scraper の 9/29 版の写し)
写したもの: keibabook.py・fetch.py・parsers.py・nouryoku_semantics.py・fetch_kb_all.py・push_kb_runs.py・fetch_jra_runs.py・jra_runs.py。
直したのは PC 固有の所だけ(挙動は変えない):
- 保存先: fetch.py・push_kb_runs.py・fetch_jra_runs.py の `DATA` を環境変数 `KB_DATA_DIR`(便では /tmp/kbdata)に。未設定なら元どおり。
- 鍵: push_kb_runs.py・fetch_jra_runs.py の `read_env()` は環境変数 `SUPABASE_URL` があればそれを使う(secrets NAR_SUPABASE_URL / NAR_SUPABASE_SERVICE_KEY)。鍵の欠けのメッセージから PC のパスを外した。
- 競馬ブックのログイン: secrets KEIBABOOK_LOGIN_ID / KEIBABOOK_PASSWORD(fetch.load_env は .env が無ければ何もしない)。
- fetch_jra_runs.py: 失敗の種類を件数だけ出す 1 行を足した(下の「未解決」)。
- 足したもの: kb_counts.py(runs_*.json を 日×場 の件数にまとめる・照合用)。
- 行末は LF にそろえた(jra_runs.py が CRLF だった)。

## 「取得済みの印」(done.tsv)= actions/cache を選んだ
- 選んだ: done.tsv だけを actions/cache で持ち越す(restore は毎回・save は apply=1 のときだけ)。
- 理由: ① PC の判定(その日の R が全部そろい・備考も載った日だけ済み・今日は済みにしない・備考は 7 日まで取り直す)を**そのまま**使える。DB の nar_kb_runs から判定し直すと「着順はあるが備考が空」「元から備考の無い R」を DB の行から見分けられず、挙動が変わる。② done.tsv の中身は日付・場の組・件数だけ= public でも出してよい。③ cache が消えても 7 日分を全部取り直すだけ(安全側・約 8 分)。
- dry-run で save しない理由: dry-run で「済み」にすると次の apply がその日を飛ばし、書かないまま終わるため。
- 頁の HTML・Cookie・runs_*.json・CSV は /tmp/kbdata に置くだけ(cache・artifact に入れない)。ログは件数とレースID だけ。

## 試しの 1 回(apply 空)
- run: https://github.com/maguronagareboshi-arch/nar-jobs/actions/runs/36546198817 (成功・約 21 分= 馬具 8 分・中央 13 分)
- master に無い workflow は dispatch できないので、枝への push で 1 回だけ起動した(コミット 53abbd3 で付けて、次のコミットで外した)。

### 馬具(日×場・PC は data/kb_all/runs_*.json を同じ kb_counts.py で数えた)
| 日 | 場 | 行 PC/cloud | 馬具あり | 出遅れ | 前半3Fあり | 送る行 |
|---|---|---|---|---|---|---|
| 0922 | 浦和 | 142/142 | 38/38 | 26/26 | **115/105** | 142/142 |
| 0922 | 門別 | 135/135 | 32/32 | 9/9 | 132/132 | 135/135 |
| 0923 | 園田・浦和・門別 | 125・145・127 同じ | 同じ | 同じ | 同じ | 同じ |
| 0924 | 園田・浦和・門別 | 121・130・116 同じ | 同じ | 同じ | 同じ | 同じ |
| 0925 | 園田 | 122/122 | **30/33** | 17/17 | 0/0 | 122/122 |
| 0925 | 浦和 | 131/131 | 26/26 | 14/14 | 92/92 | 131/131 |
| 0928 | 船橋 | 133/133 | 33/33 | 9/9 | 133/133 | 133/133 |
| 0929 | 船橋・門別 | 24・32 / 85・76 | 0/11 | 0/7 | 0/52 | 56/161 |

- 0929 の差は時刻の差(PC は 13:00 便・cloud は 18:00 = 後の R の結果が入った)。
- 0925 園田 馬具 +3: 備考が後から載った分(PC は 9/25 の済みの後で取り直していない= cloud の方が新しい)。
- 0922 浦和 前半3F −10: 要確認。PC の runs_ は何回もの便の足し合わせ(None で上書きしない)。cloud は 1 回きり。前半3F が伏せ字の頁が 1 便に 1 回の再ログイン後も残った R の分とみられる(ログの伏せ字 54 行)。nar_kb_runs は merge-duplicates なので、cloud の None が PC の値を消すかは列ごと(PostgREST は送った列を上書きする)= **apply 前に要判断**。

### 中央戦績
| | PC(13:00 便・push) | cloud(18:00・dry-run) |
|---|---|---|
| 出馬表のレース | 165(船橋36 金沢11 水沢12 名古36 門別36 園田24 佐賀10) | 165 同じ |
| 能力表を新たに | 58 頁(残りは PC に JSON あり) | 165 頁(毎回全部) |
| 出馬表の馬 | 1,162 | 1,783(佐賀・後から出た明後日分などが増えた) |
| 対象 | 29(push 済み) | 56(PC の 29 は取得済みで外れる) |
| 失敗 | 0 | **18** |

## 未解決
1. 中央戦績の失敗 18/56: 種類がログに無かった。船橋 ① 17 頭など新馬が多く、馬の頁に走が無い `no_kanzendata_blocks`(失敗に数えるが翌日は取り直さない)の見込み。次の 1 回で「失敗の種類」行を見て確かめる。
2. 0922 浦和 前半3F −10 行(上)= apply で PC の値を None で上書きしないか。
3. apply=1 と cron は未。PC タスクの 2 段を止めるのと同時に(両方で書かない)。master へ merge しないと dispatch できない。
4. 所要 約 21 分/回(能力表を毎回 165 頁取るため。PC は 58 頁)。

## 続き(2026-09-29 夜・run https://github.com/maguronagareboshi-arch/nar-jobs/actions/runs/36551419393 ・成功・apply 空)
- 空で上書きしない: cloud の push_kb_runs.py は送る前に nar_kb_runs のその日の既存行を読み(読むだけ)、送る値が空で既存に値がある列(horse_name・kb_race_id・blinker・gear・first3f・avg_f・pace・kimete・start_note)は既存を残す。PC の台本は変えていない。単体テスト cloud/kb/test_push_kb_runs.py 3 件(便の最初でも流す)。
- dry-run で既存を残した値= 23(0922: pace 12・first3f 10 / 0925: gear 1 / ほかの日 0)。0922 浦和 前半3F −10 はこれで既存が残る。
- 中央戦績の失敗 18= 全部 no_kanzendata_blocks(馬の頁に走が無い)。失敗に数える扱い(`ok= fetch_error が空`)と「翌日は取り直さない」扱いは PC と同じコードの写し= 差なし(PC の 13:00 便は該当馬が 0 頭だっただけ)。

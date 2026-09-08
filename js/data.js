// js/data.js — データ層(統一モデル)。docs/DESIGN.md §1〜§3 の契約を実装する。
// ・Supabase は anon キーで GET するだけ(書き込み API は呼ばない)
// ・川崎・浦和の5年分は yukochi.com の静的 gzip アーカイブを DecompressionStream で読む
// ・ページは本モジュール以外から fetch しない。ui/router は import しない(§71: race-phase は純関数なので可)

import { phaseOf } from './race-phase.js';
// §26.4 競馬ブック表記の調教師名 → 公式表記の対応表(349名・pipeline/build_trainer_map.py の生成物)
import { TRAINER_MAP } from './trainer-map.js';
import { JOCKEY_MAP } from './jockey-map.js';

const SUPABASE_URL = 'https://jcrcftvrsgmsewwdkqha.supabase.co';
// 公開 anon キー(keiba-deploy/modules/app-main.js の SUPABASE_KEY と同一)
const SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjcmNmdHZyc2dtc2V3d2RrcWhhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4MDY0NjgsImV4cCI6MjA5NjM4MjQ2OH0.UED2rJNsuTPqofrhhNhQ2RM0NKc2eJ6qHllfbnebMe0';
const TIMEOUT_MS = 12000;          // §1.1: 1回あたり 12 秒(リトライ込みで最長 24 秒。文言には秒数を出さない)
const KOCHI_BABA = '31';

// 第2プロジェクト nar-official(全15場の公式結果 nar_*)。anon キーは公開キー(閲覧専用・RLS で select のみ)
const NAR_URL = 'https://qgsnsdjvzzeazbazjlwa.supabase.co';
const NAR_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFnc25zZGp2enplYXpiYXpqbHdhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc0MTg0NDIsImV4cCI6MjEwMjk5NDQ0Mn0.a4pjf8WKgcVGL3d8ZBdP4dJDpnDkM2EnKofnXdHE2I8';

// §1.4: yukochi.com/viewer-data は Access-Control-Allow-Origin: * を返した(2026-08-23 curl 実測)ので ON
const ARCHIVE_ENABLED = true;
const ARCHIVE_BASE = 'https://yukochi.com/viewer-data/';
// 静的アーカイブ(yukochi.com/viewer-data/)を持つ場。2 家族ある:
//  - 川崎・浦和 = Supabase に無いので**今のデータ源**(2021-08〜今日)
//  - §28.1b の9場 = 過去5年ぶんだけ(2018-01〜2022-10)。2022-11 以降は公式(nar_*)にあるので競合しない
const ARCHIVE_LIVE = ['kawasaki', 'urawa'];
const ARCHIVE_HIST = ['morioka', 'mizusawa', 'kanazawa', 'kasamatsu', 'nagoya', 'sonoda', 'himeji', 'saga', 'obihiro'];
const ARCHIVE_PREFIXES = [...ARCHIVE_LIVE, ...ARCHIVE_HIST];
// 9場のアーカイブが持っている最後の日(実測。索引1つが 60〜115KB あるので、
// この日より後を見ているときは9場ぶんの索引を取りに行かない=トップや当日の結果一覧で 11本→2本)
const ARCHIVE_HIST_UNTIL = '2022-10-31';
// 前後の開催日さがし用の余裕。公式 DB は 2022-11-01 から毎日どこかで開催しているので、
// そこから2か月離れた日付では9場のアーカイブが「前後の開催日」の答えになることはない
const ARCHIVE_HIST_EDGE = '2022-12-31';
// 公式(nar_*)がある最初の日(実測: nar_races の最古が 2022-11-01)。
// これより前の日付では公式に必ず何も無いので、補完のクエリを投げない(§28.1b でアーカイブの日を開けるようになったため)
const NAR_FROM = '2022-11-01';

// その日付で索引を見に行く価値がある場だけ返す
function archivePrefixesFor(date, edge) {
  return isDateStr(date) && date > (edge || ARCHIVE_HIST_UNTIL) ? ARCHIVE_LIVE : ARCHIVE_PREFIXES;
}

// §14.2 公式レース映像(NAR公式プレーヤー)。track スラッグは prefix と同じだが高知だけ 'kouchi'
const VIDEO_BASE = 'https://keiba-lv-st.jp/movie/player';
const VIDEO_SLUG = new Map([['kochi', 'kouchi']]);

// §11: 独自データ(高知のパドック索引・前半3F の出自)。§98/§98b(2026-09-04)で配り元を
// yukochi.com の静的ファイルから **nar_meta** へ移したので、yukochi.com へは1本も出さない
// (OWN_BASE / ownFetch は廃止。ARCHIVE_BASE=川崎浦和アーカイブだけが yukochi.com に残る)。
// R2 の動画・ポスターは URL を組み立てて <video> に渡すだけ(R2 は CORS 無しなので fetch で存在確認しない)
// §11.2 / PROJECT.md「例外: 開発用の表示切替」: 競馬ブック由来のもの(厩舎の話・調教・能検の寸評)は閲覧者に出さない(ユーザー決定 2026-08-23)。
// §58: 本文の表(chihou_danwa/chihou_cyokyo)は 2026-08 に DB 権限で anon から閉鎖。管理者だけが
// 高知 Worker の admin read 経路(X-Write-Token 検証)で読む。トークンは localStorage 'viewer_admin' に
// 管理者が自分で入れる(DevTools コンソールで localStorage.viewer_admin='…'・消せば閲覧者と同じ)。
// ⛔旧 ?dev=1 は廃止(Codex検品A2): URL/localStorage はアクセス制御にならない。フラグを立てても
//   トークンが合わなければ Worker が 401 を返すので、閲覧者には何も見えない
const ADMIN_WORKER = 'https://keiba-proxydeploy.maguronagareboshi.workers.dev';
function adminToken() {
  try { return String(localStorage.getItem('viewer_admin') || ''); } catch { return ''; }
}
export const FLAGS = { dev: !!adminToken(), keibabookText: false };
FLAGS.keibabookText = FLAGS.dev;   // 管理者のときだけ文章(厩舎の話・調教短評・能検の寸評)も返す。閲覧者は常に false
// 管理者読み取り(トークン無しなら null)。Worker が表・列を固定しているので path はこの2種類だけ
async function adminGet(path) {
  const token = adminToken();
  if (!token) return null;
  const res = await fetch(ADMIN_WORKER + path, { headers: { 'X-Write-Token': token } });
  if (!res.ok) throw new Error(`admin read ${res.status}`);
  return res.json();
}
// 能検(デビュー前の試験)を持っている地区。
// §117b で **13地区すべてが主催者公式(nar-official の nar_meta)**になった。
// ⛔競馬ブック由来(旧DB chihou_meta)の経路は空にした= 行に競馬ブックの馬ID(horse_id)は入らない。
//   馬ページとの接続は NAR 8 地区と同じ「馬名(+生年月日)」の索引(nar_meta noken_index)だけを通る。
// ⚠この配列を空にすると、下の nokenOf / getNokenLinks(競馬ブック ID の経路)は**呼ばれない**。
//   道を消すのは切替が本番で落ち着いてから(⛔切替と同時に2つ変えない)。
export const NOKEN_CHIHOU = [];
// §32d PDF勢3場(笠松・名古屋・高知)を追加=12地区。nar_meta の鍵は `<prefix>_noken` なので、
// 高知は競馬場 prefix と同じ 'kochi' のまま鍵が 'kochi_noken' になり、URL も /noken/kochi で衝突しない。
// §32f 金沢を追加=**13地区**で能検は全国そろった(能検を実施している主催者は全部入っている)
// §117b 門別・大井・船橋・川崎・浦和を cloud(主催者公式)へ移してここに足した
const NOKEN_NAR = ['iwate', 'hyogo', 'saga', 'banei', 'kasamatsu', 'nagoya', 'kochi', 'kanazawa',
  'monbetsu', 'ooi', 'funabashi', 'kawasaki', 'urawa'];
export const NOKEN_PREFIXES = [...NOKEN_CHIHOU, ...NOKEN_NAR];
// §33.7-3 日単位の動画をレース別に頭出しできる場(`{prefix}_noken_offsets` がある)。
// 南関の能検は1日1本の通し動画で、各レースの開始秒だけを別に持っている(動画は再ホストしない)。
// §117b 大井を追加(主催者が動画の説明欄に章「0:00 第1組」を書いている。川崎・船橋は章が無い)
// §117c 兵庫(園田)を追加= nar_meta 側。⛔クリップは作らないので CLIP_DISTRICTS には入れない
const NOKEN_OFFSETS = ['kawasaki', 'urawa', 'ooi', 'hyogo'];
// nar_meta 組は「地区」なので競馬場と1対1ではない(岩手は1日に盛岡と水沢が同居する)。
// venues = その地区の競馬場ページ(導線に使う。西脇は調教場なので 15場には無い)
const NOKEN_DISTRICTS = {
  iwate: { name: '岩手(盛岡・水沢)', venues: ['morioka', 'mizusawa'] },
  hyogo: { name: '兵庫(園田・西脇)', venues: ['sonoda', 'himeji'] },
  saga: { name: '佐賀', venues: ['saga'] },
  banei: { name: 'ばんえい帯広', venues: ['obihiro'] },
  kasamatsu: { name: '笠松', venues: ['kasamatsu'] },
  nagoya: { name: '名古屋', venues: ['nagoya'] },
  kochi: { name: '高知', venues: ['kochi'] },
  kanazawa: { name: '金沢', venues: ['kanazawa'] },
  // §117b 1場1地区(名前は競馬場と同じ)。⛔騎手・調教師は公式の略記なので**字のまま出す**
  //   (official: true。他の8地区と同じ扱い= 存在しない人ページへ飛ばさない)
  monbetsu: { name: '門別', venues: ['monbetsu'] },
  ooi: { name: '大井', venues: ['ooi'] },
  funabashi: { name: '船橋', venues: ['funabashi'] },
  kawasaki: { name: '川崎', venues: ['kawasaki'] },
  urawa: { name: '浦和', venues: ['urawa'] },
};

// 能検の地区1件 → { prefix, name, venues }。対象外は null
export function nokenDistrict(prefix) {
  const p = String(prefix ?? '');
  // official = 主催者公式のぶん(名前が元から公式表記・馬IDが無い)
  const d = NOKEN_DISTRICTS[p];
  if (d) return { prefix: p, name: d.name, venues: d.venues.slice(), official: true };
  if (!NOKEN_CHIHOU.includes(p)) return null;
  const v = VENUE_BY_PREFIX.get(p);
  return v ? { prefix: p, name: v.name, venues: [p], official: false } : null;
}

// 競馬場 → その場の能検がある地区(競馬場ページの導線用)。無ければ null
export function nokenPrefixFor(venuePrefix) {
  const p = String(venuePrefix ?? '');
  if (NOKEN_CHIHOU.includes(p)) return p;
  for (const k of NOKEN_NAR) {
    if (NOKEN_DISTRICTS[k].venues.includes(p)) return k;
  }
  return null;
}
const BIAS_PREFIXES = ['monbetsu', 'ooi', 'funabashi'];                           // {prefix}_stats.corner4_inout がある場

// ---------------------------------------------------------------- 定数

// code = 競馬ブックの場コード(race_id の [6:8])。babaCode = 公式サイトの k_babaCode(§13.1。競馬ブックの code とは別物)
// §116a pref = 競馬場のある都道府県(/venues の一覧に出す)。⛔並び(order)は北から= 一覧もこの順で出す
export const VENUES = [
  { code: '58', prefix: 'obihiro',   name: '帯広', supported: 'nar',    babaCode: '03', order: 0, banei: true, pref: '北海道' },
  { code: '42', prefix: 'monbetsu',  name: '門別', supported: 'chihou', babaCode: '36', order: 1, pref: '北海道' },
  { code: '33', prefix: 'morioka',   name: '盛岡', supported: 'nar',    babaCode: '10', order: 2, pref: '岩手県' },
  { code: '29', prefix: 'mizusawa',  name: '水沢', supported: 'nar',    babaCode: '11', order: 3, pref: '岩手県' },
  { code: '13', prefix: 'urawa',     name: '浦和', supported: 'chihou', babaCode: '18', order: 4, pref: '埼玉県' },
  { code: '12', prefix: 'funabashi', name: '船橋', supported: 'chihou', babaCode: '19', order: 5, pref: '千葉県' },
  { code: '10', prefix: 'ooi',       name: '大井', supported: 'chihou', babaCode: '20', order: 6, pref: '東京都' },
  { code: '11', prefix: 'kawasaki',  name: '川崎', supported: 'chihou', babaCode: '21', order: 7, pref: '神奈川県' },
  { code: '20', prefix: 'kanazawa',  name: '金沢', supported: 'nar',    babaCode: '22', order: 8, pref: '石川県' },
  { code: '19', prefix: 'kasamatsu', name: '笠松', supported: 'nar',    babaCode: '23', order: 9, pref: '岐阜県' },
  { code: '34', prefix: 'nagoya',    name: '名古屋', supported: 'nar',  babaCode: '24', order: 10, pref: '愛知県' },
  { code: '37', prefix: 'sonoda',    name: '園田', supported: 'nar',    babaCode: '27', order: 11, pref: '兵庫県' },
  { code: '39', prefix: 'himeji',    name: '姫路', supported: 'nar',    babaCode: '28', order: 12, pref: '兵庫県' },
  { code: '26', prefix: 'kochi',     name: '高知', supported: 'kochi',  babaCode: '31', order: 13, pref: '高知県' },
  { code: '23', prefix: 'saga',      name: '佐賀', supported: 'nar',    babaCode: '32', order: 14, pref: '佐賀県' },
];
// ばんえい(そりを曳く 200m 直線)は帯広だけ。省略した行にも false を入れる(ページが venue.banei をそのまま見られるように)
for (const v of VENUES) v.banei = v.banei === true;

export const TICKET_LABELS = {
  win: '単勝', place: '複勝', quinella: '馬連', exacta: '馬単', wide: 'ワイド', trio: '三連複', trifecta: '三連単',
  bracket_quinella: '枠連', bracket_exacta: '枠単',      // nar_payouts で出得る種別(表示順は TICKET_ORDER の末尾扱い)
};
export const TICKET_ORDER = ['win', 'place', 'quinella', 'exacta', 'wide', 'trio', 'trifecta'];
// §50 V-5 払戻ボードの並び= **場内の掲示板と同じ順**(枠の2つは複勝の次)。⛔券種の並びの知識はこの2つだけ(§5.4)。
// ⚠実測(2026-08-28・3期間×1000レース): 公式の払戻に **枠連・枠単は1件も無い**ので、その2行は
// 「その回に実際にあるときだけ」出す(いつも「発売なし」と書くと、売られていないと断言することになる)
export const TICKET_BOARD_ORDER = ['win', 'place', 'bracket_quinella', 'bracket_exacta',
  'quinella', 'exacta', 'wide', 'trio', 'trifecta'];
// §46 T4 その日の結果一覧に持ち帰る券種。**三連単を足した**(payouts 列は丸ごと取っているので通信は増えない)。
// ⚠三連単が無い回(ばんえい等)は行が来ないだけ=画面は単複だけを出す
const NAR_FLASH_TICKETS = ['win', 'place', 'trifecta'];
// §14: nar_person_stats.kind。ページの並び順(騎手→調教師)も兼ねる
export const PERSON_KINDS = ['jockey', 'trainer'];
export const PERSON_LABELS = { jockey: '騎手', trainer: '調教師' };
// §105 `nar_person_stats` に行がある種別。⛔PERSON_KINDS(上の検索窓が回る種別)とは別物=
//   種牡馬・母父は**名前検索の対象にしない**(同じ名前の馬と紛れるため)。getPerson だけが通す
export const STATS_KINDS = [...PERSON_KINDS, 'sire', 'bms'];
export const SIRE_LABELS = { sire: '種牡馬(父)', bms: '母父' };
// §16: トップ「本日の勝負レース」に出す件数
export const KACHI_MAX = 5;
// §15.3: いま画面に出している印のモデル。本命の予想AIが来たらこの2つを差し替えるだけで表示が移る
export const AI_PRIMARY_MODEL = 'base-v0';
export const AI_PRIMARY_LABEL = '仮運用(公式データの単純スコア)';
// §23.3 閲覧者に見せてよい印のモデル(**明示の許可制**)。/record の切替はこの表の中からしか出さない。
// ⛔2026-08-28 の事故: getAiModels() が nar_ai_record にある model をそのまま並べていたため、
//   承認前の M60 影モデル(m60-mask183-b/c-shadow-v1)が本番 /record に切替ボタンとして出て、
//   1レースだけの「通算成績 ◎勝率0.0% 0/1R」を閲覧者に見せていた(DB実測で確認)。
//   nar_ai_marks 側の4本は全て model=eq. で絞っていて無事だったが、ここだけ素通りだった。
//   DB は「誰が書いてもよい」前提で作る(凍結は nar_ai_marks_guard トリガーが守る)。
//   **公開してよいかは画面側のこの表だけで決める**=この表に足す行為が昇格の承認そのもの。
export const AI_PUBLIC_MODELS = [AI_PRIMARY_MODEL];
// §122 レース画面の「AIの見立て」で切り替えられるモデル(**画面の切替だけ**)。
// ⛔これは成績公開の許可ではない= AI_PUBLIC_MODELS(/record の並び)には足さない。B/C は評価中の影モデル。
export const AI_MODELS_SELECTABLE = [
  { id: AI_PRIMARY_MODEL, label: 'base' },
  { id: 'm60-mask183-b-shadow-v1', label: 'B' },
  { id: 'm60-mask183-c-shadow-v1', label: 'C' },
  { id: 'base-v1', label: 'v1' },   // §129e 2026-09-08〜 影運用(LightGBM・Actions の朝便が書く)。公開は F 章のゲート後
];
// 印の並び(集計もこの4つを見る)
export const AI_MARKS = ['◎', '○', '▲', '△'];

const VENUE_BY_PREFIX = new Map(VENUES.map((v) => [v.prefix, v]));
const VENUE_BY_NAME = new Map(VENUES.map((v) => [v.name, v]));
const VENUE_BY_CODE = new Map(VENUES.map((v) => [v.code, v]));

// nar_runs の走歴(全15場)を場 prefix に落とすときの別名。帯広は公式表記が '帯広ば'
const NAR_TRACK_ALIAS = new Map([['帯広ば', 'obihiro']]);
// 逆引き(prefix → 公式場名)。nar_venue_stats.track など公式表記で引くときに使う(§12.3)
const NAR_TRACK_NAME = new Map([...NAR_TRACK_ALIAS].map(([track, prefix]) => [prefix, track]));
function narTrackName(v) { return NAR_TRACK_NAME.get(v.prefix) ?? v.name; }
// §1.6 / §13.2A: nar_* を出馬表・結果の源にする9場(帯広ばを含む)。既存6場は競馬ブック/高知が主で nar は補完(§13.2B)
const NAR_TRACKS = VENUES.filter((v) => v.supported === 'nar').map(narTrackName);

// ---------------------------------------------------------------- ユーティリティ(同期)

export function todayJST() {
  const t = new Date(Date.now() + 9 * 3600 * 1000);
  return `${t.getUTCFullYear()}-${pad2(t.getUTCMonth() + 1)}-${pad2(t.getUTCDate())}`;
}
export function listVenues() { return VENUES.map((v) => ({ ...v })); }
export function venueByPrefix(prefix) { const v = VENUE_BY_PREFIX.get(String(prefix ?? '')); return v ? { ...v } : null; }
export function venueByName(name) { const v = VENUE_BY_NAME.get(String(name ?? '').trim()); return v ? { ...v } : null; }

function pad2(n) { return String(n).padStart(2, '0'); }
// 'YYYY-MM-DD' の形 **かつ 実在する日** だけ通す。
// 形だけ見ていたので /race/monbetsu/9999-99-99/1 のような URL 直打ちがそのまま DB へ飛び、
// 400 とコンソールエラーになっていた(2026-08-26 SEO 修繕で実測)
export function isDateStr(d) {
  const s = String(d ?? '');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const t = new Date(s + 'T00:00:00Z');
  return !Number.isNaN(t.getTime()) && t.toISOString().slice(0, 10) === s;
}
function toKochiDate(d) { return d.replace(/-/g, '/'); }     // 'YYYY-MM-DD' → 'YYYY/MM/DD'(data.js 内だけ)
function fromKochiDate(d) { return String(d ?? '').replace(/\//g, '-'); }
function addDays(d, n) {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + n);
  return `${t.getUTCFullYear()}-${pad2(t.getUTCMonth() + 1)}-${pad2(t.getUTCDate())}`;
}
// レース映像の URL(日付は YYYYMMDD)。日付・レース番号が読めなければ null
function videoUrlOf(prefix, date, no) {
  const n = Number(no);
  if (!VENUE_BY_PREFIX.has(prefix) || !isDateStr(date) || !Number.isInteger(n) || n < 1) return null;
  return `${VIDEO_BASE}?date=${date.replace(/-/g, '')}&race=${n}&track=${VIDEO_SLUG.get(prefix) ?? prefix}`;
}

function prefixFromRaceId(raceId) {
  const v = VENUE_BY_CODE.get(String(raceId ?? '').slice(6, 8));
  return v ? v.prefix : null;
}

// ---------------------------------------------------------------- §2.9 型変換

function zenToHan(s) {
  return s.replace(/[０-９．－]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xFEE0));
}
function num(v) {
  if (v === null || v === undefined || v === '') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const n = Number(zenToHan(String(v)).trim());
  return Number.isFinite(n) ? n : null;
}
function str(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s === '' ? null : s;
}
function timeStr(v) {
  const s = str(v);
  if (!s) return null;
  return s.replace(/^(\d+)\.(\d{2}\.\d)$/, '$1:$2');       // '1.12.3' → '1:12.3'
}
function marginStr(v) {
  const s = str(v);
  return s ? s.replace(/(\d)\.(\d\/\d)/, '$1 $2') : null;   // '2.1/2' → '2 1/2'
}
function sexAgeStr(v) {
  const s = str(v);
  return s ? s.replace(/[\s　]+/g, '') : null;
}
function distNum(v) {
  const s = str(v);
  if (!s) return null;
  const m = zenToHan(s).match(/\d+/);
  return m ? Number(m[0]) : null;
}
function kochiWeight(v) {
  const m = (str(v) || '').match(/^(\d+)(?:\(([+-]?\d+)\))?$/);
  if (!m) return { bodyWeight: null, bodyWeightDiff: null };
  return { bodyWeight: Number(m[1]), bodyWeightDiff: m[2] === undefined ? null : Number(m[2]) };
}
function lapsOf(v) {
  if (Array.isArray(v)) return v.map(num).filter((x) => x !== null);
  const s = str(v);
  if (!s) return null;
  try {
    const a = JSON.parse(s);
    return Array.isArray(a) ? a.map(num).filter((x) => x !== null) : null;
  } catch { return null; }
}

// Entry.scratchKind(ユーザー決定 2026-08-23): 出走取消 / 競走除外 / 競走中止 / 失格 を区別する。
// 由来の文字は 他場 '取消'/'除外'/'中止'・高知 chakujun '取消'/'除外'・nar '出走取消'/'競走除外'/'競走中止'/'失格' なので部分一致で読む
function scratchKindOf(text) {
  const s = str(text);
  if (!s) return null;
  if (s.includes('取消')) return '取消';
  if (s.includes('除外')) return '除外';
  if (s.includes('中止')) return '中止';
  if (s.includes('失格')) return '失格';
  return null;
}
// 出走頭数に数えない種別。中止・失格の馬は出走している(ゲートを出ている)ので頭数に含める
function nonStarter(kind) { return kind === '取消' || kind === '除外'; }

// §Codex B3 成績の分母から外す注記か(「出走取消」「競走除外」)。
// ⛔夜間集計 `pipeline/sql/ai_record.sql` の `where coalesce(u.finish_note,'') !~ '取消|除外'` と
//   **同じ規則**を画面側でも使うための共有の判定(SQL は触らない= 一覧・トップ・§46 が同じ集計を見ている)。
// ⚠「競走中止・失格」は**買えている**(=買って外れた)ので外さない。取り違えると逆向きにずれる
export function isScratched(note) { return nonStarter(scratchKindOf(note)); }

// 前半タイムの区間(F 数)。他場 chihou_results.first3f は 1200m 未満だと「距離−600m の通過」(=走破タイム−上がり3F)なので
// 1100m=2.5F・1000m=2F・900m=1.5F・800m=1F。1200m 以上は 3F。距離不明は null(高知は呼ばず常に 3)
function first3fFOf(distance) {
  const d = num(distance);
  if (d === null) return null;
  if (d >= 1200) return 3;
  const f = (d - 600) / 200;
  return f > 0 ? f : null;
}
// 1200m 未満で first3f が無いとき 走破タイム−上がり3F で補う(同じ意味の値。2026-08-23 門別 1000m で一致を確認)。1200m 以上は補わない
function fillFirst3f(first3f, timeSec, last3f, distance) {
  const f = num(first3f);
  if (f !== null) return f;
  const d = num(distance), t = num(timeSec), l = num(last3f);
  if (d === null || d >= 1200 || t === null || l === null || t <= l) return null;
  return Math.round((t - l) * 10) / 10;
}

// §11.1 区間の終端ラベル。高知 1300m はポール基準で最初が 100m(半ハロン)、1900m は最後が 300m。それ以外は 200m ごと
function lapMeta(laps, distance) {
  if (!laps || !laps.length) return { lapLabels: null, lapNote: null };
  const n = laps.length;
  const rem = distance === null ? 200 : distance - 200 * (n - 1);
  const first = rem === 100 ? 100 : 200;
  const last = rem === 300 ? 300 : 200;
  const lapLabels = [];
  let acc = 0;
  for (let i = 0; i < n; i++) { acc += i === 0 ? first : (i === n - 1 ? last : 200); lapLabels.push(`${acc}m`); }
  const lapNote = first === 100 ? '最初が100m・以降200mごと' : (last === 300 ? '200mごと・最後が300m' : '200mごと');
  return { lapLabels, lapNote };
}
// §49 U-5 officialLaps = **公式発表のハロンタイム**(nar_races.furlongs)。⛔高知の自前計測(laps)とも
// 競馬ブック由来のラップ(#24 で出さないと決めたもの)とも**別の入れ物**にする(§5.3 出典の規律)
function raceExtra(laps, distance, pace, agari3fRace, sectional, agari4fRace, officialLaps) {
  return {
    laps, pace, agari3fRace, agari4fRace: agari4fRace ?? null,
    officialLaps: officialLaps && officialLaps.length ? officialLaps : null,
    ...lapMeta(laps, distance), sectional,
  };
}
function cloneExtra(x) {
  return {
    ...x,
    laps: x.laps ? [...x.laps] : null,
    officialLaps: x.officialLaps ? [...x.officialLaps] : null,
    lapLabels: x.lapLabels ? [...x.lapLabels] : null,
    sectional: x.sectional ? { ...x.sectional } : null,
  };
}

// §2.8 レース名の正規化
function isCond(s) {
  return /^(サラ|アラ|[0-9０-９]+歳|[２３４]歳)/.test(s) || /^(C|B|A)[0-9１-９]/.test(s);
}
function nameCond(klass, raceName, no) {
  const k = str(klass), r = str(raceName);
  if (k && !isCond(k)) return { name: k, cond: r };
  if (r || k) return { name: r || `${no}R`, cond: k };
  return { name: `${no}R`, cond: null };
}

// ---------------------------------------------------------------- 通信(GET のみ)

function makeError(kind, cause, detail) {
  const msgs = {
    timeout: '通信がタイムアウトしました。もう一度お試しください',
    server: 'データの取得に失敗しました(サーバー側)',
    other: 'データを読み込めませんでした',
  };
  const err = new Error(detail || kind);
  err.userMessage = msgs[kind] || msgs.other;
  err.kind = kind;
  err.cause = cause;
  return err;
}

async function fetchOnce(url, init) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { ...init, signal: ac.signal });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw makeError(res.status >= 500 ? 'server' : 'other', { status: res.status, body, url }, `HTTP ${res.status} ${url}`);
    }
    return res;
  } catch (e) {
    if (e && e.userMessage) throw e;
    if (e && e.name === 'AbortError') throw makeError('timeout', e, `timeout ${url}`);
    throw makeError('other', e, `fetch failed ${url}`);
  } finally {
    clearTimeout(timer);
  }
}

// HTTP 5xx / タイムアウトは 1 回だけリトライ(高知 keiba_horses の初回 statement timeout 対策)
async function fetchRetry(url, init) {
  try {
    return await fetchOnce(url, init);
  } catch (e) {
    if (e.kind === 'timeout' || e.kind === 'server') return fetchOnce(url, init);
    throw e;
  }
}

async function sb(path) {
  const res = await fetchRetry(`${SUPABASE_URL}/rest/v1/${path}`, {
    headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}`, Accept: 'application/json' },
  });
  return res.json();
}

// §1.6: nar_* 専用(sb と同型)。nar_* は必ずこちら経由で引き、chihou_*/keiba_* は sb() のまま(接続先が分かれる予定)
async function sbNar(path) {
  const res = await fetchRetry(`${NAR_URL}/rest/v1/${path}`, {
    headers: { apikey: NAR_KEY, Authorization: `Bearer ${NAR_KEY}`, Accept: 'application/json' },
  });
  return res.json();
}

// §122: sbNar と同型だが**引き直さない**(1 回だけ)。B/C の読みは「自動再試行 0」が契約なので、
//   5xx/タイムアウトを 1 回引き直す fetchRetry を通さない。⛔他の読みはこれまでどおり sbNar
async function sbNarOnce(path) {
  const res = await fetchOnce(`${NAR_URL}/rest/v1/${path}`, {
    headers: { apikey: NAR_KEY, Authorization: `Bearer ${NAR_KEY}`, Accept: 'application/json' },
  });
  return res.json();
}

// 静的 gzip(content-encoding 無しの application/gzip)を展開して JSON に。
// content-encoding ヘッダはクロスオリジンでは読めない(Expose-Headers 無し)ことがあるので、
// 先頭2バイト(0x1f 0x8b)で gzip かどうかを判定する。CDN が透過展開して返してきても壊れない
async function gz(path, cache = 'force-cache') {
  const res = await fetchRetry(`${ARCHIVE_BASE}${path}`, { cache });
  const buf = await res.arrayBuffer();
  const u8 = new Uint8Array(buf);
  const isGzip = u8.length >= 2 && u8[0] === 0x1f && u8[1] === 0x8b;
  if (!isGzip) return JSON.parse(new TextDecoder().decode(buf));
  if (typeof DecompressionStream !== 'function') {
    throw makeError('other', null, 'DecompressionStream unavailable');
  }
  return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
}

const enc = encodeURIComponent;

// 検索語からフィルタ構文を壊す字を落とす。⛔`*` と `%` は ilike のワイルドカード= 残すと
//   利用者の打った字が「何にでも当たる」に化ける。⛔規則はここ1か所(§5.4・§14 の検索と同じ)
function cleanKw(v) {
  return String(v ?? '').trim().replace(/[,()*%_"\\]/g, '');
}
const quoteIn = (ids) => ids.map((s) => `"${String(s).replace(/"/g, '')}"`).join(',');
const chunk = (arr, n) => { const out = []; for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n)); return out; };
// 束ねたクエリの結果を鍵ごとに分ける(§24.1-2)。filter を回すより速く、書き方もそろう
function groupBy(rows, keyOf) {
  const out = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const k = keyOf(r);
    const list = out.get(k);
    if (list) list.push(r); else out.set(k, [r]);
  }
  return out;
}

// ---------------------------------------------------------------- §3.2 メモ化

const cache = new Map();
const MIN = 60 * 1000;

// ttl は数値(ms)か、値から ttl を決める関数。失敗した Promise はキャッシュに残さない
function memo(key, ttl, fn) {
  const hit = cache.get(key);
  if (hit && hit.expires > Date.now()) return hit.promise;
  const promise = fn();
  const entry = { promise, expires: Infinity };
  cache.set(key, entry);
  promise.then((v) => {
    const t = typeof ttl === 'function' ? ttl(v) : ttl;
    entry.expires = t === Infinity ? Infinity : Date.now() + t;
  }, () => { if (cache.get(key) === entry) cache.delete(key); });
  return promise;
}
const ttlForDate = (date) => (date < todayJST() ? Infinity : MIN);

// §40 その鍵がもう手元にある(取得中を含む)か。**引き直さずに済むか**の判断だけに使う。
// 取得中は expires=Infinity なので true= 同じ promise を待つ(二重に投げない)
function memoReady(key) {
  const hit = cache.get(key);
  return !!(hit && hit.expires > Date.now());
}

// §24.1-3 確定した日のデータだけ sessionStorage に置く(リロード・直開きの取り直しを消す)。
// 当日は対象外(鮮度が優先)。鍵は 'ss:v1:' 始まり= 形を変えたいときは v2 にすれば古い物は読まれない
const SS_PREFIX = 'ss:v1:';

function ssGet(key) {
  try {
    const raw = typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(SS_PREFIX + key);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}
function ssSet(key, value) {
  try { sessionStorage.setItem(SS_PREFIX + key, JSON.stringify(value)); } catch { /* 容量超過などは諦める */ }
}

// memo と同じ使い方。opt.persist が true のときだけ sessionStorage を見る/書く。
// opt.ok(v) が false の値は書かない(まだ確定していない日を固めない)
function ssMemo(key, ttl, fn, opt) {
  const o = opt || {};
  if (o.persist) {
    const raw = ssGet(key);
    if (raw !== null) return memo(key, Infinity, () => Promise.resolve(o.revive ? o.revive(raw) : raw));
  }
  return memo(key, ttl, async () => {
    const v = await fn();
    if (o.persist && (!o.ok || o.ok(v))) ssSet(key, o.dump ? o.dump(v) : v);
    return v;
  });
}

// ---------------------------------------------------------------- 他場(chihou_*)

function chihouRaceFromRow(row, prefix, sourceKind) {
  const date = String(row.race_date ?? row.date ?? '');
  const no = Number(row.race_no);
  const nc = nameCond(row.klass, row.race_name ?? row.name, no);
  const laps = lapsOf(row.laps ?? (row.extra && row.extra.laps));
  return {
    id: `${prefix}/${date}/${no}`,
    venue: prefix,
    date,
    no,
    name: nc.name,
    cond: nc.cond,
    distance: num(row.distance_m),
    surface: str(row.surface),
    going: str(row.going),
    weather: str(row.weather),
    postTime: str(row.hasso_time),
    headCount: null,
    status: 'pre',
    sourceId: String(row.race_id),
    sourceKind: sourceKind || 'chihou',          // §13.2B: 'chihou' | 'archive'(nar 由来は narRaceFromRow が 'nar')
    banei: false,
    videoUrl: videoUrlOf(prefix, date, no),      // §14.2 公式レース映像
    oddsAt: null,                                // §13.2C: 当日オッズの取得時刻(ISO)と「(最終)」表示
    oddsFinal: false,
    bias: null,                                  // §11.1: 内外の傾向は getRaceOwn().bias で返す(ここは常に null)
    extra: raceExtra(laps, num(row.distance_m), str(row.pace), null, null),
  };
}

function kbId(horseId) { const s = str(horseId); return s ? `kb:${s}` : null; }

// 結果行の前半タイムと区間(distance はレースの距離。1200m 未満は距離−600m の通過で、無ければ 走破−上がり3F で補う)
function chihouFirst3f(r, distance) {
  const first3f = fillFirst3f(r.first3f, num(r.time_sec) ?? timeToSec(timeStr(r.time_str)), r.last3f, distance);
  return { first3f, first3fF: first3f === null ? null : first3fFOf(distance) };
}

function chihouResult(r, raceId, distance) {
  return {
    raceId,
    umaban: Number(r.umaban),
    horseName: str(r.horse_name) || '',
    horseId: kbId(r.horse_id),
    finish: num(r.finish),
    finishNote: str(r.finish_note),
    time: timeStr(r.time_str),
    timeSec: num(r.time_sec),
    margin: marginStr(r.margin),
    last3f: num(r.last3f),
    ...chihouFirst3f(r, distance),
    passing: str(r.passing),
    popularity: num(r.pop),
    odds: num(r.win_odds),
    jockey: str(r.jockey),
    weight: num(r.kinryo),
    bodyWeight: num(r.body_weight),
    bodyWeightDiff: num(r.weight_diff),
  };
}

// §3.4 出馬表行+結果行 → Entry(結果があれば確定値を優先)
function chihouEntry(e, r, raceId, distance) {
  const src = e || r;
  // 種別は結果の注記(取消/除外/中止)を優先し、結果前は出馬表の status(取消/除外)
  const scratchKind = scratchKindOf(r && r.finish_note) ?? scratchKindOf(e && e.status);
  const f = r ? chihouFirst3f(r, distance) : { first3f: null, first3fF: null };
  return {
    raceId,
    waku: num(src.waku),
    umaban: Number(src.umaban),
    horseName: str(src.horse_name) || '',
    horseId: kbId(src.horse_id),
    sexAge: sexAgeStr(src.sex_age),
    weight: num(src.kinryo),
    weightLabel: '斤量',                          // §13.2A: 帯広だけ 'そり重量'
    jockey: str(src.jockey),
    trainer: str(src.trainer),
    // §25.1 馬体重は結果行を優先(出馬表行は当日ぶんが空のことがある。odds/ninki と同じ作法)。
    // これが無いと確定レースの出馬表だけ「—」になる(2026-08-24 船橋11R で実測)
    bodyWeight: (r && num(r.body_weight)) ?? (e && num(e.body_weight)) ?? null,
    bodyWeightDiff: (r && num(r.weight_diff)) ?? (e && num(e.weight_diff)) ?? null,
    first3f: f.first3f,                          // §11.1: chihou_results.first3f(結果前は null)
    first3fF: f.first3fF,
    odds: (r && num(r.win_odds)) ?? (e && num(e.win_odds)) ?? null,
    placeLow: null,                              // §13.2C: 複勝は当日オッズ(nar_race_odds)にしか無い
    placeHigh: null,
    oddsObservedAt: null,                        // 単勝を当日オッズで埋めたときの取得時刻(ISO)
    ninki: (r && num(r.pop)) ?? (e && num(e.pop)) ?? null,
    mark: null,
    scratched: scratchKind !== null || Boolean(r && str(r.finish_note)),
    scratchKind,
  };
}

function chihouPayout(p, raceId) {
  return {
    raceId,
    ticketType: p.ticket_type,
    combination: String(p.combination),
    yen: Number(p.official_payout_per_100),
    popularity: num(p.popularity),
  };
}

function buildEntries(entryRows, resultRows, raceId, distance) {
  const byUma = new Map(resultRows.map((r) => [Number(r.umaban), r]));
  const rows = entryRows.length
    ? entryRows.map((e) => chihouEntry(e, byUma.get(Number(e.umaban)) || null, raceId, distance))
    : resultRows.map((r) => chihouEntry(null, r, raceId, distance));     // 過去レースは entries が無い
  return rows.sort((a, b) => a.umaban - b.umaban);
}
function sortResults(rows) {
  return rows.sort((a, b) => (a.finish ?? 999) - (b.finish ?? 999) || a.umaban - b.umaban);
}
// 未知の式別(nar の枠連など)は落とさず末尾に回す(§1.6)。chihou_payouts は既知7種しか無い(2026-08-23 実測)ので既存場の並びは変わらない
function ticketRank(t) { const i = TICKET_ORDER.indexOf(t); return i < 0 ? 99 : i; }
function sortPayouts(rows) {
  const valid = rows.filter((p) => str(p.ticketType) && Number.isFinite(p.yen));
  return valid.sort((a, b) => ticketRank(a.ticketType) - ticketRank(b.ticketType)
    || (a.popularity ?? 999) - (b.popularity ?? 999)
    || a.combination.localeCompare(b.combination, 'ja', { numeric: true }));
}
// 出走頭数 = 取消・除外を除いた数(中止・失格は出走しているので数える。ユーザー決定 2026-08-23)。
// 出馬表(全頭そろう)の status で判定し、出馬表が無い過去レースは結果の注記で判定する
function headCountOf(entryRows, resultRows) {
  if (entryRows.length) return entryRows.filter((e) => !nonStarter(scratchKindOf(e.status))).length;
  if (resultRows.length) return resultRows.filter((r) => !nonStarter(scratchKindOf(r.finish_note))).length;
  return null;
}
function statusOf(done, date) {
  if (done) return 'done';
  return date >= todayJST() ? 'pre' : 'pending';
}

// §Codex A7 → §71 W1 「発走時刻を過ぎたか」。⛔導出の**正本は js/race-phase.js の phaseOf**
//   (トップ・結果・レース・場×日が同じ語彙を使うため)。ここは互換の入口として残す。
// ⚠postTime が無い/形が違うレースは **false**(=従来どおり「発走前」のまま・推定しない)
export function hasStarted(race) {
  if (!race || typeof race !== 'object') return false;
  const date = str(race.date);
  const today = todayJST();
  if (race.status === 'pre' && isDateStr(date) && date < today) return true;  // 従来の保険(実データでは起きない)
  return phaseOf(race, nowMinutesJST(), today).postPassed;
}

// ⚠'HH:MM' → 分 の変換は **既にある** `hhmmMinutes()`(§21.2-5 の勝負レースが使う)を借りる
function nowMinutesJST() {
  const t = new Date(Date.now() + 9 * 3600 * 1000);
  return t.getUTCHours() * 60 + t.getUTCMinutes();
}

const RACE_COLS = 'race_id,track,race_date,race_no,klass,race_name,distance_m,surface,direction,weather,going,hasso_time,pace,extra';

// 1日分の他場レース(DB)。場ごとに entries/results を引いて頭数と status を埋める
async function chihouDay(date) {
  const rows = await sb(`chihou_races?select=${RACE_COLS}&race_date=eq.${date}&order=track.asc,race_no.asc`);
  const byVenue = new Map();
  for (const row of rows) {
    const v = VENUE_BY_NAME.get(String(row.track ?? '').trim());
    if (!v) continue;
    if (!byVenue.has(v.prefix)) byVenue.set(v.prefix, []);
    byVenue.get(v.prefix).push(row);
  }
  // §24.1-2 場ごとに引くと 2×場数 本になるので、その日の race_id をまとめて 2 本にする
  const allIds = [...byVenue.values()].flat().map((r) => r.race_id).join(',');
  const races = [];
  if (!allIds) return races;
  const [entries, results] = await Promise.all([
    sb(`chihou_entries?select=race_id,status&race_id=in.(${allIds})`),
    sb(`chihou_results?select=race_id,finish,finish_note&race_id=in.(${allIds})`),
  ]);
  const eBy = groupBy(entries, (x) => String(x.race_id));
  const rBy = groupBy(results, (x) => String(x.race_id));
  for (const [prefix, vrows] of byVenue) {
    for (const row of vrows) {
      const race = chihouRaceFromRow(row, prefix);
      const e = eBy.get(String(row.race_id)) || [];
      const r = rBy.get(String(row.race_id)) || [];
      race.headCount = headCountOf(e, r);
      race.status = statusOf(r.some((x) => Number(x.finish) === 1), race.date);
      races.push(race);
    }
  }
  return races;
}

async function chihouRace(venue, date, no) {
  const rows = await sb(`chihou_races?select=${RACE_COLS}&track=eq.${enc(venue.name)}&race_date=eq.${date}&race_no=eq.${no}&limit=1`);
  if (!rows.length) return null;
  const row = rows[0];
  const rid = row.race_id;
  const [entryRows, resultRows, payoutRows] = await Promise.all([
    sb(`chihou_entries?select=*&race_id=eq.${rid}&order=umaban.asc`),
    sb(`chihou_results?select=*&race_id=eq.${rid}&order=finish.asc.nullslast,umaban.asc`),
    sb(`chihou_payouts?select=ticket_type,combination,official_payout_per_100,popularity&race_id=eq.${rid}`),
  ]);
  return assembleChihou(row, venue.prefix, entryRows, resultRows, payoutRows);
}

function assembleChihou(row, prefix, entryRows, resultRows, payoutRows, sourceKind) {
  const race = chihouRaceFromRow(row, prefix, sourceKind);
  race.headCount = headCountOf(entryRows, resultRows);
  race.status = statusOf(resultRows.some((r) => Number(r.finish) === 1), race.date);
  return {
    race,
    entries: buildEntries(entryRows, resultRows, race.id, race.distance),
    results: sortResults(resultRows.map((r) => chihouResult(r, race.id, race.distance))),
    payouts: sortPayouts(payoutRows.map((p) => chihouPayout(p, race.id))),
  };
}

// ---------------------------------------------------------------- 川崎・浦和の静的アーカイブ(§1.4)

const archive = {
  on(prefix) { return ARCHIVE_ENABLED && ARCHIVE_PREFIXES.includes(prefix); },
  // index: { dates: { 'YYYY-MM-DD': [{race_id, race_no, klass, name, distance_m, going, weather, hasso_time, pace}] } }
  index(prefix) {
    return memo(`arc:index:${prefix}`, 10 * MIN, () => gz(`${prefix}/index.json.gz`, 'no-cache'));
  },
  pack(prefix, month) {
    return memo(`arc:pack:${prefix}:${month}`, Infinity, () => gz(`${prefix}/packs/${month}.json.gz`));
  },
  // 馬の走歴。nankan/history/NN が無ければ場別 history にフォールバック
  history(bucket) {
    return memo(`arc:hist:${bucket}`, 5 * MIN, async () => {
      try { return await gz(`nankan/history/${bucket}.json.gz`); } catch { /* 旧配置へ */ }
      const docs = await Promise.all(ARCHIVE_PREFIXES.map((p) => gz(`${p}/history/${bucket}.json.gz`).catch(() => ({}))));
      const merged = {};
      for (const doc of docs) for (const [id, runs] of Object.entries(doc || {})) merged[id] = [...(merged[id] || []), ...(runs || [])];
      return merged;
    });
  },
  // その日のレース(pack の {race, results, entries} の配列)。index に無い日は []
  async day(prefix, date) {
    const idx = await this.index(prefix);
    const list = (idx.dates || {})[date] || [];
    if (!list.length) return [];
    const pack = await this.pack(prefix, date.slice(0, 7));
    return list.map((r) => ({ index: r, row: (pack.races || {})[r.race_id] || null })).filter((x) => x.row);
  },
  async dates(prefix) {
    const idx = await this.index(prefix);
    return Object.keys(idx.dates || {}).sort();
  },
};

function archiveAssemble(prefix, item) {
  const { race, results = [], entries = [] } = item.row;
  const row = { ...race, race_date: race.date, race_name: race.name, race_id: race.race_id || item.index.race_id };
  return assembleChihou(row, prefix, entries, results, [], 'archive');   // pack に払戻は無い(実測 0/120 レース)
}

// 全アーカイブ場の1日分(DB に無い race_id だけ)。
// ⛔§67 B5 直し: 落ちた場があったことを **`out.failed`** で返す(前は握りつぶして「開催なし」に見えた)。
//   ⚠**アーカイブだけが源の日**(2022-10 以前)は、これが無いと 0 件を「開催データはありません」と断定する
async function archiveDay(date, knownIds) {
  const out = [];
  out.failed = false;
  if (!ARCHIVE_ENABLED) return out;
  await Promise.all(archivePrefixesFor(date).map(async (prefix) => {
    let items;
    try { items = await archive.day(prefix, date); } catch { out.failed = true; return; }
    for (const it of items) {
      if (knownIds.has(it.index.race_id)) continue;
      out.push(archiveAssemble(prefix, it));
    }
  }));
  return out;
}

// 前後の開催日さがし用。pivot の近くに答えがあり得る場だけ索引を開く
async function archiveDatesAll(pivot) {
  if (!ARCHIVE_ENABLED) return [];
  const lists = await Promise.allSettled(archivePrefixesFor(pivot, ARCHIVE_HIST_EDGE).map((p) => archive.dates(p)));
  return lists.flatMap((r) => (r.status === 'fulfilled' ? r.value : []));
}

// ---------------------------------------------------------------- 高知(keiba_*)

const KOCHI_RACE_COLS = 'id,race_date,race_no,race_name,distance,race_class,track_cond,lap_times,agari3f_race,pace_type,first3f,first3f_source,agari4f';
// §85 高知の日別結果。結果が自前DBで空の日も、同じ1本から公式補完と安全に照合する馬IDを拾う。
// `select=*` をやめ、1日全出走馬でも必要列だけに絞る。
const KOCHI_DAY_RESULT_COLS = 'race_no,uma_ban,horse_name,lineage_login_code,chakujun,time,diff,agari3f,first3f,corner,ninki,odds,jockey,kinryo,weight';

// §11.1 keiba_races.first3f_source(auto:lap_sum_* / auto:formula_* / auto:estimate_*)→ 閲覧者向けの由来。それ以外(manual・空)は null
function first3fKindOf(source) {
  const s = str(source) || '';
  if (s.startsWith('auto:lap_sum')) return 'ラップから';
  if (s.startsWith('auto:formula')) return '公式タイムから';
  if (s.startsWith('auto:estimate')) return '推定';
  return null;
}
// §11.1 高知のレース単位の前半3F・上がり4F・前後半差・ペース(keiba_races の同じ行から。全部空なら null)
function kochiSectional(row) {
  const first3f = num(row.first3f);
  const agari3fRace = num(row.agari3f_race);
  const halfDiff = first3f !== null && agari3fRace !== null ? (Math.round((first3f - agari3fRace) * 10) / 10) || 0 : null;
  const pace = str(row.pace_type);
  // pace_type が空なら本番と同じ閾値(前後半差 ≤−2.0 ハイ / ≤−0.5 ミドル / それ以外 スロー)で決める
  const paceLabel = ['ハイ', 'ミドル', 'スロー'].includes(pace) ? pace
    : (halfDiff === null ? null : (halfDiff <= -2.0 ? 'ハイ' : (halfDiff <= -0.5 ? 'ミドル' : 'スロー')));
  // §49 #174 ペースの由来。手入力(pace_type がある)=**当サイト判定** / 無い=閾値で決めた**当サイト算出**。
  // ⚠paceLabel が null のときは由来も無い(false でなく null にして「言わない」を保つ)
  const paceManual = paceLabel === null ? null : ['ハイ', 'ミドル', 'スロー'].includes(pace);
  const out = { first3f, first3fKind: first3f === null ? null : first3fKindOf(row.first3f_source), agari4f: num(row.agari4f), halfDiff, paceLabel };
  if (Object.values(out).every((v) => v === null)) return null;
  out.paceManual = paceManual;
  return out;
}

function kochiRaceFromRow(row, postTime) {
  const date = fromKochiDate(row.race_date);
  const no = Number(row.race_no);
  return {
    id: `kochi/${date}/${no}`,
    venue: 'kochi',
    date,
    no,
    name: str(row.race_name) || `${no}R`,
    cond: str(row.race_class),
    distance: distNum(row.distance),
    surface: 'ダート',
    going: str(row.track_cond),
    weather: null,
    postTime: postTime ?? null,
    kind: null,                                  // §27.2 高知の表に競走種類は無い(公式の便で埋める)
    headCount: null,
    status: 'pre',
    sourceId: String(row.id),
    sourceKind: 'kochi',
    banei: false,
    videoUrl: videoUrlOf('kochi', date, no),
    oddsAt: null,
    oddsFinal: false,
    bias: null,
    extra: raceExtra(lapsOf(row.lap_times), distNum(row.distance), str(row.pace_type), num(row.agari3f_race),
      kochiSectional(row), num(row.agari4f)),   // §41-A 上り4F(keiba_races に元からある列)
  };
}

function kochiHorseId(h) {
  const code = str(h.lineage_login_code);
  if (code) return `kochi:${code}`;
  const name = str(h.horse_name);
  return name ? `name:${name}` : null;
}
// chakujun が数値なら着順、'取消'/'除外' なら注記(kind 付き)。競走中止は chakujun が空(7/26 R2 #7・実測)で、注記は nar フォールバックが補う
function kochiFinish(h) {
  const raw = str(h.chakujun);
  if (!raw) return { finish: null, note: null, scratched: false, kind: null };
  const n = num(raw);
  return n === null
    ? { finish: null, note: raw, scratched: true, kind: scratchKindOf(raw) }
    : { finish: n, note: null, scratched: false, kind: null };
}
// 高知の出走頭数(取消・除外を除く。中止は chakujun が空なので元から数えている)。
// 数値化できず種別も読めない chakujun は従来どおり数えない
function kochiHeadCount(rows) {
  if (!rows.length) return null;
  return rows.filter((h) => { const f = kochiFinish(h); return !f.scratched || (f.kind !== null && !nonStarter(f.kind)); }).length;
}

// §3.5 keiba_horses 1行 → Entry(+ chakujun 非空なら Result)
function kochiEntry(h, raceId) {
  const w = kochiWeight(h.weight);
  const f = kochiFinish(h);
  return {
    raceId,
    waku: num(h.waku_ban),
    umaban: Number(h.uma_ban),
    horseName: str(h.horse_name) || '',
    horseId: kochiHorseId(h),
    sexAge: sexAgeStr(h.sex_age),
    weight: num(h.kinryo),
    weightLabel: '斤量',
    jockey: str(h.jockey),
    trainer: str(h.trainer),
    bodyWeight: w.bodyWeight,
    bodyWeightDiff: w.bodyWeightDiff,
    first3f: num(h.first3f),                     // §11.1: 各馬の前半3F(実測と推定が混在。出自は getRaceOwn で)
    first3fF: num(h.first3f) === null ? null : 3, // 高知は距離によらず常に 3F
    odds: num(h.odds),
    placeLow: null,
    placeHigh: null,
    oddsObservedAt: null,
    ninki: num(h.ninki),
    mark: null,
    scratched: f.scratched,
    scratchKind: f.kind,
  };
}
function kochiResult(h, raceId) {
  const w = kochiWeight(h.weight);
  const f = kochiFinish(h);
  const time = timeStr(h.time);
  return {
    raceId,
    umaban: Number(h.uma_ban),
    horseName: str(h.horse_name) || '',
    horseId: kochiHorseId(h),
    finish: f.finish,
    finishNote: f.note,
    time,
    timeSec: timeToSec(time),
    margin: marginStr(h.diff),
    last3f: num(h.agari3f),
    first3f: num(h.first3f),
    first3fF: num(h.first3f) === null ? null : 3,
    passing: str(h.corner),
    popularity: num(h.ninki),
    odds: num(h.odds),
    jockey: str(h.jockey),
    weight: num(h.kinryo),
    bodyWeight: w.bodyWeight,
    bodyWeightDiff: w.bodyWeightDiff,
  };
}
function timeToSec(t) {
  if (!t) return null;
  const m = t.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!m) return null;
  return (m[1] ? Number(m[1]) * 60 : 0) + Number(m[2]);
}

// 発走時刻: **本体の nar_races.post_time が正**(公式 CSV・朝の便で全レースぶん入る・#476)。
// 旧: keiba_odds_snapshots の post_time= PC 側のオッズ記録が走ったレースにしか無く、PC を閉じている日は
//   1R しか出ない(2026-09-05 ユーザー指摘)。nar_races に無い日(2026-06 以前)だけ旧の表へ落とす。
function kochiPostTimes(date) {
  return memo(`kochi:post:${date}`, ttlForDate(date), async () => {
    const map = new Map();
    try {
      const rows = await sbNar(`nar_races?select=race_no,post_time&track=eq.${enc('高知')}&race_date=eq.${date}&order=race_no.asc`);
      for (const r of rows) {
        const t = narPostTime(r.post_time);
        if (t) map.set(Number(r.race_no), t);
      }
    } catch { /* 本体が読めない日は旧の表へ */ }
    if (map.size) return map;
    // order を付けて、万一 1000 行に達しても切られるのが末尾の race_no に限られるようにする
    const rows = await sb(`keiba_odds_snapshots?select=race_no,post_time&baba_code=eq.${KOCHI_BABA}&race_date=eq.${enc(toKochiDate(date))}&uma_ban=eq.1&order=race_no.asc&limit=1000`);
    for (const r of rows) {
      const t = str(r.post_time);
      if (t && !map.has(Number(r.race_no))) map.set(Number(r.race_no), t);
    }
    return map;
  });
}

async function kochiDay(date) {
  const kd = enc(toKochiDate(date));
  // §24.1 高知は開催が週2日ほど。まずレースの有無を見て、無い日は残り2本を投げない
  // (開催日は1波ぶん遅くなるが、非開催日の空振り2本が毎ページ消える)
  const races = await sb(`keiba_races?select=${KOCHI_RACE_COLS}&baba_code=eq.${KOCHI_BABA}&race_date=eq.${kd}&order=race_no.asc`);
  if (!races.length) return [];
  const [horses, posts] = await Promise.all([
    sb(`keiba_horses?select=race_no,uma_ban,chakujun&baba_code=eq.${KOCHI_BABA}&race_date=eq.${kd}`),
    kochiPostTimes(date).catch(() => new Map()),
  ]);
  return races.map((row) => {
    const no = Number(row.race_no);
    const race = kochiRaceFromRow(row, posts.get(no) ?? null);
    const hs = horses.filter((h) => Number(h.race_no) === no);
    race.headCount = kochiHeadCount(hs);
    race.status = statusOf(hs.some((h) => str(h.chakujun) === '1'), race.date);
    return race;
  });
}

async function kochiRace(date, no) {
  const kd = enc(toKochiDate(date));
  const [races, horses, posts] = await Promise.all([
    sb(`keiba_races?select=${KOCHI_RACE_COLS}&baba_code=eq.${KOCHI_BABA}&race_date=eq.${kd}&race_no=eq.${no}&limit=1`),
    sb(`keiba_horses?select=*&baba_code=eq.${KOCHI_BABA}&race_date=eq.${kd}&race_no=eq.${no}&order=uma_ban.asc`),
    kochiPostTimes(date).catch(() => new Map()),
  ]);
  if (!races.length && !horses.length) return null;
  const row = races[0] || { id: `race_${KOCHI_BABA}_${toKochiDate(date)}_${no}`, race_date: toKochiDate(date), race_no: no };
  const race = kochiRaceFromRow(row, posts.get(Number(no)) ?? null);
  race.headCount = kochiHeadCount(horses);
  race.status = statusOf(horses.some((h) => str(h.chakujun) === '1'), race.date);
  const entries = horses.map((h) => kochiEntry(h, race.id)).sort((a, b) => a.umaban - b.umaban);
  const results = sortResults(horses.filter((h) => str(h.chakujun)).map((h) => kochiResult(h, race.id)));
  return { race, entries, results, payouts: [] };    // 高知の払戻は無し(§10 #3)
}

// ---------------------------------------------------------------- NAR公式(nar_*・§1.6)

const NAR_TRACK_IN = `track=in.(${NAR_TRACKS.map(enc).join(',')})`;
// §13.2B-1: 日付系(直近の開催日・前後の開催日・週間日程)は全15場を見て既存ソースと和集合にする。
// 競馬ブック経路(PC の取込)が止まっても、公式データがある日は開催日として出る
const NAR_ALL_IN = `track=in.(${VENUES.map((v) => enc(narTrackName(v))).join(',')})`;
// §13.2B-2: 1日一覧の補完対象= 競馬ブック(chihou)/高知(kochi)が主の6場(nar 9場は narDay が直接引く)
const NAR_FALLBACK_TRACKS = VENUES.filter((v) => v.supported === 'chihou' || v.supported === 'kochi');
const NAR_FALLBACK_IN = `track=in.(${NAR_FALLBACK_TRACKS.map((v) => enc(narTrackName(v))).join(',')})`;
const NAR_RACE_COLS = 'track,race_date,race_no,post_time,race_name,surface,distance_m,weather,going,field_size,condition,race_last3f,furlongs,race_kind';

// 公式表記の場名 → prefix。nar 8場以外(走歴に混ざる門別・南関・高知・帯広ば)も引けるようにする
function narPrefixOf(track) {
  const t = String(track ?? '').trim();
  const v = VENUE_BY_NAME.get(t);
  return v ? v.prefix : (NAR_TRACK_ALIAS.get(t) ?? null);
}
// §13.2A ばんえいの going は馬場水分率の文字列('0.7'。空文字もある)。閲覧者向けに '水分率 0.7%' にする
function baneiGoing(banei, going) {
  const g = str(going);
  if (!g) return null;
  return banei && /^\d+(\.\d+)?$/.test(g) ? `水分率 ${g}%` : g;
}
function narPostTime(v) {
  const m = (str(v) || '').match(/^(\d{2})(\d{2})$/);
  return m ? `${m[1]}:${m[2]}` : null;
}
// time_sec → 'M:SS.s'(60 秒未満は 'SS.s')。§108 で画面(検索の集計)からも使うので export
export function narTimeStr(sec) {
  const s = num(sec);
  if (s === null || s <= 0) return null;
  const m = Math.floor(s / 60);
  const rest = (s - m * 60).toFixed(1);
  return m ? `${m}:${rest.padStart(4, '0')}` : rest;
}
// 取消・除外・中止の注記は margin 列に入っている(投入側の finish_note は実質 null。§10 #18)
function narNote(r) {
  const note = str(r.finish_note);
  if (note) return { note, margin: marginStr(r.margin) };
  const m = str(r.margin);
  if (m && /(取消|除外|中止|失格)/.test(m)) return { note: m, margin: null };
  return { note: null, margin: marginStr(m) };
}
function narFinish(r) {
  const f = num(r.finish);
  return f === null || f <= 0 ? null : f;      // finish=0 の行(実測2件)は null 扱い
}
function narHorseId(r) { const n = str(r.horse_name); return n ? `nar:${n}` : null; }
function narSexAge(r) {
  const s = str(r.sex), a = num(r.age);
  if (!s && a === null) return null;
  return sexAgeStr(`${s ?? ''}${a ?? ''}`);
}

function narRaceFromRow(row, prefix) {
  const date = String(row.race_date ?? '');
  const no = Number(row.race_no);
  const cond = str(row.condition);
  const banei = Boolean((VENUE_BY_PREFIX.get(prefix) || {}).banei);
  const laps = lapsOf(row.furlongs);              // ばんえいは furlongs=[] なので null にする
  return {
    id: `${prefix}/${date}/${no}`,
    venue: prefix,
    date,
    no,
    name: str(row.race_name) || `${no}R`,        // 全角のまま出す(§2.8 の入れ替え判定はしない)
    cond: cond ? cond.replace(/　/g, ' ') : null, // 全角空白だけ半角に
    distance: num(row.distance_m),
    surface: str(row.surface),
    going: baneiGoing(banei, row.going),
    weather: str(row.weather),
    postTime: narPostTime(row.post_time),
    kind: raceKind(row.race_kind),               // §27.2 公式の競走種類名称(重賞・準重賞だけ画面に出す)
    headCount: num(row.field_size),              // runs が取れたら注記なし行数で上書き
    status: 'pre',
    sourceId: `nar:${str(row.track) ?? ''}/${date}/${no}`,
    sourceKind: 'nar',
    banei,
    videoUrl: videoUrlOf(prefix, date, no),
    oddsAt: null,
    oddsFinal: false,
    bias: null,
    // §41-A 公式のコーナー通過(#121 の開栓)。select=* で既に取れているので通信は増えない
    corners: cornerList(row.corners),
    // §79 P2 このレースの本賞金(1〜5着)と条件クラス。**select=* で既に来ている列**=通信は増えない
    prizeList: Array.isArray(row.prize_yen) ? row.prize_yen : null,
    raceClass: raceClassOf(str(row.race_name), str(row.race_kind)),
    // §49 U-5 nar 経路の laps は**公式発表のハロンタイム**そのものなので officialLaps にも入れる
    extra: raceExtra(laps && laps.length ? laps : null, num(row.distance_m), null,
      num(row.race_last3f), null, num(row.race_last4f), laps),
  };
}

function narEntry(r, raceId, banei) {
  const n = narNote(r);
  return {
    raceId,
    waku: num(r.gate),
    umaban: Number(r.runner_number),
    horseName: str(r.horse_name) || '',
    horseId: narHorseId(r),
    sexAge: narSexAge(r),
    weight: num(r.carried_weight),                // ばんえいは「そり重量」(null の行もある)
    weightMark: str(r.weight_mark),               // 減量記号(◇☆▲★・公式の字のまま・2026-09-04)
    weightLabel: banei ? 'そり重量' : '斤量',
    jockey: str(r.jockey),
    trainer: str(r.trainer),
    // §54.3-a 転入初戦の判定に使う。**`select=*` で既に来ている列**なので通信は増えない。
    // ⚠所属は「厩舎の地区」(佐賀・兵庫・北海道・JRA…)= 遠征しても変わらない(2026-08-29 実測)
    trainerArea: str(r.trainer_area),
    birthDate: str(r.birth_date),                 // ⛔同名馬(34名)を潰す鍵の片方
    bodyWeight: num(r.body_weight),
    bodyWeightDiff: num(r.body_weight_change),
    first3f: null,                               // 前半3F は nar に無い
    first3fF: null,
    odds: null,                                  // 単勝オッズは nar_runs に無い(当日オッズは §13.2C で足す)
    placeLow: null,
    placeHigh: null,
    oddsObservedAt: null,
    ninki: num(r.popularity),
    mark: null,
    scratched: n.note !== null,
    scratchKind: scratchKindOf(n.note),
  };
}
function narResult(r, raceId) {
  const n = narNote(r);
  return {
    raceId,
    umaban: Number(r.runner_number),
    horseName: str(r.horse_name) || '',
    horseId: narHorseId(r),
    finish: n.note !== null ? null : narFinish(r),
    finishNote: n.note,
    time: narTimeStr(r.time_sec),
    timeSec: num(r.time_sec),
    margin: n.margin,
    last3f: num(r.last3f),
    first3f: null,
    first3fF: null,
    passing: null,
    popularity: num(r.popularity),
    odds: null,
    jockey: str(r.jockey),
    weight: num(r.carried_weight),
    weightMark: str(r.weight_mark),
    bodyWeight: num(r.body_weight),
    bodyWeightDiff: num(r.body_weight_change),
  };
}
// nar_race_payouts.payouts(1レース1行の JSON 配列 [{t:券種, c:組番, y:100円あたり払戻, p:人気}, …]。
// 2026-08-23 に 63万行の nar_payouts を 5.8万行に畳んで DB を 170MB 減らした)
function narPayout(p, raceId) {
  return {
    raceId,
    ticketType: String(p.t ?? ''),
    combination: String(p.c ?? ''),
    yen: Number(p.y),
    popularity: num(p.p),
  };
}
function narPayoutList(row, raceId, types) {
  const list = row && Array.isArray(row.payouts) ? row.payouts : [];
  return sortPayouts(list.filter((p) => !types || types.includes(p.t)).map((p) => narPayout(p, raceId)));
}
// 出走頭数 = 出走取消・競走除外を除いた数(競走中止・失格は出走している)
function narHeadCount(runs, fallback) {
  if (!runs.length) return fallback;
  return runs.filter((r) => !nonStarter(scratchKindOf(narNote(r).note))).length;
}
function narDone(runs) { return runs.some((r) => narFinish(r) === 1 && narNote(r).note === null); }

// 1日分の nar 8場レース。場ごとに runs(≤192 行)を引いて頭数と status を埋める
async function narDay(date) {
  const rows = await sbNar(`nar_races?select=${NAR_RACE_COLS}&${NAR_TRACK_IN}&race_date=eq.${date}&order=track.asc,race_no.asc`);
  const byTrack = new Map();
  for (const row of rows) {
    const t = str(row.track);
    const prefix = t ? narPrefixOf(t) : null;      // 帯広は公式表記が '帯広ば'
    const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
    if (!v || v.supported !== 'nar') continue;
    if (!byTrack.has(t)) byTrack.set(t, []);
    byTrack.get(t).push(row);
  }
  // §24.1-2 場ごとに引くと場数だけ本数が増えるので、その日の出走を track=in.() の1本で取る
  const races = [];
  if (!byTrack.size) return races;
  const tracks = [...byTrack.keys()];
  const runs = await sbNar('nar_runs?select=track,race_no,runner_number,finish,finish_note,margin' +
    `&track=in.(${enc(quoteIn(tracks))})&race_date=eq.${date}`);
  const byKey = groupBy(runs, (r) => `${str(r.track) ?? ''}/${Number(r.race_no)}`);
  for (const [track, trows] of byTrack) {
    const prefix = narPrefixOf(track);
    for (const row of trows) {
      const race = narRaceFromRow(row, prefix);
      const rs = byKey.get(`${track}/${race.no}`) || [];
      race.headCount = narHeadCount(rs, race.headCount);
      race.status = statusOf(narDone(rs), race.date);
      races.push(race);
    }
  }
  return races;
}

async function narRace(venue, date, no) {
  const t = enc(narTrackName(venue));
  const rows = await sbNar(`nar_races?select=*&track=eq.${t}&race_date=eq.${date}&race_no=eq.${no}&limit=1`);
  if (!rows.length) return null;
  const [runs, payRows] = await Promise.all([
    sbNar(`nar_runs?select=*&track=eq.${t}&race_date=eq.${date}&race_no=eq.${no}&order=runner_number.asc`),
    sbNar(`nar_race_payouts?select=payouts&track=eq.${t}&race_date=eq.${date}&race_no=eq.${no}&limit=1`),
  ]);
  const race = narRaceFromRow(rows[0], venue.prefix);
  race.headCount = narHeadCount(runs, race.headCount);
  race.status = statusOf(narDone(runs), race.date);
  const entries = runs.map((r) => narEntry(r, race.id, race.banei)).sort((a, b) => a.umaban - b.umaban);
  const payouts = narPayoutList(payRows[0], race.id, null);
  const results = race.status === 'done' ? sortResults(runs.map((r) => narResult(r, race.id))) : [];
  // §41-A 公式の corners から通過順位を埋める(nar_runs には列が無い=#121)。
  // ⚠既に値のある馬(競馬ブック由来)は上書きしない
  const pass = passingFromCorners(race.corners);
  if (pass.size) for (const r of results) if (!r.passing) r.passing = pass.get(r.umaban) ?? null;
  // 単勝オッズは nar に無いので、1着馬(同着は両方)だけ単勝払戻÷100 を入れる(§1.6)
  for (const r of results) {
    if (r.finish !== 1) continue;
    const win = payouts.find((p) => p.ticketType === 'win' && p.combination === String(r.umaban));
    if (win) r.odds = Math.round(win.yen) / 100;
  }
  return { race, entries, results, payouts };
}

function narRun(r, info) {
  const date = String(r.race_date ?? '');
  const no = num(r.race_no);
  const prefix = narPrefixOf(r.track);
  const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
  const n = narNote(r);
  const i = info || {};
  return {
    date,
    venue: prefix,
    raceId: v && v.supported !== 'none' && date && no !== null ? `${prefix}/${date}/${no}` : null,
    raceNo: no,
    umaban: num(r.runner_number),
    raceName: str(i.race_name),
    distance: num(i.distance_m),
    going: baneiGoing(Boolean(v && v.banei), i.going),
    ninki: num(r.popularity),
    finish: n.note !== null ? null : narFinish(r),
    finishNote: n.note,
    time: narTimeStr(r.time_sec),
    first3f: null,
    first3fF: null,
    last3f: num(r.last3f),
    jockey: str(r.jockey),
    weight: num(r.carried_weight),
    weightMark: str(r.weight_mark),
    bodyWeight: num(r.body_weight),
    horseBirth: isDateStr(str(r.birth_date)) ? str(r.birth_date) : null, // §89 coarse 同名馬ガード専用（画面には出さない）
    margin: n.margin,
    passing: null,
  };
}
const narKey = (r) => `${str(r.track) ?? ''}/${r.race_date}/${Number(r.race_no)}`;

// 馬の横断成績(track で絞らない=全15場の走歴)。レース情報は FK が無いので 50 走ずつ or=(and(…)) で補完(失敗は無視)
async function horseNar(name, birth = null, requestedId = null) {
  const birthFilter = birth ? `&birth_date=eq.${birth}` : '';
  const rows = await sbNar(`nar_runs?select=*&horse_name=eq.${enc(name)}${birthFilter}&order=race_date.desc,race_no.desc&limit=300`);
  if (!rows.length) return null;
  const keys = [...new Set(rows.map(narKey))];
  const infoRows = (await Promise.all(chunk(keys, 50).map((part) => {
    const cond = part.map((k) => {
      const [track, date, no] = k.split('/');
      return `and(track.eq.${enc(track)},race_date.eq.${date},race_no.eq.${no})`;
    }).join(',');
    return sbNar(`nar_races?select=track,race_date,race_no,race_name,distance_m,going&or=(${cond})`).catch(() => []);
  }))).flat();
  const info = new Map(infoRows.map((r) => [narKey(r), r]));
  const runs = sortRuns(rows.map((r) => narRun(r, info.get(narKey(r))))).slice(0, 300);
  const latest = rows[0];
  return {
    id: requestedId || `nar:${name}`,
    name: str(latest.horse_name) || name,
    venue: narPrefixOf(latest.track),            // 所属は取れないので最終出走の場(horse.js は nar: を「最終出走」と表示)
    sexAge: narSexAge(latest),
    trainer: str(latest.trainer),
    birth: isDateStr(str(latest.birth_date)) ? str(latest.birth_date) : null,   // §54.5 同名馬ガード用
    runs,
    stats: finishStats(runs),
  };
}

// ---------------------------------------------------------------- §67 B5 落ちた源を画面まで伝える

// 合流で使う源の名前。⛔**内部名**= 画面には出さない(出すのは「一部」だけ)。
// ⚠#6(鮮度・信頼度バッジ)が「その源が担当する場」を引くので、**名前を捨てる簡略化をしない**
const SOURCES = { chihou: 'chihou', kochi: 'kochi', nar: 'nar', archive: 'archive' };

// `Promise.allSettled` の結果から落ちた源の名前を拾う。names は settled と同じ並び
function failedOf(settled, names) {
  const out = [];
  for (let i = 0; i < settled.length; i += 1) {
    if (settled[i] && settled[i].status === 'rejected' && names[i]) out.push(names[i]);
  }
  return out;
}
// ⛔返り値の**型は変えない**= オブジェクト/配列に印を生やすだけ(`getRunnerNames` の `.finish` と同じ手)。
// ⚠文字列を返す合流(最新日・前後の開催日)には**生やせない**ので、そこは印を持たない(§67 の実装記録)
function withPartial(out, failed) {
  if (out && typeof out === 'object') {
    out.partial = failed.length > 0;
    out.failed = failed;
  }
  return out;
}

// ---------------------------------------------------------------- 日付

function maxDate(list) { return list.length ? list.reduce((a, b) => (a > b ? a : b)) : null; }
function minDate(list) { return list.length ? list.reduce((a, b) => (a < b ? a : b)) : null; }

export function getLatestRaceDate() {
  return memo('latest', MIN, async () => {
    const today = todayJST();
    const settled = await Promise.allSettled([
      sb(`chihou_races?select=race_date&race_date=lte.${today}&order=race_date.desc&limit=1`)
        .then((r) => (r.length ? String(r[0].race_date) : null)),
      sb(`keiba_races?select=race_date&baba_code=eq.${KOCHI_BABA}&race_date=lte.${enc(toKochiDate(today))}&order=race_date.desc&limit=1`)
        .then((r) => (r.length ? fromKochiDate(r[0].race_date) : null)),
      sbNar(`nar_races?select=race_date&${NAR_ALL_IN}&race_date=lte.${today}&order=race_date.desc&limit=1`)
        .then((r) => (r.length ? String(r[0].race_date) : null)),
    ]);
    const ok = settled.filter((s) => s.status === 'fulfilled');
    if (!ok.length) throw settled[0].reason;
    const d = maxDate(ok.map((s) => s.value).filter(Boolean));
    if (!d) throw makeError('other', null, 'no race date');
    return d;
  });
}

async function neighborDate(pivot, dir) {
  const gt = dir > 0;
  const settled = await Promise.allSettled([
    sb(`chihou_races?select=race_date&race_date=${gt ? 'gt' : 'lt'}.${pivot}&order=race_date.${gt ? 'asc' : 'desc'}&limit=1`)
      .then((r) => (r.length ? String(r[0].race_date) : null)),
    sb(`keiba_races?select=race_date&baba_code=eq.${KOCHI_BABA}&race_date=${gt ? 'gt' : 'lt'}.${enc(toKochiDate(pivot))}&order=race_date.${gt ? 'asc' : 'desc'}&limit=1`)
      .then((r) => (r.length ? fromKochiDate(r[0].race_date) : null)),
    archiveDatesAll(pivot).then((ds) => (gt ? minDate(ds.filter((d) => d > pivot)) : maxDate(ds.filter((d) => d < pivot)))),
    sbNar(`nar_races?select=race_date&${NAR_ALL_IN}&race_date=${gt ? 'gt' : 'lt'}.${pivot}&order=race_date.${gt ? 'asc' : 'desc'}&limit=1`)
      .then((r) => (r.length ? String(r[0].race_date) : null)),
  ]);
  const errs = settled.filter((s) => s.status === 'rejected');
  if (errs.length === settled.length) throw errs[0].reason;
  const cands = settled.filter((s) => s.status === 'fulfilled').map((s) => s.value).filter(Boolean);
  return (gt ? minDate(cands) : maxDate(cands)) ?? null;
}
export function getNextRaceDate(after) {
  if (!isDateStr(after)) return Promise.resolve(null);
  return memo(`next:${after}`, MIN, () => neighborDate(after, +1));
}
export function getPrevRaceDate(before) {
  if (!isDateStr(before)) return Promise.resolve(null);
  return memo(`prev:${before}`, MIN, () => neighborDate(before, -1));
}

// §28.3 今日どの競馬場が開催しているか(15場ストリップの ● 用)。Set(prefix)・**1クエリ**・10分メモ。
// レースの中身は要らないので track 列だけ引く。公式(nar_races)は全15場を持ち、実測でも競馬ブック・高知に
// あって公式に無い場は無かった(2026-08-23〜27 の5日で確認)ので、これだけで「本日開催」は足りる。
// 開催が無い日は空の Set(= ● なし)。**取得に失敗したときは投げる**=呼び出し側(refreshStrip)が
// 何もしないので、通信が落ちたときに ● が消えてしまうことはない(memo は失敗を覚えないので次回やり直す)
export function getTodayVenues() {
  const today = todayJST();
  return memo(`todayvenues:${today}`, 10 * MIN, async () => {
    const out = new Set();
    const rows = await sbNar(`nar_races?select=track&${NAR_ALL_IN}&race_date=eq.${today}&limit=1000`);
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);       // '帯広ば' → obihiro もここで吸収する
      if (prefix) out.add(prefix);
    }
    return out;
  });
}

// 1000 行ちょうど返ってきたら上限到達の疑い(後ろの日付が静かに消える)。console.warn で気づけるようにする
function warnIfCapped(rows, where) {
  if (Array.isArray(rows) && rows.length >= 1000) {
    console.warn(`[data] 1000 行上限に達した可能性があります(${where || 'getSchedule'})`);
  }
  return rows;
}

export function getSchedule(from, to) {
  if (!isDateStr(from) || !isDateStr(to) || to < from) return Promise.resolve([]);
  const end = to > addDays(from, 13) ? addDays(from, 13) : to;      // 最大 14 日
  // §67 B5 直し ⛔欠けたまま覚えない(画面は「時間をおいて開き直して」と案内するので、数値 TTL だと矛盾する)
  return memo(`sched:${from}:${end}`, (v) => (v && v.partial ? 0 : MIN), () => scheduleRange(from, end));
}

// §44 カレンダー用の月ぶん。`getSchedule` の**14日の上限は掛けない**=
// race_no=eq.1 で引くので 31日×15場≈465行、1000行の上限には遠い(実測で確かめる)。
// ym = 'YYYY-MM'。読めない ym は空(ページ側で notFound)
export function getMonthSchedule(ym) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(ym ?? ''));
  if (!m) return Promise.resolve([]);
  const mo = Number(m[2]);
  if (mo < 1 || mo > 12) return Promise.resolve([]);
  const from = `${m[1]}-${m[2]}-01`;
  const to = addDays(mo === 12 ? `${Number(m[1]) + 1}-01-01` : `${m[1]}-${pad2(mo + 1)}-01`, -1);
  // 今月と先の月は短命(出馬表が日々増える)・過ぎた月は動かないので長め。
  // §67 B5 直し ⛔欠けた月は覚えない(過去月は 30分 のままだと直っても30分間 嘘が残る)
  const base = ym >= todayJST().slice(0, 7) ? MIN : 30 * MIN;
  return memo(`schedm:${ym}`, (v) => (v && v.partial ? 0 : base), () => scheduleRange(from, to));
}

// getSchedule / getMonthSchedule の中身。返り値 = [{date, venues:[prefix]}](日付昇順)
async function scheduleRange(from, end) {
  // §67 B5 直し2 ⛔**旗を立てることと、データを捨てることは別**= アーカイブは**場ごとに catch** して
  //   成功分を残し、落ちたことだけ別の変数で覚える(`archiveDay` と同じ形)。
  //   ⚠`Promise.all` は「全か無か」なので、包んだまま catch を外すと**1場の失敗で9場ぶんまで消える**
  //   (実測: 浦和1場だけ落とすと /calendar/2022-06 が のべ89場 → 6場)
  let arcFailed = false;
  // 各場・各日に 1 行あれば足りるので race_no=eq.1 で引く(行数が約 1/12 になり 1000 行上限から遠ざかる。2026-08-23 curl で両テーブル確認済)
  const settled = await Promise.allSettled([
    sb(`chihou_races?select=race_date,track&race_date=gte.${from}&race_date=lte.${end}&race_no=eq.1&order=race_date.asc&limit=1000`)
      .then(warnIfCapped)
      .then((rows) => rows.map((r) => ({ date: String(r.race_date), venue: (VENUE_BY_NAME.get(String(r.track ?? '').trim()) || {}).prefix }))),
    sb(`keiba_races?select=race_date&baba_code=eq.${KOCHI_BABA}&race_date=gte.${enc(toKochiDate(from))}&race_date=lte.${enc(toKochiDate(end))}&race_no=eq.1&order=race_date.asc&limit=1000`)
      .then(warnIfCapped)
      .then((rows) => rows.map((r) => ({ date: fromKochiDate(r.race_date), venue: 'kochi' }))),
    ARCHIVE_ENABLED
      ? Promise.all(archivePrefixesFor(from).map((p) => archive.dates(p)
        .then((ds) => ds.filter((d) => d >= from && d <= end).map((date) => ({ date, venue: p })))
        .catch(() => { arcFailed = true; return []; })))
        .then((a) => a.flat())
      : Promise.resolve([]),
    // nar 全15場(4本目。先頭2本の「両方失敗なら throw」判定には入れない=nar 側の失敗を既存に波及させない)
    sbNar(`nar_races?select=race_date,track&${NAR_ALL_IN}&race_date=gte.${from}&race_date=lte.${end}&race_no=eq.1&order=race_date.asc&limit=1000`)
      .then(warnIfCapped)
      .then((rows) => rows.map((r) => ({ date: String(r.race_date), venue: narPrefixOf(r.track) }))),
  ]);
  // ⛔throw の条件は変えない(先頭2本の両方失敗のまま)。⚠**nar が落ちたことを印に載せる**のが目的
  const schedFailed = failedOf(settled, [SOURCES.chihou, SOURCES.kochi, SOURCES.archive, SOURCES.nar]);
  // ⛔`failedOf` の names は**添字対応**なので触らない= 場ごとの失敗は**後から push** する
  if (arcFailed && !schedFailed.includes(SOURCES.archive)) schedFailed.push(SOURCES.archive);
  if (settled.slice(0, 2).every((s) => s.status === 'rejected')) throw settled[0].reason;
  const byDate = new Map();
  for (const s of settled) {
    if (s.status !== 'fulfilled') continue;
    for (const { date, venue } of s.value) {
      if (!venue) continue;
      if (!byDate.has(date)) byDate.set(date, new Set());
      byDate.get(date).add(venue);
    }
  }
  return withPartial([...byDate].sort(([a], [b]) => a.localeCompare(b)).map(([date, set]) => ({
    date,
    venues: [...set].sort((a, b) => VENUE_BY_PREFIX.get(a).order - VENUE_BY_PREFIX.get(b).order),
  })), schedFailed);
}

// ---------------------------------------------------------------- 1日

function sortRaces(races) {
  return races.sort((a, b) => {
    if (a.postTime !== b.postTime) {
      if (a.postTime === null) return 1;
      if (b.postTime === null) return -1;
      return a.postTime.localeCompare(b.postTime);
    }
    return VENUE_BY_PREFIX.get(a.venue).order - VENUE_BY_PREFIX.get(b.venue).order || a.no - b.no;
  });
}

// 1日の全場データ(内部)。他場 DB + 高知 DB + アーカイブ(DB に無い race_id だけ)。
// アーカイブ由来は entries/results も持っているので getDayResults で再利用する
// 日単位の TTL: 前日以前でも結果未投入(status!=='done')のレースが残っていれば短い TTL にして、
// タブを開いたままでも遅延投入された結果が反映されるようにする(getRace と同じ考え方)
function ttlForDay(date) {
  return (val) => {
    // §67 B5 ⛔**欠けたまま覚えない**(この1か所が `day:` `dayres:` `rides:` の3つに効く)。
    //   でないと「過ぎた日で全レース done」は Infinity なので、障害が直っても画面が嘘のままになる
    if (val && val.partial) return 0;
    if (date >= todayJST()) return MIN;
    const races = val && (val.races || (val.items && val.items.map((it) => it.race))) || [];
    return races.every((r) => r.status === 'done') ? Infinity : MIN;
  };
}

function loadDay(date) {
  return ssMemo(`day:${date}`, ttlForDay(date), async () => {
    const settled = await Promise.allSettled([chihouDay(date), kochiDay(date), narDay(date)]);
    // §67 B5 ⛔落ちた源を覚える(⚠アーカイブはこの下で別に取り、失敗しても [] を返す作り)
    const dayFailed = failedOf(settled, [SOURCES.chihou, SOURCES.kochi, SOURCES.nar]);
    if (settled.every((s) => s.status === 'rejected')) throw settled[0].reason;
    const dbRaces = settled.flatMap((s) => (s.status === 'fulfilled' ? s.value : []));
    const known = new Set(dbRaces.map((r) => r.sourceId));
    const arc = await archiveDay(date, known);
    if (arc.failed) dayFailed.push(SOURCES.archive);      // §67 B5 直し(アーカイブ期の日で効く)
    const races = [...dbRaces, ...arc.map((a) => a.race)];
    await narFillDayStatus(races, date);
    const extra = await narSupplementDay(date, races);   // §13.2B-2: 既存ソースに無い (場,日,R) を公式データで足す
    await narFillDayConds(races, date);                  // §25.2: 空いている馬場・天候を公式の値で(同じ1本を使い回す)
    return withPartial({ races: sortRaces([...races, ...extra]), archived: arc }, dayFailed);
  }, {
    // 確定した過去の日だけ端末に置く(§24.1-3)。⛔§67 B5 欠けた日は**書かない**(sessionStorage にも残さない)
    persist: isDateStr(date) && date < todayJST(),
    ok: (v) => !v.partial && v.races.length > 0 && v.races.every((r) => r.status === 'done'),
  });
}

export async function getRaceDay(date) {
  if (!isDateStr(date)) return { date: String(date ?? ''), races: [] };
  const day = await loadDay(date);
  return withPartial({ date, races: day.races.map((r) => ({ ...r, extra: cloneExtra(r.extra) })) },
    day.failed || []);
}

// §51.1/§51.5 その日に開催している場(Venue.order 順の prefix)。**日の器は memo 済み**なので
// レースページ・騎乗馬の日ビューから呼んでも**通信は増えない**(同じ loadDay を待つだけ)。
// ⛔ここでは名前を返さない(画面は venueByPrefix で引く=名前の出どころを増やさない)
export async function getDayVenues(date) {
  if (!isDateStr(date)) return [];
  const day = await loadDay(date);
  const set = new Set(day.races.map((r) => r.venue));
  // ⚠配列にも印を生やす= `/rides` は場が0でも「取れなかった」を言えるようにする(⛔ここが唯一の伝え口)
  return withPartial(VENUES.filter((v) => set.has(v.prefix)).map((v) => v.prefix), day.failed || []);
}

// §Codex A8 その日の**公式の開催予定**(nar_meta `kaisai_schedule`・cloud/convene.py が入れる)。
// 出馬表がまだ無い場を「開催はありません」と言わないために画面が使う。
// ⛔過ぎた日は引かない(確定が正・予定は要らない)= 過去のページの通信は増えない。
// 返り = [{venue, mark}](予定が無い/取れないときは [])
export async function getDayPlanned(date) {
  if (!isDateStr(date) || date < todayJST()) return [];
  // §71 P1-1(Codex監査): ⛔取得失敗を [] に変換しない= 「予定0件」と「予定を確認できない」は別物。
  // 失敗はそのまま reject し、呼び出し側(top/venue-day/results)が allSettled の status で言い分ける。
  // 「本日の開催はありません」を名乗れるのは race と plan の**両方が正常に取れて両方0件**のときだけ
  const plan = await getKaisaiSchedule();
  const rows = plan && plan.days && typeof plan.days.get === 'function' ? plan.days.get(date) : null;
  if (!Array.isArray(rows)) return [];
  return rows.map((x) => ({ venue: str(x && x.venue), mark: str(x && x.mark) })).filter((x) => x.venue);
}

// §Codex A8 「予定だけの場」= 予定にあって**出馬表がまだ無い**場(Venue.order 順)。
// ⛔画面3つ(/results の場タブ・/calendar・トップの週間日程)で**同じ判定・同じ並び**にするため
//   ここに1つだけ置く(#168「押せないチップ」の型)。fixed/planned は prefix の配列でも
//   {venue} の配列でもよい(呼び出し側の持ち方が違うため)
export function planOnlyVenues(fixed, planned) {
  const key = (x) => str(x && typeof x === 'object' ? x.venue : x);
  const has = new Set((Array.isArray(fixed) ? fixed : []).map(key));
  const want = new Set();
  for (const p of (Array.isArray(planned) ? planned : [])) {
    const v = key(p);
    if (v && !has.has(v)) want.add(v);
  }
  return VENUES.filter((v) => want.has(v.prefix)).map((v) => v.prefix);
}

export function getDayResults(date) {
  if (!isDateStr(date)) return Promise.resolve({ date: String(date ?? ''), items: [] });
  return ssMemo(`dayres:${date}`, ttlForDay(date), async () => {
    const day = await loadDay(date);
    const top3 = new Map();     // Race.id → Result[]
    const pays = new Map();     // Race.id → Payout[]
    const resultEntries = new Map(); // `${Race.id}/${馬番}` → 安全に馬IDを引き継ぐ材料(高知だけ)
    const byVenue = new Map();
    for (const r of day.races) {
      if (!byVenue.has(r.venue)) byVenue.set(r.venue, []);
      byVenue.get(r.venue).push(r);
    }
    const arcIds = new Set(day.archived.map((a) => a.race.id));
    // §24.1-2 場ごとに 2 本ずつ引いていたのを、源ごとに 1 組へまとめる(nar / 高知 / 競馬ブック)
    const narVenues = [];       // 公式が主の場
    const chihouRaces = [];     // 競馬ブックが主の場のレース
    let kochiRaces = null;
    for (const [prefix, races] of byVenue) {
      if (prefix === 'kochi') { kochiRaces = races; continue; }
      const v = VENUE_BY_PREFIX.get(prefix);
      if (v && v.supported === 'nar') { narVenues.push(v); continue; }
      for (const r of races) if (!arcIds.has(r.id) && r.sourceKind !== 'nar') chihouRaces.push(r);
    }
    // 払戻は公式にしか無い高知も同じ1本に混ぜる(§18.1-1)
    const payTracks = narVenues.map(narTrackName);
    if (kochiRaces) payTracks.push(narTrackName(VENUE_BY_PREFIX.get('kochi')));

    await Promise.all([
      (async () => {
        // §28.1b アーカイブの日(2022-10 以前)は公式に何も無いので引きに行かない。
        // アーカイブの9場は supported:'nar' なので、これが無いと古い日でも毎回2本投げてしまう
        if (date < NAR_FROM) return;
        if (!narVenues.length && !payTracks.length) return;
        const tin = narVenues.length ? `track=in.(${enc(quoteIn(narVenues.map(narTrackName)))})` : null;
        const [res, pay] = await Promise.all([
          tin ? sbNar(`nar_runs?select=*&${tin}&race_date=eq.${date}&finish=lte.3`).catch(() => []) : Promise.resolve([]),
          payTracks.length
            ? sbNar(`nar_race_payouts?select=track,race_no,payouts&track=in.(${enc(quoteIn(payTracks))})&race_date=eq.${date}`).catch(() => [])
            : Promise.resolve([]),
        ]);
        const resBy = groupBy(res, (x) => `${str(x.track) ?? ''}/${Number(x.race_no)}`);
        const payBy = new Map();
        for (const p of (Array.isArray(pay) ? pay : [])) payBy.set(`${str(p.track) ?? ''}/${Number(p.race_no)}`, p);
        for (const v of narVenues) {
          const t = narTrackName(v);
          for (const r of (byVenue.get(v.prefix) || [])) {
            top3.set(r.id, sortResults((resBy.get(`${t}/${r.no}`) || []).map((x) => narResult(x, r.id))));
            pays.set(r.id, narPayoutList(payBy.get(`${t}/${r.no}`), r.id, NAR_FLASH_TICKETS));
          }
        }
        if (kochiRaces) {
          const t = narTrackName(VENUE_BY_PREFIX.get('kochi'));
          for (const r of kochiRaces) pays.set(r.id, narPayoutList(payBy.get(`${t}/${r.no}`), r.id, NAR_FLASH_TICKETS));
        }
      })(),
      (async () => {
        if (!kochiRaces) return;
        // 着順は keiba_horses が正(払戻は上の1本で入れている)。ただし結果が全行空の日もあるため、
        // 同じ1本で全出走馬のIDを受け、あとで公式補完と レース+馬番+馬名 が一致した馬だけ結ぶ(§85)。
        const kd = enc(toKochiDate(date));
        let rows;
        try {
          rows = await sb(`keiba_horses?select=${KOCHI_DAY_RESULT_COLS}&baba_code=eq.${KOCHI_BABA}` +
            `&race_date=eq.${kd}&order=race_no.asc,uma_ban.asc&limit=1000`);
        } catch { return; }
        const by = groupBy(rows, (h) => String(Number(h.race_no)));
        for (const r of kochiRaces) {
          const list = by.get(String(r.no)) || [];
          for (const h of list) {
            const uma = Number(h.uma_ban);
            const horseName = str(h.horse_name);
            const horseId = kochiHorseId(h);
            // 名前もIDもある行だけ。narResultFrom の名前照合を空値で通さない。
            if (!Number.isInteger(uma) || uma < 1 || !horseName || !horseId) continue;
            resultEntries.set(`${r.id}/${uma}`, {
              horseName, horseId,
              first3f: num(h.first3f), first3fF: num(h.first3f) === null ? null : 3,
              weight: num(h.kinryo),
            });
          }
          top3.set(r.id, sortResults(list.map((h) => kochiResult(h, r.id))
            .filter((x) => x.finish !== null && x.finish >= 1 && x.finish <= 3)));
        }
      })(),
      (async () => {
        if (!chihouRaces.length) return;
        const rids = chihouRaces.map((r) => r.sourceId).join(',');
        const [res, pay] = await Promise.all([
          sb(`chihou_results?select=*&race_id=in.(${rids})&finish=lte.3`).catch(() => []),
          sb(`chihou_payouts?select=race_id,ticket_type,combination,official_payout_per_100,popularity&race_id=in.(${rids})&ticket_type=in.(win,place)`).catch(() => []),
        ]);
        const resBy = groupBy(res, (x) => String(x.race_id));
        const payBy = groupBy(pay, (x) => String(x.race_id));
        for (const r of chihouRaces) {
          top3.set(r.id, sortResults((resBy.get(String(r.sourceId)) || []).map((x) => chihouResult(x, r.id, r.distance))));
          pays.set(r.id, sortPayouts((payBy.get(String(r.sourceId)) || []).map((x) => chihouPayout(x, r.id))));
        }
      })(),
    ]);
    for (const a of day.archived) {
      top3.set(a.race.id, a.results.filter((x) => x.finish !== null && x.finish <= 3));
    }
    await narFillDayResults(byVenue, date, top3, pays, resultEntries);
    const items = day.races.map((race) => ({
      race: { ...race, extra: cloneExtra(race.extra) },
      top3: (top3.get(race.id) || []).filter((x) => x.finish !== null && x.finish >= 1 && x.finish <= 3),
      payouts: pays.get(race.id) || [],
    }));
    // §67 B5 ⛔`loadDay` の印を**写す**(写し忘れると画面まで届かない)
    return withPartial({ date, items }, day.failed || []);
  }, {
    persist: isDateStr(date) && date < todayJST(),
    ok: (v) => !v.partial && v.items.length > 0 && v.items.every((it) => it.race.status === 'done'),
  });
}

// ---------------------------------------------------------------- 1レース

export function getRace(venue, date, no) {
  const v = VENUE_BY_PREFIX.get(String(venue ?? ''));
  const n = Number(no);
  if (!v || v.supported === 'none' || !isDateStr(date) || !Number.isInteger(n) || n < 1) return Promise.resolve(null);
  const ttl = (val) => (val && val.race.status === 'done' ? Infinity : MIN);
  return memo(`race:${v.prefix}/${date}/${n}`, ttl, async () => applyOdds(v, await loadRace(v, date, n)));
}

// レース1件を源ごとに組み立てる(§13.2B-3 の順番: nar 9場 → 高知 → 競馬ブック → アーカイブ → nar 補完)
async function loadRace(v, date, n) {
  if (v.supported === 'nar') {
    // §28.1b 公式は 2022-11 から。それ以前はその場のアーカイブに答えがある(公式が先=新しい日は必ず公式が勝つ)
    if (date < NAR_FROM) return archiveRace(v, date, n);
    const nr = await narRace(v, date, n);
    return nr || archiveRace(v, date, n);
  }
  if (v.supported === 'kochi') {
    const kr = await kochiRace(date, n);
    return kr ? narFallbackRace(v, kr) : narRace(v, date, n);
  }
  const db = await chihouRace(v, date, n);
  if (db) return narFallbackRace(v, db);
  const arc = await archiveRace(v, date, n);
  if (arc) return arc;
  return narRace(v, date, n);                                   // 競馬ブック/高知に行が無いレース
}

// §41-B 公式の1行を kb経路のレースに載せる。⚠**通過は公式で上書きする**(裁定)=
// 競馬ブック由来の通過は corners の無い日のフォールバックに降りる(値は消さない=集計側は今まで通り)
function applyNarRaceRow(r, row) {
  if (!row) return;
  // §79 P2 このレースの本賞金(1〜5着)と公式のレース名から読む条件クラス。
  // ⛔**上の1本に相乗り**なので通信は増えない。⚠先の日付は narFallbackRace が早く帰るので入らない
  if (r.race.prizeList == null && Array.isArray(row.prize_yen)) r.race.prizeList = row.prize_yen;
  if (!r.race.raceClass) r.race.raceClass = raceClassOf(str(row.race_name), str(row.race_kind));
  const corners = cornerList(row.corners);
  if (corners.length) {
    r.race.corners = corners;
    const pass = passingFromCorners(corners);
    for (const x of r.results) {
      const p = pass.get(x.umaban);
      if (p) x.passing = p;
    }
  }
  // ⚠高知は天候もレース上がりも自前の源に無い(#126)。**空いているときだけ**入れる(既存値は上書きしない)
  if (!r.race.weather) r.race.weather = str(row.weather);
  if (r.race.extra) {
    if (r.race.extra.agari3fRace == null) r.race.extra.agari3fRace = num(row.race_last3f);
    if (r.race.extra.agari4fRace == null) r.race.extra.agari4fRace = num(row.race_last4f);
    // §49 U-5 公式ハロンタイム。⛔既にある laps(高知=自前計測・競馬ブック=出所未確認)には触らない
    if (!r.race.extra.officialLaps) {
      const of = lapsOf(row.furlongs);
      r.race.extra.officialLaps = of && of.length ? of : null;
    }
  }
}

// アーカイブから1レース。その場のアーカイブが無い / その日が入っていないときは null
async function archiveRace(v, date, n) {
  if (!archive.on(v.prefix)) return null;
  const items = await archive.day(v.prefix, date).catch(() => []);
  const it = items.find((x) => Number(x.index.race_no) === n);
  return it ? narFallbackRace(v, archiveAssemble(v.prefix, it)) : null;
}

// ---------------------------------------------------------------- 馬

function chihouRunFromJoined(r) {
  const cr = r.chihou_races || {};
  const v = VENUE_BY_NAME.get(String(cr.track ?? '').trim());
  const prefix = v ? v.prefix : prefixFromRaceId(r.race_id);
  const date = String(cr.race_date ?? '');
  const no = num(cr.race_no);
  const nc = nameCond(cr.klass, cr.race_name, no ?? '');
  const distance = num(cr.distance_m);
  return {
    date,
    venue: prefix,
    raceId: prefix && date && no !== null ? `${prefix}/${date}/${no}` : null,
    raceNo: no,
    umaban: num(r.umaban),
    raceName: nc.name,
    distance,
    going: str(cr.going),
    ninki: num(r.pop),
    finish: num(r.finish),
    finishNote: str(r.finish_note),
    time: timeStr(r.time_str),
    ...chihouFirst3f(r, distance),
    last3f: num(r.last3f),
    jockey: str(r.jockey),
    weight: num(r.kinryo),
    bodyWeight: num(r.body_weight),
    margin: marginStr(r.margin),
    passing: str(r.passing),
  };
}

// アーカイブ history の run には track/race_no が無く race_id から取る。名前・条件も無い(race_name は null が多い)
function archiveRun(run) {
  const prefix = prefixFromRaceId(run.race_id);
  const date = String(run.date ?? '');
  const no = run.race_id ? Number(String(run.race_id).slice(10, 12)) : null;
  const distance = num(run.dist);
  const time = timeStr(run.time);
  const first3f = fillFirst3f(run.f3, timeToSec(time), run.l3, distance);
  return {
    date,
    venue: prefix,
    raceId: prefix && date && no ? `${prefix}/${date}/${no}` : null,
    raceNo: no || null,
    umaban: null,                                // history の run に馬番は無い(2026-08-23 実測)
    raceName: str(run.race_name),
    distance,
    going: str(run.going),
    ninki: num(run.pop),
    finish: num(run.fin),
    finishNote: null,
    time,
    first3f,
    first3fF: first3f === null ? null : first3fFOf(distance),
    last3f: num(run.l3),
    jockey: str(run.jockey),
    weight: num(run.kin),
    bodyWeight: num(run.weight),
    margin: marginStr(run.margin),
    passing: str(run.passing),
  };
}

// history run にはレース名が無いので、読み込み済みの index(日付→レース一覧)から名前・条件を補う
async function fillArchiveRaceNames(runs) {
  const targets = [...runs].filter(([, r]) => r.raceName === null && ARCHIVE_PREFIXES.includes(r.venue));
  if (!targets.length) return;
  const idx = {};
  for (const p of new Set(targets.map(([, r]) => r.venue))) {
    try { idx[p] = await archive.index(p); } catch { idx[p] = null; }
  }
  for (const [rid, r] of targets) {
    const list = idx[r.venue] && idx[r.venue].dates ? idx[r.venue].dates[r.date] : null;
    const hit = list && list.find((x) => String(x.race_id) === rid);
    if (hit) r.raceName = nameCond(hit.klass, hit.name, r.raceNo ?? '').name;
  }
}

function finishStats(runs) {
  const s = { starts: 0, wins: 0, seconds: 0, thirds: 0 };
  for (const r of runs) {
    if (r.finish === null) continue;
    s.starts++;
    if (r.finish === 1) s.wins++;
    else if (r.finish === 2) s.seconds++;
    else if (r.finish === 3) s.thirds++;
  }
  return s;
}
function sortRuns(runs) { return runs.sort((a, b) => b.date.localeCompare(a.date) || (b.raceNo ?? 0) - (a.raceNo ?? 0)); }

// §18.1-2 出馬表(chihou_entries)にだけある これからの出走。結果が無いので finish は null のまま返し、
// 馬ページの「次走」と成績表の先頭に出す。失敗しても走歴には影響させない(呼び出し側で握る)
async function chihouPlannedRuns(code) {
  // §40-1 body_weight も取る=**当日の馬体重は出馬表に出る**(門別 2026-08-27 R1 で 448(+6) を実測)。
  // 列を1つ足すだけなので通信は増えない。走り終われば結果側の値が使われる
  const ents = await sb(`chihou_entries?select=race_id,umaban,jockey,kinryo,body_weight&horse_id=eq.${enc(code)}&order=race_id.desc&limit=60`);   // race_id は年始まりの文字列=降順で新しい行から(60走超の古馬で未来行が切れないように)
  const list = Array.isArray(ents) ? ents : [];
  // race_id は 16 桁の数字だけを in.() に入れる(フィルタ構文を壊さない)
  const ids = [...new Set(list.map((e) => String(e.race_id ?? '')).filter((s) => /^\d+$/.test(s)))];
  if (!ids.length) return [];
  const today = todayJST();
  const rows = await sb(`chihou_races?select=race_id,track,race_date,race_no,distance_m,klass,race_name&race_id=in.(${ids.join(',')})`);
  const byId = new Map((Array.isArray(rows) ? rows : []).map((r) => [String(r.race_id), r]));
  const out = [];
  for (const e of list) {
    const info = byId.get(String(e.race_id ?? ''));
    if (!info) continue;
    const date = String(info.race_date ?? '');
    const no = num(info.race_no);
    if (!isDateStr(date) || date < today || no === null) continue;   // 済んだレースは結果側にある
    const v = VENUE_BY_NAME.get(String(info.track ?? '').trim());
    const prefix = v ? v.prefix : prefixFromRaceId(e.race_id);
    if (!prefix) continue;
    out.push({
      key: String(e.race_id),
      run: {
        date,
        venue: prefix,
        raceId: `${prefix}/${date}/${no}`,
        raceNo: no,
        umaban: num(e.umaban),
        raceName: nameCond(info.klass, info.race_name, no).name,
        distance: num(info.distance_m),
        going: null,
        ninki: null,
        finish: null,
        finishNote: null,
        time: null,
        first3f: null,
        first3fF: null,
        last3f: null,
        jockey: str(e.jockey),
        weight: num(e.kinryo),
        bodyWeight: num(e.body_weight),        // §40-1 発表されていれば当日の馬体重(まだなら null)
        margin: null,
        passing: null,
      },
    });
  }
  return out;
}

async function horseKb(code) {
  const cols = 'race_id,umaban,horse_name,finish,finish_note,pop,win_odds,time_str,time_sec,margin,first3f,last3f,passing,corner4_pos,jockey,kinryo,body_weight,sex_age,trainer,chihou_races(track,race_date,race_no,distance_m,going,klass,race_name)';
  const rows = await sb(`chihou_results?select=${cols}&horse_id=eq.${enc(code)}&order=chihou_races(race_date).desc&limit=300`);
  const runs = new Map(rows.map((r) => [String(r.race_id), chihouRunFromJoined(r)]));
  let name = rows.length ? str(rows[0].horse_name) : null;
  let sexAge = rows.length ? sexAgeStr(rows[0].sex_age) : null;
  let trainer = rows.length ? str(rows[0].trainer) : null;
  if (ARCHIVE_ENABLED) {
    let hist = null;
    try { hist = await archive.history(code.slice(-2).padStart(2, '0')); } catch { hist = null; }
    for (const run of (hist && hist[code]) || []) {
      const rid = String(run.race_id ?? '');
      if (!rid || runs.has(rid)) continue;                  // DB 優先で重複排除
      runs.set(rid, archiveRun(run));
    }
    await fillArchiveRaceNames(runs);
    if (!name && runs.size) {
      // history には馬名が無いので最新走の pack から拾う
      const latest = sortRuns([...runs.values()])[0];
      try {
        const items = await archive.day(latest.venue, latest.date);
        const it = items.find((x) => Number(x.index.race_no) === latest.raceNo);
        const me = it && (it.row.results || []).find((r) => String(r.horse_id) === code);
        if (me) { name = str(me.horse_name); sexAge = sexAgeStr(me.sex_age); trainer = str(me.trainer); }
      } catch { /* 名前が取れないだけ。走歴は返す */ }
    }
  }
  // §18.1-2: これからの出走(出馬表だけにある)を足す。日付降順なので先頭に来る
  try {
    for (const p of await chihouPlannedRuns(code)) if (!runs.has(p.key)) runs.set(p.key, p.run);
  } catch { /* 予定が取れないだけ。走歴はそのまま返す */ }
  const list = sortRuns([...runs.values()]).slice(0, 300);
  if (!list.length) return null;
  return { id: `kb:${code}`, name: name || '(馬名不明)', venue: list[0].venue, sexAge, trainer, runs: list, stats: finishStats(list) };
}

function kochiRun(h, raceInfo) {
  const date = fromKochiDate(h.race_date);
  const no = Number(h.race_no);
  const f = kochiFinish(h);
  const info = raceInfo || {};
  return {
    date,
    venue: 'kochi',
    raceId: `kochi/${date}/${no}`,
    raceNo: no,
    umaban: num(h.uma_ban),
    raceName: str(info.race_name) || null,
    distance: distNum(info.distance),
    going: str(info.track_cond),
    ninki: num(h.ninki),
    finish: f.finish,
    finishNote: f.note,
    time: timeStr(h.time),
    first3f: num(h.first3f),
    first3fF: num(h.first3f) === null ? null : 3,   // 高知は常に 3F
    last3f: num(h.agari3f),
    jockey: str(h.jockey),
    weight: num(h.kinryo),
    bodyWeight: kochiWeight(h.weight).bodyWeight,
    margin: marginStr(h.diff),
    passing: str(h.corner),
  };
}

async function horseKochi(kind, key) {
  const base = `keiba_horses?select=*&baba_code=eq.${KOCHI_BABA}`;
  let rows = [];
  let code = null, name = null;
  if (kind === 'kochi') {
    code = key;
    rows = await sb(`${base}&lineage_login_code=eq.${enc(code)}&order=race_date.desc&limit=200`);
    name = rows.length ? str(rows[0].horse_name) : null;
  } else {
    name = key;
  }
  // 古い行は lineage_login_code が空のことがある(同馬で '' と code が混在=実測)。
  // 馬名で引いた行のうち code が空か同じものだけを足す(同名異馬の混入を避ける)
  if (name) {
    const extra = await sb(`${base}&horse_name=eq.${enc(name)}&order=race_date.desc&limit=200`).catch(() => []);
    const ids = new Set(rows.map((r) => r.id));
    for (const r of extra) {
      const c = str(r.lineage_login_code);
      if (ids.has(r.id)) continue;
      if (kind === 'kochi' ? (c === null || c === code) : c === null) rows.push(r);
    }
  }
  if (!rows.length) return null;
  const ids = [...new Set(rows.map((r) => `race_${KOCHI_BABA}_${r.race_date}_${r.race_no}`))];
  // id=in.(…) は 1 件 ≈36 文字。長寿馬(最大 400 件)で URL が 10KB を超えないよう 100 件ずつに分ける
  const infoRows = (await Promise.all(chunk(ids, 100).map((part) =>
    sb(`keiba_races?select=id,race_date,race_no,race_name,distance,race_class,track_cond&baba_code=eq.${KOCHI_BABA}&id=in.(${enc(quoteIn(part))})`).catch(() => [])
  ))).flat();
  const info = new Map(infoRows.map((r) => [String(r.id), r]));
  const runs = sortRuns(rows.map((h) => kochiRun(h, info.get(`race_${KOCHI_BABA}_${h.race_date}_${h.race_no}`)))).slice(0, 300);
  const latest = rows.slice().sort((a, b) => String(b.race_date).localeCompare(String(a.race_date)))[0];
  const belong = str(latest.belong);
  return {
    id: kind === 'kochi' ? `kochi:${code}` : `name:${name}`,
    name: str(latest.horse_name) || name || '',
    venue: belong ? ((VENUE_BY_NAME.get(belong) || {}).prefix ?? null) : 'kochi',
    sexAge: sexAgeStr(latest.sex_age),
    trainer: str(latest.trainer),
    runs,
    stats: finishStats(runs),
  };
}

export function getHorse(id) {
  const s = String(id ?? '');
  const m = s.match(/^(kb|kochi|name|nar|narb):(.+)$/);
  if (!m) return Promise.resolve(null);
  const [, kind, key] = m;
  if (kind === 'kb' && !/^\d{7}$/.test(key)) return Promise.resolve(null);
  let narb = null;
  if (kind === 'narb') {
    narb = /^(\d{4}-\d{2}-\d{2}):(.+)$/.exec(key);
    if (!narb || !isDateStr(narb[1]) || !str(narb[2])) return Promise.resolve(null);
  }
  return memo(`horse:${s}`, 5 * MIN, () => {
    if (kind === 'kb') return horseKb(key);
    if (kind === 'nar') return horseNar(key);
    if (kind === 'narb') return horseNar(narb[2], narb[1], s);
    return horseKochi(kind, key);
  });
}

export async function searchHorses(q) {
  const raw = cleanKw(q);
  if (raw.length < 2) return [];
  const like = enc(raw) + '*';
  // 「行」に limit をかけてから馬単位に dedupe するので、出走数の多い馬が枠を食うと該当馬が落ちる
  // (実測 'アイ*' で 60 行→32 頭)。当面は 300 行+馬名順で取り、dedupe 後に 20 件へ切る
  const settled = await Promise.allSettled([
    sb(`chihou_results?select=horse_id,horse_name&horse_name=like.${like}&order=horse_name.asc&limit=300`),
    sb(`keiba_horses?select=horse_name,lineage_login_code&baba_code=eq.${KOCHI_BABA}&horse_name=like.${like}&order=horse_name.asc&limit=300`),
    sbNar(`nar_runs?select=horse_name,track,race_date&${NAR_TRACK_IN}&horse_name=like.${like}&order=horse_name.asc,race_date.desc&limit=300`),
  ]);
  const out = new Map();
  if (settled[0].status === 'fulfilled') {
    for (const r of settled[0].value) {
      const id = kbId(r.horse_id);
      if (id && !out.has(id)) out.set(id, { id, name: str(r.horse_name) || '', venue: null });
    }
  }
  if (settled[1].status === 'fulfilled') {
    const coded = new Set(settled[1].value.map((r) => str(r.lineage_login_code) && str(r.horse_name)).filter(Boolean));
    for (const r of settled[1].value) {
      const id = kochiHorseId(r);
      if (!id || out.has(id)) continue;
      if (id.startsWith('name:') && coded.has(str(r.horse_name))) continue;   // 同馬に code 付き行があれば name: は出さない
      out.set(id, { id, name: str(r.horse_name) || '', venue: 'kochi' });
    }
  }
  if (settled[2].status === 'fulfilled') {
    // 馬名で dedupe(並びが race_date.desc なので最初の行=最新走の場)。kb:/kochi: と同名でも落とさない(id が違う)
    for (const r of settled[2].value) {
      const id = narHorseId(r);
      if (!id || out.has(id)) continue;
      out.set(id, { id, name: str(r.horse_name) || '', venue: narPrefixOf(r.track) });
    }
  }
  return [...out.values()].sort((a, b) => a.name.localeCompare(b.name, 'ja')).slice(0, 20);
}

// ---------------------------------------------------------------- §11.3 nar フォールバック(既存6場の結果・払戻を nar-official で補う)

// nar の1行 → Result。horseId・first3f は同じ馬番の既存 Entry から(nar: の ID は作らない)。passing は元行に無いので null のまま
// 斤量は発走前に決まる値なので、公式行で欠けているとき(2026-08-01 高知 R10 #8・実測)だけ出馬表の値で補う
// 同じ馬番でも馬名が食い違う(出馬表の取り直し漏れ・枠順変更)ときは別馬とみなし、既存 Entry の ID を付けない(別の馬のページへ飛ばさない)
function normName(s) { return String(s ?? '').replace(/[\s　]+/g, '').normalize('NFKC'); }
// §85 高知の日別結果でだけ使う厳密照合。両方の名前があり、正規化後に同じときだけ同一馬とする。
// 既存 sameHorse はレース画面の欠損補完でも使うため、その緩い規則は変えない。
export function sameHorseStrict(left, right) {
  const a = normName(left), b = normName(right);
  return !!a && !!b && a === b;
}
function sameHorse(entry, narName) {
  const a = normName(entry && entry.horseName), b = normName(narName);
  return !a || !b || a === b;
}
function narResultFrom(x, raceId, entry) {
  const res = narResult(x, raceId);
  res.horseId = null;                            // nar: の ID はフォールバックでは作らない(§11.3)
  if (entry && sameHorse(entry, x.horse_name)) {
    res.horseId = entry.horseId;
    res.first3f = entry.first3f;
    res.first3fF = entry.first3fF ?? null;
    if (res.weight === null) res.weight = entry.weight;
  }
  return res;
}
// 1着馬(同着は両方)だけ単勝払戻÷100 を確定単勝に(narRace と同じ規則。既に単勝がある行は触らない)
function fillWinOdds(results, payouts) {
  for (const r of results) {
    if (r.finish !== 1 || r.odds !== null) continue;
    const win = payouts.find((p) => p.ticketType === 'win' && p.combination === String(r.umaban));
    if (win) r.odds = Math.round(win.yen) / 100;
  }
}

// getRace の chihou/kochi/archive 経路の戻りに対して(§11.3 1〜3):
//  1. date ≤ 今日で結果 0 件 → nar_runs に 1 着があれば results を nar から作る(status=done・headCount も)
//  2. 結果はあるが Result の無い馬(高知の競走中止は chakujun '')→ nar の同馬番に注記があれば finish null で末尾に足す
//  3. done で払戻 0 件 → nar_race_payouts(高知は常に [] なのでここで埋まる)
// nar 側の失敗は握って既存の戻りをそのまま返す。出馬表(Entry)は nar から作らない
async function narFallbackRace(v, r) {
  if (!r) return r;
  if (r.race.date < NAR_FROM) return r;            // 公式が始まる前=補完のあてが無い(§28.1b)
  const future = r.race.date > todayJST();
  const needEntries = r.entries.length === 0;      // §13.2B-4: race 行はあるのに出馬表が空(競馬ブックの取込前)
  if (future && !needEntries) return r;            // 先の日付に結果・払戻は無い
  const t = enc(narTrackName(v)), d = r.race.date, n = r.race.no;
  // §41-B **通過は公式で全15場そろえる**(ユーザー裁定 2026-08-27)。corners・レース上がり・天候は
  // 競馬ブック / 高知の源に無いので、ここで nar_races を **+1本**引く(この経路=門別・南関4場・高知だけ)
  // §49 U-5 furlongs(公式ハロンタイム)も**この1本に相乗り**させる=通信の本数は増えない
  const narRow = sbNar(`nar_races?select=corners,race_last3f,race_last4f,weather,furlongs,prize_yen,race_name,race_kind&track=eq.${t}` +
    `&race_date=eq.${d}&race_no=eq.${n}&limit=1`).then((x) => (Array.isArray(x) && x.length ? x[0] : null)).catch(() => null);
  const has = new Set(r.results.map((x) => x.umaban));
  const missing = r.entries.filter((e) => !has.has(e.umaban));
  if (needEntries || r.results.length === 0 || (r.race.status === 'done' && missing.length)) {
    const runs = await sbNar(`nar_runs?select=*&track=eq.${t}&race_date=eq.${d}&race_no=eq.${n}&order=runner_number.asc`).catch(() => []);
    if (needEntries && runs.length) {
      r.entries = runs.map((x) => narEntry(x, r.race.id, r.race.banei)).sort((a, b) => a.umaban - b.umaban);
      r.race.headCount = narHeadCount(runs, r.race.headCount);
    }
    const byUma = new Map(r.entries.map((e) => [e.umaban, e]));
    if (!future && r.results.length === 0 && narDone(runs)) {
      r.results = sortResults(runs.map((x) => narResultFrom(x, r.race.id, byUma.get(Number(x.runner_number)) || null)));
      r.race.status = 'done';
      r.race.headCount = narHeadCount(runs, r.race.headCount);
    } else if (!future && r.results.length) {
      for (const e of missing) {
        const x = runs.find((y) => Number(y.runner_number) === e.umaban);
        if (x && narNote(x).note !== null) r.results.push(narResultFrom(x, r.race.id, e));
      }
      sortResults(r.results);
    }
    // §25.1 当日の馬体重。公式(nar_runs)は競馬ブックより先に入ることがある
    // (2026-08-25 実測: 船橋1〜4R は 競馬ブック 0/N・公式 N/N)。**空いている馬だけ**埋める(既存値は上書きしない)。
    // 確定レースでも結果が公式由来なら出馬表だけ「—」になるので、そこも同じ値でそろえる。
    // 取得は上の nar_runs に相乗りなので追加クエリは無い
    for (const x of runs) {
      const e = byUma.get(Number(x.runner_number));
      if (!e || e.bodyWeight !== null || !sameHorse(e, x.horse_name)) continue;
      const bw = num(x.body_weight);
      if (bw === null) continue;
      e.bodyWeight = bw;
      if (e.bodyWeightDiff === null) e.bodyWeightDiff = num(x.body_weight_change);
    }
    // nar に取消・除外・中止・失格の注記がある馬は出馬表でも旗を立て、種別(scratchKind)も付ける(既存の種別があればそのまま。馬名が一致する馬番だけ)
    for (const x of runs) {
      const e = byUma.get(Number(x.runner_number));
      const note = narNote(x).note;
      if (!e || note === null || !sameHorse(e, x.horse_name)) continue;
      e.scratched = true;
      if (e.scratchKind == null) e.scratchKind = scratchKindOf(note);
    }
  }
  if (!future && r.race.status === 'done' && r.payouts.length === 0) {
    const rows = await sbNar(`nar_race_payouts?select=payouts&track=eq.${t}&race_date=eq.${d}&race_no=eq.${n}&limit=1`).catch(() => []);
    if (rows.length) r.payouts = narPayoutList(rows[0], r.race.id, null);
  }
  applyNarRaceRow(r, await narRow);                // §41-B 公式の corners・上り・天候を載せる
  fillWinOdds(r.results, r.payouts);
  return r;
}

// 場単位の nar 1日分(runs ≤192 行・払戻 ≤12 行)。loadDay と getDayResults で共有。全馬に着順か注記が付いていれば永続
// §24.1-2 その日のフォールバック対象(既存6場)をまとめて1回で取る。Map(prefix → {runs, pays})。
// 場ごとに引くと 2×場数 本になっていた(2026-08-25 実測: 門別・船橋で4本)
function narDayFillAll(date) {
  const ttl = (val) => {
    for (const x of val.values()) {
      if (!x.runs.length || !x.runs.every((r) => narFinish(r) !== null || narNote(r).note !== null)) return MIN;
    }
    return val.size ? Infinity : MIN;
  };
  return memo(`narfillall:${date}`, ttl, async () => {
    const [runs, pays] = await Promise.all([
      sbNar('nar_runs?select=track,race_no,runner_number,horse_name,finish,finish_note,margin,time_sec,last3f,popularity' +
        `&${NAR_FALLBACK_IN}&race_date=eq.${date}`).catch(() => []),
      sbNar(`nar_race_payouts?select=track,race_no,payouts&${NAR_FALLBACK_IN}&race_date=eq.${date}`).catch(() => []),
    ]);
    const out = new Map();
    const put = (row, key) => {
      const prefix = narPrefixOf(row.track);
      if (!prefix) return;
      if (!out.has(prefix)) out.set(prefix, { runs: [], pays: [] });
      out.get(prefix)[key].push(row);
    };
    for (const r of (Array.isArray(runs) ? runs : [])) put(r, 'runs');
    for (const p of (Array.isArray(pays) ? pays : [])) put(p, 'pays');
    return out;
  });
}

// 1場ぶんの取り出し(返り値の形は従来どおり {runs, pays})
async function narDayFill(v, date) {
  const all = await narDayFillAll(date);
  return all.get(v.prefix) || { runs: [], pays: [] };
}
// §13.2B-2: その日の nar_races のうち、既存ソースに (場, R) が無いレースを Race にして返す(帯広・nar 8場は narDay が入れている)。
// 頭数と確定は場ごとの runs(narDayFill・≤192 行)で埋める。nar 側の失敗は握って [] を返す(既存の一覧は壊さない)
// §25.2 その日の公式レース行(既存6場ぶん)。narSupplementDay と 馬場・天候の補完で共有する(1クエリのまま)
function narFallbackRacesDay(date) {
  return memo(`narfbraces:${date}`, ttlForDate(date), () =>
    sbNar(`nar_races?select=${NAR_RACE_COLS}&${NAR_FALLBACK_IN}&race_date=eq.${date}&order=track.asc,race_no.asc`)
      .catch(() => []));
}

// §25.2 競馬ブック・高知の行は当日の馬場/天候が空のことがある(2026-08-25 実測: 門別・船橋とも null)。
// narSupplementDay と同じ1本を使い回して、空いているところだけ公式の値で埋める(追加クエリなし)
async function narFillDayConds(races, date) {
  if (date < NAR_FROM) return;                     // 公式が始まる前(§28.1b のアーカイブ日)
  // §27.2 区分(重賞・準重賞)も同じ1本で埋める
  const need = races.filter((r) => !r.going || !r.weather || !r.kind);
  if (!need.length) return;
  let rows;
  try { rows = await narFallbackRacesDay(date); } catch { return; }
  const by = new Map();
  for (const row of (Array.isArray(rows) ? rows : [])) {
    const prefix = narPrefixOf(row.track);
    const no = num(row.race_no);
    if (prefix && no !== null) by.set(`${prefix}/${no}`, row);
  }
  for (const r of need) {
    const row = by.get(`${r.venue}/${r.no}`);
    if (!row) continue;
    const v = VENUE_BY_PREFIX.get(r.venue);
    if (!r.going) r.going = baneiGoing(!!(v && v.banei), row.going);
    if (!r.weather) r.weather = str(row.weather);
    if (!r.kind) r.kind = raceKind(row.race_kind);
  }
}

async function narSupplementDay(date, races) {
  const have = new Set(races.map((r) => `${r.venue}/${r.no}`));
  let rows;
  try {
    rows = await narFallbackRacesDay(date);
  } catch { return []; }
  const byVenue = new Map();
  for (const row of rows) {
    const prefix = narPrefixOf(row.track);
    const no = Number(row.race_no);
    if (!prefix || !Number.isInteger(no) || have.has(`${prefix}/${no}`)) continue;
    if (!byVenue.has(prefix)) byVenue.set(prefix, []);
    byVenue.get(prefix).push(row);
  }
  const out = [];
  await Promise.all([...byVenue].map(async ([prefix, list]) => {
    const v = VENUE_BY_PREFIX.get(prefix);
    let fill = null;
    try { fill = await narDayFill(v, date); } catch { fill = null; }
    for (const row of list) {
      const race = narRaceFromRow(row, prefix);
      const rs = fill ? fill.runs.filter((x) => Number(x.race_no) === race.no) : [];
      race.headCount = narHeadCount(rs, race.headCount);
      race.status = statusOf(narDone(rs), race.date);
      out.push(race);
    }
  }));
  return out;
}

function fallbackVenue(prefix) {
  const v = VENUE_BY_PREFIX.get(prefix);
  return v && (v.supported === 'chihou' || v.supported === 'kochi') ? v : null;
}
// loadDay(§11.3 4): 場ごとに done が 0 件で date ≤ 今日なら nar_runs で status / headCount を埋める
async function narFillDayStatus(races, date) {
  if (date > todayJST()) return;
  const byVenue = new Map();
  for (const r of races) {
    if (!byVenue.has(r.venue)) byVenue.set(r.venue, []);
    byVenue.get(r.venue).push(r);
  }
  await Promise.all([...byVenue].map(async ([prefix, list]) => {
    const v = fallbackVenue(prefix);
    if (!v || !list.some((r) => r.status !== 'done')) return;
    let fill;
    try { fill = await narDayFill(v, date); } catch { return; }
    for (const r of list) {
      if (r.status === 'done') continue;
      const rs = fill.runs.filter((x) => Number(x.race_no) === r.no);
      if (!narDone(rs)) continue;
      r.status = 'done';
      r.headCount = narHeadCount(rs, r.headCount);
    }
  }));
}
// getDayResults(§11.3 4): 既存源の上位3着が場ごとに 0 件なら nar の runs / 払戻で top3 と単複を埋める。
// horseId は原則作らない。§85 の高知だけ、同じレース+馬番+馬名で確認済みの自前IDを引き継ぐ。
async function narFillDayResults(byVenue, date, top3, pays, resultEntries) {
  if (date > todayJST() || date < NAR_FROM) return;
  await Promise.all([...byVenue].map(async ([prefix, list]) => {
    const v = fallbackVenue(prefix);
    const need = list.filter((r) => r.status !== 'pre' && !(top3.get(r.id) || []).length);
    if (!v || !need.length) return;
    let fill;
    try { fill = await narDayFill(v, date); } catch { return; }
    for (const r of need) {
      const rs = fill.runs.filter((x) => Number(x.race_no) === r.no);
      if (!narDone(rs)) continue;
      const res = rs.filter((x) => narNote(x).note === null && narFinish(x) !== null && narFinish(x) <= 3)
        .map((x) => {
          const candidate = resultEntries && resultEntries.get(`${r.id}/${Number(x.runner_number)}`) || null;
          // レースID+馬番に加えて、**両方にある馬名**も一致したときだけIDを渡す。
          const entry = candidate && sameHorseStrict(candidate.horseName, x.horse_name) ? candidate : null;
          return narResultFrom(x, r.id, entry);
        });
      top3.set(r.id, sortResults(res));
      if (!(pays.get(r.id) || []).length) {
        pays.set(r.id, narPayoutList(fill.pays.find((x) => Number(x.race_no) === r.no), r.id, NAR_FLASH_TICKETS));
      }
    }
  }));
}

// ---------------------------------------------------------------- §13.2C 当日オッズ(nar_race_odds)

const ODDS_COLS = 'track,race_date,race_no,observed_at,is_final,runners';

// 1行 → {observedAt, isFinal, byUmaban}。runners = [{n:馬番, w:単勝, pl:複勝の下限, ph:複勝の上限}]。発売前・取消は null
function oddsFromRow(row) {
  const byUmaban = new Map();
  for (const x of (Array.isArray(row && row.runners) ? row.runners : [])) {
    const n = num(x && x.n);
    if (n === null) continue;
    byUmaban.set(n, { win: num(x.w), placeLow: num(x.pl), placeHigh: num(x.ph) });
  }
  return { observedAt: str(row && row.observed_at), isFinal: (row && row.is_final) === true, byUmaban };
}

// 単勝がいちばん低い馬(同値は馬番の小さい方)。馬名は nar_runs から引けたときだけ
function oddsFavorite(o, names, no) {
  let best = null;
  for (const [umaban, x] of o.byUmaban) {
    if (x.win === null) continue;
    if (!best || x.win < best.win || (x.win === best.win && umaban < best.umaban)) best = { umaban, win: x.win };
  }
  return best ? { ...best, horseName: (names && names.get(`${no}-${best.umaban}`)) ?? null } : null;
}

// 1レース分(≤1 行)。行が無ければ null。最終オッズは変わらないので永続、それ以外は 60 秒
export function getRaceOdds(venue, date, no) {
  const v = VENUE_BY_PREFIX.get(String(venue ?? ''));
  const n = Number(no);
  if (!v || !isDateStr(date) || !Number.isInteger(n) || n < 1) return Promise.resolve(null);
  const ttl = (val) => (val && val.isFinal ? Infinity : MIN);
  return memo(`odds:${v.prefix}/${date}/${n}`, ttl, async () => {
    const rows = await sbNar(`nar_race_odds?select=${ODDS_COLS}&track=eq.${enc(narTrackName(v))}&race_date=eq.${date}&race_no=eq.${n}&limit=1`);
    return Array.isArray(rows) && rows.length ? oddsFromRow(rows[0]) : null;
  });
}

// その日の全レース分。Map(Race.id → {observedAt, isFinal, byUmaban, fav})。
// §24.1-2 場ごとに 2 本ずつ引いていたのを、オッズ1本+馬名1本の計2本に束ねた
export function getDayOdds(date) {
  if (!isDateStr(date)) return Promise.resolve(new Map());
  return memo(`dayodds:${date}`, MIN, async () => {
    const out = new Map();
    let day;
    try { day = await loadDay(date); } catch { return out; }
    const venues = [...new Set(day.races.map((r) => r.venue))]
      .map((p) => VENUE_BY_PREFIX.get(p)).filter(Boolean);
    if (!venues.length) return out;
    const tin = `track=in.(${enc(quoteIn(venues.map(narTrackName)))})`;
    let rows = [];
    try { rows = await sbNar(`nar_race_odds?select=${ODDS_COLS}&${tin}&race_date=eq.${date}`); } catch { return out; }
    if (!Array.isArray(rows) || !rows.length) return out;
    // 馬名はオッズのある (場, R) だけ。1本にまとめて or=(and(…)) で引く(60 レースずつ)
    const keys = [];
    for (const r of rows) {
      const t = str(r.track);
      const no = num(r.race_no);
      if (t && no !== null) keys.push({ track: t, no });
    }
    // 場ごとの Map('R-馬番' → 馬名)。oddsFavorite が従来どおりこの形を見る
    const namesByTrack = new Map();
    await Promise.all(chunk(keys, 60).map(async (part) => {
      const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_no.eq.${k.no})`).join(',');
      try {
        const runs = await sbNar('nar_runs?select=track,race_no,runner_number,horse_name' +
          `&race_date=eq.${date}&or=(${cond})&limit=1000`);
        for (const x of (Array.isArray(runs) ? runs : [])) {
          const t = str(x.track);
          if (!t) continue;
          if (!namesByTrack.has(t)) namesByTrack.set(t, new Map());
          namesByTrack.get(t).set(`${Number(x.race_no)}-${Number(x.runner_number)}`, str(x.horse_name));
        }
      } catch { /* 馬名が取れなくても倍率は返す */ }
    }));
    for (const row of rows) {
      const t = str(row.track);
      const prefix = t ? narPrefixOf(t) : null;
      const no = Number(row.race_no);
      if (!prefix || !Number.isInteger(no)) continue;
      const local = namesByTrack.get(t) || new Map();
      const o = oddsFromRow(row);
      // §22.5 オッズ一覧で馬名を出すため、引いてある名前を各馬にも入れておく
      for (const [n, x] of o.byUmaban) x.horseName = local.get(`${no}-${n}`) ?? null;
      out.set(`${prefix}/${date}/${no}`, { ...o, fav: oddsFavorite(o, local, no) });
    }
    return out;
  });
}

// §22.5 の契約名。getDayOdds は元から「その日の全レース」を返すので中身は同じ
export const getDayOddsAll = getDayOdds;

// §77 W3 単勝の2分刻み(nar_odds_ticks・公開リポの収集が発走40分前から足す)。
// → {final, ticks:[{t, f, w:Map(馬番→単勝|null), p:Map(馬番→[下限,上限])}]}(id 昇順=時刻順)。
// ⛔**1レース分だけ**引く(日単位で引くと 1000行上限を踏む)。
// ⛔`nar_race_odds.history`(§76・約20分粒度)は読まない・触らない(契約と文言を変えない)。
// ⛔単勝 0 以下・馬番が無い= 発売前/取消= null(線も点も描かない)。
// TTL= 最終なら永続、それ以外 60 秒(getRaceOdds と同じ流儀)
export function getRaceTicks(venue, date, no) {
  const v = VENUE_BY_PREFIX.get(String(venue ?? ''));
  const n = Number(no);
  const empty = { final: false, ticks: [] };
  if (!v || !isDateStr(date) || !Number.isInteger(n) || n < 1) return Promise.resolve(empty);
  const ttl = (val) => (val && val.final ? Infinity : MIN);
  return memo(`ticks:${v.prefix}/${date}/${n}`, ttl, async () => {
    let rows;
    try {
      // §123 u1= 馬単1着の合成・s1= 3連単1着の合成(どちらも**収集側で計算**して jsonb で入っている)。
      //   ⛔画面では計算しない= 行の値をそのまま出すだけ。古い行・全券種が取れなかった周は null
      rows = await sbNar('nar_odds_ticks?select=t,asof,f,w,p,u1,s1' +
        `&track=eq.${enc(narTrackName(v))}&race_date=eq.${date}&race_no=eq.${n}&order=id.asc&limit=1000`);
    } catch { return empty; }
    if (!Array.isArray(rows) || !rows.length) return empty;
    const toMap = (o, pick) => {
      const m = new Map();
      for (const [k, val] of Object.entries(o && typeof o === 'object' ? o : {})) {
        const u = Number(k);
        if (Number.isFinite(u)) m.set(u, pick(val));
      }
      return m;
    };
    const ticks = [];
    for (const r of rows) {
      const t = str(r.t);
      if (!t) continue;
      ticks.push({
        t,
        // §90 asof= 主催者のページに書いてある「HH:MM 現在」。⛔取りに行った時刻(t)とは 1〜7 分ずれる。
        //   最終オッズのページは時刻を書かない= null(そこは f で分かる)
        asof: str(r.asof) || null,
        f: r.f === true,
        w: toMap(r.w, (x) => { const o = num(x); return o !== null && o > 0 ? o : null; }),
        p: r.p ? toMap(r.p, (x) => (Array.isArray(x) ? x.map(num) : null)) : null,
        // §123 列ごと null の周(改修前の行・全券種の取得が落ちた周)は Map ではなく **null**=
        //   画面が「記録が無い」と「値が無い」を言い分けられる
        u1: r.u1 ? toMap(r.u1, synthNum) : null,
        s1: r.s1 ? toMap(r.s1, synthNum) : null,
      });
    }
    return { final: ticks.some((x) => x.f), ticks };
  });
}

// §123 合成オッズの値。⛔0 以下・数でないものは null(無い馬番はそもそも載っていない)
function synthNum(x) {
  const o = num(x);
  return o !== null && o > 0 ? o : null;
}

// §77 W2 全券種オッズ(nar_odds_full・W1 が20分おきに写している)。1レース ≤7行を**1本**で取る。
// → {observedAt, isFinal, kinds:{umaren:[[a,b,o,r]…], …, wakuren:[[i,j,o]]}} / 行が無ければ null。
// ⛔**押したときだけ**呼ぶ(レースページ本体・トップ・/odds の通信は前後同一)。
// ⛔combos は公式の写しそのまま渡す= 0.0(まだ売れていない組)も同順位の人気も画面側で扱う。
// ⛔`wakutan` の行が無い場がある(門別・名古屋は枠連単を売っていない)= 鍵が無い券種は「その場に無い」。
// TTL= 全券種が最終なら永続、それ以外 60 秒(単複の getRaceOdds と同じ考え)
const ODDS_FULL_KINDS = ['wakuren', 'wakutan', 'umaren', 'umatan', 'wide', 'sanrenpuku', 'sanrentan'];
export function getRaceOddsFull(venue, date, no) {
  const v = VENUE_BY_PREFIX.get(String(venue ?? ''));
  const n = Number(no);
  if (!v || !isDateStr(date) || !Number.isInteger(n) || n < 1) return Promise.resolve(null);
  const ttl = (val) => (val && val.isFinal ? Infinity : MIN);
  return memo(`oddsfull:${v.prefix}/${date}/${n}`, ttl, async () => {
    let rows;
    try {
      rows = await sbNar('nar_odds_full?select=kind,is_final,observed_at,combos' +
        `&track=eq.${enc(narTrackName(v))}&race_date=eq.${date}&race_no=eq.${n}`);
    } catch { return null; }
    if (!Array.isArray(rows) || !rows.length) return null;
    const kinds = {};
    let observedAt = null;
    let isFinal = true;
    for (const r of rows) {
      const k = str(r.kind);
      if (!k || !ODDS_FULL_KINDS.includes(k) || !Array.isArray(r.combos) || !r.combos.length) continue;
      kinds[k] = r.combos;
      const at = str(r.observed_at);
      if (at && (!observedAt || at > observedAt)) observedAt = at;
      if (r.is_final !== true) isFinal = false;
    }
    return Object.keys(kinds).length ? { observedAt, isFinal, kinds } : null;
  });
}

// 出馬表に当日オッズを重ねる。単勝は「値が無い馬」だけ(競馬ブック/高知の値は上書きしない)。複勝はここでしか入らない
async function applyOdds(v, r) {
  if (!r || !r.entries.length) return r;
  let o = null;
  try { o = await getRaceOdds(v.prefix, r.race.date, r.race.no); } catch { o = null; }
  if (!o) return r;
  r.race.oddsAt = o.observedAt;
  r.race.oddsFinal = o.isFinal;
  for (const e of r.entries) {
    const x = o.byUmaban.get(e.umaban);
    if (!x) continue;
    if (e.odds === null && x.win !== null) { e.odds = x.win; e.oddsObservedAt = o.observedAt; }
    if (e.placeLow === null && x.placeLow !== null) { e.placeLow = x.placeLow; e.placeHigh = x.placeHigh; }
  }
  return r;
}

// ---------------------------------------------------------------- §11.2 独自データ(getRaceOwn / getHorseOwn / getOwnSummary)

// パドック索引 {base, days: {'YYYY-MM-DD': {'R': '1,2,3'}}}(10.4KB・34日分。10 分メモ)
// §98(2026-09-04): 配り元を yukochi.com の静的ファイルから **nar_meta 'kochi_paddock_index'** へ移した。
// 高知ビューア(keiba-deploy)はもう使わない=毎朝 `01_高知映像計測\paddock\paddock_index.py --apply` が
// 同じ {base, days} をそのまま upsert する。⛔中身の形は1バイトも変えていない。
// ⛔通信は +0(相手が別ドメインから同じ Supabase に変わっただけ)。まだ行が無い間は [] → null=出さない
function paddockIndex() {
  return memo('own:paddock', 10 * MIN, async () => {
    const rows = await sbNar('nar_meta?select=value&key=eq.kochi_paddock_index');
    const doc = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const base = doc && str(doc.base);
    const days = doc && doc.days && typeof doc.days === 'object' ? doc.days : {};
    return base ? { base: base.replace(/\/+$/, ''), days } : null;
  });
}
function paddockSet(idx, date, no) {
  const day = idx && idx.days[date];
  const list = day && day[String(no)];
  return new Set(String(list ?? '').split(',').map((s) => Number(s.trim())).filter((u) => Number.isInteger(u) && u > 0));
}
function paddockUrls(idx, date, no, umaban) {
  const stem = `${idx.base}/${date.replace(/-/g, '')}/R${no}/uma${pad2(umaban)}`;
  return { video: `${stem}.mp4`, poster: `${stem}.jpg` };
}
// 前半3F の出自 → Map('R-馬番' → '実測'|'推定')。
// §98b(2026-09-04): 配り元を yukochi.com の TSV(高知ビューア keiba-deploy の配信物)から
// **nar_meta 'kochi_3f_kinds:YYYY-MM-DD'** へ移した。keiba-deploy の push はもうしない=新しい日は
// 404 になっていた。毎朝 `01_高知映像計測\auto3f\kinds_index.py --apply` が**同じ判定**
// (出自が「実測…」→実測 /「推定…」→推定 / それ以外は入れない)で 1日1行 upsert する。
// ⛔通信は +0(相手が別ドメインから同じ Supabase に変わっただけ・1ページ1本のまま)。
// ⛔行が無ければ空 Map= 札を出さない(今までの 404 catch と同じ挙動)。
// 無い日付があるので、呼ぶ側がパドック索引にその日付があるときだけ取る(§10 #23)
function kochi3fKinds(date) {
  return memo(`own:3f:${date}`, Infinity, async () => {
    const rows = await sbNar(`nar_meta?select=value&key=eq.kochi_3f_kinds:${date}`);
    const doc = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const map = new Map();
    for (const [k, v] of Object.entries(doc && typeof doc === 'object' ? doc : {})) {
      const kind = str(v);
      if (kind) map.set(k, kind);
    }
    return map;
  });
}

function emptyOwnEntry() { return { first3fKind: null, paddock: null, danwa: null, cyokyo: null }; }
function emptyRaceOwn() { return { bias: null, entries: {} }; }
function emptyHorseOwn() { return { first3fHistory: [], paddockClips: [], noken: null, danwaHistory: [] }; }

// 高知: パドック映像(索引)と各馬の前半3F の出自(TSV)。内外の傾向は無い
async function kochiRaceOwn(race) {
  const idx = await paddockIndex().catch(() => null);
  const kinds = idx && idx.days[race.date] ? await kochi3fKinds(race.date).catch(() => new Map()) : new Map();
  const entries = {};
  const at = (u) => (entries[u] || (entries[u] = emptyOwnEntry()));
  for (const u of paddockSet(idx, race.date, race.no)) at(u).paddock = paddockUrls(idx, race.date, race.no, u);
  for (const [key, kind] of kinds) {
    const [no, u] = key.split('-').map(Number);
    if (no === race.no && kind) at(u).first3fKind = kind;
  }
  return { bias: null, entries };
}

// 厩舎の話 1行 → OwnEntry.danwa(全列 null の行は無い扱い。FLAGS が false なら文章は null・調教師名だけ)
function danwaOf(row) {
  const headline = str(row.headline), trainer = str(row.trainer), comment = str(row.comment);
  if (!headline && !trainer && !comment) return null;
  const text = FLAGS.keibabookText;
  return { headline: text ? headline : null, trainer, comment: text ? comment : null };
}
// 調教 works の1本 → CyokyoWork。坂路(course に「坂」)は t_5f/t_half/t_3f/t_1f を 4F/3F/2F/1F、本馬場は 5F/4F/3F/1F と読む(本番 keiba.html と同じ)
function cyokyoWork(w) {
  const course = str(w.course);
  const labels = course && course.includes('坂') ? ['4F', '3F', '2F', '1F'] : ['5F', '4F', '3F', '1F'];
  const t = w.times && typeof w.times === 'object' ? w.times : {};
  const times = [];
  [t.t_5f, t.t_half, t.t_3f, t.t_1f].forEach((v, i) => { const sec = num(v); if (sec !== null) times.push({ label: labels[i], sec }); });
  return { date: isDateStr(w.date) ? w.date : null, course, going: str(w.baba), final: w.mark === '☆', times, ashiiro: str(w.ashiiro) };
}
// 最終追い(mark '☆')→ 無ければ date 付きの最新 → 無ければ先頭の1本。短評は FLAGS に従う
function cyokyoOf(row) {
  const works = (Array.isArray(row.works) ? row.works : []).filter((w) => w && typeof w === 'object');
  const arrow = str(row.arrow);
  const tanpyo = FLAGS.keibabookText ? str(row.tanpyo) : null;
  if (!works.length && !arrow && !tanpyo) return null;
  const dated = works.filter((w) => isDateStr(w.date)).sort((a, b) => b.date.localeCompare(a.date));
  const last = works.find((w) => w.mark === '☆') || dated[0] || works[0] || null;
  return { count: works.length, arrow, tanpyo, last: last ? cyokyoWork(last) : null };
}
// 内外の傾向 = {prefix}_stats.corner4_inout[date](正=外伸び・負=内伸び)。JSON パスは引用符無し(2026-08-23 実測: 引用符付きは null)。
// 値ありは永続・null は 10 分
function chihouBias(v, date) {
  return memo(`own:bias:${v.prefix}:${date}`, (val) => (val ? Infinity : 10 * MIN), async () => {
    const rows = await sb(`chihou_meta?select=v:${enc(`value->corner4_inout->>${date}`)}&key=eq.${v.prefix}_stats`);
    const value = rows.length ? num(rows[0].v) : null;
    if (value === null) return null;
    const label = value >= 0.10 ? '外伸び' : (value <= -0.10 ? '内伸び' : '差は小さい');
    const text = label === '差は小さい'
      ? `この日の${v.name}は内と外の差が小さかった(通った位置と人気順の差がほとんど無い)`
      : `この日の${v.name}は${label}傾向(${label === '内伸び' ? '内' : '外'}を通った馬が人気以上に走った)`;
    return { value, label, text, basis: '4コーナーの位置(内〜大外)と人気順の差から・当日の全レース' };
  });
}
// 門別・南関: 厩舎の話(門別は 0 行)・調教・内外の傾向(done のときだけ・門別/大井/船橋)。
// 厩舎の話と調教は競馬ブック由来なので閲覧者には出さない= §58 管理者だけ Worker 経由で読む(閲覧者は通信もしない)
async function chihouRaceOwn(race, v) {
  const rid = enc(String(race.sourceId));
  const [own, bias] = await Promise.allSettled([
    FLAGS.dev ? adminGet(`/rpc/admin-chihou-own?race_id=${rid}`) : Promise.resolve(null),
    race.status === 'done' && BIAS_PREFIXES.includes(v.prefix) ? chihouBias(v, race.date) : Promise.resolve(null),
  ]);
  const entries = {};
  const at = (u) => { const n = num(u); return n === null ? null : (entries[n] || (entries[n] = emptyOwnEntry())); };
  if (own.status === 'fulfilled' && own.value && own.value.ok) {
    for (const row of (Array.isArray(own.value.danwa) ? own.value.danwa : [])) {
      const d = danwaOf(row); const e = d && at(row.umaban); if (e) e.danwa = d;
    }
    for (const row of (Array.isArray(own.value.cyokyo) ? own.value.cyokyo : [])) {
      const c = cyokyoOf(row); const e = c && at(row.umaban); if (e) e.cyokyo = c;
    }
  }
  return { bias: bias.status === 'fulfilled' ? bias.value : null, entries };
}

// レースの独自データ(throw しない。全滅でも {bias:null, entries:{}})。TTL は getRace と同じ(done なら永続・他は 60 秒)
export function getRaceOwn(race) {
  const r = race && typeof race === 'object' ? race : null;
  const v = r && VENUE_BY_PREFIX.get(String(r.venue ?? ''));
  if (!v || !isDateStr(r.date) || !Number.isInteger(r.no) || !str(r.sourceId)
    || (v.supported !== 'kochi' && v.supported !== 'chihou')) return Promise.resolve(emptyRaceOwn());
  const ttl = r.status === 'done' ? Infinity : MIN;
  return memo(`own:race:${v.prefix}/${r.date}/${r.no}`, ttl, () =>
    (v.supported === 'kochi' ? kochiRaceOwn(r) : chihouRaceOwn(r, v)).catch(() => emptyRaceOwn()));
}

// 前半3F の推移(first3f がある走・直近 10。出自は高知でパドック索引に日付がある開催日だけ TSV から)と
// パドック映像(索引に (日付, R, 馬番) がある高知の走・最大 6)。Supabase への追加クエリは無し
async function kochiHorseOwn(runs) {
  // 他場の chihou_results.first3f は 1200m 未満だと「距離−600m」の通過時刻(門別 1000m で 24.6 秒など・2026-08-23 実測)で 3F ではない。
  // 捨てずに区間(first3fF)を付けて全行返し、ページ側が 3F の走だけでバーを比べる(ユーザー決定 2026-08-23)
  const f3 = runs.filter((r) => r.first3f !== null && r.first3f !== undefined).slice(0, 10);
  const kochiRuns = runs.filter((r) => r.venue === 'kochi' && isDateStr(r.date) && r.raceNo !== null);
  const idx = kochiRuns.length ? await paddockIndex().catch(() => null) : null;
  const dates = [...new Set(f3.filter((r) => r.venue === 'kochi' && idx && idx.days[r.date]).map((r) => r.date))];
  const kinds = new Map(await Promise.all(dates.map(async (d) => [d, await kochi3fKinds(d).catch(() => new Map())])));
  const first3fHistory = f3.map((r) => ({
    date: r.date, raceId: r.raceId, distance: r.distance, first3f: r.first3f,
    first3fF: r.first3fF ?? (r.venue === 'kochi' ? 3 : first3fFOf(r.distance)),
    kind: r.venue === 'kochi' && kinds.has(r.date) ? (kinds.get(r.date).get(`${r.raceNo}-${r.umaban}`) ?? null) : null,
  }));
  const paddockClips = [];
  for (const r of kochiRuns) {
    if (paddockClips.length >= 6) break;
    if (r.umaban === null || !r.raceId || !paddockSet(idx, r.date, r.raceNo).has(r.umaban)) continue;
    paddockClips.push({ date: r.date, raceId: r.raceId, raceNo: r.raceNo, ...paddockUrls(idx, r.date, r.raceNo, r.umaban) });
  }
  return { first3fHistory, paddockClips };
}
// その地区の能検メタ(60〜213KB なので 30 分メモ)。返り値 = Map(鍵 → value)。
// §32 主催者公式の地区は nar-official の nar_meta から読む(§117b で13地区すべてがこちら)。
// §33.7-3 頭出し(offsets)は**同じテーブルの隣の行**なので `in.()` で**同じ1本に相乗り**させる
// = 頭出しのために通信を増やさない(§32d のハブと同じ手)。⚠ nar_meta 側でも同じ手にすること
//   (§117b で川崎・浦和・大井が nar_meta へ移った。`eq.` のままだと頭出しが取れなくなる)
function nokenMeta(prefix) {
  const p = String(prefix ?? '');
  return memo(`own:noken:${p}`, 30 * MIN, async () => {
    const keys = NOKEN_OFFSETS.includes(p) ? [`${p}_noken`, `${p}_noken_offsets`] : [`${p}_noken`];
    // §117c 兵庫も nar_meta の**隣の行**に頭出しがある= `in.()` で同じ 1 本に相乗りさせる。
    // ⚠旧DB(chihou_meta)の問い合わせ方は 1 字も変えない
    const rows = NOKEN_NAR.includes(p)
      ? await sbNar(`nar_meta?select=key,value&${keys.length > 1 ? `key=in.(${keys.join(',')})` : `key=eq.${keys[0]}`}`)
      : await sb(`chihou_meta?select=key,value&key=in.(${keys.join(',')})`);
    const out = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) out.set(str(r.key), r.value);
    return out;
  });
}

// {prefix}_noken の days(新しい順)
function nokenDays(prefix) {
  const p = String(prefix ?? '');
  return nokenMeta(p).then((m) => {
    const v = m.get(`${p}_noken`);
    return v && Array.isArray(v.days) ? v.days : [];
  });
}

// §33.7-3 レース別の頭出し。返り値 = Map(日付 → { videoId, races: [{ no, sec }] })。対象外の地区は null。
// ⚠ 使うのは `offsets`(**白板から見せる**)であって `race_start_sec`(板が終わる秒)ではない=§33.7-2 の既定。
// 動画は一切持たず YouTube の start= に渡すだけ。日と数が合わない回は投入側が落としているので、ここは素直に読む
export function getNokenOffsets(prefix) {
  const p = String(prefix ?? '');
  if (!NOKEN_OFFSETS.includes(p)) return Promise.resolve(null);
  return nokenMeta(p).then((m) => {
    const v = m.get(`${p}_noken_offsets`);
    const days = v && v.days && typeof v.days === 'object' && !Array.isArray(v.days) ? v.days : null;
    if (!days) return null;
    const out = new Map();
    for (const date of Object.keys(days)) {
      if (!isDateStr(date)) continue;
      const d = days[date];
      const id = str(d && d.video_id);
      const offs = d && d.offsets && typeof d.offsets === 'object' ? d.offsets : null;
      // YouTube の動画IDは 11 文字。形が違うものは使わない(§32d の nokenVideo と同じ用心)
      if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id) || !offs) continue;
      const races = [];
      for (const k of Object.keys(offs)) {
        const no = num(k);
        const sec = num(offs[k]);
        if (no === null || no < 1 || sec === null || sec < 0) continue;
        races.push({ no, sec });
      }
      if (races.length) out.set(date, { videoId: id, races: races.sort((a, b) => a.no - b.no) });
    }
    return out.size ? out : null;
  });
}
// 能力検査(デビュー前の試験)。rows[].horse_id === 競馬ブック 7 桁。最初に見つかった行=最新の受検
async function nokenOf(v, code) {
  const days = await nokenDays(v.prefix);
  for (const day of days) {
    for (const race of (day && Array.isArray(day.races) ? day.races : [])) {
      const row = (Array.isArray(race.rows) ? race.rows : []).find((x) => x && String(x.horse_id ?? '') === code);
      if (!row) continue;
      const time = timeStr(row.time);
      const sec = timeToSec(time);
      const last3f = num(row.last3f);
      const dist = num(race.dist);
      const mp4 = str(race.mp4), yt = str(day.video);
      return {
        venue: v.prefix, date: String(day.date ?? ''), raceNo: num(race.no), distance: dist,
        finish: num(row.fin), time, last3f,
        // 最初の 1F = タイム − 上り3F は 800m(4F)の能検だけに成り立つ。門別 1000m・大井 1200m・川崎 900m の能検もある(2026-08-23 実測)ので他は出さない
        ten1f: dist === 800 && sec !== null && last3f !== null ? Math.round((sec - last3f) * 10) / 10 : null,
        ok: str(row.ok), comment: FLAGS.keibabookText ? str(row.comment) : null,
        video: mp4 ? { kind: 'mp4', url: mp4 } : (yt ? { kind: 'youtube', url: yt } : null),
        pdf: str(race.pdf) ?? str(day.all_pdf),
      };
    }
  }
  return null;
}
// §20.1 能力検査の一覧(/noken/<prefix>)。nokenOf と同じ JSON を「日 → レース → 行」の形に整えるだけ。
// 投入側(Python)が None をそのまま文字列にしている値がある(南関の all_pdf='None'・タイムや着順の '-')ので落とす
function nokenText(v) {
  const s = str(v);
  return s === null || s === 'None' || s === 'null' || s === '-' ? null : s;
}
// §66 B2 映像・PDF の配信元(⛔許可リストは**ここ1か所**・§5.4)。実データに出てくる先だけ=
// 両DBの能検 blob 全走査で **6,651本・5ホスト・全部 https**(2026-08-30 実測)。
// ⚠**CSP の表とは別物**= `youtu.be` は `<iframe>`/`<video>` に入らない(`<a href>` で開くだけ)ので
//   CSP には要らないが、ここには要る。⚠`banei-keiba.or.jp` は PDF(成績表)の置き場
const MEDIA_HOSTS = new Set([
  'www.youtube.com',
  'youtu.be',
  'www.hokkaidokeiba.net',
  'pub-6567e3477a0d451093923a95ba6c2e3c.r2.dev',
  'banei-keiba.or.jp',
]);
// ⛔`http:` と知らないホストは落とす(前は `^https?://` を通すだけだった= どのホストでも通っていた)
function nokenUrl(v) {
  const s = nokenText(v);
  if (!s) return null;
  let u;
  try { u = new URL(s); } catch { return null; }
  return u.protocol === 'https:' && MEDIA_HOSTS.has(u.hostname) ? s : null;
}

// §117g 外部リンク用のプレイリスト。埋め込めるかは見ない(押すと YouTube を開くだけ)。
// ⚠笠松の2件のように list の ID が短い回もここは通す= 見出しの外部リンクとして残せる
function nokenPlaylist(v) {
  const s = nokenUrl(v);
  return s && /youtube\.com\/playlist\?/.test(s) && /[?&]list=[A-Za-z0-9_-]+/.test(s) ? s : null;
}
// §32d 映像 URL。YouTube は **ID の形まで見る**。
// ⛔笠松 2026-07-31 のプレイリストIDが公式側で 13 文字に切れている(正しくは 34 文字)。
// 動画ID 11 文字・プレイリストID 18 文字以上でなければ出さない。
// ⚠§117g 2026-09-07 実測= 13 文字でも**YouTube のページは開く**(その回の動画2本が読めた)。
//   埋め込みで動くかは確かめていないのでここは今までどおり落とし、外部リンク(nokenPlaylist)で残す
function nokenVideo(v) {
  const s = nokenUrl(v);
  if (!s) return null;
  if (!/youtube\.com|youtu\.be/.test(s)) return s;              // YouTube 以外(mp4 等)はそのまま
  const list = /[?&]list=([A-Za-z0-9_-]+)/.exec(s);
  if (list) return list[1].length >= 18 ? s : null;
  const id = /[?&]v=([A-Za-z0-9_-]+)/.exec(s) || /youtu\.be\/([A-Za-z0-9_-]+)/.exec(s);
  if (id) return id[1].length === 11 ? s : null;
  return null;                                                  // v も list も無い YouTube URL は出さない
}
// '02:44.1'(ばんえい)の頭の 0 を落として '2:44.1' に。'1.24.5' → '1:24.5' は timeStr が済ませている
function nokenTime(v) {
  const s = timeStr(nokenText(v));
  return s === null ? null : s.replace(/^0(\d:)/, '$1');
}

function nokenRow(row) {
  const r = row && typeof row === 'object' ? row : {};
  const code = nokenText(r.horse_id) ?? '';
  return {
    fin: num(nokenText(r.fin)),
    umaban: num(nokenText(r.umaban)),
    name: nokenText(r.name) || '',
    horseId: /^\d{7}$/.test(code) ? `kb:${code}` : null,
    time: nokenTime(r.time),
    last3f: num(nokenText(r.last3f)),
    // §117e 通過順(公式に無い。旧DB からの補完(§117b-2)と提供データのレース割りで入る地区だけ持つ)
    passOrder: nokenText(r.pass_order),
    weight: num(nokenText(r.weight)),
    sexage: nokenSexAge(r.sexage),
    jockey: nokenText(r.jockey),
    trainer: nokenText(r.trainer),
    ok: nokenText(r.ok),
    // §117h 行ごとの検査種別(南関の「試験内容」・兵庫は §117e で組の種別を行に移してある)。
    // ⚠ここに無かったので画面のどこにも出ていなかった(§119c の通過順と同じ落ち方)。⛔列は作らない=
    // 馬名の下の注記行に出す。⚠race.kind(レースの区分)とは別物
    kind: nokenText(r.kind),
    // §32 主催者公式のぶん(無い地区は null のまま=画面はその列を出さない)
    // 高知の kin は 923/925 行が 0(発表が無い)。0 は「無し」として扱う=画面はその列ごと出さない
    kin: num(nokenText(r.kin)) || null,          // 佐賀=斤量 / ばんえい=そり重量
    sire: nokenText(r.sire),                     // 佐賀・高知は父
    dam: nokenText(r.dam),                       // 佐賀・高知は母
    damSire: nokenText(r.bms),                   // §117h 南関の母父馬(cloud NANKAN_KEEP に bms)。馬名の下の血統行に
    cls: nokenText(r.cls),                       // 佐賀・笠松・名古屋・高知はクラス
    note: nokenText(r.note),                     // 佐賀の備考・笠松の受検理由・名古屋の不合格理由
    status: nokenText(r.status),                 // ばんえい・名古屋の 中止・取消 など
    // §32d 新しい列(無い地区は null=画面はその列を出さない)
    stable: nokenText(r.stable),                 // 笠松の厩舎記号
    prevWeight: num(nokenText(r.prev_weight)),   // 高知の前走馬体重
    // §32f 金沢だけが発表している2列(旧様式の 2019〜21 には無いので、その日は列ごと出ない)
    origin: nokenText(r.origin),                 // 産地(浦河町・新ひだか町 など)
    owner: nokenText(r.owner),                   // 馬主
    base: nokenBase(r.base),                     // 高知の合格基準タイム(行ごと)
    isNew: nokenText(r.new) !== null,            // 佐賀の新馬印(元は馬名頭の ※)
    // 寸評は競馬ブック由来=閲覧者に出さない(dev のときだけ入る。§20.1 / §10 #22)
    comment: FLAGS.keibabookText ? nokenText(r.comment) : null,
  };
}
function nokenRace(race) {
  const r = race && typeof race === 'object' ? race : {};
  return {
    no: num(nokenText(r.no)),
    dist: num(nokenText(r.dist)),
    going: nokenText(r.going),
    weather: nokenText(r.weather),
    mp4: nokenUrl(r.mp4),
    pdf: nokenUrl(r.pdf),
    // §32 主催者公式のぶん
    video: nokenVideo(r.video),                  // §33.2 岩手だけレース単位の YouTube がある
    venue: nokenText(r.venue),                   // 岩手は1日に水沢と盛岡が同居する
    kind: nokenText(r.kind),                     // 兵庫=ゲート検査/能力検査ほか・佐賀=2歳/3歳
    moisture: nokenText(r.moisture),             // ばんえい=馬場水分率(%)
    base: nokenBase(r.base),                     // ばんえい・高知=合格基準タイム
    start: nokenText(r.start),                   // §32d 笠松・名古屋・高知=発走時刻
    rows: (Array.isArray(r.rows) ? r.rows : []).map(nokenRow)
      .sort((a, b) => (a.fin ?? 99) - (b.fin ?? 99) || (a.umaban ?? 99) - (b.umaban ?? 99)),
  };
}
function nokenDayOf(day) {
  const d = day && typeof day === 'object' ? day : {};
  // §32d 壊れた YouTube ID は出さない(笠松に2件)
  const vids = (Array.isArray(d.videos) ? d.videos : []).map(nokenVideo).filter(Boolean);
  const one = nokenVideo(d.video);
  return {
    date: isDateStr(d.date) ? String(d.date) : null,
    allPdf: nokenUrl(d.all_pdf),
    videoUrl: one,
    // §32 主催者公式のぶん
    videoUrls: vids.length ? [...new Set(vids)] : (one ? [one] : []),
    // §32f 兵庫は day.video が**その日の通し動画**になった(26日とも別URL)。
    // 元のプレイリスト(検査回ぜんぶ)は day.playlist に残っているので、脇に小さく併記する
    // §117g 笠松の day.video は「検査回のプレイリスト」。埋め込めない回は videoUrl から落ちるので、
    // そのままだと映像がどこにも出ない。⛔落とさない= 外部リンク用にここへ回す
    playlist: nokenVideo(d.playlist) || (one ? null : nokenPlaylist(d.video)),
    venue: nokenText(d.venue),                   // その日の主な場(岩手は日の中で分かれる)
    going: nokenText(d.going),                   // 兵庫・佐賀・笠松・名古屋は日レベル
    weather: nokenText(d.weather),
    // §32d 笠松・名古屋は「クラスごとの合格基準」を日単位で出す(距離もクラスで違う日がある)
    baseTimes: nokenMap(d.base_times),
    baseDists: nokenMap(d.base_dists),
    // ⚠ 記事の見出しに日付が無い/誤記の回は WordPress の掲載日を使っている(投入側が date_src:'post' を付ける)
    datePosted: nokenText(d.date_src) === 'post',
    races: fillDist((Array.isArray(d.races) ? d.races : []).map(nokenRace).sort((a, b) => (a.no ?? 99) - (b.no ?? 99)),
      nokenMap(d.base_dists)),
  };
}

// {クラス: 値} の素の連想配列 → [[クラス, 値], …](空なら [])
function nokenMap(v) {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return [];
  return Object.keys(v).map((k) => [String(k), v[k]]).filter(([, x]) => x !== null && x !== undefined && x !== '');
}

// §32d ⚠名古屋は race.dist が無い。その日の base_dists の値が1種類なら、それがその日の距離(実測: 全59日とも 900m)。
// 笠松のように 800 と 1400 が混ざる日は決められないので触らない(レース側に dist がある場なので困らない)
function fillDist(races, baseDists) {
  const vals = [...new Set(baseDists.map(([, v]) => num(v)).filter((v) => v !== null))];
  if (vals.length !== 1) return races;
  for (const r of races) { if (r.dist === null) r.dist = vals[0]; }
  return races;
}

// §32d 高知の PDF は「セン(騙馬)」に外字を使っていて、そのまま出すと □ になる(925行中66行)。
// 意味の無い私用領域の文字は落として齢だけ出す(齢は末尾の数字なので §33.1 の「2歳のみ」には影響しない)
function nokenSexAge(v) {
  const s = sexAgeStr(nokenText(v));
  return s === null ? null : (s.replace(/[-]/g, '') || null);
}

// '1.34.0' / '57.0' → 表示用。'00.0' のような中身の無い値(高知に35件)は落とす
function nokenBase(v) {
  const s = nokenTime(v);
  return s && /[1-9]/.test(s) ? s : null;
}

// 能力検査の全日程(新しい順)。対象外の場は [](ページは「データはありません」を出す)
export function getNoken(prefix) {
  const p = String(prefix ?? '');
  if (!NOKEN_PREFIXES.includes(p)) return Promise.resolve([]);
  return nokenDays(p).then((days) => (Array.isArray(days) ? days : [])
    .map(nokenDayOf)
    .filter((d) => d.date)
    .sort((a, b) => b.date.localeCompare(a.date)));
}

// §33.6 能検を受けた馬が **その後 実戦に出たか**。公式の出走記録を**日を開いたとき1本**だけ引く。
// 返り値 = Map(馬名 → { first, next })。first = いちばん古い出走 / next = 検査日以降の最初の出走。
// 2歳馬は next がそのまま新馬戦。古馬(復帰・転入の再検査)は first が検査より前になるので、画面はそこで言い方を変える。
// ⚠**公式の出走記録は 2022-11-01 から**。それより前の検査日は「出ていない」と「記録が無い」を区別できないので
// 引かずに null を返す(画面は行を出さない)。⚠同名の別馬は区別できない(§26.5 と同じ限界)
// ⚠**nar_runs の1行=かならずしも「走った」ではない**(2026-08-26 全件実測)。
//  ①`finish` も `finish_note` も無い行 = **まだ行われていないレースの出馬表**(例 2026-08-27 門別11R の11頭)
//  ②`出走取消` 4,213行・`競走除外` 1,970行 = 出走を取り消した/除外された=**1歩も走っていない**
//  ③`競走中止` 1,868行・`失格` 89行 = 発走はした=**走ったことになる**(着順は付かない)
// ①②を出走として数えていたため、デビュー前に取消のあった馬が「デビュー待ち」から漏れていた
// (実例: 金沢 2026-08-22 のヤマカツパピヨンは 6/28 の新馬戦を出走取消・8/22 に受検=まだ未デビュー)
// ⚠**PostgREST は 1000 行で黙って切る**。ふだんは届かない(実測: 岩手27頭で397行・金沢24頭で365行)が、
// **ばんえいは1日に 211 頭が受検する**ので届いてしまう(2022-11 以降の36日のうち**13日**が 1000 行ちょうど= 打ち切り)。
// 日付昇順で切られる=**新しい出走から消える**ので、走っている馬が「デビュー待ち」に見えていた。
// offset は深いと 500 を返す(§10 #63 と同じ)ので、**race_date のキーセット**で続きを取る。
// 同じ日をまたぐぶんは重複するので鍵で潰す。ふだんは1本のまま=通信は増えない
const RUNS_PAGE = 1000;
async function nokenRunRows(list) {
  const base = 'nar_runs?select=horse_name,race_date,track,race_no,finish,finish_note' +
    `&horse_name=in.(${enc(quoteIn(list))})&order=race_date.asc,race_no.asc&limit=${RUNS_PAGE}`;
  const out = [];
  const seen = new Set();
  let from = null;
  for (let page = 0; page < 6; page += 1) {
    const rows = await sbNar(base + (from ? `&race_date=gte.${from}` : ''));
    const got = Array.isArray(rows) ? rows : [];
    for (const r of got) {
      const k = `${str(r.horse_name)}|${str(r.race_date)}|${str(r.track)}|${num(r.race_no)}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(r);
    }
    if (got.length < RUNS_PAGE) return out;
    const last = str(got[got.length - 1].race_date);
    // 1日だけで 1000 行を超える組み合わせは無い(1頭は1日1走)が、進めないなら打ち切る=無限に回さない
    if (!isDateStr(last) || last === from) return out;
    from = last;
  }
  return out;
}

// §51.2 「走った」= **着順が付いた** か、**発走はした**(競走中止・失格)。⛔出走取消・競走除外は走っていない。
// ⛔定義はこの2つ(didRun と RAN_FILTER)だけに置く(§5.4)。実測(2026-08-29): finish_note は
// 出走取消510 / 競走除外254 / 競走中止224 / 失格12 の4通りで、**note のある行に finish は1つも入らない**
const RAN_NOTES = ['競走中止', '失格'];
function didRun(r) {
  if (r.finish !== null && r.finish !== undefined && r.finish !== '') return true;
  return RAN_NOTES.includes(str(r.finish_note));
}
// 同じ判定を PostgREST 側でやる形(行を取ってから捨てるのではなく、初めから走った行だけ引く)
const RAN_FILTER = `or=(finish.not.is.null,finish_note.in.(${enc(quoteIn(RAN_NOTES))}))`;

export function getNokenRuns(names, since, opts) {
  const list = [...new Set((Array.isArray(names) ? names : []).map((n) => String(n ?? '').trim()).filter(Boolean))].sort();
  if (!list.length || !isDateStr(since) || since < NAR_FROM) return Promise.resolve(null);
  // §33.9-3 レース名(=クラスの手掛かり)まで要るかどうか。主催者がクラスを発表している地区では要らない
  const wantName = !!(opts && opts.withRaceName);
  return memo(`nokenruns:${wantName ? 'n' : 'x'}:${since}:${list.join(',')}`, 30 * MIN, async () => {
    const out = new Map();
    // 日付昇順なので、名前ごとに最初に見た行が初出走・最初に見た「検査日以降」の行がその後の初戦になる。
    // prev は上書きし続けるので、最後に残るのが**検査日の直前の1走**になる
    const rows = await nokenRunRows(list);
    for (const r of rows) {
      const name = str(r.horse_name);
      const date = str(r.race_date);
      if (!name || !isDateStr(date) || !didRun(r)) continue;
      const run = {
        date, venue: narPrefixOf(r.track), no: num(r.race_no),
        finish: num(r.finish), note: str(r.finish_note), track: str(r.track), name: null,
      };
      const cur = out.get(name) || { first: null, prev: null, next: null };
      if (!cur.first) cur.first = run;
      if (date < since) cur.prev = run;
      if (!cur.next && date >= since) cur.next = run;
      out.set(name, cur);
    }
    if (wantName) await fillRunNames(out);
    return out;
  });
}

// §33.9-3 ⚠**`nar_runs` には `race_name` が無い**(実測: 列が無く、`nar_races` への外部キーも無いので
// PostgREST の埋め込みもできない)。画面に出す走(検査前・検査後)のぶんだけ `nar_races` を
// **`or=(and(…))` で1本**引いて名前を貼る。60 レースずつに割るが、実測ではどの地区も1本で収まる
async function fillRunNames(map) {
  const runs = [];
  for (const rec of map.values()) {
    for (const r of [rec.prev, rec.next]) if (r && r.track && r.no !== null) runs.push(r);
  }
  if (!runs.length) return;
  const keys = new Map();
  for (const r of runs) keys.set(`${r.date}|${r.track}|${r.no}`, r);
  const parts = [...keys.values()];
  const found = new Map();
  await Promise.all(chunk(parts, 60).map(async (part) => {
    const cond = part.map((k) => `and(race_date.eq.${k.date},track.eq.${enc(k.track)},race_no.eq.${k.no})`).join(',');
    try {
      const rows = await sbNar(`nar_races?select=race_date,track,race_no,race_name&or=(${cond})&limit=1000`);
      for (const x of (Array.isArray(rows) ? rows : [])) {
        found.set(`${str(x.race_date)}|${str(x.track)}|${num(x.race_no)}`, str(x.race_name));
      }
    } catch { /* 名前が取れなくても行は出す(日付・場・着順だけになる) */ }
  }));
  for (const r of runs) {
    const v = found.get(`${r.date}|${r.track}|${r.no}`);
    if (v) r.name = v;
  }
}

// ---------------------------------------------------------------- §37 新馬戦

// 新馬戦かどうかの判定は**ここ1か所**(§26.4 と同じ作法。grep で1か所に集まる)。
// ⚠「デビュー」は使わない=笠松「デビュー馬**未勝利**戦」が混ざる(実測 394件中に未勝利・岩手デビュー限定など)。
// ⚠**園田・姫路だけ言い回しが違う**(実測 2022〜2026): 「ＮｅｗＢｅｇｉｎｎｉｎｇ　２歳初出走」64件・
//   「２歳初出走」30件・「３歳初出走」1件(姫路)。「初出走」を含むのはこの2場だけなので、これを第2の合図にする
const SHINBA_WORDS = ['新馬', '初出走'];
export function isShinba(raceName) {
  const s = str(raceName) || '';
  return SHINBA_WORDS.some((w) => s.includes(w));
}

// §37.4-3 新馬戦は**年度(4/1 始まり)**で括る=デビューの世代がそのまま1タブになる。
// 実測のレース数: 2023年度 298・2024年度 292・2025年度 287・2026年度 200(いずれも 1000 行上限に余裕)
export const SHINBA_FROM_FYEAR = 2023;

// 'YYYY-MM-DD' → 年度(4/1 始まり)
export function fyearOf(date) {
  const s = String(date ?? '');
  const y = Number(s.slice(0, 4));
  const m = Number(s.slice(5, 7));
  return Number.isFinite(y) && Number.isFinite(m) ? (m >= 4 ? y : y - 1) : null;
}

// §37.2/§37.4-3 その年度の新馬戦(レース+出走馬)。30分メモ。
// ⚠設計は「race_name のふるいはクライアント側」だったが、1年ぶんの全レースは数万行で 1000 行上限に当たる。
// **ふるいはサーバー側**(or=(like,like))にして 200〜300 行に絞る。
// ⚠**いちばん新しい年度だけ上限を切らない**=公式が出している先の出馬表(=これからの新馬戦)を落とさないため
export function getShinbaYear(fyear) {
  const y = Number(fyear);
  if (!Number.isInteger(y)) return Promise.resolve({ fyear: null, races: [] });
  const newest = fyearOf(todayJST());
  return memo(`shinba:${y}`, 30 * MIN, async () => {
    const like = SHINBA_WORDS.map((w) => `race_name.like.*${enc(w)}*`).join(',');
    const span = `race_date=gte.${y}-04-01` + (y >= newest ? '' : `&race_date=lt.${y + 1}-04-01`);
    const rows = await sbNar(`nar_races?select=${NAR_RACE_COLS}&${span}&or=(${like})` +
      '&order=race_date.asc,track.asc,race_no.asc&limit=1000');
    const races = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const date = str(r.race_date);
      const track = str(r.track);
      const no = num(r.race_no);
      const prefix = track ? narPrefixOf(track) : null;
      if (!isDateStr(date) || !prefix || no === null || !isShinba(r.race_name)) continue;
      races.push({
        date, venue: prefix, track, no,
        name: str(r.race_name) || '新馬戦',
        postTime: narPostTime(r.post_time),
        fieldSize: num(r.field_size),
        dist: num(r.distance_m),
        surface: str(r.surface),
        going: str(r.going),
        cond: str(r.condition),
        horses: [],
      });
    }
    await fillShinbaHorses(races);
    return { fyear: y, races };
  });
}

// 出走馬は**全頭**取る。⚠上位3着に絞ると4着以下が消える(実測: ディセントラリーフ=大井 8/12 の4着)。
// 1レース平均 7.6 頭なので、**鍵100個ずつ**なら 1 本あたり 800 行前後で 1000 行上限に当たらない
// (実測: 100鍵 793行・120鍵 946行)。2026年度200レース=2本・2023年度298レース=3本
const SHINBA_KEYS = 100;
async function fillShinbaHorses(races) {
  if (!races.length) return;
  const byKey = new Map(races.map((r) => [`${r.date}|${r.track}|${r.no}`, r]));
  await Promise.all(chunk(races, SHINBA_KEYS).map(async (part) => {
    const cond = part.map((r) => `and(race_date.eq.${r.date},track.eq.${enc(r.track)},race_no.eq.${r.no})`).join(',');
    let rows = [];
    try {
      rows = await sbNar('nar_runs?select=race_date,track,race_no,horse_name,runner_number,gate,finish,finish_note,time_sec' +
        `&or=(${cond})&order=runner_number.asc&limit=1000`);
    } catch { return; }                                    // 馬が取れなくてもレース一覧は出す
    for (const x of (Array.isArray(rows) ? rows : [])) {
      const r = byKey.get(`${str(x.race_date)}|${str(x.track)}|${num(x.race_no)}`);
      if (!r) continue;
      r.horses.push({
        name: str(x.horse_name) || '',
        umaban: num(x.runner_number),
        gate: num(x.gate),
        finish: num(x.finish),
        note: str(x.finish_note),
        time: narTimeStr(x.time_sec),
      });
    }
  }));
  for (const r of races) r.horses.sort((a, b) => (a.umaban ?? 99) - (b.umaban ?? 99));
}

// §50 V-3 デビュー待ちの全体ビュー。
// 返り値 = **{ran:Set(1度でも出走した馬名), complete:boolean}**。⛔ran に無い馬=デビュー待ち。
// ⛔**取り切れなかったときは complete=false**(取れなかった馬を「走っていない」と言わないため。画面が断りを出す)。
// ⚠**公式の出走記録は 2022-11-01 から**なので、それより前の検査日は判定に使えない(画面側で外す)。
// §50 #187(2026-08-28)= まず**能検索引の ran(ビルド時に nar_runs を引いたデビュー済みの旗)で枝刈り**する。
// ⛔ran は「一度付いたら戻らない」向きだけの旗なので、索引が古くても「走ったのにデビュー待ち」の誤りは出ない。
// 旗の無い馬(まだ走っていない・索引のビルド後にデビュー・3年窓の外)だけを従来どおり生で照会する
// (実測 2026-08-28: ばんえい 33本 → 索引1本+3本。索引は /shinba 等と10分メモを共有=そちらで読み済みなら +0)。
// ⚠**URL の長さ**が上限(実測 2026-08-28: 300頭=21KB は通る / 400頭=28KB は 400 Bad Request)なので
// 馬名は **200件ずつ**に割る。1000行の上限に当たったら**馬名のキーセット**で続きを取る(§10 #63 と同じ作法)。
export const RUNS_FROM = NAR_FROM;
const RUN_NAME_CHUNK = 200;
const RUN_PAGE_MAX = 12;

export function getNokenRan(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map((n) => String(n ?? '').trim()).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve({ ran: new Set(), complete: true });
  return getNokenIndex().catch(() => new Map()).then((idx) => {
    const known = new Set();
    const rest = [];
    for (const n of list) {
      const recs = idx.get(n);
      if (recs && recs.some((r) => r.ran)) known.add(n);
      else rest.push(n);
    }
    if (!rest.length) return { ran: known, complete: true };
    const key = `nokenran:${rest.length}:${rest[0]}:${rest[rest.length - 1]}`;
    // ⚠**取り切れなかった結果は覚えない**(memo の ttl は値を見て決められる)= 次に押したらやり直す
    return memo(key, (v) => (v && v.complete ? 30 * MIN : 0), () => ranNames(rest))
      .then((got) => ({ ran: new Set([...known, ...got.ran]), complete: got.complete }));
  });
}

async function ranNames(list) {
  const ran = new Set();
  let complete = true;
  for (let i = 0; i < list.length; i += RUN_NAME_CHUNK) {
    const chunk = list.slice(i, i + RUN_NAME_CHUNK);
    // §51.2 ⛔「走った」= **走った行だけ**(#198)。出馬表しか無い行(finish も finish_note も無い)は
    // **今日明日に出走予定なだけ**なので V-3 の「デビュー待ち」から消さない。
    // ⚠**取消・除外だけの馬も待ちのまま**にしたいので、絞りは `finish_note.not.is.null` ではなく
    // **didRun と同じ RAN_FILTER**。⚠ただしこの経路は**索引の ran 旗で決まらない馬だけ**が通る
    // (#187/#188 で索引に ran が入った)。索引側は取消・除外も ran=1 にしているので、
    // 「取消だけの馬」を待ちに戻すには**索引の作り方**を同じ定義に直す必要がある(実測 2026-08-29・9頭)
    const inList = `horse_name=in.(${enc(quoteIn(chunk))})&${RAN_FILTER}`;
    let from = null;
    let done = false;
    for (let page = 0; page < RUN_PAGE_MAX; page += 1) {
      const q = `nar_runs?select=horse_name&${inList}&order=horse_name.asc&limit=${RUNS_PAGE}` +
        (from ? `&horse_name=gt.${enc(from)}` : '');
      let rows;
      try { rows = await sbNar(q); } catch { return { ran, complete: false }; }
      const got = Array.isArray(rows) ? rows : [];
      for (const r of got) { const n = str(r.horse_name); if (n) ran.add(n); }
      if (got.length < RUNS_PAGE) { done = true; break; }
      const last = str(got[got.length - 1].horse_name);
      if (!last || last === from) break;                        // 進めないなら打ち切る(無限に回さない)
      from = last;
    }
    if (!done) complete = false;                                // このチャンクは最後まで見ていない
  }
  return { ran, complete };
}

// §37.4-1 能検索引= 直近3年に能検へ出た馬の1枚もの(nar_meta 'noken_index')。**これ1本で全馬にバッジが付く**
// (v1 は地区ごとに 11 本 383KB 読んでいた)。返り値 = Map(馬名 → [記録…]・**新しい順**)。10分メモ。
// 記録の形(§37.4-① の注意): d=地区 / date / time / ok=合・否・null / v=映像URL / s=頭出し秒(川崎浦和だけ) /
// p=場名(岩手・兵庫だけ。地区に複数の競馬場があるので要る)
export function getNokenIndex() {
  return memo('nokenindex', 10 * MIN, async () => {
    const rows = await sbNar('nar_meta?select=value&key=eq.noken_index');
    const v = rows.length ? rows[0].value : null;
    const horses = v && v.horses && typeof v.horses === 'object' ? v.horses : null;
    if (!horses) return new Map();
    const out = new Map();
    for (const name of Object.keys(horses)) {
      const recs = nokenRecs(horses[name]);
      if (recs.length) out.set(name, recs);
    }
    return out;
  });
}

// 索引の1頭ぶん(生の配列)→ 画面が使う形。索引ぜんぶでも1頭だけでも同じ読み方をする
function nokenRecs(list) {
  const recs = [];
  for (const r of (Array.isArray(list) ? list : [])) {
    const date = str(r && r.date);
    if (!isDateStr(date)) continue;
    recs.push({
      date,
      district: str(r.d),
      place: str(r.p),                        // 岩手=盛岡/水沢・兵庫=園田/西脇。無い地区は null
      time: str(r.time),
      ok: str(r.ok),
      video: str(r.v),
      start: num(r.s),                        // 頭出し秒(川崎・浦和の443件だけ)
      // §37.7-1 で足された値。⚠**無いキーは無いまま**(推定しない)。実測の埋まり具合(7,561件中):
      // r/n=7,561(13地区ぜんぶ)・tr=6,155(タイム欠測の馬には無い)・a/ar=1,804・t1=1,527
      // (a/ar/t1 は競馬ブックのある5場=門別・南関4場だけ。t1 は 800m の検査だけ)
      raceNo: num(r.r),                       // その検査回の第何レースか
      heads: num(r.n),                        // そのレースの発表行数(順位の分母)
      timeRank: num(r.tr),                    // レース内のタイム順位(同着は同順位)
      // §50 K-1c(2026-08-28 投入)。池= **同じ日×距離×齢帯**・タイムのある馬だけ・同タイム同順位。
      // ⚠実測の埋まり具合(7,564件中): dm 5,048 / ag 4,845 / dr・dn 4,576(距離を発表しない地区には付かない)
      dist: num(r.dm),                        // 検査の距離(m)
      ageBand: num(r.ag),                     // 2=2歳 / 3=3歳以上(齢を発表しない地区は無い)
      dayRank: num(r.dr),                     // 日全体(同じ距離・同じ齢帯)のタイム順位
      dayN: num(r.dn),                        // その順位の分母(タイムのある馬だけ)
      last3f: num(r.a),                       // 上がり3F
      last3fRank: num(r.ar),                  // 上がり3F の順位
      ten1f: num(r.t1),                       // テン1F
      // §50 #187 ビルド時に nar_runs を引いた「デビュー済み」の旗。⛔**true だけが情報**
      // (false は「このビルドの後にデビューした」「照会が取り切れなかった」の両方がありうる=枝刈りにだけ使う)
      ran: r.ran === 1,
    });
  }
  // 索引は新しい順で来るが、こちらでも保証する(先頭=最新の検査を既定で出す)
  recs.sort((a, b) => b.date.localeCompare(a.date));
  return recs;
}

// §40-5 **1頭ぶんだけ**の能検。馬ページは索引ぜんぶ(実測 1,002,928 バイト)を要らないので、
// PostgREST の JSON セレクタでサーバー側に切り出させる(実測 157 バイト・1本)。
// ⚠/shinba や新馬戦の馬柱で索引ぜんぶが**もう手元にある**ときは、それを読むだけ(通信ゼロ)。
// ⚠馬名に `(` `※` `―` などが混じる馬(実測 5,608頭中 6頭)はセレクタに載せられないので索引ごと引く
const NOKEN_NAME_OK = /^[\u3041-\u3096\u30A1-\u30FA\u30FC\u4E00-\u9FFF0-9A-Za-z]+$/;

export function getNokenFor(name) {
  const n = String(name ?? '').trim();
  if (!n) return Promise.resolve([]);
  if (memoReady('nokenindex') || !NOKEN_NAME_OK.test(n)) {
    return getNokenIndex().then((m) => m.get(n) || []).catch(() => []);
  }
  return memo(`nokenfor:${n}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_meta?select=v:value->horses->${enc('"' + n + '"')}&key=eq.noken_index`);
    } catch { return []; }
    return nokenRecs(Array.isArray(rows) && rows.length ? rows[0].v : null);
  });
}

// 2026-09-04 出走馬ぶんだけ(1本・数百バイト)。馬柱で「前走のあとの能検」を前走の位置に置くため、**全レース**で引く。
//   索引 1 枚もの(getNokenIndex)が memo にあればそれを使う。⛔名前に索引の鍵に使えない字(NOKEN_NAME_OK)があれば飛ばす
export function getNokenForNames(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map((n) => String(n ?? '').trim()).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve(new Map());
  if (memoReady('nokenindex')) {
    return getNokenIndex().then((m) => new Map(list.filter((n) => m.has(n)).map((n) => [n, m.get(n)]))).catch(() => new Map());
  }
  const ok = list.filter((n) => NOKEN_NAME_OK.test(n));
  if (!ok.length) return Promise.resolve(new Map());
  return memo(`nokenfor:${ok.join(',')}`, 10 * MIN, async () => {
    let rows;
    try {
      const sel = ok.map((n, i) => `h${i}:value->horses->${enc('"' + n + '"')}`).join(',');
      rows = await sbNar(`nar_meta?select=${sel}&key=eq.noken_index`);
    } catch { return new Map(); }
    const row = Array.isArray(rows) && rows.length ? rows[0] : null;
    const out = new Map();
    ok.forEach((n, i) => { const recs = nokenRecs(row ? row[`h${i}`] : null); if (recs.length) out.set(n, recs); });
    return out;
  });
}

// #125 検査を受けた場。岩手(盛岡/水沢)・兵庫(園田/西脇)は地区に競馬場が2つあるので索引の `p` を使う。
// ⚠`p` は岩手・兵庫にしか無い(実測 1,462件・#123)ので、無い地区は**地区名を場名として出す**
// (黙って落とさない=別の場で受けた馬が分かるように)。/shinba・馬柱・馬ページの3画面で同じ1か所を使う
export function nokenPlaceName(rec) {
  const p = str(rec && rec.place);
  if (p) return p;
  const d = str(rec && rec.district);
  const v = VENUE_BY_PREFIX.get(d);
  if (v) return v.name;
  const nd = nokenDistrict(d);
  return nd ? nd.name : d;
}

// §48 K-1b 馬場差。cloud/baba.py が夜間に書く `nar_meta 'baba_diff'` = {days:{日:{場:{d,n}}}, built}。
// ⚠**当サイトの推定**(同じ場・距離・クラス帯の過去3年の中央値との差)であって公式発表ではない。
// ⚠帯広ば(ばんえい)は対象外・その日の対象レースが少ない場も入っていない(=出さない)。
// 全期間は 11KB あるので、**1日だけ要るページ(レース・その日の結果)は JSON セレクタで切り出す**(実測 107バイト)。
// 索引ぜんぶが手元にあるときは通信ゼロで済ませる(getNokenFor と同じ作法)
function babaDayOf(v) {
  const out = new Map();
  if (!v || typeof v !== 'object') return out;
  for (const p of Object.keys(v)) {
    const o = v[p];
    const d = num(o && o.d);
    if (d === null) continue;
    out.set(p, { diff: d, n: num(o && o.n) });
  }
  return out;
}

export function getBabaDiff() {
  return memo('babadiff', 30 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_meta?select=value&key=eq.baba_diff'); } catch { return null; }
    const v = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const days = v && v.days && typeof v.days === 'object' ? v.days : null;
    if (!days) return null;
    const out = new Map();
    for (const date of Object.keys(days)) {
      if (!isDateStr(date)) continue;
      const m = babaDayOf(days[date]);
      if (m.size) out.set(date, m);
    }
    return { days: out, built: isDateStr(v.built) ? String(v.built) : null };
  });
}

export function getBabaDay(date) {
  if (!isDateStr(date)) return Promise.resolve(new Map());
  if (memoReady('babadiff')) {
    return getBabaDiff().then((b) => (b && b.days.get(date)) || new Map()).catch(() => new Map());
  }
  return memo(`babaday:${date}`, 30 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_meta?select=v:value->days->${enc('"' + date + '"')}&key=eq.baba_diff`);
    } catch { return new Map(); }
    return babaDayOf(Array.isArray(rows) && rows.length ? rows[0].v : null);
  });
}

// §100 馬場傾向。cloud/baba_trend.py が朝の便で 90 日ぶん、日中の便で当日ぶんを書く
// `nar_meta 'baba_trend'` = {built, q_built, days:{日:{場:{t,tn,f,fn,io,ion,partial,w}}}}。
// ⚠**当サイトの推定**。t= 馬場差(cloud/baba.py の値をそのまま)・f= 序盤コーナーの順位と着順の相関・
//   io= 枠番と着順の相関(**ρ>0= 内枠ほど着順が良い= 内が有利**)。w は平年の四分位の外に出た指標だけ。
// ⛔通信 +1(場ページ・その日の結果・レースページ。10 分メモを 3 画面で共用する)。
// ⛔行が無ければ null(何も出さない)
export function babaTrend() {
  return memo('baba_trend', 10 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_meta?select=value&key=eq.baba_trend'); } catch { return null; }
    const v = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const days = v && v.days && typeof v.days === 'object' ? v.days : null;
    return days ? { built: str(v.built), qBuilt: str(v.q_built), days } : null;
  });
}

// その場の日を**新しい順**に [{date, cell}] で返す(通信ゼロ・上の blob から切り出すだけ)。
// ⛔「その場のどの日があるか」の決め方をページごとに書かない(§5.4)
export function babaTrendList(doc, prefix) {
  const days = doc && doc.days;
  if (!days || !prefix) return [];
  const out = [];
  for (const date of Object.keys(days)) {
    const cell = days[date] && days[date][prefix];
    if (isDateStr(date) && cell && typeof cell === 'object') out.push({ date, cell });
  }
  return out.sort((a, b) => b.date.localeCompare(a.date));
}

// §99 展開の見立て(位置だけ)。cloud/tenkai.py が朝の便と 17:07 の便で書く
// `nar_meta 'tenkai:YYYY-MM-DD'` = {built, races:{'<prefix>-<R>':{n,k,lead,front,mid,back,none,h,w}}}。
// ⚠**当サイトの推定**(各馬の直近5走の1番目のコーナー通過順から型を決めたもの)であって公式発表ではない。
// ⚠帯広ば(通過順が無い)と、型が1頭も付かなかったレースは入っていない= 画面はカードごと出さない。
// ⛔通信 +1(レースページで**出馬表のある日だけ**1本)。レース一覧・トップからは呼ばない。
// ⛔行が無ければ null(取れなかったのか無いのかを画面で言い分けない= 何も出さないだけ)
export function tenkaiOf(date) {
  if (!isDateStr(date)) return Promise.resolve(null);
  return memo(`tenkai:${date}`, 10 * MIN, async () => {
    let rows;
    try { rows = await sbNar(`nar_meta?select=value&key=eq.tenkai:${date}`); } catch { return null; }
    const v = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const races = v && v.races && typeof v.races === 'object' ? v.races : null;
    return races ? { built: str(v.built), races } : null;
  });
}

// §103 コース特性。cloud/course_stats.py が朝の便で書く `nar_meta 'course_stats:<prefix>'`
// = {built, since, until, dist:{"1400":{races,avg_head,win_time,going,gate[],style[],lead}}}。
// ⚠**公式に発表された結果を当サイトが数えたもの**(推定ではない)。⚠当日のレースは入っていない。
// ⚠率は入っていない= 画面が n で割る(数と率の食い違いを作らないため)。
// ⛔通信 +1(コース別データのページだけ)。場ページ・レースページからは呼ばない。
// ⛔行が無ければ null(取れなかったのか無いのかを画面で言い分けない)
export function courseStats(prefix) {
  const p = str(prefix);
  if (!/^[a-z]+$/.test(p)) return Promise.resolve(null);
  return memo(`course:${p}`, 30 * MIN, async () => {
    let rows;
    try { rows = await sbNar(`nar_meta?select=value&key=eq.course_stats:${p}`); } catch { return null; }
    const v = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const dist = v && v.dist && typeof v.dist === 'object' ? v.dist : null;
    return dist ? { built: str(v.built), since: str(v.since), until: str(v.until), dist } : null;
  });
}

// §45 もうすぐ初出走。cloud/noken_debuts.py が毎日書く `nar_meta 'noken_debuts'` を**1本**読む
// (`{built, dates, debuts:[{date,track,no,name,noken:{d,date,time,ok,r,n,tr}}]}`)。読めなければ null。
// ⚠`fresh` = built が**2日より古くない**こと。古い一覧を出し続けないための印(判断は画面側)。
// ⚠能検の中身は索引の一部(r/n/tr/date/time/ok だけ)= 上がり・テン1F・映像は入っていない
export function getNokenDebuts() {
  return memo('nokendebuts', 10 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_meta?select=value&key=eq.noken_debuts'); } catch { return null; }
    return parseNokenDebuts(Array.isArray(rows) && rows.length ? rows[0].value : null);
  });
}

// blob の中身の読み取り。**ここ1か所**(§46 でトップが同じ blob を相乗りで引くようになったため)
function parseNokenDebuts(v) {
  if (!v || typeof v !== 'object') return null;
  const debuts = [];
  for (const x of (Array.isArray(v.debuts) ? v.debuts : [])) {
    const date = str(x && x.date);
    const name = str(x && x.name);
    const venue = narPrefixOf(str(x && x.track));
    const no = num(x && x.no);
    if (!isDateStr(date) || !name || !venue) continue;
    debuts.push({
      date,
      venue,
      no,
      raceId: no !== null ? `${venue}/${date}/${no}` : null,
      name,
      ht: str(x && x.ht),                        // §45 v2 発走時刻 'H:MM'(古い blob には無い=null)
      horseId: `nar:${name}`,                    // まだ1走もしていない馬でも馬ページは出る(次走+血統+能検)
      noken: nokenRecs([x && x.noken])[0] || null,
    });
  }
  const built = str(v.built);
  const day = /^(\d{4}-\d{2}-\d{2})/.exec(built || '');
  return {
    built,
    fresh: !!(day && day[1] >= addDays(todayJST(), -2)),
    dates: (Array.isArray(v.dates) ? v.dates : []).map(str).filter(isDateStr),
    debuts,
  };
}

// §20.2 その日の受検馬のうち「馬ページのある馬」= 競馬ブックに結果か出馬表がある馬。Set(馬ID)。30分メモ。
// 能検を受けたばかりの馬はまだ1走もしておらず、リンクにすると行き止まりになる
// (実測 2026-08-25: 最新日は門別 4/14頭・大井 15/52頭しか居ない。古い日ほど増える)
export function getNokenLinks(prefix, date) {
  const p = String(prefix ?? '');
  // 主催者公式の4地区(§32)は行に競馬ブックの馬IDが無いので、そもそも引かない
  if (!NOKEN_CHIHOU.includes(p) || !isDateStr(date)) return Promise.resolve(new Set());
  return memo(`nokenlink:${p}:${date}`, 30 * MIN, async () => {
    const days = await nokenDays(p);
    const day = (Array.isArray(days) ? days : []).find((d) => String(d && d.date) === date);
    const codes = [...new Set((day && Array.isArray(day.races) ? day.races : [])
      .flatMap((r) => (Array.isArray(r.rows) ? r.rows : []))
      .map((w) => nokenText(w && w.horse_id) ?? '')
      .filter((c) => /^\d{7}$/.test(c)))];
    if (!codes.length) return new Set();
    const ids = enc(quoteIn(codes));
    const parts = await Promise.all([
      sb(`chihou_results?select=horse_id&horse_id=in.(${ids})&limit=1000`).catch(() => null),
      sb(`chihou_entries?select=horse_id&horse_id=in.(${ids})&limit=1000`).catch(() => null),
    ]);
    const out = new Set();
    for (const rows of parts) {
      if (!Array.isArray(rows)) continue;
      // 1000 行上限に当たったら「分からない」= 全部リンクにする(リンクを落とすより出しすぎるほうがまし)
      if (rows.length >= 1000) return new Set(codes.map((c) => `kb:${c}`));
      for (const r of rows) { const c = str(r.horse_id); if (c) out.add(`kb:${c}`); }
    }
    return out;
  });
}

// 厩舎の話の履歴(kb: のみ・最大 8)。日付・場・R は chihou_races から引く(race_id の桁から日付を作らない)。
// 競馬ブック由来なので §58 管理者だけ Worker 経由で引く(閲覧者には常に [])
async function danwaHistory(code) {
  if (!FLAGS.dev) return [];
  const j = await adminGet(`/rpc/admin-danwa-history?horse_id=${enc(code)}`);
  const rows = j && j.ok && Array.isArray(j.rows) ? j.rows : [];
  const items = rows.map((r) => ({ rid: String(r.race_id ?? ''), d: danwaOf(r) })).filter((x) => x.rid && x.d);
  if (!items.length) return [];
  // race_id は 16 桁の数字だけを in.() に入れる(それ以外の値でフィルタ構文を壊さない)
  const rids = [...new Set(items.map((x) => x.rid))].filter((s) => /^\d+$/.test(s)).join(',');
  const info = new Map();
  const infoRows = rids ? await sb(`chihou_races?select=race_id,track,race_date,race_no&race_id=in.(${rids})`).catch(() => []) : [];
  for (const r of infoRows) info.set(String(r.race_id), r);
  const out = items.map(({ rid, d }) => {
    const r = info.get(rid);
    const v = r && VENUE_BY_NAME.get(String(r.track ?? '').trim());
    const date = r && isDateStr(r.race_date) ? String(r.race_date) : null;
    const no = r ? num(r.race_no) : null;
    return { date, venue: v ? v.prefix : null, raceNo: no, raceId: v && date && no !== null ? `${v.prefix}/${date}/${no}` : null, ...d };
  });
  return out.sort((a, b) => String(b.date ?? '').localeCompare(String(a.date ?? ''))).slice(0, 8);
}

// 馬の独自データ(throw しない。全滅でも空配列 / null)。5 分
export function getHorseOwn(horse) {
  const h = horse && typeof horse === 'object' && typeof horse.id === 'string' ? horse : null;
  if (!h) return Promise.resolve(emptyHorseOwn());
  return memo(`own:horse:${h.id}`, 5 * MIN, async () => {
    const runs = Array.isArray(h.runs) ? h.runs : [];
    const m = h.id.match(/^kb:(\d{7})$/);
    const v = m && h.venue ? VENUE_BY_PREFIX.get(h.venue) : null;
    const [k, nk, dh] = await Promise.allSettled([
      kochiHorseOwn(runs),
      v && NOKEN_CHIHOU.includes(v.prefix) ? nokenOf(v, m[1]) : Promise.resolve(null),
      m ? danwaHistory(m[1]) : Promise.resolve([]),
    ]);
    const own = k.status === 'fulfilled' ? k.value : { first3fHistory: [], paddockClips: [] };
    return { ...own, noken: nk.status === 'fulfilled' ? nk.value : null, danwaHistory: dh.status === 'fulfilled' ? dh.value : [] };
  });
}

// トップの「ここでしか見られないデータ」用の要約(60 秒)。源ごとに allSettled・取れた項目だけ返す
export function getOwnSummary() {
  return memo('own:summary', MIN, async () => {
    const [laps, pad, nk] = await Promise.allSettled([
      // 区間ラップが入っている最新の開催日(like.[* = JSON 配列が入っている行。'' は除外)
      sb(`keiba_races?select=race_date,race_no&baba_code=eq.${KOCHI_BABA}&lap_times=like.${enc('[')}*&order=race_date.desc,race_no.asc&limit=12`),
      paddockIndex(),
      sb(`chihou_meta?select=k:key,d:${enc('value->days->0->>date')}&key=in.(${NOKEN_CHIHOU.map((p) => `${p}_noken`).join(',')})`),
    ]);
    let lapsOut = null;
    if (laps.status === 'fulfilled' && laps.value.length) {
      const first = laps.value[0];
      lapsOut = { date: fromKochiDate(first.race_date), raceNo: Number(first.race_no), count: laps.value.filter((r) => r.race_date === first.race_date).length };
    }
    let paddock = null;
    const idx = pad.status === 'fulfilled' ? pad.value : null;
    const dates = idx ? Object.keys(idx.days).filter(isDateStr).sort() : [];
    if (dates.length) {
      const date = dates[dates.length - 1];
      const nos = Object.keys(idx.days[date]).map(Number).filter((n) => Number.isInteger(n) && n > 0).sort((a, b) => a - b);
      const count = nos.reduce((s, n) => s + paddockSet(idx, date, n).size, 0);
      if (nos.length && count) paddock = { date, raceNo: nos[0], count };
    }
    const noken = [];
    if (nk.status === 'fulfilled') {
      const byKey = new Map(nk.value.map((r) => [String(r.k), r.d]));
      for (const p of NOKEN_CHIHOU) { const d = byKey.get(`${p}_noken`); if (isDateStr(d)) noken.push({ venue: p, date: d }); }
    }
    return { laps: lapsOut, paddock, noken };
  });
}

// §20 追補: 能検の「各場の最新検査日」だけの軽い一覧(ハブページ /noken 用)。10分メモ
export function getNokenSummary() {
  return memo('nokensum', 10 * MIN, async () => {
    const sel = `k:key,d:${enc('value->days->0->>date')}`;
    // 2つの DB にまたがるので2本。片方が落ちても取れたほうは出す
    const settled = await Promise.allSettled([
      sb(`chihou_meta?select=${sel}&key=in.(${NOKEN_CHIHOU.map((x) => `${x}_noken`).join(',')})`),
      sbNar(`nar_meta?select=${sel}&key=in.(${NOKEN_NAR.map((x) => `${x}_noken`).join(',')})`),
    ]);
    const byKey = new Map();
    for (const s of settled) {
      if (s.status !== 'fulfilled') continue;
      for (const r of (Array.isArray(s.value) ? s.value : [])) byKey.set(String(r.k), r.d);
    }
    const out = [];
    for (const px of NOKEN_PREFIXES) {
      const dist = nokenDistrict(px);
      const d = byKey.get(`${px}_noken`);
      if (dist) out.push({ venue: px, name: dist.name, date: isDateStr(d) ? String(d) : null });
    }
    return out;
  });
}

// §18.4: その場の過去の開催日(新しい順)。1日1行にするため race_no=eq.1 で引く。30分メモ。
// 川崎・浦和は静的アーカイブにも開催日があるので和集合にする(§12)
export function getVenueDates(prefix) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v) return Promise.resolve([]);
  return memo(`vdates:${v.prefix}`, 30 * MIN, async () => {
    const today = todayJST();
    let dates = [];
    try {
      // §30.6 上限(lte.今日)を外して**先に出ている開催日**も返す。公式は先の出馬表を持つので
      // 「今後の開催」がこれ1本で出せる(クエリ本数は増えない)。過去と未来の切り分けは呼び出し側で
      const rows = await sbNar(`nar_races?select=race_date&track=eq.${enc(narTrackName(v))}` +
        `&race_no=eq.1&order=race_date.desc&limit=1000`);
      dates = (Array.isArray(rows) ? rows : []).map((r) => String(r.race_date)).filter(isDateStr);
    } catch { dates = []; }
    if (archive.on(v.prefix)) {
      try {
        const arc = (await archive.dates(v.prefix)).filter((d) => isDateStr(d) && d <= today);
        dates = [...dates, ...arc];
      } catch { /* 公式ぶんだけで出す */ }
    }
    return [...new Set(dates)].sort((a, b) => b.localeCompare(a));
  });
}

// §18.2: その日の払戻を1クエリでまとめて取る(全15場・公式データ)。Map('prefix/no' → Payout[])。10分メモ
export function getDayPayouts(date) {
  if (!isDateStr(date)) return Promise.resolve(new Map());
  return ssMemo(`daypays:${date}`, 10 * MIN, async () => {
    const out = new Map();
    let rows;
    try {
      rows = await sbNar(`nar_race_payouts?select=track,race_no,payouts&race_date=eq.${date}&limit=300`);
    } catch { return out; }
    for (const row of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(row.track);
      const no = num(row.race_no);
      if (!prefix || no === null) continue;
      out.set(`${prefix}/${no}`, narPayoutList(row, `${prefix}/${date}/${no}`, null));
    }
    return out;
  }, {
    persist: isDateStr(date) && date < todayJST(),
    ok: (v) => v.size > 0,
    dump: (v) => [...v],
    revive: (raw) => new Map(raw),
  });
}

// ---------------------------------------------------------------- §15 AI の印と成績(nar_ai_marks / nar_ai_record)

// 印の行 → {model, timing, computedAt, fieldSize, marks:[{num, mark, score, factors[]}]}
// §122 で export に(B/C の行も同じ形に直して同じ表で出す)。⛔model と取得元の同一性は呼び側で保つ
export function aiMarksFromRow(row, model) {
  const meta = row && row.meta && typeof row.meta === 'object' ? row.meta : {};
  const factors = meta.factors && typeof meta.factors === 'object' ? meta.factors : {};
  const list = Array.isArray(row && row.marks) ? row.marks : [];
  const marks = list.map((m) => {
    const n = num(m && m.num);
    // 馬番のキーは文字列。プロトタイプの値を拾わないよう自分の持ち物だけ見る
    const f = n !== null && Object.prototype.hasOwnProperty.call(factors, String(n)) ? factors[String(n)] : null;
    return {
      num: n,
      mark: str(m && m.mark) || '',
      score: num(m && m.score),
      factors: (Array.isArray(f) ? f : []).map(str).filter(Boolean),
    };
  }).filter((m) => m.num !== null && m.mark);
  if (!marks.length) return null;
  return {
    model,
    timing: str(row.timing),
    computedAt: str(row.computed_at),
    fieldSize: num(meta.n),
    marks,
  };
}

// レース1件の印(直前予想を優先し、無ければ朝予想)。行が無ければ null。10分メモ。
// 一覧ページからは呼ばない(1レース1クエリなので N+1 になる)
export function getRaceMarks(race) {
  const r = race && typeof race === 'object' ? race : null;
  const v = r ? VENUE_BY_PREFIX.get(String(r.venue ?? '')) : null;
  const no = r ? Number(r.no) : NaN;
  if (!v || !isDateStr(r.date) || !Number.isInteger(no) || no < 1) return Promise.resolve(null);
  const model = AI_PRIMARY_MODEL;
  return memo(`marks:${model}:${v.prefix}/${r.date}/${no}`, 10 * MIN, async () => {
    const rows = await sbNar(`nar_ai_marks?model=eq.${enc(model)}&track=eq.${enc(narTrackName(v))}` +
      `&race_date=eq.${r.date}&race_no=eq.${no}&select=timing,marks,meta,computed_at`);
    if (!Array.isArray(rows) || !rows.length) return null;
    const row = rows.find((x) => x.timing === 'last') || rows.find((x) => x.timing === 'morning') || rows[0];
    return aiMarksFromRow(row, model);
  });
}

// §122 B/C 専用の読み。⛔getRaceMarks とは別物= **timing=last の完全一致だけ**で、
//   morning・base・別日・別 R で補完しない。⛔自動再試行なし(sbNarOnce)。
//   戻り= {state:'ok', row} / {state:'none'}(正常応答で 0 行= 未掲載) /
//        {state:'ambiguous', rows}(2 行以上= 先頭で隠さない) / {state:'error', status}(HTTP 失敗)。
//   メモは model+場+日付+R を鍵に 5 分。⛔失敗は覚えない(利用者がもう一度押したときは引き直す=自動ではない)
export function getRaceMarksFor(model, race) {
  const md = str(model);
  const r = race && typeof race === 'object' ? race : null;
  const v = r ? VENUE_BY_PREFIX.get(String(r.venue ?? '')) : null;
  const no = r ? Number(r.no) : NaN;
  if (!md || !v || !isDateStr(r && r.date) || !Number.isInteger(no) || no < 1) {
    return Promise.resolve({ state: 'error', status: null });
  }
  const track = narTrackName(v);
  return memo(`marksfor:${md}:${track}/${r.date}/${no}`, 5 * MIN, async () => {
    const rows = await sbNarOnce(`nar_ai_marks?model=eq.${enc(md)}&track=eq.${enc(track)}` +
      `&race_date=eq.${enc(r.date)}&race_no=eq.${enc(String(no))}&timing=eq.last` +
      '&select=model,track,race_date,race_no,timing,marks,meta,computed_at');
    // 読み返し= 返った行が**頼んだ鍵そのもの**か見る(合わない行は数えない=別モデル・別競走を出さない)
    const list = (Array.isArray(rows) ? rows : []).filter((x) => x && str(x.model) === md &&
      str(x.track) === track && str(x.race_date) === r.date && num(x.race_no) === no && str(x.timing) === 'last');
    if (!list.length) return { state: 'none' };
    if (list.length > 1) return { state: 'ambiguous', rows: list.length };
    return { state: 'ok', row: list[0] };
  }).catch((e) => ({ state: 'error', status: num(e && e.cause && e.cause.status) }));
}

// §23.3: その日の印を「朝/直前」両方そのまま返す(1クエリ)。Map('prefix/no' → {morning, last})。10分メモ
export function getDayMarksDetail(date, model) {
  const md = str(model) || AI_PRIMARY_MODEL;
  if (!isDateStr(date)) return Promise.resolve(new Map());
  return memo(`daymarksd:${md}:${date}`, 10 * MIN, async () => {
    const out = new Map();
    let rows;
    try {
      rows = await sbNar(`nar_ai_marks?model=eq.${enc(md)}&race_date=eq.${date}` +
        '&select=track,race_no,timing,marks,meta,computed_at&limit=400');
    } catch { return out; }
    for (const row of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(row.track);
      const no = num(row.race_no);
      const timing = str(row.timing);
      if (!prefix || no === null || (timing !== 'morning' && timing !== 'last')) continue;
      const m = aiMarksFromRow(row, md);
      if (!m) continue;
      const key = `${prefix}/${no}`;
      const cur = out.get(key) || { morning: null, last: null };
      cur[timing] = m;
      out.set(key, cur);
    }
    return out;
  });
}

// §23.3 その日の出走馬の名前をまとめて引く(1クエリ)。Map('prefix/no/umaban' → 馬名)。
// 結果が出る前は getDayResults に馬名が無いので、印の馬を名前で出すのに使う。
// §26.3 同じ1クエリで着順も持ち帰る(Map の値は馬名のまま・`.finish` を足しただけ=呼び出し側は無改修で動く)。
// 1レース最大16頭なので 60 レースずつに切る(PostgREST の 1000 行上限に当てない)
export async function getRunnerNames(date, races) {
  const out = new Map();
  out.finish = new Map();               // 'prefix/no/umaban' → {finish, note}
  const list = Array.isArray(races) ? races : [];
  if (!isDateStr(date) || !list.length) return out;
  const byRace = new Map();
  for (const x of list) {
    const v = x ? VENUE_BY_PREFIX.get(String(x.venue ?? '')) : null;
    const no = x ? num(x.no) : null;
    if (!v || no === null) continue;
    byRace.set(`${v.prefix}/${no}`, { track: narTrackName(v), no });
  }
  await Promise.all(chunk([...byRace.values()], 60).map(async (part) => {
    const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_no.eq.${k.no})`).join(',');
    let rows;
    try {
      // margin も取る= 取消などの注記が margin 列に入っている行があるため(§10 #18・narNote が両方を見る)
      rows = await sbNar('nar_runs?select=track,race_no,runner_number,horse_name,finish,finish_note,margin' +
        `&race_date=eq.${date}&or=(${cond})&limit=1000`);
    } catch { return; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      const nm = str(r.horse_name);
      const no = num(r.race_no);
      const n = num(r.runner_number);
      if (!prefix || !nm || no === null || n === null) continue;
      out.set(`${prefix}/${no}/${n}`, nm);
      const note = narNote(r).note;
      out.finish.set(`${prefix}/${no}/${n}`, { finish: note !== null ? null : narFinish(r), note });
    }
  }));
  return out;
}

// §23.3 成績のある印モデル(2つ以上あるときだけ画面に切替を出す)。30分メモ
// ⛔並べるのは AI_PUBLIC_MODELS にある名前だけ(影モデルを本番に出さない=2026-08-28)。
//   ここが閲覧者が既定以外のモデルに触れる**唯一の入口**(record.js の state.model はこのボタンでしか動かず、
//   URL からは入らない=2026-08-28 確認)。増やすときは AI_PUBLIC_MODELS を見ること
export function getAiModels() {
  return memo('aimodels', 30 * MIN, async () => {
    let rows;
    try { rows = await sbNar("nar_ai_record?select=model&track=eq.all&limit=100"); } catch { return [AI_PRIMARY_MODEL]; }
    const seen = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const m = str(r.model);
      if (m && AI_PUBLIC_MODELS.includes(m) && !seen.includes(m)) seen.push(m);
    }
    if (!seen.includes(AI_PRIMARY_MODEL)) seen.unshift(AI_PRIMARY_MODEL);
    // いま画面に出しているモデルを先頭に
    return seen.sort((a, b) => (a === AI_PRIMARY_MODEL ? -1 : b === AI_PRIMARY_MODEL ? 1 : a.localeCompare(b)));
  });
}

// §16.2: その日の印を1クエリでまとめて取る(直前予想を優先)。Map('prefix/no' → 印)。10分メモ
export function getDayMarks(date) {
  if (!isDateStr(date)) return Promise.resolve(new Map());
  const model = AI_PRIMARY_MODEL;
  return memo(`daymarks:${model}:${date}`, 10 * MIN, async () => {
    const out = new Map();
    let rows;
    try {
      rows = await sbNar(`nar_ai_marks?model=eq.${enc(model)}&race_date=eq.${date}` +
        '&select=track,race_no,timing,marks,meta,computed_at&limit=300');
    } catch { return out; }
    for (const row of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(row.track);
      const no = num(row.race_no);
      if (!prefix || no === null) continue;
      const key = `${prefix}/${no}`;
      const cur = out.get(key);
      if (cur && cur.timing === 'last' && row.timing !== 'last') continue;   // 直前予想を優先
      const m = aiMarksFromRow(row, model);
      if (m) out.set(key, m);
    }
    return out;
  });
}

// 'HH:MM' → 分。読めなければ null
// 'HH:MM' → 0時からの分。⛔それ以外は null(NaN や 25:99 を時刻として扱わない)。
// ⚠§Codex A7 の `hasStarted()` もこれを使う(時刻の読み方を2つに増やさない)
function hhmmMinutes(v) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(v ?? ''));
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  return h < 24 && mi < 60 ? h * 60 + mi : null;
}
// 選んだレースの◎の馬名を1クエリで引く(≤5レースぶん)。取れない馬番は null のまま
async function fillKachiNames(date, picks) {
  const cond = picks.map((p) => {
    const v = VENUE_BY_PREFIX.get(p.venue);
    return v ? `and(track.eq.${enc(narTrackName(v))},race_no.eq.${p.no})` : null;
  }).filter(Boolean).join(',');
  if (!cond) return;
  let rows;
  try {
    rows = await sbNar(`nar_runs?select=track,race_no,runner_number,horse_name&race_date=eq.${date}&or=(${cond})&limit=300`);
  } catch { return; }
  const byKey = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const prefix = narPrefixOf(r.track);
    if (!prefix) continue;
    byKey.set(`${prefix}/${Number(r.race_no)}/${Number(r.runner_number)}`, str(r.horse_name));
  }
  for (const p of picks) p.horseName = byKey.get(`${p.venue}/${p.no}/${p.umaban}`) ?? null;
}

// §16.2 「本日の勝負レース」= 印の点数の開き(◎−○)が大きい順・最大 KACHI_MAX 件。
// 今日以外の日付は [](「本日の」なので)。失敗しても [] を返す(トップ本文に影響させない)。
// §21.2-5 で「発走済みを落とす」のをやめた: 落とすと再読み込みのたびに行が消え、
// ◎がどうなったかを確かめられない(答え合わせはトップが持つ結果と突き合わせて画面側で出す)
export async function getKachiPicks(date, races) {
  const list = Array.isArray(races) ? races : [];
  if (!isDateStr(date) || date !== todayJST() || !list.length) return [];
  let marks;
  try { marks = await getDayMarks(date); } catch { return []; }
  const picks = pickKachi(list, marks);
  if (picks.length) await fillKachiNames(date, picks);
  return picks;
}

// §46 T3 **選び方はここ1か所だけ**(トップの「本日の勝負レース」も /shobu の過去日も同じ関数を通す)。
// races = [{venue,no,id,postTime}] / marks = Map('prefix/no' → {timing, computedAt, marks:[{num,score},…]})。
// ⛔ここを触ると過去の振り返りの意味も変わる=§5.4「基準は1か所」の規律
export function pickKachi(races, marks) {
  const list = Array.isArray(races) ? races : [];
  if (!marks || !marks.size || !list.length) return [];
  const cands = [];
  for (const race of list) {
    const m = marks.get(`${race.venue}/${race.no}`);
    if (!m || m.marks.length < 2) continue;
    if (hhmmMinutes(race.postTime) === null) continue;    // 発走時刻が読めないレースは出さない(表に出す値が無い)
    const top = m.marks[0], second = m.marks[1];
    if (top.score === null || second.score === null) continue;
    cands.push({
      venue: race.venue,
      no: race.no,
      raceId: race.id,
      postTime: race.postTime,
      umaban: top.num,
      horseName: null,
      score: top.score,
      gap: Math.round((top.score - second.score) * 100) / 100,
      timing: m.timing,
      computedAt: m.computedAt,
    });
  }
  cands.sort((a, b) => b.gap - a.gap || b.score - a.score || String(a.postTime).localeCompare(String(b.postTime)));
  return cands.slice(0, KACHI_MAX);
}

// ---------------------------------------------------------------- §46 T3 過去の勝負レース(/shobu)

export const SHOBU_DAYS = 14;             // さかのぼる日数。⚠印は 1 日 100 行前後=1000 行上限に当てない窓

// 印(nar_ai_marks)を窓ぶんまとめて1本。**◎と○だけ**を JSON セレクタで取る
// (全部だと 5 日で 143KB、先頭2件なら 79KB=2026-08-28 実測)。返り値 = Map(date → Map('prefix/no' → 印))
async function shobuMarks(from, to) {
  const model = AI_PRIMARY_MODEL;
  let rows;
  try {
    rows = await sbNar(`nar_ai_marks?model=eq.${enc(model)}&race_date=gte.${from}&race_date=lte.${to}` +
      `&select=track,race_date,race_no,timing,a:${enc('marks->0')},b:${enc('marks->1')}` +
      '&order=race_date.desc&limit=1000');
  } catch { return new Map(); }
  warnIfCapped(rows);
  const out = new Map();
  for (const row of (Array.isArray(rows) ? rows : [])) {
    const prefix = narPrefixOf(row.track);
    const no = num(row.race_no);
    const date = str(row.race_date);
    if (!prefix || no === null || !isDateStr(date)) continue;
    if (!out.has(date)) out.set(date, new Map());
    const day = out.get(date);
    const key = `${prefix}/${no}`;
    const cur = day.get(key);
    if (cur && cur.timing === 'last' && row.timing !== 'last') continue;   // 直前予想を優先(getDayMarks と同じ)
    const two = [row.a, row.b].map((m) => ({ num: num(m && m.num), mark: str(m && m.mark) || '', score: num(m && m.score) }))
      .filter((m) => m.num !== null && m.mark);
    if (two.length < 2) continue;
    day.set(key, { model, timing: str(row.timing), computedAt: null, marks: two });
  }
  return out;
}

// 窓ぶんの発走時刻を1本(nar_races・race_no ごと)。返り値 = Map(date → [{venue,no,id,postTime}])
async function shobuRaces(from, to) {
  let rows;
  try {
    rows = await sbNar(`nar_races?select=track,race_date,race_no,post_time&${NAR_ALL_IN}` +
      `&race_date=gte.${from}&race_date=lte.${to}&order=race_date.desc&limit=1000`);
  } catch { return new Map(); }
  warnIfCapped(rows);
  const out = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const prefix = narPrefixOf(r.track);
    const no = num(r.race_no);
    const date = str(r.race_date);
    if (!prefix || no === null || !isDateStr(date)) continue;
    if (!out.has(date)) out.set(date, []);
    out.get(date).push({ venue: prefix, no, id: `${prefix}/${date}/${no}`, postTime: narPostTime(r.post_time) });
  }
  return out;
}

// 選ばれたレースの◎について、馬名・着順を1本で引く(1レース1頭ぶんを and(...) で名指し=行数=件数)
async function shobuRuns(picks) {
  if (!picks.length) return;
  const conds = [];
  for (const p of picks) {
    const v = VENUE_BY_PREFIX.get(p.venue);
    if (!v) continue;
    conds.push(`and(track.eq.${enc(narTrackName(v))},race_date.eq.${p.date},race_no.eq.${p.no},runner_number.eq.${p.umaban})`);
  }
  const got = new Map();
  await Promise.all(chunk(conds, 40).map(async (part) => {
    let rows;
    try {
      rows = await sbNar('nar_runs?select=track,race_date,race_no,runner_number,horse_name,finish,finish_note' +
        `&or=(${part.join(',')})&limit=500`);
    } catch { return; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      if (!prefix) continue;
      got.set(`${prefix}/${r.race_date}/${Number(r.race_no)}/${Number(r.runner_number)}`,
        { name: str(r.horse_name), finish: num(r.finish), note: str(r.finish_note) });
    }
  }));
  for (const p of picks) {
    const hit = got.get(`${p.venue}/${p.date}/${p.no}/${p.umaban}`);
    if (!hit) continue;
    p.horseName = hit.name || null;
    p.finish = hit.finish;
    p.finishNote = hit.note || null;
  }
}

// 単勝の配当は**◎が勝ったレースだけ**引く(払戻は1レース約1KBあるので全件は取らない)
async function shobuWinPay(picks) {
  const won = picks.filter((p) => p.finish === 1);
  if (!won.length) return;
  const conds = won.map((p) => {
    const v = VENUE_BY_PREFIX.get(p.venue);
    return v ? `and(track.eq.${enc(narTrackName(v))},race_date.eq.${p.date},race_no.eq.${p.no})` : null;
  }).filter(Boolean);
  if (!conds.length) return;
  const got = new Map();
  await Promise.all(chunk(conds, 40).map(async (part) => {
    let rows;
    try {
      rows = await sbNar(`nar_race_payouts?select=track,race_date,race_no,payouts&or=(${part.join(',')})&limit=200`);
    } catch { return; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      if (!prefix) continue;
      got.set(`${prefix}/${r.race_date}/${Number(r.race_no)}`, Array.isArray(r.payouts) ? r.payouts : []);
    }
  }));
  for (const p of won) {
    const list = got.get(`${p.venue}/${p.date}/${p.no}`) || [];
    const hit = list.find((x) => String(x && x.t) === 'win' && String(x && x.c) === String(p.umaban));
    p.winYen = hit ? Number(hit.y) : null;
  }
}

// §46 T3 過去の勝負レース。返り値 = {from,to,days:[{date,picks:[…]}],total:{n,w1,t3,ret,pending}}。
// ⛔選定は pickKachi(トップと同じ)。通信= 印1本 + 発走時刻1本 + 着順1本 + (勝ったレースだけ)払戻1本
export function getShobuHistory(days) {
  const n = Number.isInteger(days) && days > 0 && days <= 60 ? days : SHOBU_DAYS;
  const to = todayJST();
  const from = addDays(to, -(n - 1));
  return memo(`shobu:${from}:${to}`, 10 * MIN, () => loadShobu(from, to));
}

async function loadShobu(from, to) {
  const [marksByDate, racesByDate] = await Promise.all([shobuMarks(from, to), shobuRaces(from, to)]);
  const all = [];
  const days = [];
  for (const date of [...marksByDate.keys()].sort((a, b) => b.localeCompare(a))) {
    const picks = pickKachi(racesByDate.get(date) || [], marksByDate.get(date));
    if (!picks.length) continue;
    for (const p of picks) { p.date = date; p.finish = null; p.finishNote = null; p.winYen = null; }
    days.push({ date, picks });
    all.push(...picks);
  }
  await shobuRuns(all);
  await shobuWinPay(all);
  // 集計= 着順が付いた◎だけを分母にする(結果待ち・取消は数えない=数字を大きく見せない)
  const settled = all.filter((p) => p.finish !== null);
  const w1 = settled.filter((p) => p.finish === 1).length;
  const t3 = settled.filter((p) => p.finish <= 3).length;
  const yen = settled.reduce((a, p) => a + (p.winYen || 0), 0);
  return {
    from, to,
    days,
    total: {
      n: settled.length,
      pending: all.length - settled.length,
      w1, t3,
      win: settled.length ? Math.round(w1 / settled.length * 1000) / 10 : null,
      fuku: settled.length ? Math.round(t3 / settled.length * 1000) / 10 : null,
      ret: settled.length ? Math.round(yen / settled.length) : null,
    },
  };
}

// 成績はモデルごとに1回だけ引いて全部(場×時点 ≤32行)を持つ。タブ切替は無通信(getPerson と同じ作法)
function aiRecordRows(model) {
  return memo(`airec:${model}`, 10 * MIN, () =>
    sbNar(`nar_ai_record?model=eq.${enc(model)}&select=track,timing,stats,updated_at&limit=100`));
}

function aiBasic(o) {
  const s = o && typeof o === 'object' ? o : {};
  return {
    n: num(s.n) ?? 0, w1: num(s.w1) ?? 0,
    win: num(s.win), ren: num(s.ren), fuku: num(s.fuku),
    tanRet: num(s.tanRet), fukuRet: num(s.fukuRet),
  };
}

// 行がある場(VENUES の順)。'all' の行は場ではないので除く
function aiRecordVenues(rows) {
  const out = [];
  const seen = new Set();
  for (const r of rows) {
    const t = String(r.track ?? '');
    if (t === 'all') continue;
    const prefix = narPrefixOf(t);
    if (!prefix || seen.has(prefix)) continue;
    seen.add(prefix);
    out.push({ prefix, name: VENUE_BY_PREFIX.get(prefix).name, order: VENUE_BY_PREFIX.get(prefix).order });
  }
  return out.sort((a, b) => a.order - b.order).map((x) => ({ prefix: x.prefix, name: x.name }));
}

function aiRecordFromRow(row, venueKey, timing, model, rows) {
  const s = row.stats && typeof row.stats === 'object' ? row.stats : {};
  const byMark = (Array.isArray(s.byMark) ? s.byMark : [])
    .map((m) => ({ mark: str(m && m.mark) || '', ...aiBasic(m) }))
    .filter((m) => m.mark);
  const bands = (Array.isArray(s.popBands) ? s.popBands : [])
    .map((b) => ({ band: str(b && b.band) || '', n: num(b && b.n) ?? 0, w1: num(b && b.w1) ?? 0, win: num(b && b.win), fuku: num(b && b.fuku), tanRet: num(b && b.tanRet) }))
    .filter((b) => b.band);
  // 割合は集計に無いので、人気が分かった◎の合計から出す(§15.1: share は持たない)
  const bandTotal = bands.reduce((a, b) => a + b.n, 0);
  for (const b of bands) b.share = bandTotal ? Math.round(b.n / bandTotal * 1000) / 10 : null;
  const monthly = (Array.isArray(s.monthly) ? s.monthly : [])
    .map((m) => ({ ym: str(m && m.ym) || '', n: num(m && m.n) ?? 0, w1: num(m && m.w1) ?? 0, win: num(m && m.win), fuku: num(m && m.fuku), tanRet: num(m && m.tanRet), fukuRet: num(m && m.fukuRet) }))
    .filter((m) => /^\d{4}-\d{2}$/.test(m.ym))
    .sort((a, b) => a.ym.localeCompare(b.ym));
  const daily = (Array.isArray(s.daily) ? s.daily : [])
    .map((d) => ({ date: isDateStr(d && d.d) ? String(d.d) : null, n: num(d && d.n) ?? 0, w1: num(d && d.w1) ?? 0, win: num(d && d.win), fuku: num(d && d.fuku), tanRet: num(d && d.tanRet) }))
    .filter((d) => d.date)
    .sort((a, b) => b.date.localeCompare(a.date));
  return {
    model,
    venue: venueKey,
    timing,
    n: num(s.n) ?? 0,
    from: isDateStr(s.from) ? String(s.from) : null,
    to: isDateStr(s.to) ? String(s.to) : null,
    top: aiBasic(s.top),
    byMark,
    popBands: bands,
    monthly,
    daily,
    venues: aiRecordVenues(rows),
    updatedAt: str(row.updated_at),
  };
}

// AI成績(venue='all'|prefix・timing='morning'|'last')。行が無ければ null(記録開始直後は表ごと空)
export function getAiRecord(venue, timing, model) {
  const m = str(model) || AI_PRIMARY_MODEL;
  const t = timing === 'morning' ? 'morning' : 'last';
  const key = String(venue ?? 'all');
  const v = key === 'all' ? null : VENUE_BY_PREFIX.get(key);
  if (key !== 'all' && !v) return Promise.resolve(null);
  const track = v ? narTrackName(v) : 'all';
  return aiRecordRows(m).then((rows) => {
    if (!Array.isArray(rows) || !rows.length) return null;
    const row = rows.find((x) => String(x.track) === track && String(x.timing) === t);
    return row ? aiRecordFromRow(row, key, t, m, rows) : null;
  });
}

// ---------------------------------------------------------------- §54.2 人物のプロフィール(nar_persons)

// ⛔突合の鍵は `name_short`(= `nar_runs.jockey` と同じ3文字・人物ページの URL の名前そのもの)。
// ⛔**同じ略称に2人いたら出さない**= 引いた行が**2行以上なら null**。出典が3文字に略しているため別人が
//   同じ `name_short` になる組があり、生年月日が違うので**どちらを出しても嘘**になる(#X1)。
//   ⛔一覧をコードに持たない= **行数で判定**しているので、将来増えても直さなくてよい
const PERSON_COLS = 'kind,name_short,birth,area';

export function getPersonProfile(kind, nameShort) {
  const k = kind === 'trainer' ? 'trainer' : 'jockey';
  const n = str(nameShort);
  if (!n) return Promise.resolve(null);
  return memo(`prof:${k}:${n}`, 30 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_persons?select=${PERSON_COLS}&kind=eq.${enc(k)}&name_short=eq.${enc(n)}&limit=5`);
    } catch { return null; }
    if (!Array.isArray(rows) || rows.length !== 1) return null;   // 0件=見つからない / 2件以上=別人が混ざる
    const b = str(rows[0].birth);
    return { birth: isDateStr(b) ? b : null, area: str(rows[0].area) };
  });
}

// §54.2 今日が誕生日で、**今日その場に乗る**騎手。⛔乗らない人の誕生日は情報にならないので出さない。
// ⛔`name_short=in.(…)` で**1本**にまとめる(1人1本にしない)。
// ⚠**月日は JS で見る**= `birth::text=like.*-MM-DD` は**この PostgREST では通らない**
//   (404 `operator does not exist: date ~~ unknown`・キャストなしでも同じ・2026-08-30 実測)。
//   その日に乗る騎手だけを名前で引くので**返る行は数十**(3人で 151 バイト実測)= 絞り込みは手元で足りる
export function getTodayBirthdays(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map((x) => str(x)).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve([]);
  const today = todayJST();
  const md = today.slice(5);                                     // 'MM-DD'
  return memo(`bday:${today}:${list.length}:${list.join(',')}`, 30 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_persons?select=${PERSON_COLS}&kind=eq.jockey` +
        `&name_short=in.(${enc(quoteIn(list))})&limit=200`);
    } catch { return []; }
    const seen = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const n = str(r.name_short);
      if (!n) continue;
      seen.set(n, (seen.get(n) || 0) + 1);
    }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const n = str(r.name_short);
      const b = str(r.birth);
      // ⛔2人いる略称は捨てる(#X1)。⛔今日の月日と合う人だけ
      if (!n || seen.get(n) !== 1 || !isDateStr(b) || b.slice(5) !== md) continue;
      out.push({ name: n, birth: b });
    }
    return out.sort((a, b2) => a.name.localeCompare(b2.name, 'ja'));
  });
}

// ---------------------------------------------------------------- §14 騎手・調教師(nar_person_stats)

// 名前ひとつで期間・場の全行(≤48行・13KB 実測)を1回だけ引く。期間タブの切替では引き直さない
function personRows(kind, name) {
  return memo(`person:${kind}:${name}`, 10 * MIN, () =>
    sbNar(`nar_person_stats?kind=eq.${enc(kind)}&name=eq.${enc(name)}&select=track,period,stats,updated_at&limit=200`));
}

function personTotal(s) {
  return {
    n: num(s.n) ?? 0, w1: num(s.w1) ?? 0, w2: num(s.w2) ?? 0, w3: num(s.w3) ?? 0,
    win: num(s.win), top2: num(s.top2), top3: num(s.top3), roi: num(s.roi),
    from: isDateStr(s.from) ? String(s.from) : null, to: isDateStr(s.to) ? String(s.to) : null,
  };
}
// 場の1行 → 表示用(prefix・場名つき)。VENUES に無い公式表記はそのまま名前にする
function personTrack(track, s) {
  const prefix = narPrefixOf(track);
  const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
  return { venue: prefix, name: v ? v.name : (str(track) || ''), order: v ? v.order : 99, ...personTotal(s) };
}
// 場別: 場ごとの行(出走10以上・w2/w3/回収率あり)を優先し、行が無い場は 'all' 行の by_track で補う
function personByTrack(rows, allStats) {
  const out = [];
  const seen = new Set();
  for (const r of rows) {
    if (r.track === 'all' || !r.stats) continue;
    out.push(personTrack(r.track, r.stats));
    seen.add(String(r.track));
  }
  for (const t of (Array.isArray(allStats.by_track) ? allStats.by_track : [])) {
    if (!t || seen.has(String(t.track))) continue;
    out.push({ ...personTrack(t.track, t), w2: null, w3: null, top2: null, roi: null, from: null, to: null });
  }
  return out.sort((a, b) => a.order - b.order || b.n - a.n);
}
function personByDistance(allStats) {
  return (Array.isArray(allStats.by_distance) ? allStats.by_distance : [])
    .map((d) => ({ distance: num(d && d.distance), n: num(d && d.n) ?? 0, w1: num(d && d.w1) ?? 0, win: num(d && d.win), top3: num(d && d.top3) }))
    .filter((d) => d.distance !== null && d.n > 0)
    .sort((a, b) => a.distance - b.distance);
}
// 直近30走(period='all' の行にだけ入る)。レース・馬へのリンク用に Race.id / 馬ID も組む
function personRecent(allStats) {
  return (Array.isArray(allStats.recent) ? allStats.recent : []).map((x) => {
    const date = x && isDateStr(x.d) ? String(x.d) : null;
    const prefix = narPrefixOf(x && x.track);
    const no = num(x && x.no);
    const horseName = str(x && x.horse);
    return {
      date,
      venue: prefix,
      venueName: prefix ? VENUE_BY_PREFIX.get(prefix).name : (str(x && x.track) || ''),
      raceNo: no,
      raceId: prefix && date && no !== null ? `${prefix}/${date}/${no}` : null,
      raceName: str(x && x.race),
      horseName,
      horseId: horseName ? `nar:${horseName}` : null,
      finish: num(x && x.fin),
      note: str(x && x.note),          // §62 B7-2 競走中止・失格を「着」の欄に出すため
      ninki: num(x && x.pop),
      distance: num(x && x.dist),
    };
  }).filter((r) => r.date);
}

// 騎手・調教師の成績(kind='jockey'|'trainer'・period='all'|'YYYY')。行が無ければ null。10分メモ
export function getPerson(kind, name, period) {
  const k = String(kind ?? '');
  const nm = str(name);
  const p = String(period ?? 'all');
  // §105 種牡馬(sire)・母父(bms)も同じ形の行なのでそのまま通す(⛔新しい関数を作らない)。
  //   ⚠あちらは track='all' の行しか無く recent も無い= byTrack/recent は空のまま返る
  if (!STATS_KINDS.includes(k) || !nm || !/^(all|\d{4})$/.test(p)) return Promise.resolve(null);
  return personRows(k, nm).then((rows) => {
    if (!Array.isArray(rows) || !rows.length) return null;
    const mine = rows.filter((r) => String(r.period) === p);
    const head = mine.find((r) => r.track === 'all');
    if (!head || !head.stats) return null;
    const s = head.stats;
    const allRow = rows.find((r) => r.track === 'all' && String(r.period) === 'all');
    const total = personTotal(s);
    const mainPrefix = narPrefixOf(s.main_track);
    return {
      kind: k,
      name: nm,
      period: p,
      // 期間タブ用(全期間→新しい年の順)。この1回のクエリで全部そろう
      periods: [...new Set(rows.map((r) => String(r.period)))].sort((a, b) => (a === 'all' ? -1 : b === 'all' ? 1 : b.localeCompare(a))),
      total,
      byTrack: personByTrack(mine, s),
      byDistance: personByDistance(s),
      // 直近30走は period='all' の行にしか無い(2026-08-24 実測)
      recent: personRecent(allRow && allRow.stats ? allRow.stats : {}),
      mainTrack: mainPrefix ? { venue: mainPrefix, name: VENUE_BY_PREFIX.get(mainPrefix).name } : (str(s.main_track) ? { venue: null, name: str(s.main_track) } : null),
      from: total.from,
      to: total.to,
      updatedAt: str(head.updated_at),
    };
  });
}

// 名前の部分一致(騎手→調教師の順・各最大10)。searchHorses と同じ入力の掃除
export async function searchPeople(q) {
  const raw = cleanKw(q);
  if (raw.length < 2) return [];
  const like = `*${enc(raw)}*`;
  const settled = await Promise.allSettled(PERSON_KINDS.map((kind) =>
    sbNar(`nar_person_stats?kind=eq.${kind}&track=eq.all&period=eq.all&name=like.${like}&select=name,stats->n&order=name.asc&limit=10`)
      .then((rows) => (Array.isArray(rows) ? rows : []).map((r) => ({ kind, name: str(r.name) || '', n: num(r.n) })))));
  const out = [];
  for (const s of settled) {
    if (s.status !== 'fulfilled') continue;
    for (const row of s.value) if (row.name) out.push(row);
  }
  return out;
}

// ---------------------------------------------------------------- §19.1 馬柱(出走各馬の直近5走)

const HIST_RUNS = 5;              // 1頭あたりに出す過去走
const HIST_ROW_LIMIT = 400;       // 競馬ブック・高知をまとめて引くときの行上限(1レース分に十分)
const HIST_NAR_LIMIT = 600;       // 公式(nar_runs)をまとめて引くときの行上限

// 過去走は「どの源のどの行か」だけの中間形 {date, venue, no, src, row} で集め、5走に切ってから Run に組む。
// レース情報(距離・馬場・レース名)は切った後の走にだけ足すので、要らない行の情報は引かない
function histPush(map, key, item) {
  const list = map.get(key);
  if (list) list.push(item); else map.set(key, [item]);
}
const histKey = (d) => `${d.venue}/${d.date}/${d.no}`;

// 新しい順に並べ、同じレースは1回だけ・HIST_RUNS 件に切る。
// 積んだ順(競馬ブック → 高知 → 公式)が同着のときは先に来るので、項目の多い源が残る(sort は安定)
function histCut(list) {
  const seen = new Set();
  const out = [];
  for (const d of list.slice().sort((a, b) => b.date.localeCompare(a.date) || (b.no ?? 0) - (a.no ?? 0))) {
    const k = histKey(d);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(d);
    if (out.length >= HIST_RUNS) break;
  }
  return out;
}

// 競馬ブック(chihou_results)。horse_id で引くので同名異馬の心配が無い(1クエリ)
async function histKb(codes, before) {
  const cols = 'race_id,horse_id,umaban,finish,finish_note,pop,time_str,time_sec,margin,first3f,last3f,passing,jockey,kinryo,body_weight,' +
    'chihou_races(track,race_date,race_no,distance_m,going,klass,race_name)';
  const rows = await sb(`chihou_results?select=${cols}&horse_id=in.(${enc(quoteIn(codes))})` +
    `&order=chihou_races(race_date).desc&limit=${HIST_ROW_LIMIT}`);
  const out = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const cr = r.chihou_races || {};
    const date = String(cr.race_date ?? '');
    const no = num(cr.race_no);
    const id = kbId(r.horse_id);
    if (!isDateStr(date) || date >= before || no === null || !id) continue;   // 当日・先の予定は過去走ではない
    const v = VENUE_BY_NAME.get(String(cr.track ?? '').trim());
    const prefix = v ? v.prefix : prefixFromRaceId(r.race_id);
    if (!prefix) continue;
    histPush(out, id, { date, venue: prefix, no, src: 'kb', row: r });
  }
  return out;
}

// 公式(nar_runs)。全15場を持つので、競馬ブックに無い川崎・浦和の走もここで埋まる(§19.5 の実測)。
// 公式に馬IDが無いので馬名で引く(同名異馬は 33/32,431 名・§10 #16 と同じ承知の上)
async function histNar(names, before) {
  // §54.3-a `trainer,trainer_area,birth_date` の3列は**転入初戦の判定だけ**に使う。
  // ⚠払うのは1行あたりこの3列ぶんだけ(クエリの本数は増えない)= 実測は DESIGN §54.3-a の記録へ
  const cols = 'horse_name,track,race_date,race_no,runner_number,finish,finish_note,time_sec,margin,last3f,popularity,carried_weight,weight_mark,body_weight,jockey,trainer,trainer_area,birth_date';
  const rows = await sbNar(`nar_runs?select=${cols}&horse_name=in.(${enc(quoteIn(names))})` +
    `&race_date=lt.${before}&order=race_date.desc,race_no.desc&limit=${HIST_NAR_LIMIT}`);
  const out = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const date = String(r.race_date ?? '');
    const no = num(r.race_no);
    const prefix = narPrefixOf(r.track);
    const nm = str(r.horse_name);
    if (!isDateStr(date) || no === null || !prefix || !nm) continue;
    histPush(out, nm, { date, venue: prefix, no, src: 'nar', row: r });
  }
  return out;
}

// 高知(keiba_horses)。lineage_login_code で引き、code が空の馬(name:)だけ馬名でも引く(§2.7)
async function histKochi(codes, names, before) {
  const cols = 'race_date,race_no,uma_ban,horse_name,lineage_login_code,chakujun,time,diff,agari3f,first3f,ninki,jockey,kinryo,weight,corner';
  const base = `keiba_horses?select=${cols}&baba_code=eq.${KOCHI_BABA}&race_date=lt.${enc(before)}` +
    `&order=race_date.desc&limit=${HIST_ROW_LIMIT}`;
  const qs = [];
  if (codes.length) qs.push(sb(`${base}&lineage_login_code=in.(${enc(quoteIn(codes))})`).catch(() => []));
  if (names.length) qs.push(sb(`${base}&horse_name=in.(${enc(quoteIn(names))})`).catch(() => []));
  const out = new Map();
  for (const rows of await Promise.all(qs)) {
    for (const h of (Array.isArray(rows) ? rows : [])) {
      const date = fromKochiDate(h.race_date);
      const no = num(h.race_no);
      const code = str(h.lineage_login_code);
      const nm = str(h.horse_name);
      // code のある行は code の馬・空の行は馬名の馬(horseKochi と同じ振り分け=同名異馬を混ぜない)
      const id = code ? `kochi:${code}` : (nm ? `name:${nm}` : null);
      if (!isDateStr(date) || no === null || !id) continue;
      histPush(out, id, { date, venue: 'kochi', no, src: 'kochi', row: h });
    }
  }
  return out;
}

// 5走に切った後の走にだけレース情報を足す。公式は 80 件ずつ or=(and(…))・高知は 100 件ずつ id=in.(…)
async function histInfo(picked) {
  const narKeys = new Map();
  const kochiIds = new Set();
  for (const d of picked) {
    const v = VENUE_BY_PREFIX.get(d.venue);
    if (v) narKeys.set(`${narTrackName(v)}/${d.date}/${d.no}`, { track: narTrackName(v), date: d.date, no: d.no });
    if (d.src === 'kochi') kochiIds.add(`race_${KOCHI_BABA}_${toKochiDate(d.date)}_${d.no}`);
  }
  const narInfo = new Map();
  const kochiInfo = new Map();
  await Promise.all([
    ...chunk([...narKeys.values()], 80).map(async (part) => {
      const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_date.eq.${k.date},race_no.eq.${k.no})`).join(',');
      // §38 R-1 `prize_yen`(本賞金の表)と `race_kind`(重賞か)を**同じ1本に足すだけ**=通信は増えない
      const rows = await sbNar('nar_races?select=track,race_date,race_no,distance_m,going,race_name,field_size,' +
        `prize_yen,race_kind&or=(${cond})`).catch(() => []);
      for (const r of (Array.isArray(rows) ? rows : [])) narInfo.set(narKey(r), r);
    }),
    ...chunk([...kochiIds], 100).map(async (part) => {
      const rows = await sb(`keiba_races?select=id,race_date,race_no,race_name,distance,race_class,track_cond` +
        `&baba_code=eq.${KOCHI_BABA}&id=in.(${enc(quoteIn(part))})`).catch(() => []);
      for (const r of (Array.isArray(rows) ? rows : [])) kochiInfo.set(String(r.id), r);
    }),
  ]);
  return { narInfo, kochiInfo };
}

// 中間形 → HorseRun。頭数(field_size)とばんえい旗は馬柱でしか使わないので、ここで足す
function histRun(d, narInfo, kochiInfo) {
  const v = VENUE_BY_PREFIX.get(d.venue);
  const ni = v ? narInfo.get(`${narTrackName(v)}/${d.date}/${d.no}`) : null;
  let run;
  if (d.src === 'kb') run = chihouRunFromJoined(d.row);
  else if (d.src === 'kochi') run = kochiRun(d.row, kochiInfo.get(`race_${KOCHI_BABA}_${toKochiDate(d.date)}_${d.no}`));
  else run = narRun(d.row, ni);
  run.heads = ni ? num(ni.field_size) : null;      // 頭数は公式にしか無い(2022-11 以降の走だけ入る)
  run.banei = !!(v && v.banei);
  // §38 R-1 条件クラスと本賞金の表。**公式(nar_races)のレース名から**取る=源が競馬ブックの走でも同じ規則で読める。
  // 公式に無い走(2022-11 より前)は両方 null=画面は何も出さない
  run.raceClass = ni ? raceClassOf(ni.race_name, str(ni.race_kind)) : null;
  run.prizeList = ni && Array.isArray(ni.prize_yen) ? ni.prize_yen : null;
  return run;
}

// 公式(nar:)は馬名そのものが ID・それ以外は出馬表の馬名で公式を引く
function histNameOf(id, names) {
  const m = /^nar:(.+)$/.exec(id);
  return m ? m[1] : (names.get(id) || null);
}

// §54.3-a 転入初戦 / 転厩初戦。**当日の所属**と**直前走の所属**を比べるだけ。
// ⛔鍵は (馬名, 生年月日)。同名で生年が違う馬が34名いて、2026年も2名が走っている(実測)。
//   名前だけで直前走を取ると、ばんえいのミナミジュウジセイ(2019年生・8/23 帯広)の直前走に
//   佐賀のミナミジュウジセイ(2022年生・8/22 佐賀)が入り「佐賀→ばんえい 転入」と誤って出る
// ⛔**直前走が無い馬(新馬・能検上がり)には出さない**=「変わった」と言えないため
// ⚠当日の所属が分かるのは**公式ソースの場**(nar_runs で出馬表を作る9場)だけ。
//   競馬ブック・高知の出馬表には所属の列が無いので、その場の馬には出ない(2026-08-29 実測)
function raceMoves(entries, nar) {
  const out = new Map();
  for (const e of entries) {
    const id = str(e.horseId);
    const nm = str(e.horseName);
    const area = str(e.trainerArea);
    const birth = str(e.birthDate);
    if (!id || !nm || !area || !birth || out.has(id)) continue;
    const list = nar.get(nm);
    if (!list || !list.length) continue;
    const prev = list.find((d) => str(d.row.birth_date) === birth);   // 新しい順に積んである
    if (!prev) continue;
    const fromArea = str(prev.row.trainer_area);
    const fromTrainer = str(prev.row.trainer);
    const trainer = str(e.trainer);
    let kind = null;
    if (fromArea && fromArea !== area) kind = 'in';
    else if (fromArea === area && fromTrainer && trainer && fromTrainer !== trainer) kind = 'stable';
    if (!kind) continue;
    out.set(id, {
      kind, fromArea, fromTrainer, toArea: area, toTrainer: trainer,
      date: prev.date, venue: prev.venue, no: prev.no,
    });
  }
  return out;
}

async function loadRaceHistory(race, entries) {
  const names = new Map();                     // horseId → 馬名
  const kbCodes = [], kochiCodes = [], kochiNames = [];
  for (const e of entries) {
    const id = str(e.horseId);
    if (!id || names.has(id)) continue;
    names.set(id, str(e.horseName));
    const m = /^(kb|kochi|name|nar):(.+)$/.exec(id);
    if (!m) continue;
    if (m[1] === 'kb') kbCodes.push(m[2]);
    else if (m[1] === 'kochi') kochiCodes.push(m[2]);
    else if (m[1] === 'name') kochiNames.push(m[2]);
  }
  const narNames = [...new Set([...names.keys()].map((id) => histNameOf(id, names)).filter(Boolean))];
  const [kb, nar, kochi] = await Promise.all([
    kbCodes.length ? histKb(kbCodes, race.date).catch(() => new Map()) : new Map(),
    narNames.length ? histNar(narNames, race.date).catch(() => new Map()) : new Map(),
    (kochiCodes.length || kochiNames.length)
      ? histKochi(kochiCodes, kochiNames, toKochiDate(race.date)).catch(() => new Map())
      : new Map(),
  ]);
  // 馬ごとに 競馬ブック → 高知 → 公式 の順に積んでから5走に切る(同じレースは先に積んだ源が残る)
  const picked = new Map();
  for (const id of names.keys()) {
    const cand = [];
    if (kb.has(id)) cand.push(...kb.get(id));
    if (kochi.has(id)) cand.push(...kochi.get(id));
    const nm = histNameOf(id, names);
    if (nm && nar.has(nm)) cand.push(...nar.get(nm));
    if (cand.length) picked.set(id, histCut(cand));
  }
  const { narInfo, kochiInfo } = await histInfo([...picked.values()].flat());
  const out = new Map();
  for (const [id, ds] of picked) out.set(id, ds.map((d) => histRun(d, narInfo, kochiInfo)));
  // §54.3-a 転入・転厩は**切る前の公式の走**(nar)から見る= 直前走が競馬ブック由来の回でも判定できる
  return { runs: out, moves: raceMoves(entries, nar) };
}

// ---------------------------------------------------------------- §38 R-1 クラスと賞金(自DBだけで出せるぶん)

// §38/調査書 §1.4 **その走で得た本賞金**。`prize_yen` は全15場で必ず5要素(実測)なので 6着以下は 0。
// ⚠**同着は按分**する: 「着順 n から 同着頭数ぶんの賞金を合計して 同着頭数で割る」。
// 実測(佐賀 2024-01-27 2R・1着同着2頭)= (350,000 + 112,000) ÷ 2 = **231,000** で公式と一致。
// ⚠同着の印(`margin='同着'`)は**2頭目にしか付かない**(実測)ので、同じ着順の行を数えるしかない
export function prizeForRun(prizeList, finish, tieCount) {
  const list = Array.isArray(prizeList) ? prizeList : null;
  const f = num(finish);
  if (!list || f === null || f < 1) return null;
  const tie = Math.max(1, num(tieCount) ?? 1);
  let sum = 0;
  for (let i = 0; i < tie; i += 1) sum += num(list[f - 1 + i]) ?? 0;    // 5要素より後ろは 0
  return Math.round(sum / tie);
}

// §38/調査書 §1.5 **そのレースの条件クラス**を race_name から取り出す。
// 型は場ごとにばらばら(門別 `Ｃ３－２`・盛岡 `Ｃ２三組`・浦和 `３歳六`・笠松 `Ｂ８組`・名古屋 `Ｃ１ｃ`・
// 園田 `Ｃ３二３歳以上`・高知 `Ａ－３`)なので、**協賛名の後ろが条件**という型だけを使い、
// 条件の頭から後ろを**そのまま**返す。⚠混合クラス(`Ｃ３－２Ｃ４－１`)も混ぜたまま返す=
// **馬のクラスを1つに決めない**(そのレースからは決まらない。調査書 §1.5 の壁1)。
// 実測: 15場×直近400レース=6,000件で 取れず **3件(0.05%)**(調査書の素朴な規則は13件)
const CLS_LATIN = /[A-Za-zＡ-Ｚａ-ｚ]/;
const CLS_LOWER = /[a-zａ-ｚ]/;
const CLS_AGE = /^[0-9０-９]歳/;
// クラス字のすぐ後ろに来るもの= 算用数字・漢数字・ダッシュ(`Ｃ４－２` `Ａ三組` `Ｃ－１`)
const CLS_AFTER = /^[0-9０-９一二三四五六七八九十\-－―‐−]/;
const CLS_UPPER = 'ABCDＡＢＣＤ';
// 語で決まるものは語を返す(クラス字より優先。`ＪＲＡ認定…２歳新馬` を `Ａ…` と読まないためでもある)
const CLS_WORDS = [['新馬', '新馬'], ['初出走', '新馬'], ['未勝利', '未勝利'], ['未受賞', '未受賞'], ['オープン', 'オープン']];
export function raceClassOf(raceName, raceKind) {
  const s = str(raceName) ? String(raceName).replace(/[\s\u3000]+/g, ' ').trim() : '';
  if (!s) return null;
  if (raceKind === '重賞' || raceKind === '準重賞') return null;      // 重賞はレース名そのものが身元
  for (const [w, label] of CLS_WORDS) if (s.includes(w)) return label;
  // ①クラス字(A〜D)を**文字列ぜんぶ**から探す。2回まわす:
  //   1周目= 後ろに 数字/漢数字/ダッシュ が続くもの(`Ｃ４－２`)。協賛名の中の字(`ＢＢ肥料`)を避けられる
  //   2周目= 続きを問わない(`ＡＢ混合`・`文月特別Ａ` のような字だけの型)
  // ⚠この順でないと『ホクレンＢＢ肥料賞Ｃ４－２』が『ＢＢ肥料賞Ｃ４－２』になる(実測 293/6000 件)
  for (let pass = 0; pass < 2; pass += 1) {
    for (let i = 0; i < s.length; i += 1) {
      if (!CLS_UPPER.includes(s[i])) continue;
      // ⚠ラテン語の中の A〜D は拾わない(ＪＲＡ・ＩＷＡＴＥ・Ａｉｂａ・ＮＯＲＴＨＥＲＮ ＢＲＥＷ)
      if (i > 0 && CLS_LATIN.test(s[i - 1])) continue;
      if (i + 1 < s.length && CLS_LOWER.test(s[i + 1])) continue;
      let j = i;
      while (j < s.length && CLS_LATIN.test(s[j]) && !CLS_LOWER.test(s[j])) j += 1;
      // 大文字が続く塊は **全部が A〜D のときだけ**クラス(`ＡＢ混合` は拾う・`ＢＲＥＷ` は拾わない)
      if ([...s.slice(i, j)].some((c) => !CLS_UPPER.includes(c))) continue;
      if (pass === 0 && !CLS_AFTER.test(s.slice(j))) continue;
      return s.slice(i).trim() || null;
    }
  }
  // ②クラス字が無い場合だけ「◯歳」を頭にする(2歳・3歳は組だけで編成される)。
  // ⚠この順でないと、協賛名の「◯歳」で切ってしまう
  // (実測 帯広ば『航太郎くん４歳お誕生日記念Ｂ４－３』→ ①が無いと『４歳お誕生日記念…』になる)
  for (let i = 0; i < s.length; i += 1) {
    if (CLS_AGE.test(s.slice(i))) return s.slice(i).trim() || null;
  }
  return null;
}

// ---------------------------------------------------------------- §38 1-F 門別の現在の級(公式発表)

// 門別だけ主催者が**級別表(PDF)で馬ごとの級と番組賞金を発表している**(§5.3 の Tier1)。
// `cloud/class_monbetsu.py` が nar_meta `monbetsu_class` に入れたものをそのまま読む(10分メモ・1本)。
// 返り値 = { asof, kai, fy, src, horses: Map(馬名 → {cls, grp, prize, tr, age, sex}) }。取れなければ null。
// ⚠**推定はしない**= 級別表に載っていない馬は Map に入れない(画面は何も出さない)。
// ⚠馬名で引く=同名馬は取り違えうる(§26.5 と同じ限界。血統登録番号での引き当ては §38 1-B の宿題)
export function getMonbetsuClass() {
  return memo('mclass:monbetsu', 10 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_meta?select=value&key=eq.monbetsu_class'); } catch { return null; }
    const v = Array.isArray(rows) && rows.length ? rows[0].value : null;
    const src = v && v.horses && typeof v.horses === 'object' ? v.horses : null;
    if (!src) return null;
    const horses = new Map();
    for (const name of Object.keys(src)) {
      const r = src[name] && typeof src[name] === 'object' ? src[name] : null;
      if (!r) continue;
      horses.set(name, {
        cls: str(r.cls),            // `Ｃ４－２` / 並記 `Ｃ３－２ Ｃ４－１` / 範囲 `Ｂ４－２～Ｃ３－１` / `未勝利` など
        grp: str(r.grp),            // 級が無い馬(2歳の一部)の**枠の題**
        prize: num(r.prize),        // 番組賞金(円・1万円の倍数=実測)。0 のこともある
        tr: str(r.tr),
        age: num(r.age),
        sex: str(r.sex),
      });
    }
    if (!horses.size) return null;
    return {
      horses,
      asof: isDateStr(v.asof) ? String(v.asof) : null,   // 級別表の基準日
      kai: num(v.kai),                                   // 第◯回
      fy: num(v.fy),
      src: str(v.src) || null,                           // 'official'=主催者の発表値(§5.3 の規律)
    };
  });
}

// ---------------------------------------------------------------- §38 2-A 大井の格付ポイント(公式)

// 南関東は主催者が**馬ごとの格付ポイント**を発表している(nankankeiba の uma_info)。
// §38 1-C(2026-09-04) 4場へ。chihou_meta の 65KB blob(大井だけ・他場PCの日次)をやめ、cloud/nankan_points.py が
//   毎朝育てる表 nar_nankan_points から**そのレースの出走馬ぶんだけ**馬名で引く(+1本・数KB・10分メモ)。
// 返り値 = { horses: Map(馬名 → {k, p, asof, b} | その配列) }。取れなければ null。
// ⚠**推定はしない**= 表に無い馬・格も点も無い馬(未格付・転入直後・抹消)は Map に入れない(画面は何も出さない)。
// ⚠**馬ごとの asof**(主催者の「◯月◯日現在」)を出す。
// ⚠馬名で引く=同名の馬が複数返ったら値を配列にし、画面側が出走馬の生年(nar_runs)で1頭に絞る(絞れなければ出さない)
export function getNankanPoints(race, entries) {
  const names = [...new Set((entries || []).map((e) => str(e && e.horseName)).filter(Boolean))];
  if (!names.length || !race) return Promise.resolve(null);
  return memo(`points:nankan/${race.venue}/${race.date}/${race.no}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_nankan_points?select=horse_name,kaku,points,asof,birth_date' +
        `&horse_name=in.(${names.map((n) => enc('"' + n + '"')).join(',')})&limit=100`);
    } catch { return null; }
    const horses = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const name = str(r.horse_name);
      const k = str(r.kaku);                           // 'C1' 型(半角)。⛔表から逆算せず、この値をそのまま出す
      const p = num(r.points);                         // 格付ポイント(整数)
      if (!name || (!k && p === null)) continue;
      const rec = { k, p, asof: isDateStr(r.asof) ? String(r.asof) : null,
        b: isDateStr(r.birth_date) ? String(r.birth_date) : null };
      const cur = horses.get(name);
      if (!cur) horses.set(name, rec);
      else if (Array.isArray(cur)) cur.push(rec);
      else horses.set(name, [cur, rec]);
    }
    if (!horses.size) return null;
    return { horses, built: null };
  });
}

// §38 1-B そのレースの出走馬の生年月日 Map(馬名 → 'YYYY-MM-DD')。nar_runs の birth_date(公式CSV・
// R-0 で投入済み)から。**大井の馬柱だけ**が ooi_points の同名馬突合に使う(+1本・10分メモ)。
// 行が無い/生年が無い馬は Map に入れない=突合できないときは従来どおり表示する(黙って消さない)
export function getNarBirths(race) {
  const v = venueByPrefix(race && race.venue);
  if (!v || !race.date || race.no == null) return Promise.resolve(null);
  return memo(`births:${race.venue}/${race.date}/${race.no}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_runs?select=horse_name,birth_date&track=eq.${enc(v.name)}` +
        `&race_date=eq.${race.date}&race_no=eq.${race.no}&limit=100`);
    } catch { return null; }
    const m = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const nm = str(r.horse_name), b = str(r.birth_date);
      if (nm && isDateStr(b)) m.set(nm, b);
    }
    return m.size ? m : null;
  });
}


// ---------------------------------------------------------------- §79 P2 馬ごとの公式値(台帳)

// そのレースの出走馬ぶんの**公式の収得賞金と直近の条件**を引く(nar_horse_codes → nar_horse_prize の2本・10分メモ)。
// → Map(馬名 → {code, prize, lastRun, lastCls, age, runs})。台帳に無い馬は入れない(=画面は何も出さない)。
// ⛔同定は **馬名+生年**。生年は出馬表の行(nar_runs.birth_date・select=* で既に来ている)から取るので
//   3本目は投げない。⛔生年が両方あって食い違う候補は外し、**1頭に絞れなければ出さない**(取り違えより無表示)。
// ⛔値は主催者(地方競馬全国協会)の写し= 「収得賞金」と名乗ってよい(§5.3。うちの合計は名乗れない)
export function getHorseLedger(race, entries) {
  const list = [...new Set((Array.isArray(entries) ? entries : [])
    .map((e) => str(e && e.horseName)).filter(Boolean))].sort();
  const v = venueByPrefix(race && race.venue);
  if (!v || !race || !isDateStr(race.date) || race.no == null || !list.length) return Promise.resolve(new Map());
  const birthOf = new Map();
  for (const e of entries) {
    const nm = str(e && e.horseName);
    const b = str(e && e.birthDate);
    if (nm && b) birthOf.set(nm, b);
  }
  return memo(`ledger:${race.venue}/${race.date}/${race.no}`, 10 * MIN, () => ledgerByName(list, birthOf));
}

// 台帳の引き当て(§79 P2/P4 共通・⛔同定の規則はここ1か所)。→ Map(馬名 → {code, prize, lastRun, lastCls, age, runs})。
// ⛔`in.()` は 80 件ずつに切る(数百頭で URL が長すぎて 400 になる=#365 と同じ手当て)。
// ⛔生年が両方あって食い違う候補を外し、**1頭に絞れなければ出さない**(取り違えより無表示)
async function ledgerByName(names, birthOf) {
  const out = new Map();
  const list = Array.isArray(names) ? names : [];
  if (!list.length) return out;
  const parts = await Promise.all(chunk(list, 80).map((part) =>
    sbNar(`nar_horse_codes?select=code,horse_name,birth_date&horse_name=in.(${enc(quoteIn(part))})`)
      .catch(() => [])));
  const codes = parts.flat();
  if (!codes.length) return out;
  const byName = new Map();
  for (const r of codes) {
    const nm = str(r.horse_name);
    const code = str(r.code);
    if (!nm || !code) continue;
    if (!byName.has(nm)) byName.set(nm, []);
    byName.get(nm).push({ code, birth: str(r.birth_date) });
  }
  const pick = new Map();                         // 馬名 → 血統登録番号(11桁)
  for (const [nm, cands] of byName) {
    const b = (birthOf && typeof birthOf.get === 'function' ? birthOf.get(nm) : null) || null;
    const ok = cands.filter((c) => !(b && c.birth && b !== c.birth));
    if (ok.length === 1) pick.set(nm, ok[0].code);
  }
  if (!pick.size) return out;
  const rows = (await Promise.all(chunk([...pick.values()], 80).map((part) =>
    sbNar('nar_horse_prize?select=code,horse_name,local_prize,last_run,last_cls,age,runs,calc' +
      `&code=in.(${enc(quoteIn(part))})`).catch(() => [])))).flat();
  const byCode = new Map();
  for (const r of rows) {
    const c = str(r.code);
    if (c) byCode.set(c, r);
  }
  for (const [nm, code] of pick) {
    const r = byCode.get(code);
    if (!r) continue;
    out.set(nm, {
      code,
      prize: num(r.local_prize),
      lastRun: str(r.last_run),
      lastCls: str(r.last_cls),
      age: num(r.age),
      runs: Array.isArray(r.runs) ? r.runs : [],
      // §79 P3 当サイトが要領から計算した番組賞金と線までの差(いまは高知だけ・他場は null)。
      // ⛔主催者の発表ではない= 画面は「当サイトの計算」と必ず断る
      calc: (r.calc && typeof r.calc === 'object') ? r.calc : null,
    });
  }
  return out;
}

// §79 P4 /class/:prefix の「今日走る馬から」。その場のその日の**出走馬を1本**で集めてから台帳を引く。
// → [{raceNo, umaban, horseName, prize, lastCls, lastRun}] を**収得賞金の多い順**。
// ⛔レースごとに getHorseLedger を回すと 12レース=24本になる。ここは日単位で 1 + 数本に収める。
// ⛔台帳に無い馬は入れない(推定しない)。30分メモ
export function getClassExamples(prefix, date) {
  const v = venueByPrefix(prefix);
  if (!v || !isDateStr(date)) return Promise.resolve([]);
  return memo(`clsex:${v.prefix}/${date}`, 30 * MIN, async () => {
    let runs;
    try {
      runs = await sbNar('nar_runs?select=race_no,runner_number,horse_name,birth_date' +
        `&track=eq.${enc(narTrackName(v))}&race_date=eq.${date}&order=race_no.asc&limit=1000`);
    } catch { return []; }
    const list = Array.isArray(runs) ? runs : [];
    if (!list.length) return [];
    const birthOf = new Map();
    const names = [];
    for (const r of list) {
      const nm = str(r.horse_name);
      if (!nm) continue;
      if (!names.includes(nm)) names.push(nm);
      const b = str(r.birth_date);
      if (b && !birthOf.has(nm)) birthOf.set(nm, b);
    }
    const led = await ledgerByName(names.sort(), birthOf);
    if (!led.size) return [];
    const out = [];
    const seen = new Set();
    for (const r of list) {
      const nm = str(r.horse_name);
      const rec = nm ? led.get(nm) : null;
      if (!rec || rec.prize === null || seen.has(nm)) continue;
      seen.add(nm);
      out.push({
        raceNo: num(r.race_no), umaban: num(r.runner_number), horseName: nm,
        prize: rec.prize, lastCls: rec.lastCls, lastRun: rec.lastRun,
        calc: rec.calc,                             // §79 P3 当サイトの計算(いまは高知だけ)
      });
    }
    return out.sort((a, b) => b.prize - a.prize || a.raceNo - b.raceNo || a.umaban - b.umaban);
  });
}

// §19.1 出走各馬の直近5走(馬柱)。Map(horseId → HorseRun[] 新しい順・最大5)。レース単位 10 分メモ。
// 過去走が取れない馬は Map に入れない(ページ側で「過去の出走記録がありません」を出す)
export function getRaceHistory(race, entries) {
  return histBundle(race, entries).then((b) => (b ? b.runs : new Map()));
}

// §54.3-a 転入初戦 / 転厩初戦。Map(horseId → {kind,fromArea,fromTrainer,toArea,toTrainer,date,venue,no})。
// ⛔過去走と**同じ memo**なので、両方呼んでも通信は1回ぶんのまま
export function getRaceMoves(race, entries) {
  return histBundle(race, entries).then((b) => (b ? b.moves : new Map()));
}

function histBundle(race, entries) {
  const r = race && typeof race === 'object' ? race : null;
  const list = Array.isArray(entries) ? entries : [];
  if (!r || !isDateStr(r.date) || !list.length) return Promise.resolve(null);
  return memo(`hist:${r.id}`, 10 * MIN, () => loadRaceHistory(r, list));
}

// ---------------------------------------------------------------- §23.2 その後成績(nar_race_level)

// 過去走のレースが「その後どう走られたか」。Map(Race.id → {n,w1,t3,top3n,top3w1})。
// 馬柱を開いたときだけ呼ぶ(1レース1〜2クエリ)。行が無いレース=その後の出走がまだ無い
// ⛔2026-08-28: 馬柱の「その後成績」廃止(ユーザー裁定)で**呼び出し元が無くなった**。
//   関数は残す=同じ集計を別の画面で使う判断が出たときのため。使うときは呼び出しを足すだけ。
export async function getRaceLevels(runs) {
  const list = Array.isArray(runs) ? runs : [];
  const keys = new Map();                     // Race.id → {track, date, no}
  for (const r of list) {
    if (!r || !r.raceId || keys.has(r.raceId) || !isDateStr(r.date) || r.raceNo === null) continue;
    const v = VENUE_BY_PREFIX.get(String(r.venue ?? ''));
    if (!v) continue;
    keys.set(r.raceId, { track: narTrackName(v), date: r.date, no: r.raceNo });
  }
  const out = new Map();
  if (!keys.size) return out;
  const byNar = new Map();                    // '公式場名/date/no' → Race.id
  for (const [id, k] of keys) byNar.set(`${k.track}/${k.date}/${k.no}`, id);
  await Promise.all(chunk([...keys.values()], 80).map(async (part) => {
    const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_date.eq.${k.date},race_no.eq.${k.no})`).join(',');
    let rows;
    try { rows = await sbNar(`nar_race_level?select=track,race_date,race_no,stats&or=(${cond})`); } catch { return; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const id = byNar.get(`${str(r.track) ?? ''}/${r.race_date}/${Number(r.race_no)}`);
      const s = r.stats && typeof r.stats === 'object' ? r.stats : null;
      if (!id || !s) continue;
      out.set(id, {
        n: num(s.n) ?? 0, w1: num(s.w1) ?? 0, t3: num(s.t3) ?? 0,
        top3n: num(s.top3n) ?? 0, top3w1: num(s.top3w1) ?? 0,
      });
    }
  }));
  return out;
}

// ---------------------------------------------------------------- §26.1 出走各馬の父(nar_horses)

// 馬柱を開いたときだけ呼ぶ(≤16頭=1クエリ)。Map(馬名 → 父)。父が無い馬は入れない。
// 公式に馬IDが無いので馬名で引く=同名異馬は混ざり得る(§10 #16・§26.5 の注記と同じ限界)。30分メモ
// §37.5-2 返り値 = Map(馬名 → {sire, dam, owner, breeder})。**select に3列足すだけ**なので通信は増えない(1本のまま)
export function getSires(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map(str).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve(new Map());
  return memo(`sires:${list.join(',')}`, 30 * MIN, async () => {
    const out = new Map();
    let rows;
    try {
      rows = await sbNar(`nar_horses?select=horse_name,sire,dam,owner,breeder&horse_name=in.(${enc(quoteIn(list))})`);
    } catch { return out; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const nm = str(r.horse_name);
      if (!nm || out.has(nm)) continue;
      const info = { sire: str(r.sire), dam: str(r.dam), owner: str(r.owner), breeder: str(r.breeder) };
      // 4つとも空の行は入れない(画面は「取れなかった」と同じ扱いにできる)
      if (info.sire || info.dam || info.owner || info.breeder) out.set(nm, info);
    }
    return out;
  });
}

// §54.5 まだ結果の出ていない回か。⛔画面が「不成立」と言い切らないための判断はここ1か所(§5.4)。
// 楽天の `auction_date` は**開催日**(木・日 12:00 開催)で、開催日の朝に出品一覧だけを取る回がある=
// その行は price null / sold false のまま残る(2026-09-02 実測: 9/3 第691回 62行・落札0・入札0)。
// ⛔器(auction_sales)は「未確定」と「不成立」を区別しないので、**日付で見分ける**しかない
const aucPending = (r) => !r.sold && str(r.auction_date) >= todayJST();

// §54.5 オークション取引(auction_sales)。馬名の束ね引き= getSires と同型(+1本・30分メモ)。行は新しい順。
// ⛔表には「画面に出してよい事実」しか無い(紹介文・落札者ニックネームは元から入っていない=読みに行かない)
export function getAuctionFlags(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map(str).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve(new Map());
  return memo(`auc:${list.join(',')}`, 30 * MIN, async () => {
    const out = new Map();
    // ⛔馬名を数百頭まとめて in.() に入れると URL が長すぎて 400 になる(/auction で実測)= 80頭ずつに切る
    const parts = await Promise.all(chunk(list, 80).map((part) =>
      sbNar('auction_sales?select=horse_name,source,item_id,auction_date,round_no,price,sold,tags,birth_date,url,category,runs_after,first_after,buyer,sire,dam' +
        `&horse_name=in.(${enc(quoteIn(part))})&order=auction_date.desc`).catch(() => [])));
    const rows = parts.flat();
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const nm = str(r.horse_name);
      if (!nm || !isDateStr(str(r.auction_date))) continue;
      if (!out.has(nm)) out.set(nm, []);
      out.get(nm).push({
        source: str(r.source), itemId: r.item_id, date: str(r.auction_date), round: r.round_no ?? null,
        price: r.price == null ? null : Number(r.price), sold: !!r.sold, pending: aucPending(r),
        tags: Array.isArray(r.tags) ? r.tags.map(str).filter(Boolean) : [],
        birth: isDateStr(str(r.birth_date)) ? str(r.birth_date) : null,
        url: str(r.url), category: str(r.category),
        buyer: str(r.buyer), sire: str(r.sire), dam: str(r.dam),      // §54.6 せり市場の行だけ入る
        // §54.5-c 落札後に何走したか(毎朝 psql が数える。null= 未計算)。0= 次の出走が「オークション後の初出走」
        runsAfter: r.runs_after == null ? null : Number(r.runs_after),
        firstAfter: isDateStr(str(r.first_after)) ? str(r.first_after) : null,
      });
    }
    return out;
  });
}

// §54.6 出典の言い方は**ここ1か所**(§5.4)。short= 馬柱の狭い所用。
//   rakuten/sat= オークション(日付あり)・jrha/hba= せり市場(⚠auction_date は月までの近似なので**年だけ**出す= aucWhen)
export function auctionSourceName(a, short) {
  const s = a && a.source;
  // §128b(2026-09-07) 会社名は閲覧者向け文言に出さない= 種類名だけ返す(値 source は不変)
  if (s === 'sat') return short ? 'せり市場(週末)' : 'せり市場の申告(週末)';
  if (s === 'jrha') return short ? 'セレクトセール' : 'セレクトセール(JRHA)';
  if (s === 'hba') return short ? '北海道市場' : '北海道市場(HBA)';
  return (short ? 'せり市場' : 'せり市場') + (a && a.round ? ' 第' + a.round + '回' : '');
}
export function auctionIsSale(a) { return !!a && (a.source === 'jrha' || a.source === 'hba'); }
export function aucWhen(a) {
  if (!a || !a.date) return '';
  return auctionIsSale(a) ? String(a.date).slice(0, 4) + '年' : String(a.date);
}

// §54.5 馬ページ用(1頭)。束ね引きの1馬版なので、馬柱で引いた直後ならメモに当たる
export function getHorseAuctions(name) {
  const nm = str(name);
  if (!nm) return Promise.resolve([]);
  return getAuctionFlags([nm]).then((m) => m.get(nm) || []);
}

// ---------------------------------------------------------------- §89 公表された疾病・競走事故履歴

const HEALTH_FROM = '2026-01-01';
const HEALTH_QUERY_MAX = 100;
const HEALTH_SHOW_MAX = 30;
const HEALTH_COLS = [
  'event_id', 'horse_name', 'birth_date', 'track', 'race_date', 'race_no', 'runner_number',
  'event_date', 'reported_date', 'stage', 'event_type', 'condition_group', 'race_status', 'detail',
  'restriction_from', 'restriction_through', 'source_kind', 'source_ref', 'source_url',
  'match_method', 'displayable',
].join(',');
const HEALTH_STAGES = new Set(['pre_race', 'in_race', 'post_race', 'auction_disclosure']);
const HEALTH_TYPES = new Set(['withdrawal', 'exclusion', 'did_not_finish', 'post_race_condition', 'auction_disclosure']);
const HEALTH_GROUPS = new Set(['disease', 'musculoskeletal', 'epistaxis', 'cardiac', 'accident', 'unspecified']);
const HEALTH_STATUSES = new Set(['出走取消', '競走除外', '競走中止']);
const HEALTH_SOURCES = new Set(['nar_pdf', 'rakuten', 'sat']);
const HEALTH_MATCHES = new Set(['race_key_name', 'name_birth', 'horse_code', 'auction_item']);
// §109 主催者公式(<slug>_official)。⛔host は adapter を足すたびにここへ 1 行(cloud/health_org_<slug>.py と対)
const HEALTH_ORG_HOSTS = {
  kochi_official: new Set(['www.keiba.or.jp']),
  ooi_official: new Set(['www.tokyocitykeiba.com']),      // §110
  saga_official: new Set(['www.sagakeiba.net']),          // §110
};
const HEALTH_SOURCE_HOSTS = {
  nar_pdf: new Set(['www.keiba.go.jp', 'keiba.go.jp']),
  rakuten: new Set(['auction.keiba.rakuten.co.jp']),
  sat: new Set(['www.sat-auction.jp']),
  ...HEALTH_ORG_HOSTS,
};
// 競走に結びつく出典= NAR の成績 PDF と主催者公式(§109)。オークションの申告と描き分けるための 1 か所
const isHealthRaceSource = (kind) => kind === 'nar_pdf' || Object.prototype.hasOwnProperty.call(HEALTH_ORG_HOSTS, kind);
const healthSourceOk = (kind) => HEALTH_SOURCES.has(kind) || isHealthRaceSource(kind);
// §109 NAR 成績 PDF と主催者公式が同じ出来事(場・日・R・馬番・種類)を持つとき、主催者の行を落として NAR を残す。
// ⛔配列をその場で削る(呼び出し側の並べ替えの前に呼ぶ)。鍵に raceStatus は入れない(同じ取消を言い方だけ違えて 2 行にしない)
function healthDropOrgDuplicates(list) {
  const narKeys = new Set(list.filter((e) => e.sourceKind === 'nar_pdf' && e.raceDate)
    .map((e) => `${e.venue}|${e.raceDate}|${e.raceNo}|${e.runnerNumber}|${e.eventType}`));
  if (!narKeys.size) return;
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const e = list[i];
    if (e.sourceKind !== 'nar_pdf' && isHealthRaceSource(e.sourceKind) &&
        narKeys.has(`${e.venue}|${e.raceDate}|${e.raceNo}|${e.runnerNumber}|${e.eventType}`)) list.splice(i, 1);
  }
}

function healthDate(v) {
  const d = str(v);
  return isDateStr(d) ? d : null;
}

// DB の source_url はサービス側でも固定するが、公開 bundle 側でも https + 許可済み3 host だけを通す。
function healthSourceUrl(kind, value) {
  const s = str(value);
  if (!s || !HEALTH_SOURCE_HOSTS[kind]) return null;
  let u;
  try { u = new URL(s); } catch { return null; }
  if (u.protocol !== 'https:' || !HEALTH_SOURCE_HOSTS[kind].has(u.hostname) || u.username || u.password) return null;
  return u.href;
}

function healthRaceKey(venue, date, raceNo, runnerNumber, raceStatus) {
  const no = num(raceNo), horseNo = num(runnerNumber);
  if (!VENUE_BY_PREFIX.has(String(venue ?? '')) || !isDateStr(date) ||
      !Number.isInteger(no) || no < 1 || !Number.isInteger(horseNo) || horseNo < 1) return null;
  return [venue, date, no, horseNo, raceStatus || ''].join('\0');
}

function coarseHealthStatus(note) {
  const kind = scratchKindOf(note);
  if (kind === '取消') return '出走取消';
  if (kind === '除外') return '競走除外';
  if (kind === '中止') return '競走中止';
  return null;                                     // 失格は疾病・事故履歴へ入れない
}

function healthNameCandidates(name) {
  // 原本と既存データの表記差は §85 と同じ NFKC + 空白除去まで。候補は契約上100件を超えない。
  return [...new Set([str(name), str(name) && String(name).normalize('NFKC'), normName(name)].filter(Boolean))]
    .slice(0, HEALTH_QUERY_MAX);
}

function healthRawRows(names) {
  const list = names.slice(0, HEALTH_QUERY_MAX);
  const key = list.join('\0');
  return memo(`health:${key}`, 30 * MIN, () => sbNar(
    `nar_horse_health_events?select=${HEALTH_COLS}&horse_name=in.(${enc(quoteIn(list))})` +
    `&reported_date=gte.${HEALTH_FROM}&displayable=eq.true&order=reported_date.desc,event_id.asc&limit=${HEALTH_QUERY_MAX}`
  ));
}

function healthSelectedEventId(value) {
  const id = typeof value === 'string' ? value : '';
  return /^[0-9a-f]{64}$/.test(id) ? id : null;
}

// §91.7 一覧から選んだ1件が通常100件の外でも拾う。event_id主キーだけを指定し、
// displayableを重ねる。返却行は後段で通常行とまったく同じ馬/birth/4鍵/item検証へ通す。
function healthRawSelectedEvent(eventId) {
  const id = healthSelectedEventId(eventId);
  if (!id) return Promise.resolve([]);
  return sbNar(`nar_horse_health_events?select=${HEALTH_COLS}&event_id=eq.${id}&displayable=eq.true&limit=1`)
    .then((rows) => (Array.isArray(rows) ? rows.filter((r) => str(r && r.event_id) === id).slice(0, 1) : []));
}

// §91 横断一覧。馬ページ用は「失敗時[]・最大100件」なので、一覧では別契約にする。
// URL由来の値はここでも固定allowlistへ戻し、DBへ任意のfilter文字列を渡さない。
export const HEALTH_INDEX_PAGE_SIZE = 40;
const HEALTH_INDEX_MAX_PAGE = 100;
const HEALTH_INDEX_PERIODS = new Set(['30', '90', 'year']);
const HEALTH_INDEX_SOURCE = { nar: 'nar_pdf', rakuten: 'rakuten', sat: 'sat', org: 'org' };   // org= 主催者公式(全 <slug>_official)

function healthIndexOptions(value) {
  const o = value && typeof value === 'object' ? value : {};
  const period = HEALTH_INDEX_PERIODS.has(String(o.period ?? '')) ? String(o.period) : '30';
  const source = Object.prototype.hasOwnProperty.call(HEALTH_INDEX_SOURCE, String(o.source ?? ''))
    ? String(o.source) : null;
  let type = HEALTH_TYPES.has(String(o.type ?? '')) ? String(o.type) : null;
  let venue = VENUE_BY_PREFIX.has(String(o.venue ?? '')) ? String(o.venue) : null;
  const rawPage = Number(o.page);
  const page = Number.isInteger(rawPage) && rawPage >= 1 && rawPage <= HEALTH_INDEX_MAX_PAGE ? rawPage : 1;
  if (source === 'rakuten' || source === 'sat') {
    venue = null;
    if (type && type !== 'auction_disclosure') type = null;
  } else if (source === 'nar' && type === 'auction_disclosure') {
    type = null;
  }
  if (type === 'auction_disclosure') venue = null;
  return { period, source, type, venue, page };
}

function healthIndexRow(r, st, from, through) {
  if (!r || typeof r !== 'object' || r.displayable !== true) return null;
  const eventId = str(r.event_id);
  const horseName = str(r.horse_name);
  const birthDate = healthDate(r.birth_date);
  const eventDate = healthDate(r.event_date);
  const reportedDate = healthDate(r.reported_date);
  const stage = str(r.stage);
  const eventType = str(r.event_type);
  const conditionGroup = str(r.condition_group);
  const raceStatus = str(r.race_status);
  const detail = str(r.detail);
  const restrictionFrom = healthDate(r.restriction_from);
  const restrictionThrough = healthDate(r.restriction_through);
  const sourceKind = str(r.source_kind);
  const sourceRef = str(r.source_ref);
  const matchMethod = str(r.match_method);
  if (!eventId || !/^[0-9a-f]{64}$/.test(eventId) || !horseName || horseName.length > 100 ||
      typeof r.horse_name !== 'string' || r.horse_name !== horseName ||
      (r.birth_date != null && !birthDate) || (r.event_date != null && !eventDate) ||
      !reportedDate || reportedDate < from || reportedDate > through ||
      !HEALTH_STAGES.has(stage) || !HEALTH_TYPES.has(eventType) || !HEALTH_GROUPS.has(conditionGroup) ||
      (raceStatus !== null && !HEALTH_STATUSES.has(raceStatus)) || !detail || detail.length > 1000 ||
      (r.restriction_from != null && !restrictionFrom) || (r.restriction_through != null && !restrictionThrough) ||
      (restrictionFrom && restrictionThrough && restrictionThrough < restrictionFrom) ||
      !healthSourceOk(sourceKind) || !sourceRef || !HEALTH_MATCHES.has(matchMethod)) return null;
  if (st.source === 'org' ? !Object.prototype.hasOwnProperty.call(HEALTH_ORG_HOSTS, sourceKind)
    : (st.source && sourceKind !== HEALTH_INDEX_SOURCE[st.source])) return null;
  if (st.type && eventType !== st.type) return null;

  let venue = null, raceDate = null, raceNo = null, runnerNumber = null, raceId = null;
  if (isHealthRaceSource(sourceKind)) {
    const track = str(r.track);
    venue = narPrefixOf(track);
    const v = venue && VENUE_BY_PREFIX.get(venue);
    raceDate = healthDate(r.race_date);
    raceNo = num(r.race_no);
    runnerNumber = num(r.runner_number);
    // 主催者公式(§109)は記事が翌日に出ることがあるので reportedDate = raceDate は課さない。source_ref は <slug>/YYYYMMDD
    const refOk = sourceKind === 'nar_pdf'
      ? (reportedDate === raceDate && sourceRef === `${raceDate.replace(/-/g, '')}/${v.babaCode}`)
      : (raceDate !== null && sourceRef === `${sourceKind.replace(/_official$/, '')}/${raceDate.replace(/-/g, '')}`);
    if (!v || track !== narTrackName(v) || matchMethod !== 'race_key_name' || !raceDate ||
        !Number.isInteger(raceNo) || raceNo < 1 || raceNo > 12 ||
        !Number.isInteger(runnerNumber) || runnerNumber < 1 || runnerNumber > 99 ||
        !refOk || stage === 'auction_disclosure' || eventType === 'auction_disclosure' ||
        (st.venue && venue !== st.venue)) return null;
    raceId = `${venue}/${raceDate}/${raceNo}`;
  } else {
    if (matchMethod !== 'auction_item' || sourceRef !== `${sourceKind}/${sourceRef.split('/')[1] || ''}` ||
        !new RegExp(`^${sourceKind}/\\d+$`).test(sourceRef) || stage !== 'auction_disclosure' ||
        eventType !== 'auction_disclosure' || raceStatus !== null || r.track != null || r.race_date != null ||
        r.race_no != null || r.runner_number != null || st.venue) return null;
  }
  return {
    eventId, horseName, birthDate, eventDate, reportedDate, stage, eventType, conditionGroup, raceStatus,
    detail, restrictionFrom, restrictionThrough, sourceKind, sourceRef,
    sourceUrl: healthSourceUrl(sourceKind, r.source_url), venue, raceDate, raceNo, runnerNumber, raceId,
    horseId: isHealthRaceSource(sourceKind) && birthDate ? `narb:${birthDate}:${horseName}` : null,
  };
}

async function healthIndexAuctionLinks(rows) {
  const targets = rows.filter((r) => !isHealthRaceSource(r.sourceKind) && r.birthDate);
  const names = [...new Set(targets.map((r) => r.horseName))].slice(0, HEALTH_INDEX_PAGE_SIZE);
  if (!names.length) return;
  let codes;
  try {
    codes = await sbNar('nar_horse_codes?select=code,horse_name,birth_date' +
      `&horse_name=in.(${enc(quoteIn(names))})&order=horse_name.asc,birth_date.asc,code.asc&limit=1000`);
  } catch { return; }
  // limit到達は後続候補があるか不明なので、一意と断定しない。
  if (!Array.isArray(codes) || codes.length >= 1000) return;
  const byIdentity = new Map();
  for (const r of codes) {
    const name = str(r && r.horse_name), birth = healthDate(r && r.birth_date), code = str(r && r.code);
    if (!name || !birth || !/^\d{11}$/.test(code || '') || r.horse_name !== name) continue;
    const key = name + '\0' + birth;
    if (!byIdentity.has(key)) byIdentity.set(key, new Set());
    byIdentity.get(key).add(code);
  }
  for (const r of targets) {
    const codesForHorse = byIdentity.get(r.horseName + '\0' + r.birthDate);
    if (codesForHorse && codesForHorse.size === 1) r.horseId = `narb:${r.birthDate}:${r.horseName}`;
  }
}

export async function getHealthIndex(options) {
  const st = healthIndexOptions(options);
  const through = todayJST();
  const from = st.period === 'year' ? HEALTH_FROM : addDays(through, st.period === '90' ? -89 : -29);
  const query = [
    `nar_horse_health_events?select=${HEALTH_COLS}`,
    `reported_date=gte.${from}`,
    `reported_date=lte.${through}`,
    'displayable=eq.true',
  ];
  if (st.source === 'org') query.push('source_kind=like.*_official');
  else if (st.source) query.push(`source_kind=eq.${HEALTH_INDEX_SOURCE[st.source]}`);
  if (st.type) query.push(`event_type=eq.${st.type}`);
  if (st.venue) query.push(`track=eq.${enc(narTrackName(VENUE_BY_PREFIX.get(st.venue)))}`);
  query.push('order=reported_date.desc,event_id.asc');
  query.push(`limit=${HEALTH_INDEX_PAGE_SIZE + 1}`);
  query.push(`offset=${(st.page - 1) * HEALTH_INDEX_PAGE_SIZE}`);
  const raw = await sbNar(query.join('&'));
  if (!Array.isArray(raw)) throw makeError('other', null, 'invalid health response');
  const seen = new Set();
  const rows = [];
  for (const item of raw.slice(0, HEALTH_INDEX_PAGE_SIZE)) {
    const row = healthIndexRow(item, st, from, through);
    if (!row || seen.has(row.eventId)) continue;
    seen.add(row.eventId);
    rows.push(row);
  }
  healthDropOrgDuplicates(rows);          // §109 同じ頁の中の NAR/主催者の重複は NAR を残す
  rows.sort((a, b) => b.reportedDate.localeCompare(a.reportedDate) || a.eventId.localeCompare(b.eventId));
  await healthIndexAuctionLinks(rows);
  return {
    rows, filters: st, from, through, page: st.page,
    hasPrev: st.page > 1,
    hasNext: st.page < HEALTH_INDEX_MAX_PAGE && raw.length > HEALTH_INDEX_PAGE_SIZE,
    capped: st.page === HEALTH_INDEX_MAX_PAGE && raw.length > HEALTH_INDEX_PAGE_SIZE,
    pageSize: HEALTH_INDEX_PAGE_SIZE,
  };
}

// 馬ページ用。auctions には既存 getHorseAuctions の Promise も渡せる。
// 先に healthRawRows() を開始してから両方を待つため、オークションと通常の疾病anon readは並列。
// 選択eventが通常100件の外にある時だけ、主キー指定のanon readをもう1本補う。
// 健康表の取得が失敗したときは coarse fallback も含めて空にし、「取れなかった」を「履歴なし」に見せない。
export function getHorseHealthEvents(horse, auctions, selectedEventId) {
  const h = horse && typeof horse === 'object' ? horse : null;
  const names = healthNameCandidates(h && h.name);
  if (!h || !names.length || !Array.isArray(h.runs)) return Promise.resolve([]);
  const selected = healthSelectedEventId(selectedEventId);

  const rowsPromise = healthRawRows(names);         // auctions の完了を待たず、ここで +1 本を開始
  const auctionsPromise = Promise.resolve(auctions).catch(() => []);
  return Promise.all([rowsPromise, auctionsPromise]).then(async ([raw, auctionRows]) => {
    const sourceRows = Array.isArray(raw) ? raw.slice() : [];
    // 通常100件内にあれば追加通信0。外にある時だけ主キー1件を補い、補助取得の失敗は通常履歴を壊さない。
    if (selected && !sourceRows.some((r) => str(r && r.event_id) === selected)) {
      try { sourceRows.push(...await healthRawSelectedEvent(selected)); } catch { /* 選択行が出ないだけ */ }
    }
    const runs = h.runs;
    const idKind = String(h.id ?? '').split(':', 1)[0];
    const birth = healthDate(h.birth);
    const runKeys = new Set();
    for (const r of runs) {
      const key = healthRaceKey(r && r.venue, r && r.date, r && r.raceNo, r && r.umaban, null);
      if (key) runKeys.add(key);
    }

    // オークション由来は、既存 getHorseAuctions が返した当該 item だけを許す。
    const auctionRefs = new Map();
    for (const a of (Array.isArray(auctionRows) ? auctionRows : [])) {
      const source = str(a && a.source);
      const item = String(a && a.itemId != null ? a.itemId : '');
      const aBirth = healthDate(a && a.birth);
      if (!/^(rakuten|sat)$/.test(source || '') || !/^\d+$/.test(item)) continue;
      if (!birth || !aBirth || birth !== aBirth) continue;
      auctionRefs.set(`${source}/${item}`, { source, birth: aBirth });
    }

    const detailed = [];
    const seen = new Set();
    for (const r of sourceRows) {
      const eventId = str(r && r.event_id);
      const sourceKind = str(r && r.source_kind);
      const sourceRef = str(r && r.source_ref);
      const matchMethod = str(r && r.match_method);
      const reportedDate = healthDate(r && r.reported_date);
      const rowBirth = healthDate(r && r.birth_date);
      const stage = str(r && r.stage);
      const eventType = str(r && r.event_type);
      const conditionGroup = str(r && r.condition_group);
      const detail = str(r && r.detail);
      if (!eventId || seen.has(eventId) || !sameHorseStrict(r && r.horse_name, h.name) ||
          !reportedDate || reportedDate < HEALTH_FROM || !detail || detail.length > 1000 ||
          !healthSourceOk(sourceKind) || !HEALTH_MATCHES.has(matchMethod) ||
          !HEALTH_STAGES.has(stage) || !HEALTH_TYPES.has(eventType) || !HEALTH_GROUPS.has(conditionGroup) ||
          r.displayable !== true) continue;

      const raceStatus = str(r.race_status);
      if (raceStatus !== null && !HEALTH_STATUSES.has(raceStatus)) continue;
      const eventDate = healthDate(r.event_date);
      const restrictionFrom = healthDate(r.restriction_from);
      const restrictionThrough = healthDate(r.restriction_through);
      if ((r.event_date != null && !eventDate) || (r.restriction_from != null && !restrictionFrom) ||
          (r.restriction_through != null && !restrictionThrough) ||
          (restrictionFrom && restrictionThrough && restrictionThrough < restrictionFrom)) continue;

      let venue = null, raceDate = null, raceNo = null, runnerNumber = null, raceId = null;
      if (isHealthRaceSource(sourceKind)) {
        if (matchMethod !== 'race_key_name') continue;
        venue = narPrefixOf(r.track);
        raceDate = healthDate(r.race_date);
        raceNo = num(r.race_no);
        runnerNumber = num(r.runner_number);
        const key = healthRaceKey(venue, raceDate, raceNo, runnerNumber, null);
        if (!key) continue;
        // nar: は生年月日、IDを持つ既存系は表示中の走歴4鍵で別馬を排除する。
        if (idKind === 'nar' || idKind === 'narb') {
          if (!birth || rowBirth !== birth || (idKind === 'narb' && !runKeys.has(key))) continue;
        } else if (!runKeys.has(key)) continue;
        raceId = `${venue}/${raceDate}/${raceNo}`;
      } else {
        if (matchMethod !== 'auction_item') continue;
        const item = auctionRefs.get(sourceRef);
        if (!item || item.source !== sourceKind) continue;
        // page・health event・既存 auction item の生年月日が3点ともあり、完全一致するときだけ表示する。
        if (!birth || !rowBirth || !item.birth || rowBirth !== birth || rowBirth !== item.birth) continue;
      }

      seen.add(eventId);
      detailed.push({
        eventId, eventDate, reportedDate, stage, eventType, conditionGroup, raceStatus,
        detail, restrictionFrom, restrictionThrough, sourceKind, sourceRef,
        sourceUrl: healthSourceUrl(sourceKind, r.source_url),
        venue, raceDate, raceNo, runnerNumber, raceId,
      });
    }

    // §109 同じ競走・同じ馬・同じ種類が NAR 成績 PDF と主催者公式の両方にあれば NAR の行を残す(重複を 2 行出さない)
    healthDropOrgDuplicates(detailed);
    // 詳細と同じ競走状態の粗い finish_note は出さない。鼻出血等 race_status=null の詳細とは別事象なので残す。
    const detailedRaceStatuses = new Set(detailed.filter((e) => isHealthRaceSource(e.sourceKind) && e.raceStatus)
      .map((e) => healthRaceKey(e.venue, e.raceDate, e.raceNo, e.runnerNumber, e.raceStatus)).filter(Boolean));
    const fallback = [];
    for (const r of runs) {
      const raceStatus = coarseHealthStatus(r && r.finishNote);
      if (!raceStatus || !isDateStr(r && r.date) || r.date < HEALTH_FROM) continue;
      // nar: は馬名取得なので、元の nar_runs に保持した生年月日まで一致させる。
      // kb:/kochi: は既存の馬IDで束ねた runs のスコープをそのまま使う。
      if ((idKind === 'nar' || idKind === 'narb') && (!birth || healthDate(r && r.horseBirth) !== birth)) continue;
      const key = healthRaceKey(r.venue, r.date, r.raceNo, r.umaban, raceStatus);
      if (!key || detailedRaceStatuses.has(key) || seen.has(`coarse:${key}`)) continue;
      seen.add(`coarse:${key}`);
      fallback.push({
        eventId: `coarse:${key}`, eventDate: r.date, reportedDate: r.date,
        stage: raceStatus === '競走中止' ? 'in_race' : 'pre_race',
        eventType: raceStatus === '出走取消' ? 'withdrawal' :
          (raceStatus === '競走除外' ? 'exclusion' : 'did_not_finish'),
        conditionGroup: 'unspecified', raceStatus, detail: null,
        restrictionFrom: null, restrictionThrough: null,
        sourceKind: 'nar_pdf', sourceRef: null, sourceUrl: null,
        venue: r.venue, raceDate: r.date, raceNo: Number(r.raceNo), runnerNumber: Number(r.umaban),
        raceId: r.raceId || `${r.venue}/${r.date}/${Number(r.raceNo)}`,
      });
    }

    const out = detailed.concat(fallback).sort((a, b) => {
      const ad = a.eventDate || a.reportedDate, bd = b.eventDate || b.reportedDate;
      return String(bd).localeCompare(String(ad)) || String(b.reportedDate).localeCompare(String(a.reportedDate)) ||
        String(a.eventId).localeCompare(String(b.eventId));
    });
    // 一覧で選んだ正規eventは、通常の時系列順では31件目以降でも先頭に固定して30件へ残す。
    if (selected) {
      const at = out.findIndex((e) => e.eventId === selected);
      if (at > 0) out.unshift(...out.splice(at, 1));
    }
    return out.slice(0, HEALTH_SHOW_MAX);
  }).catch(() => []);
}

// §54.5 /auction ハブ用= since 以降の取引(新しい順・同日は高い順)。最大 limit 行・10分メモ。
// 未来の日付(今週の出品・まだ価格0)も入る=ページ側で「これから」と「落札済み」に分ける
export function getAuctionRecent(since, limit = 400) {
  if (!isDateStr(since)) return Promise.resolve([]);
  const n = Math.max(1, Math.min(1000, Number(limit) || 400));
  return memo(`aucrecent:${since}:${n}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('auction_sales?select=horse_name,display_name,source,item_id,auction_date,round_no,price,sold,tags,' +
        `category,sex,age,url,runs_after,first_after&auction_date=gte.${since}&source=in.(rakuten,sat)&order=auction_date.desc,price.desc.nullslast&limit=${n}`);   // §54.6 せり市場は「最近の落札」に混ぜない(年単位の近似日で数千行が並ぶ)
    } catch { return []; }
    return (Array.isArray(rows) ? rows : []).filter((r) => isDateStr(str(r.auction_date))).map((r) => ({
      name: str(r.horse_name), display: str(r.display_name) || str(r.horse_name),
      source: str(r.source), itemId: r.item_id, date: str(r.auction_date), round: r.round_no ?? null,
      price: r.price == null ? null : Number(r.price), sold: !!r.sold, pending: aucPending(r),
      tags: Array.isArray(r.tags) ? r.tags.map(str).filter(Boolean) : [],
      category: str(r.category), sex: str(r.sex), age: r.age == null ? null : Number(r.age), url: str(r.url),
      runsAfter: r.runs_after == null ? null : Number(r.runs_after),
      firstAfter: isDateStr(str(r.first_after)) ? str(r.first_after) : null,
    }));
  });
}

// §106 B オークションの検索(馬名・取引額)。⛔`auction_sales` 1本・**検索したときだけ**引く。
// ⚠列は getAuctionRecent と同じ= 落札カードの描き方を 2 つに増やさない。
// ⛔並びは 新しい順 / 高い順 / 安い順 の 3 つだけ(画面の選択肢と 1 対 1)。5分メモ。
const AUC_ORDERS = {
  date: 'auction_date.desc,price.desc.nullslast',
  high: 'price.desc.nullslast,auction_date.desc',
  low: 'price.asc.nullslast,auction_date.desc',
};
export const AUCTION_SEARCH_MAX = 200;
// §113 出どころの組。⛔auctionIsSale() と同じ分け方(1 か所で決める・§5.4)。
// §116a せり市場(jrha・hba)を探す経路は画面ごと消えたので、ここも**オークションだけ**にする=
//   ⛔誰も通らない道を残さない。せり市場の取引は馬ページ(getHorseAuctions)が今までどおり出す
const AUC_AUCTION_SOURCES = ['rakuten', 'sat'];

export function searchAuction(opts) {
  const o = opts && typeof opts === 'object' ? opts : {};
  const kw = cleanKw(o.kw);
  const lo = num(o.priceMin);
  const hi = num(o.priceMax);
  const ord = AUC_ORDERS[String(o.order || 'date')] ? String(o.order || 'date') : 'date';
  const sources = AUC_AUCTION_SOURCES;
  const n = Math.max(1, Math.min(AUCTION_SEARCH_MAX, Number(o.limit) || AUCTION_SEARCH_MAX));
  // ⚠1文字だと当たりすぎる(2文字から)。条件が1つも無ければ引かない= null を返す
  const hasKw = kw.length >= 2;
  if (!hasKw && lo === null && hi === null) return Promise.resolve(null);
  const key = `aucsearch:auc:${hasKw ? kw : ''}:${lo}:${hi}:${ord}:${n}`;
  return memo(key, 5 * MIN, async () => {
    const parts = ['select=horse_name,display_name,source,item_id,auction_date,round_no,price,sold,tags,' +
      'category,sex,age,url,runs_after,first_after'];
    if (hasKw) parts.push(`or=(horse_name.ilike.*${enc(kw)}*,display_name.ilike.*${enc(kw)}*)`);
    if (lo !== null) parts.push(`price=gte.${lo}`);
    if (hi !== null) parts.push(`price=lte.${hi}`);
    parts.push(`source=in.(${enc(quoteIn(sources))})`);
    parts.push(`order=${AUC_ORDERS[ord]}`, `limit=${n}`);
    let rows;
    try { rows = await sbNar(`auction_sales?${parts.join('&')}`); } catch { return null; }
    return (Array.isArray(rows) ? rows : []).filter((r) => isDateStr(str(r.auction_date))).map((r) => ({
      name: str(r.horse_name), display: str(r.display_name) || str(r.horse_name),
      source: str(r.source), itemId: r.item_id, date: str(r.auction_date), round: r.round_no ?? null,
      price: r.price == null ? null : Number(r.price), sold: !!r.sold, pending: aucPending(r),
      tags: Array.isArray(r.tags) ? r.tags.map(str).filter(Boolean) : [],
      category: str(r.category), sex: str(r.sex), age: r.age == null ? null : Number(r.age), url: str(r.url),
      runsAfter: r.runs_after == null ? null : Number(r.runs_after),
      firstAfter: isDateStr(str(r.first_after)) ? str(r.first_after) : null,
    }));
  });
}

// §37.4-4/§37.5-1 能検索引の1件を**再生できる形**に直す。判断はここ1か所に集める(§26.4 と同じ作法)。
// 実測の内訳: YouTube 動画 4,494 / 映像なし 2,093 / mp4 902 / プレイリスト 72。
// ⚠ID の形まで見る(§32d で 13 文字に切れたプレイリストIDが実在した)
const YT_ONE = /(?:youtu\.be\/|[?&]v=)([A-Za-z0-9_-]{11})(?:[^A-Za-z0-9_-]|$)/;
const YT_LIST = /[?&]list=([A-Za-z0-9_-]{18,})/;

// §33.7-6/§33.7-7 R2 に置いたレース別クリップ。**offsets の確定している日だけ**切ってあり、
// その日の索引エントリには頭出し秒 `s` が入っている=**`r` と `s` の両方があること**が対象の印。
// ⚠**存在確認をしない**: connect-src に r2.dev が無いので fetch/HEAD は本番だけ静かに落ちる。
// 代わりに <video> の error で主催者側の映像(YouTube の頭出し)へ差し替える(ui.nokenPlayerError)
const CLIP_BASE = 'https://pub-6567e3477a0d451093923a95ba6c2e3c.r2.dev/noken-clip/';
const CLIP_DISTRICTS = ['kawasaki', 'urawa', 'funabashi', 'saga', 'banei'];

export function nokenVideoSrc(rec) {
  const alt = nokenExternalSrc(rec);                    // 主催者側(門別の直mp4・YouTube・プレイリスト)
  const d = str(rec && rec.district);
  const r = num(rec && rec.raceNo);
  const date = rec && isDateStr(rec.date) ? String(rec.date) : null;
  if (date && r !== null && r > 0 && num(rec && rec.start) !== null && CLIP_DISTRICTS.includes(d)) {
    // クリップはレースの頭から始まるので頭出しの指定は要らない
    return { kind: 'mp4', src: `${CLIP_BASE}${d}/${date}_r${r}.mp4`, clip: true, fallback: alt };
  }
  return alt;
}

// 主催者側の映像。⚠対象外(門別の直mp4・岩手のレース動画・他地区)は今までどおりここだけを通る
function nokenExternalSrc(rec) {
  const v = str(rec && rec.video);
  if (!v) return null;
  if (/\.mp4(\?|$)/i.test(v)) return { kind: 'mp4', src: v };
  const one = YT_ONE.exec(v);
  if (one) {
    const at = rec.start != null && rec.start >= 0 ? '?start=' + Math.floor(rec.start) : '';
    return { kind: 'yt', src: 'https://www.youtube.com/embed/' + one[1] + at };
  }
  const list = YT_LIST.exec(v);
  // プレイリストはレース単位に分かれていない=通し映像が開く(画面はその断りを添える)
  if (list) return { kind: 'yt', src: 'https://www.youtube.com/embed/videoseries?list=' + list[1], whole: true };
  return null;
}

// ---------------------------------------------------------------- §41-A 公式のコーナー通過(#121 の開栓)

// `nar_races.corners` = コーナーごとの**全馬の並び**([{name:'３角', order:'2,11,(4,6,12),10-(7,9)'}, …])。
// 記法= 数字は馬番・`( )` は横に並んだ馬(**先頭の順位を共有**)・`-` `=` は差の大きさ(順位の付き方は変えない)。
// 返り値 = Map(馬番 → '3-3-5')。⚠読めない並びは**そのコーナーごと捨てる**(推定しない)。
// ⚠ばんえいは corners がそもそも空(実測 8月120レースすべて)=200m 直線でコーナーが無い
export function passingFromCorners(corners) {
  const per = [];
  for (const c of (Array.isArray(corners) ? corners : [])) {
    const m = cornerRanks(c && c.order);
    if (m) per.push(m);
  }
  const out = new Map();
  if (!per.length) return out;
  const all = new Set();
  for (const m of per) for (const u of m.keys()) all.add(u);
  for (const u of all) {
    // 途中で消える馬(競走中止)はいるところまで。並びに出ない馬は Map に入れない
    const v = per.filter((m) => m.has(u)).map((m) => String(m.get(u)));
    if (v.length) out.set(u, v.join('-'));
  }
  return out;
}

// 1コーナーぶんの並び → Map(馬番 → 順位)。同着(並走)は先頭の順位を共有し、次はその頭数ぶん飛ぶ
// ⛔§99: 同じ規則が cloud/tenkai.py `corner_ranks()` にもある。tests/tenkai_corner_test.mjs と
//   `cloud/tenkai.py --selftest` が**同じ5例**を通す(どちらかを直したら両方直すこと)
export function cornerRanks(order) {
  const s = String(order ?? '').trim();
  if (!s) return null;
  const out = new Map();
  let rank = 1;
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === ',' || ch === '-' || ch === '=' || ch === ' ' || ch === '　') { i += 1; continue; }
    if (ch === '(') {
      const end = s.indexOf(')', i);
      if (end < 0) return null;                       // 閉じない=読めない
      const nums = s.slice(i + 1, end).split(',').map((x) => Number(String(x).trim()));
      if (!nums.length || nums.some((n) => !Number.isInteger(n) || n <= 0)) return null;
      for (const n of nums) if (!out.has(n)) out.set(n, rank);
      rank += nums.length;
      i = end + 1;
      continue;
    }
    const m = /^\d+/.exec(s.slice(i));
    if (!m) return null;                              // 知らない字=読めない(推定しない)
    const n = Number(m[0]);
    if (!out.has(n)) out.set(n, rank);
    rank += 1;
    i += m[0].length;
  }
  return out.size ? out : null;
}

// 画面に原文をそのまま出すための整形(値の無い行は落とす)
function cornerList(v) {
  return (Array.isArray(v) ? v : [])
    .map((c) => ({ name: str(c && c.name), order: str(c && c.order) }))
    .filter((c) => c.order);
}

// ---------------------------------------------------------------- §26.2 過去走の勝ち馬(nar_runs)

// 馬柱の過去走セルに出す勝ち馬・2着馬。Map(Race.id → {win, second})。
// 馬柱を開いたときだけ呼ぶ(過去走のレースは最大 16頭×5走 だが重複が多く、80キーずつで実測1クエリ)。
// 公式に結果が入っていないレースは Map に入れない=セルには何も足さない(§10 #39)
// ⛔2026-08-28: 馬柱の「勝ち馬」廃止(ユーザー裁定)で**呼び出し元が無くなった**。
//   ⚠関数は消さない= 返り値の `ties`(同着頭数)が §38 R-1(#133)の按分賞金の資産=賞金台帳の続きで使うため
//   (prizeForRun(prizeList, finish, tieCount) の第3引数)。復活させるときはここを呼ぶ。
export async function getRaceWinners(runs) {
  const list = Array.isArray(runs) ? runs : [];
  const keys = new Map();                     // Race.id → {track, date, no}
  for (const r of list) {
    if (!r || !r.raceId || keys.has(r.raceId) || !isDateStr(r.date) || r.raceNo === null) continue;
    const v = VENUE_BY_PREFIX.get(String(r.venue ?? ''));
    if (!v) continue;
    keys.set(r.raceId, { track: narTrackName(v), date: r.date, no: r.raceNo });
  }
  const out = new Map();
  if (!keys.size) return out;
  const byNar = new Map();                    // '公式場名/date/no' → Race.id
  for (const [id, k] of keys) byNar.set(`${k.track}/${k.date}/${k.no}`, id);
  await Promise.all(chunk([...keys.values()], 80).map(async (part) => {
    const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_date.eq.${k.date},race_no.eq.${k.no})`).join(',');
    let rows;
    try {
      // §38 R-1 賞金の按分に**同着頭数**が要るので 5着までに広げる(本賞金が付くのは5着まで=prize_yen が5要素)。
      // 引く本数は変わらない(80レースずつの同じ1本。実測 80レースで 400 行前後)
      rows = await sbNar('nar_runs?select=track,race_date,race_no,horse_name,finish' +
        `&finish=lte.5&or=(${cond})&limit=1000`);
    } catch { return; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const id = byNar.get(`${str(r.track) ?? ''}/${r.race_date}/${Number(r.race_no)}`);
      const nm = str(r.horse_name);
      const f = num(r.finish);
      if (!id || !nm || f === null || f < 1 || f > 5) continue;
      const cur = out.get(id) || { win: null, second: null, ties: new Map() };
      if (!cur.ties) cur.ties = new Map();
      cur.ties.set(f, (cur.ties.get(f) || 0) + 1);       // 同じ着順の行数=同着頭数
      // 同着は先に来た1頭だけ出す(公式紙面も勝ち馬は1頭しか刷らない)
      if (f === 1) { if (!cur.win) cur.win = nm; } else if (f === 2 && !cur.second) cur.second = nm;
      out.set(id, cur);
    }
  }));
  return out;
}

// ---------------------------------------------------------------- §43 騎乗馬一覧(/rides/:venue/:date)

// §80 A ② 調教師名の書き方は源で違う(公式 '米川' / 競馬ブック '門米川'= 場の頭文字つき)。
// 対応表(js/trainer-map.js)で公式表記へ寄せ、寄せられた名前だけ official=true にする。
// ⛔頭文字を機械で削らない(実測 2026-09-03 門別: '門柳沢' の公式は '柳澤好'= 字も長さも違う)。
// ⛔表に無い名前は**書いてあるまま**返して official=false(別人のページへ飛ばさないため。
//   規則は §26.4・race.js の trainerCell と同じ。判断はこの1か所に置く=§5.4)
function trainerOf(raw, isOfficial) {
  const s = str(raw);
  if (!s) return { name: null, official: false };
  if (isOfficial) return { name: s, official: true };
  const m = Object.prototype.hasOwnProperty.call(TRAINER_MAP, s) ? TRAINER_MAP[s] : null;
  return m ? { name: m, official: true } : { name: s, official: false };
}

// #411 騎手も源で表記が違う(競馬ブック '藤田凌駕' / 公式 '藤田駕')。対応表(js/jockey-map.js・§26.4 と同じ作り方)に
//   あれば公式表記へ。無ければ書いてあるまま(騎手はほぼ同じ字なので official 旗は持たない=ui.personLink と同じ規則)
function jockeyOf(raw) {
  const s = str(raw);
  if (!s) return null;
  return Object.prototype.hasOwnProperty.call(JOCKEY_MAP, s) ? JOCKEY_MAP[s] : s;
}

// 公式の1日1本で足りる列(騎乗一覧に要るものだけ=payload を小さく保つ)。
// §80 A ② 調教師の軸のために trainer / trainer_area を足した(行数は変わらない=**本数も増えない**)
const NAR_RIDE_COLS = 'race_no,runner_number,gate,horse_name,jockey,trainer,trainer_area,popularity,finish,finish_note,margin';

// その日その場の**騎乗**をぜんぶ返す。返り値 = { venue, date, races, rides } / その場の開催が無ければ null。
// ⚠その日の器(loadDay)は結果一覧・レースページと**同じ memo** を使い回すので、増えるのは
// 出走各馬を引く **1〜2本**だけ(公式の場=1本・競馬ブックの場=出馬表と結果で2本・高知=1本・
// アーカイブの日=**0本**。§13.2B-2 で公式から足したレースが混じる日だけ +1本)
export function getVenueRides(prefix, date) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v || !isDateStr(date)) return Promise.resolve(null);
  return memo(`rides:${v.prefix}:${date}`, ttlForDay(date), async () => {
    const day = await loadDay(date);
    // §71 P1-2(Codex監査): ⛔出走馬ソースの失敗を `.catch(() => [])` で0件へ変換しない=
    // ここに**この関数ローカルの失敗**を積み、最後に day.failed と合わせて partial に反映する。
    // 消費側は「fulfilled かつ partial=false」のときだけ「確認できた」と扱える
    const localFailed = [];
    const caught = (name) => (e) => { localFailed.push(name); return []; };
    const races = day.races.filter((r) => r.venue === v.prefix);
    // §67 B5 直し ⛔**null をやめて空の器を返す**= 印を持てるようにする(`ttlForDay` も効くようになる)。
    //   ⚠呼び出し側の `!d || !d.races.length` はそのまま効くので画面の分岐は変わらない
    if (!races.length) {
      return withPartial({ venue: { ...v }, date, races: [], rides: [] }, day.failed || []);
    }
    const byNo = new Map(races.map((r) => [r.no, r]));
    const rides = [];
    const add = (race, e, finish, note) => {
      if (!race || !e || !Number.isFinite(e.umaban)) return;
      // §80 A ② 調教師は源によって書き方が違うので、ここで公式表記へ寄せてから積む
      const tr = trainerOf(e.trainer, !!e.trainerOfficial);
      rides.push({
        no: race.no,
        raceId: race.id,
        waku: e.waku ?? null,
        umaban: e.umaban,
        horseName: e.horseName || '',
        horseId: e.horseId ?? null,
        jockey: jockeyOf(e.jockey),            // #411 騎手も公式表記へ寄せてから積む(一覧の束ねと /jockey/ リンクのため)
        trainer: tr.name,                      // 表示名(寄せた後)。無ければ null
        trainerOfficial: tr.official,          // true のときだけ /trainer/<名前> へリンクしてよい
        trainerArea: str(e.trainerArea),       // §38 R-0 '北海道' など。公式の行にしか無い
        ninki: e.ninki ?? null,
        odds: e.odds ?? null,
        finish: finish ?? null,
        finishNote: note ?? null,
        scratched: !!e.scratched,
      });
    };

    // ① アーカイブの日は出馬表も結果も**もう手元にある**(通信ゼロ)
    const arc = day.archived.filter((a) => a.race.venue === v.prefix);
    const arcIds = new Set(arc.map((a) => a.race.id));
    for (const a of arc) {
      const fin = new Map((a.results || []).map((x) => [x.umaban, x]));
      for (const e of (a.entries || [])) {
        const r = fin.get(e.umaban) || null;
        // §28.1b アーカイブの中身は競馬ブック表記('川加藤誠')= 公式扱いにしない(対応表を通す)
        add(a.race, e, r ? r.finish : null, r ? r.finishNote : null);
      }
    }
    const rest = races.filter((r) => !arcIds.has(r.id));

    if (rest.length && v.prefix === 'kochi') {
      // 高知は keiba_horses(自前DB)が出馬表と結果を兼ねている。
      // ⚠**結果の空いている日がある**(実測 2026-08-02 は ninki/odds/chakujun が全行 空)ので、
      // 公式(nar_runs)を同時に引いて埋める= レースページの §41-B と同じ作法。単勝は自前DBにしか無い
      // §80 A ② 高知の自前DBにも調教師列がある(公式と同じ略称。2026-09-03 実測)
      const cols = 'race_no,waku_ban,uma_ban,horse_name,lineage_login_code,jockey,trainer,ninki,odds,chakujun';
      const [rows, nar] = await Promise.all([
        sb(`keiba_horses?select=${cols}&baba_code=eq.${KOCHI_BABA}` +
          `&race_date=eq.${enc(toKochiDate(date))}`).catch(caught(SOURCES.kochi)),
        date < NAR_FROM ? Promise.resolve([])
          : sbNar(`nar_runs?select=${NAR_RIDE_COLS}&track=eq.${enc(narTrackName(v))}` +
            `&race_date=eq.${date}&limit=1000`).catch(caught(SOURCES.nar)),
      ]);
      const narBy = new Map();
      for (const x of (Array.isArray(nar) ? nar : [])) {
        const no = num(x.race_no);
        if (no !== null) narBy.set(`${no}/${Number(x.runner_number)}`, x);
      }
      const seen = new Set();
      for (const h of (Array.isArray(rows) ? rows : [])) {
        const no = num(h.race_no);
        const uma = Number(h.uma_ban);
        const key = `${no}/${uma}`;
        seen.add(key);
        const x = narBy.get(key) || null;
        const n = x ? narNote(x) : null;
        const f = kochiFinish(h);
        const offFin = (x && (!n || n.note === null)) ? narFinish(x) : null;
        add(byNo.get(no), {
          waku: num(h.waku_ban),
          umaban: uma,
          horseName: str(h.horse_name) || (x ? str(x.horse_name) : '') || '',
          horseId: kochiHorseId(h),
          jockey: str(h.jockey) || (x ? str(x.jockey) : null),
          trainer: str(h.trainer) || (x ? str(x.trainer) : null),
          trainerOfficial: true,               // 高知の自前DBも公式と同じ略称(§26.4 officialTrainer と同じ扱い)
          trainerArea: x ? str(x.trainer_area) : null,
          ninki: num(h.ninki) ?? (x ? num(x.popularity) : null),
          odds: num(h.odds),
          scratched: f.scratched || !!(n && isScratched(n.note)),   // §80 A 取消・除外だけ(中止・失格は走った=§50)
        }, f.finish ?? offFin, f.note || (n ? n.note : null));
      }
      // 自前DBに行が無い(公式にだけある)馬も落とさない
      for (const [key, x] of narBy) {
        if (seen.has(key)) continue;
        const no = num(x.race_no);
        const n = narNote(x);
        add(byNo.get(no), {
          waku: num(x.gate),
          umaban: Number(x.runner_number),
          horseName: str(x.horse_name) || '',
          horseId: narHorseId(x),
          jockey: str(x.jockey),
          trainer: str(x.trainer),
          trainerOfficial: true,
          trainerArea: str(x.trainer_area),
          ninki: num(x.popularity),
          odds: null,
          scratched: isScratched(n.note),              // §80 A 取消・除外だけ(中止・失格は走った=§50)
        }, n.note !== null ? null : narFinish(x), n.note);
      }
    } else if (rest.length) {
      // 公式が主の場はまるごと1本。競馬ブックが主の場でも §13.2B-2 で足したレースはこちら
      const narRaces = v.supported === 'nar' ? rest : rest.filter((r) => r.sourceKind === 'nar');
      const kbRaces = v.supported === 'nar' ? [] : rest.filter((r) => r.sourceKind !== 'nar');
      await Promise.all([
        (async () => {
          if (!narRaces.length || date < NAR_FROM) return;
          const ok = new Set(narRaces.map((r) => r.no));
          const rows = await sbNar(`nar_runs?select=${NAR_RIDE_COLS}&track=eq.${enc(narTrackName(v))}` +
            `&race_date=eq.${date}&limit=1000`).catch(caught(SOURCES.nar));
          for (const x of (Array.isArray(rows) ? rows : [])) {
            const no = num(x.race_no);
            if (no === null || !ok.has(no)) continue;
            const n = narNote(x);
            add(byNo.get(no), {
              waku: num(x.gate),
              umaban: Number(x.runner_number),
              horseName: str(x.horse_name) || '',
              horseId: narHorseId(x),
              jockey: str(x.jockey),
              trainer: str(x.trainer),
              trainerOfficial: true,                   // 公式(nar_runs)の表記そのまま
              trainerArea: str(x.trainer_area),
              ninki: num(x.popularity),
              odds: null,                              // 単勝は nar_runs に無い(§13.2C と同じ)
              scratched: isScratched(n.note),          // §80 A 取消・除外だけ(中止・失格は走った=§50)
            }, n.note !== null ? null : narFinish(x), n.note);
          }
        })(),
        (async () => {
          if (!kbRaces.length) return;
          const rids = kbRaces.map((r) => r.sourceId).join(',');
          const [ents, res] = await Promise.all([
            sb('chihou_entries?select=race_id,waku,umaban,horse_name,horse_id,jockey,trainer,status,pop,win_odds' +
              `&race_id=in.(${rids})&limit=1000`).catch(caught(SOURCES.chihou)),
            sb('chihou_results?select=race_id,umaban,horse_name,horse_id,jockey,trainer,finish,finish_note,pop,win_odds' +
              `&race_id=in.(${rids})&limit=1000`).catch(caught(SOURCES.chihou)),
          ]);
          const byRid = new Map(kbRaces.map((r) => [String(r.sourceId), r]));
          const resBy = new Map();
          for (const x of (Array.isArray(res) ? res : [])) resBy.set(`${x.race_id}/${Number(x.umaban)}`, x);
          const seen = new Set();
          for (const e of (Array.isArray(ents) ? ents : [])) {
            const key = `${e.race_id}/${Number(e.umaban)}`;
            const r = resBy.get(key) || null;
            seen.add(key);
            // §25.1 と同じ作法= 人気・単勝・騎手は**結果行を優先**(出馬表行は当日ぶんが空のことがある)
            add(byRid.get(String(e.race_id)), {
              waku: num(e.waku),
              umaban: Number(e.umaban),
              horseName: str(e.horse_name) || (r ? str(r.horse_name) : '') || '',
              horseId: kbId(e.horse_id) || (r ? kbId(r.horse_id) : null),
              jockey: (r && str(r.jockey)) || str(e.jockey),
              trainer: (r && str(r.trainer)) || str(e.trainer),   // 競馬ブック表記= 対応表を通す
              ninki: (r && num(r.pop)) ?? num(e.pop),
              odds: (r && num(r.win_odds)) ?? num(e.win_odds),
              scratched: isScratched(r && r.finish_note) || isScratched(e.status),   // §80 A 取消・除外だけ(§50)
            }, r ? num(r.finish) : null, r ? str(r.finish_note) : (scratchKindOf(e.status) !== null ? str(e.status) : null));
          }
          // ⚠出馬表に無いのに結果にはいる行(取込の前後で起きる)も落とさない
          for (const [key, x] of resBy) {
            if (seen.has(key)) continue;
            add(byRid.get(String(x.race_id)), {
              waku: null,
              umaban: Number(x.umaban),
              horseName: str(x.horse_name) || '',
              horseId: kbId(x.horse_id),
              jockey: str(x.jockey),
              trainer: str(x.trainer),
              ninki: num(x.pop),
              odds: num(x.win_odds),
              scratched: isScratched(x.finish_note),   // §80 A 取消・除外だけ(§50)
            }, num(x.finish), str(x.finish_note));
          }
        })(),
      ]);
    }

    rides.sort((a, b) => a.no - b.no || a.umaban - b.umaban);
    return withPartial({
      venue: { ...v },
      date,
      races: races.map((r) => ({
        // §80 A ① date は phaseOf/nextRace が「今日か」を見るのに要る(器に足すだけ=通信は増えない)
        id: r.id, no: r.no, name: r.name, status: r.status, postTime: r.postTime, date: r.date,
        distance: r.distance, going: r.going,
      })).sort((a, b) => a.no - b.no),
      rides,
    }, [...new Set([...(day.failed || []), ...localFailed])]);
  });
}

// §80 A ② その日の出走馬の馬主(nar_horses)。馬主一覧の軸のときだけ呼ぶ=
// 騎手・調教師の一覧では通信は増えない。返り値 = Map(馬名 → 馬主名)。
// ⛔馬名を数百頭まとめて in.() に入れると URL が長すぎて 400 になる(#365)= **80頭ずつ**に切る。
// ⛔公式に馬IDが無いので馬名で引く= 同名異馬があり得る。行が割れた馬は Map に入れない
//   (呼び出し側が「不明」に倒す。⛔どちらかに推定しない)。30分メモ
export function getHorseOwners(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map(str).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve(new Map());
  return memo(`owners:${list.join(',')}`, 30 * MIN, async () => {
    const parts = await Promise.all(chunk(list, 80).map((part) =>
      sbNar(`nar_horses?select=horse_name,owner&horse_name=in.(${enc(quoteIn(part))})`).catch(() => [])));
    const seen = new Map();                    // 馬名 → Set(馬主名)
    for (const r of parts.flat()) {
      const nm = str(r.horse_name);
      if (!nm) continue;
      if (!seen.has(nm)) seen.set(nm, new Set());
      seen.get(nm).add(str(r.owner) || '');
    }
    const out = new Map();
    for (const [nm, set] of seen) {
      if (set.size !== 1) continue;            // 同名で馬主が割れた= 断らずに落とす(画面は「不明」)
      const owner = [...set][0];
      if (owner) out.set(nm, owner);
    }
    return out;
  });
}

// ---------------------------------------------------------------- §87 A 売上の遡り・平均(ビュー3本)

// ⛔ビューの中身(nar_sales_daily / nar_sales_venue_avg / nar_sales_hourly)は pipeline 側にある。
//   ここは **anon で select するだけ**。1票=100円に直すのは画面(sales.js の yen/man)の役目。
// ⛔`nar_sales_daily` は全部で 1,020 行(2026-09-03 実測)= **範囲で絞らないと 1000 行の上限を踏む**。
//   1回の範囲は 60 日まで(実測 61日=167行。1日の場数は最大5・平均2.8)
const SALES_SPAN_MAX = 60;

// 日ごとの売上(場の内訳つき)。返り値 = [{date, races, netVotes, venues:[{prefix,name,races,netVotes}]}] の**日付降順**。
// from〜to は 60 日に丸める(⛔上限を踏まないため)。10分メモ
export function getSalesDays(fromDate, toDate) {
  if (!isDateStr(fromDate) || !isDateStr(toDate) || toDate < fromDate) return Promise.resolve([]);
  const end = toDate > addDays(fromDate, SALES_SPAN_MAX) ? addDays(fromDate, SALES_SPAN_MAX) : toDate;
  return memo(`saledays:${fromDate}:${end}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_sales_daily?select=track,race_date,races,net_votes' +
        `&race_date=gte.${fromDate}&race_date=lte.${end}&order=race_date.desc&limit=1000`);
    } catch { return []; }
    return salesDayList(rows);
  });
}

// その場の売上が入っている日(前後の送り用)。⛔**場は開催の間隔が長い**ので範囲で切らない
//   (実測 2026-09-03: 船橋 294日・盛岡 167日・水沢 67日 あく)= その場の全部を1本で取る(≤400行)。1時間メモ
export function getSalesVenueDates(prefix) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v) return Promise.resolve([]);
  return memo(`saledates:${v.prefix}`, 60 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_sales_daily?select=race_date' +
        `&track=eq.${enc(narTrackName(v))}&order=race_date.asc&limit=1000`);
    } catch { return []; }
    return [...new Set((Array.isArray(rows) ? rows : []).map((r) => str(r.race_date)).filter(isDateStr))].sort();
  });
}

// 場ごとの平均(直近1年)。返り値 = [{prefix, name, days, races, netVotes, avgRaceVotes, avgDayVotes, since, until}]。
// ⚠並べ替えは画面の役目(ここは取れた順のまま返す)。1時間メモ・14〜15行
export function getSalesVenueAvg() {
  return memo('saleavg', 60 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_sales_venue_avg?select=track,days,races,net_votes,avg_race_votes,avg_day_votes,since,until&limit=100');
    } catch { return []; }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);                  // '帯広ば' もここで吸収する
      const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
      if (!v) continue;
      out.push({
        prefix: v.prefix,
        name: v.name,
        days: num(r.days) ?? 0,
        races: num(r.races) ?? 0,
        netVotes: num(r.net_votes) ?? 0,
        avgRaceVotes: num(r.avg_race_votes),
        avgDayVotes: num(r.avg_day_votes),
        since: isDateStr(r.since) ? String(r.since) : null,
        until: isDateStr(r.until) ? String(r.until) : null,
      });
    }
    return out;
  });
}

// その場の時間帯ごとの1レース平均(直近1年)。返り値 = [{slot, label, races, avgRaceVotes}] を時刻順。
// slot = 発走時刻の30分枠の開始分(930 なら 15:30〜15:59)。⛔時刻が読めないレースは元から入っていない。
// ⚠**平均を出すかどうかの線引きは画面**(races が少ない枠)。ここは取れた行をそのまま返す。1時間メモ
export function getSalesHourly(prefix) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v) return Promise.resolve([]);
  return memo(`salehour:${v.prefix}`, 60 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_sales_hourly?select=slot_min,races,avg_race_votes' +
        `&track=eq.${enc(narTrackName(v))}&order=slot_min.asc&limit=100`);
    } catch { return []; }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const slot = num(r.slot_min);
      if (slot === null || slot < 0 || slot >= 24 * 60) continue;
      out.push({
        slot,
        label: `${pad2(Math.floor(slot / 60))}:${pad2(slot % 60)}`,
        races: num(r.races) ?? 0,
        avgRaceVotes: num(r.avg_race_votes),
      });
    }
    return out;
  });
}

// nar_sales_daily の行 → 日ごとの器(日付降順・場は VENUES の並び)
function salesDayList(rows) {
  const by = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const date = str(r.race_date);
    const prefix = narPrefixOf(r.track);
    const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
    if (!isDateStr(date) || !v) continue;
    if (!by.has(date)) by.set(date, new Map());
    by.get(date).set(v.prefix, {
      prefix: v.prefix, name: v.name, races: num(r.races) ?? 0, netVotes: num(r.net_votes) ?? 0,
    });
  }
  const out = [];
  for (const [date, m] of by) {
    const venues = VENUES.map((v) => m.get(v.prefix)).filter(Boolean);
    out.push({
      date,
      venues,
      races: venues.reduce((a, x) => a + x.races, 0),
      netVotes: venues.reduce((a, x) => a + x.netVotes, 0),
    });
  }
  return out.sort((a, b) => b.date.localeCompare(a.date));
}

// ---------------------------------------------------------------- #131 走歴に公式の通過を付ける(§40-4)

// 馬ページの脚質を**画面の結果表と同じ値**(公式 `nar_races.corners`)で数えるための束。
// 返り値 = Map(Race.id → Map(馬番 → '3-3-5'))。走歴が出そろってから**1回だけ**呼ぶ。
// ⚠corners の無い走(ばんえい=コーナーが無い・2022-11 より前)は Map に入れない=
// 呼ぶ側が競馬ブックの `passing` に落ちる(§41-B と同じ型)。80レースずつ=ふつうの馬は1本
export async function getRunCorners(runs) {
  const list = Array.isArray(runs) ? runs : [];
  const keys = new Map();                     // Race.id → {track, date, no}
  for (const r of list) {
    if (!r || !r.raceId || keys.has(r.raceId) || !isDateStr(r.date) || r.raceNo === null) continue;
    if (r.date < NAR_FROM) continue;           // 公式の記録が始まる前=引くだけ無駄(§28.1b)
    const v = VENUE_BY_PREFIX.get(String(r.venue ?? ''));
    if (!v) continue;
    keys.set(r.raceId, { track: narTrackName(v), date: r.date, no: r.raceNo });
  }
  const out = new Map();
  if (!keys.size) return out;
  const byNar = new Map();                    // '公式場名/date/no' → Race.id
  for (const [id, k] of keys) byNar.set(`${k.track}/${k.date}/${k.no}`, id);
  await Promise.all(chunk([...keys.values()], 80).map(async (part) => {
    const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_date.eq.${k.date},race_no.eq.${k.no})`).join(',');
    let rows;
    try {
      rows = await sbNar(`nar_races?select=track,race_date,race_no,corners&or=(${cond})&limit=1000`);
    } catch { return; }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const id = byNar.get(`${str(r.track) ?? ''}/${r.race_date}/${Number(r.race_no)}`);
      if (!id) continue;
      const pass = passingFromCorners(cornerList(r.corners));
      if (pass.size) out.set(id, pass);
    }
  }));
  return out;
}

// ---------------------------------------------------------------- §119b 馬具(nar_kb_runs)

// 提供データ(成績の「馬装具」欄)を 1 行 1 馬 1 走で持つ表。§119a の実測で、行があるのは
// **6 場だけ**(門別・大井・船橋・川崎・浦和・園田)。他の 9 場は出どころに欄が無い= 行が来ない。
// ⛔`blinker` 列は常に null(出馬表のブリンカ欄が空)なので**読まない**= 馬具は `gear` だけが出どころ。
// ⛔場名 → prefix の表は作らない= venueByName() を通す(§5.4。園田は sonoda)。
export const KB_GEAR_TRACKS = ['monbetsu', 'ooi', 'funabashi', 'kawasaki', 'urawa', 'sonoda'];
export const KB_BLINKER = 'ブリンカー着用';
const KB_NAME_CHUNK = 100;
const KB_COLS = 'track,race_date,race_no,umaban,horse_name,gear,first3f,avg_f,pace,kimete,start_note';

// 馬名の束 → Map(馬名 → 行[]・新しい順)。100 頭ずつ・30 分メモ。
// ⚠**馬名だけでは同名の別馬を分けられない**ので、使う側は必ず kbRunFor() で
//   「その馬の走(場・日付・R が一致)」に当たる行だけを取ること。
export function getKbRunsForNames(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map(str).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve(new Map());
  return memo(`kbruns:${list.join(',')}`, 30 * MIN, async () => {
    const parts = await Promise.all(chunk(list, KB_NAME_CHUNK).map((part) =>
      sbNar(`nar_kb_runs?select=${KB_COLS}&horse_name=in.(${enc(quoteIn(part))})` +
        '&order=race_date.desc&limit=2000').catch(() => [])));
    const out = new Map();
    for (const r of parts.flat()) {
      const name = str(r.horse_name);
      const v = venueByName(str(r.track));
      if (!name || !v || !isDateStr(str(r.race_date))) continue;
      if (!out.has(name)) out.set(name, []);
      out.get(name).push({
        venue: v.prefix, date: str(r.race_date), raceNo: num(r.race_no), umaban: num(r.umaban),
        gear: str(r.gear), first3f: num(r.first3f), avgF: num(r.avg_f),
        pace: str(r.pace), kimete: str(r.kimete), startNote: str(r.start_note),
      });
    }
    return out;
  });
}

// その走(走歴の1行)に当たる馬具の行。⛔馬名だけで拾わない= 場・日付・R が全部そろって初めて同じ走と見なす
export function kbRunFor(rows, run) {
  if (!Array.isArray(rows) || !run || !run.venue || !isDateStr(str(run.date))) return null;
  const no = num(run.raceNo);
  if (no === null) return null;
  return rows.find((x) => x.venue === run.venue && x.date === run.date && x.raceNo === no) || null;
}

// §119b/§119c 馬具の短い字。「B」= ブリンカー着用 /「SR」= シャドーロール着用 / それ以外は先頭2字。
// ⛔語を足さない(判定・価値判断は書かない)。正式の字は呼ぶ側が title に残す
export function kbGearShort(gear) {
  const t = str(gear) || '';
  if (!t) return '';
  if (t.indexOf('ブリンカー') === 0) return 'B';
  if (t.indexOf('シャドーロール') === 0) return 'SR';
  return t.slice(0, 2);
}

// 併用は空白等で並んでいる(実測「ブリンカー着用 シャドーロール着用」)。1つずつに割る
export function kbGearItems(gear) {
  return (str(gear) || '').split(/[\s、,・/]+/).filter(Boolean);
}

// まとめの区分の名。1つならその字のまま・2つ以上は短い字を + でつなぐ(「B+SR」)
export function kbGearLabel(gear) {
  const items = kbGearItems(gear);
  if (!items.length) return '';
  return items.length === 1 ? items[0] : items.map(kbGearShort).join('+');
}

// §119b 馬具の「変化」。⛔**隣り合う2走の両方に行があるとき**だけ出す
//   (間に 6 場以外の走が挟まる= 片方に行が無い → 何も出さない。⛔推定しない)。
// ⛔ブリンカー以外は「初◯」「◯外す」にしない= 語を増やさず「変更」だけ。
export function kbGearChange(prevRow, row) {
  if (!prevRow || !row) return '';
  const a = str(prevRow.gear) || '';
  const b = str(row.gear) || '';
  if (a === b) return '';
  if (!a && b === KB_BLINKER) return '初B';
  if (a === KB_BLINKER && !b) return 'B外す';
  return '変更';
}

// 馬柱用= 出走各馬の**馬名で引いた行の配列**(新しい順)。返り値 = Map(horseId → 行[])。
// ⛔通信は getKbRunsForNames の1本だけ。⚠どの走に当たるかは呼ぶ側が kbRunFor(場・日付・R の3つ一致)で
//   決める= **同名の別馬を混ぜない**。§119c で「前走1行」から配列に変えた(過去走の枠ごとに出すため)
export async function getKbRunsForRace(race, entries) {
  const list = Array.isArray(entries) ? entries : [];
  const out = new Map();
  if (!list.length) return out;
  const rows = await getKbRunsForNames(list.map((e) => e && e.horseName));
  for (const e of list) out.set(e.horseId, rows.get(str(e.horseName)) || []);
  return out;
}

// ---------------------------------------------------------------- §120 高知のレース後コメント(主催者公式)

// 高知県競馬組合の公式サイトが結果の後に出している記事(騎手の話を聞き書きしたもの)を、
// cloud/kochi_comments.py が `nar_race_comments` に 1 頭 1 行で入れている。
// ⛔当サイトの言葉ではない= 画面は**原文のまま**出し、出どころの断りを添える(言い換え・要約をしない)。
// ⛔行があるのは高知だけ= 他の 14 場では**引かない**(通信を増やさない)。
export const KOCHI_COMMENT_TRACK = '高知';
const KC_COLS = 'race_date,race_no,umaban,horse_name,jockey,comment,source_url';
const KC_NAME_CHUNK = 100;

function kochiCommentOf(r) {
  return {
    date: isDateStr(str(r.race_date)) ? str(r.race_date) : null,
    raceNo: num(r.race_no),
    umaban: num(r.umaban),
    horseName: str(r.horse_name),
    jockey: str(r.jockey),
    comment: str(r.comment),
    sourceUrl: str(r.source_url),
  };
}

const kcOk = (x) => !!(x && x.date && x.raceNo !== null && x.umaban !== null && x.comment);

// レースページ用= その 1 レースぶん(馬番順)。30 分メモ。⚠表がまだ無い/行が無いときは空で返す
export function getKochiComments(date, raceNo) {
  const d = isDateStr(date) ? String(date) : null;
  const no = num(raceNo);
  if (!d || no === null) return Promise.resolve([]);
  return memo(`kcomment:${d}/${no}`, 30 * MIN, async () => {
    const rows = await sbNar(`nar_race_comments?select=${KC_COLS}` +
      `&track=eq.${enc(KOCHI_COMMENT_TRACK)}&race_date=eq.${d}&race_no=eq.${no}` +
      '&order=umaban.asc').catch(() => []);
    return (Array.isArray(rows) ? rows : []).map(kochiCommentOf).filter(kcOk);
  });
}

// 馬ページ用= 馬名の束 → Map(馬名 → 行[])。100 頭ずつ・30 分メモ。
// ⚠**馬名だけでは同名の別馬を分けられない**ので、使う側は必ず kochiCommentFor() で
//   「その馬の走(日付・R・馬番が一致)」に当たる行だけを取ること(§119b の kbRunFor と同じ規則)。
export function getKochiCommentsForHorse(names) {
  const list = [...new Set((Array.isArray(names) ? names : []).map(str).filter(Boolean))].sort();
  if (!list.length) return Promise.resolve(new Map());
  return memo(`kcomments:${list.join(',')}`, 30 * MIN, async () => {
    const parts = await Promise.all(chunk(list, KC_NAME_CHUNK).map((part) =>
      sbNar(`nar_race_comments?select=${KC_COLS},horse_name` +
        `&track=eq.${enc(KOCHI_COMMENT_TRACK)}&horse_name=in.(${enc(quoteIn(part))})` +
        '&order=race_date.desc&limit=2000').catch(() => [])));
    const out = new Map();
    for (const r of parts.flat()) {
      const x = kochiCommentOf(r);
      if (!kcOk(x) || !x.horseName) continue;
      if (!out.has(x.horseName)) out.set(x.horseName, []);
      out.get(x.horseName).push(x);
    }
    return out;
  });
}

// その走(走歴の 1 行)に当たるコメント。⛔馬名だけで拾わない=
// **高知の走**で 日付・R・馬番 の 3 つがそろって初めて同じ走と見なす(同名の別馬を入れないため)
export function kochiCommentFor(rows, run) {
  if (!Array.isArray(rows) || !run || run.venue !== 'kochi' || !isDateStr(str(run.date))) return null;
  const no = num(run.raceNo);
  const uma = num(run.umaban);
  if (no === null || uma === null) return null;
  return rows.find((x) => x.date === str(run.date) && x.raceNo === no && x.umaban === uma) || null;
}

// ---------------------------------------------------------------- §121 福ちゃん競馬新聞(高知)の陣営談話

// 紙面(PDF)を手元 PC で読んだもの。⛔**私的利用**= 閲覧者には 1 字も出さない
// (紙面 1 ページ目に「本誌からの複製・転載を禁ず」)。表 `kochi_paper_talks` は anon から select も
// できない(RLS で policy 無し)ので、**管理者だけ**が Worker の admin read 経路で読む(§58 と同じ)。
// ⛔FLAGS.dev でなければ**1 本も投げない**= 閲覧者の通信は増えない。
export const PAPER_TALK_VENUE = 'kochi';

function paperTalkOf(r) {
  return {
    date: isDateStr(str(r.paper_date)) ? str(r.paper_date) : null,
    raceNo: num(r.race_no),
    umaban: num(r.umaban),
    horseName: str(r.horse_name),
    talk: str(r.talk),
    matched: r.matched === true,
    sourceFile: str(r.source_file),   // Worker が列に入れていなければ null(画面は出さないだけ)
  };
}
const ptOk = (x) => !!(x && x.date && x.raceNo !== null && x.umaban !== null && x.talk);

// admin read の戻り(`{ok, rows}`)→ 行の配列。⛔トークンが無ければ引かない。
// ⛔**取れなかったときは覚えない**= 中で throw して memo から落とし、外で [] にする
//   (覚えてしまうと、一度の失敗のあと 30 分ずっと「行が無い」ことになる)
function paperRows(path, key) {
  if (!FLAGS.dev) return Promise.resolve([]);
  return memo(key, 30 * MIN, async () => {
    const j = await adminGet(path);
    const rows = j && j.ok && Array.isArray(j.rows) ? j.rows : [];
    return rows.map(paperTalkOf).filter(ptOk);
  }).catch(() => []);
}

// レースページ用= その 1 レースぶん(馬番順)。⛔高知のレースでだけ呼ぶ
export function getPaperTalks(date, raceNo) {
  const d = isDateStr(date) ? String(date) : null;
  const no = num(raceNo);
  if (!FLAGS.dev || !d || no === null) return Promise.resolve([]);
  return paperRows(`/rpc/admin-kochi-paper?date=${enc(d)}&race_no=${enc(String(no))}`,
    `ptalk:${d}/${no}`).then((rows) => [...rows].sort((a, b) => a.umaban - b.umaban));
}

// 馬ページ用= その馬名ぶん。⚠**馬名だけでは同名の別馬を分けられない**ので、使う側は必ず
// paperTalkFor() で「その馬の走(日付・R・馬番が一致)」に当たる行だけを取ること(§120 と同じ規則)
export function getPaperTalksForHorse(name) {
  const nm = str(name);
  if (!FLAGS.dev || !nm) return Promise.resolve([]);
  return paperRows(`/rpc/admin-kochi-paper?horse=${enc(nm)}`, `ptalkh:${nm}`);
}

// その走(走歴の 1 行)に当たる談話。⛔馬名だけで拾わない=
// **高知の走**で 日付・R・馬番 の 3 つがそろって初めて同じ走と見なす(同名の別馬を入れないため)
export function paperTalkFor(rows, run) {
  if (!Array.isArray(rows) || !run || run.venue !== PAPER_TALK_VENUE || !isDateStr(str(run.date))) return null;
  const no = num(run.raceNo);
  const uma = num(run.umaban);
  if (no === null || uma === null) return null;
  return rows.find((x) => x.date === str(run.date) && x.raceNo === no && x.umaban === uma) || null;
}

// ---------------------------------------------------------------- §126 乗り替わり(nar_jc_*)

// 集計は夜間の便(cloud/jockey_change.py)で作り直している。画面は**読むだけ**。
// 定義は pipeline/sql/jockey_change_20260907.sql の頭に全部ある(乗替= 前走と騎手が違う走・
// 複勝= 3 着以内・前走は場をまたいで数える)。⛔画面で定義を作り直さない。
// ⛔色の閾値はここ 1 か所(旧ビューアと同じ値)。⛔価値判断の語は使わない(並びと色だけ)
export const JC_HI = 45;
export const JC_LO = 20;
// fin='final' の行がある場だけ(実測 2026-09-07: 高知 1,787・名古屋 420・他の場は 0)
export const JC_FINAL_PREFIXES = ['kochi', 'nagoya'];
const JC_YEARS_FROM = 2022;                 // 集計の始まり(nar_jc_meta.min_date と同じ年)
const JC_PAGE = 1000;                       // PostgREST の 1 回の上限
const JC_MAX_PAGES = 10;                    // ⛔回り続けない(実測で一番多い大井で 3,302 行= 4 頁)

const JC_TJ_COLS = 'trainer,jockey,n,win,hit,chg_n,chg_win,chg_hit,cont_n,cont_win,cont_hit,' +
  'first_n,first_hit,rejoin_n,rejoin_hit,up_n,up_hit,down_n,down_hit,same_n,same_hit';
const JC_PAIR_COLS = 'trainer,from_jockey,to_jockey,n,win,hit,first_n,first_hit,rejoin_n,rejoin_hit';

// 共通の絞り(場・年・ファイナル)。⛔値は必ず enc を通す
function jcWhere(prefix, opts) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v) return null;
  const o = opts || {};
  const yr = str(o.yr) && /^(all|20\d{2})$/.test(str(o.yr)) ? str(o.yr) : 'all';
  const fin = o.fin === 'final' && JC_FINAL_PREFIXES.includes(v.prefix) ? 'final' : 'all';
  return { v, yr, fin, q: `track=eq.${enc(narTrackName(v))}&yr=eq.${enc(yr)}&fin=eq.${enc(fin)}` };
}

const jcNum = (x) => { const n = num(x); return n === null ? 0 : n; };
function jcRow(r) {
  return {
    trainer: str(r.trainer) || '',
    jockey: str(r.jockey) || '',
    n: jcNum(r.n), win: jcNum(r.win), hit: jcNum(r.hit),
    chg: { n: jcNum(r.chg_n), win: jcNum(r.chg_win), hit: jcNum(r.chg_hit) },
    cont: { n: jcNum(r.cont_n), win: jcNum(r.cont_win), hit: jcNum(r.cont_hit) },
    first: { n: jcNum(r.first_n), hit: jcNum(r.first_hit) },
    rejoin: { n: jcNum(r.rejoin_n), hit: jcNum(r.rejoin_hit) },
    up: { n: jcNum(r.up_n), hit: jcNum(r.up_hit) },
    down: { n: jcNum(r.down_n), hit: jcNum(r.down_hit) },
    same: { n: jcNum(r.same_n), hit: jcNum(r.same_hit) },
  };
}

// 厩舎×騎手の行。trainer='' なら**全厩舎を束ねた行**(騎手側の見方)。
// jockey を渡すと「その騎手の厩舎別」(trainer<>'' の行を騎手で絞る)
export function getJcTrainerJockey(prefix, opts) {
  const w = jcWhere(prefix, opts);
  if (!w) return Promise.resolve([]);
  const o = opts || {};
  const trainer = str(o.trainer);
  const jockey = str(o.jockey);
  const filter = jockey
    ? `&jockey=eq.${enc(jockey)}&trainer=neq.`
    : `&trainer=eq.${enc(trainer || '')}`;
  const key = `jctj:${w.v.prefix}/${w.yr}/${w.fin}/${trainer || ''}/${jockey || ''}`;
  return memo(key, 30 * MIN, async () => {
    const rows = await sbNar(`nar_jc_trainer_jockey?select=${JC_TJ_COLS}&${w.q}${filter}` +
      `&order=n.desc,jockey.asc&limit=${JC_PAGE}`).catch(() => []);
    return (Array.isArray(rows) ? rows : []).map(jcRow);
  });
}

// 乗替ペア A→B。⛔厩舎か to_jockey で**必ず絞る**(全部は引かない= 1 場で数千行ある)
export function getJcPairs(prefix, opts) {
  const w = jcWhere(prefix, opts);
  const o = opts || {};
  const trainer = str(o.trainer);
  const toJockey = str(o.toJockey);
  if (!w || (!trainer && !toJockey)) return Promise.resolve([]);
  const filter = (trainer ? `&trainer=eq.${enc(trainer)}` : '&trainer=eq.') +
    (toJockey ? `&to_jockey=eq.${enc(toJockey)}` : '');
  const key = `jcpair:${w.v.prefix}/${w.yr}/${w.fin}/${trainer || ''}/${toJockey || ''}`;
  return memo(key, 30 * MIN, async () => {
    const rows = await sbNar(`nar_jc_pairs?select=${JC_PAIR_COLS}&${w.q}${filter}` +
      `&order=n.desc,to_jockey.asc&limit=${JC_PAGE}`).catch(() => []);
    return (Array.isArray(rows) ? rows : []).map((r) => ({
      trainer: str(r.trainer) || '',
      from: str(r.from_jockey) || '',
      to: str(r.to_jockey) || '',
      n: jcNum(r.n), win: jcNum(r.win), hit: jcNum(r.hit),
      first: { n: jcNum(r.first_n), hit: jcNum(r.first_hit) },
      rejoin: { n: jcNum(r.rejoin_n), hit: jcNum(r.rejoin_hit) },
    }));
  });
}

// 人気帯 × 種別(chg/cont/first/rejoin/up/down/same)。実測 35 行= 1 本で足りる
export function getJcPop(prefix, opts) {
  const w = jcWhere(prefix, opts);
  if (!w) return Promise.resolve([]);
  return memo(`jcpop:${w.v.prefix}/${w.yr}/${w.fin}`, 30 * MIN, async () => {
    const rows = await sbNar(`nar_jc_pop?select=kind,pop_band,n,win,hit&${w.q}` +
      `&order=kind.asc,pop_band.asc&limit=${JC_PAGE}`).catch(() => []);
    return (Array.isArray(rows) ? rows : []).map((r) => ({
      kind: str(r.kind) || '', band: str(r.pop_band) || '',
      n: jcNum(r.n), win: jcNum(r.win), hit: jcNum(r.hit),
    }));
  });
}

// 集計の期間と更新時刻(注記に使う)
export function getJcMeta() {
  return memo('jcmeta', 30 * MIN, async () => {
    const rows = await sbNar('nar_jc_meta?select=value&key=eq.refresh&limit=1').catch(() => []);
    const v = Array.isArray(rows) && rows[0] && rows[0].value && typeof rows[0].value === 'object' ? rows[0].value : {};
    return { at: str(v.at), minDate: str(v.min_date), maxDate: str(v.max_date) };
  });
}

// 厩舎の一覧(n の合計順)。⚠1 場の行は **1,000 を超える**(実測: 大井 3,302・名古屋 1,763・
// 門別 1,326・高知 1,214)ので、**一意な並び(trainer,jockey)で頁送り**する。
// ⛔order が一意でないと offset で行が重複/欠落する(台帳の実測)。⛔回り続けない(JC_MAX_PAGES)
export function getJcTrainers(prefix, opts) {
  const w = jcWhere(prefix, opts);
  if (!w) return Promise.resolve([]);
  return memo(`jctr:${w.v.prefix}/${w.yr}/${w.fin}`, 30 * MIN, async () => {
    const by = new Map();
    for (let page = 0; page < JC_MAX_PAGES; page += 1) {
      let rows;
      try {
        rows = await sbNar(`nar_jc_trainer_jockey?select=trainer,n&${w.q}&trainer=neq.` +
          `&order=trainer.asc,jockey.asc&limit=${JC_PAGE}&offset=${page * JC_PAGE}`);
      } catch { break; }
      if (!Array.isArray(rows) || !rows.length) break;
      for (const r of rows) {
        const t = str(r.trainer);
        if (t) by.set(t, (by.get(t) || 0) + jcNum(r.n));
      }
      if (rows.length < JC_PAGE) break;
    }
    return [...by].map(([trainer, n]) => ({ trainer, n }))
      .sort((a, b) => b.n - a.n || a.trainer.localeCompare(b.trainer));
  });
}

// §126 C 出馬表の 1 行ぶん。⛔**1 レースで 2 本**だけ= ①乗替ペア ②厩舎×騎手。
// ⛔馬ごとに引かない(前走騎手と今走騎手を束ねて in.() で 1 回ずつ)。
// 返り= { pair: Map('前→今' → 行), tj: Map('厩舎::騎手' → 行) }。取れなければ空の Map。
export function getJcRaceLines(prefix, froms, tos, trainers) {
  const w = jcWhere(prefix, { yr: 'all', fin: 'all' });
  const f = [...new Set((Array.isArray(froms) ? froms : []).map(str).filter(Boolean))].sort();
  const t = [...new Set((Array.isArray(tos) ? tos : []).map(str).filter(Boolean))].sort();
  const tr = [...new Set((Array.isArray(trainers) ? trainers : []).map(str).filter(Boolean))].sort();
  const empty = { pair: new Map(), tj: new Map() };
  if (!w || !f.length || !t.length) return Promise.resolve(empty);
  const key = `jcrace:${w.v.prefix}/${f.join(',')}/${t.join(',')}/${tr.join(',')}`;
  return memo(key, 30 * MIN, async () => {
    const [pairs, rows] = await Promise.all([
      // ⛔前走側と今走側の**両方**を絞る= 1 レースぶんなら最大 16×16 行(1000 上限に触らない)
      sbNar(`nar_jc_pairs?select=from_jockey,to_jockey,n,win,hit&${w.q}&trainer=eq.` +
        `&from_jockey=in.(${enc(quoteIn(f))})&to_jockey=in.(${enc(quoteIn(t))})&limit=${JC_PAGE}`).catch(() => []),
      tr.length
        ? sbNar(`nar_jc_trainer_jockey?select=trainer,jockey,chg_n,chg_hit&${w.q}` +
          `&trainer=in.(${enc(quoteIn(tr))})&jockey=in.(${enc(quoteIn(t))})&limit=${JC_PAGE}`).catch(() => [])
        : Promise.resolve([]),
    ]);
    const out = { pair: new Map(), tj: new Map() };
    for (const r of (Array.isArray(pairs) ? pairs : [])) {
      const a = str(r.from_jockey);
      const b = str(r.to_jockey);
      if (a && b) out.pair.set(a + '::' + b, { n: jcNum(r.n), win: jcNum(r.win), hit: jcNum(r.hit) });
    }
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const a = str(r.trainer);
      const b = str(r.jockey);
      if (a && b) out.tj.set(a + '::' + b, { n: jcNum(r.chg_n), hit: jcNum(r.chg_hit) });
    }
    return out;
  });
}

// 年の選択肢(集計の始まり〜今年)。⛔通信なし
export function jcYears(today) {
  const y = Number(String(today ?? todayJST()).slice(0, 4)) || JC_YEARS_FROM;
  const out = [];
  for (let i = y; i >= JC_YEARS_FROM; i -= 1) out.push(String(i));
  return out;
}

// ---------------------------------------------------------------- §22.3 血統・馬主・生産者(nar_horses)

// 公式に馬ID が無いので馬名で引く。同名異馬があり得るので ambiguous を添えてページ側で断る。30分メモ
export function getHorseProfile(name) {
  const nm = str(name);
  if (!nm) return Promise.resolve(null);
  return memo(`hprof:${nm}`, 30 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_horses?select=horse_name,sex,sire,dam,broodmare_sire,owner,breeder,runs' +
        `&horse_name=eq.${enc(nm)}&limit=2`);
    } catch { return null; }
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) return null;
    const r = list[0];
    const out = {
      name: str(r.horse_name) || nm,
      sire: str(r.sire),
      dam: str(r.dam),
      bms: str(r.broodmare_sire),
      owner: str(r.owner),
      breeder: str(r.breeder),
      runs: num(r.runs),
      ambiguous: list.length > 1,      // 同じ馬名が複数ある(表示側で断る)
    };
    // 全部空なら「無い」と同じ
    return (out.sire || out.dam || out.owner || out.breeder) ? out : null;
  });
}

// §105 産駒(または母父が同じ馬)の一覧。`nar_horses` 1本・30分メモ・**通信 +1**。
// ⚠新しい順(最終出走)で最大 SIRE_HORSES_MAX 頭。それ以上いる父は「◯頭まで出しています」と画面が断る。
// ⛔馬IDは公式に無いので馬名で結ぶ(同名異馬が混ざり得る= 画面が注記で断る)。読めなければ [] ではなく null
//   (「0頭」と「取れなかった」を画面で言い分けるため)
export const SIRE_HORSES_MAX = 300;

export function getSireHorses(kind, name) {
  const k = kind === 'bms' ? 'broodmare_sire' : 'sire';
  const nm = str(name);
  if (!nm) return Promise.resolve(null);
  return memo(`sirehorses:${k}:${nm}`, 30 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_horses?select=horse_name,sex,dam,broodmare_sire,first_date,last_date,runs' +
        `&${k}=eq.${enc(nm)}&order=last_date.desc.nullslast,horse_name.asc&limit=${SIRE_HORSES_MAX}`);
    } catch { return null; }
    return (Array.isArray(rows) ? rows : []).map((r) => ({
      name: str(r.horse_name),
      sex: str(r.sex),
      dam: str(r.dam),
      bms: str(r.broodmare_sire),
      first: isDateStr(str(r.first_date)) ? str(r.first_date) : null,
      last: isDateStr(str(r.last_date)) ? str(r.last_date) : null,
      runs: num(r.runs),
    })).filter((x) => x.name);
  });
}

// ---------------------------------------------------------------- §22.2 マイ印(この端末だけ・localStorage)

// 押すたびに ◎→○→▲→△→×→(無)と一周する
export const MY_MARKS = ['◎', '○', '▲', '△', '×'];
export const MY_MARKS_MAX = 500;          // これを超えたら古い開催日のレースから消す
const MY_MARKS_KEY = 'kv_my_marks';

// 'prefix/YYYY-MM-DD/no' だけを鍵として認める(localStorage の中身は何が入っているか分からない)
function parseRaceId(id) {
  const m = /^([a-z]+)\/(\d{4}-\d{2}-\d{2})\/(\d{1,2})$/.exec(String(id ?? ''));
  if (!m || !VENUE_BY_PREFIX.has(m[1])) return null;
  return { venue: m[1], date: m[2], no: Number(m[3]) };
}

function readMyMarks() {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(MY_MARKS_KEY);
    const o = raw ? JSON.parse(raw) : null;
    return o && typeof o === 'object' && !Array.isArray(o) ? o : {};
  } catch { return {}; }
}

function writeMyMarks(all) {
  try { localStorage.setItem(MY_MARKS_KEY, JSON.stringify(all)); return true; } catch { return false; }
}

// 開催日の古い順に落として上限に収める
function pruneMyMarks(all) {
  const ids = Object.keys(all).filter((id) => parseRaceId(id));
  if (ids.length <= MY_MARKS_MAX) return;
  // 鍵は 'prefix/date/no' なので文字列順は日付順にならない。日付で並べ直してから古い方を落とす
  const byDate = ids.map((id) => ({ id, date: parseRaceId(id).date }))
    .sort((a, b) => a.date.localeCompare(b.date));
  for (const x of byDate.slice(0, ids.length - MY_MARKS_MAX)) delete all[x.id];
}

// そのレースの印(馬番 → 印)。無ければ空の Map
export function getMyMarks(raceId) {
  const out = new Map();
  const id = String(raceId ?? '');
  if (!parseRaceId(id)) return out;
  const all = readMyMarks();
  const race = Object.prototype.hasOwnProperty.call(all, id) ? all[id] : null;
  if (!race || typeof race !== 'object') return out;
  for (const k of Object.keys(race)) {
    const n = num(k);
    const mk = str(race[k]);
    if (n !== null && MY_MARKS.includes(mk)) out.set(n, mk);
  }
  return out;
}

// 1つ進める。戻り = 新しい印(消えたときは null)
export function cycleMyMark(raceId, umaban) {
  const id = String(raceId ?? '');
  const n = Number(umaban);
  if (!parseRaceId(id) || !Number.isInteger(n) || n < 1) return null;
  const all = readMyMarks();
  const cur = Object.prototype.hasOwnProperty.call(all, id) && all[id] && typeof all[id] === 'object' ? all[id] : {};
  const race = {};
  for (const k of Object.keys(cur)) { const v = str(cur[k]); if (num(k) !== null && MY_MARKS.includes(v)) race[k] = v; }
  const i = MY_MARKS.indexOf(str(race[String(n)]));
  const next = i < 0 ? MY_MARKS[0] : (i + 1 < MY_MARKS.length ? MY_MARKS[i + 1] : null);
  if (next) race[String(n)] = next; else delete race[String(n)];
  if (Object.keys(race).length) all[id] = race; else delete all[id];
  pruneMyMarks(all);
  writeMyMarks(all);
  return next;
}

// 印を付けたレースの一覧(新しい順)
export function listMyMarks() {
  const all = readMyMarks();
  const out = [];
  for (const id of Object.keys(all)) {
    const p = parseRaceId(id);
    const race = all[id];
    if (!p || !race || typeof race !== 'object') continue;
    const marks = [];
    for (const k of Object.keys(race)) {
      const n = num(k);
      const mk = str(race[k]);
      if (n !== null && MY_MARKS.includes(mk)) marks.push({ umaban: n, mark: mk });
    }
    if (!marks.length) continue;
    marks.sort((a, b) => MY_MARKS.indexOf(a.mark) - MY_MARKS.indexOf(b.mark) || a.umaban - b.umaban);
    out.push({ raceId: id, venue: p.venue, date: p.date, no: p.no, marks });
  }
  return out.sort((a, b) => b.date.localeCompare(a.date) || b.no - a.no);
}

export function clearMyMarks() {
  try { localStorage.removeItem(MY_MARKS_KEY); } catch { /* 消せなくても画面は動く */ }
}

// ---------------------------------------------------------------- §27.3 全国リーディング(nar_person_stats)

export const LEADING_MAX = 50;
const LEADING_KINDS = ['jockey', 'trainer', 'sire', 'bms'];   // §105 母父を追加

// 種別×期間で1クエリ・10分メモ。並べ替えは DB 側(stats->w1 の降順)に任せる。
// 主戦場は騎手・調教師が stats.main_track、種牡馬は by_track の先頭(出走の多い順に入っている)
export function getLeading(kind, period) {
  const k = String(kind ?? '');
  const p = String(period ?? '');
  if (!LEADING_KINDS.includes(k) || !/^(all|\d{4})$/.test(p)) return Promise.resolve([]);
  return memo(`leading:${k}:${p}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_person_stats?kind=eq.${k}&track=eq.all&period=eq.${p}` +
        `&select=name,stats&order=stats->w1.desc&limit=${LEADING_MAX}`);
    } catch { return []; }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const nm = str(r.name);
      const s = r.stats && typeof r.stats === 'object' ? r.stats : null;
      if (!nm || !s) continue;
      const by = Array.isArray(s.by_track) ? s.by_track : [];
      out.push({
        rank: out.length + 1,
        name: nm,
        n: num(s.n), w1: num(s.w1), win: num(s.win), top3: num(s.top3), roi: num(s.roi),
        mainTrack: str(s.main_track) || (by.length ? str(by[0].track) : null),
      });
    }
    return out;
  });
}

// ---------------------------------------------------------------- §27.2 重賞(nar_graded)

export const GRADED_FROM_YEAR = 2022;             // 公式データの最初の年(2022-11〜)
// 画面に出す区分。普通・特別は出さない(公式の「競走種類名称」そのまま)
const GRADED_KINDS = ['重賞', '準重賞'];
function raceKind(v) {
  const s = str(v);
  return s && GRADED_KINDS.includes(s) ? s : null;
}

// 年ごとに1クエリ・10分メモ。今年は上限を付けない(先の重賞も入れて「今週の重賞」に使う)。
// 全期間 1,727 件は PostgREST の 1000 行上限に当たるので、年で切っている(§10 の 1000 行上限)
export function getGraded(year) {
  const y = Number(year);
  if (!Number.isInteger(y) || y < GRADED_FROM_YEAR) return Promise.resolve([]);
  return memo(`graded:${y}`, 10 * MIN, async () => {
    const cur = Number(todayJST().slice(0, 4));
    const cols = 'race_date,track,race_no,race_name,race_kind,distance_m,post_time,field_size,' +
      'prize1_yen,winner_horse,winner_jockey,winner_pop';
    const upper = y >= cur ? '' : `&race_date=lt.${y + 1}-01-01`;
    let rows;
    try {
      rows = await sbNar(`nar_graded?select=${cols}&race_date=gte.${y}-01-01${upper}` +
        '&order=race_date.desc,race_no.desc&limit=1000');
    } catch { return []; }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      const date = String(r.race_date ?? '');
      const no = num(r.race_no);
      if (!prefix || !isDateStr(date) || no === null) continue;
      const v = VENUE_BY_PREFIX.get(prefix);
      out.push({
        raceId: v && v.supported !== 'none' ? `${prefix}/${date}/${no}` : null,
        venue: prefix, date, no,
        name: str(r.race_name) || `${no}R`,
        kind: raceKind(r.race_kind) || str(r.race_kind),
        distance: num(r.distance_m),
        postTime: narPostTime(r.post_time),
        heads: num(r.field_size),
        prize1: num(r.prize1_yen),
        winnerHorse: str(r.winner_horse),
        winnerJockey: str(r.winner_jockey),
        winnerPop: num(r.winner_pop),
      });
    }
    return out;
  });
}

// ---------------------------------------------------------------- §46.2 先の開催日程(主催者の月別開催日程)

// ---------------------------------------------------------------- §54.1 P1 売上(発売票数)

// nar_sales(cloud/rakuten_sales.py が楽天競馬の払戻ページから集めた**券種ごとの票数**)。
// ⛔1票=100円は主催者共通の単位。⛔**重勝式(WIN5等)は入っていない**= 楽天のページに無い
// (けーばどっとこむの合計との差はそれだけ、と §54.1 実装記録で1円まで検算済み)。
// 返り値の形は「場ごと」= { prefix, name, races:[{no, votes, refunds, total, refundTotal}],
//                          votes, refunds, total, refundTotal }
const SALES_COLS = 'track,race_no,votes,refunds';
// 1レースぶんの上限。1日は 15場×12R でも 180 行なので 400 で足りる(⛔1000 行の silent cap を踏まない)
const SALES_DAY_LIMIT = 400;

// 売上が入っている**いちばん新しい日**(= /sales の既定日)。1クエリ・10分メモ
export function getSalesLatestDate() {
  return memo('saleslatest', 10 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_sales?select=race_date&order=race_date.desc&limit=1'); } catch { return null; }
    const d = Array.isArray(rows) && rows.length ? str(rows[0].race_date) : '';
    return isDateStr(d) ? d : null;
  });
}

// その日の全場の売上。**1日=1クエリ**(実測 16〜17KB / 46〜48レース)
export function getDaySales(date) {
  if (!isDateStr(date)) return Promise.resolve([]);
  return memo(`sales:${date}`, ttlForDate(date), async () => {
    let rows;
    try {
      rows = await sbNar(`nar_sales?select=${SALES_COLS}&race_date=eq.${date}` +
        `&order=race_no.asc&limit=${SALES_DAY_LIMIT}`);
    } catch { return []; }
    return salesVenues(rows);
  });
}

// その日その場の売上。日ぶんが**もう手元にあればそれを切って使う**(通信ゼロ)。
// 無ければその場だけを引く(1クエリ・1〜2KB)
export function getVenueSales(prefix, date) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v || !isDateStr(date)) return Promise.resolve(null);
  if (memoReady(`sales:${date}`)) {
    return getDaySales(date).then((list) => list.find((x) => x.prefix === v.prefix) || null);
  }
  return memo(`sales:${date}:${v.prefix}`, ttlForDate(date), async () => {
    let rows;
    try {
      rows = await sbNar(`nar_sales?select=${SALES_COLS}&race_date=eq.${date}` +
        `&track=eq.${enc(narTrackName(v))}&order=race_no.asc&limit=40`);
    } catch { return null; }
    return salesVenues(rows)[0] || null;
  });
}

// §90 「買うと」の見込みの元= 場×レース番号の単勝正味票数の中央値(ビュー nar_sales_win_ref・直近365日)。
// 返り値 = Map(場の prefix → Map(レース番号 → 票数))。⛔**元になったレースが5走に満たない行は入れない**
//   (少ない実績で中央値を作らない)。全場で1本・180行前後。10分メモ
const WIN_REF_MIN_RACES = 5;
export function getSalesWinRef() {
  return memo('winref', 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_sales_win_ref?select=track,race_no,races,med_win_votes&limit=400');
    } catch { return new Map(); }
    const out = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      const no = num(r.race_no);
      const med = num(r.med_win_votes);
      const n = num(r.races);
      if (!prefix || no === null || med === null || med <= 0) continue;
      if (n === null || n < WIN_REF_MIN_RACES) continue;
      if (!out.has(prefix)) out.set(prefix, new Map());
      out.get(prefix).set(no, med);
    }
    return out;
  });
}

// §54.1 P1 レース別の行に添える発走時刻とレース名(売上とは別テーブルなので**別の1本**・実測 1.4KB)。
// 返り値 = Map(レース番号 → { postTime, name, distance })。取れなければ空の Map(行は出る)
export function getVenueRaceHeads(prefix, date) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  if (!v || !isDateStr(date)) return Promise.resolve(new Map());
  return memo(`rheads:${v.prefix}:${date}`, ttlForDate(date), async () => {
    let rows;
    try {
      rows = await sbNar(`nar_races?select=race_no,post_time,race_name,distance_m&race_date=eq.${date}` +
        `&track=eq.${enc(narTrackName(v))}&order=race_no.asc&limit=40`);
    } catch { return new Map(); }
    const out = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const no = num(r.race_no);
      if (no === null) continue;
      out.set(no, { postTime: narPostTime(r.post_time), name: str(r.race_name) || null, distance: num(r.distance_m) });
    }
    return out;
  });
}

// 生の行 → 場ごとの塊。⛔知らない場名(別名を含む)の行は落とす=場の並びは VENUES の順
function salesVenues(rows) {
  const by = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const prefix = narPrefixOf(r.track);
    const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
    if (!v) continue;
    const no = num(r.race_no);
    if (no === null) continue;
    let g = by.get(v.prefix);
    if (!g) {
      g = { prefix: v.prefix, name: v.name, races: [], votes: ticketZero(), refunds: ticketZero(), total: 0, refundTotal: 0 };
      by.set(v.prefix, g);
    }
    const votes = ticketNums(r.votes);
    const refunds = ticketNums(r.refunds);
    const total = ticketSum(votes);
    const refundTotal = ticketSum(refunds);
    g.races.push({ no, votes, refunds, total, refundTotal });
    for (const k of TICKET_BOARD_ORDER) {
      g.votes[k] += votes[k];
      g.refunds[k] += refunds[k];
    }
    g.total += total;
    g.refundTotal += refundTotal;
  }
  const out = [];
  for (const v of VENUES) {
    const g = by.get(v.prefix);
    if (!g) continue;
    g.races.sort((a, b) => a.no - b.no);
    out.push(g);
  }
  return out;
}

function ticketZero() {
  const o = {};
  for (const k of TICKET_BOARD_ORDER) o[k] = 0;
  return o;
}
// jsonb の { win: 29846, … } を数に。⛔知らない鍵は捨てる(券種の知識は TICKET_BOARD_ORDER 1か所)
function ticketNums(v) {
  const o = ticketZero();
  if (v && typeof v === 'object') {
    for (const k of TICKET_BOARD_ORDER) {
      const n = num(v[k]);
      if (n !== null && n > 0) o[k] = n;
    }
  }
  return o;
}
function ticketSum(o) {
  let n = 0;
  for (const k of TICKET_BOARD_ORDER) n += o[k];
  return n;
}

// 公式の月別開催日程(予定)を `cloud/convene.py` が nar_meta `kaisai_schedule` に入れたものを読む。
// 返り値 = { built, months, days: Map(date → [{venue, mark}]) }。取れなければ null。
// ⚠**予定であって確定ではない**(画面は薄く出し、リンクは付けない)。記号は公式の字のまま持つ:
//   ●=通常開催 / ☆=ナイター競馬 / Ｄ=ダート交流重賞競走が実施される日 / △=別の日に代替開催
//   (2026-08-28 に公式ページの凡例を実読して確認。文言は画面の注記にそのまま出す)
export function getKaisaiSchedule() {
  // §53.2続き トップ(getTopMeta)が**同じ blob を相乗りで持っている**ときは引き直さない(#94 の型)。
  // ⚠鍵が別なので、これが無いと「トップ → 場ページ」で同じ 8.5KB を2回取ることになる
  if (memoReady('topmeta')) return getTopMeta().then((m) => (m && m.kaisai ? m.kaisai : fetchKaisai()));
  return fetchKaisai();
}

function fetchKaisai() {
  return memo('kaisai', 30 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_meta?select=value&key=eq.kaisai_schedule'); } catch { return null; }
    return parseKaisai(Array.isArray(rows) && rows.length ? rows[0].value : null);
  });
}

// §46 トップは「もうすぐ初出走」と「先の開催日程」の**両方**を使う。同じテーブルの隣の行なので
// `key=in.()` で**1本に相乗り**させる(#94 の型)。⚠/noken と /calendar は今までどおり単独で引く
// (memo が別なので、トップを見てから移ると 1 本だけ引き直す=8.5KB。両立させると memo が複雑になる)
export function getTopMeta() {
  return memo('topmeta', 10 * MIN, async () => {
    let rows;
    try { rows = await sbNar('nar_meta?select=key,value&key=in.(noken_debuts,kaisai_schedule)'); } catch { return {}; }
    const by = new Map();
    for (const r of (Array.isArray(rows) ? rows : [])) by.set(str(r.key), r.value);
    return { debuts: parseNokenDebuts(by.get('noken_debuts')), kaisai: parseKaisai(by.get('kaisai_schedule')) };
  });
}

function parseKaisai(v) {
  if (!v || typeof v !== 'object' || !v.days || typeof v.days !== 'object') return null;
  const days = new Map();
  for (const date of Object.keys(v.days)) {
    if (!isDateStr(date)) continue;
    const list = [];
    for (const x of (Array.isArray(v.days[date]) ? v.days[date] : [])) {
      const prefix = str(Array.isArray(x) ? x[0] : null);
      if (!prefix || !VENUE_BY_PREFIX.has(prefix)) continue;         // 知らない場は入れない(推定しない)
      list.push({ venue: prefix, mark: str(Array.isArray(x) ? x[1] : null) });
    }
    if (list.length) days.set(date, list);
  }
  if (!days.size) return null;
  return {
    built: isDateStr(v.built) ? String(v.built) : null,
    months: (Array.isArray(v.months) ? v.months : []).map(str).filter(Boolean),
    days,
  };
}

// ---------------------------------------------------------------- §74 重賞×年号(静的 JSON)
// 入力= コミット済み pipeline/graded_master.json を build で割った /data/graded/(tools/graded_split.mjs)。
// ⛔DB は引かない= URL は master の slug からしか生えない。同一オリジンなので CSP の connect-src 'self' の範囲
const SITE_BASE = (typeof document !== 'undefined' && document.documentElement.dataset.base) || '';
async function gradedJSON(path) {
  const res = await fetchOnce(`${SITE_BASE}/data/graded/${path}`, {});
  return res.json();
}
// slug → {h, n, o, y, k, t}(存在判定・ハブ用)。10分メモ
export function getGradedIndex() {
  return memo('graded:index', 10 * MIN, async () => {
    const j = await gradedJSON('index.json');
    return j && j.races && typeof j.races === 'object' ? j.races : {};
  });
}
// "prefix/日付/R" → slug(/graded の一覧から年ページへ飛ぶ逆引き)
export function getGradedRev() {
  return memo('graded:rev', 10 * MIN, async () => {
    const j = await gradedJSON('rev.json');
    return j && j.map && typeof j.map === 'object' ? j.map : {};
  });
}
// 1レースぶん。⛔master に無い slug は null(notFound)・通信失敗は例外(呼び手が言い分ける)
export function getGradedRace(slug) {
  const s = String(slug ?? '');
  if (!s || s.length > 80) return Promise.resolve(null);
  return memo(`graded:r:${s}`, 10 * MIN, async () => {
    const idx = await getGradedIndex();
    const e = idx[s];
    if (!e || !/^[0-9a-f]{12}$/.test(String(e.h ?? ''))) return null;
    const r = await gradedJSON(`r/${e.h}.json`);
    return r && r.years && typeof r.years === 'object' ? r : null;
  });
}

// §46 追加1 これから走る重賞を数件だけ(1クエリ・~120 バイト)。getGraded(年ぶん1000行)は重いので分ける
export function getUpcomingGraded(limit) {
  const n = Number.isInteger(limit) && limit > 0 && limit <= 10 ? limit : 3;
  const today = todayJST();
  return memo(`gradedup:${today}:${n}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_graded?select=race_date,track,race_no,race_name,race_kind,distance_m,post_time' +
        `&race_date=gte.${today}&order=race_date.asc,race_no.asc&limit=${n}`);
    } catch { return []; }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      const date = str(r.race_date);
      const no = num(r.race_no);
      if (!prefix || !isDateStr(date) || no === null) continue;
      const v = VENUE_BY_PREFIX.get(prefix);
      out.push({
        raceId: v && v.supported !== 'none' ? `${prefix}/${date}/${no}` : null,
        venue: prefix, date, no,
        name: str(r.race_name) || `${no}R`,
        kind: raceKind(r.race_kind) || str(r.race_kind),
        distance: num(r.distance_m),
        postTime: narPostTime(r.post_time),
      });
    }
    return out;
  });
}

// §46 追加2 その日のいちばん高い三連単(1行だけ出す)。1クエリ(1日ぶんの払戻 ~26KB=2026-08-27 実測)。
// 三連単が1件も無い日は null(黙って単複に落とさない=呼び出し側が「無い」と分かる)
export function getTopPayout(date) {
  if (!isDateStr(date)) return Promise.resolve(null);
  return memo(`toppay:${date}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar(`nar_race_payouts?select=track,race_no,payouts&${NAR_ALL_IN}&race_date=eq.${date}&limit=1000`);
    } catch { return null; }
    warnIfCapped(rows);
    let best = null;
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      const no = num(r.race_no);
      if (!prefix || no === null) continue;
      for (const p of (Array.isArray(r.payouts) ? r.payouts : [])) {
        if (String(p && p.t) !== 'trifecta') continue;
        const yen = Number(p && p.y);
        if (!Number.isFinite(yen) || (best && yen <= best.yen)) continue;
        best = { date, venue: prefix, no, raceId: `${prefix}/${date}/${no}`, yen, comb: String(p.c ?? ''), pop: num(p.p) };
      }
    }
    return best;
  });
}

// ⚠「その日より前の直近の開催日」は **既にある `getPrevRaceDate`**(§7.1)を使う=足さない(§5.4)

// ---------------------------------------------------------------- §54.3-d 移籍・在籍の変化

// `nar_horse_changes`(cloud/horse_changes.py が夜間に検出して書く)。
// ⛔**全部は引かない**= 1年5,705行(1日あたり約15.6件)なので 1000 行は約64日ぶんしかない。
// 既定の窓= **これから(未来日)+ 過去14日** ≒ 250行(2026-08-29 実測 227行・35.9KB)を**1本**で。
// ⚠`race_date` は「その変化が現れた出走(予定)日」= 出馬表の行でも立つ(#222)。未来日は**予定**。
// ⛔`from_value`/`to_value` は kind で意味が変わる(転入=地区名 / 転厩=調教師名)=画面でラベルを分ける
export function getHorseChanges(from) {
  if (!isDateStr(from)) return Promise.resolve([]);
  return memo(`changes:${from}`, 10 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_horse_changes?select=horse_name,birth_date,race_date,kind,from_value,to_value' +
        `&race_date=gte.${from}&order=race_date.desc,horse_name.asc&limit=1000`);
    } catch { return []; }
    warnIfCapped(rows, 'getHorseChanges');
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const date = str(r.race_date);
      const name = str(r.horse_name);
      const kind = str(r.kind);
      if (!isDateStr(date) || !name || !kind) continue;
      out.push({
        date,
        horseName: name,
        birthDate: str(r.birth_date),
        kind,
        from: str(r.from_value),
        to: str(r.to_value),
      });
    }
    return out;
  });
}

// ---------------------------------------------------------------- §56 メモ(端末が正本・サーバは写し)

// §56.2 端末の見分け。⛔**画面にも URL にもログにも出さない**(持っている人がその行を書ける=実質パスワード)。
// ⛔読むためだけには作らない= **初めて書くとき**に作る(何も保存しない人には ID を配らない)
const DEVICE_KEY = 'kv_device';
const NOTES_KEY = 'kv_notes';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// ⛔上限は DESIGN §56.10 の表と DB の `_viewer_limit()` に合わせる(変えるときは3か所そろえて直す)
export const NOTE_BODY_MAX = 1000;
export const NOTES_MAX = 200;
const NOTE_HORSE_MAX = 100;
// 引き継ぎで取り込んだメモをサーバへ写すときの同時数(⛔一度に投げすぎない)
const HANDOVER_BATCH = 5;

function deviceId(make) {
  try {
    if (typeof localStorage === 'undefined') return null;
    const cur = localStorage.getItem(DEVICE_KEY);
    if (cur && UUID_RE.test(cur)) return cur;
    if (!make || typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') return null;
    const id = crypto.randomUUID();
    localStorage.setItem(DEVICE_KEY, id);
    return id;
  } catch { return null; }
}

// この端末に保存されたメモ。形の合う行だけ通す(localStorage の中身は何が入っているか分からない)
function readNotes() {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(NOTES_KEY);
    const o = raw ? JSON.parse(raw) : null;
    if (!o || typeof o !== 'object' || Array.isArray(o)) return {};
    const out = {};
    for (const k of Object.keys(o)) {
      const id = str(k);
      const v = o[k];
      const body = v && typeof v === 'object' ? str(v.body) : null;
      if (!id || !body || id.length > NOTE_HORSE_MAX || body.length > NOTE_BODY_MAX) continue;
      out[id] = { body, at: str(v.at) || null };
    }
    return out;
  } catch { return {}; }
}
function writeNotes(o) {
  try { localStorage.setItem(NOTES_KEY, JSON.stringify(o)); return true; } catch { return false; }
}

// 新しく書いた順。⛔サーバからは読まない(表示はいつもこの端末の中身=§56.2)
export function listMyNotes() {
  const o = readNotes();
  return Object.keys(o).map((id) => ({ horseId: id, body: o[id].body, at: o[id].at }))
    .sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')));
}
export function getMyNote(horseId) {
  const id = str(horseId);
  const o = readNotes();
  return id && o[id] ? { horseId: id, body: o[id].body, at: o[id].at } : null;
}
export function countMyNotes() { return Object.keys(readNotes()).length; }
// メモを1件でも書いたことがあるか(=サーバに写しがあり得るか)。マイページの案内の出し分けに使う
// ⛔メモが0件でも**マイホースの控え**があればサーバに写しがある(§56.13 2-2 で馬も送るようになった)
export function hasServerCopy() {
  return !!deviceId(false) && (countMyNotes() > 0 || readMyHorses().length > 0);
}

// §56.1 書き込みは**関数(RPC)だけ**を通る(表に直接は触れない=anon に権限が無い)。
// ⛔claim だけは 5xx でも**やり直さない**(コードは使い切りなので、2回目は空振りになる)
async function rpcNar(name, body, once) {
  const url = `${NAR_URL}/rest/v1/rpc/${name}`;
  const init = {
    method: 'POST',
    headers: {
      apikey: NAR_KEY, Authorization: `Bearer ${NAR_KEY}`,
      'Content-Type': 'application/json', Accept: 'application/json',
    },
    body: JSON.stringify(body),
  };
  const res = await (once ? fetchOnce(url, init) : fetchRetry(url, init));
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

// ⛔サーバの日本語メッセージを**そのまま画面に出さない**= 画面側の言葉に直すための符丁に変える
function rpcReason(err) {
  const b = err && err.cause && typeof err.cause.body === 'string' ? err.cause.body : '';
  if (/件数/.test(b)) return 'too_many';
  if (/長すぎ/.test(b)) return 'too_long';
  if (/空です/.test(b)) return 'empty';
  if (/引き継ぐメモがありません/.test(b)) return 'no_notes';
  return 'offline';
}

// メモの保存(上書き)。**まず端末に書き**、そのあとサーバへ写す。
// 戻り = {ok, saved, synced, reason}。saved=端末に入ったか / synced=サーバに届いたか
export async function saveMyNote(horseId, body) {
  const id = str(horseId);
  const text = typeof body === 'string' ? body : '';
  if (!id) return { ok: false, saved: false, synced: false, reason: 'bad_horse' };
  if (id.length > NOTE_HORSE_MAX) return { ok: false, saved: false, synced: false, reason: 'bad_horse' };
  if (!text.trim()) return { ok: false, saved: false, synced: false, reason: 'empty' };
  if (text.length > NOTE_BODY_MAX) return { ok: false, saved: false, synced: false, reason: 'too_long' };
  const o = readNotes();
  if (!o[id] && Object.keys(o).length >= NOTES_MAX) {
    return { ok: false, saved: false, synced: false, reason: 'too_many' };
  }
  o[id] = { body: text, at: new Date().toISOString() };
  const saved = writeNotes(o);
  const dev = deviceId(true);
  if (!dev) return { ok: saved, saved, synced: false, reason: 'no_device' };
  try {
    await rpcNar('viewer_note_save', { p_device: dev, p_horse: id, p_body: text });
    return { ok: true, saved, synced: true, reason: null };
  } catch (e) {
    return { ok: saved, saved, synced: false, reason: rpcReason(e) };
  }
}

// メモを1件消す(端末から消してから、サーバの写しも消す)
export async function deleteMyNote(horseId) {
  const id = str(horseId);
  if (!id) return { ok: false, synced: false };
  const o = readNotes();
  delete o[id];
  const saved = writeNotes(o);
  const dev = deviceId(false);
  if (!dev) return { ok: saved, synced: true };            // 端末IDが無い=サーバにも写しは無い
  try {
    await rpcNar('viewer_note_delete', { p_device: dev, p_horse: id });
    return { ok: saved, synced: true };
  } catch { return { ok: saved, synced: false }; }
}

// §56.8 保存したデータを消す。alsoLocal=true なら**この端末の中のメモと端末の番号**も消す
// (⛔マイ印とマイホースは別のボタンのまま=巻き込まない)
export async function purgeMyData(alsoLocal) {
  const dev = deviceId(false);
  let synced = true;
  if (dev) {
    try { await rpcNar('viewer_purge', { p_device: dev }); } catch { synced = false; }
  }
  if (alsoLocal) {
    try { localStorage.removeItem(NOTES_KEY); localStorage.removeItem(DEVICE_KEY); } catch { /* 消せなくても画面は動く */ }
  }
  return { ok: true, synced, hadDevice: !!dev };
}

// §56.8 引き継ぎコードの発行。⛔返すのはコードだけ(端末の番号は画面に出さない)
export async function issueHandover() {
  const dev = deviceId(false);
  if (!dev) return { ok: false, reason: 'no_notes' };      // 一度も書いていない=サーバに写しが無い
  try {
    const code = await rpcNar('viewer_handover_issue', { p_device: dev });
    const s = str(code);
    return s ? { ok: true, code: s } : { ok: false, reason: 'offline' };
  } catch (e) {
    return { ok: false, reason: rpcReason(e) };
  }
}

// §56.8 引き継ぎコードの引き換え。⛔失敗は例外でなく {"ok":false,...} で返ってくる(§56.10 実装記録)。
// 受け取ったメモは**この端末の番号で**保存し直す(サーバは元の端末ぶんを残したまま=呼び出し側が案内する)
export async function claimHandover(code) {
  const s = str(code) ? String(code).trim().toUpperCase() : '';
  if (!s) return { ok: false, reason: 'bad_format' };
  let r;
  try {
    r = await rpcNar('viewer_handover_claim', { p_code: s }, true);
  } catch { return { ok: false, reason: 'offline' }; }
  if (!r || r.ok !== true) return { ok: false, reason: str(r && r.error) || 'bad_format' };
  const list = Array.isArray(r.notes) ? r.notes : [];
  const o = readNotes();
  const took = [];
  for (const n of list) {
    const id = str(n && n.horse_id);
    const body = str(n && n.body);
    if (!id || !body || id.length > NOTE_HORSE_MAX || body.length > NOTE_BODY_MAX) continue;
    if (!o[id] && Object.keys(o).length >= NOTES_MAX) break;      // ⛔上限を超えて取り込まない
    o[id] = { body, at: str(n.updated_at) || new Date().toISOString() };
    took.push({ id, body });
  }
  writeNotes(o);
  // §56.13 2-2 **馬も書き戻す**。⛔いまこの端末にある馬はそのまま残し、届いたぶんを
  //   **新しく登録した順**(サーバは added_at の新しい順で返す)で足りるだけ足す
  //   = 上限50を超えたら**古い方から落ちる**
  const gotH = Array.isArray(r.horses) ? r.horses : [];
  const before = readMyHorses();
  const mine = before.slice();
  const seenH = new Set(mine.map((h) => h.id));
  for (const x of gotH) {
    if (mine.length >= MY_HORSES_MAX) break;
    const row = myHorseRow(x);
    if (!row || seenH.has(row.id)) continue;
    seenH.add(row.id);
    mine.push(row);
  }
  if (mine.length > before.length) writeMyHorses(mine);   // ⛔この中でサーバにも写る(丸ごと置換)
  // この端末の番号でサーバにも写す(⛔一度に投げすぎない)
  const dev = deviceId(true);
  let synced = 0;
  if (dev) {
    for (let i = 0; i < took.length; i += HANDOVER_BATCH) {
      const part = took.slice(i, i + HANDOVER_BATCH);
      const rs = await Promise.allSettled(part.map((n) =>
        rpcNar('viewer_note_save', { p_device: dev, p_horse: n.id, p_body: n.body })));
      synced += rs.filter((x) => x.status === 'fulfilled').length;
    }
  }
  return {
    ok: true, got: list.length, took: took.length, synced,
    gotHorses: gotH.length, tookHorses: mine.length - before.length,
  };
}

// ---------------------------------------------------------------- §27.1 マイホース(この端末だけ・localStorage)

export const MY_HORSES_MAX = 50;          // これ以上は登録しない(断ってから止める)
const MY_HORSES_KEY = 'kv_my_horses';

// localStorage の中身は何が入っているか分からないので、形の合う行だけ通す
function myHorseRow(x) {
  if (!x || typeof x !== 'object') return null;
  const id = str(x.id);
  const name = str(x.name);
  if (!id || !/^(kb|kochi|name|nar|narb):/.test(id)) return null;
  return { id, name: name || id.replace(/^[a-z]+:/, '') };
}

function readMyHorses() {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(MY_HORSES_KEY);
    const a = raw ? JSON.parse(raw) : null;
    if (!Array.isArray(a)) return [];
    const out = [], seen = new Set();
    for (const x of a) {
      const r = myHorseRow(x);
      if (!r || seen.has(r.id)) continue;
      seen.add(r.id);
      out.push(r);
    }
    return out.slice(0, MY_HORSES_MAX);
  } catch { return []; }
}

// §56.13 2-2 マイホースをサーバへ写す(**丸ごと置換**)。⛔best-effort=
//   ★の切り替えを待たせない(await しない)し、失敗しても端末の中は巻き戻さない(正本は端末・§56.2)。
//   ⛔書き込みの口は writeMyHorses と clearMyHorses の**2つ**ある= どちらからも必ずここを通す。
//   ⚠長すぎる行だけ落とす(DB は100文字で断る)= 1頭のせいで**全部が写らなくなる**のを避ける。
//   実際の id は `nar:${馬名}` 等なので十数文字(§56.13 の実測)
function syncMyHorses(list) {
  try {
    const dev = deviceId(true);                       // ⛔初めて登録したときに端末の番号を作る
    if (!dev) return;
    const rows = [];
    for (const h of (Array.isArray(list) ? list : []).slice(0, MY_HORSES_MAX)) {
      const id = str(h && h.id);
      const name = str(h && h.name);
      if (!id || id.length > NOTE_HORSE_MAX || name.length > NOTE_HORSE_MAX) continue;
      rows.push({ id, name });
    }
    rpcNar('viewer_horses_save', { p_device: dev, p_horses: rows }).catch(() => { /* 写せないだけ */ });
  } catch { /* 端末の番号が作れない環境=写さない */ }
}

function writeMyHorses(list) {
  let ok = true;
  try { localStorage.setItem(MY_HORSES_KEY, JSON.stringify(list)); } catch { ok = false; }
  if (ok) syncMyHorses(list);                         // ⛔端末に入ってからサーバへ(端末が正本)
  return ok;
}

// 登録した馬(新しく登録した順)
export function listMyHorses() { return readMyHorses(); }

export function isMyHorse(id) {
  const s = str(id);
  return !!s && readMyHorses().some((h) => h.id === s);
}

// 登録/解除。戻り = {on, full}。full=true は「上限で登録できなかった」
export function toggleMyHorse(id, name) {
  const r = myHorseRow({ id, name });
  if (!r) return { on: false, full: false };
  const list = readMyHorses();
  const i = list.findIndex((h) => h.id === r.id);
  if (i >= 0) {
    list.splice(i, 1);
    writeMyHorses(list);
    return { on: false, full: false };
  }
  if (list.length >= MY_HORSES_MAX) return { on: false, full: true };
  list.unshift(r);                        // 新しく登録した馬を先頭に
  writeMyHorses(list);
  return { on: true, full: false };
}

export function clearMyHorses() {
  try { localStorage.removeItem(MY_HORSES_KEY); } catch { /* 消せなくても画面は動く */ }
  syncMyHorses([]);                                   // ⛔呼び出しが0でも塞いでおく(#252)
}

// §27.1 登録した馬のこれからの出走(公式は先の出馬表も持つので全15場ぶん出る)。**1クエリ**・5分メモ。
// 公式に馬ID が無いので馬名で引く=同名異馬が混ざり得る(§26.5 と同じ限界)
export function getMyHorseRuns(horses, from) {
  const names = [...new Set((Array.isArray(horses) ? horses : []).map((h) => str(h && h.name)).filter(Boolean))].sort();
  if (!names.length || !isDateStr(from)) return Promise.resolve([]);
  return memo(`myruns:${from}:${names.join(',')}`, 5 * MIN, async () => {
    let rows;
    try {
      rows = await sbNar('nar_runs?select=track,race_date,race_no,runner_number,horse_name' +
        `&horse_name=in.(${enc(quoteIn(names))})&race_date=gte.${from}&order=race_date.asc,race_no.asc,runner_number.asc&limit=300`);
    } catch { return []; }
    const out = [];
    for (const r of (Array.isArray(rows) ? rows : [])) {
      const prefix = narPrefixOf(r.track);
      const date = String(r.race_date ?? '');
      const no = num(r.race_no);
      const nm = str(r.horse_name);
      if (!prefix || !isDateStr(date) || no === null || !nm) continue;
      const v = VENUE_BY_PREFIX.get(prefix);
      out.push({
        raceId: v && v.supported !== 'none' ? `${prefix}/${date}/${no}` : null,
        venue: prefix, date, no, umaban: num(r.runner_number), horseName: nm,
      });
    }
    return out;
  });
}

// ---------------------------------------------------------------- §22.1 レース検索(nar_races)

export const SEARCH_RACES_MAX = 200;      // これ以上は返さない(呼び出し側が「しぼって」と出す)

// §112 クラスの絞り込み。表にクラスの列は無いので、**レース名・区分・条件**から当てる。
// ⛔サーバ(PostgREST)では**粗く**引き(SEARCH_RACES_MAX の上限はこの粗い方で効く)、
//   Ａ/Ｂ/Ｃ だけ手元でもう一度見る= 「ＡＢＣ杯」のような固有名の字を落とすため。
// ⛔上級/下級の並べ替え・色分けはしない(絞り込みだけ)。
export const SEARCH_CLASSES = [
  { key: 'grade', label: '重賞', kinds: ['重賞', '準重賞'] },
  { key: 'special', label: '特別', kinds: ['特別'] },
  // 手元の精密条件。レース名を NFKC で半角にしてから見る(Ｃ２－６ → C2-6)
  // 「AB混合」(高知)は A にも B にも当てる(「ABC杯」のような固有名は落としたまま)
  { key: 'A', label: 'Ａ', letter: 'Ａ', re: /(^|[^A-Z])A(?=[0-9一二三四五\-ー－\s組]|B混合|$)/ },
  { key: 'B', label: 'Ｂ', letter: 'Ｂ', re: /(^|[^A-Z]|A)B(?=[0-9一二三四五\-ー－\s組]|混合|$)/ },
  { key: 'C', label: 'Ｃ', letter: 'Ｃ', re: /(^|[^A-Z])C(?=[0-9一二三四五\-ー－\s組]|$)/ },
  { key: 'y2', label: '２歳', cond: '２歳' },
  // ⛔「３歳以上」は古馬の条件なので外す(２歳に「以上」は無いので y2 は外さない)
  { key: 'y3', label: '３歳', cond: '３歳', notCond: '３歳以上' },
];
const SEARCH_CLASS_BY_KEY = new Map(SEARCH_CLASSES.map((c) => [c.key, c]));
export function searchClass(key) { return SEARCH_CLASS_BY_KEY.get(str(key) || '') || null; }

// 条件つきでレースを探す。公式データ(全15場・2022-11〜)を1クエリで。
// §108 で **5 分メモ**にした= 「この条件で集計する」の開け閉め(URL に agg=1 を足すだけの描き直し)で
// 同じ検索を引き直さないため。⛔鍵は組み立てた問い合わせそのもの= 条件が違えば別物になる
export async function searchRaces(opts) {
  const o = opts && typeof opts === 'object' ? opts : {};
  const parts = ['select=track,race_date,race_no,race_name,distance_m,field_size,going'];
  const vs = (Array.isArray(o.venues) ? o.venues : [])
    .map((p) => VENUE_BY_PREFIX.get(String(p ?? '')))
    .filter(Boolean);
  if (vs.length) parts.push(`track=in.(${enc(quoteIn(vs.map(narTrackName)))})`);
  const dMin = num(o.distMin), dMax = num(o.distMax);
  if (dMin !== null) parts.push(`distance_m=gte.${dMin}`);
  if (dMax !== null) parts.push(`distance_m=lte.${dMax}`);
  if (isDateStr(o.from)) parts.push(`race_date=gte.${o.from}`);
  if (isDateStr(o.to)) parts.push(`race_date=lte.${o.to}`);
  // 入力の掃除は §14 の検索と同じ(フィルタ構文を壊す文字を落とす)
  const kw = cleanKw(o.kw);
  if (kw) parts.push(`race_name=like.*${enc(kw)}*`);
  // §112 クラス。⛔ここは**粗く**(上限 200 件はこの粗い方で数える)
  const cls = searchClass(o.cls);
  if (cls && cls.kinds) parts.push(`race_kind=in.(${enc(quoteIn(cls.kinds))})`);
  else if (cls && cls.letter) parts.push(`race_name=like.*${enc(cls.letter)}*`);
  else if (cls && cls.cond) {
    parts.push(`condition=like.*${enc(cls.cond)}*`);
    if (cls.notCond) parts.push(`condition=not.like.*${enc(cls.notCond)}*`);
  }
  parts.push('order=race_date.desc,race_no.asc', `limit=${SEARCH_RACES_MAX}`);
  const path = `nar_races?${parts.join('&')}`;
  const rows = await memo(`searchraces:${path}`, 5 * MIN, () => sbNar(path));
  const out = [];
  for (const r of (Array.isArray(rows) ? rows : [])) {
    const prefix = narPrefixOf(r.track);
    const date = String(r.race_date ?? '');
    const no = num(r.race_no);
    if (!prefix || !isDateStr(date) || no === null) continue;
    // §112 手元の精密条件(Ａ/Ｂ/Ｃ だけ)。⛔落とした数は数えも出しもしない= 返す配列だけ
    if (cls && cls.re && !cls.re.test(str(r.race_name).normalize('NFKC'))) continue;
    const v = VENUE_BY_PREFIX.get(prefix);
    const nc = nameCond(null, r.race_name, no);
    out.push({
      id: `${prefix}/${date}/${no}`,
      venue: prefix,
      venueName: v ? v.name : (str(r.track) || ''),
      date,
      no,
      name: nc.name,
      cond: nc.cond,
      distance: num(r.distance_m),
      going: baneiGoing(!!(v && v.banei), r.going),
      headCount: num(r.field_size),
    });
  }
  return out;
}

// ---------------------------------------------------------------- §111 制裁(nar_penalties)

// ⛔並べ替えは**日付の新しい順だけ**(人ごとの多い少ないは出さない= 価値判断をしない)
export const PENALTY_PAGE_SIZE = 40;
export const PENALTY_PERSON_MAX = 20;        // 騎手・調教師ページの節に出す件数
const PENALTY_MAX_PAGE = 100;
const PENALTY_FROM = '2026-01-01';           // 器に入っている一番古い開催日
const PENALTY_KINDS = ['戒告', '過怠金', '騎乗停止', '注意', 'その他'];
const PENALTY_PERIODS = ['30', '90', 'year'];
const PENALTY_COLS = 'penalty_id,track,race_date,race_no,person_kind,person_name,kind,detail,' +
  'suspension_from,suspension_through,source_url';

// URL から来る値は allowlist だけ(#113 fail-closed)。⛔知らない値は既定へ落とす
export function penaltyOptions(options) {
  const o = options && typeof options === 'object' ? options : {};
  const person = str(o.person) || null;
  const personKind = o.personKind === 'trainer' || o.personKind === 'jockey' ? o.personKind : null;
  const page = Number.isInteger(o.page) && o.page >= 1 && o.page <= PENALTY_MAX_PAGE ? o.page : 1;
  return {
    person: person && personKind ? person : null,
    personKind: person && personKind ? personKind : null,
    kind: PENALTY_KINDS.includes(o.kind) ? o.kind : null,
    venue: VENUE_BY_PREFIX.has(str(o.venue) || '') ? str(o.venue) : null,
    period: PENALTY_PERIODS.includes(String(o.period)) ? String(o.period) : '30',
    page,
  };
}

function penaltyRow(r) {
  const track = str(r && r.track);
  const prefix = track ? narPrefixOf(track) : null;
  const v = prefix ? VENUE_BY_PREFIX.get(prefix) : null;
  const date = str(r && r.race_date);
  const no = num(r && r.race_no);
  const id = str(r && r.penalty_id);
  const name = str(r && r.person_name);
  const detail = str(r && r.detail);
  if (!id || !isDateStr(date) || !name || !detail) return null;
  return {
    id,
    venue: prefix, venueName: v ? v.name : track, date,
    raceNo: no,
    raceId: v && v.supported !== 'none' && no !== null ? `${prefix}/${date}/${no}` : null,
    personKind: r.person_kind === 'trainer' ? 'trainer' : (r.person_kind === 'jockey' ? 'jockey' : 'other'),
    personName: name,
    kind: PENALTY_KINDS.includes(str(r.kind)) ? str(r.kind) : 'その他',
    detail,
    from: isDateStr(str(r.suspension_from)) ? str(r.suspension_from) : null,
    through: isDateStr(str(r.suspension_through)) ? str(r.suspension_through) : null,
    sourceUrl: str(r && r.source_url),
  };
}

// 制裁を引く。⛔1 本だけ・10 分メモ。person を渡すとその人の直近 PENALTY_PERSON_MAX 件。
// §118 データの状態(cloud/coverage.py が毎朝 nar_meta 'coverage' に書く 1 枚)。/status だけが読む。10 分メモ
export function parseCoverage(v) {
  const o = v && typeof v === 'object' ? v : null;
  if (!o || !Array.isArray(o.rows)) return null;
  const rows = o.rows.filter((r) => r && typeof r === 'object' && typeof r.kind === 'string')
    .map((r) => ({ kind: r.kind, venue: str(r.venue), expected: r.expected == null ? null : num(r.expected),
      have: num(r.have) ?? 0, last: isDateStr(r.last) ? r.last : null,
      missing: Array.isArray(r.missing) ? r.missing.filter(isDateStr) : [],
      stale_days: r.stale_days == null ? null : num(r.stale_days),
      warn_after: r.warn_after == null ? null : num(r.warn_after), note: str(r.note), src: str(r.src) }));
  return { built: str(o.built), today: isDateStr(o.today) ? o.today : null, rows };
}

export function getCoverage() {
  return memo('coverage', 10 * MIN, async () => {
    const rows = await sbNar('nar_meta?select=value&key=eq.coverage');
    return parseCoverage(Array.isArray(rows) && rows.length ? rows[0].value : null);
  });
}

export function getPenalties(options) {
  const st = penaltyOptions(options);
  const through = todayJST();
  const size = st.person ? PENALTY_PERSON_MAX : PENALTY_PAGE_SIZE;
  const parts = [`nar_penalties?select=${PENALTY_COLS}`];
  if (st.person) {
    parts.push(`person_kind=eq.${st.personKind}`, `person_name=eq.${enc(st.person)}`,
      `race_date=gte.${PENALTY_FROM}`);
  } else {
    const from = st.period === 'year' ? PENALTY_FROM : addDays(through, st.period === '90' ? -89 : -29);
    parts.push(`race_date=gte.${from}`, `race_date=lte.${through}`);
    if (st.kind) parts.push(`kind=eq.${enc(st.kind)}`);
    if (st.venue) parts.push(`track=eq.${enc(narTrackName(VENUE_BY_PREFIX.get(st.venue)))}`);
  }
  // ⛔offset の order は**一意**に(#468)= 日付の次に penalty_id
  parts.push('order=race_date.desc,penalty_id.asc', `limit=${size + 1}`);
  if (!st.person) parts.push(`offset=${(st.page - 1) * size}`);
  const path = parts.join('&');
  return memo(`penalties:${path}`, 10 * MIN, async () => {
    const raw = await sbNar(path);
    const list = Array.isArray(raw) ? raw : [];
    const rows = [];
    const seen = new Set();
    for (const item of list.slice(0, size)) {
      const row = penaltyRow(item);
      if (!row || seen.has(row.id)) continue;
      seen.add(row.id);
      rows.push(row);
    }
    return {
      rows, filters: st, page: st.page, pageSize: size,
      hasPrev: !st.person && st.page > 1,
      hasNext: !st.person && st.page < PENALTY_MAX_PAGE && list.length > size,
      capped: st.page === PENALTY_MAX_PAGE && list.length > size,
    };
  });
}

// ---------------------------------------------------------------- §108 この条件で集計(検索結果を数える)

// 1本の要求に入れるレース数。⛔URL の長さ(#365)と 1000 行の上限(#113)の両方に効く=
//   40 レース × 最大16頭 = 640 行 < 1000 行。検索の上限 200 レースなら **5本**まで
const AGG_RACES_PER_REQ = 40;

// 人気の帯。⛔ここ1か所で決める(画面に2つ目を作らない・§5.4)
export const AGG_POP_BANDS = [
  { key: 'p1', label: '1番人気', min: 1, max: 1 },
  { key: 'p2', label: '2番人気', min: 2, max: 2 },
  { key: 'p3', label: '3番人気', min: 3, max: 3 },
  { key: 'p46', label: '4〜6番人気', min: 4, max: 6 },
  { key: 'p7', label: '7番人気〜', min: 7, max: null },
];

// 検索で見つかったレースの出走を全部取る。list= [{venue,date,no}]。
// ⛔`Promise.allSettled`= 落ちた束は**空扱い**にして、取れた束だけで表を出す(返り値の failed を
//   画面が「一部を数えられませんでした」に使う)。⛔押したときだけ呼ぶ= 開かなければ通信は増えない
export function getRunsForRaces(list) {
  const keys = [];
  const seen = new Set();
  for (const r of (Array.isArray(list) ? list : [])) {
    const v = VENUE_BY_PREFIX.get(str(r && r.venue) || '');
    const date = str(r && r.date);
    const no = num(r && r.no);
    if (!v || !isDateStr(date) || no === null) continue;
    const id = `${v.prefix}/${date}/${no}`;
    if (seen.has(id)) continue;
    seen.add(id);
    keys.push({ track: narTrackName(v), date, no });
  }
  if (!keys.length) return Promise.resolve({ runs: [], reqs: 0, failed: 0 });
  return memo(`aggruns:${[...seen].sort().join(',')}`, 5 * MIN, async () => {
    const parts = chunk(keys, AGG_RACES_PER_REQ);
    const settled = await Promise.allSettled(parts.map((part) => {
      const cond = part.map((k) => `and(track.eq.${enc(k.track)},race_date.eq.${k.date},race_no.eq.${k.no})`).join(',');
      return sbNar('nar_runs?select=track,race_date,race_no,gate,finish,finish_note,popularity,jockey,trainer,' +
        `time_sec&or=(${cond})&limit=1000`);
    }));
    const runs = [];
    let failed = 0;
    for (const x of settled) {
      if (x.status !== 'fulfilled' || !Array.isArray(x.value)) { failed += 1; continue; }
      for (const r of x.value) runs.push(r);
    }
    return { runs, reqs: parts.length, failed };
  });
}

const AGG_GOING_ORDER = ['良', '稍重', '重', '不良'];

function aggCell(map, key) {
  let c = map.get(key);
  if (!c) { c = { n: 0, w: 0, p2: 0, p3: 0 }; map.set(key, c); }
  return c;
}
// 1走を数える。⛔p2/p3 は**累計**(連対・3着内)= courseRates(§103)と同じ形にする
function aggAdd(cell, finish) {
  cell.n += 1;
  if (finish === null) return;                 // 競走中止・失格は出走だけ数える
  if (finish === 1) cell.w += 1;
  if (finish <= 2) cell.p2 += 1;
  if (finish <= 3) cell.p3 += 1;
}
// まん中の値。⛔cloud/course_stats.py(statistics.median)と同じ= 偶数本は 2 つの平均・小数1桁
function aggMedian(xs) {
  const a = xs.slice().sort((x, y) => x - y);
  const i = Math.floor(a.length / 2);
  const v = a.length % 2 ? a[i] : (a[i - 1] + a[i]) / 2;
  return Math.round(v * 10) / 10;
}

// 見つかったレース(races= searchRaces の返り)と、その出走(runs= getRunsForRaces の runs)を数える。
// **純関数**(通信も DOM も見ない= tests から呼べる)。⛔率は出さない= 数だけ返し、割るのは画面の
// courseRates 1か所(§5.4)。⛔「走った」の判定は didRun(§51.2)だけ= 取消・除外は数えない。
// ⛔しきい値(何走以上で出すか・上位何人か)は画面の側に置く= ここは素の数を全部返す
export function aggregateRuns(races, runs) {
  const dist = new Map();
  const going = new Map();
  let raceN = 0;
  for (const r of (Array.isArray(races) ? races : [])) {
    const prefix = str(r && r.venue);
    const date = str(r && r.date);
    const no = num(r && r.no);
    if (!prefix || !isDateStr(date) || no === null) continue;
    raceN += 1;
    dist.set(`${prefix}/${date}/${no}`, num(r && r.distance));
    const g = str(r && r.going);
    if (g) going.set(g, (going.get(g) || 0) + 1);
  }
  const gate = new Map();
  const pop = new Map();
  const jockey = new Map();
  const trainer = new Map();
  const times = new Map();
  let runN = 0;
  for (const r of (Array.isArray(runs) ? runs : [])) {
    if (!r || !didRun(r)) continue;
    runN += 1;
    const finish = num(r.finish);
    const g = num(r.gate);
    if (g !== null && g >= 1 && g <= 8) aggAdd(aggCell(gate, String(g)), finish);
    const p = num(r.popularity);
    const band = p === null ? null : AGG_POP_BANDS.find((b) => p >= b.min && (b.max === null || p <= b.max));
    if (band) aggAdd(aggCell(pop, band.key), finish);        // 人気の無い走は数えない
    const jk = str(r.jockey);
    if (jk) aggAdd(aggCell(jockey, jk), finish);
    const tr = str(r.trainer);
    if (tr) aggAdd(aggCell(trainer, tr), finish);
    // 勝ち時計= 1着の時計だけ。⛔距離は**レースの側**から取る(走の行に距離の列は無い)
    if (finish === 1) {
      const sec = num(r.time_sec);
      const d = dist.get(`${narPrefixOf(r.track)}/${str(r.race_date)}/${num(r.race_no)}`);
      if (sec !== null && sec > 0 && d) {
        if (!times.has(d)) times.set(d, []);
        times.get(d).push(sec);
      }
    }
  }
  const named = (map) => [...map.entries()].map(([name, c]) => ({ name, ...c }))
    .sort((a, b) => b.w - a.w || b.n - a.n || a.name.localeCompare(b.name));
  const goingRank = (k) => (AGG_GOING_ORDER.indexOf(k) < 0 ? 90 : AGG_GOING_ORDER.indexOf(k));
  return {
    races: raceN,
    runs: runN,
    going: [...going.entries()].map(([name, n]) => ({ name, races: n }))
      .sort((a, b) => goingRank(a.name) - goingRank(b.name) || b.races - a.races),
    gate: [...gate.entries()].map(([name, c]) => ({ name, ...c }))
      .sort((a, b) => Number(a.name) - Number(b.name)),
    pop: AGG_POP_BANDS.filter((b) => pop.has(b.key)).map((b) => ({ name: b.label, ...pop.get(b.key) })),
    jockey: named(jockey),
    trainer: named(trainer),
    times: [...times.entries()].map(([d, xs]) => ({ d, n: xs.length, med: aggMedian(xs), best: Math.min(...xs) }))
      .sort((a, b) => a.d - b.d),
  };
}

// ---------------------------------------------------------------- §12.3 競馬場の集計(nar_venue_stats)

// 夜間集計 JSON(pipeline/sql/venue_stats.sql)の 1 行を VenueStats に正規化する。欠損は null / []
function rankRows(list, numericName) {
  if (!Array.isArray(list)) return [];
  const rows = list.map((r) => ({
    name: str(r && r.name),
    n: num(r && r.n) ?? 0, w1: num(r && r.w1) ?? 0, w2: num(r && r.w2) ?? 0, w3: num(r && r.w3) ?? 0,
    win: num(r && r.win), top2: num(r && r.top2), top3: num(r && r.top3), roi: num(r && r.roi),
  })).filter((r) => r.name !== null && r.n > 0);
  // 枠番・人気は番号順(SQL も番号順だが、文字列のまま来たときのために数値で並べ直す)
  if (numericName) rows.sort((a, b) => (num(a.name) ?? 99) - (num(b.name) ?? 99));
  return rows;
}
function recordOf(o) {
  const yen = num(o && o.y);
  if (yen === null) return null;
  return { yen, date: isDateStr(o.date) ? String(o.date) : null, no: num(o.no) };
}

// §39.3 全期間のレコード(期間タブに関わらず併記する)。⚠**当サイトにあるデータの中の最速**であって
// 主催者の発表するコースレコードではない(画面の注記でそう書く)
function alltimeOf(o) {
  const rec = num(o && o.record);
  if (rec === null) return null;
  return {
    record: rec,
    horse: str(o.horse),
    date: isDateStr(o.date) ? String(o.date) : null,
    going: str(o.going),                       // ⚠ばんえいは馬場水分率の数字('1.2')で来る
  };
}

// §39.2 距離ごとのランキング → [{distance, rows}]。集計側は種牡馬を `name`・枠番を `gate` で持つ。
// ⚠この経路には **2着・3着が無い**(距離×上位10で行が増えるので集計側が落としてある)=
// rankRows が 0 を入れるので、画面側は距離を選んだときだけ列を減らすこと
function byDistanceRows(list, key, numericName) {
  return (Array.isArray(list) ? list : []).map((d) => {
    const src = Array.isArray(d && d[key]) ? d[key] : [];
    const rows = rankRows(numericName ? src.map((r) => ({ ...r, name: r && r.gate })) : src, numericName);
    return { distance: num(d && d.distance), rows };
  }).filter((d) => d.distance !== null && d.rows.length).sort((a, b) => a.distance - b.distance);
}
function dateList(list) {
  return Array.isArray(list) ? list.map((d) => String(d ?? '')).filter(isDateStr) : [];
}
function venueStatsFromRow(row, v, period) {
  const s = row && row.stats && typeof row.stats === 'object' ? row.stats : {};
  const pz = s.payouts && typeof s.payouts === 'object' ? s.payouts : null;
  const rc = s.records && typeof s.records === 'object' ? s.records : {};
  const sc = s.schedule && typeof s.schedule === 'object' ? s.schedule : {};
  return {
    venue: v.prefix,
    period,
    races: num(s.races) ?? 0,
    runs: num(s.runs) ?? 0,
    from: isDateStr(s.from) ? String(s.from) : null,
    to: isDateStr(s.to) ? String(s.to) : null,
    jockeys: rankRows(s.jockeys, false),
    trainers: rankRows(s.trainers, false),
    sires: rankRows(s.sires, false),
    gates: rankRows(s.gates, true),
    popularity: rankRows(s.popularity, true),
    distances: (Array.isArray(s.distances) ? s.distances : []).map((d) => ({
      distance: num(d && d.distance), races: num(d && d.races) ?? 0, avgWin: num(d && d.avg_win), record: num(d && d.record),
      recordHorse: str(d && d.record_horse), recordDate: d && isDateStr(d.record_date) ? String(d.record_date) : null,
      recordGoing: str(d && d.record_going),          // §39.3 期間内の最速が出たときの馬場
      alltime: alltimeOf(d && d.alltime),             // §39.3 全期間のレコード(期間が「全期間」なら同じ値)
    })).filter((d) => d.distance !== null).sort((a, b) => a.distance - b.distance),
    // §39.2 距離チップ用。1回引いた JSON の中に全距離ぶん入っているので、切替で通信は増えない
    siresByDistance: byDistanceRows(s.sires_by_distance, 'sires', false),
    gatesByDistance: byDistanceRows(s.gates_by_distance, 'gates', true),
    going: (Array.isArray(s.going) ? s.going : []).map((g) => ({
      going: str(g && g.going), races: num(g && g.races) ?? 0, favWin: num(g && g.fav_win),
    })).filter((g) => g.going !== null && g.races > 0),
    // §30.7 馬場 × 距離の勝ち時計(集計側で5レース未満の組は落としてある)
    goingDistance: (Array.isArray(s.going_distance) ? s.going_distance : []).map((g) => ({
      going: str(g && g.going), distance: num(g && g.distance), races: num(g && g.races) ?? 0,
      avgWin: num(g && g.avg_win), best: num(g && g.best),
    })).filter((g) => g.going !== null && g.distance !== null && g.races > 0),
    payouts: pz ? {
      winAvg: num(pz.win_avg), trifectaAvg: num(pz.trifecta_avg), trifectaMax: num(pz.trifecta_max),
      manbakenRate: num(pz.manbaken_rate), favWinRate: num(pz.fav_win_rate),
    } : null,
    records: { maxWin: recordOf(rc.max_win), maxTrifecta: recordOf(rc.max_trifecta) },
    schedule: { next: dateList(sc.next).sort(), recent: dateList(sc.recent).sort().reverse() },
    updatedAt: str(row && row.updated_at),
  };
}

// 競馬場ページ用の集計(場 × 期間で 1 行)。行が無ければ null、通信失敗は throw(§3.1)。10 分メモ
export function getVenueStats(prefix, period) {
  const v = VENUE_BY_PREFIX.get(String(prefix ?? ''));
  const p = String(period ?? '');
  if (!v || !/^(all|\d{4})$/.test(p)) return Promise.resolve(null);
  return memo(`vstats:${v.prefix}:${p}`, 10 * MIN, async () => {
    const rows = await sbNar(`nar_venue_stats?select=stats,updated_at&track=eq.${enc(narTrackName(v))}&period=eq.${enc(p)}&limit=1`);
    return Array.isArray(rows) && rows.length ? venueStatsFromRow(rows[0], v, p) : null;
  });
}

// ---------------------------------------------------------------- §29.1 アクセスカウンター
// 旧DB に完動品がある: site_stats(key,n) + RPC bump_stat(k)(SECURITY DEFINER・加算して**新しい値を返す**)。
// 高知ビューアが 'total' / 'd_YYYYMMDD' で使っているので、こちらは 'nar:' を付けて相手の数字に混ぜない。
const PV_HOST = 'nar.yukochi.com';
const PV_TOTAL = 'nar:pv';

// 加算は**やり直さない**(fetchRetry ではなく fetchOnce)。5xx でも実際は加算されていることがあり、
// 数え直すと二重に増える。数え落としのほうが数え過ぎより無害
function bumpStat(k) {
  return fetchOnce(`${SUPABASE_URL}/rest/v1/rpc/bump_stat`, {
    method: 'POST',
    headers: {
      apikey: SUPABASE_KEY,
      Authorization: `Bearer ${SUPABASE_KEY}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ k }),
  }).then((res) => res.json());
}

// §71 W2 route family の計測。⭐CWA は SPA 遷移を数えない(2026-09-02 本番実測)ので、
// SPA を含む導線別 PV は独自計測でしか取れない。⛔キーは**固定 allowlist の9種だけ**
// (生URL・馬名・日付サフィックス禁止= bump_stat を無制限の logger にしない・§10 #78/B1)
const PV_FAMILY = {
  top: 'top', 'venue-day': 'venue-day', race: 'race', results: 'results',
  odds: 'odds', 'search-races': 'search', horse: 'horse', mymarks: 'my',
};
export function bumpRouteFamily(routeName) {
  try {
    if (typeof location === 'undefined' || location.hostname !== PV_HOST) return;
    const name = str(routeName);
    if (!name) return;                                   // 未マッチ(404)は数えない
    const fam = PV_FAMILY[name] || 'deep';               // 9種目= その他のデータ系ページ
    bumpStat(`nar:f_${fam}`).catch(() => { /* 計測は落ちても構わない */ });
  } catch { /* 同上 */ }
}

// §72 W4 導線イベント。⛔分析キーはこの6種だけ。URL・日付・場名・馬名を suffix に足さない。
// route family と同じ site_stats を使い、管理側は夜間に累積値の差分を保存する。
export const GROWTH_EVENTS = Object.freeze({
  TOP_TO_VENUE_DAY: 'top-venue-day',
  VENUE_DAY_TO_RACE: 'venue-day-race',
  RACE_TO_HORSE: 'race-horse',
  RACE_PREV_NEXT: 'race-prev-next',
  FAVORITE_ADD: 'favorite-add',
  EXTERNAL_OUT: 'external-out',
});

const PV_EVENT = new Map([
  [GROWTH_EVENTS.TOP_TO_VENUE_DAY, 'top_day'],
  [GROWTH_EVENTS.VENUE_DAY_TO_RACE, 'day_race'],
  [GROWTH_EVENTS.RACE_TO_HORSE, 'race_horse'],
  [GROWTH_EVENTS.RACE_PREV_NEXT, 'race_nav'],
  [GROWTH_EVENTS.FAVORITE_ADD, 'favorite_add'],
  [GROWTH_EVENTS.EXTERNAL_OUT, 'external_out'],
]);

export function bumpGrowthEvent(eventName) {
  try {
    if (typeof location === 'undefined' || location.hostname !== PV_HOST) return;
    const suffix = PV_EVENT.get(String(eventName ?? ''));
    if (!suffix) return;
    bumpStat(`nar:e_${suffix}`).catch(() => { /* 計測は画面を止めない */ });
  } catch { /* 同上 */ }
}

function pageCountOrNull(value) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

// 1ページビューを数えて**今日と通算の新しい値**を返す。数えない場所(本番ホスト以外=ローカル確認や
// Playwright の巡回)は null。片方だけ失敗したときは、取れた方を残して画面側で正直に表示する。
export async function bumpPageView() {
  if (typeof location === 'undefined' || location.hostname !== PV_HOST) return null;
  // どちらも加算APIなので再送しない。2本は並列に始め、片方の失敗で片方を捨てない。
  const [today, total] = await Promise.all([
    bumpStat(`nar:d_${todayJST().replace(/-/g, '')}`).then(pageCountOrNull).catch(() => null),
    bumpStat(PV_TOTAL).then(pageCountOrNull).catch(() => null),
  ]);
  return today === null && total === null ? null : { today, total };
}

// ---------------------------------------------------------------- §93 お知らせ(site_news)と管理者読み取り
// 表は旧プロジェクト(sb)の site_news。anon は published_at is not null の行だけ select できる。
// 書き込みは既存の Worker write proxy(X-Write-Token)経由= ここ以外に書き口を作らない。
// ⛔通信を増やすのは **/news と /admin を開いたときだけ**(トップは getNewsLatest の1本だけ)

// 種別の正本(画面はここから札の文字を引く。DB の kind がこの4つ以外なら 'notice' に寄せる)
// 2026-09-05 ユーザーFB: 「改善」(improve)を足した(DB の check は pipeline/sql/site_news_kind_improve_20260905.sql)
export const NEWS_KINDS = ['feature', 'improve', 'fix', 'notice'];
export const NEWS_KIND_LABEL = { feature: '新機能', improve: '改善', fix: '修正', notice: 'お知らせ' };
export const NEWS_X_MAX = 280;              // X 用の文面の上限(URL 込み・§93.6)
const NEWS_LIMIT_MAX = 200;

function newsRow(r) {
  const kind = str(r.kind);
  return {
    id: num(r.id),
    kind: NEWS_KINDS.includes(kind) ? kind : 'notice',
    title: str(r.title) || '',
    body: str(r.body) || '',
    url: str(r.url),
    publishedAt: str(r.published_at),
    xText: str(r.x_text),
    xPostedAt: str(r.x_posted_at),
  };
}

// 公開済みのお知らせ(新しい順)。opts.withX= X 用の文面と投稿済み時刻も引く(管理者の③タブだけ)。
// opts.fresh= memo を捨てて引き直す(公開した直後の一覧)
export function getNews(limit, opts) {
  const o = opts || {};
  const n = Math.min(Math.max(Number(limit) || 50, 1), NEWS_LIMIT_MAX);
  const cols = 'id,kind,title,body,url,published_at' + (o.withX ? ',x_text,x_posted_at' : '');
  const key = `news:${n}:${o.withX ? 'x' : '-'}`;
  if (o.fresh) cache.delete(key);
  return memo(key, 10 * MIN, async () => {
    const rows = await sb(`site_news?select=${cols}&published_at=not.is.null&order=published_at.desc&limit=${n}`);
    return (Array.isArray(rows) ? rows : []).map(newsRow);
  });
}

// 最新1件だけ(gnav の ● とトップの帯が使う)。⛔列を絞って1本で済ませる。無ければ null
export function getNewsLatest() {
  return memo('news:latest', 10 * MIN, async () => {
    const rows = await sb('site_news?select=id,kind,title,published_at&published_at=not.is.null&order=published_at.desc&limit=1');
    return Array.isArray(rows) && rows.length ? newsRow(rows[0]) : null;
  });
}

// 管理者の書き込み(Worker write proxy)。⛔やり直さない(fetchRetry を使わない)=
// 二重投稿になるより1回失敗して人が押し直すほうが安全。status を載せて画面が言い分ける
async function adminWrite(path, method, body) {
  const token = adminToken();
  if (!token) { const e = new Error('no token'); e.status = 401; throw e; }
  let res;
  try {
    res = await fetch(ADMIN_WORKER + path, {
      method,
      headers: {
        'X-Write-Token': token,
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Prefer: 'return=representation',
      },
      body: JSON.stringify(body),
    });
  } catch (err) { const e = new Error('network'); e.status = 0; throw e; }
  if (!res.ok) { const e = new Error(`admin write ${res.status}`); e.status = res.status; throw e; }
  const text = await res.text();
  const rows = text ? JSON.parse(text) : null;
  return Array.isArray(rows) && rows.length ? newsRow(rows[0]) : null;
}

export function postNews(row) {
  return adminWrite('/rest/v1/site_news', 'POST', row);
}

// ⛔id フィルタ必須(付け忘れると全行を書き換える)。id が数値でなければ投げる前に止める
export function patchNews(id, patch) {
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) { const e = new Error('bad id'); e.status = 400; return Promise.reject(e); }
  return adminWrite(`/rest/v1/site_news?id=eq.${n}`, 'PATCH', patch);
}

// §93.2 A 1レース分の陣営コメント・調教(競馬ブック由来)。**既存の読み口をそのまま叩く**。
// ⛔memo に載せない(§93.6: 管理者ページに本文を溜めない)。⛔401 を握りつぶさない=
//   「トークンが合わない」と「その日は空」を画面が言い分けられるよう status を載せて投げ直す。
// 返り= { danwa: [{umaban, horseName, horseId, headline, trainer, comment}], cyokyo: [...], updatedAt }
export async function adminRaceOwn(race) {
  const r = race && typeof race === 'object' ? race : null;
  const v = r && VENUE_BY_PREFIX.get(String(r.venue ?? ''));
  if (!v || v.supported !== 'chihou' || !str(r.sourceId)) return null;   // 対象外の場は**通信しない**
  let json;
  try {
    json = await adminGet(`/rpc/admin-chihou-own?race_id=${enc(String(r.sourceId))}`);
  } catch (err) {
    const m = /admin read (\d+)/.exec(String((err && err.message) || ''));
    const e = new Error('admin own');
    e.status = m ? Number(m[1]) : 0;
    throw e;
  }
  if (!json || !json.ok) return { danwa: [], cyokyo: [], updatedAt: null };
  let updatedAt = null;
  const at = (row) => { const s = str(row && row.updated_at); if (s && (!updatedAt || s > updatedAt)) updatedAt = s; };
  const danwa = (Array.isArray(json.danwa) ? json.danwa : []).map((row) => {
    at(row);
    return {
      umaban: num(row.umaban),
      horseName: str(row.horse_name) || '',
      horseId: kbId(row.horse_id),
      headline: str(row.headline),
      trainer: str(row.trainer),
      comment: str(row.comment),
    };
  });
  const cyokyo = (Array.isArray(json.cyokyo) ? json.cyokyo : []).map((row) => {
    at(row);
    return {
      umaban: num(row.umaban),
      horseName: str(row.horse_name) || '',
      arrow: str(row.arrow),
      tanpyo: str(row.tanpyo),
      works: (Array.isArray(row.works) ? row.works : []).filter((w) => w && typeof w === 'object').map(cyokyoWork),
    };
  });
  return { danwa, cyokyo, updatedAt };
}

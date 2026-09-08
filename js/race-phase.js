// §71 W1: レースの「今どの段階か」の共有導出。DESIGN.md §71.1。
// ⛔純関数・DOM/通信/Date.now を触らない(now は必ず注入)= node から試験できる。
// ⛔時計だけで「発走済(走り終わった)」と**断定しない**= 分かるのは「発走時刻を過ぎた」まで。
//   結果が来たかは race.status(done/pending)だけが知っている(§Codex A7 の型)。
// ⚠3分の猶予(旧 top.js STARTED_AFTER_MIN)は**用途別の値**として残す= 次走一覧に残すかの判定にだけ使う。

export const CLOSING_BEFORE_MIN = 2;   // 発走2分前=「締切」表示(投票の締切が発走の少し前のため)
export const GRACE_AFTER_MIN = 3;      // 発走+3分までは次走一覧に残す(発走直後に行が消し飛ばないように)

// 'HH:MM' → 分。形が違えば null(推定しない)
export function hhmmToMin(hhmm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm ?? ''));
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

// race = { date, status(done|pending|pre), postTime } / nowMin = JST の分 / today = 'YYYY-MM-DD'
// 返り値(全部同時に返す= 呼び出し側が用途別に選ぶ):
//   resultKnown   … 結果が取得済み(status done)
//   pendingPast   … 過ぎた日で結果未着(status pending)
//   minutesToPost … 発走まで何分(今日でない・時刻不明は null。負=過ぎた)
//   closing       … 発走2分前を過ぎた(まだ発走時刻前)
//   postPassed    … 発走時刻を過ぎた
//   inGrace       … 発走+3分以内(次走一覧に残す猶予)
//   leftBoard     … 次走一覧から落としてよい(done か、発走+3分超)
export function phaseOf(race, nowMin, today) {
  const r = race && typeof race === 'object' ? race : {};
  const done = r.status === 'done';
  const pendingPast = r.status === 'pending';
  const isToday = String(r.date ?? '') === String(today ?? '');
  const post = isToday ? hhmmToMin(r.postTime) : null;
  const toPost = post === null || nowMin === null || nowMin === undefined ? null : post - nowMin;
  const postPassed = done || pendingPast || (toPost !== null && toPost <= 0);
  const closing = toPost !== null && toPost <= CLOSING_BEFORE_MIN && toPost > 0;
  const inGrace = toPost !== null && toPost <= 0 && -toPost < GRACE_AFTER_MIN;
  return {
    resultKnown: done,
    pendingPast,
    minutesToPost: toPost,
    closing,
    postPassed,
    inGrace,
    leftBoard: done || (toPost !== null && -toPost >= GRACE_AFTER_MIN && toPost <= 0),
  };
}

// §80 A ①「次の発走」= その日その場でまだ発走板から落ちていない**最初の1レース**。
// ⛔判定は phaseOf(leftBoard)を通す= トップの発走板・場×日・レースの R 帯が同じ物差しになる(§5.4)。
// races = [{no, postTime, status, date}] / nowMin = JST の分 / today = 'YYYY-MM-DD'。
// ⛔今日以外の日は null(過ぎた日・先の日に「次の発走」は無い)。
// ⛔発走時刻が読めないレースは飛ばす(何分後かを言えないので「次」と名乗らせない)。
// ⛔並びは呼び出し側の順に頼らずレース番号の昇順で見る。
export function nextRace(races, nowMin, today) {
  const day = String(today ?? '');
  const list = (Array.isArray(races) ? races : []).filter((r) => r && typeof r === 'object' &&
    String(r.date ?? '') === day && hhmmToMin(r.postTime) !== null);
  if (!list.length) return null;
  return list.slice().sort((a, b) => (Number(a.no) || 0) - (Number(b.no) || 0))
    .find((r) => !phaseOf(r, nowMin, day).leftBoard) || null;
}

// レース番号だけが要る呼び出し側のための薄い皮。無ければ null
export function nextRaceNo(races, nowMin, today) {
  const r = nextRace(races, nowMin, today);
  return r && Number.isFinite(Number(r.no)) ? Number(r.no) : null;
}

// 発走板・場カードの右端表示 [文言, class]。⛔文言はここ1か所(トップ・場×日・結果で共有)。
// §71 P1-5(Codex監査): ⛔leftBoard(次走一覧から外す判定)を表示語に流用しない=
// **時計だけで「発走済」と断定しない**。発走時刻を過ぎて結果未着は何分経っても「結果待ち」
// (「発走済」「確定」を名乗れるのは結果が取得できたときだけ)
export function boardRight(phase, postTimeText) {
  if (phase.resultKnown) return ['確定', 'done'];
  if (phase.pendingPast) return ['結果待ち', 'done'];
  if (phase.minutesToPost === null) return [postTimeText || '', ''];
  if (phase.postPassed) return ['結果待ち', 'done'];
  if (phase.closing) return ['締切', 'done'];
  const n = phase.minutesToPost - CLOSING_BEFORE_MIN;
  return ['あと' + n + '分', n <= 5 ? 'soon' : ''];
}

// §71 P1-4(Codex監査): 開催中止日の推定を**1か所**に(results.js の既存契約 §21.2-8 を共有化)。
// rows = [{status, hasResult, hasPayout}]。⛔partial(取得失敗)の日で呼ばない= 失敗を中止と推定しない
export function cancelledDay(date, today, rows) {
  const list = Array.isArray(rows) ? rows : [];
  return String(date ?? '') < String(today ?? '') && list.length > 0 &&
    list.every((r) => r && r.status === 'pending' && !r.hasResult && !r.hasPayout);
}
export const CANCELLED_TEXT = 'この日の開催は中止になったとみられます(結果・払戻がどのレースにもありません)';

// 「結果がまだ無いレース」の注記(レースページ・結果一覧・場×日で共有)。
// ⛔発走時刻を過ぎても「発走前」と言わない・結果が無いのに「発走済(確定)」とも言わない
export const POST_PASSED_TEXT = '結果はまだ出ていません(発走時刻を過ぎています)';
export function pendingNote(phase) {
  if (phase.resultKnown) return null;
  if (phase.pendingPast) return '結果は準備中です';
  if (phase.postPassed) return POST_PASSED_TEXT;
  return '発走前です';
}

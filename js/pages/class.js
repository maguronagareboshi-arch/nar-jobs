// クラスと賞金の台帳 `/class`・`/class/:prefix`。DESIGN §38 2-A(調査書 docs/research/class_prize_survey_20260827.md §2)。
// ⛔ここは**一次資料の写し**だけを置く。馬ごとの現在値(あといくら)は別(データ側の準備待ち)。
// ⛔金沢・岩手は閾値そのものが公表されていない=「無い」とはっきり書く(推定で線を引かない=§5.3)。
// ⛔年度で数値が変わる(調査書 §2.5)ので、採取日と出典を必ず添える。
// ⛔定数はこのファイル1か所(§5.4「表と実装が食い違わないよう定数は1か所」)。計算側はここから import すること。
// 通信ゼロ(すべて定数)。

import { explain, explainFull } from './explain.js';

export const ASOF = '2026-08-27';        // 一次資料を読んだ日(全場この日に採取)

// 決まり方の3つの型(調査書 §2.1)。閲覧者向けの言い方にする(専門用語を出さない)
const KIND = {
  prize: { label: '金額で決まる', hint: '賞金の額に線が引いてあり、超えると上のクラスへ上がります' },
  point: { label: '点数で決まる', hint: '着順ごとの持ち点を足していき、決められた点に届くと上がります' },
  rank: { label: '上位から順に決まる', hint: '金額の線は無く、そのときの上位から順に決める方式です' },
};

// 一次資料の写し。prefixes = この規則が使われている競馬場
export const SYSTEMS = [
  {
    id: 'monbetsu', name: '門別', prefixes: ['monbetsu'], kind: 'prize',
    basis: '番組賞金(主催者が決めた独自の指数・上限4,000万円)',
    classes: '2歳1〜3組 / 3歳条件1〜4組 / Ａ1〜Ａ4 / Ｂ1〜Ｂ4 / Ｃ1〜Ｃ4',
    lines: [
      ['Ａ1', '800万円 超'], ['Ａ2', '800万円 以下'], ['Ａ3', '600万円 以下'], ['Ａ4', '500万円 以下'],
      ['Ｂ1', '400万円 以下'], ['Ｂ2', '350万円 以下'], ['Ｂ3', '300万円 以下'], ['Ｂ4', '250万円 以下'],
      ['Ｃ1', '200万円 以下'], ['Ｃ2', '160万円 以下'], ['Ｃ3', '120万円 以下'], ['Ｃ4', '80万円 以下'],
    ],
    up: '番組賞金がその線を越えた時点で上がります。3歳から古馬へ入るのは、第1回終了時に300万円超・第2回200万円超・第3回150万円超、第4回のあとは全馬です',
    down: '年1回(シーズン初めの当初格付)。4〜11月の1シーズン制で、4〜5歳は前年度の最終額の80%−α、6歳は70%−α、7歳以上は60%−α に減らして持ち越します',
    src: [['令和8年度 番組編成要領(PDF)', 'https://www.hokkaidokeiba.net/hkj/henseiyouryou/2026henseiyouryou.pdf'],
      ['掲載ページ', 'https://www.hokkaidokeiba.net/racedata/hensei/hkj.php']],
    note: 'この場だけ、馬ごとの級と番組賞金が公式の「級別表」で発表されます。当サイトはそれをそのまま馬柱の左に出しています(朱の「公式」バッジ)',
  },
  {
    id: 'iwate', name: '岩手(盛岡・水沢)', prefixes: ['morioka', 'mizusawa'], kind: 'rank',
    basis: '格付賞金の上位順',
    classes: 'Ａ / Ｂ1 / Ｂ2 / Ｃ1 / Ｃ2 ＋ 3歳・2歳',
    lines: null,
    up: '上位順なので、順位が上がれば自動で上のクラスへ入ります',
    down: '2開催が終わるごと(シーズン中に10回前後)。直近15競走(通算12開催以降は12競走)で計算し直すので、上がることも下がることもあります',
    src: [['令和8年度 番組編成要領及び諸規程集(PDF)', 'https://www.iwatekeiba.or.jp/dir/wp-content/uploads/2026/03/2026_iwate_hensei_yoryo.pdf']],
  },
  {
    id: 'obihiro', name: '帯広ばんえい', prefixes: ['obihiro'], kind: 'prize',
    basis: '通算収得賞金',
    classes: 'オープン / Ａ1 / Ａ2 / Ｂ1〜Ｂ4 / Ｃ1 / Ｃ2 ＋ 2歳',
    lines: [
      ['オープン', '1,300万円 以上'], ['Ａ1', '1,300万円 未満'], ['Ａ2', '1,000万円 未満'],
      ['Ｂ1', '850万円 未満'], ['Ｂ2', '670万円 未満'], ['Ｂ3', '550万円 未満'], ['Ｂ4', '430万円 未満'],
      ['Ｃ1(3・4歳)', '340万円 未満'], ['Ｃ2(3・4歳)', '220万円 未満'],
    ],
    up: '線を越えた時点で上がります。その回の番組は初日の4日前に発表されます',
    down: '「年◯回」という決まりは書かれていません。実際には「通算=令和5年度以降」という4年度ぶんの数え方が、年度替わりで1年ぶん落ちることが、下がる仕組みになっています',
    src: [['令和8年度 番組編成要領(PDF)', 'https://www.banei-keiba.or.jp/data/fd/000000/00/0000000003/data_KdrQ9c5h1743730712.pdf'],
      ['掲載ページ', 'https://www.banei-keiba.or.jp/race_program.php']],
  },
  {
    id: 'nankan', name: '南関東(大井・川崎・船橋・浦和)', prefixes: ['ooi', 'kawasaki', 'funabashi', 'urawa'], kind: 'point',
    basis: '格付ポイント(令和6年1月1日から。それ以前は賞金の積み上げ)',
    classes: 'Ａ1Ａ2 / Ｂ1〜Ｂ3 / Ｃ1〜Ｃ3 の8クラス(それぞれ 一組・二組…)',
    lines: 'nankan',
    up: '1〜5着でもらう持ち点の通算が、基準の点に届いたら上がります。数えるのは前々開催までのぶんです',
    down: '上半期(1〜6月)と下半期(7〜12月)で基準の表が入れ替わる年2回、加えて1月1日で馬齢が1つ上がります。基準は齢とともに上がるので、稼がない馬は自然に下がります。反映は開催最終日の全レースが終わったあとです',
    src: [['番組について(公式Q&A)', 'https://www.nankankeiba.com/info/qanda/program.html'],
      ['レースについて(公式Q&A)', 'https://www.nankankeiba.com/info/qanda/race.html']],
    note: '3・4歳が古馬に入る時期は 3歳2月Ａ1 → 3月Ａ2 → 4月Ｂ1 → 5月Ｂ2 → 6月Ｂ3 → 7月Ｃ1 → 10月Ｃ2 → 4歳1月Ｃ3 の順です',
  },
  {
    id: 'kanazawa', name: '金沢', prefixes: ['kanazawa'], kind: 'rank',
    basis: '番組賞金の上位順',
    classes: '一般Ａ1Ａ2 / Ｂ1Ｂ2 / Ｃ1Ｃ2 ＋ 3歳Ａ・Ｂ ＋ 2歳',
    lines: null,
    up: '上位順なので順位が上がれば自動です。3歳から一般へは通算第14回で一斉、それ以前でも3歳Ａ1組の勝ち馬か、番組賞金250万円超なら入ります',
    down: '毎開催(年22回)ごとに格付が発表されます。7歳以上は30%減額・3歳が入るときは40%減額・年度替わりで数え始めの日が繰り上がります',
    src: [['令和8年度 番組編成要綱・報償金等支給要綱(PDF)', 'https://www.kanazawakeiba.com/wp-content/uploads/2026/04/R8_bangumi_hensei_houshou.pdf'],
      ['掲載ページ', 'https://www.kanazawakeiba.com/race/page-31368/']],
  },
  {
    id: 'kasamatsu', name: '笠松', prefixes: ['kasamatsu'], kind: 'prize',
    basis: '番組賞金(東海地区で共通)',
    classes: 'Ａ級 / Ｂ級 / Ｃ級(それぞれ1組2組…) ＋ 3歳・2歳',
    lines: [['Ａ級', '450万円 以上'], ['Ｂ級', '250万円 以上 450万円 未満'], ['Ｃ級', '250万円 未満'],
      ['3歳', '440万円 未満(令和9年1月から450万円未満)'], ['2歳', '450万円 未満']],
    up: '線に届いたときに上がります。適用は、番組の発表日の直前に終わった東海地区の開催最終日の時点です',
    down: '年4回の「番組賞金の調整」(6月・9月・12月・3月の月末開催が終わったあと)。調整の額は番組賞金の25%です。その期間に勝った馬と、調整額を超える賞金を得た馬は差し引きません。3歳限定は9月末まで(10月に一斉編入)',
    src: [['令和8年度 番組要綱・賞金等支給基準(PDF)', 'https://www.kasamatsu-keiba.com/resources/pdfs/news/2026/1774670513_37e97f66111794f4064f.pdf']],
  },
  {
    id: 'nagoya', name: '名古屋', prefixes: ['nagoya'], kind: 'prize',
    basis: '番組賞金(東海地区で共通・笠松と同じ額)',
    classes: '一般格Ａ / Ｂ / Ｃ級(それぞれ1組2組…) ＋ 3歳格・2歳格',
    lines: [['Ａ級', '450万円 以上'], ['Ｂ級', '250万円 以上 450万円 未満'], ['Ｃ級', '250万円 未満'],
      ['3歳格', '440万円 未満'], ['2歳格', '450万円 未満']],
    up: '線に届いたときに上がります',
    down: '四半期ごとの年4回「番組賞金額の調整」(第7・13・19・26回名古屋開催が終わったあと)。調整の額は25%です。前回の調整日以降に一般格で勝った馬と、調整額を超える馬は差し引きません。3歳格は第13回までです',
    src: [['競馬番組要綱(PDF)', 'https://www.nagoyakeiba.com/info/program/file/cb9f549e8a8adb8b2a9f4fd2c033a617431aebc8.pdf'],
      ['掲載ページ', 'https://www.nagoyakeiba.com/info/program/outline/index.html']],
  },
  {
    id: 'hyogo', name: '兵庫(園田・姫路)', prefixes: ['sonoda', 'himeji'], kind: 'point',
    basis: 'ポイント制(3歳以上)。2歳だけは番組賞金',
    classes: '4歳以上(令和8年7月4日から3歳以上) Ａ1Ａ2Ｂ1Ｂ2Ｃ1Ｃ2Ｃ3 / 3歳だけの Ａ・Ｂ・Ｃ1・Ｃ2 / 2歳は格付なし',
    lines: [['Ａ1', '760 以上'], ['Ａ2', '630〜759'], ['Ｂ1', '500〜629'], ['Ｂ2', '350〜499'],
      ['Ｃ1', '230〜349'], ['Ｃ2', '100〜229'], ['Ｃ3', '0〜99'],
      ['3歳Ａ', '330 以上'], ['3歳Ｂ', '230〜329'], ['3歳Ｃ1', '130〜229'], ['3歳Ｃ2', '0〜129']],
    up: '今のクラスの上限を超えたら上がります。⚠上がったあとは、そのクラスの下限の点まで戻されます(重賞で上がったときは戻されません)。重賞1着は点に関係なく1つ上へ',
    down: 'おおむね2か月ごと(9月・11月・1月・3月ほか)。⚠下がる方は点ではなく、同じクラスでの近3走の着順の合計が多い順に1クラス下がります。下がった馬の点は「前のクラスの下限−60」(Ｃ3へ下がるときは60、3歳Ｃ2へは90)。Ａ1とＣ3は下がりません',
    src: [['令和8年度 番組要綱(PDF)', 'https://www.sonoda-himeji.jp/resources/pdfs/outline/2026/1777357602_55f7128522fb9f5bbcbf.pdf'],
      ['掲載ページ', 'https://www.sonoda-himeji.jp/race/rank/'],
      ['格付修正の時期(公式ニュース)', 'https://www.sonoda-himeji.jp/news/detail/298']],
    add: '点の足し方: 普通の重賞 1着100 / 2着24 / 3着12 / 4着8 / 5着6、グレードのある重賞 100 / 34 / 18 / 10 / 8',
  },
  {
    id: 'kochi', name: '高知', prefixes: ['kochi'], kind: 'prize',
    basis: '番組賞金',
    classes: 'Ａ / Ｂ / Ｃ1 / Ｃ2 / Ｃ3上 / Ｃ3下 ＋ 3歳・2歳',
    lines: [['Ａ', '1,100万円 超'], ['Ｂ', '700万円 超 〜 1,100万円 以下'], ['Ｃ1', '460万円 超 〜 700万円 以下'],
      ['Ｃ2', '300万円 超 〜 460万円 以下'], ['Ｃ3上', '200万円 超 〜 300万円 以下'], ['Ｃ3下', '200万円 以下']],
    up: '2歳・3歳は番組賞金100万円に届くと一般格へ入ります。3歳格は9月27日まで(9月28日に一斉編入)',
    down: '1サイクルが終わるごと(年29サイクル)。加えて9月1日に「数え始めの日」が5か月ぶん繰り上がるので、そこで一斉に下がります',
    src: [['令和8年度 番組編成要領(PDF)', 'https://www.keiba.or.jp/wp/wp-content/uploads/2026/04/c5839a921547136ea50a798417603595.pdf'],
      ['掲載ページ', 'https://www.keiba.or.jp/?p=122535']],
    note: '令和8年度に線が全面的に変わりました(上の額は改定後のものです)',
  },
  {
    id: 'saga', name: '佐賀', prefixes: ['saga'], kind: 'prize',
    basis: '番組賞金(初出走からの通算・1〜5着の本賞金。付加賞は入れません)',
    classes: 'Ａ1 / Ａ2 / Ｂ / Ｃ1 / Ｃ2 ＋ 3歳格・2歳格(Ｃ3はありません)',
    lines: [['Ａ1', '1,000万円 以上'], ['Ａ2', '600万円 以上 1,000万円 未満'], ['Ｂ', '300万円 以上 600万円 未満'],
      ['Ｃ1', '150万円 以上 300万円 未満'], ['Ｃ2', '150万円 未満'], ['3歳格', '3歳の間(300万円未満)']],
    up: '線の額を超えたときは次回の競馬から上のクラスへ入ります',
    down: '一斉に下げる仕組みは無く、年2回にあたる「賞金の減額」で行います。8月競馬(3歳が一般格に入るとき)=3歳は50%減額・4歳と5歳はそれぞれ50万円減額。1月=6歳は2歳のときの賞金を全額減額、7歳は3歳のとき、8歳は4歳のときのぶんを減額します',
    src: [['令和8年度 番組編成要領(PDF)', 'https://www.sagakeiba.net/wp-content/uploads/2026/04/2026bangumi_hensei.pdf'],
      ['掲載ページ', 'https://www.sagakeiba.net/raceinfo/summary/']],
  },
];

// 南関の格付基準表(単位=ポイント・令和6年1月1日から)。列= 3歳/4歳/5歳/6歳/7歳/8歳以上
export const NANKAN_TH = {
  ages: ['3歳', '4歳', '5歳', '6歳', '7歳', '8歳以上'],
  kami: [['Ａ1', [2800, 3400, 4300, 5000, 5500, 5900]], ['Ａ2', [2000, 2200, 2500, 3200, 3700, 4100]],
    ['Ｂ1', [1500, 1700, 1900, 2200, 2700, 3000]], ['Ｂ2', [1100, 1200, 1400, 1700, 2000, 2200]],
    ['Ｂ3', [700, 800, 1000, 1300, 1600, 1800]], ['Ｃ1', [null, 500, 700, 1000, 1300, 1500]],
    ['Ｃ2', [null, 200, 400, 700, 1000, 1200]]],
  shimo: [['Ａ1', [3000, 3600, 4400, 5200, 5700, 5900]], ['Ａ2', [2200, 2300, 2600, 3400, 3900, 4100]],
    ['Ｂ1', [1700, 1800, 2000, 2500, 2900, 3000]], ['Ｂ2', [1200, 1300, 1500, 1800, 2100, 2200]],
    ['Ｂ3', [800, 900, 1100, 1400, 1700, 1800]], ['Ｃ1', [500, 600, 800, 1100, 1400, 1500]],
    ['Ｃ2', [200, 300, 500, 800, 1100, 1200]]],
  c3: 'Ｃ3 は上の表に届かない馬(=残り)です。3歳は4月以降 20 以上',
};

const BY_PREFIX = new Map();
for (const s of SYSTEMS) for (const p of s.prefixes) BY_PREFIX.set(p, s);
export function systemOf(prefix) { return BY_PREFIX.get(prefix) || null; }

export function title(params) {
  if (params && params.prefix) {
    const s = systemOf(params.prefix);
    return s ? s.name + 'のクラスと賞金 — 昇級の線・格付け替えの時期' : 'このページはありません';
  }
  return '地方競馬 クラスと賞金の決まり方(全15場)';
}

// §79 P4 用語(閲覧者の言葉で。⛔主催者の発表と当サイトの計算を混ぜない)
const TERMS = [
  ['番組賞金', '主催者がクラス分けのために数える賞金。実際に受け取った額と同じではなく、他の競馬場やＪＲＡで得た賞金は決められた割合で換算し、期間や減額の決まりがあります。'],
  ['収得賞金', '主催者(地方競馬全国協会)の記録にある、その馬が地方競馬で得た本賞金の合計。当サイトの「収得賞金」はこの公式の値です。'],
  ['格付ポイント', '南関東4場で使う持ち点。1〜5着で決まった点がもらえ、その合計と馬齢で格が決まります。'],
  ['組', '同じクラスの中をさらに分けたまとまり(Ｃ３一、Ｃ３二三 など)。番組賞金やポイントの順で上から分けます。'],
  ['一斉編入', '2歳・3歳限定のクラスにいた馬が、決まった日に古馬のクラスへまとめて入ること。'],
  ['格付け替え・降級', '一定の時期に、クラスを決め直すこと。稼いだ額を減らす(減額)・数え始めの日をずらす(起算日の繰り上げ)などの方法で、稼がない馬が下のクラスへ移ります。'],
  ['格上挑戦', '自分のクラスより上のレースに出ること。出馬表の条件と馬のクラスが違うのはこのためです。'],
  ['線(昇級の線)', 'このクラスに入るために必要な金額・点数。当サイトの「あと◯」はこの線からの引き算です。'],
  ['展開の見立て', '直近5走の最初のコーナー通過順(公式)から、逃げ/先行/差し/追込の型を当サイトが推定したもの。通過順が2走未満の馬は型を付けません。ペース見込みは、逃げ候補の中でいちばん速いテンから当サイトが機械的に決めています。'],
  ['間隔・距離・クラスのチップ', '直近の走(地方)と今回の違いを当サイトが並べたものです。中央の走は数えません。'],
  ['テン', '直近3〜5走の前半3F(高知は当サイトの映像計測)から、その競馬場・距離の平年との差を当サイトが出したもの。マイナスが速い。3走未満の馬には出しません。'],
  ['産駒の成績', '父(または母父)が同じ馬の地方競馬での結果を当サイトが数えたもの。産駒の出走が30走に満たない種牡馬は産駒の一覧だけ。'],
  ['条件で集計', 'レース検索で見つかったレース(最大200)の出走を、枠番・人気・騎手・調教師・勝ち時計で当サイトが数えたもの。'],
  ['コース別データ', '過去1年の公式の結果を、距離ごとに枠番・序盤の位置・逃げ馬で当サイトが数えたもの。勝ち時計だけは過去3年を馬場状態とクラスごとに出しています。当日のレースは入れていません。'],
  ['馬場傾向', 'その日の全レースから、時計(過去3年の標準との差)・前後(序盤コーナーの順位と着順の相関)・内外(枠番と着順の相関)を当サイトが機械的に数えたもの。偏りがその競馬場の平年の上下1割から外れた日だけ言葉を付けます。'],
];

// §79 P4 よくある疑問。⛔画面と JSON-LD(FAQPage)で**同じ1か所**から出す(食い違いを作らない)
const FAQ = [
  ['Ｃ３とＣ１はどちらが上ですか',
    'Ｃ１が上です。どの場でも Ａ→Ｂ→Ｃ の順、同じ字の中では数字が小さいほど上です(Ａ１＞Ａ２、Ｃ１＞Ｃ２＞Ｃ３)。ただし帯広ばんえいには「オープン」が最上位にあります。'],
  ['地方競馬のクラスはどう決まりますか',
    '競馬場ごとに違います。門別・帯広・笠松・名古屋・高知・佐賀は賞金の額、南関東4場と兵庫は持ち点、金沢と岩手はそのときの上位から順に決めます。'],
  ['勝つとすぐ上のクラスに上がりますか',
    '線を越えた時点で上がる場と、次の開催や格付け替えのときに反映される場があります。南関東は前々開催までの点で決まるため、勝ってすぐには変わりません。'],
  ['なぜ強い馬が下のクラスにいるのですか',
    '多くの場で、決まった時期に賞金を減額したり数え始めの日をずらしたりするため、勝てない期間が続くと下のクラスへ移ります。転入直後や3歳から古馬に入ったときにも起こります。'],
  ['馬柱の「あと◯」は何ですか',
    '主催者が公表している線から、その馬の現在の額や点を引いた値です。当サイトの引き算であり、昇級を約束するものではありません。'],
  ['金沢や岩手に線が無いのはなぜですか',
    '両場は賞金の順位で上から順にクラスを決める方式で、金額の線そのものが公表されていないためです。当サイトでは推測して線を引くことはしません。'],
  ['収得賞金と番組賞金は同じですか',
    '違います。収得賞金は公式の記録にある本賞金の合計、番組賞金は各主催者がクラス分けのために換算・減額して数える額です。'],
  ['数字はいつのものですか',
    '一次資料を読んだ日を各ページに出しています。数値は年度で変わるので、実際の出走前には主催者の発表をご確認ください。'],
];

// ⛔JSON-LD は inert データ(CSP の script-src は実行を止めるだけで ld+json は実行されない)。
// 二重差しを防ぐため data-ld="faq" で1つだけ置き、ページを離れるときに外す
function setFaqLd() {
  if (typeof document === 'undefined') return () => {};
  const drop = () => {
    const n = document.head.querySelector('script[data-ld="faq"]');
    if (n) n.remove();
  };
  drop();
  const s = document.createElement('script');
  s.type = 'application/ld+json';
  s.dataset.ld = 'faq';
  s.textContent = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: FAQ.map(([q, a]) => ({
      '@type': 'Question', name: q, acceptedAnswer: { '@type': 'Answer', text: a },
    })),
  });
  document.head.appendChild(s);
  return drop;
}

export async function render(el, params, ctx) {
  if (params && params.prefix) { return renderOne(el, params.prefix, ctx); }
  const { ui, router } = ctx;
  const rows = SYSTEMS.map((s) => ({ s, kind: KIND[s.kind].label, basis: s.basis, down: shortDown(s) }));
  el.innerHTML =
    '<div class="eyebrow">クラスと賞金</div>' +
    '<div class="venue-head"><div><h1>クラスと賞金の決まり方</h1>' +
    '<div class="sub">全15場。どのクラスにいるか・どうすれば上がるか・いつ下がるかを、主催者の発表そのままで並べています</div>' +
    '</div></div>' +
    explain('class', ctx) +
    ui.card('<p class="lede">地方競馬の馬は、稼いだ賞金や持ち点で「クラス」に分けられ、同じクラスの馬どうしで走ります。' +
      'Ａ・Ｂ・Ｃの字と数字(Ｃ３など)がそのクラスの名前です。</p>' +
      '<p>決め方は競馬場ごとに違います。金額の線で決める場・点数で決める場・そのときの上位から順に決める場の3通りがあります。</p>' +
      '<p>このページでは、15場それぞれの決め方・上がる条件・下がる時期を、主催者の発表そのままで並べています。' +
      '各馬がいまどこにいるかは、レースページの出馬表と馬柱に出しています。</p>' +
      ui.kvList(Object.keys(KIND).map((k) => ({ label: KIND[k].label, value: KIND[k].hint })))) +
    ui.secHead('15場の比べかた', { h1: false }) +
    ui.table([
      { label: '競馬場', render: (r) => r.s.prefixes.map((p) => ui.venueIcon(p)).join('') + ' ' +
        router.link('/class/' + r.s.prefixes[0], ui.escapeHTML(r.s.name)) },
      { label: '決まり方', key: 'kind' },
      { label: '何で決まるか', key: 'basis' },
      { label: '線', render: (r) => (r.s.lines ? '<span class="cl-yes">あり</span>' : '<span class="cl-no">公表なし</span>') },
      { label: '格付け替えの時期', key: 'down' },
    ], rows, { className: 'cl-tbl' }) +
    ui.note('競馬場の名前を押すと、その場の線の表と、元にした資料が見られます。' +
      '⚠<b>金沢と岩手には線がありません</b>——上位から順に決める方式で、金額の線そのものが公表されていないためです。' +
      '当サイトで勝手に線を作ることはしません。') +
    ui.note('一次資料を読んだ日: ' + ASOF + '。<b>数値は年度で変わります</b>。' +
      '実際の出走前には各主催者の発表をご確認ください。') +
    ui.note('<b>各馬の格と収得賞金は、レースページの出馬表と馬柱に出しています</b>' +
      '(主催者の発表値そのままで、当サイトの計算ではありません)。') +
    '<div id="terms"></div>' + ui.secHead('用語') +
    ui.card(ui.kvList(TERMS.map(([k, v]) => ({ label: ui.escapeHTML(k), value: ui.escapeHTML(v) })))) +
    '<div id="faq"></div>' + ui.secHead('よくある疑問') +
    ui.card('<dl class="cl-faq">' + FAQ.map(([q, a]) =>
      '<dt>' + ui.escapeHTML(q) + '</dt><dd>' + ui.escapeHTML(a) + '</dd>').join('') + '</dl>') +
    explainFull('class', ctx);
  return setFaqLd();
}

function shortDown(s) {
  const t = s.down.split('。')[0];
  return t.length > 32 ? t.slice(0, 31) + '…' : t;
}

function renderOne(el, prefix, ctx) {
  const { ui, router, data } = ctx;
  const s = systemOf(prefix);
  // ⚠notFound() は題と noindex を替えるだけ=**本文はページ側が出す**(他ページと同じ作法)。
  // §38 2-A のときに /class/zzz が真っ白(題だけ)だったのを直した
  if (!s) {
    router.notFound('この競馬場のクラス表はありません');          // SEO P3b
    el.innerHTML = ui.errorBox('この競馬場のクラス表は見つかりませんでした', { homeLink: true });
    return;
  }
  const parts = [];
  parts.push(ui.secHead('クラスの体系') +
    ui.card('<p class="lede">' + ui.escapeHTML(s.classes) + '</p>' +
      ui.kvList([{ label: '何で決まるか', value: ui.escapeHTML(s.basis) },
        { label: '決まり方', value: KIND[s.kind].label + ' — ' + KIND[s.kind].hint }])));

  if (s.lines === 'nankan') {
    parts.push(ui.secHead('昇級の線(格付基準)') +
      '<div class="cl-half">上半期(1〜6月)</div>' + thTable(ui, NANKAN_TH.kami) +
      '<div class="cl-half">下半期(7〜12月)</div>' + thTable(ui, NANKAN_TH.shimo) +
      ui.note(NANKAN_TH.c3 + '。表の数字は「その点以上ならそのクラス」という意味です'));
  } else if (s.lines) {
    parts.push(ui.secHead('昇級の線') +
      ui.table([{ label: 'クラス', key: 'cls' }, { label: '線', key: 'line' }],
        s.lines.map((r) => ({ cls: r[0], line: r[1] })), { className: 'cl-tbl' }));
  } else {
    parts.push(ui.secHead('昇級の線') +
      ui.card('<p class="lede">この競馬場は<b>金額の線が公表されていません</b>。そのときの上位から順にクラスが決まる方式です。</p>' +
        '<p>そのため「あと◯円で昇級」という言い方ができません。' +
        '当サイトでは、公表されていないものを推測して線を引くことはしません。</p>'));
  }
  if (s.add) parts.push(ui.note(ui.escapeHTML(s.add)));
  parts.push(ui.secHead('上がるとき') + ui.card('<p>' + ui.escapeHTML(s.up) + '</p>'));
  parts.push(ui.secHead('下がるとき・格付け替えの時期') + ui.card('<p>' + ui.escapeHTML(s.down) + '</p>'));
  if (s.note) parts.push(ui.note(ui.escapeHTML(s.note)));
  parts.push(ui.secHead('元にした資料と当サイトの計算') +
    ui.card('<ul class="cl-src">' + s.src.map((x) =>
      '<li><a href="' + ui.attr(x[1]) + '" target="_blank" rel="noopener noreferrer">' +
      ui.escapeHTML(x[0]) + '</a></li>').join('') + '</ul>' +
      '<p class="dim">読んだ日: ' + ASOF + '。数値は年度で変わります。</p>'));
  const rooms = s.prefixes.map((p) => router.link('/venue/' + p, ui.escapeHTML(venueName(p)))).join('・');
  // §38 2-A/1-C 南関東4場は「あといくら」が馬柱に出ている
  parts.push(ui.note(s.kind === 'point'
    ? '<b>' + ui.escapeHTML(venueName(prefix)) + 'は、各馬の「格」「格付ポイント」「1つ上の線まであと何点か」を馬柱の左欄に出しています</b>' +
      '(レースページ →「馬柱」タブ)。格とポイントは主催者の発表値そのままで、その馬の「◯月◯日現在」も添えています。' +
      '「あと◯」は上の表からの引き算で、昇級を約束するものではありません(反映は主催者の格付け替えで行われます)。' +
      '⚠馬名で引き当てているので、同じ名前の馬がいる場合は取り違えることがあります。' +
      '発表に載っていない馬(未格付・転入直後・2歳など)は何も出しません。この競馬場のデータは ' + rooms + ' から見られます。'
    : '各馬が「あといくらで上がるか」は準備中です。この競馬場のデータは ' + rooms + ' から見られます。'));

  el.innerHTML =
    '<div class="eyebrow">' + router.link('/class', 'クラスと賞金') + ' ｜ ' + ui.escapeHTML(s.name) + '</div>' +
    '<div class="venue-head"><div><h1>' + ui.escapeHTML(s.name) + 'のクラスと賞金</h1>' +
    '<div class="sub">' + KIND[s.kind].label + ' ｜ ' + ui.escapeHTML(s.basis) + '</div></div></div>' +
    '<div class="cl-nav">' + SYSTEMS.map((x) =>
      router.link('/class/' + x.prefixes[0], ui.escapeHTML(x.name),
        { class: 'chip' + (x.id === s.id ? ' on' : '') })).join('') + '</div>' +
    // §79 P4 その日の実例は別便(本文は待たせない)。⛔空なら節ごと消える
    '<div data-cl-today></div>' +
    parts.join('') +
    ui.note('言葉の意味は' + router.link('/class#terms', '用語') + '、よくある質問は' +
      router.link('/class#faq', 'よくある疑問') + 'にまとめています。');

  let alive = true;   // ページを離れた後に差し込まない
  loadToday(el, prefix, ctx, () => alive).catch(() => { /* 実例が出ないだけ */ });
  return () => { alive = false; };
}

// §79 P4 「今日走る馬から」+「今日のレース(クラス別)」。⛔本文を待たせない別便・空なら節ごと出さない。
// ⛔今日その場の開催が無ければ**次の開催日**(それも無ければ直近の開催日)で出し、いつの日かを必ず書く
async function loadToday(el, prefix, ctx, isAlive) {
  const { ui, router, data } = ctx;
  const box = el.querySelector('[data-cl-today]');
  if (!box || typeof data.getVenueDates !== 'function') return;
  const today = data.todayJST();
  let dates = [];
  try { dates = await data.getVenueDates(prefix); } catch { dates = []; }
  if (!isAlive() || !Array.isArray(dates) || !dates.length) return;
  const future = dates.filter((d) => d >= today).sort();
  const date = future.length ? future[0] : dates[0];
  if (!date) return;
  const [dayR, exR] = await Promise.all([
    typeof data.getRaceDay === 'function' ? data.getRaceDay(date).catch(() => null) : Promise.resolve(null),
    typeof data.getClassExamples === 'function' ? data.getClassExamples(prefix, date).catch(() => []) : Promise.resolve([]),
  ]);
  if (!isAlive()) return;
  const races = (dayR && Array.isArray(dayR.races) ? dayR.races : []).filter((r) => r.venue === prefix);
  const isToday = date === today;
  const when = ui.fmtDate(date, 'long') + (isToday ? '(今日)' : (date > today ? '(次の開催)' : '(直近の開催)'));
  const out = [];

  const all = Array.isArray(exR) ? exR : [];
  // §79 P3 「あと◯」が計算できる場(いまは高知)は**線に近い順**に。⛔他の場に自動で広がる書き方にする
  const REGION = { kasamatsu: 'tokai', nagoya: 'tokai', sonoda: 'hyogo', himeji: 'hyogo' };   // race.js の CALC_REGION と同じ
  const sameRegion = (a, b) => a === b || (!!REGION[a] && REGION[a] === REGION[b]);
  const gapOf = (x) => {
    const c = x && x.calc && !x.calc.hide && sameRegion(x.calc.prefix, prefix) && x.calc.next ? x.calc.next : null;
    const g = c && Number.isFinite(Number(c.gap)) ? Number(c.gap) : null;
    return g !== null && g > 0 ? g : null;
  };
  const near = all.filter((x) => gapOf(x) !== null).sort((a, b) => gapOf(a) - gapOf(b));
  const useGap = near.length > 0;
  const ex = (useGap ? near : all).slice(0, 5);
  if (ex.length) {
    const byNo = new Map(races.map((r) => [Number(r.no), r]));
    const raceCell = (x) => {
      const r = byNo.get(Number(x.raceNo));
      const label = x.raceNo + 'R';
      return r ? router.link('/race/' + r.id, ui.escapeHTML(label), { class: 'horse-link' }) : ui.escapeHTML(label);
    };
    const nameCell = (x) => router.link('/horse/' + encodeURIComponent('nar:' + x.horseName),
      ui.escapeHTML(x.horseName), { class: 'horse-link' });
    const cols = useGap
      ? [
        { label: '馬名', align: 'left', render: nameCell },
        { label: '表の位置', align: 'left', render: (x) => ui.escapeHTML(String((x.calc && x.calc.cls) || '—')) },
        {
          label: 'あと', align: 'left',
          render: (x) => 'あと ' + ui.escapeHTML(x.calc.basis === 'point' ? String(gapOf(x)) + 'ポイント' : manYen(gapOf(x))) + 'で<b>' +
            ui.escapeHTML(String(x.calc.next.cls)) + '</b>',
        },
        { label: 'レース', align: 'left', render: raceCell },
      ]
      : [
        { label: '馬名', align: 'left', render: nameCell },
        { label: '直近の条件', align: 'left', render: (x) => (x.lastCls ? ui.escapeHTML(x.lastCls) : '—') },
        { label: '収得賞金', num: true, render: (x) => ui.escapeHTML(manYen(x.prize)) },
        { label: 'レース', align: 'left', render: raceCell },
      ];
    out.push(ui.secHead(isToday ? '今日走る馬から' : 'この開催の馬から', { note: when }) + ui.table(cols, ex) +
      ui.note(useGap
        ? '線に近い順に5頭を出しています。「あと◯」は、当サイトが<b>主催者の番組' + (near[0].calc.basis === 'point' ? '要綱' : '編成要領') + '</b>から計算した' +
          (near[0].calc.basis === 'point'
            ? '着順ポイント(1着100・2着24・3着12・4着8・5着6)と線の差です。'
            : '番組賞金(' + windowText(near[0].calc.window, ui) + '前日までの収得賞金を換算)と線の差です。') +
          '<b>主催者の発表ではなく、昇級を約束するものではありません</b>。「表の位置」は線の表での位置で、' +
          '主催者が発表した格ではありません。'
        : '収得賞金の多い順に5頭を出しています。値は<b>主催者(地方競馬全国協会)の発表</b>の写しで、' +
          '当サイトの計算ではありません。「あと◯」は準備中です。'));
  }

  if (races.length) {
    const groups = new Map();
    for (const r of races) {
      const k = (typeof data.raceClassOf === 'function' ? data.raceClassOf(r.name, r.kind) : null) || r.cond || 'その他';
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r);
    }
    const body = [...groups.entries()].map(([k, list]) =>
      '<div class="cl-day"><h3 class="year-head">' + ui.escapeHTML(k) +
      '<span class="dim">' + list.length + 'レース</span></h3><div class="cl-races">' +
      list.sort((a, b) => a.no - b.no).map((r) =>
        router.link('/race/' + r.id, ui.escapeHTML(r.no + 'R') +
          (r.postTime ? '<small>' + ui.escapeHTML(ui.fmtTime(r.postTime)) + '</small>' : '') +
          (r.headCount != null ? '<small>' + r.headCount + '頭</small>' : ''),
        { class: 'dchip' })).join('') + '</div></div>').join('');
    out.push(ui.secHead((isToday ? '今日' : 'この日') + 'のレース(クラス別)', { note: when }) + ui.card(body));
  }
  box.innerHTML = out.join('');
}

// calc.window '2024-09-01〜' → 「2024年9月1日から」(場ごとに違うので文言に固定しない)
function windowText(w, ui) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(w || ''));
  return m ? ui.escapeHTML(Number(m[1]) + '年' + Number(m[2]) + '月' + Number(m[3]) + '日から') : '';
}

// 円 → 「747万円」(1桁まで)。⛔race.js と同じ言い方(§5.4 の「言い方は1か所」に反するが、
//   ここは表示のためだけの小さな関数=定数を持たない。値そのものは公式の写し)
function manYen(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  if (n === 0) return '0円';
  const man = Math.round(n / 1000) / 10;
  return (Number.isInteger(man) ? String(man) : man.toFixed(1)) + '万円';
}

const VENUE_NAME = {
  monbetsu: '門別', morioka: '盛岡', mizusawa: '水沢', obihiro: '帯広ば', ooi: '大井', kawasaki: '川崎',
  funabashi: '船橋', urawa: '浦和', kanazawa: '金沢', kasamatsu: '笠松', nagoya: '名古屋',
  sonoda: '園田', himeji: '姫路', kochi: '高知', saga: '佐賀',
};
function venueName(p) { return VENUE_NAME[p] || p; }

function thTable(ui, rows) {
  const cols = [{ label: 'クラス', key: 'cls' }].concat(
    NANKAN_TH.ages.map((a, i) => ({ label: a, key: 'a' + i })));
  const data = rows.map((r) => {
    const o = { cls: r[0] };
    r[1].forEach((v, i) => { o['a' + i] = v === null ? '—' : String(v); });
    return o;
  });
  return ui.table(cols, data, { className: 'cl-tbl cl-th' });
}

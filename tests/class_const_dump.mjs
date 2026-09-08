// §79 P3 class.js の定数(SYSTEMS / NANKAN_TH / ASOF)を JSON で吐く小道具。
// cloud/class_calc.py がこれを node で叩いて線の表を読む(⛔Python 側に線の表を写さない=§5.4)。
//   node tests/class_const_dump.mjs > /tmp/class_const.json
import { SYSTEMS, NANKAN_TH, ASOF } from '../js/pages/class.js';
process.stdout.write(JSON.stringify({ ASOF, SYSTEMS, NANKAN_TH }));

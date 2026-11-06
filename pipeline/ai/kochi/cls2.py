# 場ごとのレース名からクラスを読む(2026-11-06・早見表用)
# 年齢を限ったレース(2 歳・3 歳。「3 歳以上」は除かない)・新馬・未勝利・オープン・交流・混ぜたクラス(A2B1・B2B3・C3-2C4-1)は None。
# 例: 佐賀 C2-10組 → C2・門別 C4-3 → C4・高知 C3-7 → C3・名古屋 C16組 → C16・盛岡 C1七組 → C1・大井 C2十二 → C2・佐賀 B → B・笠松 C級サバイバル → C
import re
import unicodedata

_TOK = re.compile(r'(?<![A-Za-z0-9])([ABC])(\d{0,2})(?![A-Za-z0-9])')
_TOK_DASH = re.compile(r'(?<![A-Za-z0-9])([ABC])(\d{1,2})(?=-)')
_MIX = re.compile(r'[ABC]\d{0,2}(-\d+)?[~〜・]?[ABC]\d')


def cls2(name):
    if name is None:
        return None
    n = unicodedata.normalize('NFKC', str(name))
    if re.search(r'新馬|未勝利|オープン|OP|交流|JRA|中央|デビュ', n):
        return None
    n2 = re.sub(r'[2-9]歳以上', '', n)
    if re.search(r'[23]歳', n2):
        return None
    if _MIX.search(n2):
        return None
    m = _TOK_DASH.search(n2) or _TOK.search(n2)
    if not m:
        return None
    return m.group(1) + m.group(2)


if __name__ == '__main__':
    for s in ['C2-10組', 'C4-3', 'C3-7', 'C16組', 'C1七組', 'C2十二 十三', 'B', '3歳B二特編', 'A2B1', 'C3-2C4-1', 'C3 4歳イ',
              'C1-2~C3-1', 'SAGA', 'C2一3歳以上', 'C級サバイバル選抜(ロ)', 'B3B4-1', '宝満山(ほうまんざん)特別A1', '2歳新馬', 'アジア・アジアパラ応援9B10']:
        print(s, '→', cls2(s))

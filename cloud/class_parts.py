"""レース名 → 級・組・付帯(サイト nar-viewer js/class-parts.js raceClassParts の Python 写し・2026-11-04)。
⛔読み方を変えるときは JS と両方を直し、tests/test_class_parts_js.py の照合(本物の名前で JS と一致)を流す。
  race_class_parts(name, kind, track) → {"cls", "grp", "age", "extra", "label", "src"} または None
"""
import re

KAN = "一二三四五六七八九十"
UP = "ABCD"
_HALF = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
_HALF[0x3000] = 0x20
AFTER0 = re.compile(r"^[0-9一二三四五六七八九十\-―‐−級]")
ORD = re.compile(r"[0-9](st|nd|rd|th)$", re.I)
STRICT = re.compile(r"^[0-9]+([一二三四五六七八九十\-―‐−組]|$)")
WORDS = (("新馬", "新馬"), ("初出走", "新馬"), ("未勝利", "未勝利"), ("未受賞", "未受賞"), ("オープン", "オープン"))
NK = ("名古屋", "笠松")
# 金沢・南関の 2022 年までの詰めた書き方= 級は字+1 桁・後ろの数字は組(Ａ２１= A2 の 1組・Ｃ２１２１３= C2 の 12・13組)。JS の PACKED と同じ
PACKED = ("金沢", "大井", "浦和", "川崎", "船橋")
AGE_RE = re.compile(r"([2-4])歳(以上|上)?")


def _packed_group(d):
    """詰めた組の数字 → '12・13組'。1 通りにしか読めないときだけ(「12」は 12組 とも 1・2組 とも読める= None)。JS の packedGroup と同じ"""
    reads = []
    if 0 < len(d) <= 2 and d[0] != "0":
        reads.append([int(d)])
    for first in (1, 2):
        ns, i, ok = [], 0, True
        while i < len(d):
            ln = len(str(ns[-1] + 1)) if ns else first
            piece = d[i:i + ln]
            if len(piece) < ln or piece[0] == "0" or (ns and int(piece) != ns[-1] + 1):
                ok = False
                break
            ns.append(int(piece))
            i += ln
        if ok and len(ns) >= 2:
            reads.append(ns)
    return "・".join(str(n) for n in reads[0]) + "組" if len(reads) == 1 else None


def half(s):
    return s.translate(_HALF)


def _latin(c):
    return bool(c) and c.isascii() and c.isalpha()


def _lower(c):
    return bool(c) and c.isascii() and c.islower()


def kanji_num(k):
    if not k:
        return None
    d = lambda c: KAN.index(c) + 1 if c in KAN else 0  # noqa: E731
    if k == "十":
        return 10
    t = k.find("十")
    if t < 0:
        return d(k) if len(k) == 1 else None
    hi = 1 if t == 0 else d(k[0])
    lo = 0 if t == len(k) - 1 else d(k[t + 1])
    return hi * 10 + lo


def _find_letter(h, pass0):
    for i in range(len(h)):
        if h[i] not in UP:
            continue
        if _lower(h[i + 1] if i + 1 < len(h) else ""):
            continue
        j = i
        while j < len(h) and _latin(h[j]) and not _lower(h[j]):
            j += 1
        blk = h[i:j]
        if any(c not in UP for c in blk):
            continue
        rest = h[j:]
        if i > 0 and _latin(h[i - 1]):
            ordm = ORD.search(h[max(0, i - 6):i])
            if not ordm and not (len(blk) == 1 and STRICT.match(rest)):
                continue
        if pass0 and not AFTER0.match(rest):
            continue
        if len(blk) >= 2 and rest.startswith(" "):
            continue
        return i, blk
    return None


def _take_group(r):
    m = re.match(r"[-―‐−]([0-9]+)(組)?", r)
    if m:
        return m.group(1) + "組", r[m.end():]
    m = re.match(r"([一二三四五六七八九十]+)(組)?((?: [一二三四五六七八九十]+(?:組)?)*)", r)
    if m:
        parts = [m.group(1)] + [re.sub("組$", "", x) for x in m.group(3).split(" ") if x]
        ns = [kanji_num(x) for x in parts]
        if all(n is not None for n in ns):
            return "・".join(str(n) for n in ns) + "組", r[m.end():]
    m = re.match(r"([0-9]+)(組)?", r)
    if m:
        return m.group(1) + "組", r[m.end():]
    return None, r


def _tidy(x):
    t = re.sub(r"^[\s・\-―‐−]+", "", str(x or ""))
    t = re.sub(r"\s+$", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t or None


def race_class_parts(name, kind=None, track=None):
    s = re.sub(r"[\s　]+", " ", "" if name is None else str(name)).strip()
    if not s:
        return None
    if kind in ("重賞", "準重賞"):
        return None
    h = half(s)
    nk = str(track or "") in NK
    hit = _find_letter(h, True)
    knd = "letter" if hit else None
    start = hit[0] if hit else -1
    word = None
    if not hit:
        for w, lab in WORDS:
            p = h.find(w)
            if p < 0:
                continue
            word = (w, lab, p)
            break
        if word:
            knd = "word"
            start = word[2]
            before = h[:word[2]]
            ai = -1
            for k in range(len(before) - 2, -1, -1):
                if re.match(r"[2-4]", before[k]) and before[k + 1] == "歳":
                    ai = k
                    break
            if ai >= 0 and word[2] - (ai + 2) <= 6:
                start = ai
    if not knd:
        hit = _find_letter(h, False)
        if hit:
            knd, start = "letter", hit[0]
    if not knd:
        m = AGE_RE.search(h)
        if m:
            knd, start = "age", m.start()
    if not knd:
        return None
    src = s[start:].strip() or None
    t = h[start:].strip()
    cls = grp = None
    rest = ""
    cls_label = None
    mid = ""
    if knd == "letter":
        blk = hit[1]
        p = len(blk)
        cls = blk
        if nk and len(blk) == 1:
            if t[p:p + 1] == "級":
                p += 1
            m = re.match(r"([0-9]+)(組)?", t[p:])
            if m:
                grp = m.group(1) + "組"
                p += m.end()
            rest = t[p:]
            if not grp and t[len(blk):len(blk) + 1] == "級":
                g = re.search("(^|[^A-Za-z])" + blk + "([0-9]+)(組)?", rest)
                if g:
                    grp = g.group(2) + "組"
                    rest = rest[:g.start() + len(g.group(1))] + rest[g.end():]
            if grp and grp.endswith("組"):
                rest = re.sub("(^|[^A-Za-z])" + blk + grp.replace("組", "") + "(組)?(?![0-9])", r"\1", rest, count=1)
            cls_label = cls if re.search(r"[0-9]", cls) else cls + "級"
        else:
            dd = re.match(r"[0-9]{2,}(組)?", t[p:])
            # 前に「3歳」がある名前(金沢の ３歳Ｂ１０= 3 歳戦の番号は 14 まで)は割らない
            if len(blk) == 1 and dd and str(track or "") in PACKED and not re.search(r"[2-4]歳", h[:hit[0]]):
                ds = dd.group(0)
                if not dd.group(1) and t[p + len(ds):p + len(ds) + 1] == "歳":
                    ds = ds[:-1]   # Ｃ１３歳= C1 と 3歳(最後の数字は馬齢)
                cls += ds[0]   # 字+1 桁が級・残りの数字が組(馬齢・付帯は下の共通の読み)
                p += len(ds)
                grp = _packed_group(ds[1:].replace("組", "")) if len(ds) > 1 else None
                rest = t[p:]
                cls_label = cls
            else:
                if len(blk) == 1 and dd:
                    cls += dd.group(0).replace("組", "")
                    p += len(dd.group(0))
                    return {"cls": cls, "grp": None, "age": None, "extra": _tidy(t[p:]), "label": t[:p], "src": src}
                if len(blk) == 1 and re.match(r"[0-9]", t[p:p + 1]):
                    cls += t[p]
                    p += 1
                if t[p:p + 1] == "級":
                    p += 1
                grp, rest = _take_group(t[p:])
                cls_label = cls
    elif knd == "word":
        cls = word[1]
        wp = t.find(word[0])
        mid = t[:wp]
        rest = t[wp + len(word[0]):]
        cls_label = cls
    else:
        rest = t
    age = None
    mm = AGE_RE.search(mid)
    if mm:
        age = mm.group(1) + "歳" + ("以上" if mm.group(2) else "")
        mid = mid[:mm.start()] + " " + mid[mm.end():]
    am = None if age else AGE_RE.search(rest)
    if am:
        age = am.group(1) + "歳" + ("以上" if am.group(2) else "")
        rest = rest[:am.start()] + " " + rest[am.end():]
    elif not age:
        lm = re.search(r"([2-4])歳(以上|上)?\s*(?:牝馬|牡馬|せん馬)?\s*$", h[:start])
        if lm:
            age = lm.group(1) + "歳" + ("以上" if lm.group(2) else "")
    if knd == "age":
        cls = age.replace("以上", "") if age else None
        cls_label = cls
    if knd != "letter":
        g, r2 = _take_group(_tidy(rest) or "")
        if g:
            grp, rest = g, r2
    extra = _tidy((_tidy(mid) or "") + " " + (_tidy(rest) or ""))
    label = cls_label or ""
    if knd == "word" and age:
        label = age + label
    if grp:
        label += (" " if grp.endswith("組") else "") + grp
    return {"cls": cls, "grp": grp, "age": age, "extra": extra, "label": label or None, "src": src}

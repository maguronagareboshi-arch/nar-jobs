# -*- coding: utf-8 -*-
"""§89 公表された疾病・競走事故履歴。

既存許可済みの NAR 成績 PDF と repository 内の楽天/SAT原本だけを読み、
`nar_horse_health_events` を source 単位で冪等同期する。画面向けの推測はしない。

  python cloud/horse_health.py --source nar                 # 直近7日、dry-run
  python cloud/horse_health.py --source nar --apply
  python cloud/horse_health.py --source auction --apply
  python cloud/horse_health.py --source nar --start 2026-03-01 --end 2026-03-31

環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。ローカルだけ --env を指定できる。
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from load_nar_official import load_env  # noqa: E402

PARSER_VERSION = "health-v1.1.1"   # 1 記述 1 件(分類が複数当たっても鍵を重ねない・再解析が要る)
JST = dt.timezone(dt.timedelta(hours=9))
MIN_DATE = dt.date(2026, 1, 1)
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 150
MIN_HOST_INTERVAL = 0.5
UA = "nar-viewer-health/1.0 (+maguronagareboshi@gmail.com)"
AUCTION_ROOT = HERE / "data" / "auction"
PUBLIC_PDF_GUARD_CODES = frozenset({
    "pdf_size", "pdf_magic", "pdf_content_type", "pdf_pages", "pdf_redirect_host",
})

# NAR DataDownload と同じ公式場名。門別だけ URL の綴りが mombetsu であることを実PDFで確認済み。
NAR_PDF = {
    "帯広ば": ("03", "obihiro"),
    "門別": ("36", "mombetsu"),
    "盛岡": ("10", "morioka"),
    "水沢": ("11", "mizusawa"),
    "浦和": ("18", "urawa"),
    "船橋": ("19", "funabashi"),
    "大井": ("20", "oi"),
    "川崎": ("21", "kawasaki"),
    "金沢": ("22", "kanazawa"),
    "笠松": ("23", "kasamatsu"),
    "名古屋": ("24", "nagoya"),
    "園田": ("27", "sonoda"),
    "姫路": ("28", "himeji"),
    "高知": ("31", "kochi"),
    "佐賀": ("32", "saga"),
}
NAR_TRACK_BY_CODE = {code: track for track, (code, _slug) in NAR_PDF.items()}

ALLOWED_SOURCE_HOSTS = {
    "www.keiba.go.jp",
    "keiba.go.jp",
    "auction.keiba.rakuten.co.jp",
    "www.sat-auction.jp",
}

# 本文中の「第5競走における制裁」を次R開始と誤認しないよう、ページ抽出テキストの行頭だけ。
RACE_HEAD_RE = re.compile(r"^[^\S\r\n]*第\s*([0-9０-９\s　]{1,8})\s*競\s*走", re.MULTILINE)
NUMBER_MARK_RE = re.compile(r"(?<![0-9])(?:第)?([0-9]{1,2})(?:番|号馬)")
HORSE_NAME_STATEMENT_RE = re.compile(r"([ァ-ヶーA-Za-z][ァ-ヶーA-Za-z0-9ー・]{1,29})号(?:は|が)")
STATUS_RULES = (
    ("出走取消", re.compile(r"出走取消|出走を取り消"), "withdrawal", "pre_race"),
    ("競走除外", re.compile(r"競走除外|競走から除外"), "exclusion", "pre_race"),
    ("競走中止", re.compile(r"競走中止|競走を中止"), "did_not_finish", "in_race"),
)
GROUP_RULES = (
    ("epistaxis", re.compile(r"鼻出血")),
    ("cardiac", re.compile(r"心房細動")),
    ("musculoskeletal", re.compile(
        r"馬体(?:に)?故障|跛行|破行|骨折|屈腱炎|腱炎|腱断裂|靱帯|靭帯|関節炎|脱臼|捻挫|挫跖|蹄葉炎|骨膜炎|飛節炎|球節炎"
    )),
    ("accident", re.compile(r"擦過傷|裂創|挫創|創傷|外傷|挫傷")),
    ("disease", re.compile(
        r"疾病|病気|発症|感冒|蕁麻疹|熱中症|疝痛|フレグモーネ|肺炎|腸炎|気管支炎|喘鳴症|喉頭片麻痺|発熱"
    )),
)
KNOWN_HEALTH_RE = re.compile("|".join(f"(?:{rx.pattern})" for _, rx in GROUP_RULES))
UNKNOWN_MEDICAL_RE = re.compile(r"馬体.{0,12}(?:異常|不調)|疾患|患部|手術|治療|診断|炎症|腫脹|疼痛")
RIDER_ONLY_RE = re.compile(
    r"(?:号)?(?:の)?騎手(?:(?!馬体).){0,100}"
    r"(?:疾病|病気|負傷|けが|怪我|異常|骨折|脱臼|捻挫|挫傷|裂創|発熱|感冒|蕁麻疹)"
)
HORSE_SPECIFIC_RE = re.compile(
    r"馬体|鼻出血|心房細動|跛行|破行|骨折|屈腱|腱炎|靱帯|靭帯|関節炎|脱臼|捻挫|挫跖|蹄葉炎|"
    r"骨膜炎|飛節炎|球節炎|擦過傷|裂創|挫創|創傷|外傷|挫傷|感冒|蕁麻疹|熱中症|疝痛|"
    r"フレグモーネ|肺炎|腸炎|気管支炎|喘鳴症|喉頭片麻痺"
)
NEGATIVE_DISCLOSURE_RE = re.compile(
    r"(?:故障歴|傷病歴|疾病歴)は?(?:なし|ありません|ございません)|"
    r"(?:疾病|傷病|故障|異常)(?:や[^。]{0,15})?は?(?:ありません|ございません|ない)|"
    r"特に[^。]{0,25}(?:傷病|疾病|異常)[^。]{0,15}(?:ありません|ございません|なし)"
)
_NEGATIVE_CONDITION = r"(?:疾病|病気|傷病|故障|異常|ケガ|怪我|負傷|跛行|破行|鼻出血|心房細動|骨折|脱臼|屈腱炎)"
NEGATIVE_HEALTH_RE = re.compile(
    rf"(?:{_NEGATIVE_CONDITION})(?:や[^。]{{0,24}})?(?:の)?(?:発症|症状|既往)?(?:歴)?"
    rf"(?:は|が|も)?(?:何も|特に)?(?:なし|ありません(?:でした)?|ございません(?:でした)?|ない(?:です)?)(?:。|$)|"
    rf"(?:{_NEGATIVE_CONDITION})[^。]{{0,24}}(?:認められな|認めず|否定)"
)
OTHER_HORSE_RE = re.compile(r"^[★※\s]*(?:父|母|母系|兄|姉|弟|妹|半兄|半姉|産駒|相手馬|近親|祖母|祖父)")
ALLOWED_SAT_SECTIONS = {"レース内容", "関係者コメント", "近況", "その他"}
NAME_CHAR_RE = re.compile(r"[ァ-ヶーA-Za-z0-9・]")
AUCTION_NON_HORSE_ACTOR_RE = re.compile(
    r"(?:騎手|調教師|厩務員|馬主|担当者|スタッフ|関係者|獣医(?:師)?)"
    r"[^。]{0,100}(?:疾病|病気|ケガ|怪我|負傷|骨折|脱臼|捻挫|挫傷|裂創|鼻出血|発症)"
)
AUCTION_EXPLICIT_HORSE_RE = re.compile(
    r"(?:本馬|当該馬|同馬|馬体)[^。]{0,100}"
    r"(?:疾病|病気|ケガ|怪我|負傷|故障|跛行|破行|鼻出血|心房細動|骨折|脱臼|屈腱炎|発症)"
)
AUCTION_HORSE_ANATOMY_RE = re.compile(r"(?:前肢|後肢|四肢|蹄|屈腱|飛節|球節|管骨|繋靱帯|繋靭帯)")
AUCTION_HUMAN_ANATOMY_RE = re.compile(r"(?:右腕|左腕|両腕|上腕|前腕|手首|肩|鎖骨|肋骨|腰|頭部)")


def log(message: str) -> None:
    print(f"[{dt.datetime.now(JST):%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def public_source_error_reason(exc: Exception) -> str:
    """公開artifactへは既知PDF guard codeだけを出し、自由例外文を出さない。"""
    if isinstance(exc, ValueError):
        code = str(exc)
        if code in PUBLIC_PDF_GUARD_CODES:
            return f"ValueError:{code}"
    return f"{type(exc).__name__}:source_processing"


def _reason_codes(values: list[str] | None) -> list[str]:
    """Actionsへ原本文を出さず、parserが付けた短いreason codeだけを残す。"""
    out: list[str] = []
    for value in values or []:
        code = re.sub(r"[^A-Za-z0-9_.:/-]", "_", str(value))[:120]
        if code and code not in out:
            out.append(code)
    return out


def add_report(
    reports: list[dict] | None, *, kind: str, ref: str, status: str,
    events: list[dict] | None = None, reasons: list[str] | None = None,
    candidate_count: int | None = None, rpc_status: str | None = None,
    rpc_applied: bool | None = None,
) -> None:
    rows = events or []
    codes = _reason_codes(reasons)
    row = {
        "source_kind": kind,
        "source_ref": ref,
        "status": status,
        "candidate_count": len(rows) if candidate_count is None else max(0, int(candidate_count)),
        "displayable_count": sum(1 for item in rows if item.get("displayable")),
        "reasons": codes,
    }
    if rpc_status is not None:
        row["rpc_status"] = clean_text(rpc_status)[:40]
    if rpc_applied is not None:
        row["rpc_applied"] = bool(rpc_applied)
    if reports is not None:
        reports.append(row)
    if status not in {"complete", "skipped"} or codes:
        log(
            f"{kind} {ref}: {status} candidates={row['candidate_count']} "
            f"displayable={row['displayable_count']} reasons={','.join(codes) or '-'}"
        )


def nfkc(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def norm_name(value: object) -> str:
    return re.sub(r"\s+", "", nfkc(value))


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", nfkc(value)).strip()


def compact_text(value: object) -> str:
    return re.sub(r"\s+", "", nfkc(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def is_date(value: object) -> bool:
    try:
        dt.date.fromisoformat(str(value))
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)))
    except (TypeError, ValueError):
        return False


def source_url_ok(value: object, kind: str | None = None) -> bool:
    try:
        u = urllib.parse.urlsplit(str(value or ""))
    except ValueError:
        return False
    if u.scheme != "https" or u.hostname not in ALLOWED_SOURCE_HOSTS or u.username or u.password:
        return False
    if kind == "nar_pdf" and u.hostname not in {"www.keiba.go.jp", "keiba.go.jp"}:
        return False
    if kind == "rakuten" and u.hostname != "auction.keiba.rakuten.co.jp":
        return False
    if kind == "sat" and u.hostname != "www.sat-auction.jp":
        return False
    return True


def event_id(parts: list[object]) -> str:
    return sha256_text("\0".join(str(x if x is not None else "") for x in parts))


def line_hash(detail: str) -> str:
    return sha256_text(clean_text(detail))


def normalize_race_no_token(value: object) -> int | None:
    """pdfplumber の字形重複(11/44/1100/1122)を 1/4/10/12 に戻す。"""
    digits = re.sub(r"\s+", "", nfkc(value))
    if not digits.isdigit():
        return None
    if len(digits) % 2 == 0 and all(digits[i] == digits[i + 1] for i in range(0, len(digits), 2)):
        collapsed = digits[::2]
        if 1 <= int(collapsed) <= 12:
            return int(collapsed)
    if 1 <= int(digits) <= 12:
        return int(digits)
    return None


def _segments(pages: list[str], expected: set[int]) -> tuple[list[tuple[int | None, str]], set[int], int]:
    raw_tokens = [m.group(1) for page in pages for m in RACE_HEAD_RE.finditer(nfkc(page))]
    raw_values = {
        int(re.sub(r"\s+", "", nfkc(x))) for x in raw_tokens
        if re.sub(r"\s+", "", nfkc(x)).isdigit() and 1 <= int(re.sub(r"\s+", "", nfkc(x))) <= 12
    }
    doubled_values = {x for x in (normalize_race_no_token(v) for v in raw_tokens) if x is not None}
    # 同じ「11」は通常の11Rか重複抽出の1Rか曖昧。文書全体が既存R集合に一致する向きを選ぶ。
    doubled_mode = doubled_values == expected or (raw_values != expected and len(doubled_values & expected) >= len(raw_values & expected))

    def decode(token: str) -> int | None:
        digits = re.sub(r"\s+", "", nfkc(token))
        if doubled_mode:
            return normalize_race_no_token(digits)
        return int(digits) if digits.isdigit() and 1 <= int(digits) <= 12 else None

    segments: list[tuple[int | None, str]] = []
    seen: set[int] = set()
    invalid = 0
    current: int | None = None
    for page in pages:
        text = nfkc(page)
        matches = list(RACE_HEAD_RE.finditer(text))
        if not matches:
            segments.append((current, text))
            continue
        if matches[0].start() and current is not None:
            segments.append((current, text[: matches[0].start()]))
        for i, match in enumerate(matches):
            no = decode(match.group(1))
            if no is None:
                invalid += 1
                current = None
            else:
                current = no
                seen.add(no)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segments.append((current, text[match.end() : end]))
    merged: list[tuple[int | None, str]] = []
    for no, text in segments:
        if merged and merged[-1][0] == no:
            merged[-1] = (no, merged[-1][1] + "\n" + text)
        else:
            merged.append((no, text))
    return merged, seen, invalid


def _status(block: str) -> tuple[str | None, str, str]:
    for label, rx, event_type, stage in STATUS_RULES:
        if rx.search(block):
            return label, event_type, stage
    # 公式本文で語尾だけになる折返しにも対応するが、疾病語との同居を後段で必須にする。
    if "取消" in block:
        return "出走取消", "withdrawal", "pre_race"
    if "中止" in block:
        return "競走中止", "did_not_finish", "in_race"
    return None, "post_race_condition", "post_race"


def _groups(block: str) -> list[str]:
    matched = [name for name, rx in GROUP_RULES if rx.search(block)]
    # 「発症」「疾病」は具体病態にも併記される総称。同じ根拠文を disease と二重計上しない。
    if len(matched) > 1 and "disease" in matched:
        matched.remove("disease")
    return matched


def _rider_only(block: str) -> bool:
    # 馬名の直後に「同号馬の騎手...骨折」等が続く書式がある。具体病名でもsubjectが騎手なら除外する。
    # 一方「騎手が下馬し、馬体に故障を認めた」は馬の記述なので `馬体` を越えては一致させない。
    return bool(RIDER_ONLY_RE.search(block))


def _short_detail(block: str) -> str:
    # 制限期間は疾病文の次文に置かれることがある。コーナー順・払戻まで巻き込まない。
    parts = re.findall(r"[^。]{1,800}(?:。|$)", clean_text(block))
    if not parts:
        return clean_text(block)[:1000]
    picked = [parts[0]]
    if not re.search(r"出走できない|出走制限|制限期間", parts[0]):
        for part in parts[1:3]:
            if re.search(r"出走できない|出走制限|制限期間|令和\s*\d+年", part):
                picked.append(part)
                if re.search(r"出走できない|出走制限|制限期間", part):
                    break
    return clean_text("".join(picked))[:1000]


def _parse_restriction(detail: str, reported_date: str | None = None) -> tuple[str | None, str | None, bool]:
    # PDFは日付の途中でも折り返す（例 `1月2\n2日`, `ま\nで`）ため、解析時だけ空白を除く。
    # detail自体は後段で原文相当を保持し、ここで書き換えない。
    s = compact_text(detail)
    if not re.search(r"出走できない|出走制限|制限期間|\d+日間", s):
        return None, None, False

    era = r"令和\s*(\d{1,2})年\s*(\d{1,2})月\s*(\d{1,2})日"
    found = list(re.finditer(era, s))

    def as_date(y: int, m: int, d: int) -> dt.date:
        return dt.date(y, m, d)

    start: dt.date | None = None
    through: dt.date | None = None
    try:
        # 「から」「〜」に直接接する2つを優先し、発生日を期間開始日に取り違えない。
        for idx, match in enumerate(found):
            first = as_date(2018 + int(match.group(1)), int(match.group(2)), int(match.group(3)))
            tail = s[match.end() : match.end() + 80]
            if not re.match(r"\s*(?:から|[~〜～\-])", tail):
                continue
            if idx + 1 < len(found):
                other = found[idx + 1]
                start = first
                through = as_date(2018 + int(other.group(1)), int(other.group(2)), int(other.group(3)))
                break
            same = re.search(r"(?:同年\s*)?(\d{1,2})月\s*(\d{1,2})日", tail)
            if same:
                start = first
                through = as_date(first.year, int(same.group(1)), int(same.group(2)))
                if through < start:
                    through = as_date(first.year + 1, through.month, through.day)
                break
        if through is None and found and "まで" in s[found[-1].end() : found[-1].end() + 20]:
            last = found[-1]
            through = as_date(2018 + int(last.group(1)), int(last.group(2)), int(last.group(3)))
        if through is None and reported_date and is_date(reported_date):
            end_only = re.search(r"(?<!年)(\d{1,2})月\s*(\d{1,2})日\s*まで", s)
            if end_only:
                base = dt.date.fromisoformat(reported_date)
                through = as_date(base.year, int(end_only.group(1)), int(end_only.group(2)))
                if through < base:
                    through = as_date(base.year + 1, through.month, through.day)
    except ValueError:
        return None, None, True
    return (
        start.isoformat() if start else None,
        through.isoformat() if through else None,
        bool(start and through and through < start),
    )


def _runner_token_positions(segment: str, runners: list[dict]) -> tuple[str, list[tuple[int, int, dict, int | None]], list[int]]:
    compact = compact_text(segment)
    exact: list[tuple[int, int, dict, int | None]] = []
    name_positions: set[int] = set()
    for runner in runners:
        no = runner.get("runner_number")
        name = norm_name(runner.get("horse_name"))
        if not isinstance(no, int) or not name:
            continue
        at = 0
        while True:
            name_pos = compact.find(name, at)
            if name_pos < 0:
                break
            name_end = name_pos + len(name)
            before_ok = name_pos == 0 or not NAME_CHAR_RE.fullmatch(compact[name_pos - 1])
            after_ok = name_end == len(compact) or not NAME_CHAR_RE.fullmatch(compact[name_end])
            prefix = compact[max(0, name_pos - 8) : name_pos]
            any_marker = re.search(r"(?:第)?(\d{1,2})(?:番|号馬)$", prefix)
            marker = any_marker if any_marker and int(any_marker.group(1)) == no else None
            # 数字markerが直前にあるなら番号も一致必須。marker無しの金沢型は完全な馬名境界かつ
            # `号は/号が` の明示トークンだけを採る。アオをアオゾラの接頭辞として拾わない。
            name_only = not any_marker and after_ok and re.match(r"号(?:は|が)", compact[name_end:])
            if not before_ok or not after_ok or (marker is None and not name_only):
                at = name_pos + max(1, len(name))
                continue
            name_positions.add(name_pos)
            marker_pos = name_pos - len(marker.group(0)) if marker else None
            begin = marker_pos if marker_pos is not None else name_pos
            exact.append((begin, name_end, runner, marker_pos))
            at = name_pos + max(1, len(name))
    # 同じ文字位置に複数候補が残っても、最長の完全名だけを採る。
    longest = {(a, m): max(b for aa, b, _r, mm in exact if aa == a and mm == m) for a, _b, _r, m in exact}
    exact = [row for row in exact if row[1] == longest[(row[0], row[3])]]
    # 別名・未照合馬も境界として扱い、直前の馬へ疾病を誤帰属させない。
    boundaries = sorted({m.start() for m in NUMBER_MARK_RE.finditer(compact)} | name_positions)
    dedup = {(a, b, int(r["runner_number"]), m): (a, b, r, m) for a, b, r, m in exact}
    return compact, sorted(dedup.values(), key=lambda x: (x[0], x[1])), boundaries


@dataclass
class ParseResult:
    status: str
    events: list[dict] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    seen_races: set[int] = field(default_factory=set)

    @property
    def review_count(self) -> int:
        return len(self.review_reasons)


def parse_nar_pages(
    pages: list[str], *, track: str, race_date: str, expected_races: set[int], runners: list[dict],
    source_hash: str = "fixture", source_url: str = "https://www.keiba.go.jp/fixture.pdf",
) -> ParseResult:
    """抽出済みページを保守的に解析する。未知・同定不能は source 全体を review にする。"""
    reasons: list[str] = []
    segments, seen, invalid_heads = _segments(pages, set(expected_races))
    if invalid_heads:
        reasons.append(f"invalid_race_heading:{invalid_heads}")
    if seen != set(expected_races):
        reasons.append(f"race_sections:{len(seen)}/{len(expected_races)}")

    by_race: dict[int, list[dict]] = {}
    for runner in runners:
        try:
            no = int(runner.get("race_no"))
            num = int(runner.get("runner_number"))
        except (TypeError, ValueError):
            reasons.append("runner_key_invalid")
            continue
        by_race.setdefault(no, []).append({**runner, "race_no": no, "runner_number": num})
    for no, rows in by_race.items():
        nums = [r["runner_number"] for r in rows]
        if len(nums) != len(set(nums)):
            reasons.append(f"duplicate_runner_number:R{no}")
        names = [norm_name(r.get("horse_name")) for r in rows]
        if any(not x for x in names) or len(names) != len(set(names)):
            reasons.append(f"duplicate_or_empty_runner_name:R{no}")

    source_ref = f"{race_date.replace('-', '')}/{NAR_PDF.get(track, ('', ''))[0]}"
    events: dict[str, dict] = {}
    for race_no, segment in segments:
        if race_no is None or race_no not in by_race:
            compact_segment = compact_text(segment)
            if (KNOWN_HEALTH_RE.search(compact_segment) or UNKNOWN_MEDICAL_RE.search(compact_segment)) and (
                NUMBER_MARK_RE.search(compact_segment) or HORSE_NAME_STATEMENT_RE.search(compact_segment)
            ):
                reasons.append("health_without_race_context")
            continue
        compact, exact, boundaries = _runner_token_positions(segment, by_race[race_no])
        known_names = {norm_name(row.get("horse_name")) for row in by_race[race_no]}
        exact_marker_positions = {marker for _, _, _, marker in exact if marker is not None}
        for pos, mention_end, runner, _marker in exact:
            next_bounds = [p for p in boundaries if p >= mention_end]
            end = next_bounds[0] if next_bounds else len(compact)
            block = compact[pos:end][:2000]
            # まず当該馬の先頭文（必要なら直後の制限文）だけへ狭める。後続する騎手疾病や別記事を
            # 同じ馬の病態として拾わないため、subject判定・分類もこの短い根拠文に対して行う。
            detail = _short_detail(block)
            if NEGATIVE_HEALTH_RE.search(detail) or _rider_only(detail) or "失格" in block or "降着" in block:
                continue
            groups = _groups(detail)
            if not groups:
                if UNKNOWN_MEDICAL_RE.search(detail):
                    reasons.append(f"unknown_expression:R{race_no}:{runner['runner_number']}")
                continue
            race_status, event_type, stage = _status(detail)
            # 落馬・制裁だけでは groups が立たない。疾病語だけ立った騎手記述も上で除外する。
            if not detail:
                reasons.append(f"empty_detail:R{race_no}:{runner['runner_number']}")
                continue
            rfrom, rthrough, inverted = _parse_restriction(detail, race_date)
            if inverted:
                reasons.append(f"restriction_inverted:R{race_no}:{runner['runner_number']}")
                continue
            birth = str(runner.get("birth_date") or "")
            birth = birth if is_date(birth) else None
            # ⚠1 つの記述に分類が 2 つ当たる(例: 跛行+鼻出血)と、event_key(分類を含まない)が同じ記録が
            #   2 件できて race RPC が「duplicate event_key」で PDF ごと review にし、毎日 exit 1 が続いた
            #   (2026-09-12 実測: 高知 9/6・門別 9/10)。記録は**1 記述 1 件**= 分類は先頭(GROUP_RULES の順)だけ。
            #   ⛔本文(detail)は全文そのまま残るので情報は落ちない
            for group in groups[:1]:
                lh = line_hash(detail)
                eid = event_id([
                    "nar_pdf", track, race_date, race_no, runner["runner_number"], stage, event_type, group, lh,
                ])
                events[eid] = {
                    "event_id": eid,
                    # ⛔器の displayable 制約と race RPC は event_key を要求し、DB 側で同じ式で再計算して照合する
                    #   (private.nar_health_event_key= "race-v1" と各値を NUL で連結した sha256・race_status は無ければ空)。
                    #   NAR は基準なので末尾に source_kind を足さない(主催者公式 health_org.py は足して衝突を避ける)。
                    "event_key": hashlib.sha256(bytes([0]).join(str(x).encode("utf-8") for x in [
                        "race-v1", track, race_date, race_no, runner["runner_number"],
                        str(runner.get("horse_name") or ""), event_type, race_status or "",
                    ])).hexdigest(),
                    # DB側RPCも同定元の既存行を再照合するため、表示名は正規化値でなくnar_runsの値をexact copyする。
                    "horse_name": str(runner.get("horse_name") or ""),
                    "birth_date": birth,
                    "horse_code": None,
                    "jbis_id": None,
                    "track": track,
                    "race_date": race_date,
                    "race_no": race_no,
                    "runner_number": runner["runner_number"],
                    "event_date": None,
                    "reported_date": race_date,
                    "stage": stage,
                    "event_type": event_type,
                    "condition_group": group,
                    "race_status": race_status,
                    "detail": detail,
                    "restriction_from": rfrom,
                    "restriction_through": rthrough,
                    "source_kind": "nar_pdf",
                    "source_ref": source_ref,
                    "source_url": source_url,
                    "source_hash": source_hash,
                    "source_line_hash": lh,
                    "match_method": "race_key_name",
                    "displayable": True,
                    "parser_version": PARSER_VERSION,
                }

        # 健康語を含む番号付き記述が完全一致馬トークンで解決しない場合は公開しない。
        for match in NUMBER_MARK_RE.finditer(compact):
            start = match.start()
            next_bounds = [p for p in boundaries if p > start]
            end = next_bounds[0] if next_bounds else len(compact)
            block = compact[start:end][:1000]
            if start in exact_marker_positions or _rider_only(block) or "失格" in block or "降着" in block:
                continue
            # 払戻欄の「1着6番190円」は馬記述ではない。番/号馬の直後が馬名らしい字の時だけ未照合候補にする。
            if not re.match(r"[ァ-ヶーA-Za-z]", compact[match.end() : match.end() + 1]):
                continue
            if not NEGATIVE_HEALTH_RE.search(block) and (KNOWN_HEALTH_RE.search(block) or UNKNOWN_MEDICAL_RE.search(block)):
                reasons.append(f"unmatched_health:R{race_no}:{match.group(1)}")

        # 金沢等には馬番を省き馬名だけを記す欄がある。既存出走行へ一意一致する名前は上で拾うが、
        # 不一致名を黙って捨てるとsourceの一部だけを公開してしまうためreviewへ送る。
        for match in HORSE_NAME_STATEMENT_RE.finditer(compact):
            if norm_name(match.group(1)) in known_names:
                continue
            end = compact.find("。", match.end())
            block = compact[match.start() : (end + 1 if end >= 0 else min(len(compact), match.end() + 1000))]
            if not NEGATIVE_HEALTH_RE.search(block) and not _rider_only(block) and \
                    "失格" not in block and "降着" not in block and \
                    (KNOWN_HEALTH_RE.search(block) or UNKNOWN_MEDICAL_RE.search(block)):
                reasons.append(f"unmatched_health_name:R{race_no}")

    status = "review" if reasons else "complete"
    rows = list(events.values())
    if status == "review":
        for row in rows:
            row["displayable"] = False
            row["match_method"] = "unmatched"
    return ParseResult(status=status, events=rows, review_reasons=sorted(set(reasons)), seen_races=seen)


def _html_plain(value: object) -> str:
    raw = str(value or "")
    raw = re.sub(r"<(?:br|/p|/div|/tr|/td|/pre)[^>]*>", "\n", raw, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def _rakuten_about(record: dict) -> tuple[str, bool]:
    desc = str(((record.get("item") or {}).get("description")) or "")
    match = re.search(
        r"(?:本馬について|本馬のご紹介).*?<pre[^>]*>(.*?)</pre>", desc, flags=re.I | re.S,
    )
    if match:
        return _html_plain(match.group(1)), True
    # 既知見出しがあるのに box を取れない変更は review。説明全体へ範囲を広げない。
    return "", not bool(re.search(r"骨折|屈腱炎|跛行|鼻出血|疾病|傷病|馬体故障", _html_plain(desc)))


def _sat_allowed_lines(record: dict) -> tuple[list[str], bool, bool]:
    fields = (record.get("api") or {}).get("free_fields") or []
    out: list[str] = []
    injury = False
    saw_shape = False
    for field_obj in fields:
        if not isinstance(field_obj, dict):
            continue
        injury = injury or str(field_obj.get("injury_history") or "") == "1"
        current: str | None = None
        for raw in nfkc(field_obj.get("remarks")).splitlines():
            line = raw.strip()
            if not line:
                continue
            heading = re.fullmatch(r"[<＜]([^>＞]+)[>＞]", line)
            if heading:
                current = heading.group(1).strip() if heading.group(1).strip() in ALLOWED_SAT_SECTIONS else None
                saw_shape = saw_shape or current is not None
                continue
            if current and line.startswith(("★", "※")):
                out.append(line)
    return out, injury, saw_shape


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in nfkc(text).splitlines():
        line = line.strip()
        if not line:
            continue
        out.extend(x.strip() for x in re.findall(r"[^。]+(?:。|$)", line) if x.strip())
    return out


def _event_date(detail: str) -> str | None:
    s = nfkc(detail)
    m = re.search(r"(?<!\d)(\d{2}|\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", s)
    if not m:
        return None
    year = int(m.group(1))
    if year < 100:
        year += 2000
    try:
        return dt.date(year, int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _auction_details(lines: list[str]) -> tuple[list[tuple[str, str, str | None]], list[str]]:
    """出品 1 件の文 → 分類ごと・発生日ごとに 1 事象(§124)。

    旧(v1.0.0)は「病名の語を含む文 1 つ = 1 事象」だったので、同じ出品の同じ内容が
    画面に何件も並んだ(実測= 998 行 / 477 出品・1 出品で最大 11 行)。束ね方は 2 つだけ:
      ① 日付のある文= その日付の事象(同じ分類・同じ日付の文は 1 つに合流)。
      ② 日付の無い文= その分類に日付つきの事象があれば**いちばん新しい日付**に合流し、
        無ければ日付なしの事象 1 つに合流する。
    ⛔文の中身は変えない(連結は**原文の順**・区切りは半角空白・1000 字で切る)。
    ⛔分類の規則(GROUP_RULES)も除外の規則も触らない。⛔推定しない(日付の無い文に日付を作らない)。
    """
    review: list[str] = []
    # (分類, 発生日) → [(原文で何番目の文か, 本文)]。番号を持つのは
    # 束ねたあとも**原文の順**で並べ直すため(日付なしの文が先に書かれていることがある)
    buckets: dict[tuple[str, str | None], list[tuple[int, str]]] = {}
    seen: set[tuple[str, str]] = set()          # 旧と同じく同じ文の重複は 1 つにする
    for order_no, raw in enumerate(lines):
        detail = clean_text(raw.lstrip("★※ "))[:1000]
        if not detail or OTHER_HORSE_RE.search(detail) or NEGATIVE_DISCLOSURE_RE.search(detail) or NEGATIVE_HEALTH_RE.search(detail):
            continue
        if AUCTION_NON_HORSE_ACTOR_RE.search(detail):
            if AUCTION_EXPLICIT_HORSE_RE.search(detail):
                pass
            elif AUCTION_HORSE_ANATOMY_RE.search(detail) and not AUCTION_HUMAN_ANATOMY_RE.search(detail):
                review.append("ambiguous_auction_actor")
                continue
            else:
                continue
        groups = _groups(detail)
        if not groups:
            if UNKNOWN_MEDICAL_RE.search(detail):
                review.append("unknown_auction_expression")
            continue
        happened = _event_date(detail)
        for group in groups:
            key = (line_hash(detail), group)
            if key in seen:
                continue
            seen.add(key)
            buckets.setdefault((group, happened), []).append((order_no, detail))
    return _merge_auction_buckets(buckets), review


def _merge_auction_buckets(
    buckets: dict[tuple[str, str | None], list[tuple[int, str]]],
) -> list[tuple[str, str, str | None]]:
    """分類ごとに束ね、日付なしの文をいちばん新しい日付の事象へ合流させる。

    ⊙本文は**原文の順**でつなぐ(束ねた順ではない)。⊙日付の無い文に日付を作らない。
    """
    order: list[str] = []                        # 分類の先頭登場順(画面の並びを原文に寄せる)
    by_group: dict[str, dict[str | None, list[tuple[int, str]]]] = {}
    for (group, happened), sentences in buckets.items():
        if group not in by_group:
            by_group[group] = {}
            order.append(group)
        by_group[group].setdefault(happened, []).extend(sentences)
    out: list[tuple[str, str, str | None]] = []
    for group in order:
        dates = sorted(d for d in by_group[group] if d is not None)
        undated = by_group[group].pop(None, [])
        if undated:
            # 日付つきがあればいちばん新しい日付へ、無ければ日付なしの事象に残す
            if dates:
                by_group[group][dates[-1]].extend(undated)
            else:
                by_group[group][None] = undated
        for happened in (dates or [None]):
            sentences = sorted(by_group[group][happened])          # 原文で何番目かで並べ直す
            joined = " ".join(text for _, text in sentences)[:1000]
            if joined:
                out.append((joined, group, happened))
    return out


def auction_candidate(record: dict, source: str) -> dict | None:
    try:
        item_id = int(record.get("id"))
    except (TypeError, ValueError):
        return None
    if source == "rakuten":
        item = record.get("item") or {}
        date = str(item.get("end_datetime") or "")[:10]
        raw_name = clean_text(item.get("name")).split(" ", 1)[0]
        about, shape_ok = _rakuten_about(record)
        details, review = _auction_details(_sentences(about))
        if not shape_ok:
            review.append("rakuten_about_shape")
        url = f"https://auction.keiba.rakuten.co.jp/item/{item_id}"
        injury_flag = False
    elif source == "sat":
        status = (record.get("api") or {}).get("bid_status") or {}
        date = str(status.get("end_datetime") or "")[:10]
        raw_name = clean_text(record.get("title"))
        allowed, injury_flag, shape_ok = _sat_allowed_lines(record)
        details, review = _auction_details(allowed)
        if (KNOWN_HEALTH_RE.search(nfkc(record.get("text"))) or injury_flag) and not shape_ok:
            review.append("sat_section_shape")
        url = f"https://www.sat-auction.jp/auction/{item_id}"
    else:
        return None
    if not is_date(date) or not raw_name:
        return None
    if injury_flag and not details:
        details = [("傷病歴の申告あり", "unspecified", None)]
    # fetched_atは収集時刻であって公式本文ではない。同じ原本の再取得だけでchanged停止しないようhash対象外。
    source_record = {key: value for key, value in record.items() if key != "fetched_at"}
    canonical = json.dumps(source_record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "source": source,
        "item_id": item_id,
        "source_ref": f"{source}/{item_id}",
        "auction_date": date,
        "raw_name": raw_name,
        "source_url": url,
        "source_hash": sha256_text(canonical),
        "details": details,
        "review_reasons": sorted(set(review)),
    }


def parse_auction_record(record: dict, source: str, sale: dict | None) -> ParseResult:
    candidate = auction_candidate(record, source)
    if not candidate:
        return ParseResult("review", review_reasons=["auction_record_key"])
    reasons = list(candidate["review_reasons"])
    if not sale:
        reasons.append("auction_item_unmatched")
        return ParseResult("review", review_reasons=sorted(set(reasons)))
    # auction_salesとのRPC再照合が同じ値を見られるよう、同定後に既存行の表示名をexact copyする。
    horse_name = str(sale.get("horse_name") or "")
    if not horse_name or norm_name(horse_name) != norm_name(candidate["raw_name"]):
        reasons.append("auction_name_unmatched")
    if str(sale.get("source")) != source or int(sale.get("item_id") or -1) != candidate["item_id"]:
        reasons.append("auction_key_unmatched")
    reported = str(sale.get("auction_date") or "")
    if not is_date(reported) or reported != candidate["auction_date"]:
        reasons.append("auction_date_unmatched")
    url = str(sale.get("url") or "")
    if not source_url_ok(url, source) or url != candidate["source_url"]:
        reasons.append("auction_source_url")
    if reasons:
        return ParseResult("review", review_reasons=sorted(set(reasons)))

    birth = str(sale.get("birth_date") or "")
    birth = birth if is_date(birth) else None
    jbis = clean_text(sale.get("jbis_id")) or None
    events: list[dict] = []
    for detail, group, happened in candidate["details"]:
        lh = line_hash(detail)
        eid = event_id([source, candidate["item_id"], "auction_disclosure", "auction_disclosure", group, lh])
        events.append({
            "event_id": eid,
            "horse_name": horse_name,
            "birth_date": birth,
            "horse_code": None,
            "jbis_id": jbis,
            "track": None,
            "race_date": None,
            "race_no": None,
            "runner_number": None,
            "event_date": happened,
            "reported_date": reported,
            "stage": "auction_disclosure",
            "event_type": "auction_disclosure",
            "condition_group": group,
            "race_status": None,
            "detail": detail,
            "restriction_from": None,
            "restriction_through": None,
            "source_kind": source,
            "source_ref": candidate["source_ref"],
            "source_url": url,
            "source_hash": candidate["source_hash"],
            "source_line_hash": lh,
            "match_method": "auction_item",
            "displayable": True,
            "parser_version": PARSER_VERSION,
        })
    return ParseResult("complete", events=events)


class Supabase:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    @property
    def headers(self) -> dict[str, str]:
        return {"apikey": self.key, "Authorization": f"Bearer {self.key}", "User-Agent": UA}

    def get(self, path: str) -> list[dict]:
        req = urllib.request.Request(f"{self.url}/rest/v1/{path}", headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def rpc(self, name: str, payload: dict) -> object:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {**self.headers, "Content-Type": "application/json", "Prefer": "return=representation"}
        req = urllib.request.Request(f"{self.url}/rest/v1/rpc/{name}", data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=90) as response:
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else None


def q(value: object) -> str:
    return urllib.parse.quote(str(value), safe="")


def get_import(client: Supabase, kind: str, ref: str) -> dict | None:
    rows = client.get(
        "nar_health_imports?select=source_kind,source_ref,source_hash,parser_version,status,event_count,review_count,"
        f"attempt_count,failure_count,http_etag,http_last_modified,first_seen_at,last_checked_at&"
        f"source_kind=eq.{q(kind)}&source_ref=eq.{q(ref)}&limit=1"
    )
    return rows[0] if rows else None


def list_import_refs(client: Supabase, kind: str) -> set[str]:
    out: set[str] = set()
    cursor: str | None = None
    while True:
        tail = f"&source_ref=gt.{q(cursor)}" if cursor else ""
        rows = client.get(
            f"nar_health_imports?select=source_ref&source_kind=eq.{q(kind)}{tail}&order=source_ref.asc&limit=1000"
        )
        if not rows:
            break
        out.update(str(r.get("source_ref")) for r in rows if r.get("source_ref"))
        cursor = str(rows[-1].get("source_ref"))
        if len(rows) < 1000:
            break
    return out


def unresolved_nar_refs(client: Supabase) -> list[str]:
    """rolling 7日から外れてもerror/not_readyを次回jobで必ず再列挙する。"""
    rows = client.get(
        "nar_health_imports?select=source_ref&source_kind=eq.nar_pdf&"
        "status=in.(error,not_ready)&order=source_ref.asc&limit=1000"
    )
    return [str(row.get("source_ref")) for row in rows if row.get("source_ref")]


def apply_source(
    client: Supabase | None, *, apply: bool, kind: str, ref: str, url: str, source_hash: str,
    status: str, events: list[dict] | None, review_count: int = 0, etag: str | None = None,
    last_modified: str | None = None, error: str | None = None, force: bool = False,
) -> object | None:
    if not apply:
        return None
    assert client is not None
    # ⛔Codex 9/4 の器(pipeline/sql/horse_health_organizers_20260904.sql)で apply_nar_health_source は
    #   auction(rakuten/sat)専用になり、競走の source(nar_pdf・<slug>_official)は apply_nar_health_race_source
    #   (同じ引数)へ。2026-09-04〜05 の日次と 9/5 の backfill が「auction-only」の 400 で全滅した(#485)。
    rpc_name = "apply_nar_health_source" if kind in {"rakuten", "sat"} else "apply_nar_health_race_source"
    return client.rpc(rpc_name, {
        "p_source_kind": kind,
        "p_source_ref": ref,
        "p_source_url": url,
        "p_source_hash": source_hash,
        "p_parser_version": PARSER_VERSION,
        "p_status": status,
        "p_events": events,
        "p_review_count": int(review_count),
        "p_http_etag": etag,
        "p_http_last_modified": last_modified,
        "p_last_error": (clean_text(error)[:300] if error else None),
        "p_force": bool(force),
    })


def rpc_outcome(value: object) -> tuple[str | None, bool]:
    """PostgRESTのjsonb戻り値からforce検証に必要な2項目だけを取り出す。"""
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        return None, False
    status = clean_text(value.get("status")) or None
    return status, value.get("applied") is True


def _same_jst_day(value: object) -> bool:
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.astimezone(JST).date() == dt.datetime.now(JST).date()
    except (TypeError, ValueError):
        return False


def _age_days(value: object) -> int | None:
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt.datetime.now(JST).date() - t.astimezone(JST).date()).days
    except (TypeError, ValueError):
        return None


def fetch_decision(old: dict | None, force: bool, reparse: bool = False) -> tuple[str, str | None]:
    if not old:
        return "fetch", None
    if force:
        return "fetch", None
    status = str(old.get("status") or "")
    if status == "changed":
        return "skip", "changed_waiting_review"
    parser_changed = str(old.get("parser_version") or "") != PARSER_VERSION
    if status in {"complete", "review"} and parser_changed:
        return ("fetch", None) if reparse else ("skip", "parser_changed_use_reparse")
    if status == "review":
        return "skip", "review_waiting_parser_or_force"
    age = _age_days(old.get("first_seen_at"))
    if status == "complete" and age is not None and age >= 7:
        return "skip", "complete_after_window"
    # 1日1回のconditional確認は採用済みcompleteだけ。error/not_readyは手動rerunで同日回復できる。
    if status == "complete" and _same_jst_day(old.get("last_checked_at")):
        return "skip", "checked_today"
    return "fetch", None


class HostLimiter:
    def __init__(self) -> None:
        self.last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).hostname or ""
        elapsed = time.monotonic() - self.last.get(host, 0.0)
        if elapsed < MIN_HOST_INTERVAL:
            time.sleep(MIN_HOST_INTERVAL - elapsed)
        self.last[host] = time.monotonic()


@dataclass
class PdfResponse:
    code: int
    body: bytes = b""
    content_type: str = ""
    etag: str | None = None
    last_modified: str | None = None


class NarRedirectHandler(urllib.request.HTTPRedirectHandler):
    """302先へGETする前に、NAR許可host・https以外を拒否する。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not source_url_ok(newurl, "nar_pdf"):
            raise ValueError("pdf_redirect_host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


NAR_OPENER = urllib.request.build_opener(NarRedirectHandler())


def download_pdf(url: str, limiter: HostLimiter, old: dict | None) -> PdfResponse:
    limiter.wait(url)
    headers = {"User-Agent": UA, "Accept": "application/pdf"}
    # parser更新時は304では再解析できないため、本文を取り直す。
    if old and str(old.get("parser_version")) == PARSER_VERSION:
        if old.get("http_etag"):
            headers["If-None-Match"] = str(old["http_etag"])
        if old.get("http_last_modified"):
            headers["If-Modified-Since"] = str(old["http_last_modified"])
    req = urllib.request.Request(url, headers=headers)
    try:
        with NAR_OPENER.open(req, timeout=60) as response:
            # urllibは302を自動追跡する。許可外CDN/別hostへ移った本文は「新規サイト0」の範囲外なので読まない。
            if not source_url_ok(response.geturl(), "nar_pdf"):
                raise ValueError("pdf_redirect_host")
            body = response.read(MAX_PDF_BYTES + 1)
            return PdfResponse(
                response.status, body, response.headers.get_content_type(),
                response.headers.get("ETag"), response.headers.get("Last-Modified"),
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return PdfResponse(304, etag=exc.headers.get("ETag"), last_modified=exc.headers.get("Last-Modified"))
        if exc.code in {404, 410}:
            return PdfResponse(exc.code)
        raise


def conditional_import(old: dict | None, forced: bool) -> dict | None:
    """304 touchが安全なのは採用済みcompleteだけ。changed/error/reviewとforceは必ず本文を取り直す。"""
    if forced or not old or str(old.get("status") or "") != "complete":
        return None
    return old


def can_touch_unchanged(old: dict | None, digest: str, forced: bool) -> bool:
    """本文省略はcompleteの同一版だけ。error等は同一hashでも再解析して状態を回復させる。"""
    return bool(
        old and not forced and str(old.get("status") or "") == "complete"
        and old.get("source_hash") == digest and old.get("parser_version") == PARSER_VERSION
    )


def retry_window_exhausted(old: dict | None, forced: bool) -> bool:
    """直前までに6連続失敗なら、今回が実際の7回目。経過日/総attemptとは混同しない。"""
    if forced:
        return False
    try:
        return int((old or {}).get("failure_count") or 0) >= 6
    except (TypeError, ValueError):
        return False


def auction_fetch_decision(
    old: dict | None, digest: str, force: bool, reparse: bool = False,
) -> tuple[str, str | None]:
    """repo原本は通信不要なので、年齢/statusより先に毎回本文hash差分を見る。"""
    if old and old.get("source_hash") and str(old.get("source_hash")) != digest:
        return "fetch", None
    return fetch_decision(old, force, reparse)


def pdf_pages(payload: bytes, content_type: str) -> list[str]:
    if len(payload) > MAX_PDF_BYTES:
        raise ValueError("pdf_size")
    if not payload.startswith(b"%PDF"):
        raise ValueError("pdf_magic")
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise ValueError("pdf_content_type")
    import pdfplumber  # 遅延 import: parser fixture は依存なしでも実行できる

    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        if not 1 <= len(pdf.pages) <= MAX_PDF_PAGES:
            raise ValueError("pdf_pages")
        return [(page.extract_text(x_tolerance=1, y_tolerance=3) or "") for page in pdf.pages]


def pdf_url(track: str, race_date: str) -> tuple[str, str]:
    code, slug = NAR_PDF[track]
    ymd = race_date.replace("-", "")
    return f"https://www.keiba.go.jp/seisekipdf/{ymd}/{code}/{ymd}_{slug}.pdf", f"{ymd}/{code}"


def venue_days(client: Supabase, start: dt.date, end: dt.date) -> list[tuple[str, str, set[int]]]:
    out: list[tuple[str, str, set[int]]] = []
    day = start
    while day <= end:
        iso = day.isoformat()
        rows = client.get(
            "nar_races?select=track,race_date,race_no&"
            f"race_date=eq.{iso}&order=track.asc,race_no.asc&limit=1000"
        )
        grouped: dict[str, set[int]] = {}
        for row in rows:
            track = str(row.get("track") or "")
            try:
                no = int(row.get("race_no"))
            except (TypeError, ValueError):
                continue
            if track in NAR_PDF and 1 <= no <= 12:
                grouped.setdefault(track, set()).add(no)
        out.extend((track, iso, grouped[track]) for track in sorted(grouped))
        day += dt.timedelta(days=1)
    return out


def nar_runners(client: Supabase, track: str, race_date: str) -> list[dict]:
    return client.get(
        "nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date,finish,finish_note&"
        f"track=eq.{q(track)}&race_date=eq.{race_date}&order=race_no.asc,runner_number.asc&limit=1000"
    )


def _tight_note(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def nar_status_matches(event: dict, run: dict | None) -> bool:
    """DB の race RPC(Codex 9/4・apply_nar_health_race_source)と同じ照合。⛔1 行でも合わないと source ごと 400 で
    突き返されるので、送る前に同じ式で落とす(式を変えるときは SQL と両方)。"""
    if not run:
        return False
    note = _tight_note(run.get("finish_note"))
    kind, stage, status = event.get("event_type"), event.get("stage"), event.get("race_status")
    if kind == "withdrawal":
        return stage == "pre_race" and status == "出走取消" and note in {"取消", "出走取消"}
    if kind == "exclusion":
        return stage == "pre_race" and status == "競走除外" and note in {"除外", "競走除外"}
    if kind == "did_not_finish":
        return stage == "in_race" and status == "競走中止" and note in {"中止", "競走中止"}
    if kind == "post_race_condition":
        try:
            finish = int(run.get("finish") or 0)
        except (TypeError, ValueError):
            finish = 0
        return stage == "post_race" and status is None and (finish > 0 or str(run.get("finish_note") or "").strip() in {"競走中止", "失格"})
    return False


def drop_status_mismatch(events: list[dict], runners: list[dict]) -> list[str]:
    """名簿(nar_runs)の finish_note と合わない行をその場で落とし、落とした鍵を返す(数えるだけ・止めない)。
    実測 2026-03-11 高知 3R 1番= 同じ馬に「競走除外」と「出走取消」の 2 行が読まれ、名簿は競走除外 → 取消の行を落とす。"""
    by_key = {(int(r["race_no"]), int(r["runner_number"])): r for r in runners
              if str(r.get("race_no") or "").isdigit() and str(r.get("runner_number") or "").isdigit()}
    dropped: list[str] = []
    for i in range(len(events) - 1, -1, -1):
        ev = events[i]
        try:
            key = (int(ev.get("race_no")), int(ev.get("runner_number")))
        except (TypeError, ValueError):
            key = None
        if not nar_status_matches(ev, by_key.get(key)):
            dropped.append(f"status_mismatch:R{ev.get('race_no')}:{ev.get('runner_number')}:{ev.get('event_type')}")
            del events[i]
    return dropped


def attach_horse_codes(client: Supabase, events: list[dict]) -> None:
    cache: dict[tuple[str, str], str | None] = {}
    for row in events:
        name, birth = str(row.get("horse_name") or ""), str(row.get("birth_date") or "")
        if not name or not is_date(birth):
            continue
        key = (name, birth)
        if key not in cache:
            matches = client.get(
                "nar_horse_codes?select=code,horse_name,birth_date&"
                f"horse_name=eq.{q(name)}&birth_date=eq.{birth}&limit=3"
            )
            codes = {str(x.get("code")) for x in matches if re.fullmatch(r"\d{11}", str(x.get("code") or ""))}
            cache[key] = next(iter(codes)) if len(codes) == 1 else None
        row["horse_code"] = cache[key]


# §124(2026-09-07): parser の規則変更で**意図して**事象が減るとき(束ね)は、この番人を全 source で解く。
#   ⛔既定は False= 普段の日次では「減ったら review」のまま。--allow-fewer を付けた実行だけ True。
ALLOW_FEWER = False


def _guard_result(old: dict | None, result: ParseResult, new_hash: str, force: bool) -> tuple[str, list[dict], list[str]]:
    if old and old.get("source_hash") and str(old.get("source_hash")) != new_hash and not force:
        return "changed", [], ["source_hash_changed"]
    visible = sum(1 for x in result.events if x.get("displayable"))
    old_count = int((old or {}).get("event_count") or 0)
    parser_changed = bool(old) and str(old.get("parser_version") or "") != PARSER_VERSION
    if result.status == "complete" and parser_changed and visible < old_count and not force and not ALLOW_FEWER:
        hidden = [{**x, "displayable": False, "match_method": "unmatched"} for x in result.events]
        return "review", hidden, ["displayable_count_decreased"]
    return result.status, result.events, result.review_reasons


def run_nar(
    client: Supabase, start: dt.date, end: dt.date, apply: bool, force_ref: str | None,
    reports: list[dict] | None = None, reparse: bool = False,
) -> dict[str, int]:
    stats = {k: 0 for k in (
        "sources", "complete", "candidates", "events", "review", "not_ready", "changed", "error", "attention",
        "skipped", "force_matched", "force_applied", "status_mismatch", "review_waiting",
    )}
    limiter = HostLimiter()
    work = venue_days(client, start, end)
    seen_refs = {pdf_url(track, race_date)[1] for track, race_date, _expected in work}
    # 公開遅延や一時失敗の初見が遅くても、rolling rangeから落ちたsourceを永久放置しない。
    for pending_ref in unresolved_nar_refs(client):
        if pending_ref in seen_refs:
            continue
        matched = re.fullmatch(r"(\d{8})/(\d{2})", pending_ref)
        if not matched:
            stats["error"] += 1
            add_report(
                reports, kind="nar_pdf", ref=pending_ref, status="error",
                reasons=["pending_source_ref_invalid"],
            )
            continue
        race_date = f"{matched.group(1)[:4]}-{matched.group(1)[4:6]}-{matched.group(1)[6:]}"
        try:
            pending_date = dt.date.fromisoformat(race_date)
        except ValueError:
            stats["error"] += 1
            add_report(
                reports, kind="nar_pdf", ref=pending_ref, status="error",
                reasons=["pending_source_ref_invalid_date"],
            )
            continue
        track = NAR_TRACK_BY_CODE.get(matched.group(2))
        if not track or pending_date > end:
            continue
        pending_runners = nar_runners(client, track, race_date)
        expected = {
            int(row["race_no"]) for row in pending_runners
            if str(row.get("race_no") or "").isdigit() and 1 <= int(row["race_no"]) <= 12
        }
        if not expected:
            stats["error"] += 1
            add_report(
                reports, kind="nar_pdf", ref=pending_ref, status="error",
                reasons=["pending_source_missing_race_context"],
            )
            continue
        work.append((track, race_date, expected))
        seen_refs.add(pending_ref)

    for track, race_date, expected in sorted(work, key=lambda row: (row[1], row[0])):
        url, ref = pdf_url(track, race_date)
        old = get_import(client, "nar_pdf", ref)
        forced = bool(force_ref and force_ref == ref)
        if forced:
            stats["force_matched"] += 1
        decision, reason = fetch_decision(old, forced, reparse)
        if decision == "skip":
            stats["skipped"] += 1
            if reason == "changed_waiting_review":
                stats["changed"] += 1
            elif reason == "review_waiting_parser_or_force":
                # ⛔前の run で review になった source を毎回 review に数えると、毎日 exit 1 が続く
                #   (2026-09-06 auction 363 件・nar 13 件)。新しく review になった数だけ exit 1 に効かせ、
                #   待ちは review_waiting で見せる(--reparse か --force-review-ref で解く)。
                stats["review_waiting"] += 1
            elif reason == "parser_changed_use_reparse":
                stats["attention"] += 1
            if reason not in {"complete_after_window", "checked_today"}:
                add_report(
                    reports, kind="nar_pdf", ref=ref, status=str((old or {}).get("status") or "skipped"),
                    reasons=[reason] if reason else [], candidate_count=int((old or {}).get("event_count") or 0),
                )
            continue
        stats["sources"] += 1
        try:
            # changedで観測した新ETagをforce採用時に送ると304のまま永久に採用できない。
            # error/not_readyも304 touchでは状態が回復しないためconditionalを使わない。
            response = download_pdf(url, limiter, conditional_import(old, forced))
            if response.code == 304:
                apply_source(
                    client, apply=apply, kind="nar_pdf", ref=ref, url=url,
                    source_hash=str((old or {}).get("source_hash") or ""), status="complete", events=None,
                    etag=response.etag or (old or {}).get("http_etag"),
                    last_modified=response.last_modified or (old or {}).get("http_last_modified"),
                )
                stats["skipped"] += 1
                add_report(
                    reports, kind="nar_pdf", ref=ref, status="complete",
                    candidate_count=int((old or {}).get("event_count") or 0),
                )
                continue
            if response.code in {404, 410}:
                # 日齢ではなく、直前までのfailure_count=6なら今回の実失敗が7回目。
                # SQLへは元のnot_readyを送り、原子的加算とreview昇格を同じupsertで行う。
                exhausted = retry_window_exhausted(old, forced)
                rpc = apply_source(
                    client, apply=apply, kind="nar_pdf", ref=ref, url=url,
                    source_hash=str((old or {}).get("source_hash") or ""),
                    status="not_ready", events=[], review_count=0,
                    error=f"http_{response.code}" + ("_seventh_failure" if exhausted else ""), force=forced,
                )
                rpc_status, rpc_applied = rpc_outcome(rpc)
                if forced and rpc_applied:
                    stats["force_applied"] += 1
                failure_status = (
                    rpc_status if apply and rpc_status in {"not_ready", "review"}
                    else "review" if exhausted else "not_ready"
                )
                exhausted = failure_status == "review"
                stats[failure_status] += 1
                add_report(
                    reports, kind="nar_pdf", ref=ref, status=failure_status,
                    reasons=[f"http_{response.code}" + ("_seventh_failure" if exhausted else "")],
                    rpc_status=rpc_status, rpc_applied=rpc_applied if forced else None,
                )
                continue
            digest = sha256_bytes(response.body)
            if can_touch_unchanged(old, digest, forced):
                apply_source(
                    client, apply=apply, kind="nar_pdf", ref=ref, url=url, source_hash=digest,
                    status="complete", events=None, etag=response.etag, last_modified=response.last_modified,
                )
                stats["skipped"] += 1
                add_report(
                    reports, kind="nar_pdf", ref=ref, status="complete",
                    candidate_count=int((old or {}).get("event_count") or 0),
                )
                continue
            pages = pdf_pages(response.body, response.content_type)
            runners = nar_runners(client, track, race_date)
            result = parse_nar_pages(
                pages, track=track, race_date=race_date, expected_races=expected,
                runners=runners, source_hash=digest, source_url=url,
            )
            # ⛔race RPC は名簿と合わない行が 1 つでもあると source ごと拒む → 送る前に同じ式で落とす(数えるだけ)
            # ⛔attention(=人が見る・exit 1)には数えない= 同じ馬の「除外」と「取消」の重なりは読み手の癖で毎日出る。
            #   数は status_mismatch に出す(0 でない日が続いたら読み手を直す)
            for dropped in drop_status_mismatch(result.events, runners):
                stats["status_mismatch"] += 1
                log(f"  status_mismatch {ref} {dropped}")
            if result.status == "complete":
                attach_horse_codes(client, result.events)
            status, events, reasons = _guard_result(old, result, digest, forced)
            if status == "review":
                for row in events:
                    row["displayable"] = False
            rpc = apply_source(
                client, apply=apply, kind="nar_pdf", ref=ref, url=url, source_hash=digest,
                status=status, events=events, review_count=len(reasons), etag=response.etag,
                last_modified=response.last_modified, error=",".join(reasons[:6]) or None, force=forced,
            )
            rpc_status, rpc_applied = rpc_outcome(rpc) if forced else (None, False)
            if forced and rpc_applied:
                stats["force_applied"] += 1
            stats[status] += 1
            stats["candidates"] += len(events)
            stats["events"] += sum(1 for row in events if row.get("displayable"))
            add_report(
                reports, kind="nar_pdf", ref=ref, status=status, events=events, reasons=reasons,
                rpc_status=rpc_status, rpc_applied=rpc_applied if forced else None,
            )
        except Exception as exc:  # source単位。既存displayableはRPCが保持する
            exhausted = retry_window_exhausted(old, forced)
            rpc = apply_source(
                client, apply=apply, kind="nar_pdf", ref=ref, url=url,
                source_hash=str((old or {}).get("source_hash") or ""), status="error", events=[],
                review_count=0,
                error=f"{type(exc).__name__}:{str(exc)[:160]}" + ("_seventh_failure" if exhausted else ""),
                force=forced,
            )
            rpc_status, rpc_applied = rpc_outcome(rpc)
            if forced and rpc_applied:
                stats["force_applied"] += 1
            failure_status = (
                rpc_status if apply and rpc_status in {"error", "review"}
                else "review" if exhausted else "error"
            )
            stats[failure_status] += 1
            add_report(
                reports, kind="nar_pdf", ref=ref, status=failure_status,
                reasons=[public_source_error_reason(exc)],
                rpc_status=rpc_status, rpc_applied=rpc_applied if forced else None,
            )
            log(f"NAR {ref}: error {type(exc).__name__}")
    return stats


def _raw_ref(path: Path) -> str:
    try:
        return path.relative_to(AUCTION_ROOT).as_posix()
    except ValueError:
        return path.name


def read_raw_records() -> tuple[dict[tuple[str, int], dict], list[tuple[str, str, int]]]:
    """既存原本を読む。壊れたfile/行は黙殺せず、原文なしの監査情報として返す。"""
    records: dict[tuple[str, int], dict] = {}
    errors: list[tuple[str, str, int]] = []
    rk = AUCTION_ROOT / "rakuten_items"
    for path in sorted(list(rk.glob("*xxx.jsonl.gz")) + list(rk.glob("*xxx.jsonl"))):
        invalid = 0
        try:
            stream = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")
            with stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        records[("rakuten", int(row["id"]))] = row
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        invalid += 1
            if invalid:
                errors.append(("rakuten", _raw_ref(path), invalid))
        except (OSError, EOFError, UnicodeError, gzip.BadGzipFile):
            errors.append(("rakuten", _raw_ref(path), max(1, invalid)))
    sat = AUCTION_ROOT / "sat" / "items.jsonl"
    if sat.exists():
        invalid = 0
        try:
            with sat.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        records[("sat", int(row["id"]))] = row
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        invalid += 1
            if invalid:
                errors.append(("sat", _raw_ref(sat), invalid))
        except (OSError, UnicodeError):
            errors.append(("sat", _raw_ref(sat), max(1, invalid)))
    return records, errors


def sales_for(client: Supabase, source: str, ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for at in range(0, len(ids), 150):
        part = ids[at : at + 150]
        if not part:
            continue
        rows = client.get(
            "auction_sales?select=source,item_id,horse_name,birth_date,jbis_id,auction_date,url&"
            f"source=eq.{source}&item_id=in.({','.join(str(x) for x in part)})&limit=1000"
        )
        for row in rows:
            try:
                item_id = int(row.get("item_id"))
            except (TypeError, ValueError):
                continue
            if item_id in out:
                out[item_id] = {}  # primary key違反相当を黙って1頭へ寄せない
            else:
                out[item_id] = row
    return out


def run_auction(
    client: Supabase, start: dt.date, end: dt.date, apply: bool, force_ref: str | None,
    reports: list[dict] | None = None, reparse: bool = False,
) -> dict[str, int]:
    stats = {k: 0 for k in (
        "sources", "complete", "candidates", "events", "review", "changed", "error", "attention", "skipped",
        "force_matched", "force_applied", "review_waiting",
    )}
    imported = {kind: list_import_refs(client, kind) for kind in ("rakuten", "sat")}
    records, raw_errors = read_raw_records()
    for kind, raw_ref, count in raw_errors:
        stats["error"] += 1
        add_report(
            reports, kind=kind, ref=f"raw/{raw_ref}", status="error",
            reasons=[f"raw_json_or_gzip_invalid:{count}"], candidate_count=count,
        )
    candidates: dict[tuple[str, int], dict] = {}
    for key, record in records.items():
        source, item_id = key
        cand = auction_candidate(record, source)
        if not cand or not (start.isoformat() <= cand["auction_date"] <= end.isoformat()):
            continue
        # 新規の完全な否定/無関係原本は状態表を膨らませない。以前のeventがあるrefは0件化も同期する。
        if cand["details"] or cand["review_reasons"] or cand["source_ref"] in imported[source]:
            candidates[key] = cand
    sales: dict[tuple[str, int], dict] = {}
    for source in ("rakuten", "sat"):
        ids = sorted(item for (kind, item) in candidates if kind == source)
        sales.update({(source, item): row for item, row in sales_for(client, source, ids).items()})

    for (source, item_id), candidate in sorted(candidates.items()):
        ref = candidate["source_ref"]
        old = get_import(client, source, ref)
        digest = candidate["source_hash"]
        forced = bool(force_ref and force_ref == ref)
        # §124 --allow-fewer= parser が古い source は全部 force 扱い(= DB 側の「事象が減ったら changed」の
        #   番人も p_force で解く)。parser が今の版の source には効かない(普段の日次と同じ)
        if ALLOW_FEWER and old and str(old.get("parser_version") or "") != PARSER_VERSION:
            forced = True
        if forced:
            stats["force_matched"] += 1
        # repository内原本は追加通信なしで読める。completeの8日超skipやreview停止より先に
        # 現在hashを比較し、差分があれば必ずparse→guardしてchangedを可視化する。
        decision, reason = auction_fetch_decision(old, digest, forced, reparse)
        if decision == "skip":
            stats["skipped"] += 1
            if reason == "changed_waiting_review":
                stats["changed"] += 1
            elif reason == "review_waiting_parser_or_force":
                # ⛔前の run で review になった source を毎回 review に数えると、毎日 exit 1 が続く
                #   (2026-09-06 auction 363 件・nar 13 件)。新しく review になった数だけ exit 1 に効かせ、
                #   待ちは review_waiting で見せる(--reparse か --force-review-ref で解く)。
                stats["review_waiting"] += 1
            elif reason == "parser_changed_use_reparse":
                stats["attention"] += 1
            if reason not in {"complete_after_window", "checked_today"}:
                add_report(
                    reports, kind=source, ref=ref, status=str((old or {}).get("status") or "skipped"),
                    reasons=[reason] if reason else [], candidate_count=int((old or {}).get("event_count") or 0),
                )
            continue
        stats["sources"] += 1
        try:
            if can_touch_unchanged(old, digest, forced):
                apply_source(
                    client, apply=apply, kind=source, ref=ref, url=candidate["source_url"],
                    source_hash=digest, status="complete", events=None,
                )
                stats["skipped"] += 1
                add_report(
                    reports, kind=source, ref=ref, status="complete",
                    candidate_count=int((old or {}).get("event_count") or 0),
                )
                continue
            result = parse_auction_record(records[(source, item_id)], source, sales.get((source, item_id)))
            status, events, reasons = _guard_result(old, result, digest, forced)
            if status == "review":
                for row in events:
                    row["displayable"] = False
            rpc = apply_source(
                client, apply=apply, kind=source, ref=ref, url=candidate["source_url"], source_hash=digest,
                status=status, events=events, review_count=len(reasons), error=",".join(reasons[:6]) or None,
                force=forced,
            )
            rpc_status, rpc_applied = rpc_outcome(rpc) if forced else (None, False)
            if forced and rpc_applied:
                stats["force_applied"] += 1
            stats[status] += 1
            candidate_count = max(len(events), len(candidate.get("details") or []))
            stats["candidates"] += candidate_count
            stats["events"] += sum(1 for row in events if row.get("displayable"))
            add_report(
                reports, kind=source, ref=ref, status=status, events=events, reasons=reasons,
                candidate_count=candidate_count,
                rpc_status=rpc_status, rpc_applied=rpc_applied if forced else None,
            )
        except Exception as exc:
            stats["error"] += 1
            rpc = apply_source(
                client, apply=apply, kind=source, ref=ref, url=candidate["source_url"],
                source_hash=str((old or {}).get("source_hash") or ""), status="error", events=[],
                error=f"{type(exc).__name__}:{str(exc)[:180]}",
            )
            rpc_status, rpc_applied = rpc_outcome(rpc) if forced else (None, False)
            if forced and rpc_applied:
                stats["force_applied"] += 1
            add_report(
                reports, kind=source, ref=ref, status="error",
                reasons=[f"{type(exc).__name__}:source_processing"],
                candidate_count=len(candidate.get("details") or []),
                rpc_status=rpc_status, rpc_applied=rpc_applied if forced else None,
            )
            log(f"auction {ref}: error {type(exc).__name__}")
    return stats


def parse_date_arg(value: str | None, default: dt.date) -> dt.date:
    if not value:
        return default
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"日付が不正: {value}") from exc
    if parsed < MIN_DATE:
        raise SystemExit("§89 MVPは2026-01-01以降だけ")
    return parsed


def write_run_report(
    path_value: str | None, *, source: str, ranges: dict[str, tuple[dt.date, dt.date]],
    mode: str, totals: dict[str, dict[str, int]], rows: list[dict], reparse: bool,
) -> dict:
    status_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status") or "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1
    candidates = sum(int(row.get("candidate_count") or 0) for row in rows)
    displayable = sum(int(row.get("displayable_count") or 0) for row in rows)
    checked = sum(status_counts.get(key, 0) for key in ("complete", "review", "changed"))
    payload = {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "generated_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
        "source": source,
        "mode": mode,
        "reparse": reparse,
        "ranges": {key: {"start": value[0].isoformat(), "end": value[1].isoformat()} for key, value in ranges.items()},
        "totals": totals,
        "metrics": {
            "reported_sources": len(rows),
            "status_counts": status_counts,
            "candidate_count": candidates,
            "displayable_count": displayable,
            "structure_complete_rate": (round(status_counts.get("complete", 0) / checked, 6) if checked else None),
            "identity_displayable_rate": (round(displayable / candidates, 6) if candidates else None),
        },
        # source_ref / reason code / 件数だけ。原本文・event detail・header・秘密は含めない。
        "sources": rows,
    }
    if path_value:
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"監査reportを書出し: {path} sources={len(rows)}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        attention = [row for row in rows if row.get("status") not in {"complete", "skipped"} or row.get("reasons")]
        lines = [
            "## Horse health import", "",
            f"- parser: `{PARSER_VERSION}` / mode: `{mode}` / source: `{source}` / reparse: `{str(reparse).lower()}`",
            f"- candidates: {candidates} / displayable: {displayable} / 要確認source: {len(attention)}",
            "", "| source | stats |", "|---|---|",
        ]
        for key, value in totals.items():
            lines.append(f"| {key} | " + " / ".join(f"{k}={v}" for k, v in value.items()) + " |")
        if attention:
            lines += ["", "### 要確認（先頭200件。全件はJSON artifact）", "", "| ref | status | candidates | reasons |", "|---|---:|---:|---|"]
            for row in attention[:200]:
                reasons = ", ".join(row.get("reasons") or []) or "-"
                lines.append(
                    f"| {row.get('source_kind')} `{row.get('source_ref')}` | {row.get('status')} | "
                    f"{row.get('candidate_count')} | {reasons.replace('|', '_')} |"
                )
        try:
            with Path(summary_path).open("a", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")
        except OSError as exc:
            log(f"Actions summary書出し失敗: {type(exc).__name__}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("nar", "auction", "all"), default="nar")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-review-ref")
    parser.add_argument("--reparse", action="store_true", help="parser版更新後の過去sourceを明示再解析する")
    parser.add_argument("--allow-fewer", action="store_true",
                        help="§124 束ねなど、parser の変更で事象が減るのを承知で全 source を通す(displayable_count_decreased を解く)")
    parser.add_argument("--report-json", help="原本文を含まないsource別監査reportの保存先")
    parser.add_argument("--env")
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("--apply と --dry-run は同時指定できない")
    if args.env:
        load_env(args.env)
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    client = Supabase(url, key)
    today = dt.datetime.now(JST).date()
    default_end = today - dt.timedelta(days=1)
    explicit_start = parse_date_arg(args.start, MIN_DATE) if args.start else None
    end = parse_date_arg(args.end, default_end)
    if end >= today and not args.end:
        end = default_end
    nar_start = explicit_start or max(MIN_DATE, end - dt.timedelta(days=6))
    auction_start = explicit_start or MIN_DATE
    if end < nar_start or end < auction_start:
        parser.error("--end は --start 以降")
    mode = "apply" if args.apply else "dry-run"
    ranges = []
    if args.source in {"nar", "all"}:
        ranges.append(f"nar={nar_start}..{end}")
    if args.source in {"auction", "all"}:
        ranges.append(f"auction={auction_start}..{end}")
    global ALLOW_FEWER
    ALLOW_FEWER = bool(args.allow_fewer)
    log(f"開始 source={args.source} {' '.join(ranges)} {mode} reparse={args.reparse} allow_fewer={ALLOW_FEWER} parser={PARSER_VERSION}")
    totals: dict[str, dict[str, int]] = {}
    report_rows: list[dict] = []
    report_ranges = {}
    if args.source in {"nar", "all"}:
        report_ranges["nar"] = (nar_start, end)
    if args.source in {"auction", "all"}:
        report_ranges["auction"] = (auction_start, end)

    if args.force_review_ref:
        force_scope = (
            "nar" if re.fullmatch(r"\d{8}/\d{2}", args.force_review_ref) else
            "auction" if re.fullmatch(r"(?:rakuten|sat)/\d+", args.force_review_ref) else None
        )
        reason = None
        if not args.apply:
            reason = "force_ref_requires_apply"
        elif force_scope is None:
            reason = "force_ref_invalid"
        elif args.source != "all" and args.source != force_scope:
            reason = "force_ref_source_mismatch"
        if reason:
            add_report(
                report_rows, kind="control", ref=args.force_review_ref[:120], status="error", reasons=[reason],
            )
            write_run_report(
                args.report_json, source=args.source, ranges=report_ranges, mode=mode,
                totals=totals, rows=report_rows, reparse=args.reparse,
            )
            return 2
    if args.source in {"nar", "all"}:
        totals["nar"] = run_nar(
            client, nar_start, end, args.apply, args.force_review_ref, report_rows, args.reparse,
        )
    if args.source in {"auction", "all"}:
        totals["auction"] = run_auction(
            client, auction_start, end, args.apply, args.force_review_ref, report_rows, args.reparse,
        )
    bad = 0
    for source, stats in totals.items():
        log(f"{source}: " + " ".join(f"{k}={v}" for k, v in stats.items()))
        bad += (
            stats.get("review", 0) + stats.get("changed", 0) +
            stats.get("not_ready", 0) + stats.get("error", 0) + stats.get("attention", 0)
        )
    if args.force_review_ref:
        matched = sum(stats.get("force_matched", 0) for stats in totals.values())
        applied = sum(stats.get("force_applied", 0) for stats in totals.values())
        if matched != 1 or applied != 1:
            reason = (
                "force_ref_not_found" if matched == 0 else
                "force_ref_matched_multiple" if matched > 1 else
                "force_ref_rpc_not_applied"
            )
            add_report(
                report_rows, kind="control", ref=args.force_review_ref, status="error", reasons=[reason],
                rpc_applied=applied == 1,
            )
            bad += 1
    write_run_report(
        args.report_json, source=args.source, ranges=report_ranges, mode=mode,
        totals=totals, rows=report_rows, reparse=args.reparse,
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

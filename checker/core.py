"""
xbrl_en_label_checker.py
========================
XBRL 확장 계정 영문명(en_label) 적절성 검토 도구
금융감독원 DART XBRL 재무제표 작성 가이드(2026.01) 기반

Usage:
    python xbrl_en_label_checker.py input.xlsx --company LG화학 --type 별도
    python xbrl_en_label_checker.py input.xlsm --pwc-encoded --company 사조씨푸드 --type 연결
    python xbrl_en_label_checker.py *.xlsx --batch --output-dir ./결과

    # Claude API 2차 검토 활성화
    python xbrl_en_label_checker.py input.xlsx --company LG화학 --type 별도 --ai-review
    python xbrl_en_label_checker.py input.xlsx --company LG화학 --type 별도 --ai-review --api-key sk-ant-...
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

# AI 리뷰어 (선택적 임포트 — 없어도 기본 동작)
try:
    from xbrl_ai_reviewer import AIIssue, prepare_entity_rows, review_labels
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
# Style constants
# ─────────────────────────────────────────────────────────────
VB_YELLOW  = "FFFF00"
VB_RED     = "FF0000"
HEADER_BG  = "DEDEDE"   # 14606046 (연한 회색)
HEADER_FG  = "1A1A1A"   # 거의 검정
FONT_NAME  = "맑은 고딕"
FONT_SIZE  = 9

# ─────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────
@dataclass
class Issue:
    error_type:        str
    description:       str
    highlight_en:      list[str] = field(default_factory=list)   # 기본 영문명 하이라이트
    highlight_ko:      list[str] = field(default_factory=list)   # 기본 한글명 하이라이트
    highlight_en2:     list[str] = field(default_factory=list)   # 표현 영문명 하이라이트
    highlight_ko2:     list[str] = field(default_factory=list)   # 표현 한글명 하이라이트
    is_full_en_error:  bool      = False   # 기본 영문명 전체가 오류
    is_full_en2_error: bool      = False   # 표현 영문명 전체가 오류


@dataclass
class RowResult:
    title:   str
    ko:      str          # ko_label
    en:      str          # en_label
    lt:      str          # labelTitle (표현속성)
    ko2:     str          # ko (표현 한글명)
    en2:     str          # en (표현 영문명)
    issues:  list[Issue]


# ─────────────────────────────────────────────────────────────
# PwC xlsm base64 decoder
# ─────────────────────────────────────────────────────────────
def decode_pwc(val) -> str:
    """Decode `pwcxbrl|<base64>` encoded labels; return raw string otherwise."""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if not s.startswith("pwcxbrl|"):
        return s
    b64 = s[len("pwcxbrl|"):]
    b64 = re.sub(r"_x000D_.*", "", b64)
    try:
        raw = base64.b64decode(b64 + "==")
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return s


# ─────────────────────────────────────────────────────────────
# Typo dictionary  (pattern, raw_typo, correction)
# ─────────────────────────────────────────────────────────────
TYPO_RULES: list[tuple[str, str, str]] = [
    # --- 일반 오탈자 ---
    (r"\bfoward\b",                      "foward",         "forward"),
    (r"\bfowards\b",                     "fowards",        "forwards"),
    (r"finanical",                        "finanical",      "financial"),
    (r"\bexchangable\b",                 "exchangable",    "exchangeable"),
    (r"liabilites(?!s)",                  "liabilites",     "liabilities"),
    (r"\bc urrent\b",                    "c urrent",       "current"),
    (r"\brecievable",                    "recievable",     "receivable"),
    (r"\brecievab",                      "recievab",       "receivab"),
    (r"\bdepreciation\s+accumulat",      None,             None),          # 이 패턴은 맞으니 패스
    (r"\baccumulat\s+depreciation",      None,             None),
    (r"\bintrest\b",                     "intrest",        "interest"),
    (r"\bpayable s\b",                   "payable s",      "payables"),
    (r"\breceivable s\b",                "receivable s",   "receivables"),
    (r"\binventary\b",                   "inventary",      "inventory"),
    (r"\binvetory\b",                    "invetory",       "inventory"),
    (r"\binventories\s+s\b",            "inventories s",  "inventories"),
    (r"\bdividened\b",                   "dividened",      "dividend"),
    (r"\bdividened\b",                   "dividened",      "dividend"),
    (r"\bconsolidatd\b",                 "consolidatd",    "consolidated"),
    (r"\bamortizaion\b",                 "amortizaion",    "amortization"),
    # amortisation은 IFRS 영국식 표기로 유효 — 제거
    (r"\bdepreication\b",                "depreication",   "depreciation"),
    (r"\bimpairmet\b",                   "impairmet",      "impairment"),
    (r"\bimpariment\b",                  "impariment",     "impairment"),
    (r"\bexpendiutre\b",                 "expendiutre",    "expenditure"),
    (r"\bexpenditure s\b",              "expenditure s",  "expenditures"),
    (r"\bsuplier\b",                     "suplier",        "supplier"),
    (r"\bprepiad\b",                     "prepiad",        "prepaid"),
    (r"\btransation\b",                  "transation",     "transaction"),
    (r"\btransctions\b",                 "transctions",    "transactions"),
    (r"\bsubsidary\b",                   "subsid ary",     "subsidiary"),
    (r"\bsubsidiary s\b",               "subsidiary s",   "subsidiaries"),
    (r"\baffilait",                      "affilait",       "affiliat"),
    (r"\baffilat(?!e)",                  "affiliat",       "affiliate"),
    (r"\bsecurit(?!ies|y)\b",            "securit",        "security/securities"),
    (r"\bcash equilvalent",              "equilvalent",    "equivalent"),
    (r"\bequivalant\b",                  "equivalant",     "equivalent"),
    (r"\bborrowing s\b",                "borrowing s",    "borrowings"),
    (r"\bnon-current\s+non-current\b",  "이중 non-current","non-current (중복)"),
    (r"\bcurrent\s+current\b",          "current current","current (중복)"),
    # --- 이중 공백은 별도 체크 ---
]

# 대/소문자 오류: en_label 첫 글자는 대문자여야 하는 경우 체크는 
# 자연어 문장형 레이블에만 적용 (CamelCase가 아닌 경우)

# ─────────────────────────────────────────────────────────────
# Known XBRL suffix patterns (these indicate XBRL IDs, not labels)
# ─────────────────────────────────────────────────────────────
XBRL_SUFFIX_RE = re.compile(
    r"(Abstract|Table|LineItems|Lineitems|LineItem|Member|Axis|Domain|"
    r"Explanatory|Explantion|LinkRole|Roll[Ff]orward)$"
)

# XBRL 구조 요소 타입 (Abstract, Table 등은 en_label이 XBRL ID여도 허용)
STRUCTURAL_SUFFIX_RE = re.compile(
    r"\[(abstract|table|line\s*items|항목|개요|표|문장영역)\]",
    re.IGNORECASE,
)

# 회사 고유 확장 Member 이름: CamelCase + Member 로 끝나는 패턴
ENTITY_MEMBER_RE = re.compile(r"^[A-Z][A-Za-z]+Member$")

# ─────────────────────────────────────────────────────────────
# Core detection logic
# ─────────────────────────────────────────────────────────────
def _is_camel_case_id(s: str) -> bool:
    """True if s looks like a pure XBRL CamelCase element ID (no spaces, ≥2 uppercase transitions)."""
    if " " in s:
        return False
    # At least 2 capital letter transitions (Word boundaries)
    caps = len(re.findall(r"[A-Z]", s))
    return caps >= 3 and bool(re.match(r"^[A-Z][a-z]", s))


def _contains_korean(s: str) -> bool:
    return bool(re.search(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]", s))


def _detect_typos_in(text: str, field: str = "en") -> list[Issue]:
    """
    단순 오탈자를 주어진 텍스트에서 검출한다.
    field: "en"  → highlight_en  (기본 영문명)
           "en2" → highlight_en2 (표현 영문명)
    """
    issues: list[Issue] = []
    for pattern, typo, correct in TYPO_RULES:
        if typo is None:
            continue
        if re.search(pattern, text, re.IGNORECASE):
            kw = {"highlight_" + field: [typo]}
            issues.append(Issue(
                error_type  = "단순 오탈자",
                description = f'"{typo}" → "{correct}" 로 수정 필요',
                **kw,
            ))
    if "  " in text:
        issues.append(Issue(
            error_type  = "단순 오탈자",
            description = "이중 공백 포함 — 단일 공백으로 수정 필요",
        ))
    text_s = text.strip()
    if text_s.endswith(".") and not text_s.endswith("..."):
        kw = {"highlight_" + field: ["."]}
        issues.append(Issue(
            error_type  = "단순 오탈자",
            description = f'{"기본" if field == "en" else "표현"} 영문명 끝에 마침표(".") 불필요',
            **kw,
        ))
    return issues


def detect_issues(
    en:          str,
    ko:          str  = "",
    en2:         str  = "",
    ko2:         str  = "",
    prefix:      str  = "",
    label_title: str  = "기본",
) -> list[Issue]:
    """
    오탈자·원칙 위배를 탐지한다.

    오탈자 검사 범위 (가이드 §4.Ⅰ.3 기반):
        - prefix == 'entity'        → 기본 영문명(en_label) 오탈자 검사
        - prefix != 'entity'
            labelTitle != '기본'    → 표현 영문명(en2)만 오탈자 검사
            labelTitle == '기본'    → 오탈자 검사 없음 (표준 계정은 검사 불필요)

    영문명 미기재 / XBRL 확장 원칙 위배는 entity prefix 항목에만 적용.
    """
    is_entity = prefix.startswith("entity") or prefix == ""
    en_s      = en.strip()
    issues: list[Issue] = []

    # ═══════════════════════════════════════════════════════════
    # entity prefix: 전체 검사 (미기재 + 확장원칙 + 오탈자)
    # ═══════════════════════════════════════════════════════════
    if is_entity:

        # ── (A) 영문명 미기재 ─────────────────────────────────
        if not en_s:
            return []

        PLACEHOLDER_RE = re.compile(
            r"^(item|title)([-_]\d+)?(\s*\[.*\])?\s*$", re.IGNORECASE
        )
        if PLACEHOLDER_RE.match(en_s):
            issues.append(Issue(
                error_type       = "영문명 미기재",
                description      = (
                    f"⚠ 정정공시 대상 ⚠ — 기본 영문명에 적절한 영문 표준명이 기재되지 않음 "
                    f'(현재값: "{en_s}")'
                ),
                highlight_en     = [en_s],
                is_full_en_error = True,
            ))
            return issues

        # ── 한글 annotation suffix 패턴: "English text [구성요소|축]" ─
        # XBRL 요소 유형 annotation이 한글로 입력된 경우
        # (en_label에서는 [member]/[axis]/[table] 등 영문을 써야 함)
        _KR_ANNOT_MAP = {
            "구성요소": "member",
            "축":       "axis",
            "표":       "table",
            "항목":     "line items",
            "개요":     "abstract",
            "문장영역": "text block",
        }
        _KR_ANNOT_RE = re.compile(
            r"\[(" + "|".join(_KR_ANNOT_MAP.keys()) + r")\]",
            re.IGNORECASE,
        )
        annot_match = _KR_ANNOT_RE.search(en_s)
        eng_without_annot = _KR_ANNOT_RE.sub("", en_s).strip()

        if annot_match and not _contains_korean(eng_without_annot):
            # 순수 영문 본문 + 한글 suffix
            kr_sfx  = annot_match.group(1)
            en_sfx  = _KR_ANNOT_MAP.get(kr_sfx, kr_sfx)
            issues.append(Issue(
                error_type       = "단순 오탈자",
                description      = (
                    f"영문명 내 XBRL 요소 유형이 한글로 입력됨 — "
                    f'"[{kr_sfx}]" → "[{en_sfx}]" 로 수정 필요'
                ),
                highlight_en     = [annot_match.group()],
                is_full_en_error = False,
            ))
            return issues

        if _contains_korean(en_s):
            issues.append(Issue(
                error_type       = "영문명 미기재",
                description      = "기본 영문명 필드에 한글이 입력됨 — 영문 표준명으로 대체 필요",
                is_full_en_error = True,
            ))
            return issues

        # ── (B) XBRL 확장 원칙 위배 ───────────────────────────
        violations: list[str] = []
        hi_ext: list[str]     = []

        # (B-1) FootNote 포함
        m_fn = re.search(r"foot\s*note", en, re.IGNORECASE)
        if m_fn:
            hi_ext.append(m_fn.group())
            violations.append(
                '"FootNote" 포함 — 주석 참조 형식은 확장 요소 기본 영문명으로 부적합 '
                "(가이드 §4.Ⅰ.3)"
            )

        # (B-2) ~주기 / Disclosure Note 형식
        if re.search(r"주기", ko + ko2):
            violations.append(
                '"~주기" 형식 — XBRL 확장 원칙상 독립 요소로 부적합 (가이드 §4.Ⅰ.3)'
            )
        if re.search(r"disclosure\s+note", en, re.IGNORECASE):
            hi_ext.append("disclosure note")
            violations.append('"Disclosure Note" 형식 — 가이드 §4.Ⅰ.3 위배')

        # (B-3) CamelCase XBRL ID
        is_structural = bool(STRUCTURAL_SUFFIX_RE.search(en_s))
        if not is_structural and _is_camel_case_id(en_s) and not XBRL_SUFFIX_RE.search(en_s):
            hi_ext.append(en_s[:80])
            violations.append(
                "CamelCase XBRL 요소 ID가 기본 영문명으로 입력됨 — "
                "공백 구분 자연어 형식(Natural Language Label)으로 기재 필요 "
                "(가이드 §3.Ⅱ.2.(4), §4.Ⅰ.3.(3))"
            )

        # (B-4) DescriptionOf...
        if re.match(r"^Description[A-Z]", en_s) and " " not in en_s[:50]:
            hi_ext.append(en_s[:60])
            violations.append(
                '"DescriptionOf..." 형태의 XBRL 요소 ID가 기본 영문명으로 입력됨 '
                "(가이드 §3.Ⅱ.2.(4))"
            )

        # (B-5) XxxAndXxx
        if re.match(r"^[A-Z][a-z]+And[A-Z]", en_s) and " " not in en_s:
            m2 = re.match(r"^[A-Za-z]+", en_s)
            hi_ext.append(m2.group() if m2 else en_s[:30])
            violations.append(
                "XBRL 요소 ID 형식(XxxAndXxx)이 기본 영문명으로 입력됨 "
                "(가이드 §3.Ⅱ.2.(4))"
            )

        # (B-6) Member 접미사 누락
        if (
            _is_camel_case_id(en_s)
            and not XBRL_SUFFIX_RE.search(en_s)
            and re.search(r"(Co|Corp|Ltd|Inc|Llc|Plc|Gmbh|SA|SAS|BV)$", en_s, re.IGNORECASE)
        ):
            hi_ext.append(en_s[-20:])
            violations.append(
                '구성요소(Member) 이름에 "Member" 접미사 누락 — '
                'XBRL 표준상 구성요소 ID 마지막에 "Member"를 붙여야 함 '
                "(가이드 §2.Ⅱ.2.(3), §5.Ⅲ.19.(3))"
            )

        # (B-7) 너무 짧은 영문명
        if re.match(r"^[A-Za-z]{1,3}$", en_s):
            violations.append(
                f'기본 영문명이 너무 짧음("{en_s}") — 회계 개념을 충분히 설명하는 영문명 기재 필요 '
                "(가이드 §3.Ⅱ.2.(4))"
            )

        # (B-8) 총액/순액 접미사 누락
        if re.search(r"총액", ko) and not re.search(r"Gross", en_s, re.IGNORECASE):
            violations.append(
                '한글명에 "총액" 포함 — XBRL 이름(Name)에 "Gross" 접미사 추가 필요 '
                "(가이드 §3.Ⅱ.2.(4))"
            )
        if re.search(r"순액", ko) and not re.search(r"Net", en_s, re.IGNORECASE):
            violations.append(
                '한글명에 "순액" 포함 — XBRL 이름(Name)에 "Net" 접미사 추가 필요 '
                "(가이드 §3.Ⅱ.2.(4))"
            )

        # (B-9) 현금흐름 조정 접두사 누락
        if re.search(r"현금흐름.*조정|조정.*현금흐름", ko) and not re.search(
            r"AdjustmentsFor", en_s
        ):
            violations.append(
                "현금흐름표 조정 항목 — XBRL 표준상 이름(Name)을 "
                '"AdjustmentsFor"로 시작해야 함 (가이드 §4.Ⅰ.6)'
            )

        if violations:
            issues.append(Issue(
                error_type       = "XBRL 확장 원칙 위배",
                description      = " | ".join(violations),
                highlight_en     = hi_ext,
                is_full_en_error = True,
            ))

        # ── (C) 오탈자: 기본 영문명(en) ────────────────────────
        issues.extend(_detect_typos_in(en, field="en"))

    # ═══════════════════════════════════════════════════════════
    # 비(非) entity prefix: labelTitle이 '기본'이 아닌 경우만
    # 표현 영문명(en2)에 대해서만 오탈자 검사
    # ═══════════════════════════════════════════════════════════
    elif label_title != "기본":
        if en2:
            issues.extend(_detect_typos_in(en2, field="en2"))

    # prefix != entity + labelTitle == '기본' → 검사 없음

    return issues


# ─────────────────────────────────────────────────────────────
# Excel output helpers
# ─────────────────────────────────────────────────────────────
def _make_rich_text(
    text: str,
    patterns: list[str],
    bold: bool = False,
    italic: bool = False,
    base_color: str | None = None,
) -> "CellRichText | str":
    """
    패턴에 매칭되는 부분을 빨간 글자로 강조한 CellRichText를 반환한다.
    매칭이 없으면 원본 문자열 반환.

    InlineFont.sz 는 포인트 단위 (9 = 9pt).
    CellRichText 셀에 c.font 를 별도로 설정하면 크기가 재해석될 수 있으므로
    normal/red 모두 sz 를 명시적으로 고정한다.
    """
    if not text or not patterns:
        return text or ""
    normal = InlineFont(
        rFont=FONT_NAME, sz=FONT_SIZE,
        b=bold, i=italic,
        color=base_color or "000000",
    )
    red = InlineFont(
        rFont=FONT_NAME, sz=FONT_SIZE,
        b=bold, i=italic,
        color=VB_RED,
    )
    pos: list[tuple[int, int]] = []
    for p in patterns:
        for m in re.finditer(re.escape(p), text, re.IGNORECASE):
            pos.append((m.start(), m.end()))
    if not pos:
        return text
    pos.sort()
    merged: list[tuple[int, int]] = []
    for s, e in pos:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    blocks: list[TextBlock] = []
    prev = 0
    for s, e in merged:
        if prev < s:
            blocks.append(TextBlock(normal, text[prev:s]))
        blocks.append(TextBlock(red, text[s:e]))
        prev = e
    if prev < len(text):
        blocks.append(TextBlock(normal, text[prev:]))
    return CellRichText(*blocks)


def _format_description(desc: str) -> "CellRichText | str":
    """
    ErrorDescription 셀 값을 포맷한다.

    '정정공시 대상' 포함 시:
        1행(빨강 볼드): "정정공시 대상"
        2행(일반):      나머지 설명 (이모지·구분자 제거)
    그 외: 원본 문자열 반환.
    """
    if "정정공시 대상" not in desc:
        return desc

    # 이모지 및 앞뒤 구분자 제거 후 나머지 추출
    # 예: "⚠ 정정공시 대상 ⚠ — 기본 영문명에 ..."  →  "기본 영문명에 ..."
    EMOJI_RE  = re.compile(r"[⚠️\u26A0\uFE0F\u203C\u2757]+")
    stripped  = EMOJI_RE.sub("", desc)
    # "정정공시 대상" 앞뒤를 분리
    parts = re.split(r"정정공시\s*대상", stripped, maxsplit=1)
    rest  = parts[1] if len(parts) > 1 else ""
    # 앞쪽 구분자 제거 (—, -, ─, 공백)
    rest  = re.sub(r"^[\s\-—─]+", "", rest).strip()

    # 첫 번째 줄: 빨강 (sz=포인트 단위)
    red_if = InlineFont(rFont=FONT_NAME, sz=FONT_SIZE, b=True,  color=VB_RED)
    # 두 번째 줄: 일반
    nor_if = InlineFont(rFont=FONT_NAME, sz=FONT_SIZE, color="333333")
    if rest:
        return CellRichText(
            TextBlock(red_if, "정정공시 대상"),
            TextBlock(nor_if, f"\n{rest}"),
        )
    return CellRichText(TextBlock(red_if, "정정공시 대상"))


def _apply_full_border(ws, nrows: int, ncols: int) -> None:
    inner = Side(style="dotted", color="AAAAAA")
    outer = Side(style="thin",   color="000000")
    for r in range(1, nrows + 1):
        for c in range(1, ncols + 1):
            ws.cell(r, c).border = Border(
                left   = outer if c == 1     else inner,
                right  = outer if c == ncols else inner,
                top    = outer if r == 1     else inner,
                bottom = outer if r == nrows else inner,
            )


# ─────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────
HEADERS    = [
    "Index", "Report",
    "기본 한글명", "기본 영문명",
    "표현속성", "표현 한글명", "표현 영문명",
    "ErrorType", "ErrorDescription",
]
COL_WIDTHS = [7, 28, 32, 55, 18, 30, 55, 22, 70]


def generate_report(
    results:    list[RowResult],
    out_path,           # Path | io.BytesIO
    company:    str,
    btype:      str,
    total_rows: int,
) -> None:
    """
    검사 결과를 Excel 파일로 출력한다.

    변경 사항:
    - 헤더 배경 DEDEDE (연한 회색), 글자 진한 색
    - [AI] 접두사 제거 (ErrorType 표시 시)
    - 정정공시 대상: 이모지 제거, 1행(빨강) + 줄바꿈 + 2행(일반)
    - 표현 한글명 / 표현 영문명에도 오류 시 interior·font 색상 적용
    - 전체 데이터 ListObject (Excel Table) 처리
    - 가운데 맞춤 없음, 위쪽 맞춤 + 줄바꿈
    - insert_rows 제거 → 플랫(flat) 행 순서로 직접 기재
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "검사결과"

    COLS = {h: i + 1 for i, h in enumerate(HEADERS)}
    N    = len(HEADERS)

    # ── 공통 스타일 ────────────────────────────────────────────
    hdr_font  = Font(name=FONT_NAME, bold=True,  size=FONT_SIZE, color=HEADER_FG)
    hdr_fill  = PatternFill("solid", start_color=HEADER_BG)
    norm_font = Font(name=FONT_NAME, size=FONT_SIZE)
    err_font  = Font(name=FONT_NAME, bold=True,  size=FONT_SIZE, color="CC0000")
    desc_font = Font(name=FONT_NAME, italic=True, size=FONT_SIZE, color="333333")
    yell_fill = PatternFill("solid", start_color=VB_YELLOW)
    TOP       = Alignment(horizontal="left", vertical="top", wrap_text=True)
    TOP_CTR   = Alignment(horizontal="left", vertical="top", wrap_text=True)

    # ── 헤더 행 ────────────────────────────────────────────────
    for ci, (h, w) in enumerate(zip(HEADERS, COL_WIDTHS), 1):
        cell           = ws.cell(1, ci, h)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.alignment = TOP
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[1].height = 22

    # ── 데이터 없음 ────────────────────────────────────────────
    if not results:
        c = ws.cell(2, 1, "이상 없음")
        c.font      = Font(name=FONT_NAME, bold=True, size=10, color="008000")
        c.alignment = Alignment(horizontal="left", vertical="top")
        ws.merge_cells("A2:I2")
        _apply_full_border(ws, 2, N)
        ws.freeze_panes = "A2"
        wb.save(out_path)
        return

    # ── RowResult → 플랫 행 목록 ───────────────────────────────
    # 각 RowResult의 오류 판정을 필드별로 독립적으로 계산한 후 평탄화한다.
    flat: list[dict] = []

    for rr in results:
        all_hi_en  = [p for iss in rr.issues for p in iss.highlight_en]
        all_hi_ko  = [p for iss in rr.issues for p in iss.highlight_ko]
        all_hi_en2 = [p for iss in rr.issues for p in iss.highlight_en2]
        all_hi_ko2 = [p for iss in rr.issues for p in iss.highlight_ko2]

        is_full_en  = any(i.is_full_en_error  for i in rr.issues)
        is_full_en2 = any(i.is_full_en2_error for i in rr.issues)

        def _has_match(patterns, text):
            return bool(patterns and any(
                re.search(re.escape(p), text or "", re.I) for p in patterns
            ))

        # 필드별 오류 여부 (interior.color 적용 기준)
        en_err  = is_full_en  or _has_match(all_hi_en,  rr.en)
        ko_err  = _has_match(all_hi_ko,  rr.ko)
        en2_err = is_full_en2 or (bool(rr.en2) and _has_match(all_hi_en2, rr.en2))
        ko2_err = bool(rr.ko2) and _has_match(all_hi_ko2, rr.ko2)

        # 오탈자 패턴 강조 포함 rich-text 값 (매칭 없으면 원본 str 반환)
        en_val  = _make_rich_text(rr.en,  all_hi_en)  if all_hi_en  else rr.en
        ko_val  = _make_rich_text(rr.ko,  all_hi_ko)  if all_hi_ko  else rr.ko
        en2_val = _make_rich_text(rr.en2, all_hi_en2) if all_hi_en2 else rr.en2
        ko2_val = _make_rich_text(rr.ko2, all_hi_ko2) if all_hi_ko2 else rr.ko2

        for ii, iss in enumerate(rr.issues):
            flat.append(dict(
                rr=rr, iss=iss, is_first=(ii == 0),
                en_val=en_val,   ko_val=ko_val,
                en2_val=en2_val, ko2_val=ko2_val,
                en_err=en_err,   ko_err=ko_err,
                en2_err=en2_err, ko2_err=ko2_err,
            ))

    # ── 데이터 행 기재 ─────────────────────────────────────────
    for seq, row in enumerate(flat, 1):
        ri  = seq + 1          # 헤더가 row 1
        rr  = row["rr"]
        iss = row["iss"]
        fst = row["is_first"]

        def _wcell(col_name, val, *, is_rich=False, font=norm_font, fill=None):
            """
            셀에 값을 기록하고 스타일을 적용한다.
            is_rich=True 이면 CellRichText가 포함될 수 있으므로
            c.font 를 설정하지 않는다 — InlineFont 의 sz 가 보존된다.
            """
            c = ws.cell(ri, COLS[col_name], val)
            c.alignment = TOP
            if fill:
                c.fill = fill
            if not is_rich:
                c.font = font
            return c

        # Index
        _wcell("Index", seq)

        # Report
        _wcell("Report", rr.title)

        # ── 기본 한글명 ──────────────────────────────────────────
        ko_v    = row["ko_val"] if fst else rr.ko
        ko_fill = yell_fill if (fst and row["ko_err"]) else None
        _wcell("기본 한글명",
               ko_v,
               is_rich=isinstance(ko_v, CellRichText),
               fill=ko_fill)

        # ── 기본 영문명 ──────────────────────────────────────────
        en_v    = row["en_val"] if fst else rr.en
        en_fill = yell_fill if (fst and row["en_err"]) else None
        _wcell("기본 영문명",
               en_v,
               is_rich=isinstance(en_v, CellRichText),
               fill=en_fill)

        # ── 표현속성 ─────────────────────────────────────────────
        _wcell("표현속성", rr.lt)

        # ── 표현 한글명 ──────────────────────────────────────────
        ko2_v    = row["ko2_val"] if fst else rr.ko2
        ko2_fill = yell_fill if (fst and row["ko2_err"]) else None
        _wcell("표현 한글명",
               ko2_v,
               is_rich=isinstance(ko2_v, CellRichText),
               fill=ko2_fill)

        # ── 표현 영문명 ──────────────────────────────────────────
        en2_v    = row["en2_val"] if fst else rr.en2
        en2_fill = yell_fill if (fst and row["en2_err"]) else None
        _wcell("표현 영문명",
               en2_v,
               is_rich=isinstance(en2_v, CellRichText),
               fill=en2_fill)

        # ── ErrorType — [AI] 접두사 제거 후 표시 ─────────────────
        etype = re.sub(r"^\[AI\]\s*", "", iss.error_type)
        _wcell("ErrorType", etype, font=err_font)

        # ── ErrorDescription — 정정공시 대상 포맷 적용 ───────────
        desc_val = _format_description(iss.description)
        c = ws.cell(ri, COLS["ErrorDescription"], desc_val)
        c.alignment = TOP
        if not isinstance(desc_val, CellRichText):
            c.font = desc_font

        ws.row_dimensions[ri].height = 42

    # ── 테두리 ─────────────────────────────────────────────────
    last_row = len(flat) + 1
    _apply_full_border(ws, last_row, N)

    # ── ListObject (Excel Table) ────────────────────────────────
    tbl_ref   = f"A1:{get_column_letter(N)}{last_row}"
    tbl       = Table(displayName="InspectionResults", ref=tbl_ref)
    tbl_style = TableStyleInfo(
        name             = "TableStyleLight9",
        showFirstColumn  = False,
        showLastColumn   = False,
        showRowStripes   = False,   # 수동 fill과 충돌 방지
        showColumnStripes= False,
    )
    tbl.tableStyleInfo = tbl_style
    ws.add_table(tbl)

    ws.freeze_panes = "A2"
    wb.save(out_path)


# ─────────────────────────────────────────────────────────────
# File ingestion
# ─────────────────────────────────────────────────────────────
SHEET_CANDIDATES = [
    "XBRLMPMaster", "연결", "별도", "Sheet1", "Data", "재무제표", "MPMaster"
]


def _read_dataframe(path: Path, pwc_encoded: bool = False) -> pd.DataFrame:
    """Read the source xlsx/xlsm and return a normalized DataFrame."""
    # Detect sheet
    xl = pd.ExcelFile(path, engine="openpyxl")
    sheet = None
    for candidate in SHEET_CANDIDATES:
        if candidate in xl.sheet_names:
            sheet = candidate
            break
    if sheet is None:
        sheet = xl.sheet_names[0]

    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")

    # Decode PwC base64 encoded labels if requested
    if pwc_encoded:
        for col in ["ko_label", "en_label", "ko", "en"]:
            if col in df.columns:
                df[col] = df[col].apply(decode_pwc)
    else:
        for col in ["ko_label", "en_label", "ko", "en"]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def _has_extra_columns(df: pd.DataFrame) -> bool:
    return all(c in df.columns for c in ["labelTitle", "ko", "en"])


def run_check(
    path:        Path,
    company:     str,
    btype:       str,
    output_dir:  Path,
    pwc_encoded: bool = False,
    ai_review:   bool = False,
    ai_engine:   str  = "claude",
    api_key:     str  = "",
) -> Path:
    """
    Main entry point: run checks on a single file and write the Excel report.
    Returns the output path.
    """
    df = _read_dataframe(path, pwc_encoded=pwc_encoded)
    has_extra = _has_extra_columns(df)

    # ── 1단계: 규칙 기반 검사 ────────────────────────────────
    # row_idx → RowResult 매핑 (AI 병합용)
    result_map: dict[int, RowResult] = {}
    results: list[RowResult] = []

    for idx, row in df.iterrows():
        en    = str(row.get("en_label", "") or "").strip()
        ko    = str(row.get("ko_label", "") or "").strip()
        en2   = str(row.get("en",       "") or "").strip() if has_extra else ""
        ko2   = str(row.get("ko",       "") or "").strip() if has_extra else ""
        lt    = str(row.get("labelTitle","") or "").strip() if has_extra else ""
        title = str(row.get("Title",    "") or "").strip()
        pfx   = str(row.get("prefix",   "") or "").strip()

        issues = detect_issues(en, ko, en2, ko2, prefix=pfx, label_title=lt)
        rr = RowResult(title=title, ko=ko, en=en, lt=lt, ko2=ko2, en2=en2, issues=issues)
        if issues:
            results.append(rr)
        result_map[idx] = rr   # AI 이슈 병합을 위해 항상 저장

    # ── 2단계: Claude API 2차 검토 ───────────────────────────
    n_ai = 0
    if ai_review:
        if not _AI_AVAILABLE:
            print("  [AI] xbrl_ai_reviewer.py 를 찾을 수 없습니다. AI 검토를 건너뜁니다.")
        else:
            entity_rows = prepare_entity_rows(df)
            ai_issues   = review_labels(entity_rows, engine=ai_engine, api_key=api_key, verbose=True)

            for ai_iss in ai_issues:
                rr = result_map.get(ai_iss.row_idx)
                if rr is None:
                    continue

                # Issue 객체로 변환
                if ai_iss.field == "en_label":
                    iss = Issue(
                        error_type   = f"[AI] {ai_iss.error_type}",
                        description  = ai_iss.description,
                        highlight_en = ai_iss.highlight,
                    )
                else:
                    iss = Issue(
                        error_type    = f"[AI] {ai_iss.error_type}",
                        description   = ai_iss.description,
                        highlight_en2 = ai_iss.highlight,
                    )

                rr.issues.append(iss)
                # 아직 결과 목록에 없으면 추가
                if rr not in results:
                    results.append(rr)
                n_ai += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{company}_{btype}_오탈자검사.xlsx"
    generate_report(results, out_path, company, btype, total_rows=len(df))

    n_violations = sum(
        1 for rr in results
        for iss in rr.issues
        if iss.error_type == "XBRL 확장 원칙 위배"
    )
    n_missing = sum(
        1 for rr in results
        for iss in rr.issues
        if iss.error_type == "영문명 미기재"
    )
    n_typo = sum(
        1 for rr in results
        for iss in rr.issues
        if iss.error_type == "단순 오탈자"
    )
    print(
        f"[{company} {btype}] {len(df):,}행 검사 → "
        f"오류항목 {len(results)}건 "
        f"(영문명미기재:{n_missing} / 확장원칙위배:{n_violations} / 오탈자:{n_typo})"
    )
    print(f"  → {out_path}")
    return out_path


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="XBRL 확장 계정 영문명(en_label) 적절성 검토 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python xbrl_en_label_checker.py LG화학.xlsx --company LG화학 --type 별도
  python xbrl_en_label_checker.py 사조씨푸드.xlsm --pwc-encoded --company 사조씨푸드 --type 연결
  python xbrl_en_label_checker.py *.xlsx --batch --output-dir ./결과
        """,
    )
    p.add_argument("inputs",        nargs="+", help="검사할 xlsx/xlsm 파일 경로 (glob 가능)")
    p.add_argument("--company",     default="",      help="회사명 (단일 파일 처리시)")
    p.add_argument("--type",        default="별도",  help="구분: 별도 | 연결 (단일 파일 처리시)")
    p.add_argument("--output-dir",  default="./결과", help="결과 파일 저장 경로 (기본: ./결과)")
    p.add_argument("--pwc-encoded", action="store_true",
                   help="PwC xlsm 파일의 base64 인코딩된 레이블 디코딩 활성화")
    p.add_argument("--batch",       action="store_true",
                   help="다수 파일 일괄 처리 — 파일명에서 회사명/구분 자동 추출")
    p.add_argument("--ai-review",   action="store_true",
                   help="Claude API 2차 정밀 검토 활성화")
    p.add_argument("--engine",      default="claude",
                   choices=["spellcheck", "claude", "both"],
                   help="2차 검토 엔진 (기본: claude, --ai-review 시 유효)")
    p.add_argument("--api-key",     default="",
                   help="Anthropic API 키 (미지정 시 ANTHROPIC_API_KEY 환경변수)")
    return p


def _infer_meta_from_filename(fname: str) -> tuple[str, str]:
    """
    파일명에서 회사명과 구분(별도/연결)을 추론합니다.
    예: LG화학_2512_별도.xlsx → ("LG화학", "별도")
        XBRL-Wizard_한화솔루션_2512_연결.xlsx → ("한화솔루션", "연결")
    """
    stem = Path(fname).stem
    # 구분 추출
    btype = "별도"
    if "연결" in stem:
        btype = "연결"
    elif "별도" in stem:
        btype = "별도"

    # XBRL-Wizard_ 또는 숫자_ 접두사 제거 후 첫 번째 한글 토큰을 회사명으로
    stem_clean = re.sub(r"^(XBRL-Wizard_|XBRL_Wizard_|\d{8}_)", "", stem)
    parts = re.split(r"[_\-]", stem_clean)
    # 첫 번째 의미 있는 파트 (숫자 아닌 것)
    company = ""
    for part in parts:
        if part and not re.match(r"^\d+$", part) and part not in ("별도", "연결", "v1", "v2", "v3"):
            company = part
            break
    return company or stem, btype


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    output_dir = Path(args.output_dir)
    all_files: list[Path] = []
    for pattern in args.inputs:
        p = Path(pattern)
        if p.exists():
            all_files.append(p)
        else:
            parent = p.parent if p.parent != Path(".") else Path(".")
            matched = list(parent.glob(p.name))
            all_files.extend(matched if matched else [p])

    if not all_files:
        print("오류: 입력 파일을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    for fp in all_files:
        if not fp.exists():
            print(f"경고: 파일을 찾을 수 없음 — {fp}", file=sys.stderr)
            continue

        if args.batch or len(all_files) > 1:
            company, btype = _infer_meta_from_filename(fp.name)
        else:
            company = args.company or fp.stem
            btype   = args.type

        pwc = args.pwc_encoded or fp.suffix.lower() == ".xlsm"

        run_check(
            path        = fp,
            company     = company,
            btype       = btype,
            output_dir  = output_dir,
            pwc_encoded = pwc,
            ai_review   = args.ai_review,
            ai_engine   = args.engine,
            api_key     = args.api_key,
        )


if __name__ == "__main__":
    main()


def run_check_bytes(
    file_bytes:  bytes,
    filename:    str,
    company:     str,
    btype:       str,
    pwc_encoded: bool = False,
) -> tuple:
    """
    Streamlit 용: 파일 바이트를 받아 검사 결과 Excel 바이트를 반환한다.
    Returns (excel_bytes, stats_dict)
    """
    import io
    import tempfile

    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        df        = _read_dataframe(tmp_path, pwc_encoded=pwc_encoded)
        has_extra = _has_extra_columns(df)

        results:    list[RowResult] = []
        result_map: dict[int, RowResult] = {}

        for idx, row in df.iterrows():
            en    = str(row.get("en_label",  "") or "").strip()
            ko    = str(row.get("ko_label",  "") or "").strip()
            en2   = str(row.get("en",        "") or "").strip() if has_extra else ""
            ko2   = str(row.get("ko",        "") or "").strip() if has_extra else ""
            lt    = str(row.get("labelTitle","") or "").strip() if has_extra else ""
            title = str(row.get("Title",     "") or "").strip()
            pfx   = str(row.get("prefix",    "") or "").strip()

            issues = detect_issues(en, ko, en2, ko2, prefix=pfx, label_title=lt)
            rr = RowResult(title=title, ko=ko, en=en, lt=lt, ko2=ko2, en2=en2, issues=issues)
            if issues:
                results.append(rr)
            result_map[idx] = rr

        buf = io.BytesIO()
        generate_report(results, buf, company, btype, total_rows=len(df))
        buf.seek(0)
        excel_bytes = buf.read()

        stats = {
            "total_rows":  len(df),
            "issue_count": len(results),
            "n_missing":   sum(1 for rr in results for i in rr.issues if i.error_type == "영문명 미기재"),
            "n_violation": sum(1 for rr in results for i in rr.issues if i.error_type == "XBRL 확장 원칙 위배"),
            "n_typo":      sum(1 for rr in results for i in rr.issues if i.error_type == "단순 오탈자"),
        }
        return excel_bytes, stats

    finally:
        tmp_path.unlink(missing_ok=True)

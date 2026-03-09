"""
xbrl_ai_reviewer.py
====================
XBRL 확장 계정 영문명 2차 정밀 검토 모듈.

두 가지 엔진을 지원합니다:

  1. pyspellchecker  — 오프라인 철자 검사 (pip install pyspellchecker)
     - 빠름, 무료, 재무 전문 용어 화이트리스트 내장
     - 단순 철자 오류에 특화

  2. Claude API      — 문맥 기반 정밀 검토 (ANTHROPIC_API_KEY 필요)
     - IFRS 표준 용어 / 영국식·미국식 구분
     - 한영 의미 불일치, 부자연스러운 표현까지 탐지
     - entity prefix 행에만 적용 (비용 최소화)

단독 실행:
    python xbrl_ai_reviewer.py input.xlsx --engine spellcheck
    python xbrl_ai_reviewer.py input.xlsx --engine claude --api-key sk-ant-...

xbrl_en_label_checker.py 에서 --ai-review 플래그로 자동 호출됩니다.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────
# pyspellchecker 선택적 임포트
# ─────────────────────────────────────────────────────────────
try:
    from spellchecker import SpellChecker
    _SPELL_AVAILABLE = True
except ImportError:
    _SPELL_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
# Claude API 설정
# ─────────────────────────────────────────────────────────────
API_URL    = "https://api.anthropic.com/v1/messages"
MODEL      = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048
BATCH_SIZE = 25       # 한 번에 보낼 레이블 수
MAX_RETRIES = 3
RETRY_DELAY = 2.0

# ─────────────────────────────────────────────────────────────
# IFRS / 재무 회계 전문 용어 화이트리스트
# (pyspellchecker 가 틀렸다고 판단하지 않도록)
# ─────────────────────────────────────────────────────────────
FINANCIAL_WHITELIST: set[str] = {
    # IFRS 영국식 표기 — 오탈자 아님
    "amortisation", "amortisations", "amortised",
    "recognised", "recognise", "recognisable",
    "realised", "unrealised",
    "capitalised", "uncapitalised",
    "impairment", "impairments",
    "goodwill", "intangibles",
    "lessee", "lessor",
    "receivable", "receivables",
    "payable", "payables",
    "inventories", "inventory",
    "depreciation", "depreciable",
    "deferred", "deferral",
    "hedging", "hedged",
    "remeasurement", "remeasurements",
    "reclassification", "reclassifications",
    "revaluation", "revaluations",
    "onerous",
    "hyperinflationary",
    "consolidation", "consolidated",
    "acquiree", "acquirer",
    "subsidiaries", "subsidiary",
    "associates",
    "counterparty",
    "lien",
    "prepaid", "prepayment",
    "collateral",
    "tranche",
    "annuitization",
    "contractual",
    # 약어 / 두문자어
    "ebitda", "ebit", "roe", "roa", "roi",
    "cogs", "sga", "capex", "opex",
    "ppe", "nci",
    "ifrs", "gaap", "iasb",
    "dart",
    # 접두어/접미어 형태
    "noncurrent", "non-current",
    "reinsurance",
    "subgroup",
    "sublessor",
    "sublessee",
    # 한국 기업 관련
    "korea", "korean",
}

# ─────────────────────────────────────────────────────────────
# 데이터 구조
# ─────────────────────────────────────────────────────────────
@dataclass
class AIIssue:
    """2차 검토에서 발견된 단일 오류"""
    row_idx:     int
    field:       str          # "en_label" | "en2"
    error_type:  str
    description: str
    original:    str          # 오류 단어 또는 구문
    suggestion:  str = ""
    highlight:   list[str] = field(default_factory=list)
    source:      str = ""     # "spellcheck" | "claude"


# ─────────────────────────────────────────────────────────────
# ── ENGINE 1: pyspellchecker ─────────────────────────────────
# ─────────────────────────────────────────────────────────────

def _tokenize_label(label: str) -> list[str]:
    """레이블을 단어 토큰으로 분리. 괄호·콤마·기호 제거."""
    # 괄호 안 내용 제거 후 영문 단어만 추출
    clean = re.sub(r"\[.*?\]|\(.*?\)", " ", label)
    tokens = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", clean)
    return tokens


def _spell_check_label(
    spell: "SpellChecker",
    label: str,
    field: str,
    row_idx: int,
) -> list[AIIssue]:
    """단일 레이블의 철자 오류를 spellchecker로 검출."""
    issues: list[AIIssue] = []
    tokens = _tokenize_label(label)

    for token in tokens:
        token_lower = token.lower()
        # 화이트리스트 또는 숫자, 너무 짧은 토큰 건너뜀
        if (
            token_lower in FINANCIAL_WHITELIST
            or len(token) <= 2
            or token.isupper()           # 약어 (USD, IFRS 등)
            or re.match(r"^\d", token)
        ):
            continue

        # spellchecker 판정
        if token_lower in spell:
            continue                      # 올바른 단어

        candidates = spell.candidates(token_lower) or set()
        best       = spell.correction(token_lower)

        # 후보가 화이트리스트 단어이면 skip (예: amortisation)
        if best and best.lower() in FINANCIAL_WHITELIST:
            continue
        if candidates and all(c.lower() in FINANCIAL_WHITELIST for c in candidates):
            continue

        suggestion = best or ""
        desc = (
            f'철자 오류 가능성: "{token}"'
            + (f' → "{suggestion}" 로 수정 검토' if suggestion and suggestion != token_lower else "")
        )
        issues.append(AIIssue(
            row_idx    = row_idx,
            field      = field,
            error_type = "단순 오탈자",
            description= desc,
            original   = token,
            suggestion = suggestion,
            highlight  = [token],
            source     = "spellcheck",
        ))

    return issues


def review_with_spellcheck(rows: list[dict], verbose: bool = True) -> list[AIIssue]:
    """
    pyspellchecker 를 사용해 entity prefix 레이블의 철자 오류를 검출합니다.

    Parameters
    ----------
    rows : prepare_entity_rows() 결과
    verbose : 진행 상황 출력 여부
    """
    if not _SPELL_AVAILABLE:
        print(
            "  [spellcheck] pyspellchecker 가 설치되지 않았습니다.\n"
            "  설치: pip install pyspellchecker"
        )
        return []

    spell = SpellChecker(language="en")
    # 화이트리스트를 사전에 추가
    spell.word_frequency.load_words(list(FINANCIAL_WHITELIST))

    all_issues: list[AIIssue] = []
    for row in rows:
        en  = row.get("en_label", "")
        en2 = row.get("en2", "")
        lt  = row.get("label_title", "기본")

        # 기본 영문명 검사 (entity prefix 이므로 항상)
        if en:
            all_issues.extend(_spell_check_label(spell, en, "en_label", row["_row_idx"]))

        # 표현 영문명은 labelTitle이 기본이 아닌 경우만
        if en2 and lt != "기본":
            all_issues.extend(_spell_check_label(spell, en2, "en2", row["_row_idx"]))

    if verbose:
        print(f"  [spellcheck] {len(rows)}개 레이블 검사 → {len(all_issues)}건 발견")

    return all_issues


# ─────────────────────────────────────────────────────────────
# ── ENGINE 2: Claude API ─────────────────────────────────────
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
당신은 IFRS XBRL 재무제표 영문 레이블(Label) 품질 검토 전문가입니다.

검토 대상은 한국 상장기업이 DART XBRL 보고서에 사용하는 **확장 계정(entity prefix)**의
기본 영문명(en_label) 또는 표현 영문명(en2)입니다.

검토 원칙:
1. IFRS 택사노미는 영국식 영어를 사용합니다. amortisation, recognised, realised 등은 올바른 표기입니다.
2. en_label은 자연어(Natural Language Label) 형식이어야 합니다.
3. ko_label(한글명)과 en_label(영문명)의 의미가 일치해야 합니다.
4. 오류가 없으면 반드시 빈 배열 results:[] 를 반환합니다. 오류가 없는데 억지로 만들지 마십시오.

탐지 오류 유형 (중요도 순):
- "단순 오탈자"    : 명백한 철자 오류 (finanical, recievable, liabilites 등)
- "부적절한 표현"  : 비표준 표현 ("money income" → "monetary income")
- "IFRS 용어 불일치": IFRS 표준 용어와 다른 표현
- "한영 불일치"    : ko_label과 en_label의 의미가 다름

응답은 반드시 아래 JSON 형식만 출력하십시오. 추가 설명 없이 JSON만:
{"results":[{"idx":<0-based>,"field":"en_label"|"en2","error_type":"<유형>","description":"<설명>","original":"<오류단어/구문>","suggestion":"<수정제안>"}]}\
"""


def _call_claude(user_message: str, api_key: str) -> str:
    """Claude API 단일 호출."""
    headers = {
        "Content-Type":      "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key

    payload = json.dumps({
        "model":      MODEL,
        "max_tokens": MAX_TOKENS,
        "system":     SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": user_message}],
    }).encode("utf-8")

    req = urllib.request.Request(API_URL, data=payload, headers=headers, method="POST")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["content"][0]["text"]
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                wait = RETRY_DELAY * attempt * 2
                print(f"  [claude] Rate limit → {wait:.0f}s 대기 ({attempt}/{MAX_RETRIES})")
                time.sleep(wait)
            elif e.code >= 500:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"API {e.code}: {err_text[:300]}") from e
        except Exception as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"API 호출 실패: {exc}") from exc

    raise RuntimeError("Claude API 최대 재시도 초과")


def _parse_claude_response(text: str, chunk: list[dict]) -> list[AIIssue]:
    """Claude 응답 JSON → AIIssue 리스트."""
    clean = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return []

    issues: list[AIIssue] = []
    for item in data.get("results", []):
        idx = item.get("idx")
        if idx is None or not (0 <= idx < len(chunk)):
            continue

        original   = str(item.get("original", ""))
        suggestion = str(item.get("suggestion", ""))
        field_name = str(item.get("field", "en_label"))
        desc       = str(item.get("description", ""))
        if suggestion:
            desc = f'{desc} — 수정 제안: "{suggestion}"'

        highlight = [original] if original and len(original.split()) <= 4 else []

        issues.append(AIIssue(
            row_idx     = chunk[idx]["_row_idx"],
            field       = field_name,
            error_type  = str(item.get("error_type", "부적절한 표현")),
            description = desc,
            original    = original,
            suggestion  = suggestion,
            highlight   = highlight,
            source      = "claude",
        ))
    return issues


def review_with_claude(
    rows:       list[dict],
    api_key:    str = "",
    batch_size: int = BATCH_SIZE,
    verbose:    bool = True,
) -> list[AIIssue]:
    """
    Claude API를 사용해 entity prefix 레이블을 문맥 기반으로 정밀 검토합니다.

    Parameters
    ----------
    rows       : prepare_entity_rows() 결과
    api_key    : Anthropic API 키 (없으면 환경변수 ANTHROPIC_API_KEY)
    batch_size : 배치당 레이블 수
    verbose    : 진행 상황 출력 여부
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    # 미기재 플레이스홀더는 이미 1차에서 처리됨 → 건너뜀
    PLACEHOLDER_RE = re.compile(
        r"^(item|title)([-_]\d+)?(\s*\[.*\])?\s*$", re.IGNORECASE
    )
    valid = [
        r for r in rows
        if r.get("en_label", "").strip()
        and not PLACEHOLDER_RE.match(r.get("en_label", "").strip())
    ]

    if not valid:
        return []

    total_batches = (len(valid) + batch_size - 1) // batch_size
    if verbose:
        print(f"  [claude] {len(valid)}개 레이블 × {total_batches}배치 검토 중…")

    all_issues: list[AIIssue] = []

    for bi, start in enumerate(range(0, len(valid), batch_size), 1):
        chunk = valid[start : start + batch_size]
        api_payload = [
            {
                "idx":         i,
                "en_label":    r.get("en_label", ""),
                "ko_label":    r.get("ko_label", ""),
                "en2":         r.get("en2", ""),
                "ko2":         r.get("ko2", ""),
                "label_title": r.get("label_title", "기본"),
            }
            for i, r in enumerate(chunk)
        ]

        prompt = (
            "아래 XBRL 확장 계정 영문 레이블들을 검토하고 "
            "오류가 있는 항목만 JSON으로 반환하세요.\n\n"
            + json.dumps(api_payload, ensure_ascii=False, indent=2)
        )

        try:
            response   = _call_claude(prompt, api_key=key)
            new_issues = _parse_claude_response(response, chunk)
            all_issues.extend(new_issues)
            if verbose:
                print(f"    배치 {bi}/{total_batches}: {len(chunk)}건 → {len(new_issues)}건 발견")
        except RuntimeError as e:
            print(f"  [claude] 배치 {bi} 실패: {e}")

        if bi < total_batches:
            time.sleep(0.3)   # rate limit 예방

    if verbose:
        print(f"  [claude] 총 {len(all_issues)}건 추가 발견")

    return all_issues


# ─────────────────────────────────────────────────────────────
# ── 통합 진입점 ──────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────

def review_labels(
    rows:       list[dict],
    engine:     str  = "claude",   # "spellcheck" | "claude" | "both"
    api_key:    str  = "",
    batch_size: int  = BATCH_SIZE,
    verbose:    bool = True,
) -> list[AIIssue]:
    """
    2차 검토 통합 인터페이스.

    Parameters
    ----------
    rows       : prepare_entity_rows() 결과
    engine     : "spellcheck" | "claude" | "both"
    api_key    : Claude API 키
    batch_size : Claude API 배치 크기
    verbose    : 진행 출력 여부
    """
    issues: list[AIIssue] = []

    if engine in ("spellcheck", "both"):
        issues.extend(review_with_spellcheck(rows, verbose=verbose))

    if engine in ("claude", "both"):
        issues.extend(review_with_claude(rows, api_key=api_key,
                                          batch_size=batch_size, verbose=verbose))

    # 중복 제거: 같은 row_idx + field + original 조합
    seen: set[tuple] = set()
    deduped: list[AIIssue] = []
    for iss in issues:
        key = (iss.row_idx, iss.field, iss.original.lower())
        if key not in seen:
            seen.add(key)
            deduped.append(iss)

    return deduped


# ─────────────────────────────────────────────────────────────
# ── DataFrame 변환 헬퍼 ──────────────────────────────────────
# ─────────────────────────────────────────────────────────────

def prepare_entity_rows(df) -> list[dict]:
    """
    DataFrame에서 entity prefix 행만 추출 → review_labels 입력 형태.
    prefix 컬럼이 없으면 전체 행 대상.
    """
    has_prefix = "prefix" in df.columns
    has_extra  = all(c in df.columns for c in ["labelTitle", "ko", "en"])

    rows = []
    for idx, row in df.iterrows():
        pfx = str(row.get("prefix", "") or "").strip() if has_prefix else ""
        if has_prefix and not pfx.startswith("entity"):
            continue

        lt = str(row.get("labelTitle", "") or "").strip() if has_extra else "기본"
        rows.append({
            "_row_idx":    idx,
            "en_label":    str(row.get("en_label", "") or "").strip(),
            "ko_label":    str(row.get("ko_label", "") or "").strip(),
            "en2":         str(row.get("en",       "") or "").strip() if has_extra else "",
            "ko2":         str(row.get("ko",       "") or "").strip() if has_extra else "",
            "label_title": lt,
        })
    return rows


# ─────────────────────────────────────────────────────────────
# ── 단독 CLI ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────

def _standalone_main():
    import argparse, base64
    import pandas as pd

    def _decode_pwc(val):
        s = str(val or "").strip()
        if not s.startswith("pwcxbrl|"):
            return s
        b64 = re.sub(r"_x000D_.*", "", s[len("pwcxbrl|"):])
        try:
            raw = base64.b64decode(b64 + "==")
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    pass
        except Exception:
            pass
        return s

    p = argparse.ArgumentParser(description="XBRL AI 레이블 품질 검토 (단독 실행)")
    p.add_argument("input",
                   help="xlsx/xlsm 파일 경로")
    p.add_argument("--engine",
                   choices=["spellcheck", "claude", "both"],
                   default="claude",
                   help="검토 엔진 (기본: claude)")
    p.add_argument("--api-key",
                   default="",
                   help="Anthropic API 키 (미지정 시 ANTHROPIC_API_KEY 환경변수 사용)")
    p.add_argument("--batch-size",
                   type=int, default=BATCH_SIZE,
                   help=f"Claude API 배치 크기 (기본: {BATCH_SIZE})")
    p.add_argument("--pwc-encoded",
                   action="store_true",
                   help="PwC xlsm base64 레이블 디코딩")
    args = p.parse_args()

    SHEET_CANDIDATES = ["XBRLMPMaster", "연결", "별도", "Sheet1", "Data", "재무제표"]
    xl    = pd.ExcelFile(args.input, engine="openpyxl")
    sheet = next((s for s in SHEET_CANDIDATES if s in xl.sheet_names), xl.sheet_names[0])
    df    = pd.read_excel(args.input, sheet_name=sheet, engine="openpyxl")

    pwc = args.pwc_encoded or args.input.endswith(".xlsm")
    for col in ["ko_label", "en_label", "ko", "en"]:
        if col in df.columns:
            df[col] = df[col].apply(_decode_pwc) if pwc else df[col].fillna("").astype(str).str.strip()

    rows   = prepare_entity_rows(df)
    issues = review_labels(rows, engine=args.engine, api_key=args.api_key,
                            batch_size=args.batch_size)

    if issues:
        print(f"\n총 {len(issues)}건 발견:")
        for iss in issues:
            src = f"[{iss.source}]" if iss.source else ""
            print(f"  {src}[{iss.error_type}] row={iss.row_idx}  {iss.field}")
            print(f"    원문   : {iss.original!r}")
            print(f"    설명   : {iss.description}")
    else:
        print("이상 없음")


if __name__ == "__main__":
    _standalone_main()

"""element_validator.py — XBRL 계정명(element name) 오류 검증기.

입력된 XBRL 요소 식별자를 4단계 심각도로 분류하여 오류를 탐지한다.

Level 1 — CRITICAL : 플레이스홀더·미완성 계정명
Level 2 — HIGH     : CamelCase / snake_case / ALL-CAPS (자연어 미처리)
Level 3 — MEDIUM   : IFRS 표준 요소 재정의 / 비특정 포괄 계정명 / Axis·Member 구조 오용
Level 4 — LOW      : 오탈자 의심 (optional)
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Data structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ElementError:
    level:      int
    code:       str
    title:      str
    items:      list[str]
    message:    str
    suggestion: str
    optional:   bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

PLACEHOLDER_KEYWORDS: frozenset[str] = frozenset({
    "item", "title", "element", "name", "label",
    "field", "value", "data", "text", "entry",
})

ALLOWED_ACRONYMS: frozenset[str] = frozenset({
    "IFRS", "GAAP", "EBITDA", "EBIT", "ROE", "ROA", "EPS",
    "PER", "PBR", "FCF", "CAPEX", "OPEX", "SGA", "RND",
})

XBRL_STRUCTURAL_SUFFIXES: tuple[str, ...] = (
    "_Abstract", "_Member", "_Axis", "_Domain", "_Table", "_LineItems",
)

# IFRS-full 및 DART 표준 택소노미 주요 요소 (240개+)
IFRS_STANDARD_ELEMENTS: frozenset[str] = frozenset({
    # ── Statement of Financial Position — Assets ─────────────────────────
    "Assets",
    "CurrentAssets",
    "NoncurrentAssets",
    "CashAndCashEquivalents",
    "CurrentTaxAssets",
    "NoncurrentCurrentTaxAssets",
    "TradeAndOtherCurrentReceivables",
    "TradeAndOtherNoncurrentReceivables",
    "CurrentInventories",
    "Inventories",
    "OtherCurrentFinancialAssets",
    "OtherNoncurrentFinancialAssets",
    "OtherCurrentAssets",
    "OtherNoncurrentAssets",
    "PropertyPlantAndEquipment",
    "RightOfUseAssets",
    "InvestmentProperty",
    "Goodwill",
    "IntangibleAssetsOtherThanGoodwill",
    "DeferredTaxAssets",
    "FinancialAssets",
    "CurrentFinancialAssets",
    "NoncurrentFinancialAssets",
    "BiologicalAssets",
    "NoncurrentAssetsOrDisposalGroupsClassifiedAsHeldForSale",
    "InvestmentsAccountedForUsingEquityMethod",
    "InvestmentsInSubsidiariesAssociatesAndJointVentures",
    "DerivativeFinancialAssets",
    "CurrentDerivativeFinancialAssets",
    "NoncurrentDerivativeFinancialAssets",
    "FinancialAssetsAtFairValueThroughProfitOrLoss",
    "FinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
    "FinancialAssetsAtAmortisedCost",
    "CurrentPortionOfLongtermBorrowings",
    "ShorttermBorrowings",
    # ── Statement of Financial Position — Liabilities ───────────────────
    "Liabilities",
    "CurrentLiabilities",
    "NoncurrentLiabilities",
    "TradeAndOtherCurrentPayables",
    "TradeAndOtherNoncurrentPayables",
    "CurrentBorrowings",
    "NoncurrentBorrowings",
    "Borrowings",
    "CurrentLeaseLiabilities",
    "NoncurrentLeaseLiabilities",
    "LeaseLiabilities",
    "CurrentTaxLiabilities",
    "NoncurrentCurrentTaxLiabilities",
    "DeferredTaxLiabilities",
    "CurrentProvisions",
    "NoncurrentProvisions",
    "Provisions",
    "OtherCurrentFinancialLiabilities",
    "OtherNoncurrentFinancialLiabilities",
    "OtherCurrentLiabilities",
    "OtherNoncurrentLiabilities",
    "DerivativeFinancialLiabilities",
    "CurrentDerivativeFinancialLiabilities",
    "NoncurrentDerivativeFinancialLiabilities",
    "FinancialLiabilitiesAtFairValueThroughProfitOrLoss",
    "FinancialGuaranteeContracts",
    "LiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale",
    "ContingentLiabilities",
    # ── Statement of Financial Position — Equity ────────────────────────
    "Equity",
    "EquityAttributableToOwnersOfParent",
    "NoncontrollingInterests",
    "IssuedCapital",
    "SharePremium",
    "RetainedEarnings",
    "OtherReserves",
    "TreasuryShares",
    "OtherEquityInterest",
    "ReservesWithinEquityForEquityComponents",
    "AccumulatedOtherComprehensiveIncome",
    "CapitalRedemptionReserve",
    "MiscellaneousOtherReserves",
    "RevaluationSurplus",
    # ── Income Statement ─────────────────────────────────────────────────
    "Revenue",
    "CostOfSales",
    "GrossProfit",
    "OtherIncome",
    "DistributionCosts",
    "AdministrativeExpense",
    "OtherExpense",
    "OtherOperatingIncomeExpense",
    "ProfitLossFromOperatingActivities",
    "FinanceIncome",
    "FinanceCosts",
    "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
    "OtherFinanceIncomeCost",
    "ProfitLossBeforeTax",
    "IncomeTaxExpenseContinuingOperations",
    "ProfitLossFromContinuingOperations",
    "ProfitLossFromDiscontinuedOperations",
    "ProfitLoss",
    "ProfitLossAttributableToOwnersOfParent",
    "ProfitLossAttributableToNoncontrollingInterests",
    "BasicEarningsLossPerShare",
    "DilutedEarningsLossPerShare",
    "WeightedAverageShares",
    "DilutedWeightedAverageShares",
    # ── OCI ──────────────────────────────────────────────────────────────
    "OtherComprehensiveIncome",
    "OtherComprehensiveIncomeThatWillNotBeReclassifiedToProfitOrLossNetOfTax",
    "OtherComprehensiveIncomeThatWillBeReclassifiedToProfitOrLossNetOfTax",
    "GainsLossesOnRemeasurementsOfDefinedBenefitPlans",
    "GainsLossesOnRevaluationPropertyPlantEquipment",
    "GainsLossesArisingFromTranslatingFinancialStatementsOfForeignOperationsNetOfTax",
    "GainsLossesOnCashFlowHedgesNetOfTax",
    "GainsLossesOnFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncome",
    "ComprehensiveIncome",
    "ComprehensiveIncomeAttributableToOwnersOfParent",
    "ComprehensiveIncomeAttributableToNoncontrollingInterests",
    # ── Cash Flow Statement ──────────────────────────────────────────────
    "CashFlowsFromUsedInOperatingActivities",
    "CashFlowsFromUsedInInvestingActivities",
    "CashFlowsFromUsedInFinancingActivities",
    "IncreaseDecreaseInCashAndCashEquivalents",
    "CashAndCashEquivalentsAtEndOfPeriod",
    "CashAndCashEquivalentsAtBeginningOfPeriod",
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents",
    "PurchaseOfPropertyPlantAndEquipment",
    "ProceedsFromDisposalOfPropertyPlantAndEquipment",
    "AcquisitionOfSubsidiariesNetOfCashAcquired",
    "PurchaseOfIntangibleAssets",
    "ProceedsFromDisposalOfIntangibleAssets",
    "PurchaseOfInvestmentProperty",
    "ProceedsFromDisposalOfInvestmentProperty",
    "PurchaseOfFinancialInstruments",
    "ProceedsFromSalesOfFinancialInstruments",
    "ProceedsFromBorrowings",
    "RepaymentsOfBorrowings",
    "PaymentsOfLeaseLiabilities",
    "DividendsPaid",
    "DividendsPaidToNoncontrollingInterests",
    "ProceedsFromIssuingShares",
    "PaymentsForRepurchaseOfShares",
    "AdjustmentsForDepreciationAndAmortisationExpense",
    "AdjustmentsForImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
    "AdjustmentsForProvisions",
    "AdjustmentsForFinanceCosts",
    "AdjustmentsForCurrentTaxExpense",
    "AdjustmentsForDeferredTaxExpense",
    "AdjustmentsForIncreaseDecreaseInTradeAccountReceivable",
    "AdjustmentsForIncreaseDecreaseInInventories",
    "AdjustmentsForIncreaseDecreaseInTradeAccountPayable",
    "InterestPaidClassifiedAsOperatingActivities",
    "InterestReceivedClassifiedAsOperatingActivities",
    "DividendsReceivedClassifiedAsOperatingActivities",
    "IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
    # ── Supplementary / Notes ────────────────────────────────────────────
    "DepreciationAndAmortisationExpense",
    "DepreciationExpense",
    "AmortisationExpense",
    "ImpairmentLossRecognisedInProfitOrLoss",
    "ReverseImpairmentLossRecognisedInProfitOrLoss",
    "GainLossOnDisposalOfNoncurrentAssets",
    "ShareBasedPaymentExpense",
    "EmployeeBenefitsExpense",
    "WagesAndSalaries",
    "RetirementBenefitExpense",
    "ResearchAndDevelopmentExpense",
    "OperatingLeaseExpense",
    "CapitalisedDevelopmentCosts",
    "InterestExpense",
    "InterestIncome",
    "DividendIncome",
    "IncomeTaxExpense",
    "DeferredTaxExpense",
    "CurrentTaxExpense",
    "DisclosureOfSignificantAccountingPoliciesExplanatory",
    "DisclosureOfChangesInAccountingPoliciesExplanatory",
    "DisclosureOfPropertyPlantAndEquipmentExplanatory",
    "DisclosureOfIntangibleAssetsExplanatory",
    "DisclosureOfGoodwillExplanatory",
    "DisclosureOfInvestmentPropertyExplanatory",
    "DisclosureOfLeasesExplanatory",
    "DisclosureOfFinancialInstrumentsExplanatory",
    "DisclosureOfBorrowingsExplanatory",
    "DisclosureOfProvisionsExplanatory",
    "DisclosureOfContingentLiabilitiesExplanatory",
    "DisclosureOfRelatedPartyExplanatory",
    "DisclosureOfShareCapitalReservesAndOtherEquityInterestExplanatory",
    "DisclosureOfEarningsPerShareExplanatory",
    "DisclosureOfIncomeTaxExplanatory",
    "DisclosureOfSegmentInformationExplanatory",
    "DisclosureOfSubsidiariesExplanatory",
    "DisclosureOfAssociatesExplanatory",
    "DisclosureOfJointVenturesExplanatory",
    "DisclosureOfCommitmentsExplanatory",
    "DisclosureOfEventsAfterReportingPeriodExplanatory",
    "DisclosureOfBasisOfPreparationOfFinancialStatementsExplanatory",
})

# Level 4 — TYPO 탐지 기준 단어 목록 (올바른 철자)
FINANCIAL_TERMS: list[str] = [
    # A
    "Accumulated", "Acquisition", "Acquisitions", "Administrative",
    "Adjustments", "Allowance", "Amortisation", "Amortization",
    "Assets", "Associates", "Attributable",
    # B
    "Balance", "Benefit", "Benefits", "Borrowings", "Business",
    # C
    "Capital", "Cash", "Classification", "Comprehensive",
    "Consolidated", "Contributions", "Costs", "Current",
    # D
    "Deferred", "Depreciation", "Derivative", "Diluted",
    "Discontinued", "Disposal", "Distributions", "Dividends",
    # E
    "Earnings", "Employees", "Equity", "Equivalents", "Expense",
    "Expenses",
    # F
    "Financial", "Financing", "Foreign", "Forward",
    # G
    "Goodwill", "Gross", "Guarantee", "Guarantees",
    # I
    "Impairment", "Income", "Increase", "Intangible",
    "Interest", "Inventories", "Investments",
    # L
    "Lease", "Liabilities", "Loss", "Losses",
    # M
    "Measurement",
    # N
    "Noncurrent", "Noncontrolling",
    # O
    "Operating", "Operations", "Outflows",
    # P
    "Payment", "Payables", "Period", "Plant", "Premium",
    "Profit", "Property", "Provision", "Provisions",
    # R
    "Receivables", "Recognised", "Recognized", "Related",
    "Research", "Retained", "Revenue",
    # S
    "Salaries", "Securities", "Separate", "Settlement",
    "Shares", "Statement", "Subsidiary", "Subsidiaries",
    # T
    "Terminal", "Trade", "Treasury",
    # V
    "Valuation",
    # W
    "Wages",
]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(
    r"^(?:" + "|".join(re.escape(k) for k in PLACEHOLDER_KEYWORDS) + r")"
    r"(?:[-_]?\d+)?(?:\s*\[.*\])?\s*$",
    re.IGNORECASE,
)

_NEW_PREFIX_RE = re.compile(r"^New[\s_]|^New[A-Z]")

_GENERIC_RE = re.compile(r"^(Others?|기타\d*)$", re.IGNORECASE)


def _parse_input(text: str) -> list[str]:
    """Split input by newline or comma; strip whitespace; remove empty."""
    parts = re.split(r"[\n,]+", text)
    return [p.strip() for p in parts if p.strip()]


def _is_placeholder(name: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(name))


def _is_new_prefix(name: str) -> bool:
    return bool(_NEW_PREFIX_RE.match(name))


def _is_camel_case(name: str) -> bool:
    """True if name has no spaces/underscores and contains a lowercase→uppercase transition."""
    if " " in name or "_" in name:
        return False
    return bool(re.search(r"[a-z][A-Z]", name))


def _is_snake_case(name: str) -> bool:
    """True if name contains underscore but does NOT end with a structural XBRL suffix."""
    if "_" not in name:
        return False
    return not any(name.endswith(sfx) for sfx in XBRL_STRUCTURAL_SUFFIXES)


def _is_all_caps(name: str) -> bool:
    """True if name is all-uppercase alphabets and is not an allowed acronym."""
    alpha = re.sub(r"[^A-Za-z]", "", name)
    if not alpha or len(alpha) < 2:
        return False
    if alpha.upper() in ALLOWED_ACRONYMS:
        return False
    return alpha == alpha.upper()


def _is_generic_extension(name: str) -> bool:
    return bool(_GENERIC_RE.match(name))


def _split_pascal(name: str) -> list[str]:
    """Split a PascalCase/camelCase string into component words (≥ 3 chars)."""
    # Insert space before each uppercase sequence followed by lowercase
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", spaced)
    return [w for w in spaced.split() if len(w) >= 3]


def _find_typo_suggestion(word: str) -> str:
    """
    Return a suggestion string if 'word' looks like a misspelled financial term,
    using difflib similarity (≈ Levenshtein distance ≤ 2 for typical word lengths).
    Returns empty string if no typo detected.
    """
    if len(word) < 4:
        return ""
    # Use difflib; cutoff 0.82 ≈ at most 1–2 character edits for 6–15 char words
    matches = difflib.get_close_matches(word, FINANCIAL_TERMS, n=1, cutoff=0.82)
    if matches and matches[0] != word:
        return matches[0]
    return ""


def _detect_typo(name: str) -> str | None:
    """
    Return a human-readable suggestion if the name (or a component word) looks
    like a typo. Returns None if clean.
    """
    if "  " in name:
        return "이중 공백 제거 필요"
    words = _split_pascal(name) if (" " not in name and "_" not in name) else name.replace("_", " ").split()
    for word in words:
        suggestion = _find_typo_suggestion(word)
        if suggestion:
            return f'"{word}" → "{suggestion}"'
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def validate_element_names(text: str) -> list[ElementError]:
    """
    Validate XBRL element names (계정명).

    Args:
        text: Newline- or comma-separated element names.

    Returns:
        List of ElementError, grouped by level and code.
        Higher-priority (lower level number) errors take precedence;
        a name reported at one level will not appear in lower-level results.
    """
    names = _parse_input(text)
    if not names:
        return []

    reported: set[str] = set()
    errors: list[ElementError] = []

    def _collect(
        level: int,
        code: str,
        title: str,
        items: list[str],
        message: str,
        suggestion: str,
        optional: bool = False,
    ) -> None:
        if not items:
            return
        errors.append(ElementError(
            level=level, code=code, title=title,
            items=items, message=message, suggestion=suggestion, optional=optional,
        ))
        reported.update(items)

    # ── Level 1 — CRITICAL ──────────────────────────────────────────────

    ph = [n for n in names if n not in reported and _is_placeholder(n)]
    _collect(
        1, "PLACEHOLDER", "플레이스홀더 계정명",
        ph,
        "재무 개념을 담지 않는 임시 명칭(item, Title 등)이 사용되었습니다. "
        "공시에 제출될 경우 정정공시 사유가 됩니다.",
        "실제 회계 개념을 반영하는 XBRL 계정명으로 교체하세요. "
        "(예: item → TradeReceivables, Title → LongTermBorrowings)",
    )

    new_pfx = [n for n in names if n not in reported and _is_new_prefix(n)]
    _collect(
        1, "NEW-PREFIX", "'New' 접두사 계정명",
        new_pfx,
        '"New"로 시작하는 미완성 계정명입니다. 담당자가 임시로 작성한 것으로 간주됩니다.',
        '"New" 접두사 없이 구체적인 계정명을 입력하세요. '
        "(예: NewAssets → SpecificAssets, New Revenue → SalesRevenue)",
    )

    # ── Level 2 — HIGH ──────────────────────────────────────────────────

    camel = [n for n in names if n not in reported and _is_camel_case(n)]
    _collect(
        2, "CAMEL-CASE", "CamelCase / PascalCase 계정명",
        camel,
        "공시 레이블에 CamelCase/PascalCase 형식(내부 코드 식별자)이 그대로 사용되었습니다. "
        "자연어 형식이 아닙니다.",
        "단어 사이에 공백을 넣어 자연어 표현으로 수정하세요. "
        "(예: AccountsReceivable → Accounts Receivable)",
    )

    snake = [n for n in names if n not in reported and _is_snake_case(n)]
    _collect(
        2, "SNAKE-CASE", "snake_case 계정명",
        snake,
        "공시 레이블에 snake_case 형식이 사용되었습니다. 시스템 내부 코드 형식입니다.",
        "밑줄 대신 공백을 사용해 자연어 표현으로 수정하세요. "
        "(예: trade_payables → Trade Payables)",
    )

    allcaps = [n for n in names if n not in reported and _is_all_caps(n)]
    _collect(
        2, "ALL-CAPS", "전체 대문자 계정명",
        allcaps,
        f"전체 대문자(ALL CAPS) 계정명은 허용된 약어({', '.join(sorted(ALLOWED_ACRONYMS))}) 외에는 "
        "사용하지 않습니다.",
        "Title Case 또는 의미를 나타내는 영문 계정명으로 수정하세요. "
        "(예: INVENTORIES → Inventories)",
    )

    # ── Level 3 — MEDIUM ────────────────────────────────────────────────

    std_redef = [n for n in names if n not in reported and n in IFRS_STANDARD_ELEMENTS]
    _collect(
        3, "STD-REDEFINED", "IFRS 표준 요소 재정의",
        std_redef,
        "IFRS-full 또는 DART 표준 택소노미에 이미 존재하는 요소명을 확장 택소노미에 재정의하였습니다.",
        "표준 요소를 그대로 참조하거나, 확장이 필요한 경우 고유 접두사(회사명·업종 등)를 붙여 구분하세요.",
    )

    generic = [n for n in names if n not in reported and _is_generic_extension(n)]
    _collect(
        3, "GENERIC-EXTENSION", "비특정 포괄 계정명",
        generic,
        '"Other", "기타" 등 포괄적 계정명은 구체적인 회계 개념을 표현하지 못합니다.',
        "계정의 성격을 구체적으로 명시하세요. (예: Other → OtherOperatingExpense)",
    )

    # DIMENSION-MISUSE: Axis/Member 요소와 동일 기반 이름의 Fact 요소가 함께 존재
    name_set = set(names)
    dim_misuse: list[str] = []
    for n in names:
        if n in reported:
            continue
        if n.endswith("Axis") or n.endswith("Member"):
            base = re.sub(r"(Axis|Member)$", "", n)
            if base and base in name_set and base not in reported:
                dim_misuse.append(n)
    _collect(
        3, "DIMENSION-MISUSE", "Axis·Member 구조 오용 의심",
        dim_misuse,
        "입력 목록에 Axis/Member 요소와 동일 기반 이름의 Fact 요소가 함께 존재합니다. "
        "구조 오용 가능성이 있습니다.",
        "Axis·Member 요소와 Fact 요소의 계층 관계를 검토하세요. "
        "동일한 이름에 Axis/Member 접미사를 붙이는 것은 올바른 차원(Dimension) 설계가 아닐 수 있습니다.",
    )

    # ── Level 4 — LOW (optional) ─────────────────────────────────────────

    typo_items: list[tuple[str, str]] = []
    for n in names:
        if n in reported:
            continue
        suggestion = _detect_typo(n)
        if suggestion:
            typo_items.append((n, suggestion))

    if typo_items:
        suggestions = "; ".join(f"{n}: {s}" for n, s in typo_items)
        errors.append(ElementError(
            level=4,
            code="TYPO",
            title="오탈자 의심",
            items=[n for n, _ in typo_items],
            message="계정명에 오탈자로 의심되는 단어가 포함되어 있습니다. (difflib 유사도 기반 탐지)",
            suggestion=suggestions,
            optional=True,
        ))

    return errors

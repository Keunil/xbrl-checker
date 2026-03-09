"""
app.py — XBRL 영문명 오탈자 검토 웹 앱 (Streamlit)
"""

import io
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from checker import run_check_bytes

# ──────────────────────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="XBRL 영문명 검토",
    page_icon="🔍",
    layout="centered",
)

# ──────────────────────────────────────────────────────────────
# 스타일
# ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* 헤더 여백 줄이기 */
    .block-container { padding-top: 2rem; }

    /* 결과 카드 */
    .result-card {
        background: #f8f9fa;
        border-left: 4px solid #1f77b4;
        border-radius: 6px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
    }
    .result-card.warn {
        border-left-color: #ff7f0e;
    }
    .result-card.ok {
        border-left-color: #2ca02c;
    }

    /* 오류 배지 */
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-right: 4px;
    }
    .badge-red    { background:#ffe0e0; color:#c00; }
    .badge-orange { background:#fff3e0; color:#c65f00; }
    .badge-yellow { background:#fffde7; color:#a07000; }
    .badge-gray   { background:#f0f0f0; color:#555; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# 타이틀
# ──────────────────────────────────────────────────────────────
st.title("🔍 XBRL 영문명 오탈자 검토")
st.caption("금감원 DART XBRL 재무제표 작성 가이드(2026.01) 기반 | 규칙 기반 자동 검사")

st.divider()

# ──────────────────────────────────────────────────────────────
# 입력 폼
# ──────────────────────────────────────────────────────────────
with st.form("check_form"):
    col_left, col_right = st.columns([2, 1])

    with col_left:
        uploaded = st.file_uploader(
            "XBRL 파일 업로드",
            type=["xlsm", "xlsx"],
            help="스마트XBRL에서 내보낸 .xlsm 또는 .xlsx 파일을 업로드하세요.",
        )
        company = st.text_input(
            "회사명",
            placeholder="예: 주한화, LG화학, 사조씨푸드",
            help="결과 파일명에 사용됩니다.",
        )

    with col_right:
        btype = st.radio(
            "재무제표 구분",
            options=["별도", "연결"],
            index=0,
        )
        pwc_encoded = st.checkbox(
            "PwC 인코딩 적용",
            value=False,
            help=(
                "PwC 스마트XBRL 도구로 작성된 파일은 레이블이 Base64로 인코딩되어 있습니다. "
                "해당 파일인 경우 체크하세요."
            ),
        )

    submitted = st.form_submit_button(
        "🔎 검사 시작",
        use_container_width=True,
        type="primary",
    )

# ──────────────────────────────────────────────────────────────
# 처리
# ──────────────────────────────────────────────────────────────
if submitted:
    # ── 입력 검증 ──────────────────────────────────────────────
    errors = []
    if not uploaded:
        errors.append("파일을 업로드해 주세요.")
    if not company.strip():
        errors.append("회사명을 입력해 주세요.")

    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    company_clean = company.strip()

    # ── 처리 ──────────────────────────────────────────────────
    with st.spinner("검사 중입니다… 잠시 기다려 주세요."):
        t0 = time.time()
        try:
            file_bytes = uploaded.read()
            excel_bytes, stats = run_check_bytes(
                file_bytes   = file_bytes,
                filename     = uploaded.name,
                company      = company_clean,
                btype        = btype,
                pwc_encoded  = pwc_encoded,
            )
            elapsed = time.time() - t0
        except Exception as exc:
            st.error(f"검사 중 오류가 발생했습니다:\n\n```\n{exc}\n```")
            st.stop()

    # ── 결과 표시 ──────────────────────────────────────────────
    st.success(f"✅ 검사 완료 ({elapsed:.1f}초)")
    st.divider()

    total      = stats["total_rows"]
    n_issues   = stats["issue_count"]
    n_missing  = stats["n_missing"]
    n_viol     = stats["n_violation"]
    n_typo     = stats["n_typo"]

    # 요약 카드
    card_cls = "ok" if n_issues == 0 else ("warn" if n_issues < 20 else "result-card")
    st.markdown(f"""
<div class="result-card {card_cls}">
    <b>📊 검사 결과 요약</b><br><br>
    전체 행: <b>{total:,}행</b> &nbsp;|&nbsp; 이슈 항목: <b>{n_issues}건</b><br><br>
    <span class="badge badge-red">영문명 미기재 {n_missing}건</span>
    <span class="badge badge-orange">확장 원칙 위배 {n_viol}건</span>
    <span class="badge badge-yellow">오탈자 {n_typo}건</span>
</div>
""", unsafe_allow_html=True)

    # 다운로드 버튼
    st.markdown("&nbsp;")
    timestamp     = datetime.now().strftime("%Y%m%d_%H%M")
    output_name   = f"{company_clean}_{btype}_오탈자검사_{timestamp}.xlsx"

    st.download_button(
        label        = "⬇️  결과 다운로드 (.xlsx)",
        data         = excel_bytes,
        file_name    = output_name,
        mime         = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width = True,
        type         = "primary",
    )

    # 상세 안내
    with st.expander("결과 파일 컬럼 안내", expanded=False):
        st.markdown("""
| 컬럼 | 설명 |
|---|---|
| **표현속성** | 기본 / 별칭 등 레이블 유형 |
| **한글명** | 확장 계정 기본 한글명 |
| **영문명** | 확장 계정 기본 영문명 (노란/빨강 강조) |
| **표현 한글명** | 해당 표현에서의 한글명 |
| **표현 영문명** | 해당 표현에서의 영문명 |
| **오류유형** | 영문명 미기재 / XBRL 확장 원칙 위배 / 단순 오탈자 |
| **오류내용** | 구체적인 오류 설명 및 수정 제안 |

> **노란색** 셀: 오탈자 또는 원칙 위배 &nbsp;|&nbsp; **빨간색** 셀: 영문명 미기재
        """)

# ──────────────────────────────────────────────────────────────
# 푸터
# ──────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "금감원 DART XBRL 재무제표 작성 가이드(2026.01) 기반 규칙 검사 | "
    "결과는 참고용이며 최종 판단은 담당자가 직접 확인하시기 바랍니다."
)

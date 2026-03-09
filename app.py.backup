"""
app.py — XBRL 영문명 오탈자 검토 웹 앱 (Streamlit)
"""

import io
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from openpyxl import load_workbook

from checker import run_check_bytes, run_master_check_bytes, run_ai_review

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
# 탭 설정
# ──────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📋 일반 검사", "📊 마스터 파일 검사"])

with tab1:
    st.markdown("### 📤 일반 XBRL 파일 검사")
    st.markdown("스마트XBRL에서 내보낸 .xlsm 또는 .xlsx 파일을 업로드하여 검사합니다.")
    
    # ──────────────────────────────────────────────────────────────
    # 파일 검증 함수
    # ──────────────────────────────────────────────────────────────
    def validate_and_extract_metadata(file_bytes):
        """
        업로드된 파일에서 필수 시트를 검증하고 메타데이터를 추출합니다.
        
        Returns:
            tuple: (is_valid, error_message, company_name, finance_type)
                   - is_valid: 파일이 유효한지 여부
                   - error_message: 유효하지 않으면 에러 메시지
                   - company_name: 회사명 (Sources.A1)
                   - finance_type: 별도 or 연결 (Sources.B3)
        """
        try:
            wb = load_workbook(file_bytes)
            sheet_names = wb.sheetnames
            
            # 필수 시트 확인
            required_sheets = {"Sources", "XBRLMPMaster", "XBRLTGMaster"}
            missing_sheets = required_sheets - set(sheet_names)
            
            if missing_sheets:
                return False, "스마트XBRL 파일을 업로드해주세요", None, None
            
            # Sources 시트에서 회사명과 별도/연결 추출
            sources = wb["Sources"]
            
            # 회사명: Sources.A1 (1행 1열)
            company_name = sources["A1"].value
            if not company_name:
                company_name = ""
            else:
                company_name = str(company_name).strip()
            
            # 별도/연결: Sources.B3 (3행 2열)
            finance_type_raw = sources["B3"].value
            if finance_type_raw:
                finance_type_raw = str(finance_type_raw).strip()
                # "별도", "연결" 또는 다른 형식 처리
                if "연결" in finance_type_raw:
                    finance_type = "연결"
                elif "별도" in finance_type_raw:
                    finance_type = "별도"
                else:
                    finance_type = "별도"  # 기본값
            else:
                finance_type = "별도"
            
            return True, None, company_name, finance_type
            
        except Exception as e:
            return False, f"파일 읽기 중 오류가 발생했습니다: {str(e)}", None, None


    # 파일 검증 및 메타데이터 추출
    company_extracted = None
    finance_type_extracted = None
    file_validation_error = None

    if uploaded:
        file_bytes_check = uploaded.read()
        uploaded.seek(0)  # 파일 포인터 초기화
        
        is_valid, error_msg, company_name, finance_type = validate_and_extract_metadata(file_bytes_check)
        
        if not is_valid:
            st.error(f"❌ {error_msg}")
            uploaded = None
            st.stop()
        else:
            company_extracted = company_name
            finance_type_extracted = finance_type
            st.success(f"✅ 파일 검증 완료 | 회사명: **{company_name}** | 구분: **{finance_type}**")

    # 일반 검사 폼
    with st.form("check_form"):
        col_left, col_right = st.columns([2, 1])

        with col_left:
            company = st.text_input(
                "회사명",
                value=company_extracted or "",
                placeholder="예: 주한화, LG화학, 사조씨푸드",
                help="파일에서 자동 추출되었습니다.",
            )

        with col_right:
            btype = st.radio(
                "재무제표 구분",
                options=["별도", "연결"],
                index=0 if finance_type_extracted == "별도" or finance_type_extracted is None else 1,
                help="파일에서 자동 추출되었습니다.",
            )

        # AI 검토 옵션
        st.markdown("---")
        col_ai_left, col_ai_right = st.columns([3, 1])
        
        with col_ai_left:
            ai_review = st.checkbox(
                "🤖 AI 2차 검토 적용",
                value=False,
                help="Claude API를 사용하여 추가적인 오류를 검토합니다. API Key가 필요합니다.",
            )
            
            if ai_review:
                api_key = st.text_input(
                    "Claude API Key",
                    type="password",
                    placeholder="sk-ant-api03-...",
                    help="Anthropic Claude API 키를 입력하세요.",
                )
            else:
                api_key = ""

        with col_ai_right:
            st.markdown("&nbsp;")

        submitted = st.form_submit_button(
            "🔎 검사 시작",
            use_container_width=True,
            type="primary",
        )

with tab2:
    st.markdown("### 📊 마스터 파일 검사")
    st.markdown("XBRL 마스터 파일(.xlsx)을 업로드하여 모든 항목을 일괄 검사합니다.")
    
    # 마스터 파일 검사 폼
    with st.form("master_form"):
        master_uploaded = st.file_uploader(
            "마스터 파일 업로드",
            type=["xlsx"],
            help="XBRL 마스터 파일(.xlsx)을 업로드하세요.",
        )
        
        master_submitted = st.form_submit_button(
            "🔎 마스터 검사 시작",
            use_container_width=True,
            type="primary",
        )

# ──────────────────────────────────────────────────────────────
# 마스터 파일 검사 처리
# ──────────────────────────────────────────────────────────────
if master_submitted:
    # ── 입력 검증 ──────────────────────────────────────────────
    if not master_uploaded:
        st.error("마스터 파일을 업로드해 주세요.")
        st.stop()

    # ── 처리 ──────────────────────────────────────────────────
    with st.spinner("마스터 파일 검사 중입니다… 잠시 기다려 주세요."):
        t0 = time.time()
        try:
            file_bytes = master_uploaded.read()
            excel_bytes, stats = run_master_check_bytes(
                file_bytes = file_bytes,
                filename   = master_uploaded.name,
            )
            elapsed = time.time() - t0
        except Exception as exc:
            st.error(f"마스터 파일 검사 중 오류가 발생했습니다:\n\n```\n{exc}\n```")
            st.stop()

    # ── 결과 표시 ──────────────────────────────────────────────
    st.success(f"✅ 마스터 파일 검사 완료 ({elapsed:.1f}초)")
    st.divider()

    total = stats["total_rows"]
    n_issues = stats["issue_count"]
    n_missing = stats["n_missing"]
    n_viol = stats["n_violation"]
    n_typo = stats["n_typo"]

    # 요약 카드
    card_cls = "ok" if n_issues == 0 else ("warn" if n_issues < 100 else "result-card")
    st.markdown(f"""
<div class="result-card {card_cls}">
    <b>📊 마스터 파일 검사 결과 요약</b><br><br>
    전체 행: <b>{total:,}행</b> &nbsp;|&nbsp; 이슈 항목: <b>{n_issues}건</b><br><br>
    <span class="badge badge-red">영문명 미기재 {n_missing}건</span>
    <span class="badge badge-orange">확장 원칙 위배 {n_viol}건</span>
    <span class="badge badge-yellow">오탈자 {n_typo}건</span>
</div>
""", unsafe_allow_html=True)

    # 다운로드 버튼
    st.markdown("&nbsp;")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_name = f"마스터파일_오탈자검사_{timestamp}.xlsx"

    st.download_button(
        label="⬇️ 마스터 검사 결과 다운로드 (.xlsx)",
        data=excel_bytes,
        file_name=output_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
    )

# ──────────────────────────────────────────────────────────────
# 일반 파일 검사 처리
# ──────────────────────────────────────────────────────────────
# 입력 폼
# ──────────────────────────────────────────────────────────────
st.markdown("### 📤 파일 및 옵션 설정")

uploaded = st.file_uploader(
    "XBRL 파일 업로드",
    type=["xlsm", "xlsx"],
    help="스마트XBRL에서 내보낸 .xlsm 또는 .xlsx 파일을 업로드하세요.",
)

# 파일 검증 및 메타데이터 추출
company_extracted = None
finance_type_extracted = None
file_validation_error = None

if uploaded:
    file_bytes_check = uploaded.read()
    uploaded.seek(0)  # 파일 포인터 초기화
    
    is_valid, error_msg, company_name, finance_type = validate_and_extract_metadata(file_bytes_check)
    
    if not is_valid:
        st.error(f"❌ {error_msg}")
        uploaded = None
        st.stop()
    else:
        company_extracted = company_name
        finance_type_extracted = finance_type
        st.success(f"✅ 파일 검증 완료 | 회사명: **{company_name}** | 구분: **{finance_type}**")

with st.form("check_form"):
    col_left, col_right = st.columns([2, 1])

    with col_left:
        company = st.text_input(
            "회사명",
            value=company_extracted or "",
            placeholder="예: 주한화, LG화학, 사조씨푸드",
            help="파일에서 자동 추출되었습니다.",
        )

    with col_right:
        btype = st.radio(
            "재무제표 구분",
            options=["별도", "연결"],
            index=0 if finance_type_extracted == "별도" or finance_type_extracted is None else 1,
            help="파일에서 자동 추출되었습니다.",
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
        errors.append("회사명이 비어 있습니다. 파일에서 자동 추출되거나 직접 입력하세요.")

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
                pwc_encoded  = True,  # 항상 PwC 인코딩 적용
            )
            elapsed = time.time() - t0
        except Exception as exc:
            st.error(f"검사 중 오류가 발생했습니다:\n\n```\n{exc}\n```")
            st.stop()

    # AI 2차 검토 (선택적)
    if ai_review and api_key:
        with st.spinner("🤖 AI 2차 검토 중입니다… 잠시 기다려 주세요."):
            try:
                excel_bytes, ai_stats = run_ai_review(
                    excel_bytes=excel_bytes,
                    api_key=api_key,
                    company=company_clean,
                    btype=btype,
                )
                # AI 통계 병합
                stats["ai_issues_count"] = ai_stats["ai_issues_count"]
                stats["high_confidence"] = ai_stats["high_confidence"]
                stats["medium_confidence"] = ai_stats["medium_confidence"]
                stats["low_confidence"] = ai_stats["low_confidence"]
                st.success("✅ AI 2차 검토 완료")
            except Exception as exc:
                st.warning(f"AI 2차 검토 중 오류가 발생했습니다. 기본 검토 결과만 제공됩니다:\n\n```\n{exc}\n```")
    elif ai_review and not api_key:
        st.warning("API Key가 입력되지 않아 AI 2차 검토를 건너뜁니다.")

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
    summary_html = f"""
<div class="result-card {card_cls}">
    <b>📊 검사 결과 요약</b><br><br>
    전체 행: <b>{total:,}행</b> &nbsp;|&nbsp; 이슈 항목: <b>{n_issues}건</b><br><br>
    <span class="badge badge-red">영문명 미기재 {n_missing}건</span>
    <span class="badge badge-orange">확장 원칙 위배 {n_viol}건</span>
    <span class="badge badge-yellow">오탈자 {n_typo}건</span>
"""
    
    # AI 검토 결과 추가
    if ai_review and "ai_issues_count" in stats:
        ai_count = stats["ai_issues_count"]
        high_conf = stats["high_confidence"]
        med_conf = stats["medium_confidence"]
        low_conf = stats["low_confidence"]
        summary_html += f"""<br><br>
    <span class="badge" style="background-color: #6B73FF; color: white;">🤖 AI 검토 {ai_count}건</span>
    <small>(고신뢰: {high_conf} | 중신뢰: {med_conf} | 저신뢰: {low_conf})</small>
"""
    
    summary_html += "</div>"
    st.markdown(summary_html, unsafe_allow_html=True)

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
        base_info = """
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
        """
        
        if ai_review and "ai_issues_count" in stats:
            base_info += """

**🤖 AI 검토 시트 (AI_Review)**:
- 행 번호, 한글명, 영문명, AI 검토 결과, 신뢰도, 설명 컬럼 포함
- Claude AI가 추가로 발견한 잠재적 문제점들을 표시
- 신뢰도에 따라 검토 우선순위 결정 가능
            """
        
        st.markdown(base_info)

# ──────────────────────────────────────────────────────────────
# 푸터
# ──────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "금감원 DART XBRL 재무제표 작성 가이드(2026.01) 기반 규칙 검사 | "
    "결과는 참고용이며 최종 판단은 담당자가 직접 확인하시기 바랍니다."
)

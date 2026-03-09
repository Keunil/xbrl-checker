#!/bin/bash
echo "========================================"
echo " XBRL 영문명 오탈자 검토 앱 시작 중..."
echo "========================================"
echo ""

cd "$(dirname "$0")"

# Python 확인
if ! command -v python3 &>/dev/null; then
    echo "[오류] python3가 설치되지 않았습니다."
    echo "Python 3.9 이상을 https://python.org 에서 설치해 주세요."
    exit 1
fi

# 패키지 설치
echo "패키지 설치 확인 중..."
pip3 install -r requirements.txt -q

echo ""
echo "브라우저에서 http://localhost:8501 이 열립니다."
echo "종료하려면 Ctrl+C 를 누르세요."
echo ""

streamlit run app.py

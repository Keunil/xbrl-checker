@echo off
chcp 65001 >nul
echo ========================================
echo  XBRL 영문명 오탈자 검토 앱 시작 중...
echo ========================================
echo.

cd /d %~dp0

:: Python 설치 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되지 않았습니다.
    echo Python 3.9 이상을 https://python.org 에서 설치해 주세요.
    pause
    exit /b 1
)

:: 패키지 설치
echo 패키지 설치 확인 중...
pip install -r requirements.txt -q

echo.
echo 브라우저에서 http://localhost:8501 이 열립니다.
echo 종료하려면 이 창을 닫으세요.
echo.

streamlit run app.py

pause

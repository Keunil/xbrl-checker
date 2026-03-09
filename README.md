# XBRL 영문명 오탈자 검토 앱

금감원 DART XBRL 재무제표 작성 가이드(2026.01) 기반  
스마트XBRL(.xlsm/.xlsx) 파일의 확장 계정 영문명 오탈자를 자동 검사하는 웹 앱입니다.

## 기능

- **영문명 미기재** — 플레이스홀더(item, Title 등) 또는 한글 입력 탐지
- **XBRL 확장 원칙 위배** — CamelCase ID, FootNote, 주기 형식, 총액/순액 접미사 누락 등 9종
- **단순 오탈자** — liabilites→liabilities 등 20+ 패턴

---

## 로컬 실행

### 1. 환경 준비

```bash
# Python 3.9 이상 필요
python --version

# 가상환경 생성 (권장)
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 패키지 설치
pip install -r requirements.txt
```

### 2. 앱 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 자동 열림

---

## 배포 옵션

### A. Streamlit Community Cloud (무료, 권장)

> GitHub 리포지토리 연동 방식. 설정 5분이면 완료.

1. **GitHub 리포지토리 생성**
   ```bash
   git init
   git add .
   git commit -m "initial"
   git remote add origin https://github.com/<your-org>/xbrl-checker.git
   git push -u origin main
   ```

2. **[share.streamlit.io](https://share.streamlit.io) 접속** → Google/GitHub 계정으로 로그인

3. **New app** 클릭
   - Repository: `<your-org>/xbrl-checker`
   - Branch: `main`
   - Main file path: `app.py`

4. **Deploy** → 1~2분 후 공개 URL 발급  
   예시: `https://xbrl-checker-abcdef.streamlit.app`

> ⚠️ Community Cloud는 **Public 리포지토리** 무료.  
> Private 리포지토리는 팀 플랜($10/월) 필요.

---

### B. Docker (사내 서버 / 온프레미스)

```dockerfile
# Dockerfile (이미 포함됨)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
```

```bash
# 빌드 & 실행
docker build -t xbrl-checker .
docker run -p 8501:8501 xbrl-checker
```

접속: `http://<서버IP>:8501`

---

### C. 사내 PC에서 직접 실행 (비개발자용)

`run_app.bat` (Windows) 또는 `run_app.sh` (Mac/Linux)를 더블클릭하면  
브라우저가 자동 열립니다. (Python 설치 필요)

**Windows `run_app.bat`:**
```bat
@echo off
cd /d %~dp0
pip install -r requirements.txt -q
streamlit run app.py
pause
```

**Mac/Linux `run_app.sh`:**
```bash
#!/bin/bash
cd "$(dirname "$0")"
pip install -r requirements.txt -q
streamlit run app.py
```

---

## 파일 구조

```
xbrl_app/
├── app.py                  # Streamlit 웹 UI
├── checker/
│   ├── __init__.py
│   ├── core.py             # 검사 엔진 (규칙 기반)
│   └── ai_reviewer.py      # Claude API 2차 검토 (선택적)
├── requirements.txt
├── Dockerfile
├── .streamlit/
│   └── config.toml         # 테마 설정
└── README.md
```

---

## 결과 파일 컬럼

| 컬럼 | 설명 |
|---|---|
| 표현속성 | 기본 / 별칭 등 레이블 유형 |
| 한글명 | 확장 계정 기본 한글명 |
| **영문명** | 확장 계정 기본 영문명 (노란/빨강 강조) |
| 표현 한글명 | 해당 표현에서의 한글명 |
| **표현 영문명** | 해당 표현에서의 영문명 |
| **오류유형** | 영문명 미기재 / XBRL 확장 원칙 위배 / 단순 오탈자 |
| **오류내용** | 구체적인 오류 설명 및 수정 제안 |

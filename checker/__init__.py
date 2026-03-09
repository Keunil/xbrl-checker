from .core import run_check_bytes, run_check, detect_issues, Issue, RowResult

__all__ = ["run_check_bytes", "run_check", "detect_issues", "Issue", "RowResult"]
```

**Commit changes** 클릭

---

**② `checker/core.py` 생성**

파일명: `checker/core.py`  
내용: zip 파일 안 `xbrl_app/checker/core.py` 전체 내용 붙여넣기

---

**③ `checker/ai_reviewer.py` 생성**

파일명: `checker/ai_reviewer.py`  
내용: zip 파일 안 `xbrl_app/checker/ai_reviewer.py` 전체 내용 붙여넣기

---

### 완성 후 리포지토리 구조 확인

GitHub에서 이렇게 보여야 합니다:
```
리포지토리 루트/
  📄 app.py
  📄 requirements.txt
  📄 Dockerfile
  📄 README.md
  📁 checker/
       📄 __init__.py
       📄 core.py
       📄 ai_reviewer.py
  📁 .streamlit/
       📄 config.toml

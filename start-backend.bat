@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
echo ============================================
echo  AI 新闻聚合与问答系统 · 后端
echo  http://127.0.0.1:8000/docs
echo ============================================
python -m uvicorn main:app --reload --port 8000

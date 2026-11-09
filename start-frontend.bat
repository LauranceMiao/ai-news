@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
echo ============================================
echo  AI 新闻聚合与问答系统 · 前端
echo  http://localhost:5173  /  http://127.0.0.1:5173
echo ============================================
npm run dev -- --host 127.0.0.1

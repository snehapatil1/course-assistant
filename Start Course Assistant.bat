@echo off
setlocal
title Course Assistant
cd /d "%~dp0"
set GRADIO_ANALYTICS_ENABLED=False
if exist ".venv\Scripts\python.exe" goto check
where uv >nul 2>nul
if not errorlevel 1 (
  echo Preparing Course Assistant for the first time...
  uv venv --python 3.11 .venv >nul 2>nul
) else (
  python -m venv .venv >nul 2>nul
)
if not exist ".venv\Scripts\python.exe" goto setup_error
:check
".venv\Scripts\python.exe" -c "import gradio, pymupdf, pptx, chromadb, bm25s, openai, dotenv, langchain_text_splitters; assert gradio.__version__ == '6.29.1'" >nul 2>nul
if not errorlevel 1 goto launch
echo Installing the dashboard. This first step needs an internet connection...
where uv >nul 2>nul
if not errorlevel 1 (
  uv pip install --python ".venv\Scripts\python.exe" -r requirements-dashboard.txt >nul 2>nul
) else (
  ".venv\Scripts\python.exe" -m pip install -r requirements-dashboard.txt >nul 2>nul
)
if errorlevel 1 goto setup_error
:launch
echo Opening Course Assistant in your browser...
echo Keep this window open while you study. Close it to stop the dashboard.
".venv\Scripts\python.exe" -m src.app
if errorlevel 1 goto launch_error
exit /b 0
:setup_error
echo.
echo Setup could not finish. Check your internet connection and ensure Python 3.11 or newer is installed, then try again.
echo Ask your course team for help if setup still fails.
pause
exit /b 1
:launch_error
echo.
echo The dashboard stopped. Close any other Course Assistant window and try again.
pause
exit /b 1

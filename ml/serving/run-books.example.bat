@echo off
REM ---------------------------------------------------------------------------
REM  Start the retrieval service with EVERY book (tdd.md 3.2a "Many books").
REM
REM  Usage:  run-books.example.bat <INDEX_DIR> <python.exe> [BOOKS]
REM    INDEX_DIR   folder of book folders <id>\<id>.colqwen2.pt, as ml/indexing writes
REM    python.exe  a venv with torch, colpali-engine, fastapi and uvicorn
REM    BOOKS       optional comma-separated book ids, to load fewer books and less RAM
REM
REM  Example:
REM    run-books.example.bat C:\path\to\corpus\out C:\path\to\.venv\Scripts\python.exe
REM
REM  All books need about 7.5 GB of RAM (model ~5 GB + ~2.5 GB of page indexes).
REM  Committed as an example: no machine's paths are written into it.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

if "%~2"=="" (
  echo Usage: %~nx0 ^<INDEX_DIR^> ^<python.exe^> [BOOKS]
  exit /b 1
)
if not exist "%~1\" (
  echo INDEX_DIR not found: %~1
  exit /b 1
)
if not exist "%~2" (
  echo python.exe not found: %~2
  exit /b 1
)

set "INDEX_DIR=%~1"
set "BOOKS=%~3"
set "DTYPE=bfloat16"
"%~2" -m uvicorn app:app --host 127.0.0.1 --port 8100 --workers 1

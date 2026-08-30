@echo off
setlocal
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo === LACEN ETL DW + SE real ===
echo Uso: rodar_etl_dw.bat [--allow-local-fallback] [--skip-ml] [--skip-cievs]
echo.

"%PY%" -m etl.run_etl_dw %*
set ERR=%ERRORLEVEL%

echo.
echo Validacao: saida_pipeline\validacao_etl_dw_ultimo.txt
exit /b %ERR%

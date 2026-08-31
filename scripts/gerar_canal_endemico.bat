@echo off
REM Canal endêmico Bortman (P25/P50/P75) — LACEN / CIEVS
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo === Canal endemico Bortman ===
"%PY%" -m ml.canal_endemico_bortman --outdir saida_pipeline %*
if errorlevel 1 (
  echo [ERRO] Canal endemico falhou.
  pause
  exit /b 1
)

echo [OK] Saidas em saida_pipeline\canal_endemico.xlsx e canal_endemico_classificacao.csv
pause

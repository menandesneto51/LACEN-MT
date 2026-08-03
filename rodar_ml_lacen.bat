@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo === ML LACEN MT ===
"%PY%" -m ml.run_ml_pipeline --outdir saida_pipeline
if errorlevel 1 (
  echo [ERRO] Pipeline ML falhou.
  pause
  exit /b 1
)

echo === Parquet ===
"%PY%" exportar_parquet_saida.py --outdir saida_pipeline

echo [OK] Sinais preditivos atualizados.
pause

@echo off
cd /d "%~dp0"
title LACEN MT — Dashboard SES/CIEVS
echo.
echo === LACEN MT / SES-MT / CIEVS ===
echo Dados: saida_pipeline  ^|  Auth: veja scripts\deploy_ses.md
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Criando .venv e instalando dependencias...
  python -m venv .venv
  if exist "requirements.txt" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  ) else (
    ".venv\Scripts\python.exe" -m pip install -r requirements_lacen_integrado_total.txt
  )
)
if not defined LACEN_PORT set LACEN_PORT=8510
echo Iniciando Streamlit na porta %LACEN_PORT% ...
echo URL local: http://localhost:%LACEN_PORT%
".venv\Scripts\python.exe" -m streamlit run "lacen_dashboard_integrado_total.py" --server.port %LACEN_PORT% --server.headless true --browser.gatherUsageStats false

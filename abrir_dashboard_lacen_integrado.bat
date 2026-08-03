@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Criando .venv e instalando dependencias...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements_lacen_integrado_total.txt
)
".venv\Scripts\python.exe" -m streamlit run "lacen_dashboard_integrado_total.py"

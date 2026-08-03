@echo off
setlocal
cd /d "%~dp0"
echo Instalando dashboard LACEN V5...
if not exist "lacen_dashboard_integrado_total_v5_periodo_alertas.py" (
  echo ERRO: coloque lacen_dashboard_integrado_total_v5_periodo_alertas.py nesta pasta.
  pause
  exit /b 1
)
copy /Y "lacen_dashboard_integrado_total.py" "lacen_dashboard_integrado_total_backup_v5.py" >nul 2>nul
copy /Y "lacen_dashboard_integrado_total_v5_periodo_alertas.py" "lacen_dashboard_integrado_total.py" >nul
findstr /C:"v5.0-csv-analise-periodo-alertas-2026" "lacen_dashboard_integrado_total.py" >nul
if errorlevel 1 (
  echo ERRO: a instalacao falhou.
  pause
  exit /b 1
)
python -m pip install --upgrade streamlit plotly pandas numpy pyshp
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul
python -m streamlit run "lacen_dashboard_integrado_total.py"
pause

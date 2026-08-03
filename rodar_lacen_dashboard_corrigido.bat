@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo       LACEN-MT - DASHBOARD INTEGRADO TOTAL CORRIGIDO
echo ============================================================
echo.

if not exist "lacen_dashboard_integrado_total.py" (
    echo [ERRO] Arquivo lacen_dashboard_integrado_total.py nao encontrado nesta pasta.
    echo Copie este BAT e o dashboard corrigido para a pasta do projeto LACEN.
    pause
    exit /b 1
)

if not exist "saida_pipeline\integrated_weekly_surveillance.csv" (
    echo [ERRO] Nao encontrei saida_pipeline\integrated_weekly_surveillance.csv
    echo Rode primeiro a integracao final ou o sistema completo.
    pause
    exit /b 1
)

echo [INFO] Verificando se o dashboard contem a correcao do mapa...
findstr /C:"safe_marker_size" "lacen_dashboard_integrado_total.py" >nul
if errorlevel 1 (
    echo [ERRO] O arquivo lacen_dashboard_integrado_total.py ainda esta antigo.
    echo Substitua-o pela versao corrigida baixada.
    pause
    exit /b 1
)

echo [OK] Correcao encontrada.

echo.
echo [INFO] Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul

echo.
echo [INFO] Abrindo dashboard...
python -m streamlit run "lacen_dashboard_integrado_total.py"

pause

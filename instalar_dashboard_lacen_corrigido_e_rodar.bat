@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

echo ============================================================
echo   INSTALAR DASHBOARD LACEN CORRIGIDO E RODAR STREAMLIT
echo ============================================================
echo.

REM Este BAT deve ficar na pasta:
REM C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN

cd /d "%~dp0"
set "PROJ=%CD%"
set "DASH_DEST=%PROJ%\lacen_dashboard_integrado_total.py"
set "DOWNLOADS=%USERPROFILE%\Downloads"

echo Pasta atual:
echo %PROJ%
echo.

set "SRC="

REM 1) Procura primeiro na pasta do projeto
if exist "%PROJ%\lacen_dashboard_integrado_total_v2_corrigido_mapa.py" (
    set "SRC=%PROJ%\lacen_dashboard_integrado_total_v2_corrigido_mapa.py"
    goto FOUND
)

if exist "%PROJ%\lacen_dashboard_integrado_total_corrigido.py" (
    set "SRC=%PROJ%\lacen_dashboard_integrado_total_corrigido.py"
    goto FOUND
)

REM 2) Procura na pasta Downloads com o nome exato
if exist "%DOWNLOADS%\lacen_dashboard_integrado_total_v2_corrigido_mapa.py" (
    set "SRC=%DOWNLOADS%\lacen_dashboard_integrado_total_v2_corrigido_mapa.py"
    goto FOUND
)

if exist "%DOWNLOADS%\lacen_dashboard_integrado_total_corrigido.py" (
    set "SRC=%DOWNLOADS%\lacen_dashboard_integrado_total_corrigido.py"
    goto FOUND
)

REM 3) Procura versões baixadas com sufixos: (1), (2), etc.
for %%F in ("%DOWNLOADS%\lacen_dashboard_integrado_total_v2_corrigido_mapa*.py") do (
    if exist "%%~fF" (
        set "SRC=%%~fF"
        goto FOUND
    )
)

for %%F in ("%DOWNLOADS%\lacen_dashboard_integrado_total_corrigido*.py") do (
    if exist "%%~fF" (
        set "SRC=%%~fF"
        goto FOUND
    )
)

echo [ERRO] Nao encontrei o dashboard corrigido.
echo.
echo Baixe novamente o arquivo:
echo lacen_dashboard_integrado_total_v2_corrigido_mapa.py
echo.
echo Depois coloque ele em uma destas pastas:
echo %PROJ%
echo ou
echo %DOWNLOADS%
echo.
pause
exit /b 1

:FOUND
echo [OK] Dashboard corrigido encontrado:
echo %SRC%
echo.

REM Verifica se o arquivo fonte contem a funcao de correcao
findstr /C:"safe_marker_size" "%SRC%" >nul
if errorlevel 1 (
    echo [ERRO] O arquivo encontrado nao contem safe_marker_size.
    echo Ele provavelmente nao e a versao corrigida.
    echo Fonte encontrada:
    echo %SRC%
    pause
    exit /b 1
)

REM Backup do antigo
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
if exist "%DASH_DEST%" (
    echo [INFO] Fazendo backup do dashboard antigo...
    copy /Y "%DASH_DEST%" "%PROJ%\lacen_dashboard_integrado_total_backup_%STAMP%.py" >nul
    echo [OK] Backup criado:
    echo lacen_dashboard_integrado_total_backup_%STAMP%.py
    echo.
)

REM Substitui o arquivo principal
echo [INFO] Instalando dashboard corrigido como lacen_dashboard_integrado_total.py...
copy /Y "%SRC%" "%DASH_DEST%" >nul
if errorlevel 1 (
    echo [ERRO] Falha ao copiar o arquivo corrigido.
    pause
    exit /b 1
)

REM Verifica destino
findstr /C:"safe_marker_size" "%DASH_DEST%" >nul
if errorlevel 1 (
    echo [ERRO] A copia foi feita, mas o arquivo final ainda parece antigo.
    pause
    exit /b 1
)

echo [OK] Dashboard corrigido instalado.
echo.

REM Verifica CSV final
if not exist "%PROJ%\saida_pipeline\integrated_weekly_surveillance.csv" (
    echo [ALERTA] Nao encontrei:
    echo saida_pipeline\integrated_weekly_surveillance.csv
    echo.
    echo O dashboard foi instalado, mas talvez seja necessario rodar a integracao final antes.
    echo.
    pause
)

REM Limpa cache
echo [INFO] Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul

echo.
echo [INFO] Abrindo dashboard corrigido...
python -m streamlit run "%DASH_DEST%"

pause
endlocal

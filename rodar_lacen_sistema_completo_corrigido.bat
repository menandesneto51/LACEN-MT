@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo          LACEN-MT - SISTEMA COMPLETO COM DASH CORRIGIDO
echo ============================================================
echo.

set "OUTDIR=saida_pipeline"
set "LOGDIR=logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "LOG=%LOGDIR%\lacen_sistema_completo_%STAMP%.log"

set "PIPELINE=lacen_analysis_pipeline_completo_corrigido.py"
if not exist "%PIPELINE%" if exist "lacen_analysis_pipeline_completo_corrigido(1).py" set "PIPELINE=lacen_analysis_pipeline_completo_corrigido(1).py"

set "BUILDER=lacen_builder_integrado_total.py"
if not exist "%BUILDER%" if exist "lacen_builder_integrado_total(18).py" set "BUILDER=lacen_builder_integrado_total(18).py"

set "FINAL=lacen_integracao_final_only.py"
if not exist "%FINAL%" if exist "lacen_integracao_final_only(2).py" set "FINAL=lacen_integracao_final_only(2).py"

set "DASH=lacen_dashboard_integrado_total.py"

set "RAW=LACEN 2010 a 2026.csv"
set "SINAN=SINAN 2010 a 2025.csv"
set "SIM=SIM 2010 a 2025.csv"
set "CNES_ESTAB=CNES_ESTABELECIMENTOS.csv"
set "CNES_LEITOS=CNES_LEITOS.csv"
set "CNES_EQUIP=CNES EQUIPAMENTOS .csv"
if not exist "%CNES_EQUIP%" if exist "CNES_EQUIPAMENTOS.csv" set "CNES_EQUIP=CNES_EQUIPAMENTOS.csv"
set "CNES_EQUIPES=CNES_EQUIPESATENCAOBASICA.csv"
set "GEO=geo_social.csv"
set "CLIMA=historico_clima_10_anos.csv"
set "MUN=Municipios MT lat long.csv"
set "PEA=Populacao_economicamente_ativa.csv"

:MENU
cls
echo ============================================================
echo          LACEN-MT - SISTEMA COMPLETO COM DASH CORRIGIDO
echo ============================================================
echo.
echo [1] Instalar/atualizar dependencias
echo [2] Rodar tudo: bases + integracao final + dashboard
echo [3] Rodar bases pesadas
echo [4] Rodar somente integracao final
echo [5] Abrir somente dashboard corrigido
echo [6] Verificar arquivos
echo [0] Sair
echo.
set /p OP=Escolha: 

if "%OP%"=="1" goto INSTALL
if "%OP%"=="2" goto FULL
if "%OP%"=="3" goto BASES
if "%OP%"=="4" goto FINAL
if "%OP%"=="5" goto DASH
if "%OP%"=="6" goto CHECK
if "%OP%"=="0" goto END
goto MENU

:INSTALL
python -m pip install --upgrade pip pandas numpy openpyxl pyarrow streamlit plotly scipy scikit-learn statsmodels
pause
goto MENU

:FULL
call :CHECK_DASH_FIX || goto FAIL
call :BASES_RUN || goto FAIL
call :FINAL_RUN || goto FAIL
call :DASH_RUN
goto MENU

:BASES
call :BASES_RUN || goto FAIL
pause
goto MENU

:FINAL
call :FINAL_RUN || goto FAIL
pause
goto MENU

:DASH
call :CHECK_DASH_FIX || goto FAIL
call :DASH_RUN
goto MENU

:CHECK
echo.
call :CHECK_ONE "%PIPELINE%"
call :CHECK_ONE "%BUILDER%"
call :CHECK_ONE "%FINAL%"
call :CHECK_ONE "%DASH%"
call :CHECK_ONE "%RAW%"
call :CHECK_ONE "%SINAN%"
call :CHECK_ONE "%SIM%"
call :CHECK_ONE "%CNES_ESTAB%"
call :CHECK_ONE "%CNES_LEITOS%"
call :CHECK_ONE "%CNES_EQUIP%"
call :CHECK_ONE "%CNES_EQUIPES%"
call :CHECK_ONE "%GEO%"
call :CHECK_ONE "%CLIMA%"
call :CHECK_ONE "%MUN%"
call :CHECK_ONE "%PEA%"
call :CHECK_ONE "%OUTDIR%\integrated_weekly_surveillance.csv"
pause
goto MENU

:BASES_RUN
echo [1/3] Pipeline LACEN/GAL...
python "%PIPELINE%" --inputs "%RAW%" --outdir "%OUTDIR%" --start-year 2010 --chunk-size 50000 --municipality-source residencia --log-level INFO >> "%LOG%" 2>&1
if errorlevel 1 exit /b 1

echo [2/3] Builder integrado...
python "%BUILDER%" ^
  --raw "%RAW%" ^
  --outdir "%OUTDIR%" ^
  --pipeline-script "%PIPELINE%" ^
  --geo-social "%GEO%" ^
  --climate "%CLIMA%" ^
  --municipios "%MUN%" ^
  --pea "%PEA%" ^
  --sim "%SIM%" ^
  --sinan "%SINAN%" ^
  --cnes-estab "%CNES_ESTAB%" ^
  --cnes-leitos "%CNES_LEITOS%" ^
  --cnes-equip "%CNES_EQUIP%" ^
  --cnes-equipes "%CNES_EQUIPES%" ^
  --chunk-size 10000 ^
  --municipality-source residencia >> "%LOG%" 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:FINAL_RUN
echo [3/3] Integracao final...
python "%FINAL%" --outdir "%OUTDIR%" >> "%LOG%" 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:DASH_RUN
echo Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul
python -m streamlit run "%DASH%"
exit /b 0

:CHECK_DASH_FIX
findstr /C:"safe_marker_size" "%DASH%" >nul
if errorlevel 1 (
    echo [ERRO] O dashboard ainda esta sem a correcao safe_marker_size.
    echo Substitua lacen_dashboard_integrado_total.py pela versao corrigida.
    exit /b 1
)
exit /b 0

:CHECK_ONE
if exist "%~1" (
    echo [OK]    %~1
) else (
    echo [FALTA] %~1
)
exit /b 0

:FAIL
echo.
echo [ERRO] Falha no processamento.
echo Consulte o log:
echo %LOG%
pause
goto MENU

:END
endlocal
exit /b 0

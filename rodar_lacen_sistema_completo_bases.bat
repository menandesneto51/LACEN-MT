@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM ============================================================
REM  SISTEMA COMPLETO LACEN-MT
REM  1) Constrói bases LACEN/GAL
REM  2) Integra SINAN, SIM, CNES, clima, população e geossocial
REM  3) Recalcula integração final
REM  4) Abre dashboard Streamlit
REM ============================================================

cd /d "%~dp0"
set "PROJECT_DIR=%CD%"
set "OUTDIR=saida_pipeline"
set "LOGDIR=logs"

REM ----------------------------
REM Arquivos principais
REM ----------------------------
set "RAW_LACEN=LACEN 2010 a 2026.csv"
set "SINAN=SINAN 2010 a 2025.csv"
set "SIM=SIM 2010 a 2025.csv"
set "CNES_ESTAB=CNES_ESTABELECIMENTOS.csv"
set "CNES_LEITOS=CNES_LEITOS.csv"
set "CNES_EQUIP=CNES EQUIPAMENTOS .csv"
set "CNES_EQUIP_ALT=CNES_EQUIPAMENTOS.csv"
set "CNES_EQUIPES=CNES_EQUIPESATENCAOBASICA.csv"
set "GEO_SOCIAL=geo_social.csv"
set "CLIMATE=historico_clima_10_anos.csv"
set "MUNICIPIOS=Municipios MT lat long.csv"
set "PEA=Populacao_economicamente_ativa.csv"

REM ----------------------------
REM Scripts
REM ----------------------------
set "PIPELINE_SCRIPT=lacen_analysis_pipeline_completo_corrigido.py"
set "PIPELINE_SCRIPT_ALT1=lacen_analysis_pipeline_completo_corrigido(1).py"
set "PIPELINE_SCRIPT_ALT2=lacen_analysis_pipeline.py"

set "BUILDER_SCRIPT=lacen_builder_integrado_total.py"
set "BUILDER_SCRIPT_ALT1=lacen_builder_integrado_total(18).py"

set "FINAL_SCRIPT=lacen_integracao_final_only.py"
set "FINAL_SCRIPT_ALT1=lacen_integracao_final_only(2).py"

set "DASH_SCRIPT=lacen_dashboard_integrado_total.py"
set "DASH_SCRIPT_ALT1=lacen_dashboard_integrado_total_corrigido.py"
set "DASH_SCRIPT_ALT2=lacen_dashboard_integrado_total(6).py"

REM ----------------------------
REM Parâmetros operacionais
REM ----------------------------
set "START_YEAR=2010"
set "PIPELINE_CHUNK_SIZE=50000"
set "BUILDER_CHUNK_SIZE=10000"
set "MUNICIPALITY_SOURCE=residencia"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUNSTAMP=%%i"
set "LOG=%LOGDIR%\lacen_sistema_completo_%RUNSTAMP%.log"

call :resolve_scripts
call :resolve_python

:MENU
cls
echo ============================================================
echo             SISTEMA COMPLETO LACEN-MT
echo ============================================================
echo Pasta do projeto:
echo %PROJECT_DIR%
echo.
echo Saida:
echo %PROJECT_DIR%\%OUTDIR%
echo.
echo Log desta sessao:
echo %PROJECT_DIR%\%LOG%
echo.
echo [1] Instalar/atualizar dependencias Python
echo [2] RODAR SISTEMA COMPLETO: bases + integracao + dashboard
echo [3] Construir bases pesadas: pipeline LACEN + builder integrado
echo [4] Refazer somente a integracao final
echo [5] Abrir somente o dashboard
echo [6] Verificar arquivos de entrada e saida
echo [7] Limpar cache do Streamlit
echo [8] Mostrar configuracao atual
echo [0] Sair
echo.
set /p OPCAO=Escolha uma opcao: 

if "%OPCAO%"=="1" goto INSTALL
if "%OPCAO%"=="2" goto FULL
if "%OPCAO%"=="3" goto BASES
if "%OPCAO%"=="4" goto FINAL_ONLY
if "%OPCAO%"=="5" goto DASH
if "%OPCAO%"=="6" goto CHECK_ALL
if "%OPCAO%"=="7" goto CLEAR_CACHE
if "%OPCAO%"=="8" goto SHOW_CONFIG
if "%OPCAO%"=="0" goto END

echo Opcao invalida.
pause
goto MENU

REM ============================================================
REM ROTINAS PRINCIPAIS
REM ============================================================

:INSTALL
echo.
echo [DEPENDENCIAS] Instalando/atualizando pacotes...
echo ===== %DATE% %TIME% - INSTALAR DEPENDENCIAS ===== >> "%LOG%"
%PYTHON% -m pip install --upgrade pip >> "%LOG%" 2>&1
if errorlevel 1 goto FAIL

%PYTHON% -m pip install --upgrade pandas numpy openpyxl pyarrow streamlit plotly scipy scikit-learn statsmodels >> "%LOG%" 2>&1
if errorlevel 1 goto FAIL

echo [OK] Dependencias instaladas/atualizadas.
pause
goto MENU

:FULL
echo.
echo [SISTEMA COMPLETO] Iniciando execucao completa.
echo Esta etapa pode demorar, pois reconstrói as bases pesadas.
echo.
call :CHECK_INPUTS
if errorlevel 1 goto FAIL_PAUSE

call :RUN_PIPELINE
if errorlevel 1 goto FAIL_PAUSE

call :RUN_BUILDER
if errorlevel 1 goto FAIL_PAUSE

call :RUN_FINAL
if errorlevel 1 goto FAIL_PAUSE

echo.
echo [OK] Sistema completo processado. Abrindo dashboard...
call :RUN_DASH
goto MENU

:BASES
echo.
echo [BASES] Construindo bases pesadas: pipeline LACEN + builder integrado.
call :CHECK_INPUTS
if errorlevel 1 goto FAIL_PAUSE

call :RUN_PIPELINE
if errorlevel 1 goto FAIL_PAUSE

call :RUN_BUILDER
if errorlevel 1 goto FAIL_PAUSE

echo.
echo [OK] Bases pesadas construidas em "%OUTDIR%".
pause
goto MENU

:FINAL_ONLY
echo.
echo [FINAL] Recalculando somente integracao final.
call :CHECK_FINAL_INPUTS
if errorlevel 1 goto FAIL_PAUSE

call :RUN_FINAL
if errorlevel 1 goto FAIL_PAUSE

echo.
echo [OK] Integracao final concluida.
pause
goto MENU

:DASH
echo.
echo [DASHBOARD] Abrindo painel Streamlit.
call :CHECK_DASH
if errorlevel 1 goto FAIL_PAUSE

call :RUN_DASH
goto MENU

:CHECK_ALL
echo.
call :CHECK_INPUTS
echo.
call :CHECK_FINAL_INPUTS
echo.
call :CHECK_DASH
echo.
echo [INFO] Verificando arquivos finais principais em "%OUTDIR%":
call :CHECK_FINAL_OUTPUT "integrated_weekly_surveillance.csv"
call :CHECK_FINAL_OUTPUT "integrated_alerts.csv"
call :CHECK_FINAL_OUTPUT "integrated_annual_summary.csv"
call :CHECK_FINAL_OUTPUT "integrated_target_municipio_summary.csv"
call :CHECK_FINAL_OUTPUT "forecast_integrated_statewide.csv"
call :CHECK_FINAL_OUTPUT "municipal_master.csv"
call :CHECK_FINAL_OUTPUT "populacao_municipio.csv"
call :CHECK_FINAL_OUTPUT "climate_weekly_municipio.csv"
call :CHECK_FINAL_OUTPUT "sinan_weekly_municipio.csv"
call :CHECK_FINAL_OUTPUT "sim_weekly_municipio.csv"
call :CHECK_FINAL_OUTPUT "cnes_capacity_municipio.csv"
echo.
pause
goto MENU

:CLEAR_CACHE
echo.
echo [CACHE] Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul
echo [OK] Cache limpo quando existente.
pause
goto MENU

:SHOW_CONFIG
echo.
echo ================= CONFIGURACAO ATUAL =================
echo Python:              %PYTHON%
echo Pipeline script:     %PIPELINE_SCRIPT%
echo Builder script:      %BUILDER_SCRIPT%
echo Integracao final:    %FINAL_SCRIPT%
echo Dashboard:           %DASH_SCRIPT%
echo Raw LACEN:           %RAW_LACEN%
echo SINAN:               %SINAN%
echo SIM:                 %SIM%
echo CNES estab.:         %CNES_ESTAB%
echo CNES leitos:         %CNES_LEITOS%
echo CNES equip.:         %CNES_EQUIP%
echo CNES equipes:        %CNES_EQUIPES%
echo Geo social:          %GEO_SOCIAL%
echo Clima:               %CLIMATE%
echo Municipios:          %MUNICIPIOS%
echo PEA:                 %PEA%
echo Saida:               %OUTDIR%
echo Ano inicial:         %START_YEAR%
echo Chunk pipeline:      %PIPELINE_CHUNK_SIZE%
echo Chunk builder:       %BUILDER_CHUNK_SIZE%
echo Fonte municipio:     %MUNICIPALITY_SOURCE%
echo Log:                 %LOG%
echo ======================================================
pause
goto MENU

REM ============================================================
REM EXECUCOES
REM ============================================================

:RUN_PIPELINE
echo.
echo [1/3] Pipeline geral LACEN/GAL
echo ===== %DATE% %TIME% - PIPELINE GERAL LACEN/GAL ===== >> "%LOG%"
echo Comando: %PYTHON% "%PIPELINE_SCRIPT%" --inputs "%RAW_LACEN%" --outdir "%OUTDIR%" --start-year %START_YEAR% --chunk-size %PIPELINE_CHUNK_SIZE% --municipality-source %MUNICIPALITY_SOURCE% --log-level INFO >> "%LOG%"

%PYTHON% "%PIPELINE_SCRIPT%" ^
  --inputs "%RAW_LACEN%" ^
  --outdir "%OUTDIR%" ^
  --start-year %START_YEAR% ^
  --chunk-size %PIPELINE_CHUNK_SIZE% ^
  --municipality-source %MUNICIPALITY_SOURCE% ^
  --log-level INFO >> "%LOG%" 2>&1

if errorlevel 1 (
    echo [ERRO] Falha no pipeline geral LACEN/GAL. Veja o log:
    echo %LOG%
    exit /b 1
)
echo [OK] Pipeline geral LACEN/GAL concluido.
exit /b 0

:RUN_BUILDER
echo.
echo [2/3] Builder integrado LACEN + SINAN + SIM + CNES + clima
echo ===== %DATE% %TIME% - BUILDER INTEGRADO TOTAL ===== >> "%LOG%"
echo Comando: %PYTHON% "%BUILDER_SCRIPT%" --raw "%RAW_LACEN%" --outdir "%OUTDIR%" --pipeline-script "%PIPELINE_SCRIPT%" ... >> "%LOG%"

%PYTHON% "%BUILDER_SCRIPT%" ^
  --raw "%RAW_LACEN%" ^
  --outdir "%OUTDIR%" ^
  --pipeline-script "%PIPELINE_SCRIPT%" ^
  --geo-social "%GEO_SOCIAL%" ^
  --climate "%CLIMATE%" ^
  --municipios "%MUNICIPIOS%" ^
  --pea "%PEA%" ^
  --sim "%SIM%" ^
  --sinan "%SINAN%" ^
  --cnes-estab "%CNES_ESTAB%" ^
  --cnes-leitos "%CNES_LEITOS%" ^
  --cnes-equip "%CNES_EQUIP%" ^
  --cnes-equipes "%CNES_EQUIPES%" ^
  --chunk-size %BUILDER_CHUNK_SIZE% ^
  --municipality-source %MUNICIPALITY_SOURCE% >> "%LOG%" 2>&1

if errorlevel 1 (
    echo [ERRO] Falha no builder integrado. Veja o log:
    echo %LOG%
    exit /b 1
)
echo [OK] Builder integrado concluido.
exit /b 0

:RUN_FINAL
echo.
echo [3/3] Integracao final
echo ===== %DATE% %TIME% - INTEGRACAO FINAL ===== >> "%LOG%"
%PYTHON% "%FINAL_SCRIPT%" --outdir "%OUTDIR%" >> "%LOG%" 2>&1

if errorlevel 1 (
    echo [ERRO] Falha na integracao final. Veja o log:
    echo %LOG%
    exit /b 1
)
echo [OK] Integracao final concluida.
exit /b 0

:RUN_DASH
echo.
echo Abrindo Streamlit...
echo Se o navegador nao abrir automaticamente, use o endereco mostrado pelo Streamlit.
echo.
%PYTHON% -m streamlit run "%DASH_SCRIPT%"
exit /b 0

REM ============================================================
REM VERIFICACOES
REM ============================================================

:CHECK_INPUTS
echo.
echo [CHECK] Verificando scripts e arquivos de entrada...
set "MISSING=0"

call :CHECK_FILE "%PIPELINE_SCRIPT%"
call :CHECK_FILE "%BUILDER_SCRIPT%"
call :CHECK_FILE "%FINAL_SCRIPT%"
call :CHECK_FILE "%DASH_SCRIPT%"
call :CHECK_FILE "%RAW_LACEN%"
call :CHECK_FILE "%SINAN%"
call :CHECK_FILE "%SIM%"
call :CHECK_FILE "%CNES_ESTAB%"
call :CHECK_FILE "%CNES_LEITOS%"
call :CHECK_FILE "%CNES_EQUIP%"
call :CHECK_FILE "%CNES_EQUIPES%"
call :CHECK_FILE "%GEO_SOCIAL%"
call :CHECK_FILE "%CLIMATE%"
call :CHECK_FILE "%MUNICIPIOS%"
call :CHECK_FILE "%PEA%"

if "%MISSING%"=="1" (
    echo.
    echo [ERRO] Existem arquivos ausentes. Coloque todos os arquivos na pasta:
    echo %PROJECT_DIR%
    exit /b 1
)

echo [OK] Arquivos de entrada encontrados.
exit /b 0

:CHECK_FINAL_INPUTS
echo.
echo [CHECK] Verificando arquivos minimos para integracao final...
set "MISSING=0"

call :CHECK_FILE "%FINAL_SCRIPT%"
call :CHECK_FILE "%OUTDIR%\positivity_by_target_epiweek_municipio.csv"
call :CHECK_FILE "%OUTDIR%\weekly_tests_by_target_municipio.csv"
call :CHECK_FILE "%OUTDIR%\weekly_alerts.csv"
call :CHECK_FILE "%OUTDIR%\municipal_master.csv"
call :CHECK_FILE "%OUTDIR%\populacao_municipio.csv"
call :CHECK_FILE "%OUTDIR%\climate_weekly_municipio.csv"
call :CHECK_FILE "%OUTDIR%\sinan_weekly_municipio.csv"
call :CHECK_FILE "%OUTDIR%\sim_weekly_municipio.csv"
call :CHECK_FILE "%OUTDIR%\cnes_capacity_municipio.csv"

if "%MISSING%"=="1" (
    echo.
    echo [ERRO] Faltam arquivos intermediarios. Rode a opcao [2] ou [3].
    exit /b 1
)

echo [OK] Arquivos minimos para integracao final encontrados.
exit /b 0

:CHECK_DASH
set "MISSING=0"
call :CHECK_FILE "%DASH_SCRIPT%"
call :CHECK_FILE "%OUTDIR%\integrated_weekly_surveillance.csv"
call :CHECK_FILE "%OUTDIR%\integrated_alerts.csv"
call :CHECK_FILE "%OUTDIR%\integrated_annual_summary.csv"
call :CHECK_FILE "%OUTDIR%\integrated_target_municipio_summary.csv"

if "%MISSING%"=="1" (
    echo.
    echo [ERRO] Faltam dashboard ou CSVs finais. Rode a opcao [2] ou [4].
    exit /b 1
)

echo [OK] Dashboard e CSVs finais encontrados.
exit /b 0

:CHECK_FILE
if not exist "%~1" (
    echo [FALTA] %~1
    set "MISSING=1"
) else (
    echo [OK]    %~1
)
exit /b 0

:CHECK_FINAL_OUTPUT
if exist "%OUTDIR%\%~1" (
    echo [OK]    %OUTDIR%\%~1
) else (
    echo [FALTA] %OUTDIR%\%~1
)
exit /b 0

REM ============================================================
REM RESOLUCOES
REM ============================================================

:resolve_scripts
if not exist "%PIPELINE_SCRIPT%" if exist "%PIPELINE_SCRIPT_ALT1%" set "PIPELINE_SCRIPT=%PIPELINE_SCRIPT_ALT1%"
if not exist "%PIPELINE_SCRIPT%" if exist "%PIPELINE_SCRIPT_ALT2%" set "PIPELINE_SCRIPT=%PIPELINE_SCRIPT_ALT2%"

if not exist "%BUILDER_SCRIPT%" if exist "%BUILDER_SCRIPT_ALT1%" set "BUILDER_SCRIPT=%BUILDER_SCRIPT_ALT1%"

if not exist "%FINAL_SCRIPT%" if exist "%FINAL_SCRIPT_ALT1%" set "FINAL_SCRIPT=%FINAL_SCRIPT_ALT1%"

if not exist "%DASH_SCRIPT%" if exist "%DASH_SCRIPT_ALT1%" set "DASH_SCRIPT=%DASH_SCRIPT_ALT1%"
if not exist "%DASH_SCRIPT%" if exist "%DASH_SCRIPT_ALT2%" set "DASH_SCRIPT=%DASH_SCRIPT_ALT2%"

if not exist "%CNES_EQUIP%" if exist "%CNES_EQUIP_ALT%" set "CNES_EQUIP=%CNES_EQUIP_ALT%"
exit /b 0

:resolve_python
set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERRO] Python nao encontrado. Instale Python 3 e marque "Add Python to PATH".
        pause
        exit /b 1
    )
    set "PYTHON=py -3"
)
exit /b 0

:FAIL
echo.
echo [ERRO] Ocorreu uma falha. Veja o log:
echo %LOG%
pause
goto MENU

:FAIL_PAUSE
echo.
echo [ERRO] Processo interrompido. Veja o log:
echo %LOG%
pause
goto MENU

:END
echo Saindo...
endlocal
exit /b 0

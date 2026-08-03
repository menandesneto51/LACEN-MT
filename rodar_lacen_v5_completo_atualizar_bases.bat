@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM  LACEN MT - V5 COMPLETO
REM  Mantem leitura por CSV e permite:
REM  - instalar/abrir dashboard V5
REM  - refazer integracao final
REM  - reconstruir bases pesadas
REM  - atualizar dados e abrir painel
REM ============================================================

set "OUTDIR=saida_pipeline"
set "LOGDIR=logs"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "LOG=%LOGDIR%\lacen_v5_completo_%STAMP%.log"

REM ----------------------------
REM Scripts
REM ----------------------------
set "DASH_V5=lacen_dashboard_integrado_total_v5_periodo_alertas.py"
set "DASH_MAIN=lacen_dashboard_integrado_total.py"

set "PIPELINE=lacen_analysis_pipeline_completo_corrigido.py"
if not exist "%PIPELINE%" if exist "lacen_analysis_pipeline_completo_corrigido(1).py" set "PIPELINE=lacen_analysis_pipeline_completo_corrigido(1).py"
if not exist "%PIPELINE%" if exist "lacen_analysis_pipeline.py" set "PIPELINE=lacen_analysis_pipeline.py"

set "BUILDER=lacen_builder_integrado_total.py"
if not exist "%BUILDER%" if exist "lacen_builder_integrado_total(18).py" set "BUILDER=lacen_builder_integrado_total(18).py"

set "FINAL=lacen_integracao_final_only.py"
if not exist "%FINAL%" if exist "lacen_integracao_final_only(2).py" set "FINAL=lacen_integracao_final_only(2).py"

REM ----------------------------
REM Bases de entrada
REM ----------------------------
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

REM ----------------------------
REM Parametros
REM ----------------------------
set "START_YEAR=2010"
set "PIPELINE_CHUNK=50000"
set "BUILDER_CHUNK=10000"
set "MUN_SOURCE=residencia"

:MENU
cls
echo ============================================================
echo             LACEN MT - V5 COMPLETO
echo ============================================================
echo Pasta atual:
cd
echo.
echo Log atual:
echo %LOG%
echo.
echo [1] Instalar ou atualizar dependencias
echo [2] Instalar dashboard V5 e abrir painel
echo [3] ATUALIZAR DADOS COMPLETOS: reconstruir bases + integracao final + painel
echo [4] Reconstruir bases pesadas: pipeline LACEN + builder integrado
echo [5] Refazer somente integracao final e abrir painel
echo [6] Refazer somente integracao final, sem abrir painel
echo [7] Abrir somente dashboard
echo [8] Verificar arquivos de entrada e saida
echo [9] Limpar cache do Streamlit
echo [0] Sair
echo.
set /p OP=Escolha uma opcao: 

if "%OP%"=="1" goto INSTALL
if "%OP%"=="2" goto INSTALL_DASH
if "%OP%"=="3" goto FULL_UPDATE
if "%OP%"=="4" goto HEAVY_BASES
if "%OP%"=="5" goto FINAL_AND_DASH
if "%OP%"=="6" goto FINAL_ONLY
if "%OP%"=="7" goto DASH_ONLY
if "%OP%"=="8" goto CHECK
if "%OP%"=="9" goto CLEAN_CACHE
if "%OP%"=="0" goto END
goto MENU

:INSTALL
echo.
echo Instalando/atualizando dependencias...
python -m pip install --upgrade pip
python -m pip install --upgrade pandas numpy openpyxl pyarrow streamlit plotly pyshp scipy scikit-learn statsmodels
pause
goto MENU

:INSTALL_DASH
call :COPY_DASH || goto FAIL
call :RUN_DASH
goto MENU

:FULL_UPDATE
call :COPY_DASH || goto FAIL
call :CHECK_INPUTS || goto FAIL
call :RUN_HEAVY_BASES || goto FAIL
call :RUN_FINAL || goto FAIL
call :RUN_DASH
goto MENU

:HEAVY_BASES
call :CHECK_INPUTS || goto FAIL
call :RUN_HEAVY_BASES || goto FAIL
echo.
echo OK: bases pesadas reconstruidas em %OUTDIR%.
echo Agora voce pode rodar a opcao [5] para integracao final + painel.
pause
goto MENU

:FINAL_AND_DASH
call :COPY_DASH || goto FAIL
call :CHECK_FINAL_INPUTS || goto FAIL
call :RUN_FINAL || goto FAIL
call :RUN_DASH
goto MENU

:FINAL_ONLY
call :CHECK_FINAL_INPUTS || goto FAIL
call :RUN_FINAL || goto FAIL
echo.
echo OK: integracao final concluida.
pause
goto MENU

:DASH_ONLY
call :COPY_DASH || goto FAIL
call :RUN_DASH
goto MENU

:CHECK
echo.
echo ===== Scripts =====
call :CHECK_ONE "%DASH_V5%"
call :CHECK_ONE "%DASH_MAIN%"
call :CHECK_ONE "%PIPELINE%"
call :CHECK_ONE "%BUILDER%"
call :CHECK_ONE "%FINAL%"

echo.
echo ===== Entradas brutas =====
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

echo.
echo ===== Saidas intermediarias para integracao final =====
call :CHECK_ONE "%OUTDIR%\positivity_by_target_epiweek_municipio.csv"
call :CHECK_ONE "%OUTDIR%\weekly_tests_by_target_municipio.csv"
call :CHECK_ONE "%OUTDIR%\weekly_alerts.csv"
call :CHECK_ONE "%OUTDIR%\municipal_master.csv"
call :CHECK_ONE "%OUTDIR%\populacao_municipio.csv"
call :CHECK_ONE "%OUTDIR%\climate_weekly_municipio.csv"
call :CHECK_ONE "%OUTDIR%\sinan_weekly_municipio.csv"
call :CHECK_ONE "%OUTDIR%\sim_weekly_municipio.csv"
call :CHECK_ONE "%OUTDIR%\cnes_capacity_municipio.csv"

echo.
echo ===== Saidas finais do dashboard =====
call :CHECK_ONE "%OUTDIR%\integrated_weekly_surveillance.csv"
call :CHECK_ONE "%OUTDIR%\integrated_alerts.csv"
call :CHECK_ONE "%OUTDIR%\integrated_annual_summary.csv"
call :CHECK_ONE "%OUTDIR%\integrated_target_municipio_summary.csv"
call :CHECK_ONE "%OUTDIR%\forecast_integrated_statewide.csv"
echo.
pause
goto MENU

:CLEAN_CACHE
echo.
echo Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul
echo OK.
pause
goto MENU

:COPY_DASH
if not exist "%DASH_V5%" (
  echo ERRO: nao encontrei %DASH_V5%.
  echo Coloque o arquivo V5 baixado nesta pasta.
  exit /b 1
)
findstr /C:"v5.0-csv-analise-periodo-alertas-2026" "%DASH_V5%" >nul
if errorlevel 1 (
  echo ERRO: o arquivo V5 encontrado nao parece ser a versao correta.
  exit /b 1
)
if exist "%DASH_MAIN%" (
  copy /Y "%DASH_MAIN%" "lacen_dashboard_integrado_total_backup_v5_%STAMP%.py" >nul
)
copy /Y "%DASH_V5%" "%DASH_MAIN%" >nul
findstr /C:"v5.0-csv-analise-periodo-alertas-2026" "%DASH_MAIN%" >nul
if errorlevel 1 (
  echo ERRO: falha ao instalar dashboard V5.
  exit /b 1
)
echo OK: dashboard V5 instalado como %DASH_MAIN%.
exit /b 0

:CHECK_INPUTS
set "MISS=0"
call :CHECK_ONE "%PIPELINE%"
call :CHECK_ONE "%BUILDER%"
call :CHECK_ONE "%FINAL%"
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
if "%MISS%"=="1" (
  echo.
  echo ERRO: existem arquivos de entrada ausentes.
  exit /b 1
)
exit /b 0

:CHECK_FINAL_INPUTS
set "MISS=0"
call :CHECK_ONE "%FINAL%"
call :CHECK_ONE "%OUTDIR%\positivity_by_target_epiweek_municipio.csv"
call :CHECK_ONE "%OUTDIR%\weekly_tests_by_target_municipio.csv"
call :CHECK_ONE "%OUTDIR%\weekly_alerts.csv"
call :CHECK_ONE "%OUTDIR%\municipal_master.csv"
call :CHECK_ONE "%OUTDIR%\populacao_municipio.csv"
call :CHECK_ONE "%OUTDIR%\climate_weekly_municipio.csv"
call :CHECK_ONE "%OUTDIR%\sinan_weekly_municipio.csv"
call :CHECK_ONE "%OUTDIR%\sim_weekly_municipio.csv"
call :CHECK_ONE "%OUTDIR%\cnes_capacity_municipio.csv"
if "%MISS%"=="1" (
  echo.
  echo ERRO: faltam arquivos intermediarios. Rode a opcao [3] ou [4].
  exit /b 1
)
exit /b 0

:CHECK_ONE
if exist "%~1" (
  echo [OK]    %~1
) else (
  echo [FALTA] %~1
  set "MISS=1"
)
exit /b 0

:RUN_HEAVY_BASES
echo.
echo [1/2] Rodando pipeline LACEN/GAL...
echo ===== %DATE% %TIME% - PIPELINE LACEN/GAL ===== >> "%LOG%"
echo Comando: python "%PIPELINE%" --inputs "%RAW%" --outdir "%OUTDIR%" >> "%LOG%"

python "%PIPELINE%" ^
  --inputs "%RAW%" ^
  --outdir "%OUTDIR%" ^
  --start-year %START_YEAR% ^
  --chunk-size %PIPELINE_CHUNK% ^
  --municipality-source %MUN_SOURCE% ^
  --log-level INFO >> "%LOG%" 2>&1

if errorlevel 1 (
  echo ERRO: falha no pipeline LACEN/GAL.
  echo Veja o log: %LOG%
  exit /b 1
)

echo.
echo [2/2] Rodando builder integrado...
echo ===== %DATE% %TIME% - BUILDER INTEGRADO ===== >> "%LOG%"

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
  --chunk-size %BUILDER_CHUNK% ^
  --municipality-source %MUN_SOURCE% >> "%LOG%" 2>&1

if errorlevel 1 (
  echo ERRO: falha no builder integrado.
  echo Veja o log: %LOG%
  exit /b 1
)

echo OK: bases pesadas reconstruidas.
exit /b 0

:RUN_FINAL
echo.
echo Rodando integracao final...
echo ===== %DATE% %TIME% - INTEGRACAO FINAL ===== >> "%LOG%"
python "%FINAL%" --outdir "%OUTDIR%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo ERRO: falha na integracao final.
  echo Veja o log: %LOG%
  exit /b 1
)
echo OK: integracao final concluida.
exit /b 0

:RUN_DASH
echo.
echo Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul
echo.
echo Abrindo painel...
python -m streamlit run "%DASH_MAIN%"
exit /b 0

:FAIL
echo.
echo ERRO no processamento.
echo Veja o log:
echo %LOG%
pause
goto MENU

:END
endlocal
exit /b 0

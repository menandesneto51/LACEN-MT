@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title LACEN MT - Sistema completo
color 0A

REM ================================================================
REM  LACEN MT - Sistema completo
REM  Coloque este arquivo .bat na mesma pasta dos scripts Python:
REM  C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN
REM ================================================================

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

set "OUTDIR=%PROJECT_DIR%saida_pipeline"
set "DASH_SCRIPT=lacen_dashboard_integrado_total.py"
set "FINAL_SCRIPT=lacen_integracao_final_only.py"

REM Aceita nomes com sufixo de download, caso ainda não tenham sido renomeados.
if not exist "%FINAL_SCRIPT%" (
    if exist "lacen_integracao_final_only(2).py" set "FINAL_SCRIPT=lacen_integracao_final_only(2).py"
)
if not exist "%DASH_SCRIPT%" (
    if exist "lacen_dashboard_integrado_total_corrigido.py" set "DASH_SCRIPT=lacen_dashboard_integrado_total_corrigido.py"
)

REM Localiza Python.
set "PY_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
    set "PY_CMD=py -3"
    where py >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [ERRO] Python nao encontrado no PATH.
        echo Instale o Python 3 e marque a opcao "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
)

:MENU
cls
echo ================================================================
echo              LACEN MT - SISTEMA COMPLETO
echo ================================================================
echo Pasta do projeto:
echo %PROJECT_DIR%
echo.
echo Pasta de saida:
echo %OUTDIR%
echo.
echo Script de integracao final: %FINAL_SCRIPT%
echo Script do dashboard:        %DASH_SCRIPT%
echo ================================================================
echo.
echo Escolha uma opcao:
echo.
echo [1] Instalar/atualizar dependencias
echo [2] Refazer integracao final e abrir dashboard  ^(recomendado^)
echo [3] Apenas abrir dashboard
echo [4] Verificar arquivos finais em saida_pipeline
echo [5] Limpar cache do Streamlit
echo [0] Sair
echo.
set /p OPCAO=Digite a opcao e pressione ENTER: 

if "%OPCAO%"=="1" goto DEPENDENCIAS
if "%OPCAO%"=="2" goto INTEGRACAO_E_DASH
if "%OPCAO%"=="3" goto DASHBOARD
if "%OPCAO%"=="4" goto VERIFICAR
if "%OPCAO%"=="5" goto LIMPAR_CACHE
if "%OPCAO%"=="0" goto SAIR

echo.
echo Opcao invalida.
pause
goto MENU

:DEPENDENCIAS
cls
echo ================================================================
echo Instalando/atualizando dependencias principais...
echo ================================================================
echo.
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install --upgrade streamlit pandas numpy plotly openpyxl pyarrow scipy statsmodels scikit-learn
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar dependencias.
    echo Tente executar este BAT como usuario normal, com internet ativa.
    echo.
    pause
    goto MENU
)
echo.
echo [OK] Dependencias instaladas/atualizadas.
pause
goto MENU

:INTEGRACAO_E_DASH
cls
echo ================================================================
echo Etapa 1/2 - Integracao final dos CSVs ja processados
echo ================================================================
echo.

if not exist "%FINAL_SCRIPT%" (
    echo [ERRO] Script de integracao final nao encontrado:
    echo %PROJECT_DIR%%FINAL_SCRIPT%
    echo.
    echo Verifique se o arquivo lacen_integracao_final_only.py esta na pasta do projeto.
    echo.
    pause
    goto MENU
)

if not exist "%OUTDIR%" (
    echo [ERRO] Pasta saida_pipeline nao encontrada:
    echo %OUTDIR%
    echo.
    echo A integracao final depende dos CSVs ja gerados pelas etapas anteriores.
    echo.
    pause
    goto MENU
)

%PY_CMD% "%FINAL_SCRIPT%" --outdir "%OUTDIR%"
if errorlevel 1 (
    echo.
    echo [ERRO] A integracao final falhou.
    echo Revise a mensagem acima. O dashboard nao sera aberto automaticamente.
    echo.
    pause
    goto MENU
)

echo.
echo [OK] Integracao final concluida.
echo.
echo ================================================================
echo Etapa 2/2 - Abrindo dashboard Streamlit
echo ================================================================
echo.
goto EXEC_DASH

:DASHBOARD
cls
echo ================================================================
echo Abrindo dashboard Streamlit
echo ================================================================
echo.
goto EXEC_DASH

:EXEC_DASH
if not exist "%DASH_SCRIPT%" (
    echo [ERRO] Dashboard nao encontrado:
    echo %PROJECT_DIR%%DASH_SCRIPT%
    echo.
    echo Copie o arquivo lacen_dashboard_integrado_total.py para a pasta do projeto.
    echo.
    pause
    goto MENU
)

if not exist "%OUTDIR%\integrated_weekly_surveillance.csv" (
    echo [AVISO] Nao encontrei integrated_weekly_surveillance.csv em saida_pipeline.
    echo O dashboard pode falhar se os CSVs finais ainda nao tiverem sido gerados.
    echo.
    set /p CONTINUAR=Deseja abrir mesmo assim? [S/N]: 
    if /I not "!CONTINUAR!"=="S" goto MENU
)

echo.
echo Abrindo em: http://localhost:8501
echo Para encerrar, pressione CTRL+C nesta janela.
echo.
%PY_CMD% -m streamlit run "%DASH_SCRIPT%" --server.fileWatcherType none --server.maxUploadSize 1024

echo.
echo O Streamlit foi encerrado.
pause
goto MENU

:VERIFICAR
cls
echo ================================================================
echo Verificacao dos arquivos finais em saida_pipeline
echo ================================================================
echo.

if not exist "%OUTDIR%" (
    echo [ERRO] Pasta saida_pipeline nao encontrada:
    echo %OUTDIR%
    echo.
    pause
    goto MENU
)

call :CHECKFILE "integrated_weekly_surveillance.csv"
call :CHECKFILE "integrated_alerts.csv"
call :CHECKFILE "integrated_annual_summary.csv"
call :CHECKFILE "integrated_target_municipio_summary.csv"
call :CHECKFILE "forecast_integrated_statewide.csv"
call :CHECKFILE "municipal_master.csv"
call :CHECKFILE "populacao_municipio.csv"
call :CHECKFILE "climate_weekly_municipio.csv"
call :CHECKFILE "sinan_weekly_municipio.csv"
call :CHECKFILE "sim_weekly_municipio.csv"
call :CHECKFILE "cnes_capacity_municipio.csv"

echo.
echo Lista completa da pasta saida_pipeline:
echo.
dir "%OUTDIR%" /b

echo.
pause
goto MENU

:CHECKFILE
if exist "%OUTDIR%\%~1" (
    echo [OK]      %~1
) else (
    echo [AUSENTE] %~1
)
exit /b 0

:LIMPAR_CACHE
cls
echo ================================================================
echo Limpando cache local do Streamlit
echo ================================================================
echo.
%PY_CMD% -m streamlit cache clear
if errorlevel 1 (
    echo.
    echo [AVISO] Nao foi possivel limpar o cache pelo comando do Streamlit.
    echo Isso nao impede o funcionamento do sistema.
) else (
    echo.
    echo [OK] Cache do Streamlit limpo.
)
echo.
pause
goto MENU

:SAIR
echo.
echo Encerrado.
exit /b 0

@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo       LACEN MT - DIAGNOSTICAR ERRO DO BUILDER
echo ============================================================
echo.

if not exist "logs" (
    echo [ERRO] Pasta logs nao encontrada.
    pause
    exit /b 1
)

echo [INFO] Localizando log mais recente...
for /f "delims=" %%F in ('powershell -NoProfile -Command "Get-ChildItem -Path 'logs' -Filter '*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"') do set "LOGFILE=%%F"

if "%LOGFILE%"=="" (
    echo [ERRO] Nenhum arquivo .log encontrado em logs.
    pause
    exit /b 1
)

echo [OK] Log encontrado:
echo %LOGFILE%
echo.

echo ============================================================
echo ULTIMAS 160 LINHAS DO LOG
echo ============================================================
powershell -NoProfile -Command "Get-Content '%LOGFILE%' -Tail 160"

echo.
echo ============================================================
echo LINHAS COM ERRO / TRACEBACK / VALUEERROR
echo ============================================================
powershell -NoProfile -Command "Select-String -Path '%LOGFILE%' -Pattern 'Traceback','Error','ERROR','ERRO','ValueError','KeyError','FileNotFoundError','UnicodeDecodeError','ParserError','MemoryError' -Context 2,4 | ForEach-Object { $_.ToString() }"

echo.
echo ============================================================
echo ARQUIVOS GERADOS EM saida_pipeline
echo ============================================================
if exist "saida_pipeline" (
    dir /b "saida_pipeline"
) else (
    echo Pasta saida_pipeline nao encontrada.
)

echo.
echo ============================================================
echo PROXIMO PASSO
echo ============================================================
echo Copie e cole aqui principalmente as linhas de TRACEBACK, ValueError ou KeyError acima.
echo.
pause

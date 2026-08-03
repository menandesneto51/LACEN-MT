@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   LACEN MT - INSTALAR DASHBOARD CORRIGIDO E RODAR
echo ============================================================
echo.
echo Pasta atual:
cd
echo.

if not exist "lacen_dashboard_integrado_total_v2_corrigido_mapa.py" goto FALTA_CORRIGIDO

echo Verificando arquivo corrigido...
findstr /C:"safe_marker_size" "lacen_dashboard_integrado_total_v2_corrigido_mapa.py" >nul
if errorlevel 1 goto CORRIGIDO_INVALIDO

if exist "lacen_dashboard_integrado_total.py" (
  echo Fazendo backup do dashboard antigo...
  copy /Y "lacen_dashboard_integrado_total.py" "lacen_dashboard_integrado_total_backup_erro_size.py" >nul
)

echo Instalando dashboard corrigido...
copy /Y "lacen_dashboard_integrado_total_v2_corrigido_mapa.py" "lacen_dashboard_integrado_total.py" >nul
if errorlevel 1 goto FALHA_COPIA

echo Conferindo arquivo final...
findstr /C:"safe_marker_size" "lacen_dashboard_integrado_total.py" >nul
if errorlevel 1 goto FINAL_INVALIDO

echo.
echo OK: dashboard corrigido instalado.
echo.
echo Limpando cache do Streamlit...
rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
rmdir /s /q "%TEMP%\streamlit" 2>nul

echo.
echo Abrindo dashboard...
python -m streamlit run "lacen_dashboard_integrado_total.py"
pause
exit /b 0

:FALTA_CORRIGIDO
echo.
echo ERRO: nao encontrei o arquivo:
echo lacen_dashboard_integrado_total_v2_corrigido_mapa.py
echo.
echo Coloque este arquivo na MESMA PASTA deste BAT e rode novamente.
pause
exit /b 1

:CORRIGIDO_INVALIDO
echo.
echo ERRO: o arquivo corrigido nao contem safe_marker_size.
echo Baixe novamente o dashboard corrigido.
pause
exit /b 1

:FALHA_COPIA
echo.
echo ERRO: falha ao copiar o dashboard corrigido.
pause
exit /b 1

:FINAL_INVALIDO
echo.
echo ERRO: o arquivo final ainda nao contem safe_marker_size.
pause
exit /b 1

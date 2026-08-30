@echo off
REM Gera parecer VE inteligente (Top 10 + Guia MS) e opcionalmente envia.
cd /d "%~dp0.."
python scripts\gerar_relatorio_ve.py %*
if errorlevel 1 pause

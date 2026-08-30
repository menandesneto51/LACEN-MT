@echo off
cd /d "%~dp0"
title LACEN MT — Relatorio CIEVS 2x/semana
echo.
echo === LACEN-MT / CIEVS / Vigidesastres — Relatorio 2x/semana ===
echo Dados: saida_pipeline  ^|  Credenciais: .env (ver .env.example)
echo Agenda sugerida: terca e sexta
echo.
if not exist ".venv\Scripts\python.exe" (
  echo ERRO: .venv nao encontrado. Crie com: python -m venv .venv
  exit /b 1
)
REM Sem args: dry-run. Passe --email --telegram --to ... para envio real.
if "%~1"=="" (
  ".venv\Scripts\python.exe" scripts\enviar_relatorio_cievs.py --dry-run
) else (
  ".venv\Scripts\python.exe" scripts\enviar_relatorio_cievs.py %*
)
echo.
pause

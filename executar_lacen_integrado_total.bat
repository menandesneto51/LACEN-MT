@echo off
cd /d "%~dp0"
python -m pip install -r "requirements_lacen_integrado_total.txt"

python "lacen_builder_integrado_total.py" ^
  --raw "LACEN 2010 a 2026.csv" ^
  --outdir ".\saida_pipeline" ^
  --pipeline-script "lacen_analysis_pipeline.py" ^
  --geo-social "geo_social.csv" ^
  --climate "historico_clima_10_anos.csv" ^
  --municipios "Municipios MT lat long.csv" ^
  --pea "Populacao_economicamente_ativa.csv" ^
  --sim "SIM 2010 a 2025.csv" ^
  --sinan "SINAN 2010 a 2025.csv" ^
  --cnes-estab "CNES_ESTABELECIMENTOS.csv" ^
  --cnes-leitos "CNES_LEITOS.csv" ^
  --cnes-equip "CNES EQUIPAMENTOS .csv" ^
  --cnes-equipes "CNES_EQUIPESATENCAOBASICA.csv" ^
  --chunk-size 10000

IF ERRORLEVEL 1 (
  echo.
  echo O builder integrado falhou. Corrija o erro acima e rode novamente.
  pause
  exit /b 1
)

python -m streamlit run "lacen_dashboard_integrado_total.py"
pause

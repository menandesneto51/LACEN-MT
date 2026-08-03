@echo off
cd /d "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\lacen TATI"
python lacen_analysis_pipeline_completo_corrigido.py --inputs "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\LACEN 2010 a 2026.csv" --outdir "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\lacen TATI\saida_pipeline" --start-year 2010 --chunk-size 10000
pause

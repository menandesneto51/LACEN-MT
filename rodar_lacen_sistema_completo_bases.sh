#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SISTEMA COMPLETO LACEN-MT - versao Git Bash/WSL/Linux
# 1) Constrói bases LACEN/GAL
# 2) Integra SINAN, SIM, CNES, clima, população e geossocial
# 3) Recalcula integração final
# 4) Abre dashboard Streamlit
# ============================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

OUTDIR="saida_pipeline"
LOGDIR="logs"
mkdir -p "$OUTDIR" "$LOGDIR"

RUNSTAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGDIR/lacen_sistema_completo_${RUNSTAMP}.log"

PYTHON="${PYTHON:-python}"

RAW_LACEN="LACEN 2010 a 2026.csv"
SINAN="SINAN 2010 a 2025.csv"
SIM="SIM 2010 a 2025.csv"
CNES_ESTAB="CNES_ESTABELECIMENTOS.csv"
CNES_LEITOS="CNES_LEITOS.csv"
CNES_EQUIP="CNES EQUIPAMENTOS .csv"
CNES_EQUIP_ALT="CNES_EQUIPAMENTOS.csv"
CNES_EQUIPES="CNES_EQUIPESATENCAOBASICA.csv"
GEO_SOCIAL="geo_social.csv"
CLIMATE="historico_clima_10_anos.csv"
MUNICIPIOS="Municipios MT lat long.csv"
PEA="Populacao_economicamente_ativa.csv"

PIPELINE_SCRIPT="lacen_analysis_pipeline_completo_corrigido.py"
[[ -f "$PIPELINE_SCRIPT" ]] || [[ ! -f "lacen_analysis_pipeline_completo_corrigido(1).py" ]] || PIPELINE_SCRIPT="lacen_analysis_pipeline_completo_corrigido(1).py"
[[ -f "$PIPELINE_SCRIPT" ]] || [[ ! -f "lacen_analysis_pipeline.py" ]] || PIPELINE_SCRIPT="lacen_analysis_pipeline.py"

BUILDER_SCRIPT="lacen_builder_integrado_total.py"
[[ -f "$BUILDER_SCRIPT" ]] || [[ ! -f "lacen_builder_integrado_total(18).py" ]] || BUILDER_SCRIPT="lacen_builder_integrado_total(18).py"

FINAL_SCRIPT="lacen_integracao_final_only.py"
[[ -f "$FINAL_SCRIPT" ]] || [[ ! -f "lacen_integracao_final_only(2).py" ]] || FINAL_SCRIPT="lacen_integracao_final_only(2).py"

DASH_SCRIPT="lacen_dashboard_integrado_total.py"
[[ -f "$DASH_SCRIPT" ]] || [[ ! -f "lacen_dashboard_integrado_total_corrigido.py" ]] || DASH_SCRIPT="lacen_dashboard_integrado_total_corrigido.py"

[[ -f "$CNES_EQUIP" ]] || [[ ! -f "$CNES_EQUIP_ALT" ]] || CNES_EQUIP="$CNES_EQUIP_ALT"

START_YEAR=2010
PIPELINE_CHUNK_SIZE=50000
BUILDER_CHUNK_SIZE=10000
MUNICIPALITY_SOURCE="residencia"

check_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "[FALTA] $f"
    return 1
  fi
  echo "[OK]    $f"
}

check_inputs() {
  echo "[CHECK] Arquivos de entrada"
  local missing=0
  for f in \
    "$PIPELINE_SCRIPT" "$BUILDER_SCRIPT" "$FINAL_SCRIPT" "$DASH_SCRIPT" \
    "$RAW_LACEN" "$SINAN" "$SIM" "$CNES_ESTAB" "$CNES_LEITOS" "$CNES_EQUIP" "$CNES_EQUIPES" \
    "$GEO_SOCIAL" "$CLIMATE" "$MUNICIPIOS" "$PEA"; do
    check_file "$f" || missing=1
  done
  [[ "$missing" -eq 0 ]]
}

install_deps() {
  echo "[DEPENDENCIAS] Instalando/atualizando pacotes..."
  "$PYTHON" -m pip install --upgrade pip >> "$LOG" 2>&1
  "$PYTHON" -m pip install --upgrade pandas numpy openpyxl pyarrow streamlit plotly scipy scikit-learn statsmodels >> "$LOG" 2>&1
  echo "[OK] Dependencias instaladas/atualizadas."
}

run_pipeline() {
  echo "[1/3] Pipeline geral LACEN/GAL"
  {
    echo "===== $(date) - PIPELINE GERAL LACEN/GAL ====="
    "$PYTHON" "$PIPELINE_SCRIPT" \
      --inputs "$RAW_LACEN" \
      --outdir "$OUTDIR" \
      --start-year "$START_YEAR" \
      --chunk-size "$PIPELINE_CHUNK_SIZE" \
      --municipality-source "$MUNICIPALITY_SOURCE" \
      --log-level INFO
  } >> "$LOG" 2>&1
  echo "[OK] Pipeline geral concluido."
}

run_builder() {
  echo "[2/3] Builder integrado"
  {
    echo "===== $(date) - BUILDER INTEGRADO ====="
    "$PYTHON" "$BUILDER_SCRIPT" \
      --raw "$RAW_LACEN" \
      --outdir "$OUTDIR" \
      --pipeline-script "$PIPELINE_SCRIPT" \
      --geo-social "$GEO_SOCIAL" \
      --climate "$CLIMATE" \
      --municipios "$MUNICIPIOS" \
      --pea "$PEA" \
      --sim "$SIM" \
      --sinan "$SINAN" \
      --cnes-estab "$CNES_ESTAB" \
      --cnes-leitos "$CNES_LEITOS" \
      --cnes-equip "$CNES_EQUIP" \
      --cnes-equipes "$CNES_EQUIPES" \
      --chunk-size "$BUILDER_CHUNK_SIZE" \
      --municipality-source "$MUNICIPALITY_SOURCE"
  } >> "$LOG" 2>&1
  echo "[OK] Builder integrado concluido."
}

run_final() {
  echo "[3/3] Integracao final"
  {
    echo "===== $(date) - INTEGRACAO FINAL ====="
    "$PYTHON" "$FINAL_SCRIPT" --outdir "$OUTDIR"
  } >> "$LOG" 2>&1
  echo "[OK] Integracao final concluida."
}

run_dash() {
  echo "[DASHBOARD] Abrindo Streamlit..."
  "$PYTHON" -m streamlit run "$DASH_SCRIPT"
}

case "${1:-menu}" in
  install)
    install_deps
    ;;
  bases)
    check_inputs
    run_pipeline
    run_builder
    ;;
  final)
    run_final
    ;;
  dash)
    run_dash
    ;;
  completo|full)
    check_inputs
    run_pipeline
    run_builder
    run_final
    run_dash
    ;;
  *)
    cat <<EOF
Uso:
  bash rodar_lacen_sistema_completo_bases.sh install    # instala dependencias
  bash rodar_lacen_sistema_completo_bases.sh bases      # pipeline + builder integrado
  bash rodar_lacen_sistema_completo_bases.sh final      # integracao final
  bash rodar_lacen_sistema_completo_bases.sh dash       # abre dashboard
  bash rodar_lacen_sistema_completo_bases.sh completo   # bases + final + dashboard

Log:
  $LOG
EOF
    ;;
esac

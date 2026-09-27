param(
  [string]$OutDir = "saida_pipeline",
  [int]$WeeksBack = 60,
  [int]$MicroDays = 120
)

$ErrorActionPreference = "Stop"

Write-Host "LACEN-MT V2.1 — coleta de evidências DEC-001/DEC-002"
Write-Host "Nenhum ML, mirror ou envio CIEVS será executado."

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$etlArgs = @(
  "-m", "etl.run_etl_dw",
  "--outdir", $OutDir,
  "--weeks-back", "$WeeksBack",
  "--micro-days", "$MicroDays",
  "--evidence-only",
  "--skip-ml",
  "--skip-cievs",
  "--no-bulk"
)

& $python @etlArgs
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0 -and $exitCode -ne 3) {
  throw "ETL de evidências falhou com código $exitCode."
}

$quality = Join-Path $OutDir "quality"
$required = @(
  "gal_temporal_anchor_summary.json",
  "gal_temporal_anchor_weekly_comparison.csv",
  "population_source_comparison_summary.json",
  "population_source_coverage_detail.csv",
  "population_source_pairwise_comparison.csv",
  "decision_brief_DEC-001.md",
  "decision_brief_DEC-002.md",
  "decision_readiness_v2_1.json",
  "decision_status_registry_v2_1.json"
)

Write-Host ""
Write-Host "Artefatos de decisão:"
foreach ($name in $required) {
  $path = Join-Path $quality $name
  if (Test-Path $path) {
    Write-Host "[OK] $path"
  } else {
    Write-Host "[PENDENTE] $path"
  }
}

$readinessPath = Join-Path $quality "decision_readiness_v2_1.json"
if (Test-Path $readinessPath) {
  Write-Host ""
  Write-Host "Decision Readiness:"
  Get-Content $readinessPath -Raw
}

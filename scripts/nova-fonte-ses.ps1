param(
    [Parameter(Mandatory = $true)][string]$Query,
    [string]$Context = "LACEN-MT",
    [string]$CatalogRoot = $env:SES_DATA_CATALOG_ROOT,
    [string]$AgentRoot = $env:SES_DATA_CATALOG_AGENT_ROOT
)
$ErrorActionPreference = "Stop"
if (-not $AgentRoot) { throw "Defina SES_DATA_CATALOG_AGENT_ROOT para o clone canônico do vigia-vsr." }
$reviewScript = Join-Path $AgentRoot "agents\ses_data_catalog\new_source_review.py"
if (-not (Test-Path $reviewScript)) { throw "New Source Review Pack não encontrado em: $reviewScript" }
$argsList = @($reviewScript, $Query, "--context", $Context)
if ($CatalogRoot) { $argsList += @("--catalog-root", $CatalogRoot) }
python @argsList
exit $LASTEXITCODE
